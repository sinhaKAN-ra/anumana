"""ClickHouse adapter — the open-source OLAP engine of choice for real-time
analytics at scale.

ClickHouse exposes multiple EXPLAIN modes without running the query. The one
with a cost signal is:

    EXPLAIN ESTIMATE <sql>   -> per-table (database, table, parts, rows, marks)

`rows` and `marks` are what a query will READ. A query that reads most of the
table's rows/marks (no primary-key / partition pruning) is the expensive OLAP
pattern. `EXPLAIN PLAN` (operator tree) is also available for the physical shape.

Honesty rail: EXPLAIN only, never run. Not yet verified against a live
ClickHouse server (verified_live=False).
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


class ClickHouseAdapter:
    name = "clickhouse"
    label = "ClickHouse (OLAP)"
    verified_live = False

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        # EXPLAIN ESTIMATE returns rows of (database, table, parts, rows, marks).
        raw = run_sql(f"EXPLAIN ESTIMATE {query}")
        rows_data = raw
        if isinstance(raw, (bytes, str)):
            rows_data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)

        nodes: list[dict] = []
        total_rows = 0
        total_marks = 0
        for r in rows_data:
            if isinstance(r, dict):
                db, tbl = r.get("database"), r.get("table")
                parts = int(r.get("parts", 0) or 0)
                rrows = int(r.get("rows", 0) or 0)
                marks = int(r.get("marks", 0) or 0)
            elif isinstance(r, (list, tuple)) and len(r) >= 5:
                db, tbl, parts, rrows, marks = r[0], r[1], int(r[2]), int(r[3]), int(r[4])
            else:
                continue
            total_rows += rrows
            total_marks += marks
            nodes.append({
                "Node Type": "Table read (estimate)",
                "Relation Name": tbl,
                "Plan Rows": rrows,
                "Total Cost": float(marks),   # marks ≈ the unit of IO work
                "_parts": parts,
                "_marks": marks,
                "_db": db,
            })
        metrics = EngineMetrics(
            rows_scanned=total_rows, rows_returned=total_rows,
            total_cost=float(total_marks), cost_is_unitless=True,
            strategy=[f"{n['Relation Name']}: {n['Plan Rows']:,} rows / "
                      f"{n['_marks']} marks / {n['_parts']} parts" for n in nodes],
        )
        return PlanResult(raw=rows_data, nodes=nodes, metrics=metrics, has_live_stats=True)

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        total_rows = sum(n.get("Plan Rows", 0) for n in plan.nodes)

        if _SELECT_STAR.search(query):
            flags.append(EngineFlag(
                "CLICKHOUSE_SELECT_STAR",
                "SELECT * on a columnar store reads every column's data — "
                "ClickHouse is column-oriented, so projecting only needed columns "
                "is the primary IO saving.",
                "high",
            ))
        if total_rows and total_rows > 1_000_000:
            flags.append(EngineFlag(
                "CLICKHOUSE_LARGE_SCAN",
                f"EXPLAIN ESTIMATE says this reads ~{total_rows:,} rows — the query "
                f"isn't pruning by the primary key / partition. Filter on the "
                f"table's ORDER BY / PARTITION BY columns so ClickHouse skips "
                f"granules.",
                "high",
            ))
        if not _HAS_WHERE.search(query):
            flags.append(EngineFlag(
                "CLICKHOUSE_NO_PK_FILTER",
                "No WHERE filter — ClickHouse can't skip any granules and reads the "
                "whole table. Filter on the primary-key prefix columns.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        return (f"reads ~{node.get('Plan Rows', 0):,} rows across "
                f"{node.get('_parts', 0)} parts ({node.get('_marks', 0)} marks) "
                f"from {node.get('Relation Name', 'the table')}")

    def headline(self, plan: PlanResult) -> str:
        total_rows = sum(n.get("Plan Rows", 0) for n in plan.nodes)
        if total_rows and total_rows > 1_000_000:
            return (f"ClickHouse will read ~{total_rows:,} rows because the filter "
                    f"doesn't match the primary-key / partition order — it can't "
                    f"skip granules. Filter on the ORDER BY columns to prune.")
        if total_rows:
            return (f"Good — ClickHouse prunes to ~{total_rows:,} rows using the "
                    f"primary key / partition, instead of scanning the whole table.")
        return "ClickHouse plan read from EXPLAIN ESTIMATE (rows/marks to be read)."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from system.columns / system.tables (READ-ONLY)."""
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, (list, tuple)) else doc
            if isinstance(doc, (bytes, str)):
                doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the ClickHouse schema ({type(e).__name__}). "
                    "Provide a read-only user with access to system.columns, or "
                    "paste your CREATE TABLE (with ENGINE/ORDER BY)."
                ),
            )
        tables = []
        for t in doc.get("tables", []):
            tables.append(SchemaTable(
                name=t.get("name", "?"),
                columns=[{"name": c.get("name"), "type": c.get("type")}
                         for c in t.get("columns", [])],
                indexes=[],
                row_count=t.get("total_rows"),
                caveats=["ClickHouse has no secondary indexes by default — the "
                         f"ORDER BY key is the index. Sorting key: "
                         f"{t.get('sorting_key') or 'unknown'}."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="LIVE",
            notes=["Cost lever is primary-key (ORDER BY) and partition pruning, "
                   "not secondary indexes."],
        )


assert isinstance(ClickHouseAdapter(), Adapter)
