# Contributing to Anumana

Thanks for wanting to help. Anumana has one job — **tell an AI agent what a
query will cost before it runs** — and the fastest way to add value is a new
engine adapter or a sharper cost flag.

## Ground rules (the honesty rails)

These are non-negotiable; a PR that breaks one will be asked to change:

1. **Never execute the agent's query.** Adapters use `EXPLAIN` / dry-run /
   catalog reads only — never `EXPLAIN ANALYZE`, `GRAPH.PROFILE`, or anything
   that runs the user's SQL.
2. **Never fake a cost.** If an engine exposes no cost signal (no planner, no
   deterministic rule), it does not get an adapter. Report the *access pattern*
   and say plainly when there are no live counts — don't invent milliseconds.
3. **Planner cost is unitless, not milliseconds.** Say so.
4. **Read-only by default.** Docs and examples use read-only roles.
5. **Mark new adapters `verified_live = False`** until they've been run against a
   real instance of that engine. See [SUPPORTED_ENGINES.md](SUPPORTED_ENGINES.md).

## Dev setup

```bash
git clone https://github.com/sinhaKAN-ra/anumana.git
cd anumana
uv venv && uv pip install -e ".[dev]"      # or: pip install -e ".[dev]"
uv run pytest                               # run the test suite
```

Run the server from source (no cache) while iterating:

```bash
uv run --project . --with "mcp[cli]<2" python -m anumana.server
```

## Adding a database engine

An engine adapter implements the contract in
[`src/anumana/adapters/base.py`](src/anumana/adapters/base.py):

| Method | Does |
|---|---|
| `get_plan(run_sql, query)` | ask the engine what it WOULD do (no execution), normalise to the shared node shape |
| `detect_flags(query, plan)` | deterministic overhead flags (full scan, missing index, unbounded, …) |
| `node_reason(node)` | one plain-English line per plan node |
| `headline(plan)` | the single sentence a dev needs about the dominant cost |
| `describe_schema(run_sql)` | read the engine's own catalog (read-only), or return `need_from_user` |

Plus `name`, `label`, and `verified_live`. Then:

1. Register it in [`src/anumana/adapters/__init__.py`](src/anumana/adapters/__init__.py).
2. Wire a live runner in [`src/anumana/server.py`](src/anumana/server.py)
   (`_runner_for` + a `_<engine>_runner`).
3. Add a row to [SUPPORTED_ENGINES.md](SUPPORTED_ENGINES.md) (`UNTESTED` until proven).
4. Add a test in `tests/` — the MongoDB and SQLite adapters are good templates
   (feed a sample plan, assert the flags).

The MongoDB (`src/anumana/adapters/mongodb.py`) and SQLite
(`src/anumana/adapters/sqlite.py`) adapters are the cleanest references.

## Pull requests

- Keep PRs focused — one engine or one fix per PR.
- Include a test and a line in the PR description on what you ran.
- Run `uv run pytest` before pushing.
- Describe any honesty-rail implications explicitly.

## Reporting bugs / ideas

Open a [GitHub issue](../../issues). For security-sensitive reports, see
[SECURITY.md](SECURITY.md). For anything else you can reach the maintainer at
**nomore.report@gmail.com**.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
