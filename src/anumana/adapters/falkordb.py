"""FalkorDB adapter — cost diagnosis for the Cypher queries agents write against
a graph database.

FalkorDB is a Redis-module graph DB (OpenCypher) and a fast-growing target for
agent/RAG workloads (GraphRAG). Like SQL EXPLAIN and Mongo queryPlanner, it
exposes a plan WITHOUT running the query:

    GRAPH.EXPLAIN <graph> "<cypher>"     -> the operation plan (no execution)
    GRAPH.PROFILE <graph> "<cypher>"     -> same plan WITH real counts (RUNS it)

Honesty rail: we use GRAPH.EXPLAIN only — never PROFILE — so preflight never
executes the user's query. EXPLAIN returns the operation tree as lines of text
(e.g. "Node By Label Scan | (p:Person)", "All Node Scan | (n)", "Conditional
Traverse", "Cartesian Product"), NOT row estimates. So FalkorDB preflight is
HEURISTIC on cost, like Mongo: it reads the ACCESS PATTERN (label/index scan vs
full scan, cartesian blow-ups, unbounded var-length traversals), which is what
actually determines whether a graph query is cheap, and says plainly it has no
live row counts.

The `run_sql` callable here is really `run_explain(cypher) -> list[str]`:
server.py wires it to the FalkorDB client's `graph.explain(cypher)` (redis
`GRAPH.EXPLAIN`). The engine-agnostic risk/English/rewrite layers are unchanged
— this file only teaches Anumana how to READ FalkorDB's cost signal.
"""
from __future__ import annotations

import re
from typing import Callable

from anumana.adapters.base import (
    Adapter,
    EngineFlag,
    EngineMetrics,
    PlanResult,
    SchemaDescription,
    SchemaTable,
)

# ── plan-line classification ────────────────────────────────────────────────
# FalkorDB GRAPH.EXPLAIN emits one operation per line, indented by depth. The
# operation name is the text before the first '|'. We match on the operation.
_FULL_SCAN_OPS = ("All Node Scan", "All Relationship Scan")
_INDEXED_SCAN_OPS = ("Node By Index Scan", "Node By Label Scan", "Index Scan")
_CARTESIAN_OP = "Cartesian Product"
_TRAVERSE_OPS = ("Conditional Traverse", "Expand Into", "Conditional Variable Length Traverse")

# a var-length relationship with no upper bound: -[:REL*]-> or -[:REL*2..]->
_UNBOUNDED_VARLEN = re.compile(r"\[\s*[^\]]*\*\s*\d*\s*\.\.\s*\]|\[\s*[^\]]*\*\s*\]")
# a Cypher query with no LIMIT clause
_HAS_LIMIT = re.compile(r"\bLIMIT\b", re.I)
# RETURN * (graph "SELECT *": returns every bound variable, whole nodes/rels)
_RETURN_STAR = re.compile(r"\bRETURN\s+\*", re.I)


def _op_name(line: str) -> str:
    """The operation name is the text before the first '|', trimmed of indent."""
    head = line.split("|", 1)[0]
    return head.strip()


def _op_detail(line: str) -> str:
    """Everything after the first '|' — the operand, e.g. '(p:Person)'."""
    parts = line.split("|", 1)
    return parts[1].strip() if len(parts) > 1 else ""


