"""Redshift adapter — Amazon's warehouse, ~20% of the cloud-warehouse market.

Redshift speaks the Postgres wire protocol and a Postgres-like EXPLAIN, so this
adapter SUBCLASSES PostgresAdapter and overrides only what differs:

  - Redshift EXPLAIN does NOT support FORMAT JSON — it returns text rows. We
    issue a plain `EXPLAIN <sql>` and parse the text plan.
  - Redshift adds distribution/broadcast operators (DS_BCAST_INNER,
    DS_DIST_BOTH) that signal expensive cross-node data movement — the dominant
    cost in an MPP warehouse. We flag those on top of the inherited SQL flags.

Honesty rail: EXPLAIN only, never run. Not yet verified against a live Redshift
cluster (verified_live=False) — the text-plan parsing is unit-checked offline.
"""
from __future__ import annotations

import re
from typing import Callable

from anumana.adapters.base import Adapter, EngineFlag, EngineMetrics, PlanResult
from anumana.adapters.postgres import PostgresAdapter

# Redshift data-distribution operators that mean cross-node movement
_DS_BCAST = re.compile(r"DS_BCAST", re.I)       # broadcast a whole table to every node
_DS_DIST = re.compile(r"DS_DIST_(?:BOTH|INNER|OUTER)", re.I)  # redistribute rows
_COST_RE = re.compile(r"cost=\d+\.\d+\.\.(\d+\.\d+)")
_ROWS_RE = re.compile(r"rows=(\d+)")


class RedshiftAdapter(PostgresAdapter):
    name = "redshift"
    label = "Amazon Redshift (MPP warehouse)"
    verified_live = False  # offline-verified only; no live cluster tested yet

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        # Redshift: plain text EXPLAIN (no FORMAT JSON).
        rows = run_sql(f"EXPLAIN {query}")
        lines = []
        for r in rows:
            if isinstance(r, (list, tuple)):
                lines.append(str(r[0]))
            elif isinstance(r, dict):
                lines.append(str(next(iter(r.values()))))
            else:
                lines.append(str(r))

        nodes: list[dict] = []
        max_cost = 0.0
        max_rows = 0
        for ln in lines:
            cm = _COST_RE.search(ln)
            rm = _ROWS_RE.search(ln)
            cost = float(cm.group(1)) if cm else 0.0
            est = int(rm.group(1)) if rm else 0
            max_cost = max(max_cost, cost)
            max_rows = max(max_rows, est)
            op = ln.strip().split("  ")[0].lstrip("-> ").strip()
            nodes.append({
                "Node Type": op,
                "Relation Name": None,
                "Plan Rows": est,
                "Total Cost": cost,
                "_line": ln.strip(),
            })
        metrics = EngineMetrics(
            rows_scanned=max_rows, rows_returned=max_rows, total_cost=max_cost,
            cost_is_unitless=True, strategy=[n["Node Type"] for n in nodes if n["Node Type"]],
        )
        return PlanResult(raw=lines, nodes=nodes, metrics=metrics, has_live_stats=True)

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        # inherit the SQL-text flags (SELECT *, unbounded, leading wildcard),
        # then add Redshift's MPP data-movement flags from the plan text.
        flags = super().detect_flags(query, plan)
        plan_text = "\n".join(n.get("_line", "") for n in plan.nodes)
        if _DS_BCAST.search(plan_text):
            flags.append(EngineFlag(
                "REDSHIFT_BROADCAST",
                "DS_BCAST — Redshift broadcasts an entire table to every compute "
                "node before the join. On a large table this is the dominant cost. "
                "Align the join keys with the tables' DISTKEY to avoid it.",
                "high",
            ))
        if _DS_DIST.search(plan_text):
            flags.append(EngineFlag(
                "REDSHIFT_REDISTRIBUTE",
                "DS_DIST_* — rows are redistributed across nodes for the join "
                "because the join key isn't the distribution key. Set a matching "
                "DISTKEY to keep the join node-local.",
                "high",
            ))
        return flags

    def headline(self, plan: PlanResult) -> str:
        plan_text = "\n".join(n.get("_line", "") for n in plan.nodes)
        if _DS_BCAST.search(plan_text) or _DS_DIST.search(plan_text):
            return ("This query moves data BETWEEN compute nodes (broadcast / "
                    "redistribute) — the dominant cost in an MPP warehouse. Align "
                    "the join keys with the table DISTKEYs to keep the join local.")
        return super().headline(plan)


assert isinstance(RedshiftAdapter(), Adapter)
