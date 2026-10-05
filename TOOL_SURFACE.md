# Anumana — MCP Tool Surface Design

The agent-facing contract. These are the MCP tools Claude / Cursor / Windsurf /
Codex / Kiro call. Keep the surface **small and sharp** — four tools, one job.

Design principles:
1. **Every number carries an `accuracy_tier`** (PRECISE | UPPER_BOUND | HEURISTIC). Never a bare fake ms.
2. **`EXPLAIN` only, never `EXPLAIN ANALYZE`** inside the pre-flight tools — nothing executes the user's query.
3. **Schema-only mode must work with no live DB** (lowest install friction — nobody hands a stranger's addon live creds on day one).
4. **The agent is the user.** Outputs are structured for an LLM to reason over AND a human to read.

---

## Tool 1 — `connect_schema`

Register a datasource. Three input modes (all first-class):

```jsonc
{
  "mode": "dsn | schema_ddl | mapping",      // 1=live DB, 2=pasted DDL, 3=sidecar to another DB MCP
  "dsn": "postgres://readonly@host/db",       // mode=dsn; read-only creds strongly recommended
  "ddl": "CREATE TABLE orders (...);",         // mode=schema_ddl; offline, no connection
  "name": "prod_pg"
}
```

Returns: `{ datasource_id, engine, tables_seen, has_live_stats, warnings[] }`.
`has_live_stats=false` in DDL mode downgrades every later estimate to UPPER_BOUND
or HEURISTIC — the honesty model propagates from here.

---

## Tool 2 — `preflight_query` *(the core tool)*

Given a query the agent just wrote, predict overhead **without running it.**

Input: `{ datasource_id, sql }`

Mechanism: `EXPLAIN (FORMAT JSON, VERBOSE, BUFFERS OFF)` + catalog stats
(`pg_class.reltuples`, `pg_stats`, index presence). Never ANALYZE.

Output:
```jsonc
{
  "risk_tier": "cheap | moderate | expensive | dangerous",
  "accuracy_tier": "PRECISE | UPPER_BOUND | HEURISTIC",
  "rows_scanned_est": 40000000,
  "rows_returned_est": 12,
  "scan_strategy": ["Seq Scan on orders", "Nested Loop"],
  "planner_total_cost": 15629.12,          // raw, labelled "unitless planner cost, NOT ms"
  "flags": [
    { "code": "MISSING_INDEX", "detail": "filter on orders.created_at has no index; forces Seq Scan over ~40M rows", "severity": "high" },
    { "code": "SELECT_STAR_WIDE", "detail": "SELECT * on a 38-column table; most columns unused downstream", "severity": "medium" },
    { "code": "UNBOUNDED_RESULT", "detail": "no LIMIT; result set is unbounded", "severity": "medium" }
  ],
  "human_summary": "Scans ~40M rows to return 12. Seq Scan because created_at is unindexed. Expensive on this schema; see rewrite.",
  "has_rewrite": true
}
```

**Flag catalogue (v1):** `MISSING_INDEX`, `SEQ_SCAN_LARGE`, `NESTED_LOOP_BLOWUP`,
`SELECT_STAR_WIDE`, `UNBOUNDED_RESULT`, `FUNCTION_ON_INDEXED_COL`
(kills index use), `LEADING_WILDCARD_LIKE`, `IMPLICIT_CAST_MISMATCH`,
`CARTESIAN_JOIN`.

---

## Tool 3 — `rewrite_query` *(the differentiator)*

Produce a semantically-equivalent, cheaper query and **prove it** by EXPLAIN-ing
both and comparing planner cost.

Input: `{ datasource_id, sql, apply_flags?: string[] }`

Output:
```jsonc
{
  "rewritten_sql": "SELECT id, total FROM orders WHERE created_at >= $1 ORDER BY created_at DESC LIMIT 50",
  "changes": [
    "Replaced SELECT * with the 2 columns actually projected",
    "Added LIMIT 50 to bound the result",
    "Recommend index: CREATE INDEX CONCURRENTLY ON orders (created_at)"
  ],
  "cost_before": 15629.12,
  "cost_after": 42.08,
  "cost_delta_pct": -99.7,                   // honest: this is PLANNER cost delta, not wall-clock
  "accuracy_tier": "UPPER_BOUND",
  "index_suggestions": [
    { "ddl": "CREATE INDEX CONCURRENTLY idx_orders_created_at ON orders (created_at)",
      "simulated_with": "hypopg", "simulated_cost_after": 42.08 }
  ],
  "equivalence_caveats": ["LIMIT changes row count; confirm the caller wanted all rows"]
}
```

Index what-if uses **HypoPG** (hypothetical indexes, no disk write) so "add this
index" is simulated against the real planner, not asserted.

---

## Tool 4 — `explain_working`

Teach, don't just flag. Plain-English walkthrough of *how* the query executes and
*why* it's slow on this schema — the "explain the working" Karan asked for.

Input: `{ datasource_id, sql }`
Output: ordered plan-node narration + the one sentence a dev needs:
> "Postgres can't use an index for `created_at > ...` because none exists, so it
> reads every one of the ~40M rows (a Seq Scan) just to find 12. Add the index
> and it jumps straight to them."

---

## What is deliberately NOT in the surface

- ❌ `run_query` / arbitrary execution — that's every other DB MCP; not our job, and it's the security-scary part.
- ❌ NL→SQL generation — commodity; the host agent already does it. We take the SQL it wrote.
- ❌ DB health reports (`analyze_db_health`) — that's Postgres MCP Pro's lane; we optionally *read* from it, we don't rebuild it.
- ❌ dollar/billing estimates — that's cost-guard-mcp's warehouse lane.

Staying out of these is the strategy, not a gap.

---

## The CLAUDE.md-killing demo (the thing you show a buyer)

1. Agent writes `SELECT * FROM orders WHERE created_at > now() - interval '7 days'`.
2. `preflight_query` → `risk_tier: expensive`, flag `MISSING_INDEX`, "scans 40M rows to return 12."
3. `rewrite_query` → projected columns + LIMIT + `CREATE INDEX CONCURRENTLY`, planner cost 15629 → 42, HypoPG-simulated.
4. The dev never shipped the N+1. A paragraph in CLAUDE.md could not have done steps 2–3 — they require the real schema and the real planner.
