"""SQLite adapter — cost diagnosis for the text-to-SQL base case.

SQLite is the database every local agent / text-to-SQL prototype hits first
(it's a file, zero-setup), and it's the #3 most-used DB overall. It exposes a
plan WITHOUT running the query:

    EXPLAIN QUERY PLAN <sql>   -> the query plan (no execution)

EXPLAIN QUERY PLAN returns flat rows whose `detail` column reads in plain
English, e.g.:

    SCAN orders                         -> full table scan (the "Seq Scan")
    SEARCH orders USING INDEX idx_x     -> an index was used
    USE TEMP B-TREE FOR ORDER BY        -> an un-indexed sort (materialises)

Honesty rail: EXPLAIN QUERY PLAN has NO row or cost estimates — SQLite's planner
doesn't expose them here. So SQLite preflight is HEURISTIC on cost (like Mongo /
FalkorDB): it reads the ACCESS PATTERN (full scan vs index search, temp-btree
sorts), which is what actually decides whether a SQLite query is cheap, and says
plainly it has no live counts.

The `run_sql` callable is wired by server.py to a read-only sqlite3 connection's
`.execute(...).fetchall()`. The engine-agnostic risk/English/rewrite layers are
unchanged — this file only teaches Anumana how to READ SQLite's cost signal.
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

# shared SQL-text flag patterns (same shapes as the Postgres adapter)
_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_LEADING_WILDCARD = re.compile(r"like\s+'%", re.I)

# EXPLAIN QUERY PLAN detail classification
_SCAN_RE = re.compile(r"\bSCAN\b", re.I)          # full table scan
_SEARCH_RE = re.compile(r"\bSEARCH\b", re.I)      # index-assisted
_USING_INDEX_RE = re.compile(r"USING\s+(?:COVERING\s+)?INDEX\s+(\S+)", re.I)
_TEMP_BTREE_RE = re.compile(r"USE\s+TEMP\s+B-?TREE", re.I)
_TABLE_NAME_RE = re.compile(r"\b(?:SCAN|SEARCH)\s+(\w+)", re.I)


class SqliteAdapter:
    name = "sqlite"
    label = "SQLite"
    verified_live = True  # tested end-to-end against a real seeded .db this session

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        rows = run_sql(f"EXPLAIN QUERY PLAN {query}")
        # rows: list of (id, parent, notused, detail) tuples (or dict-ish)
        details: list[str] = []
        for r in rows:
            if isinstance(r, (list, tuple)):
                details.append(str(r[-1]))
            elif isinstance(r, dict):
                details.append(str(r.get("detail", r)))
            else:
                details.append(str(r))

        nodes: list[dict] = []
        for d in details:
            is_scan = bool(_SCAN_RE.search(d)) and not _SEARCH_RE.search(d)
            is_search = bool(_SEARCH_RE.search(d))
            idx_m = _USING_INDEX_RE.search(d)
            tbl_m = _TABLE_NAME_RE.search(d)
            if _TEMP_BTREE_RE.search(d):
                ntype = "Temp B-Tree Sort"
            elif is_search:
                ntype = "Search (index)"
            elif is_scan:
                ntype = "Scan (full table)"
            else:
                ntype = "Step"
            nodes.append({
                "Node Type": ntype,
                "Relation Name": tbl_m.group(1) if tbl_m else None,
                "Plan Rows": 0,          # EXPLAIN QUERY PLAN has NO row estimate
                "Total Cost": 0.0,
                "_detail": d,
                "_index": idx_m.group(1) if idx_m else None,
                "_full_scan": is_scan,
            })
        strategy = [n["Node Type"] + (f" on {n['Relation Name']}" if n.get("Relation Name") else "")
                    for n in nodes]
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=0.0,
            cost_is_unitless=True, strategy=strategy,
        )
        return PlanResult(raw=details, nodes=nodes, metrics=metrics, has_live_stats=False)

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []

        if any(n.get("_full_scan") for n in plan.nodes):
            rel = next((n["Relation Name"] for n in plan.nodes
                        if n.get("_full_scan") and n.get("Relation Name")), "a table")
            flags.append(EngineFlag(
                "SQLITE_FULL_SCAN",
                f"SCAN {rel} — SQLite reads every row because no index supports the "
                f"filter. Add an index: CREATE INDEX idx ON {rel}(col).",
                "high",
            ))
        if any(n.get("Node Type") == "Temp B-Tree Sort" for n in plan.nodes):
            flags.append(EngineFlag(
                "SQLITE_TEMP_BTREE_SORT",
                "USE TEMP B-TREE — the ORDER BY / GROUP BY can't be served by an "
                "index, so SQLite builds a temporary B-tree to sort. An index on "
                "the sort column(s) removes this step.",
                "medium",
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
                "LIKE '%...' with a leading wildcard cannot use an index; forces a scan.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        nt = node.get("Node Type", "")
        rel = node.get("Relation Name")
        idx = node.get("_index")
        if nt == "Scan (full table)":
            return f"reads every row of {rel or 'the table'} — no index supports the filter"
        if nt == "Search (index)":
            return f"uses index {idx or ''} to jump to matching rows in {rel or 'the table'}".strip()
        if nt == "Temp B-Tree Sort":
            return "builds a temporary B-tree to sort because no index serves the ORDER BY/GROUP BY"
        return node.get("_detail", nt) or "plan step"

    def headline(self, plan: PlanResult) -> str:
        if any(n.get("_full_scan") for n in plan.nodes):
            rel = next((n["Relation Name"] for n in plan.nodes
                        if n.get("_full_scan") and n.get("Relation Name")), "the table")
            return (f"SQLite reads EVERY row of {rel} (a full SCAN) because no index "
                    f"matched your filter — it gets linearly slower as the table grows. "
                    f"Add an index on the filtered column.")
        if any(n.get("Node Type") == "Search (index)" for n in plan.nodes):
            return ("Good — SQLite uses an index (SEARCH) to jump straight to matching "
                    "rows instead of scanning the whole table.")
        return "SQLite plan read from EXPLAIN QUERY PLAN (access pattern only; no live counts)."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from SQLite's own catalog: sqlite_master + PRAGMA table_info /
        index_list. READ-ONLY. run_sql is wired to a read-only connection."""
        try:
            tbls = run_sql(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the SQLite schema ({type(e).__name__}). "
                    "Provide a path to a readable .db file, or paste your CREATE "
                    "TABLE statements so I can analyse offline."
                ),
            )
        tables: list[SchemaTable] = []
        for row in tbls:
            tname = row[0] if isinstance(row, (list, tuple)) else (
                row.get("name") if isinstance(row, dict) else str(row))
            cols, idxs = [], []
            try:
                for ci in run_sql(f"PRAGMA table_info({tname})"):
                    # PRAGMA table_info: (cid, name, type, notnull, dflt, pk)
                    c = ci if isinstance(ci, (list, tuple)) else list(ci.values())
                    cols.append({"name": c[1], "type": c[2] or "unknown"})
                for ix in run_sql(f"PRAGMA index_list({tname})"):
                    x = ix if isinstance(ix, (list, tuple)) else list(ix.values())
                    # index_list: (seq, name, unique, origin, partial)
                    iname = x[1]
                    icols = []
                    for info in run_sql(f"PRAGMA index_info({iname})"):
                        y = info if isinstance(info, (list, tuple)) else list(info.values())
                        icols.append(y[2])  # column name
                    idxs.append({"name": iname, "columns": icols, "kind": "btree"})
            except Exception:
                pass
            tables.append(SchemaTable(
                name=tname, columns=cols, indexes=idxs, row_count=None,
                caveats=["Row count omitted — SQLite has no cached estimate; a "
                         "COUNT(*) would scan the table."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="LIVE",
            notes=["Columns from PRAGMA table_info; indexes from PRAGMA index_list."],
        )


assert isinstance(SqliteAdapter(), Adapter)
