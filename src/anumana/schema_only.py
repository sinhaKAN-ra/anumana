"""Anumana schema-only mode — analyse a query against pasted CREATE TABLE DDL,
with NO live database connection.

This is the low-friction front door: a user can try Anumana by pasting their
schema before ever trusting the addon with real DB credentials. It cannot read
live row-count statistics, so every estimate it produces is HEURISTIC (never
UPPER_BOUND) — the honesty model degrades gracefully and says so.

What it can still catch without a DB (purely from SQL text + declared schema):
  - SELECT *            (projection waste)
  - missing LIMIT       (unbounded result)
  - filter on a column with no index declared in the DDL  (likely scan)
  - LIKE '%...'         (leading wildcard, can't use btree)
  - function on a filtered column   (disables plain index use)

What it CANNOT do (and admits): predict real cost/selectivity (no stats), prove
a rewrite's planner-cost delta (no planner). It flags; it does not promise ms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from anumana.engine import Flag

# --- tiny DDL parser: table name -> {columns, indexed_columns} ---------------

_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?[\"']?(\w+)[\"']?\s*\((.*?)\);",
    re.I | re.S,
)
_CREATE_INDEX = re.compile(
    r"create\s+(?:unique\s+)?index\s+\w*\s*on\s+[\"']?(\w+)[\"']?\s*\(([^)]+)\)",
    re.I,
)
_PRIMARY_KEY = re.compile(r"\bprimary\s+key\s*\(?\s*([\w,\s]+?)\s*\)?", re.I)


@dataclass
class ParsedSchema:
    tables: dict[str, list[str]] = field(default_factory=dict)      # table -> columns
    indexed: dict[str, set[str]] = field(default_factory=dict)      # table -> indexed cols
    warnings: list[str] = field(default_factory=list)

    def table_count(self) -> int:
        return len(self.tables)


def parse_ddl(ddl: str) -> ParsedSchema:
    s = ParsedSchema()
    for m in _CREATE_TABLE.finditer(ddl):
        table, body = m.group(1), m.group(2)
        cols: list[str] = []
        idx: set[str] = set()
        for line in body.split(","):
            line = line.strip()
            if not line:
                continue
            pk = _PRIMARY_KEY.search(line)
            if pk and line.lower().startswith("primary key"):
                idx.update(c.strip() for c in pk.group(1).split(","))
                continue
            col = line.split()[0].strip('"\'')
            if col.lower() in ("constraint", "foreign", "unique", "check"):
                continue
            cols.append(col)
            # inline PRIMARY KEY / UNIQUE on the column => indexed
            if re.search(r"\b(primary\s+key|unique)\b", line, re.I):
                idx.add(col)
        s.tables[table] = cols
        s.indexed[table] = idx
    for m in _CREATE_INDEX.finditer(ddl):
        table, collist = m.group(1), m.group(2)
        first = collist.split(",")[0].strip().strip('"\'')
        s.indexed.setdefault(table, set()).add(first)
    if not s.tables:
        s.warnings.append("No CREATE TABLE statements parsed — check the DDL syntax.")
    return s


# --- static query analysis against the parsed schema -------------------------

_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_LEADING_WILDCARD = re.compile(r"like\s+'%", re.I)
_FUNC_ON_COL = re.compile(r"where[^=]*\b(lower|upper|date|cast)\s*\(", re.I)
_FROM_TABLE = re.compile(r"from\s+[\"']?(\w+)[\"']?", re.I)
_WHERE_COL = re.compile(r"where\s+[\"']?(\w+)[\"']?\s*[<>=]", re.I)


@dataclass
class SchemaOnlyResult:
    accuracy_tier: str
    flags: list[Flag]
    human_summary: str
    tables_seen: list[str]
    note: str = ("HEURISTIC — no live DB connection, so no real row counts or "
                 "selectivity. Connect a read-only DSN for grounded cost estimates.")


def analyse_static(ddl: str, sql: str) -> SchemaOnlyResult:
    schema = parse_ddl(ddl)
    flags: list[Flag] = []

    if _SELECT_STAR.search(sql):
        flags.append(Flag("SELECT_STAR_WIDE",
                           "SELECT * returns every column; project only what you use.",
                           "medium"))
    if not _HAS_LIMIT.search(sql):
        flags.append(Flag("UNBOUNDED_RESULT",
                           "No LIMIT — the result set is unbounded.", "medium"))
    if _LEADING_WILDCARD.search(sql):
        flags.append(Flag("LEADING_WILDCARD_LIKE",
                           "LIKE '%...' cannot use a btree index; forces a scan.", "medium"))
    if _FUNC_ON_COL.search(sql):
        flags.append(Flag("FUNCTION_ON_INDEXED_COL",
                           "A function wraps the filtered column, disabling plain index use.",
                           "medium"))

    # the schema-grounded check: is the filtered column indexed in the DDL?
    tm = _FROM_TABLE.search(sql)
    wm = _WHERE_COL.search(sql)
    if tm and wm:
        table, col = tm.group(1), wm.group(1)
        if table in schema.indexed and col not in schema.indexed[table]:
            flags.append(Flag(
                "MISSING_INDEX",
                f"Filter on {table}.{col} but no index on it is declared in the DDL — "
                f"this will likely force a scan. (Heuristic: no live stats to confirm.)",
                "high",
            ))

    summary = (f"Static analysis against pasted DDL ({schema.table_count()} table(s)). "
               f"Found {len(flags)} potential issue(s). No live cost — HEURISTIC only.")
    return SchemaOnlyResult(
        accuracy_tier="HEURISTIC", flags=flags, human_summary=summary,
        tables_seen=list(schema.tables), note=SchemaOnlyResult.note,
    )
