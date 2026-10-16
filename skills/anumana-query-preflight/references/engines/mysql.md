# MySQL / MariaDB

Status in the current development checkout: **Live testing pending**.
Adapter implemented: yes. MCP runner connected: yes.
Input: SQL. Signal: EXPLAIN FORMAT=JSON. Evidence: Estimated rows; optimizer cost only when supplied.

## Setup and routing

mysql:// or mariadb:// read-only DSN; current checkout mysql extra.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Read information_schema metadata for the selected database. Inspect ALL, index, ref, eq_ref, range, index_merge, nested-loop and sorting behavior. ALL denotes a table scan; index can mean a full index scan, not a selective lookup.

MySQL and MariaDB plan JSON differs. Row estimates may exist without query_cost. Use planner_cost_available when present and inspect actual response evidence on older releases. Never turn a missing/invalid query_cost into a claimed numeric improvement. Avoid applying PostgreSQL index syntax or HypoPG to this engine.

Check separately on MySQL and MariaDB: indexed/full scans, joins, LIMIT, sorts, schema discovery, escaped DSN characters, JSON with/without cost_info. Both live checks remain pending; do not promote MariaDB solely from a MySQL result.
