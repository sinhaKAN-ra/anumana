# Decision scenarios

These examples describe expected decisions, not observed database results.

## Review an existing all-rows export

Request: "Check this export before we ship it. Every matching row is required."

Inspect the live schema, then preflight the supplied SQL. If a rewrite adds
LIMIT 100, reject that change because it truncates the export. Preserve required
columns and row count. Explain actual scan/selectivity findings and propose an
index only as an unverified schema change. Recheck any semantics-preserving
candidate. If no acceptable candidate is found in three rounds, report the
remaining risk instead of promising a cheaper equivalent.

## Generate a PostgreSQL endpoint query

Request: "Return the latest 20 orders for this customer."

Describe the schema first; verify names and relationships. Draft explicit
required columns, the customer predicate, and the requested ordering/LIMIT.
Use an appropriate tie-breaker if stable ordering is required. Grade with
suggest_query using the actual user intent. A cheap candidate with a policy
block still cannot pass. A cost acceptance alone does not verify correctness or
authorize execution.

## Review a pgvector retrieval query

Request: "Check our top-10 semantic search with a tenant filter."

Select a pgvector target, inspect schema and indexes, then use the vector
preflight and generic preflight policy check. Match the index operator class to
the actual metric. Discuss filter/ANN recall interaction without inventing a
recall percentage. Do not increase top-k, remove tenant isolation, or change
exact search into approximate search simply to make the cost look better.
Recheck the final SQL after an authorized change.

## Offline review

Request: "Here is my DDL and query. I cannot share database access."

Call preflight_schema_only directly. Explain heuristic findings and distinguish
DDL-declared indexes from live planner behavior. Offer a candidate preserving
intent and recheck it against the DDL; do not report actual row estimates,
planner-cost reductions, runtime predictions, or live verification.

## Tool failure or missing setup

If tools are absent, read SETUP.md and explain local registration. If a tool
returns an error, do not treat the absence of flags as success. Resolve only
within authorized configuration scope or stop and report what is missing.

## Provisional MongoDB review

Request: "Review this find request; Mongo hasn't been live-tested yet."

Load the MongoDB engine profile. Select the matching connected target and inspect
schema/index metadata first, disclosing document sampling. Pass the native JSON
through preflight_query's sql argument. Treat returned winning-plan signals as
provisional evidence, not measured counts. If refinement is needed, preserve the
filter/projection semantics and change JSON manually; do not call a SQL LIMIT
proposal a Mongo rewrite. Stop on unsupported fields or connection errors.

## Prepare an unwired cloud database

Request: "Review our BigQuery query before we enable its integration."

Load the BigQuery profile and report that the MCP runner is not wired. Review
supplied schema, partition/clustering information and any supplied dry-run
artifact as supplied evidence. Missing artifacts mean missing evidence, not a
zero-cost query. Do not request credentials, configure a pretend runner, quote
the adapter's hard-coded price as current billing, or route to PostgreSQL.
Record the next implementation/test gates from the profile.

## Composite partition-key review

Request: "Is this Scylla query restricted to one partition?"

Load the Cassandra/Scylla profile. Require the actual full partition key and CQL
restrictions, then review every component. One matching column is insufficient
for a composite key. The adapter prototype and missing runner cannot prove this
live; label the review manual/heuristic and record what must be fixed/tested.
