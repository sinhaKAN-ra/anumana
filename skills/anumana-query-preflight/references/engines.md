# Engine catalog and readiness

Snapshot: current development checkout. This is not a promise that published
0.2.1 includes every runner or unreleased safety/rewrite improvement.

All 12 adapter families are prepared in this skill. PostgreSQL and SQLite have
live evidence; the other ten remain unverified. Seven runners are connected;
five adapters cannot be used live through this MCP server yet. Read the matching
profile before choosing tools.

## PostgreSQL

- Adapter: implemented. MCP runner: connected. Test status: Live-tested.
- Engine key: `postgres`. Aliases: postgresql, pg.
- Input: SQL. Signal: EXPLAIN JSON.
- Evidence: Cached rows and unitless planner cost.
- [Engine workflow and remaining checks](engines/postgres.md).

## pgvector

- Adapter: implemented. MCP runner: connected. Test status: Live testing pending.
- Engine key: `pgvector`. Aliases: vector.
- Input: SQL. Signal: PostgreSQL EXPLAIN + vector flags.
- Evidence: Unitless planner cost; no recall estimate.
- [Engine workflow and remaining checks](engines/pgvector.md).

## SQLite

- Adapter: implemented. MCP runner: connected. Test status: Live-tested.
- Engine key: `sqlite`. Aliases: sqlite3.
- Input: SQL. Signal: EXPLAIN QUERY PLAN.
- Evidence: HEURISTIC access pattern; no numeric cost.
- [Engine workflow and remaining checks](engines/sqlite.md).

## MySQL / MariaDB

- Adapter: implemented. MCP runner: connected. Test status: Live testing pending.
- Engine key: `mysql`. Aliases: mariadb.
- Input: SQL. Signal: EXPLAIN FORMAT=JSON.
- Evidence: Estimated rows; optimizer cost only when supplied.
- [Engine workflow and remaining checks](engines/mysql.md).

## MongoDB

- Adapter: implemented. MCP runner: connected. Test status: Live testing pending.
- Engine key: `mongodb`. Aliases: mongo.
- Input: JSON find request. Signal: explain with queryPlanner verbosity.
- Evidence: HEURISTIC access pattern; no row/cost estimates.
- [Engine workflow and remaining checks](engines/mongodb.md).

## DynamoDB

- Adapter: implemented. MCP runner: connected. Test status: Live testing pending.
- Engine key: `dynamodb`. Aliases: dynamo.
- Input: JSON Query/Scan request. Signal: Request-shape rules; metadata discovery.
- Evidence: HEURISTIC; no planner or capacity prediction.
- [Engine workflow and remaining checks](engines/dynamodb.md).

## Amazon Redshift

- Adapter: implemented. MCP runner: connected. Test status: Live testing pending.
- Engine key: `redshift`. Aliases: none.
- Input: SQL. Signal: Text EXPLAIN.
- Evidence: Estimated rows and relative plan cost.
- [Engine workflow and remaining checks](engines/redshift.md).

## Google BigQuery

- Adapter: implemented. MCP runner: not wired. Test status: Runner not wired; testing pending.
- Engine key: `bigquery`. Aliases: bq.
- Input: SQL. Signal: Dry-run byte estimates (adapter contract).
- Evidence: Prepared bytes signal; no live MCP runner.
- [Engine workflow and remaining checks](engines/bigquery.md).

## Snowflake

- Adapter: implemented. MCP runner: not wired. Test status: Runner not wired; testing pending.
- Engine key: `snowflake`. Aliases: none.
- Input: SQL. Signal: EXPLAIN USING JSON (adapter contract).
- Evidence: Prepared partition/byte estimates; no live MCP runner.
- [Engine workflow and remaining checks](engines/snowflake.md).

## ClickHouse

- Adapter: implemented. MCP runner: not wired. Test status: Runner not wired; testing pending.
- Engine key: `clickhouse`. Aliases: none.
- Input: SQL. Signal: EXPLAIN ESTIMATE (adapter contract).
- Evidence: Prepared parts/marks/row estimates; no live MCP runner.
- [Engine workflow and remaining checks](engines/clickhouse.md).

## FalkorDB

- Adapter: implemented. MCP runner: not wired. Test status: Runner not wired; testing pending.
- Engine key: `falkordb`. Aliases: falkor.
- Input: Cypher. Signal: GRAPH.EXPLAIN (adapter contract).
- Evidence: HEURISTIC access pattern; no row/cost estimates.
- [Engine workflow and remaining checks](engines/falkordb.md).

## Cassandra / ScyllaDB

- Adapter: implemented. MCP runner: not wired. Test status: Runner not wired; testing pending.
- Engine key: `cassandra`. Aliases: scylla, scylladb.
- Input: CQL + actual key schema. Signal: Partition-key request-shape rules.
- Evidence: HEURISTIC; no EXPLAIN or cost estimate.
- [Engine workflow and remaining checks](engines/cassandra.md).

## Outside the adapter catalog

Plain Redis and managed vector APIs such as Pinecone do not have an Anumana
adapter in this checkout. Do not infer support from a shared protocol or query
language. If a user supplies artifacts, provide only a clearly labelled manual
review within the request; do not invent Anumana tools or planner numbers.
