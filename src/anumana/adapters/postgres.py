"""Postgres adapter — the original SQL EXPLAIN engine, now behind the Adapter
contract. The honest core is unchanged: run EXPLAIN (FORMAT JSON), NEVER
ANALYZE, read the planner's estimates, translate. No fake milliseconds.
"""
from __future__ import annotations

import re
from typing import Callable

from anumana.adapters.base import Adapter, EngineFlag, EngineMetrics, PlanResult

# ---- SQL-text flag patterns (shared with schema-only) -----------------------
_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_LEADING_WILDCARD = re.compile(r"like\s+'%", re.I)
_FUNC_ON_COL = re.compile(r"where[^=]*\b(lower|upper|date|cast)\s*\(", re.I)


def _walk(node: dict):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


class PostgresAdapter:
    name = "postgres"
    label = "Postgres"
    verified_live = True  # exercised end-to-end against a live Postgres this session

    # ---- plan ---------------------------------------------------------------
    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        rows = run_sql(f"EXPLAIN (FORMAT JSON, VERBOSE) {query}")
        doc = rows[0]
        plan = doc[next(iter(doc))] if isinstance(doc, dict) else doc
        if isinstance(plan, list):
            plan = plan[0]
        plan = plan["Plan"]
        nodes = list(_walk(plan))

        rows_scanned = max((n.get("Plan Rows", 0) for n in nodes), default=0)
        rows_returned = plan.get("Plan Rows", 0)
        total_cost = float(plan.get("Total Cost", 0.0))
        strategy = [
            n["Node Type"] + (f" on {n['Relation Name']}" if n.get("Relation Name") else "")
            for n in nodes if n.get("Node Type")
        ]
        metrics = EngineMetrics(
            rows_scanned=rows_scanned, rows_returned=rows_returned,
            total_cost=total_cost, cost_is_unitless=True, strategy=strategy,
        )
        return PlanResult(raw=plan, nodes=nodes, metrics=metrics, has_live_stats=True)

    # ---- flags --------------------------------------------------------------
    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        for n in plan.nodes:
            ntype = n.get("Node Type", "")
            est_rows = n.get("Plan Rows", 0)
            rel = n.get("Relation Name", "a table")
            if ntype == "Seq Scan" and est_rows and est_rows > 100_000:
                flags.append(EngineFlag(
                    "SEQ_SCAN_LARGE",
                    f"Seq Scan on {rel} over ~{est_rows:,} estimated rows — "
                    f"no usable index for the filter.",
                    "high",
                ))
            if ntype == "Nested Loop":
                outer = n.get("Plans", [{}])[0].get("Plan Rows", 0)
                if outer and outer > 10_000:
                    flags.append(EngineFlag(
                        "NESTED_LOOP_BLOWUP",
                        f"Nested Loop with a large outer side (~{outer:,} rows); "
                        f"may explode into millions of inner lookups.",
                        "high",
                    ))
        if _SELECT_STAR.search(query):
            flags.append(EngineFlag(
                "SELECT_STAR_WIDE",
                "SELECT * returns every column; project only what you use.",
                "medium",
            ))
        _raw_is_aggregate = (
            isinstance(plan.raw, dict) and plan.raw.get("Node Type") == "Aggregate"
        )
        if not _HAS_LIMIT.search(query) and not _raw_is_aggregate:
            flags.append(EngineFlag(
                "UNBOUNDED_RESULT",
                "No LIMIT — the result set is unbounded and can flood the caller.",
                "medium",
            ))
        if _LEADING_WILDCARD.search(query):
            flags.append(EngineFlag(
                "LEADING_WILDCARD_LIKE",
                "LIKE '%...' cannot use a btree index; forces a scan.",
                "medium",
            ))
        if _FUNC_ON_COL.search(query):
            flags.append(EngineFlag(
                "FUNCTION_ON_INDEXED_COL",
                "A function wraps the filtered column, which disables plain index "
                "use (consider an expression index).",
                "medium",
            ))
        return flags

    # ---- explain_working helpers -------------------------------------------
    def node_reason(self, node: dict) -> str:
        ntype = node.get("Node Type", "")
        rel = node.get("Relation Name")
        rows = node.get("Plan Rows", 0)
        if ntype == "Seq Scan":
            return (f"reads every row of {rel or 'the table'} (~{rows:,}) because no "
                    f"usable index matched the filter")
        if ntype == "Index Scan":
            return f"jumps straight to matching rows in {rel or 'the table'} via an index"
        if ntype == "Index Only Scan":
            return f"answers entirely from the index on {rel or 'the table'} — never touches the heap"
        if ntype == "Bitmap Heap Scan":
            return f"gathers matching row locations from a bitmap, then fetches them from {rel or 'the table'}"
        if ntype == "Nested Loop":
            return "for each outer row, probes the inner side — cheap only if the outer side is small"
        if ntype == "Hash Join":
            return "builds a hash of one side, then streams the other through it"
        if ntype == "Sort":
            return "materialises and sorts rows — spills to disk if they exceed work_mem"
        if ntype == "Aggregate":
            return "collapses rows into aggregate results"
        if ntype == "Limit":
            return "stops after the requested number of rows (but only after everything below ran)"
        return f"{ntype} node"

    def headline(self, plan: PlanResult) -> str:
        worst = max(plan.nodes, key=lambda n: n.get("Total Cost", 0), default={})
        ntype = worst.get("Node Type", "")
        rel = worst.get("Relation Name", "the table")
        rows = worst.get("Plan Rows", 0)
        if ntype == "Seq Scan":
            return (f"Postgres can't use an index for your filter, so it reads every one "
                    f"of ~{rows:,} rows in {rel} (a Seq Scan). If the filter is selective, "
                    f"add an index and it jumps straight to the matches instead.")
        if ntype in ("Index Scan", "Index Only Scan"):
            return (f"Good — Postgres uses an index on {rel}, touching only matching rows "
                    f"(~{rows:,}) instead of scanning the whole table.")
        return f"The dominant step is a {ntype or 'scan'} over ~{rows:,} rows."

    # ---- describe_schema ----------------------------------------------------
    def describe_schema(self, run_sql) -> SchemaDescription:
        from anumana.adapters.base import SchemaDescription, SchemaTable
        try:
            cols = run_sql(_SCHEMA_COLS_SQL)
            idxs = run_sql(_SCHEMA_IDX_SQL)
            counts = run_sql(_SCHEMA_ROWS_SQL)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    "Could not read the Postgres catalog "
                    f"({type(e).__name__}). Provide a read-only ANUMANA_DSN with "
                    "USAGE on the schema, or paste your CREATE TABLE DDL so I can "
                    "analyse offline."
                ),
            )
        return _assemble_pg_schema(self.name, cols, idxs, counts)


