# Anumana — Design & Scope

> **Anumana** (Sanskrit: *inference, estimation*) — foresight for the queries AI
> agents write. Know what a query will cost, and understand how it behaves,
> *before* it runs.

Status: published package v0.2.1; core-roadmap improvements below are unreleased.
Audience for this doc: the maintainer (future self) and contributors.

---

## 1. The problem Anumana solves

AI coding agents (Claude, Cursor, Windsurf, Codex, Kiro) and AI *products*
(text-to-SQL copilots, "chat with your data", RAG apps, autonomous agents)
generate database queries constantly. **The agent has no feedback loop with the
real database.** It writes a query from the schema and its training priors, with
no idea whether that query:

- scans an entire 40M-row table because the filter isn't selective,
- fires a brute-force distance scan over every embedding (no vector index),
- over-fetches `top_k=1000` neighbours a prompt will never use,
- returns an unbounded result that floods the app.

A `CLAUDE.md` rule ("always add an index on filter columns") can't fix this —
it's **wrong half the time**, because correctness depends on real selectivity
against the live table, which only the planner's own stats can know.

**Anumana IS that missing feedback loop.** It asks the engine what it *would*
do — never runs the query — and translates the engine's own cost signal into:

1. a **risk tier** (cheap / moderate / expensive / dangerous),
2. **plain-English behaviour** (how the query actually executes), and
3. a **verified cheaper rewrite** (proven by re-planning, not asserted).

---

## 2. Scope — targeted at the queries AI AGENTS generate

We do **not** try to support "every database". We target the databases AI agents
*actually write queries against in production*, ranked by real agent-query
traffic:

| Priority | Workload | Engines | Why it's in scope |
|---|---|---|---|
| **P0 — built** | text-to-SQL | Postgres | the #1 agentic-query pattern |
| **P0 — built** | RAG / vector search | pgvector | RAG is the dominant AI workload; rides the PG plan path |
| **P1 — implemented** | text-to-SQL base | SQLite, MySQL/MariaDB | students/vibe coders use SQLite; same mechanism, new parser |
| **P2 — built** | NoSQL agents touch | MongoDB | `explain(queryPlanner)` → COLLSCAN vs IXSCAN, access-pattern diagnosis |
| **P2 — built** | serverless AI backends | DynamoDB | rule-based: no partition key = full Scan; surprise bills |
| **out of scope** | KV / graph | Redis, Neo4j, Cassandra | no pre-run cost concept to foresee — we refuse to fake one |

**Scope-defining line:** *Anumana is not a SQL tool — it's a "foresee query
cost" tool.* The asset is "read an engine's own cost signal and translate it."
Any engine that exposes a cost signal (planner, profiler, or predictable rule)
can get an adapter; any engine that doesn't, can't — and shouldn't be forced to.

---

## 3. The one rule everything obeys

**Never run the query.** For SQL/pgvector engines Anumana runs
`EXPLAIN (FORMAT JSON, VERBOSE)` — which *plans* the query and returns the
planner's cost estimate — and **never** `EXPLAIN ANALYZE`, which would execute
it. A read-only DSN is defence-in-depth on top of that.

**No fake milliseconds.** The planner cost is a *unitless* relative score, not a
time. Anumana structurally refuses to emit "this takes 3.2 s". Every estimate is
labelled `UPPER_BOUND` (live stats) or `HEURISTIC` (schema-only, no stats) —
never `PRECISE`.

**Determinism over cleverness.** Flags come from the plan tree + regexes you can
read and test, grounded in the planner's own numbers. No LLM guessing inside the
engine.

---

## 4. Architecture — the adapter pattern

```
                 ┌─────────────────────────────────────────────┐
   agent query → │  engine.py  (ENGINE-AGNOSTIC)                │
                 │   • risk tiering   • rewrite proof           │
                 │   • two-layer explain_working                │
                 └───────────────┬─────────────────────────────┘
                                 │ Adapter contract
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                        ▼
  PostgresAdapter         PgVectorAdapter          SqliteAdapter …
  EXPLAIN JSON            EXPLAIN JSON +            EXPLAIN QUERY PLAN
                          vector-specific flags
```

An **adapter** teaches Anumana how to read ONE engine's cost signal. It
implements four methods (`adapters/base.py`):

- `get_plan(run_sql, query) -> PlanResult` — ask the engine what it would do.
- `detect_flags(query, plan) -> [EngineFlag]` — deterministic overhead findings.
- `node_reason(node) -> str` — plain-English reason for one plan node.
- `headline(plan) -> str` — the one sentence about the dominant cost.

The risk/English/rewrite layers sit **on top** and never change when you add an
engine. `get_adapter(name)` resolves the registry and **fails loudly** on an
unsupported engine — we never silently pretend.

### Why pgvector inherits Postgres
A pgvector similarity search runs *inside* Postgres and produces an ordinary
EXPLAIN plan tree, so `PgVectorAdapter(PostgresAdapter)` reuses all the plumbing
and only **adds** vector-aware flags the generic SQL detector can't see.

---

## 5. Feature surface (built in v0.2)

### SQL (text-to-SQL) — `engine="postgres"`
- **`preflight_query`** — risk tier, rows scanned vs returned, scan strategy,
  overhead flags: `SEQ_SCAN_LARGE`, `NESTED_LOOP_BLOWUP`, `SELECT_STAR_WIDE`,
  `UNBOUNDED_RESULT`, `LEADING_WILDCARD_LIKE`, `FUNCTION_ON_INDEXED_COL`.
- **`rewrite_query`** — cheaper equivalent + proven cost delta, with the
  **selectivity gate**: only suggests a btree index when the filter returns
  ≤10% of scanned rows (the live-test lesson — "always index" is wrong when the
  filter matches most of the table).
