"""DynamoDB adapter — RULE-BASED cost detection, no planner.

DynamoDB has no query planner and no EXPLAIN. But its cost model is PREDICTABLE
BY RULE, which is exactly why it fits Anumana's "foresee cost before running"
promise — and it's a CLEANER signal than parsing a plan tree:

  - Query  (uses the partition key)        -> cheap, O(matched items)
  - Scan   (no partition key)              -> reads the WHOLE table/GSI = expensive
  - a filter WITHOUT a key condition       -> still a Scan under the hood (the
       FilterExpression runs AFTER the read, so you pay for every item read)
  - a GSI/LSI that doesn't cover the access pattern -> forces a Scan
  - large Limit / no Limit on a Scan       -> unbounded read-capacity burn

Surprise AWS bills come from exactly these patterns, and an AI agent writing a
DynamoDB access pattern has no feedback that it just wrote a full-table Scan.

Input shape: the agent passes the request as JSON — the operation plus its
key/filter expressions, e.g.
    {"op": "Scan", "TableName": "orders", "FilterExpression": "status = :s"}
    {"op": "Query", "TableName": "orders",
     "KeyConditionExpression": "pk = :u", "IndexName": "by_user"}

There is NO run_sql call — nothing to EXPLAIN. get_plan parses the request and
builds a synthetic node so the engine-agnostic layers still work. has_live_stats
is False and accuracy is HEURISTIC: we judge the ACCESS PATTERN, not item counts.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from anumana.adapters.base import Adapter, EngineFlag, EngineMetrics, PlanResult

_KEY_COND = re.compile(r"keycondition", re.I)
_FILTER = re.compile(r"filterexpression", re.I)
_OP = re.compile(r'"op"\s*:\s*"(\w+)"', re.I)
_TABLE = re.compile(r'"tablename"\s*:\s*"([^"]+)"', re.I)
_INDEX = re.compile(r'"indexname"\s*:\s*"([^"]+)"', re.I)
_LIMIT = re.compile(r'"limit"\s*:\s*(\d+)', re.I)


class DynamoAdapter:
    name = "dynamodb"
    label = "DynamoDB (rule-based)"
    verified_live = False  # offline-verified; no live AWS table tested

    def get_plan(self, run_sql: Callable[[str], list], query: str) -> PlanResult:
        # No EXPLAIN exists — we parse the request shape itself. run_sql is ignored.
        req = _parse(query)
        op = req["op"]
        access = _classify_access(req)   # "query" (cheap) or "scan" (expensive)
        node = {
            "Node Type": "Query (key condition)" if access == "query" else "Scan (full table)",
            "Relation Name": req.get("table"),
            "Plan Rows": 0,
            "Total Cost": 0.0,
            "_dynamo_op": op,
            "_dynamo_access": access,
            "_dynamo_index": req.get("index"),
        }
        metrics = EngineMetrics(
            rows_scanned=0, rows_returned=0, total_cost=0.0,
            cost_is_unitless=True,
            strategy=[node["Node Type"] + (f" on {req['index']}" if req.get("index") else "")],
        )
        pr = PlanResult(raw=req, nodes=[node], metrics=metrics, has_live_stats=False)
        pr._access = access  # type: ignore[attr-defined]
        return pr

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        req = plan.raw
        access = plan.nodes[0]["_dynamo_access"]
        flags: list[EngineFlag] = []

        if access == "scan":
            flags.append(EngineFlag(
                "DYNAMO_FULL_SCAN",
                "This reads the WHOLE table (a Scan) — there is no partition-key "
                "condition, so DynamoDB cannot target items. Cost grows with table "
                "size and burns read capacity. Design a key or GSI for this access "
                "pattern and use Query with a KeyConditionExpression instead.",
                "high",
            ))
        if req.get("has_filter") and access == "scan":
            flags.append(EngineFlag(
                "DYNAMO_FILTER_WITHOUT_KEY",
                "A FilterExpression WITHOUT a KeyConditionExpression does NOT save "
                "reads — DynamoDB reads every item first, THEN filters. You pay for "
                "the full scan. Move the predicate into a key condition on an index.",
                "high",
            ))
        if req["op"].lower() == "scan" and not req.get("limit"):
            flags.append(EngineFlag(
                "DYNAMO_UNBOUNDED_SCAN",
                "A Scan with no Limit pages through the entire table — unbounded "
                "read-capacity consumption. Add a Limit, or (better) make it a Query.",
                "medium",
            ))
        if req.get("limit") and req["limit"] > 1000:
            flags.append(EngineFlag(
                "DYNAMO_LARGE_PAGE",
                f"Limit {req['limit']} on a single request — large pages spike "
                f"consumed capacity. Page in smaller batches.",
                "medium",
            ))
        return flags

    def node_reason(self, node: dict) -> str:
        if node["_dynamo_access"] == "query":
            idx = node.get("_dynamo_index")
            return (f"targets items by partition key"
                    + (f" on index {idx}" if idx else "")
                    + " — reads only matching items (the cheap path)")
        return ("reads every item in the table and applies any filter afterward — "
                "cost scales with table size, not with matches (the expensive path)")

    def headline(self, plan: PlanResult) -> str:
        if plan.nodes[0]["_dynamo_access"] == "scan":
            return ("This is a full-table SCAN: DynamoDB reads every item because the "
                    "request has no partition-key condition. It gets more expensive as "
                    "the table grows and is the #1 cause of surprise DynamoDB bills. "
                    "Add a key/GSI for this access pattern and use Query.")
        return ("Good — this is a Query against the partition key, so DynamoDB reads "
                "only the items you asked for (the efficient, predictable-cost path).")

    def describe_schema(self, run_sql) -> "object":
        """DynamoDB has no columns to list, but the KEY SCHEMA + GSIs/LSIs ARE the
        schema that matters — they define which access patterns are cheap. run_sql
        is wired to return DescribeTable output: {"tables":[{name, key_schema,
        gsis, item_count}]}."""
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
                    f"Could not DescribeTable ({type(e).__name__}). Provide AWS "
                    "credentials + region (read-only), or tell me the table's "
                    "partition key, sort key, and any GSIs — those define the valid "
                    "access patterns."
                ),
            )
        tables = []
        for t in doc.get("tables", []):
            ks = t.get("key_schema", {})
            idx = [{"name": "primary",
                    "columns": [ks.get("partition_key"), ks.get("sort_key")],
                    "kind": "primary"}]
            for g in t.get("gsis", []):
                idx.append({"name": g.get("name"), "columns": g.get("keys", []),
                            "kind": "gsi"})
            tables.append(SchemaTable(
                name=t.get("name", "?"),
                columns=[{"name": ks.get("partition_key"), "type": "partition_key"}]
                        + ([{"name": ks.get("sort_key"), "type": "sort_key"}]
                           if ks.get("sort_key") else []),
                indexes=idx, row_count=t.get("item_count"),
                caveats=["DynamoDB items are schemaless beyond the key attributes; "
                         "only keys and indexes define cheap access patterns."],
            ))
        return SchemaDescription(
            engine=self.name, tables=tables, accuracy="LIVE",
            notes=["Key schema + GSIs from DescribeTable define which queries are "
                   "cheap. Design queries around a partition key to avoid Scans."],
        )


# ---- request parsing + access classification --------------------------------

def _parse(query: str) -> dict:
    op_m = _OP.search(query)
    table_m = _TABLE.search(query)
    index_m = _INDEX.search(query)
    limit_m = _LIMIT.search(query)
    op = op_m.group(1) if op_m else ("Query" if _KEY_COND.search(query) else "Scan")
    return {
        "op": op,
        "table": table_m.group(1) if table_m else None,
        "index": index_m.group(1) if index_m else None,
        "limit": int(limit_m.group(1)) if limit_m else None,
        "has_key_condition": bool(_KEY_COND.search(query)),
        "has_filter": bool(_FILTER.search(query)),
    }


def _classify_access(req: dict) -> str:
    """A request is a cheap 'query' ONLY if it carries a key condition AND the op
    is Query. Everything else — Scan, or a Query missing its key condition — is a
    'scan' in cost terms."""
    if req["op"].lower() == "query" and req["has_key_condition"]:
        return "query"
    return "scan"


assert isinstance(DynamoAdapter(), Adapter)
