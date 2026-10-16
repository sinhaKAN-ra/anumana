# Test engines one at a time

Preparation is complete only for instructions/configs, not proof of live support.
The catalog records implementation, connection wiring and live evidence separately.
Never promote an engine from mocks or a successful tools/list response alone.

## Per-engine evidence record

For each engine, record these locally without credentials:

- Server/adapter version or source commit; database version and deployment type.
- Runner availability, connection method and read-only permissions.
- Schema/key/index discovery outcome and its sampling/metadata limitations.
- Native request used, planner/access-pattern evidence, flags, accuracy and units.
- Indexed/keyed versus scan case, bounded versus unbounded case, and relevant
  joins/filter/partition/recall caveats. No candidate executions.
- Unsupported inputs and error handling; evidence of planner-only API use.
- Pass/fail/pending per scenario and remaining limitations. Retain redacted output.

Start with the relevant engine profile. Update engine-status.json, engines.md and the profile
only after reviewing evidence. The existing adapter verified_live attribute and
SUPPORTED_ENGINES.md must agree with a promoted state. Publishing a new MCP
release and updating marketplace users are separate actions.

## Available repository checks

From a prepared development checkout:

```sh
uv sync --extra dev --extra mysql --extra mongodb --extra dynamodb
uv run --no-sync pytest tests/
```

The default suite uses synthetic plans plus real local SQLite checks. Existing
opt-in live tests use local ANUMANA_TEST_* settings and existing service objects:

- PostgreSQL: ANUMANA_TEST_POSTGRES_DSN and optional ANUMANA_TEST_POSTGRES_SQL.
- MySQL/MariaDB: ANUMANA_TEST_MYSQL_DSN and optional ANUMANA_TEST_MYSQL_SQL.
- MongoDB: ANUMANA_TEST_MONGODB_URI and ANUMANA_TEST_MONGODB_QUERY (JSON find).
- DynamoDB metadata: ANUMANA_TEST_DYNAMODB_REGION and optional
  ANUMANA_TEST_DYNAMODB_PROFILE. The normal local AWS credential chain applies.

Keep connection values outside chat/source. Run `pytest tests/test_live.py`
only for configured services. Tests skip when absent; a skip is not a pass.
Repository docs/LIVE_VERIFICATION.md gives further setup details.

## Remaining scenarios by engine

- PostgreSQL: live HypoPG installed/absent/permission/failure cases; same-SQL cost
  comparison and index selection; no real index creation. Base PG planner and
  missing-extension fallback already have live evidence.
- SQLite: retain real temporary-file regression coverage; extend to your SQLite
  version, unusual schema names and representative sorting/join patterns.
- pgvector: validate all three metrics, HNSW/IVFFlat/exact plans and filter flags;
  test planning only. Recall measurement belongs to a separately authorized task.
- MySQL AND MariaDB: validate each version/format separately; cost-info absence,
  full/index scans, joins, sorting, schema metadata and native DSNs.
- MongoDB: queryPlanner API only; classic/SBE/sharded plans, JSON options,
  projection/limit semantics and disclosed schema sampling.
- DynamoDB: actual key/GSI/LSI descriptions and metadata pagination; no Query/Scan
  data calls. Request classification remains heuristic, not key-expression proof.
- Redshift: verify text parsing, schema catalogs, runner/session settings,
  distribution flags and SELECT planner-only access on an actual cluster.
- BigQuery: implement a safe dry-run/metadata runner first; validate byte and
  price units/configuration before reporting money. Current server rejects it.
- Snowflake: implement safe metadata/EXPLAIN runner, normalize actual partition/
  byte evidence and validate privileges/context. Current server rejects it.
- ClickHouse: implement metadata/EXPLAIN ESTIMATE runner, validate result formats
  and parts/marks/rows semantics. Current server rejects it.
- FalkorDB: implement GRAPH.EXPLAIN/metadata runner; never GRAPH.PROFILE. Validate
  operators, traversal bounds and schema/index descriptions.
- Cassandra/Scylla: implement metadata runner and correct the prototype's partial
  composite-key matching before relying on it. Validate both engines separately;
  do not introduce a pretend EXPLAIN or execute CQL to obtain a cost.

Unwired-engine preparation does not authorize implementing runners, deploying
services or spending money in a user's query-review task. Report missing support
and keep the prepared checklist ready for a separately requested development pass.
