# Core-engine verification

The default suite needs no external service. Install the development dependencies
and run `pytest tests/`. It includes a real temporary SQLite database and mocked
planner/driver regressions. Live checks use only planner or metadata operations
against existing databases; they do not create fixture tables, execute candidate
queries, install extensions or create real indexes.

Keep connection values in your local environment, never in source control or
chat. Use read-only accounts. The optional drivers are:

```sh
pip install -e '.[dev,mysql,mongodb,dynamodb]'
```

## PostgreSQL and HypoPG

Set ANUMANA_TEST_POSTGRES_DSN locally. Optionally set ANUMANA_TEST_POSTGRES_SQL
to one SELECT against an existing table; the default SELECT 1 checks connection
and planning only. Run:

```sh
pytest tests/test_live.py::test_live_postgres_planner -q
```

For an index-benefit check, use a selective, simple equality/range predicate on
an unindexed column of a table with cached catalog statistics. HypoPG must
already be installed by the operator. Anumana will not install it. Review
index_suggestions for `simulation_status=verified`, `hypothetical_index_used`
and `verified_cheaper`, not just the existence of a suggestion. An unsupported
predicate or an index the planner does not choose need not produce savings.

Hypothetical indexes live only in a dedicated connection. The runner EXPLAINs
the original SQL before and after, calls hypopg_reset, and closes the connection.
No actual user query or physical index is executed/created. Candidate LIMIT
replanning is separate and carries a row-count caveat.

References: https://hypopg.readthedocs.io/en/rel1_stable/usage.html

## MySQL / MariaDB

Set ANUMANA_TEST_MYSQL_DSN locally, using mysql:// or mariadb:// syntax.
Optionally set ANUMANA_TEST_MYSQL_SQL to a SELECT on an existing table; default
SELECT 1 verifies connection/planning only. Run:

```sh
pytest tests/test_live.py::test_live_mysql_planner -q
```

Verify MySQL and MariaDB separately before claiming both live-tested. MariaDB
may provide row estimates without query_cost; unavailable optimizer cost is not
zero-cost work and cannot establish a numeric rewrite improvement.

## MongoDB

Set ANUMANA_TEST_MONGODB_URI (including the database name) and
ANUMANA_TEST_MONGODB_QUERY to a JSON find request on an existing collection.
Run:

```sh
pytest tests/test_live.py::test_live_mongo_queryplanner -q
```

The check explicitly requests queryPlanner and rejects executionStats output.
Choose separate known indexed and unindexed filters to validate both IXSCAN and
COLLSCAN against your engine version. A queryPlanner access pattern is not a
row estimate. Schema discovery separately samples one document per collection;
this is disclosed and not metadata-only.

References:
https://pymongo.readthedocs.io/en/4.19.0/api/pymongo/cursor.html
https://www.mongodb.com/docs/manual/reference/command/explain/

## DynamoDB

Set ANUMANA_TEST_DYNAMODB_REGION and optionally
ANUMANA_TEST_DYNAMODB_PROFILE locally, using your normal AWS credential chain.
The account needs ListTables and DescribeTable, not data-plane Query/Scan access.
Run:

```sh
pytest tests/test_live.py::test_live_dynamo_metadata -q
```

This verifies live metadata discovery only. Candidate Query/Scan requests are
assessed offline and never sent to AWS. Key-condition presence is not proof of
a valid partition-key expression, bounded pagination or a read-capacity estimate.

## Recorded evidence for this development pass

- SQLite: actual temporary DB; schema/index discovery, indexed plan and enforced
  read-only URI verified by automated tests.
- PostgreSQL 17: isolated temporary DB with a 200,000-row fixture; selective
  filter estimated 20 returned rows and 200,000 scanned; candidate replanning
  and explicit missing-HypoPG fallback verified.
- HypoPG: session/cost comparison, parameterized DDL and failure cleanup verified
  with mocked driver sessions. Live extension verification is still pending.
- MySQL/MariaDB, MongoDB, DynamoDB: unit/driver regressions added; live service
  checks remain pending. Do not set verified_live based on these fixtures.

Before publication, run the applicable live checks, retain their outcomes, and
update SUPPORTED_ENGINES.md only for evidence actually obtained. Publish the MCP
release separately, then update the Agensi skill's pinned version and rebuild
its ZIP. The existing package remains pinned to published 0.2.1 until then.
