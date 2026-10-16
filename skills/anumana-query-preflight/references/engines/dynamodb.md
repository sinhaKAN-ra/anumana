# DynamoDB

Status in the current development checkout: **Live testing pending**.
Adapter implemented: yes. MCP runner connected: yes.
Input: JSON Query/Scan request. Signal: Request-shape rules; metadata discovery. Evidence: HEURISTIC; no planner or capacity prediction.

## Setup and routing

AWS region and local credential chain; optional profile; dynamodb extra.

Read the installed tool signatures and errors; this snapshot does not guarantee
the same behavior in published 0.2.1 or another installed release.

## Review workflow and remaining checks

Supply a JSON request, e.g. {"op":"Query","TableName":"orders","KeyConditionExpression":"pk = :p","Limit":50}. The sql parameter carries this JSON. Read actual key/index schema with describe_schema_tool first; ListTables/DescribeTable are metadata operations. Never send Query or Scan for cost measurement.

A Scan still reads before FilterExpression is applied. Presence of KeyConditionExpression does not prove it uses the real partition key, and the current adapter cannot validate every expression. Check the full key schema, aliases and GSI/LSI access pattern yourself. A Limit bounds one page of evaluated items, not all pagination; a filter does not reduce the reads already performed. Do not call a keyed request necessarily cheap in dollars.

Refine the request shape without SQL LIMIT or fabricated capacity estimates. Keep accuracy HEURISTIC. Live verification covers metadata permissions, pagination and key descriptions; no data-plane execution is needed. That live metadata check is pending.