- **`explain_query_working`** — two layers:
  1. *logical* gather order (FROM→WHERE→GROUP BY→HAVING→SELECT→ORDER BY→LIMIT) —
     universal, same in SQLite/MySQL; the teaching layer.
  2. *physical* plan the engine chose, walked bottom-up (leaves first), each node
     in plain English.

### RAG / vector search — `engine="pgvector"`
- **`preflight_vector_search`** — all of the above plus vector-specific flags:
  - `FULL_VECTOR_SCAN` — brute-force distance scan, no HNSW/IVFFlat index.
  - `TOP_K_TOO_LARGE` — `top_k` far above what a prompt uses (~50).
  - `UNBOUNDED_VECTOR_SEARCH` — similarity search with no LIMIT.
  - `VECTOR_FILTER_INTERACTION` — metadata filter + ANN can silently drop recall.
  - rewrite suggests an **HNSW index** (no selectivity gate — brute force always
    loses to ANN as the collection grows).
  - Honesty rail: pgvector's planner does **not** estimate recall; we flag the
    recall/cost knobs to verify, never invent a recall number.

### Offline front door — `preflight_schema_only`
Analyse a query against pasted `CREATE TABLE` DDL with **no DB connection**
(zero-trust trial). Catches `SELECT *`, missing LIMIT, un-indexed filter column,
leading wildcard, function-on-column. `HEURISTIC` only — no live stats, says so.

---

## 6. Distribution (how an agent "discovers" it)

There is **no plugin store an agent browses.** The flow is:

1. the **user** adds Anumana to their agent's MCP config (one JSON block),
2. on startup the agent calls `tools/list` and reads each tool's **description**,
3. when the user's request matches a description, the agent calls the tool.

So the **tool descriptions in `server.py` are the entire "SEO"** — they are
written to fire at the exact moment an agent generates a SQL query or a vector
search. Same `server.py` works in every MCP client; publish once to PyPI
(`anumana-mcp`), point each client's `mcpServers` block at it.

---

## 7. Core roadmap implementation (unreleased)

- SQLite and MySQL/MariaDB adapters and server runners are implemented. SQLite
  has automated end-to-end coverage against a temporary database, including
  quoted identifiers and enforced read-only file URIs. MySQL has a driver extra
  (`pip install 'anumana-mcp[mysql]'`), decoded DSNs and MySQL/MariaDB fixtures.
- MongoDB explicitly uses queryPlanner verbosity, never PyMongo's execution
  statistics default. Classic, SBE, branching and sharded winning-plan stages
  are recognized. Empty/unknown plans fail instead of looking cheap.
- DynamoDB request parsing uses JSON fields, not substring matches. Metadata
  discovery follows ListTables pagination. Query/Scan assessment remains an
  offline request-shape heuristic, not a key-validity or capacity-cost proof.
- Rewrite results expose failed/unavailable verification and semantic caveats.
  SQL LIMIT proposals are advisory and restricted to simple SELECT statements;
  non-SQL requests are never altered with SQL suffixes.
- Optional PostgreSQL HypoPG verification compares the original SQL before and
  after a hypothetical btree index in one dedicated connection. Proposals require
  a recognized simple predicate and catalog-backed selectivity. The extension
  must already be installed; no real index/extension is created by Anumana.
- Simple vector index proposals use the real relation/column and match the
  cosine, L2 or inner-product operator; HNSW benefits remain unverified.
- PostgreSQL explanation headlines rank local operator cost, avoiding cumulative
  Limit-wrapper ties. Heuristic engines no longer claim live row counts.
- Generic and vector preflight apply policies to the resolved target, including
  implicit selection of a single configured database.

## 8. Validation and remaining release gates

Run `.venv/bin/python -m pytest tests/` (after installing the dev dependencies).
Default checks use synthetic plans plus a real temporary SQLite database and
require no database credentials. Opt-in live checks are in `tests/test_live.py`;
setup and exact environment variables are in `docs/LIVE_VERIFICATION.md`.

A disposable PostgreSQL instance verified real filtered row estimates, SELECT
replanning, and the explicit missing-HypoPG fallback. HypoPG session isolation,
parameterized DDL and cleanup are covered by runner regression tests; a live
HypoPG installation is still needed to verify the extension end to end.

Remaining gates: live MySQL/MariaDB, MongoDB and DynamoDB smoke checks; live
HypoPG extension verification; pgvector recall/index behavior validation. Cloud
and other engines without server runners remain outside this core-roadmap pass.
Do not promote these engines to LIVE based on mocks. No package version bump or
publication is included. Update the marketplace skill and its pinned server
version after a release containing these changes is published.

---

## 9. Repo map

```
anumana/
├── DESIGN.md              ← this file (what we're building + why)
├── README.md              ← user-facing: install + one-paste MCP config
├── STRATEGY_BRIEF.md      ← positioning / market (private strategy)
├── TOOL_SURFACE.md        ← per-tool contract detail
├── MARKET_SIZING.md       ← market notes (private)
├── pyproject.toml         ← package: anumana-mcp, entry point anumana-mcp
├── src/
│   ├── demo.py            ← zero-dep proof (SQL + vector), run: python3 src/demo.py
│   ├── live_test.py       ← psql-backed proof against a real Postgres
│   └── anumana/
│       ├── engine.py      ← engine-agnostic risk / rewrite / explain_working
│       ├── schema_only.py ← offline DDL analysis
│       ├── server.py      ← MCP tools (the discovery surface)
│       └── adapters/
│           ├── base.py        ← Adapter contract + normalized dataclasses
│           ├── postgres.py    ← SQL EXPLAIN adapter
│           └── pgvector.py    ← RAG / vector-search adapter
```
