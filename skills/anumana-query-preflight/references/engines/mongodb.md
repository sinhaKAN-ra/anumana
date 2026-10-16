# MongoDB

Status in the current development checkout: **Live testing pending**.
Adapter implemented: yes. MCP runner connected: yes.
Input: JSON find request. Signal: explain with queryPlanner verbosity. Evidence: HEURISTIC access pattern; no row/cost estimates.

## Setup and routing

MongoDB URI including a database; current checkout mongodb extra.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Pass JSON find commands through the sql parameter, not SQL or shell method chains. Supported find fields are find, filter, projection, sort, limit, skip, hint, collation and maxTimeMS. Example: {"find":"orders","filter":{"status":"paid"},"projection":{"_id":1},"limit":20}. Unknown command shapes should be rejected, not forwarded.

The safe runner uses database.command with verbosity=queryPlanner. PyMongo Cursor.explain defaults can include execution statistics: do not use it as a substitute. Inspect COLLSCAN, IXSCAN, FETCH, SORT and branching/sharded/SBE winning plans. queryPlanner gives access patterns, not measured document counts. A zero limit is unbounded. Mongo schema discovery samples a document per collection; disclose that data access.

Never append SQL LIMIT or SQL index DDL to a Mongo request. Refine JSON fields manually, preserve matching/projection semantics, and re-preflight. Index suggestions are proposals, not actions. Check classic/SBE/sharded plans and supported find fields on a real service before live promotion.
