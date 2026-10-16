# SQLite

Status in the current development checkout: **Live-tested**.
Adapter implemented: yes. MCP runner connected: yes.
Input: SQL. Signal: EXPLAIN QUERY PLAN. Evidence: HEURISTIC access pattern; no numeric cost.

## Setup and routing

Absolute path to an existing SQLite file; Python stdlib sqlite3.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Inspect sqlite_master and PRAGMA catalog results first. Distinguish SEARCH using an index from SCAN, and inspect temporary B-trees for ordering/grouping. An index scan can still visit an entire index: its existence alone is not proof of cheapness.

EXPLAIN QUERY PLAN has no numeric row/cost estimates. Treat zero legacy numeric fields as unavailable, not free work. Replanning may verify a changed access path but cannot prove a numeric cost reduction. The development runner forces mode=ro even when a supplied file URI contains mode=rw. Do not create a missing database file.

Check: quoted table/index names, primary-key lookup, full scan, index-assisted filter, sorting, read-only paths and file URIs. Real temporary-file planning and metadata checks pass; the marketplace package must distinguish this checkout evidence from published-release behavior.
