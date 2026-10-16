# pgvector

Status in the current development checkout: **Live testing pending**.
Adapter implemented: yes. MCP runner connected: yes.
Input: SQL. Signal: PostgreSQL EXPLAIN + vector flags. Evidence: Unitless planner cost; no recall estimate.

## Setup and routing

PostgreSQL with pgvector; target engine must be pgvector.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Use preflight_vector_search for direct distance ordering and preflight_query for the policy verdict if the installed vector tool omits policy. Preserve the tenant/security filter. Review FULL_VECTOR_SCAN, TOP_K_TOO_LARGE, UNBOUNDED_VECTOR_SEARCH and VECTOR_FILTER_INTERACTION without inventing recall percentages.

Match cosine <=> to vector_cosine_ops, L2 <-> to vector_l2_ops, and inner product <#> to vector_ip_ops for ordinary vector columns. Other storage types need their matching operator classes. Changing exact search to ANN can change results. HypoPG does not verify HNSW benefits. Do not accept an index placeholder as executable DDL.

Check: each metric; exact/no-index versus HNSW and IVFFlat; small/large top-k; metadata filters; incompatible dimensions/types. Do not run retrieval to measure recall in this planner-only workflow. Live verification is pending.
