# Amazon Redshift

Status in the current development checkout: **Live testing pending**.
Adapter implemented: yes. MCP runner connected: yes.
Input: SQL. Signal: Text EXPLAIN. Evidence: Estimated rows and relative plan cost.

## Setup and routing

Read-only Redshift PostgreSQL-wire DSN; existing runner path is unverified.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Use the redshift engine, not postgres, because its planner response is text rather than PostgreSQL FORMAT JSON. Review DS_BCAST and DS_DIST redistribution/broadcast operators, join keys and table distribution/sort design.

Do not recommend PostgreSQL btree CREATE INDEX or HypoPG for Redshift. A DISTKEY/SORTKEY/table-design proposal is a separate schema workflow. LIMIT does not eliminate upstream joins or data redistribution. Preserve aggregates, ordering and distribution semantics when drafting a new candidate and re-preflight it.

Check real text output parsing, distribution flags, connection settings, and schema discovery independently: a PostgreSQL-wire connection is not evidence that every PostgreSQL catalog query works on Redshift. The inherited catalog reader and runner settings still need real-service validation. No live evidence is recorded.
