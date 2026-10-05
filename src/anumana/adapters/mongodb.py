"""MongoDB adapter — cost diagnosis for the document queries AI agents write.

MongoDB is the NoSQL agents actually touch (Atlas, Mongoose). It has its own
"EXPLAIN": `db.coll.find(...).explain("queryPlanner")`, which returns a
queryPlanner document describing the winning plan WITHOUT running the query —
the same honest contract as SQL EXPLAIN (never executionStats-with-execution).

Mongo's plan is a nested `inputStage` chain, not a SQL tree. We normalize it to
the shared `nodes` list so the engine-agnostic risk/English layers work
unchanged. The signals we read:

  - stage == COLLSCAN            -> the Mongo "Seq Scan": no index used
  - stage == IXSCAN / FETCH      -> an index was used
  - rejectedPlans present        -> the planner considered indexes (context)

The `run_sql` callable here is really a `run_explain(command_json) -> doc`:
server.py wires it to pymongo's `database.command({"explain": ...})`. The engine
never cares — it only sees the normalized nodes.

Honesty rail: queryPlanner alone has NO row estimates (those live in
executionStats, which requires RUNNING the query). So Mongo preflight is
HEURISTIC on cost — it tells you the ACCESS PATTERN (indexed vs collection scan),
which is the thing that actually matters, and says plainly it has no live counts.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from anumana.adapters.base import Adapter, EngineFlag, EngineMetrics, PlanResult

# the Mongo query, as the agent writes it, is JSON-ish: {"find": "...", "filter": {...}}
_SORT_META_VECTOR = re.compile(r"\$vectorSearch|\$search", re.I)


def _walk_stages(plan: dict):
    """Yield each stage in a Mongo winningPlan inputStage chain, outer-first."""
    node = plan
    while isinstance(node, dict) and node.get("stage"):
        yield node
        node = node.get("inputStage")


class MongoAdapter:
    name = "mongodb"
    label = "MongoDB (document)"
    verified_live = False  # offline-verified; no live MongoDB instance tested

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        # run_sql returns the raw explain() document (one element list).
        rows = run_sql(query)
        doc = rows[0] if isinstance(rows, list) else rows
        if isinstance(doc, str):
            doc = json.loads(doc)
        qp = doc.get("queryPlanner", doc)
        winning = qp.get("winningPlan", {})
        stages = list(_walk_stages(winning))

        # normalize each Mongo stage into the shared node shape the engine walks.
        nodes: list[dict] = []
        for s in stages:
            nodes.append({
                "Node Type": _stage_to_node_type(s.get("stage", "?")),
                "Relation Name": qp.get("namespace", "").split(".")[-1] or None,
                "Plan Rows": 0,              # queryPlanner has NO row estimate
                "Total Cost": 0.0,
                "_mongo_stage": s.get("stage"),
                "_index": s.get("indexName"),
            })
        used_index = any(n["_mongo_stage"] in ("IXSCAN", "DISTINCT_SCAN") for n in nodes)
        strategy = [n["Node Type"] + (f" using {n['_index']}" if n.get("_index") else "")
                    for n in nodes]
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=0.0,
            cost_is_unitless=True, strategy=strategy,
        )
        pr = PlanResult(raw=qp, nodes=nodes, metrics=metrics, has_live_stats=False)
        pr._used_index = used_index  # type: ignore[attr-defined]
        return pr

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        flags: list[EngineFlag] = []
        stages = {n.get("_mongo_stage") for n in plan.nodes}

        if "COLLSCAN" in stages:
            flags.append(EngineFlag(
                "MONGO_COLLSCAN",
                "COLLSCAN — the query scans every document in the collection "
                "because no index supports the filter. Add an index on the "
                "filtered field(s): db.coll.createIndex({ field: 1 }).",
                "high",
            ))
        # no projection -> whole documents returned (Mongo's SELECT *)
        if '"projection"' not in query and "projection" not in query:
            flags.append(EngineFlag(
                "MONGO_NO_PROJECTION",
                "No projection — the full document is returned for every match. "
                "Project only the fields you use: .find(filter, { field: 1 }).",
                "medium",
            ))
        # no limit -> unbounded cursor
        if '"limit"' not in query and "limit" not in query:
            flags.append(EngineFlag(
                "MONGO_UNBOUNDED",
                "No limit — the cursor can return the whole matching set. Add "
                ".limit(n) unless you truly need every document.",
                "medium",
            ))
        # a $regex anchored with a leading wildcard can't use an index
        if re.search(r"\$regex[\"']?\s*:\s*[\"']/?\^?\.\*", query) or re.search(r"\$regex[\"']?\s*:\s*[\"']?[^\^]", query):
            if re.search(r"\$regex", query) and not re.search(r"\$regex[\"']?\s*:\s*[\"']?/?\^", query):
                flags.append(EngineFlag(
                    "MONGO_UNANCHORED_REGEX",
                    "An unanchored $regex (no leading ^) cannot use an index and "
                    "forces a scan. Anchor it (^prefix) or use Atlas Search.",
                    "medium",
                ))
        return flags

    def node_reason(self, node: dict) -> str:
        stage = node.get("_mongo_stage")
        idx = node.get("_index")
        if stage == "COLLSCAN":
            return "reads every document in the collection — no index supports the filter"
        if stage == "IXSCAN":
            return f"walks the index {idx or ''} to find matching documents directly".strip()
        if stage == "FETCH":
            return "fetches the full documents for the row ids the index found"
        if stage == "SORT":
            return "sorts matched documents in memory (fails at 32MB without an index-backed sort)"
        if stage == "LIMIT":
            return "stops after the requested number of documents"
        if stage == "PROJECTION_SIMPLE" or stage == "PROJECTION_COVERED":
            return "returns only the projected fields"
        return f"{stage} stage"

    def headline(self, plan: PlanResult) -> str:
        stages = {n.get("_mongo_stage") for n in plan.nodes}
        if "COLLSCAN" in stages:
            return ("This query scans EVERY document in the collection (COLLSCAN) "
                    "because no index supports the filter — it gets linearly slower "
                    "as the collection grows. Add an index on the filtered field(s).")
        if "IXSCAN" in stages:
            return ("Good — the query uses an index (IXSCAN) to jump straight to "
                    "matching documents instead of scanning the whole collection.")
        return "Mongo plan read from queryPlanner (access pattern only; no live counts)."

    def describe_schema(self, run_sql) -> "object":
        """Mongo is schemaless, so fields are SAMPLED from a few documents (never
        authoritative) and indexes come from getIndexes(). run_sql here is wired
        to return {"collections": [{name, sample_fields, indexes, est_count}]}."""
        from anumana.adapters.base import SchemaDescription, SchemaTable
        try:
            doc = run_sql("__anumana_describe__")
            doc = doc[0] if isinstance(doc, list) else doc
            if isinstance(doc, str):
                doc = json.loads(doc)
        except Exception as e:
            return SchemaDescription(
                engine=self.name, accuracy="NONE",
                need_from_user=(
                    f"Could not sample the MongoDB schema ({type(e).__name__}). "
                    "Provide a read-only connection URI, or tell me the collection "
                    "name and the fields you filter on."
                ),
            )
        tables = []
        for c in doc.get("collections", []):
            tables.append(SchemaTable(
                name=c.get("name", "?"),
                columns=[{"name": f, "type": "sampled"} for f in c.get("sample_fields", [])],
                indexes=[{"name": i.get("name"), "columns": list(i.get("key", {})),
                          "kind": "mongo"} for i in c.get("indexes", [])],
                row_count=c.get("est_count"),
                caveats=["Fields are SAMPLED from a few documents — Mongo is "
                         "schemaless, so other documents may have different fields."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="SAMPLED",
            notes=["Document fields inferred by sampling; indexes from getIndexes()."],
        )


def _stage_to_node_type(stage: str) -> str:
    """Map a Mongo stage to a readable node type (keeps strategy lines consistent)."""
    return {
        "COLLSCAN": "Collection Scan",
        "IXSCAN": "Index Scan",
        "FETCH": "Fetch",
        "SORT": "Sort",
        "LIMIT": "Limit",
        "PROJECTION_SIMPLE": "Projection",
        "PROJECTION_COVERED": "Covered Projection",
        "DISTINCT_SCAN": "Distinct Index Scan",
    }.get(stage, stage.title() if stage else "?")


assert isinstance(MongoAdapter(), Adapter)
