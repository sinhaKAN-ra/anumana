"""Cassandra / ScyllaDB adapter — wide-column NoSQL, the paradigm no other
Anumana adapter covered.

CRITICAL honesty note: Cassandra has NO query planner and NO EXPLAIN. You cannot
ask it "what would this cost" — it either serves a query efficiently (the
partition key is specified) or it does a cluster-wide scan (and usually refuses
without ALLOW FILTERING). So, exactly like the DynamoDB adapter, this is
RULE-BASED on the query SHAPE, not a plan — and it says so (has_live_stats=False,
rows/cost = 0). What it reads is the thing that actually determines Cassandra
cost: does the query hit a single partition, or does it fan out across the ring?

The real cost rules in Cassandra:
  - no partition key in WHERE        -> cluster-wide scan (catastrophic at scale)
  - ALLOW FILTERING present          -> you've told Cassandra to scan+filter
  - secondary index on high-cardinality column -> scatter-gather across nodes
  - IN () on the partition key with many values -> multi-partition fan-out

run_sql is NOT used for a plan (there's none); server.py may pass a schema doc
for describe_schema. The engine-agnostic risk/English layers still work because
flags + a rule-based headline are all they need.

Not yet verified against a live Cassandra cluster (verified_live=False).
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

_ALLOW_FILTERING = re.compile(r"\ballow\s+filtering\b", re.I)
_HAS_WHERE = re.compile(r"\bwhere\b", re.I)
_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_IN_CLAUSE = re.compile(r"\bin\s*\(", re.I)
# a WHERE term like "col = ?" — we extract filtered column names to compare
# against the known partition key (passed via the query_meta the server supplies)
_WHERE_COLS = re.compile(r"where\s+(.*?)(?:\ballow\s+filtering\b|\border\s+by\b|\blimit\b|$)", re.I | re.S)
_COL_EQ = re.compile(r"(\w+)\s*(?:=|>=|<=|>|<|\bin\b)", re.I)


class CassandraAdapter:
    name = "cassandra"
    label = "Cassandra / ScyllaDB (wide-column)"
    verified_live = False

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        """Cassandra has no plan. We build a synthetic single-node 'shape' result
        so the engine-agnostic layers have something to walk; the real signal is
        in detect_flags. partition-key awareness comes from an optional meta doc
        the server passes as the FIRST run_sql result (or {} if unavailable)."""
        meta = {}
        try:
            raw = run_sql("__anumana_cql_meta__")
            m = raw[0] if isinstance(raw, (list, tuple)) else raw
            if isinstance(m, (bytes, str)):
                m = json.loads(m.decode() if isinstance(m, bytes) else m)
            if isinstance(m, dict):
                meta = m
        except Exception:
            meta = {}

        partition_keys = {k.lower() for k in meta.get("partition_key", [])}
        filtered = _filtered_columns(query)
        hits_partition = bool(partition_keys & filtered) if partition_keys else None

        node = {
            "Node Type": "Partition read" if hits_partition else "Cluster scan",
            "Relation Name": meta.get("table"),
            "Plan Rows": 0,
            "Total Cost": 0.0,
            "_hits_partition": hits_partition,
            "_partition_keys": sorted(partition_keys),
            "_filtered": sorted(filtered),
        }
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=0.0, cost_is_unitless=True,
            strategy=[node["Node Type"]],
        )
        pr = PlanResult(raw=meta, nodes=[node], metrics=metrics, has_live_stats=False)
        pr._hits_partition = hits_partition  # type: ignore[attr-defined]
        return pr

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        hits_partition = getattr(plan, "_hits_partition", None)

        if _ALLOW_FILTERING.search(query):
            flags.append(EngineFlag(
                "CASSANDRA_ALLOW_FILTERING",
                "ALLOW FILTERING — you've told Cassandra to read rows and filter "
                "them in memory, scanning across partitions. This is fine for a "
                "handful of rows but gets catastrophically slow as data grows. "
                "Redesign the table so the query hits a single partition.",
                "high",
            ))
        if hits_partition is False:
            flags.append(EngineFlag(
                "CASSANDRA_NO_PARTITION_KEY",
                "The WHERE clause doesn't restrict the PARTITION KEY, so this query "
                "must contact every node in the ring (a cluster-wide scan). In "
                "Cassandra you model the table around the query — add the partition "
                "key to WHERE, or create a table/materialized view keyed for it.",
                "high",
            ))
        elif hits_partition is None and _HAS_WHERE.search(query):
            flags.append(EngineFlag(
                "CASSANDRA_PARTITION_KEY_UNKNOWN",
                "Could not confirm the partition key is in WHERE (schema metadata "
                "unavailable). If it isn't, this becomes a cluster-wide scan — "
                "verify the partition key is restricted.",
                "medium",
            ))
        if _IN_CLAUSE.search(query) and hits_partition:
            flags.append(EngineFlag(
                "CASSANDRA_IN_ON_PARTITION",
                "IN (...) on the partition key fans out to one query per value "
                "across the ring; a few values are fine, many become a scatter-"
                "gather. Prefer separate async reads for large IN lists.",
                "medium",
            ))
        if not _HAS_LIMIT.search(query):
            flags.append(EngineFlag(
                "UNBOUNDED_RESULT",
                "No LIMIT — an unbounded CQL read can return very large partitions. "
                "Add LIMIT or paginate.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        if node.get("_hits_partition"):
            return (f"reads a single partition of {node.get('Relation Name', 'the table')} "
                    f"— the efficient Cassandra access path")
        if node.get("_hits_partition") is False:
            return "contacts every node in the ring — no partition key restricts the read"
        return "CQL read (partition-key restriction unverified — no planner in Cassandra)"

    def headline(self, plan: PlanResult) -> str:
        hp = getattr(plan, "_hits_partition", None)
        if hp is False:
            return ("This query doesn't restrict the PARTITION KEY, so Cassandra "
                    "must scan the WHOLE ring — the one access pattern Cassandra is "
                    "built to avoid. Model a table/view keyed for this query.")
        if hp:
            return ("Good — this query hits a single partition, which is exactly how "
                    "Cassandra is designed to be queried (no planner needed).")
        return ("Cassandra has no query planner — this is a RULE-BASED read of the "
                "query shape (partition key, ALLOW FILTERING), not a cost plan.")

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from system_schema.columns / tables (READ-ONLY). The crucial
        field is which columns are the PARTITION KEY vs clustering columns."""
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, (list, tuple)) else doc
            if isinstance(doc, (bytes, str)):
                doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the Cassandra schema ({type(e).__name__}). "
                    "Provide a read-only role, or tell me the table's PARTITION KEY "
                    "and clustering columns — that's what decides query cost."
                ),
            )
        tables = []
        for t in doc.get("tables", []):
            pk = t.get("partition_key", [])
            ck = t.get("clustering_key", [])
            tables.append(SchemaTable(
                name=t.get("name", "?"),
                columns=[{"name": c.get("name"), "type": c.get("type")}
                         for c in t.get("columns", [])],
                indexes=[{"name": "PARTITION KEY", "columns": pk, "kind": "partition"},
                         {"name": "CLUSTERING", "columns": ck, "kind": "clustering"}],
                row_count=None,
                caveats=["Cassandra cost is governed entirely by the PARTITION KEY "
                         f"({', '.join(pk) or '?'}) — a query must restrict it to "
                         "avoid a cluster-wide scan. Clustering columns: "
                         f"{', '.join(ck) or 'none'}."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="SAMPLED",
            notes=["Partition key / clustering columns from system_schema — these, "
                   "not indexes, decide whether a CQL query is cheap."],
        )


def _filtered_columns(query: str) -> set[str]:
    """Extract column names that appear in the WHERE clause (lowercased)."""
    m = _WHERE_COLS.search(query or "")
    if not m:
        return set()
    return {c.lower() for c in _COL_EQ.findall(m.group(1))}


assert isinstance(CassandraAdapter(), Adapter)
