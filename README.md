# Anumana

**Know what your query will cost — before you run it.**
*Inference-grade foresight for every query your AI writes.*

Anumana is an [MCP](https://modelcontextprotocol.io) server that catches the
costly query your AI coding agent just wrote — *before* it runs or reaches a PR.
It rides inside Claude, Cursor, Windsurf, Codex, Kiro, or any MCP-compatible
agent, reads your **real schema** via `EXPLAIN` (never `EXPLAIN ANALYZE`), and
tells you — in plain English — how the query behaves and whether it'll hurt.

Its scope is **the queries AI agents actually generate**: text-to-SQL today, and
**RAG / vector search (pgvector)** alongside it — because an agent writing a
similarity search has no idea it just triggered a brute-force scan over every
embedding. Anumana is the feedback loop the agent is missing.

It is **not** another NL→SQL tool and **not** a DB-health dashboard. It does one
job: stop AI-written database code from silently rotting production.

---

## What it does (the features)

| Tool | What it answers |
|---|---|
| **`preflight_query`** | *"Will this SQL query be costly?"* — risk tier (cheap/moderate/expensive/dangerous), rows scanned vs returned, scan strategy, and overhead flags. Without running it. |
| **`preflight_vector_search`** | *"Will this RAG similarity search be costly?"* — catches the vector traps a plain SQL check misses: brute-force scan with no HNSW/IVFFlat index, `top_k` too large, unbounded search, metadata-filter/ANN recall loss. |
| **`rewrite_query`** | *"Make it cheaper."* — a verified equivalent rewrite with before/after planner cost, plus index suggestions **gated on selectivity** (won't tell you to index a column when the filter matches most of the table). `engine="pgvector"` suggests an HNSW index. |
| **`explain_query_working`** | *"How does this run?"* — two layers: the **logical gather order** (FROM → WHERE → GROUP BY → HAVING → SELECT → ORDER BY → LIMIT) and the **actual physical plan** for your schema, step by step. |
| **`preflight_schema_only`** | *"I haven't given you DB creds yet."* — static analysis against pasted `CREATE TABLE` DDL, no connection. Offline, zero-trust front door. |

> **Engines (12, across 7 paradigms):** Postgres and SQLite are **live-tested**;
> MySQL, pgvector, MongoDB, DynamoDB, FalkorDB, Cassandra, Redshift, BigQuery,
> Snowflake and ClickHouse ship as **offline-verified, untested** adapters that
> are promoted to live one at a time. Full matrix + cost signals in
> [SUPPORTED_ENGINES.md](SUPPORTED_ENGINES.md). The adapter interface is in
> [DESIGN.md](DESIGN.md).

### The one honest rule
Postgres planner cost is **unitless — not milliseconds** ([docs](https://www.postgresql.org/docs/current/using-explain.html)).
Anumana never fakes a `~3.2s` number. It reports rows scanned, scan strategy, a
risk tier, overhead flags, and the cost-delta of a rewrite — all defensible,
nothing invented. Every estimate carries an accuracy tier (`UPPER_BOUND` live,
`HEURISTIC` schema-only).

---

## Install

```bash
pip install anumana-mcp          # once published to PyPI
# or from source:
pip install -e .
```

Then point your agent at it. **The user installs it; the agent discovers the
tools automatically** on connect via the MCP `tools/list` handshake — there is
no store to publish into.

### Claude Desktop / Cursor / Windsurf / Kiro — `mcpServers` config block
```jsonc
{
  "mcpServers": {
    "anumana": {
      "command": "uvx",
      "args": ["anumana-mcp"],
      "env": { "ANUMANA_DSN": "postgres://readonly@localhost:5432/mydb" }
    }
  }
}
```
Use a **read-only** Postgres role. Anumana only ever `EXPLAIN`s, but read-only is
defence in depth. Omit `ANUMANA_DSN` to run in schema-only mode (DDL in, no DB).

---

## Try it with no database (30 seconds)
```bash
python3 src/demo.py          # runs the engine on a canned plan, zero deps
```

## Test against a real Postgres
```bash
# a throwaway table, then:
ANUMANA_DSN=postgres://localhost/mydb anumana-mcp
```
See `src/live_test.py` for a `psql`-backed harness that proves the real
cost-delta and the selectivity gate on live data.

---

## What's deliberately NOT here
No `run_query` (we never execute your SQL), no NL→SQL (the agent already does
that), no DB-health reports, no dollar-billing. Staying narrow is the strategy.

## License
MIT — see [LICENSE](LICENSE).

## Community & contact
Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Adding a database engine is the highest-
leverage contribution; the adapter contract is small ([SUPPORTED_ENGINES.md](SUPPORTED_ENGINES.md)).

- **Bugs / ideas:** open a [GitHub issue](../../issues).
- **Security:** see [SECURITY.md](SECURITY.md) — report privately.
- **Maintainer:** nomore.report@gmail.com
