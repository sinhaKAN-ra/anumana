# FalkorDB

Status in the current development checkout: **Runner not wired; testing pending**.
Adapter implemented: yes. MCP runner connected: no.
Input: Cypher. Signal: GRAPH.EXPLAIN (adapter contract). Evidence: HEURISTIC access pattern; no row/cost estimates.

## Setup and routing

Future runner needs endpoint plus graph name; current server has no connection runner.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

PREPARED MODE ONLY. Use supplied graph labels, relationship types, index metadata and plan text for a manual review. Never send Cypher through the SQL DDL-only checker or to a relational target. GRAPH.EXPLAIN is the intended planner operation; GRAPH.PROFILE executes the query and is excluded.

Review full-node scans, labelled/index scans, Cartesian products and unbounded variable-length traversals. Preserve edge direction, path length, duplicate/path semantics and security filters when suggesting a change. A label scan need not be selective, and LIMIT does not automatically bound traversal work. Do not invent row counts.

Before enabling: wire explicit GRAPH.EXPLAIN plus disclosed metadata procedures, validate actual operator text and permissions, and test bounded traversal/indexed starts without executing candidate Cypher. No live connection or verification is recorded.
