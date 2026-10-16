# ClickHouse

Status in the current development checkout: **Runner not wired; testing pending**.
Adapter implemented: yes. MCP runner connected: no.
Input: SQL. Signal: EXPLAIN ESTIMATE (adapter contract). Evidence: Prepared parts/marks/row estimates; no live MCP runner.

## Setup and routing

Future runner needs endpoint/auth/database settings and metadata access; no current MCP runner.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

PREPARED MODE ONLY. The adapter parses estimate-like results; the server cannot connect it to ClickHouse. Do not silently route this SQL to PostgreSQL or MySQL. Review supplied schema/plan as supplied evidence, with limitations.

Review selected parts, marks, rows, MergeTree sorting/primary keys, filters and projected columns. ClickHouse primary keys are sparse skipping structures; do not treat them as PostgreSQL unique btree lookup indexes. LIMIT may not avoid substantial reads or aggregation. Do not label row/mark counts as milliseconds or numeric optimizer costs.

Before enabling: wire EXPLAIN ESTIMATE and schema metadata, validate real output formats/table engines, distinguish absent estimates from zero work, and add live coverage for pruning and aggregation. No runner or live verification is complete.
