# PostgreSQL

Status in the current development checkout: **Live-tested**.
Adapter implemented: yes. MCP runner connected: yes.
Input: SQL. Signal: EXPLAIN JSON. Evidence: Cached rows and unitless planner cost.

## Setup and routing

Read-only PostgreSQL DSN; psycopg is included.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Inspect actual schema and indexes before drafting SQL. Review sequential scan estimates, join amplification, projections and result bounds. A cached relation cardinality is not the same as filtered Plan Rows. A sequential scan can be the right choice for a broad filter.

For a selective simple predicate, rewrite_query may propose a quoted btree index. In the development checkout, an already-installed HypoPG extension can compare the SAME original SQL before/after a session-local hypothetical index. Never install the extension or a real index as part of preflight. Only claim improvement when successful simulation/candidate costs actually decreased; a proposal alone proves nothing. LIMIT remains an advisory semantic change.

Check: indexed and unindexed filters; selective versus broad predicates; joins; aggregate queries; no-statistics tables; HypoPG present/absent/failing. PostgreSQL planning and missing-HypoPG fallback have live evidence; a live HypoPG installation is still pending.
