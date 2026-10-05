"""Snowflake adapter — the #1 cloud warehouse (~35% market share).

Snowflake exposes a plan without running the query:

    EXPLAIN USING JSON <sql>   -> a GlobalStats + Operations tree

The cost signals we read from the JSON:
  - GlobalStats.bytesAssigned / partitionsAssigned vs partitionsTotal
    -> how much of the table the query must read (pruning effectiveness)
  - an operation with "TableScan" and no pruning -> full micro-partition scan
  - a "CartesianJoin" operation -> the warehouse join blow-up

Snowflake bills by WAREHOUSE TIME (credits), and bytes/partitions scanned is the
best pre-execution proxy for how much work (and credit burn) a query will cost.

Honesty rail: EXPLAIN only, never run. Not yet verified against a live Snowflake
account (verified_live=False).
"""
from __future__ import annotations

import json
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

_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_HAS_WHERE = re.compile(r"\bwhere\b", re.I)


class SnowflakeAdapter:
    name = "snowflake"
    label = "Snowflake (cloud warehouse)"
    verified_live = False

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        raw = run_sql(f"EXPLAIN USING JSON {query}")
        doc = raw[0] if isinstance(raw, (list, tuple)) else raw
        if isinstance(doc, (bytes, str)):
            doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        # Snowflake wraps the plan under "GlobalStats" + "Operations"
        gstats = doc.get("GlobalStats", {})
        ops_tree = doc.get("Operations", [])

        nodes: list[dict] = []

        def _walk(ops):
            for op in ops:
                if isinstance(op, list):
                    _walk(op)
                    continue
                if not isinstance(op, dict):
                    continue
                nodes.append({
                    "Node Type": op.get("Operation", "?"),
                    "Relation Name": (op.get("Objects") or [None])[0]
                        if isinstance(op.get("Objects"), list) else op.get("Objects"),
                    "Plan Rows": 0,
                    "Total Cost": 0.0,
                    "_op": op.get("Operation", ""),
                })
                if op.get("children"):
                    _walk(op["children"])

        _walk(ops_tree if isinstance(ops_tree, list) else [ops_tree])

        p_assigned = int(gstats.get("partitionsAssigned", 0) or 0)
        p_total = int(gstats.get("partitionsTotal", 0) or 0)
        bytes_assigned = int(gstats.get("bytesAssigned", 0) or 0)
        metrics = EngineMetrics(
            rows_scanned=p_assigned, rows_returned=0, total_cost=float(bytes_assigned),
            cost_is_unitless=True,
            strategy=[n["Node Type"] for n in nodes if n["Node Type"]],
        )
        pr = PlanResult(raw=doc, nodes=nodes, metrics=metrics, has_live_stats=True)
        pr._p_assigned = p_assigned      # type: ignore[attr-defined]
        pr._p_total = p_total            # type: ignore[attr-defined]
        pr._bytes = bytes_assigned       # type: ignore[attr-defined]
        return pr

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        p_assigned = getattr(plan, "_p_assigned", 0)
        p_total = getattr(plan, "_p_total", 0)
        ops = {n.get("_op", "") for n in plan.nodes}

        if _SELECT_STAR.search(query):
            flags.append(EngineFlag(
                "SNOWFLAKE_SELECT_STAR",
                "SELECT * reads every column from the micro-partitions. Snowflake "
                "is columnar — projecting only needed columns cuts the bytes "
                "scanned and the credits burned.",
                "high",
            ))
        # poor pruning: assigned ≈ total partitions means almost no pruning happened
        if p_total and p_assigned and (p_assigned / p_total) > 0.8:
            flags.append(EngineFlag(
                "SNOWFLAKE_POOR_PRUNING",
                f"The query must read {p_assigned}/{p_total} micro-partitions "
                f"(~{p_assigned / p_total:.0%}) — almost no pruning. Filter on a "
                f"clustered column so Snowflake prunes partitions and burns fewer "
                f"credits.",
                "high",
            ))
        if any("Cartesian" in o for o in ops):
            flags.append(EngineFlag(
                "SNOWFLAKE_CARTESIAN_JOIN",
                "CartesianJoin — two inputs are joined with no join condition, "
                "producing every N×M pairing. Add the join predicate.",
                "high",
            ))
        if not _HAS_WHERE.search(query):
            flags.append(EngineFlag(
                "SNOWFLAKE_NO_FILTER",
                "No WHERE filter — Snowflake cannot prune micro-partitions and "
                "scans the whole table. Filter on a clustered column.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        op = node.get("_op", "")
        rel = node.get("Relation Name")
        if op == "TableScan":
            return f"scans micro-partitions of {rel or 'the table'}"
        if "Join" in op:
            return f"{op} — combines two inputs"
        if op == "Aggregate":
            return "aggregates rows into groups"
        if op == "Sort":
            return "sorts the result set"
        if op == "Result":
            return "returns the final rows"
        return op or "operation"

    def headline(self, plan: PlanResult) -> str:
        p_assigned = getattr(plan, "_p_assigned", 0)
        p_total = getattr(plan, "_p_total", 0)
        if p_total and p_assigned and (p_assigned / p_total) > 0.8:
            return (f"This query reads {p_assigned} of {p_total} micro-partitions "
                    f"(~{p_assigned / p_total:.0%}) — Snowflake is barely pruning, "
                    f"so it burns warehouse credits scanning almost the whole "
                    f"table. Filter on a clustered column to prune.")
        if p_total:
            return (f"Good — Snowflake prunes to {p_assigned} of {p_total} "
                    f"micro-partitions, scanning only the data it needs.")
        return "Snowflake plan read from EXPLAIN USING JSON."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from INFORMATION_SCHEMA.COLUMNS (READ-ONLY)."""
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, (list, tuple)) else doc
            if isinstance(doc, (bytes, str)):
                doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the Snowflake schema ({type(e).__name__}). "
                    "Provide a read-only role with USAGE on the database/schema, or "
                    "paste your CREATE TABLE DDL."
                ),
            )
        tables = []
        for t in doc.get("tables", []):
            tables.append(SchemaTable(
                name=t.get("name", "?"),
                columns=[{"name": c.get("name"), "type": c.get("type")}
                         for c in t.get("columns", [])],
                indexes=[],
                row_count=t.get("row_count"),
                caveats=["Snowflake has no indexes — pruning is by micro-partition "
                         f"and clustering key: {t.get('clustering_key') or 'none'}."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="LIVE",
            notes=["Cost lever is micro-partition pruning / clustering, not indexes."],
        )


assert isinstance(SnowflakeAdapter(), Adapter)
