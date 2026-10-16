# Cassandra / ScyllaDB

Status in the current development checkout: **Runner not wired; testing pending**.
Adapter implemented: yes. MCP runner connected: no.
Input: CQL + actual key schema. Signal: Partition-key request-shape rules. Evidence: HEURISTIC; no EXPLAIN or cost estimate.

## Setup and routing

Future runner needs cluster/keyspace metadata; current server has no CQL runner.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

PREPARED MODE ONLY. Cassandra/ScyllaDB has no EXPLAIN path in Anumana. Review CQL alongside user-supplied partition and clustering keys; do not submit it to SQL schema-only tools as a planner substitute.

Require ALL components of a composite partition key to be constrained appropriately before describing a single-partition access path. The prototype adapter checks overlap with filtered columns, which is insufficient proof. Review equality versus ranges, IN fan-out, ALLOW FILTERING, large partitions, clustering order and index-dependent access. A WHERE clause alone says nothing about correct partition routing.

Do not use tracing, execution, or paging through data to estimate cost. A LIMIT does not guarantee small cluster work. Before enabling: wire read-only system_schema metadata, correct full composite-key classification, validate Cassandra and Scylla separately, and add real-service checks. All live wiring/testing remains pending.