# satisfy the Protocol at import time (fails fast if the contract drifts)
assert isinstance(PostgresAdapter(), Adapter)


# ---- catalog reads for describe_schema (READ-ONLY, never touches data) ------
# information_schema + pg_indexes + pg_class.reltuples. Public schema only by
# default; an operator can widen this later.
_SCHEMA_COLS_SQL = """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

_SCHEMA_IDX_SQL = """
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
"""

# reltuples is the planner's cached row estimate — no table scan, instant.
_SCHEMA_ROWS_SQL = """
SELECT relname, reltuples::bigint
FROM pg_class
WHERE relkind = 'r'
"""


def _assemble_pg_schema(engine: str, cols, idxs, counts):
    from anumana.adapters.base import SchemaDescription, SchemaTable

    # rows come back as [table, col, type] / [table, idx, def] / [table, n] tuples
    def _row(r):
        return r if isinstance(r, (list, tuple)) else [r]

    tables: dict[str, SchemaTable] = {}
    for r in cols:
        t, c, typ = _row(r)[0], _row(r)[1], _row(r)[2]
        tables.setdefault(t, SchemaTable(name=t)).columns.append({"name": c, "type": typ})

    # parse the indexed column(s) out of each indexdef (…USING btree (col[, col]))
    _idx_cols = re.compile(r"\(([^)]+)\)")
    _idx_method = re.compile(r"USING\s+(\w+)", re.I)
    for r in idxs:
        t, name, ddl = _row(r)[0], _row(r)[1], _row(r)[2]
        if t not in tables:
            continue
        cm = _idx_cols.search(ddl or "")
        mm = _idx_method.search(ddl or "")
        tables[t].indexes.append({
            "name": name,
            "columns": [c.strip() for c in cm.group(1).split(",")] if cm else [],
            "kind": mm.group(1).lower() if mm else "btree",
        })

    for r in counts:
        t, n = _row(r)[0], int(_row(r)[1])
        if t in tables:
            tables[t].row_count = n

    return SchemaDescription(
        engine=engine, tables=list(tables.values()), accuracy="LIVE",
        notes=["Row counts are the planner's cached estimate (pg_class.reltuples), "
               "not an exact COUNT(*) — fast and good enough for selectivity."],
    )
