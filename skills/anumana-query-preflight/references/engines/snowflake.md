# Snowflake

Status in the current development checkout: **Runner not wired; testing pending**.
Adapter implemented: yes. MCP runner connected: no.
Input: SQL. Signal: EXPLAIN USING JSON (adapter contract). Evidence: Prepared partition/byte estimates; no live MCP runner.

## Setup and routing

Future runner needs account/role/warehouse/database/schema configuration; not accepted by the current runner.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

PREPARED MODE ONLY. The adapter exists but the MCP server has no Snowflake connection runner. Use user-supplied schema/plan for a clearly labelled manual review or explain that live planning is unavailable. Do not claim configuration alone activates the integration.

Review partition pruning, assigned versus total partitions, projected columns and join fan-out. Do not translate partition/byte counts into runtime or credit charges. Snowflake physical design differs from PostgreSQL: clustering/materialized-design proposals require a separate workflow; do not recommend btree indexes or HypoPG.

Before enabling: implement metadata access and EXPLAIN USING JSON only, validate actual plan shape/privileges/warehouse context and cost units, verify pruning and joins against a live account. No execution, profiling, or query-history benchmarking is part of this skill. Live verification is pending.
