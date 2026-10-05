"""BigQuery adapter — Google's warehouse, ~28% market share, and the SINGLE
best fit for Anumana's "preflight the cost before you run it" thesis.

BigQuery bills PER BYTE SCANNED, and its dry-run API returns the exact bytes a
query WOULD scan WITHOUT running it:

    jobs.insert(configuration.dryRun=true) -> statistics.totalBytesProcessed

So this adapter can tell a user the DOLLAR cost of a query before execution —
unique among all engines. $5 / TB scanned (on-demand pricing) is the standard
conversion.

The `run_sql` callable here is really `dry_run(sql) -> {"totalBytesProcessed":
int, "referencedTables": [...], "cacheHit": bool}`: server.py wires it to the
BigQuery client's dry-run job. There is no row-by-row plan from a dry run —
the cost signal IS the bytes, which is exactly what matters for BigQuery.

Honesty rail: dry-run never executes the query (no bytes billed for a dry run).
Not yet verified against a live BigQuery project (verified_live=False).
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
# BigQuery charges for scanned bytes regardless of LIMIT, and partition filters
# are the main lever. Detect a query with no WHERE on a partitioned scan.
_HAS_WHERE = re.compile(r"\bwhere\b", re.I)

_USD_PER_TB = 5.0           # BigQuery on-demand: $5 per TB scanned
_BYTES_PER_TB = 1024 ** 4


class BigQueryAdapter:
    name = "bigquery"
    label = "Google BigQuery (serverless warehouse)"
    verified_live = False

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        raw = run_sql(query)   # dry-run result dict
        doc = raw[0] if isinstance(raw, (list, tuple)) else raw
        if isinstance(doc, (bytes, str)):
            doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        bytes_scanned = int(doc.get("totalBytesProcessed", 0) or 0)
        refs = doc.get("referencedTables", [])

        tb = bytes_scanned / _BYTES_PER_TB
        est_usd = tb * _USD_PER_TB
        node = {
            "Node Type": "Dry-run scan",
            "Relation Name": ", ".join(
                t.get("tableId", "?") if isinstance(t, dict) else str(t) for t in refs
            ) or None,
            "Plan Rows": 0,
            "Total Cost": round(est_usd, 4),   # cost here is DOLLARS, not planner units
            "_bytes": bytes_scanned,
            "_usd": est_usd,
            "_cache_hit": bool(doc.get("cacheHit", False)),
        }
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=round(est_usd, 4),
            cost_is_unitless=False,   # this cost IS a real unit: US dollars
            strategy=[f"scans {_human_bytes(bytes_scanned)} (~${est_usd:.2f})"],
        )
        pr = PlanResult(raw=doc, nodes=[node], metrics=metrics, has_live_stats=True)
        pr._bytes = bytes_scanned  # type: ignore[attr-defined]
        pr._usd = est_usd          # type: ignore[attr-defined]
        return pr

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        node = plan.nodes[0] if plan.nodes else {}
        bytes_scanned = node.get("_bytes", 0)
        usd = node.get("_usd", 0.0)

        if _SELECT_STAR.search(query):
            flags.append(EngineFlag(
                "BQ_SELECT_STAR",
                "SELECT * in BigQuery scans EVERY column's bytes — and you pay for "
                "all of them. Projecting only needed columns is the biggest cost "
                "lever (BigQuery is columnar; unused columns are free if not "
                "selected).",
                "high",
            ))
        if bytes_scanned and bytes_scanned > _BYTES_PER_TB:  # >1 TB
            flags.append(EngineFlag(
                "BQ_LARGE_SCAN",
                f"This query scans {_human_bytes(bytes_scanned)} "
                f"(~${usd:.2f} at $5/TB) BEFORE returning a single row. Add a "
                f"partition/cluster filter in WHERE to cut the scanned bytes.",
                "high",
            ))
        if not _HAS_WHERE.search(query):
            flags.append(EngineFlag(
                "BQ_NO_PARTITION_FILTER",
                "No WHERE filter — if the table is partitioned, you're scanning "
                "every partition. Filter on the partition column to scan only the "
                "partitions you need.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        if node.get("Node Type") == "Dry-run scan":
            return (f"a dry run estimates {_human_bytes(node.get('_bytes', 0))} "
                    f"will be scanned (~${node.get('_usd', 0):.2f}) — no bytes are "
                    f"billed for the dry run itself")
        return node.get("Node Type", "step")

    def headline(self, plan: PlanResult) -> str:
        node = plan.nodes[0] if plan.nodes else {}
        b = node.get("_bytes", 0)
        usd = node.get("_usd", 0.0)
        if node.get("_cache_hit"):
            return "This query hits BigQuery's cache — it scans 0 bytes and costs $0."
        if b:
            return (f"This query will scan {_human_bytes(b)} and cost about "
                    f"${usd:.2f} (at $5/TB) the moment you run it — BigQuery bills "
                    f"per byte scanned, not per row returned, so a LIMIT does NOT "
                    f"reduce this. Filter on a partition/cluster column to cut it.")
        return "BigQuery dry run: scanned-bytes estimate unavailable."

    def describe_schema(self, run_sql: Callable[[str], list]) -> SchemaDescription:
        """Schema from INFORMATION_SCHEMA.COLUMNS. run_sql wired to a read-only
        query job (dry-run-safe metadata query)."""
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, (list, tuple)) else doc
            if isinstance(doc, (bytes, str)):
                doc = json.loads(doc.decode() if isinstance(doc, bytes) else doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not read the BigQuery dataset schema ({type(e).__name__}). "
                    "Provide a service account with bigquery.tables.get on the "
                    "dataset, or paste the table DDL."
                ),
            )
        tables = []
        for t in doc.get("tables", []):
            tables.append(SchemaTable(
                name=t.get("name", "?"),
                columns=[{"name": c.get("name"), "type": c.get("type")}
                         for c in t.get("columns", [])],
                indexes=[],  # BigQuery has no indexes — partitioning/clustering instead
                row_count=t.get("row_count"),
                caveats=["BigQuery has no indexes — cost is governed by partitioning "
                         "and clustering. Partition/cluster columns: "
                         f"{t.get('partitioning') or 'none'}."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="LIVE",
            notes=["Schema from INFORMATION_SCHEMA; cost lever is partition/cluster "
                   "pruning, not indexes."],
        )


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} EB"


assert isinstance(BigQueryAdapter(), Adapter)
