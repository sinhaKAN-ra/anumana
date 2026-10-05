"""MySQL / MariaDB adapter — cost diagnosis for the #2 most-used database.

MySQL exposes a plan WITHOUT running the query, with real row estimates:

    EXPLAIN FORMAT=JSON <sql>   -> nested query_block, no execution

Unlike SQLite/Mongo/FalkorDB, MySQL's EXPLAIN DOES carry row estimates
(`rows_examined_per_scan`) and, on 8.0+, a `query_cost`, so this adapter has
LIVE stats (has_live_stats=True) like Postgres. The signals we read from each
`table` node:

    access_type == "ALL"          -> full table scan (the "Seq Scan")
    access_type in ref/eq_ref/... -> an index/key was used
    rows_examined_per_scan        -> estimated rows touched per scan
    cost_info.query_cost          -> optimizer cost (8.0+; unitless, NOT ms)

Honesty rail: EXPLAIN (never ANALYZE) — preflight does not execute the query.
query_cost is the optimizer's unitless estimate, NOT milliseconds. The
engine-agnostic risk/English/rewrite layers are unchanged — this file only
teaches Anumana how to READ MySQL's cost signal.

run_sql is wired by server.py to a read-only MySQL connection
(mysql-connector / PyMySQL) returning the single JSON string EXPLAIN produces.
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
_LEADING_WILDCARD = re.compile(r"like\s+'%", re.I)

# access_type values that mean "an index/key was used" vs a full scan
_FULL_SCAN_ACCESS = {"ALL"}
_INDEXED_ACCESS = {"ref", "eq_ref", "const", "range", "index_merge", "fulltext", "ref_or_null"}


def _walk_query_block(block: dict):
    """Yield every `table` node in a MySQL EXPLAIN JSON query_block tree."""
    if not isinstance(block, dict):
        return
    if "table" in block and isinstance(block["table"], dict):
        yield block["table"]
    for key, val in block.items():
        if isinstance(val, dict):
            yield from _walk_query_block(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    yield from _walk_query_block(item)


class MysqlAdapter:
    name = "mysql"
    label = "MySQL / MariaDB"
    verified_live = False  # offline-verified against sample EXPLAIN JSON; no live server tested

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        rows = run_sql(f"EXPLAIN FORMAT=JSON {query}")
        doc = rows[0] if isinstance(rows, (list, tuple)) else rows
        if isinstance(doc, (list, tuple)):
            doc = doc[0]
        if isinstance(doc, (bytes, bytearray)):
            doc = doc.decode()
        if isinstance(doc, str):
            doc = json.loads(doc)
        qb = doc.get("query_block", doc)

        tables = list(_walk_query_block(qb))
        nodes: list[dict] = []
        max_rows = 0
        for t in tables:
            access = t.get("access_type", "")
            est = int(t.get("rows_examined_per_scan", t.get("rows", 0)) or 0)
            max_rows = max(max_rows, est)
            nodes.append({
                "Node Type": "Full Table Scan" if access in _FULL_SCAN_ACCESS
                             else f"Index Access ({access})" if access else "Access",
                "Relation Name": t.get("table_name"),
                "Plan Rows": est,
                "Total Cost": float(
                    (t.get("cost_info") or {}).get("read_cost", 0) or 0
                ),
                "_access_type": access,
                "_key": t.get("key"),
                "_used_key_parts": t.get("used_key_parts"),
            })

        # top-level query_cost if MySQL 8.0+ provided it
        query_cost = 0.0
        ci = qb.get("cost_info") if isinstance(qb, dict) else None
        if isinstance(ci, dict) and ci.get("query_cost"):
            try:
                query_cost = float(ci["query_cost"])
            except (TypeError, ValueError):
                query_cost = 0.0

        strategy = [n["Node Type"] + (f" on {n['Relation Name']}" if n.get("Relation Name") else "")
                    for n in nodes]
        metrics = EngineMetrics(
            rows_scanned=max_rows,
            rows_returned=max_rows,          # MySQL JSON gives per-scan, not final count
            total_cost=query_cost,
            cost_is_unitless=True,
            strategy=strategy,
        )
        return PlanResult(raw=qb, nodes=nodes, metrics=metrics, has_live_stats=True)

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        for n in plan.nodes:
            if n.get("_access_type") in _FULL_SCAN_ACCESS:
                rel = n.get("Relation Name", "a table")
                est = n.get("Plan Rows", 0)
                flags.append(EngineFlag(
                    "MYSQL_FULL_SCAN",
                    f"access_type=ALL on {rel} — a full table scan over ~{est:,} "
                    f"estimated rows because no index (key) serves the filter. Add "
                    f"an index on the filtered column(s).",
                    "high",
                ))
        if _SELECT_STAR.search(query):
            flags.append(EngineFlag(
                "SELECT_STAR_WIDE",
                "SELECT * returns every column; project only what you use.",
                "medium",
            ))
        if not _HAS_LIMIT.search(query):
            flags.append(EngineFlag(
                "UNBOUNDED_RESULT",
                "No LIMIT — the result set is unbounded and can flood the caller.",
                "medium",
            ))
        if _LEADING_WILDCARD.search(query):
            flags.append(EngineFlag(
                "LEADING_WILDCARD_LIKE",
                "LIKE '%...' with a leading wildcard cannot use a btree index; "
                "forces a scan.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        access = node.get("_access_type", "")
        rel = node.get("Relation Name") or "the table"
        key = node.get("_key")
        rows = node.get("Plan Rows", 0)
        if access == "ALL":
            return f"reads every row of {rel} (~{rows:,}) — no key serves the filter"
        if access in ("eq_ref", "const"):
            return f"fetches a single matching row from {rel} via key {key or ''}".strip()
        if access in ("ref", "ref_or_null"):
            return f"uses key {key or ''} to find matching rows in {rel}".strip()
        if access == "range":
            return f"scans an index range on {rel} via key {key or ''}".strip()
        if access == "index":
            return f"full index scan on {rel} (reads the whole index instead of the table)"
        return f"{access or 'access'} on {rel}"

    def headline(self, plan: PlanResult) -> str:
        scans = [n for n in plan.nodes if n.get("_access_type") == "ALL"]
        if scans:
            worst = max(scans, key=lambda n: n.get("Plan Rows", 0))
            return (f"MySQL can't use a key for your filter, so it reads every one of "
                    f"~{worst.get('Plan Rows', 0):,} rows in "
                    f"{worst.get('Relation Name', 'the table')} (access_type=ALL). "
                    f"Add an index on the filtered column and it uses a key instead.")
        indexed = [n for n in plan.nodes if n.get("_access_type") in _INDEXED_ACCESS]
        if indexed:
            return ("Good — MySQL uses a key (index) to find matching rows instead of "
                    "scanning the whole table.")
        return "MySQL plan read from EXPLAIN FORMAT=JSON."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from information_schema (READ-ONLY, current database only)."""
        try:
            cols = run_sql(
                "SELECT table_name, column_name, column_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "ORDER BY table_name, ordinal_position"
            )
            idxs = run_sql(
                "SELECT table_name, index_name, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() "
                "ORDER BY table_name, index_name, seq_in_index"
            )
            counts = run_sql(
                "SELECT table_name, table_rows "
                "FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type='BASE TABLE'"
            )
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the MySQL schema ({type(e).__name__}). Provide "
                    "a read-only connection with SELECT on information_schema, or "
                    "paste your CREATE TABLE statements."
                ),
            )

        def _row(r):
            return r if isinstance(r, (list, tuple)) else list(r.values()) if isinstance(r, dict) else [r]

        tables: dict[str, SchemaTable] = {}
        for r in cols:
            t, c, typ = _row(r)[0], _row(r)[1], _row(r)[2]
            tables.setdefault(t, SchemaTable(name=t)).columns.append(
                {"name": c, "type": typ})
        idx_acc: dict[tuple, dict] = {}
        for r in idxs:
            t, iname, col = _row(r)[0], _row(r)[1], _row(r)[2]
            key = (t, iname)
            idx_acc.setdefault(key, {"name": iname, "columns": [], "kind": "btree"})
            idx_acc[key]["columns"].append(col)
        for (t, _iname), ix in idx_acc.items():
            if t in tables:
                tables[t].indexes.append(ix)
        for r in counts:
            t, n = _row(r)[0], _row(r)[1]
            if t in tables and n is not None:
                tables[t].row_count = int(n)

        return SchemaDescription(
            engine=self.name, tables=list(tables.values()), accuracy="LIVE",
            notes=["Row counts are information_schema.tables.table_rows — an "
                   "estimate for InnoDB (not an exact COUNT(*)), good for selectivity."],
        )


assert isinstance(MysqlAdapter(), Adapter)
