# Setup: published baseline or development preparation

This skill covers all 12 implemented adapter families and their readiness
states. It cannot activate missing server runners. Its full catalog describes
the current development checkout, not a claim that every feature ships in the
published 0.2.1 package. Python 3.10+ and a local MCP-capable agent are required.
The server is independently installed, free and MIT licensed.

## Choose your server source

### Published baseline

The existing templates [assets/mcp-postgres.json](assets/mcp-postgres.json),
[assets/mcp-pgvector.json](assets/mcp-pgvector.json) and
[assets/mcp-offline.json](assets/mcp-offline.json) use uvx with
anumana-mcp==0.2.1. They pin a release; they do NOT pull unpublished changes.
Use these for the published PostgreSQL/pgvector/offline baseline and follow the
installed tool definitions. If uvx is not in the client's PATH, use its absolute
path. First launch downloads the package/dependencies from PyPI.

### Current development checkout (for preparation and testing)

Obtain the Anumana repository from https://github.com/sinhaKAN-ra/anumana and
use the checkout containing the intended changes. Uncommitted changes in a
maintainer's workspace are not available in a fresh public clone. Do not assume
cloning main obtains an unreleased feature before it has been pushed.

Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run
in that checkout:

```sh
uv sync --extra mysql --extra mongodb --extra dynamodb
```

Merge [assets/mcp-development.json](assets/mcp-development.json) into the
client's MCP settings and replace REPLACE_WITH_ANUMANA_CHECKOUT with the absolute
checkout path. It launches `uv run --no-sync anumana-mcp` in that checkout.
This template starts offline. For a connected engine, copy the env block from
one of the per-engine development templates:

- [SQLite](assets/mcp-sqlite-development.json): existing absolute file path.
- [MySQL/MariaDB](assets/mcp-mysql-development.json): local read-only DSN.
- [MongoDB](assets/mcp-mongodb-development.json): URI including database name.
- [DynamoDB](assets/mcp-dynamodb-development.json): region and local AWS chain.
- [Redshift](assets/mcp-redshift-development.json): PostgreSQL-wire DSN.
- [All connected engines](assets/mcp-multi-development.json): seven named targets;
  remove unused targets and replace every placeholder for those you retain.

Templates are examples for clients accepting mcpServers JSON. Other clients
need their own config syntax using the same command/arguments/environment.
Do not overwrite unrelated server settings. Do not fill credentials in this
package or commit filled config. Normal operator credential setup happens
locally, not through model tool arguments or chat.

BigQuery, Snowflake, ClickHouse, FalkorDB and Cassandra/Scylla have profiles and
adapter code but NO live server runner. No fabricated connection template is
provided for them. Adding their names to ANUMANA_TARGETS will not make live
calls work. Use prepared review mode until a future implementation is verified.

ANUMANA_DSN/ANUMANA_ENGINE are single-target settings; ANUMANA_TARGETS is a
JSON array encoded as an environment string. Avoid unrelated inherited DSN or
target settings when choosing a setup. list_targets shows the actual resolved
target names; do not infer readiness from diagnosable alone.

## Load the skill

For local-folder installation, extract all ZIP contents into a directory named
anumana-query-preflight in the client's documented skill directory. SKILL.md
must be directly inside that directory; keep SETUP.md, references/ and assets/
together. For Agensi delivery use its installation flow. Local extraction only
applies when you have obtained the package through an allowed distribution
method. Installing the skill does not install or register the MCP server.

Restart/reconnect the client. Confirm these nine tool names (possibly with a
client prefix): describe_schema_tool, preflight_query, preflight_vector_search,
preflight_schema_only, rewrite_query, suggest_query, explain_query_working,
list_targets, list_policies. There is no connect_schema, explain_working or
run_query tool.

## First check without a database

Call preflight_schema_only with:

```json
{
  "ddl": "CREATE TABLE orders (id bigint PRIMARY KEY, customer_id bigint, total numeric);",
  "sql": "SELECT * FROM orders"
}
```

Expect HEURISTIC findings, not a runtime or live plan. For connected engines,
select the intended target, describe its schema first, then preflight a native
SQL/JSON request. Do not execute a candidate as an installation test.

## Troubleshooting and updates

- Missing tools: inspect the local client's MCP launch log/executable path.
- Unsupported runner: consult the engine profile; package setup cannot fix it.
- Connection/permission error: resolve locally or provide schema artifacts;
  never paste credentials into chat.
- Parameter errors: tools accept SQL text without separate bind values. Unbound
  placeholders may fail planning. Use type-correct, non-sensitive representative
  literals when appropriate and disclose value-dependent plan limitations.
- No numeric cost: preserve the engine's evidence limits; zero is not free work.
- New release: explicitly update the server pin or checkout and skill package.
  Marketplace delivery does not update a local server configuration automatically.

For engine-by-engine validation and promotion, read
[references/verification.md](references/verification.md).
