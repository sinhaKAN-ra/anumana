# Google BigQuery

Status in the current development checkout: **Runner not wired; testing pending**.
Adapter implemented: yes. MCP runner connected: no.
Input: SQL. Signal: Dry-run byte estimates (adapter contract). Evidence: Prepared bytes signal; no live MCP runner.

## Setup and routing

Future runner needs project/dataset/location and read-only metadata plus dry-run access; no current config enables it.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

PREPARED MODE ONLY. list_targets can recognize the engine, but server runner resolution rejects live calls. Do not invoke another database target as a substitute. If the user provides schema, partitioning/clustering metadata or a dry-run plan, review it as supplied evidence; do not fabricate an Anumana tool result.

The adapter expects dry-run totalBytesProcessed and referencedTables. Future wiring must set dryRun explicitly and never submit an execution job. Projection and partition pruning are the key review topics; LIMIT is not evidence of fewer scanned bytes. No btree-index workflow applies.

The prototype contains a hard-coded byte-to-dollar conversion. Do not report its dollar figure as a verified current bill: pricing model, region, units, discounts and query type have not been validated. Generic core risk thresholds and the unitless cost label also need engine-specific integration. Pasted DDL can receive only a limited generic SQL heuristic check, not a BigQuery dry run.

Before enabling: wire safe dry-run and metadata calls, validate byte units and pricing configuration, normalize evidence labels, add live tests. All are pending.