class FalkorDBAdapter:
    name = "falkordb"
    label = "FalkorDB (graph / Cypher)"
    verified_live = False  # offline-verified; no live FalkorDB instance tested

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        # run_sql returns GRAPH.EXPLAIN output: a list of plan lines (strings).
        raw = run_sql(query)
        if isinstance(raw, str):
            lines = raw.splitlines()
        elif isinstance(raw, (list, tuple)):
            # client may return list[str] or list[bytes]
            lines = [l.decode() if isinstance(l, bytes) else str(l) for l in raw]
        else:
            lines = [str(raw)]
        lines = [l for l in lines if l.strip()]

        nodes: list[dict] = []
        for line in lines:
            op = _op_name(line)
            nodes.append({
                "Node Type": op,
                "Relation Name": _op_detail(line) or None,
                "Plan Rows": 0,          # GRAPH.EXPLAIN has NO row estimate
                "Total Cost": 0.0,
                "_falkor_op": op,
                "_detail": _op_detail(line),
            })
        strategy = [
            n["Node Type"] + (f" {n['_detail']}" if n.get("_detail") else "")
            for n in nodes
        ]
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=0.0,
            cost_is_unitless=True, strategy=strategy,
        )
        return PlanResult(raw=lines, nodes=nodes, metrics=metrics, has_live_stats=False)

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        ops = [n.get("_falkor_op", "") for n in plan.nodes]

        # Full graph scan — the graph equivalent of a Seq Scan / COLLSCAN.
        if any(op in _FULL_SCAN_OPS for op in ops):
            flags.append(EngineFlag(
                "FALKOR_FULL_SCAN",
                "All Node/Relationship Scan — the query visits every node (or "
                "relationship) in the graph because no label or index narrows the "
                "start set. Match on a label and index the start property: "
                "CREATE INDEX FOR (n:Label) ON (n.prop).",
                "high",
            ))

        # Cartesian product — disconnected MATCH patterns multiply row sets.
        if any(op == _CARTESIAN_OP for op in ops):
            flags.append(EngineFlag(
                "FALKOR_CARTESIAN_PRODUCT",
                "Cartesian Product — two MATCH patterns aren't connected by a "
                "relationship, so every combination is produced (N×M blow-up). "
                "Connect the patterns with a relationship, or split into separate "
                "queries.",
                "high",
            ))

        # Unbounded variable-length traversal — -[:REL*]-> with no upper bound.
        if _UNBOUNDED_VARLEN.search(query):
            flags.append(EngineFlag(
                "FALKOR_UNBOUNDED_VARLEN",
                "Unbounded variable-length traversal (e.g. -[:REL*]->) — with no "
                "upper hop bound this can walk the whole graph and explode "
                "combinatorially on cycles. Cap the depth: -[:REL*1..3]->.",
                "high",
            ))

        # RETURN * — hands back every bound variable (whole nodes/rels).
        if _RETURN_STAR.search(query):
            flags.append(EngineFlag(
                "FALKOR_RETURN_STAR",
                "RETURN * returns every bound variable (full nodes and "
                "relationships). Return only the properties you use: "
                "RETURN p.name, p.email.",
                "medium",
            ))

        # No LIMIT — unbounded result set.
        if not _HAS_LIMIT.search(query):
            flags.append(EngineFlag(
                "FALKOR_UNBOUNDED_RESULT",
                "No LIMIT — the result set is unbounded and can flood the caller. "
                "Add LIMIT n unless you truly need every path.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        op = node.get("_falkor_op", "")
        detail = node.get("_detail", "")
        if op in _FULL_SCAN_OPS:
            return "scans every node/relationship in the graph — no label or index narrows the start set"
        if op in _INDEXED_SCAN_OPS:
            return f"starts from an index/label {detail} instead of scanning the whole graph".strip()
        if op == _CARTESIAN_OP:
            return "combines two unconnected patterns — produces every N×M pairing"
        if op in _TRAVERSE_OPS:
            return f"walks relationships {detail} to expand the matched pattern".strip()
        if op == "Filter":
            return "drops rows that fail the WHERE predicate"
        if op == "Project" or op == "Aggregate":
            return "computes the returned columns / aggregates"
        if op == "Sort":
            return "orders the result set (in memory)"
        if op == "Limit":
            return "stops after the requested number of rows"
        if op == "Results":
            return "returns the final rows to the caller"
        return f"{op} operation" if op else "plan operation"

    def headline(self, plan: PlanResult) -> str:
        ops = [n.get("_falkor_op", "") for n in plan.nodes]
        if any(op == _CARTESIAN_OP for op in ops):
            return ("This query builds a CARTESIAN PRODUCT of two unconnected "
                    "patterns — the row count is N×M and grows explosively. "
                    "Connect the patterns with a relationship.")
        if any(op in _FULL_SCAN_OPS for op in ops):
            return ("This query scans EVERY node/relationship in the graph (full "
                    "scan) because no label or index narrows the start set — it "
                    "gets linearly slower as the graph grows. Match on a label and "
                    "index the start property.")
        if any(op in _INDEXED_SCAN_OPS for op in ops):
            return ("Good — the query starts from an index/label scan and traverses "
                    "from there, instead of scanning the whole graph.")
        return "FalkorDB plan read from GRAPH.EXPLAIN (access pattern only; no live counts)."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Graph schema from FalkorDB's own procedures: db.labels(),
        db.relationshipTypes(), db.indexes(). run_sql here is wired to return
        {"labels": [...], "rel_types": [...], "indexes": [...]} — a graph has no
        fixed per-label property schema, so properties are left empty with a
        caveat (honesty rail)."""
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, list) else doc
            if isinstance(doc, (bytes, str)):
                import json
                doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the FalkorDB graph schema ({type(e).__name__}). "
                    "Provide a read-only connection URL and the graph name, or tell "
                    "me the node labels and the relationship types you traverse."
                ),
            )
        tables: list[SchemaTable] = []
        indexes_by_label: dict[str, list] = {}
        for ix in doc.get("indexes", []):
            lbl = ix.get("label") or ix.get("entity") or "?"
            indexes_by_label.setdefault(lbl, []).append({
                "name": f"{lbl}.{','.join(ix.get('properties', []))}",
                "columns": ix.get("properties", []),
                "kind": ix.get("type", "graph-index"),
            })
        # one SchemaTable per node label; relationship types noted separately.
        for label in doc.get("labels", []):
            tables.append(SchemaTable(
                name=label,
                columns=[],  # graph nodes have no fixed property schema
                indexes=indexes_by_label.get(label, []),
                row_count=None,
                caveats=["Graph node label — properties vary per node (no fixed "
                         "schema). Indexed properties are listed under indexes."],
            ))
        rel_types = doc.get("rel_types", [])
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="SAMPLED",
            notes=[
                "Node labels from db.labels(); indexes from db.indexes().",
                f"Relationship types: {', '.join(rel_types) if rel_types else '(none reported)'}.",
                "A property graph has no fixed per-label schema — only indexed "
                "properties are known without sampling nodes.",
            ],
        )


assert isinstance(FalkorDBAdapter(), Adapter)
