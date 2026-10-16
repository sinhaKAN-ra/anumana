# Supported engines

Anumana diagnoses the queries AI agents write across many databases through one
small [adapter contract](src/anumana/adapters/base.py). An engine qualifies for
an adapter **only if it exposes a cost signal** — a planner, a profiler, or a
deterministic rule — that can be read *without running the query*. If it can't,
Anumana refuses to fake one.

Each adapter carries a `verified_live` flag. **`LIVE` means the adapter has been
exercised end-to-end against a real instance of that engine. `UNTESTED` means
the plan-parsing logic is written and unit-checked offline, but not yet confirmed
against live engine output** — treat its results as provisional until promoted.
Engines are promoted to `LIVE` one at a time as each is connected and tested.

| Engine | Paradigm | Cost signal | Status |
|---|---|---|---|
| **Postgres** | Relational (SQL) | `EXPLAIN (FORMAT JSON)` | ✅ LIVE |
| **SQLite** | Relational (embedded) | `EXPLAIN QUERY PLAN` | ✅ LIVE |
| **MySQL / MariaDB** | Relational (SQL) | `EXPLAIN FORMAT=JSON` | 🧪 UNTESTED |
| **pgvector** | Vector / RAG | `EXPLAIN` on ANN search | 🧪 UNTESTED |
| **MongoDB** | Document | `explain("queryPlanner")` | 🧪 UNTESTED |
| **DynamoDB** | Key-value / serverless | rule-based (key schema) | 🧪 UNTESTED |
| **FalkorDB** | Graph (Cypher) | `GRAPH.EXPLAIN` | 🧪 UNTESTED |
| **Cassandra / ScyllaDB** | Wide-column | rule-based (partition key) | 🧪 UNTESTED |
| **Amazon Redshift** | MPP warehouse | text `EXPLAIN` (Postgres-wire) | 🧪 UNTESTED |
| **Google BigQuery** | Serverless warehouse | **dry-run → bytes → $ cost** | 🧪 UNTESTED |
| **Snowflake** | Cloud warehouse | `EXPLAIN USING JSON` | 🧪 UNTESTED |
| **ClickHouse** | OLAP | `EXPLAIN ESTIMATE` | 🧪 UNTESTED |

## Server connection availability

Live-runner wiring is separate from verification status. PostgreSQL, pgvector,
SQLite, MySQL/MariaDB, MongoDB, DynamoDB and Redshift have server runner paths.
BigQuery, ClickHouse, Snowflake, FalkorDB and Cassandra/Scylla adapters are not
connected to live runners in the MCP server and fail explicitly. Do not advertise
those adapters as end-to-end integrations.

Unreleased core-roadmap changes include optional PostgreSQL HypoPG btree
simulation, explicit Mongo queryPlanner verbosity, structured Dynamo request
parsing, and honest rewrite verification fields. See
[tool contract](TOOL_SURFACE.md) and [live verification](docs/LIVE_VERIFICATION.md).
MySQL's optional driver is installed with `anumana-mcp[mysql]` in this checkout;
it requires a future release before that extra is available from PyPI.

## Honesty rails

- **Heuristic vs live counts.** Postgres/MySQL/Redshift/BigQuery/Snowflake/
  ClickHouse expose real row/byte/partition estimates (`has_live_stats=True`).
  SQLite/Mongo/FalkorDB/Cassandra expose only the *access pattern* (indexed vs
  full scan) — Anumana reports that and says it has no live counts, rather than
  inventing numbers.
- **EXPLAIN, never ANALYZE / PROFILE.** No adapter executes the agent's query.
  The unwired BigQuery adapter models a dry run; FalkorDB uses `GRAPH.EXPLAIN`, not
  `GRAPH.PROFILE`.
- **BigQuery is not live-wired:** its offline adapter can model bytes and pricing,
  but the server cannot currently perform that dry run. Do not advertise a live
  dollar estimate or assume a hard-coded price is current.

## Not supported (by design)

| Engine | Why not |
|---|---|
| **Redis** (plain KV) | No query planner and no predictable rule to read a cost from. |
| **Pinecone / managed vector APIs** | Black-box similarity API — no plan, no cost signal to inspect. Query *shape* can be linted, but a cost can't be read. |

## Adding an engine

Implement the six methods in [`adapters/base.py`](src/anumana/adapters/base.py)
(`get_plan`, `detect_flags`, `node_reason`, `headline`, `describe_schema`, plus
`name`/`label`/`verified_live`), register it in
[`adapters/__init__.py`](src/anumana/adapters/__init__.py), and wire a live
runner in [`server.py`](src/anumana/server.py). See
[CONTRIBUTING.md](CONTRIBUTING.md).
