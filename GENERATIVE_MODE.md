# Anumana — Generative & Multi-DB Mode (design note, NOT yet built)

This note captures a feature set the user asked for that is **bigger than an
adapter** and deliberately NOT built yet. It is written down so it is built
properly, step by step, instead of rushed. Read this with `DESIGN.md`.

---

## The shift this feature represents

Everything built so far (v0.2) is **reactive**: the agent writes a query, and
Anumana *grades* it (preflight / rewrite / explain). The query already exists.

What the user described is **generative**:

> "The user doesn't write a query. They say *'find me this kind of data.'* Can
> the agent generate an OPTIMISED query from understanding the schema — gathering
> the schema itself, and asking the user only if it can't — and handle large or
> multiple databases configured for the platform?"

That is: **help the agent write the query RIGHT the first time**, schema-aware
and cost-aware, before any query text exists. It is a new mode, not a new engine.

**Key design stance:** Anumana does NOT become an NL→SQL generator (the agent
already does that, and we said we won't compete there). Anumana's job stays
"grounding + cost truth." So the division of labour is:

- the **agent** turns intent → candidate query (it's good at language),
- **Anumana** supplies the **schema the agent needs** and **grades every
  candidate** so the agent iterates to an optimised one before running anything.

Anumana is the schema oracle + cost referee in a generate→check→refine loop.

---

## Phase 1 — Schema introspection (`describe_schema`)  ✅ BUILT (v0.2)

The foundation. The agent can't write a good query without knowing the schema;
today it guesses. Give it a tool that returns the real schema from the configured
DB, per engine:

| Engine | Source of truth |
|---|---|
| Postgres | `information_schema.columns`, `pg_indexes`, `pg_stats` (incl. row counts / selectivity) |
| pgvector | the above + which columns are `vector` + which have HNSW/IVFFlat |
| MongoDB | `db.coll.find().limit(N)` sampled key inference + `getIndexes()` |
| DynamoDB | `DescribeTable` → key schema + GSIs/LSIs (THE thing that defines valid access patterns) |

Returns: tables/collections, columns/fields + types, **indexes**, and (where
available) **row counts** so the agent knows what's selective. This is a READ-ONLY
catalog read — never touches data rows (Mongo samples; it's the one exception,
disclosed).

Honesty rail: if the engine can't give a field (Mongo is schemaless; Dynamo
items vary), say so — "sampled from N docs, not authoritative."

**Fallback-to-ask:** if there's no DSN, or the catalog read is denied, the tool
returns a structured `need_from_user` payload naming exactly what to ask for
(DSN, or paste DDL). This is the "ask the user if it can't gather" the user
wanted — and it's a tool RESULT, so the agent relays it naturally.

**Build status (v0.2):** `describe_schema(engine=...)` is implemented for all
four adapters, with the fallback-to-ask path, and verified on canned catalog
docs (zero DB). The MCP tool is wired in `server.py`.
*Live-wiring gap, disclosed:* the server's `run_sql` runner is the Postgres
EXPLAIN runner, so the **Postgres / pgvector** catalog read works end-to-end
over a live DSN today. **Mongo / Dynamo** describe_schema is tested against the
documents their drivers return, but the live runner that calls `getIndexes()` /
`DescribeTable` needs `pymongo` / `boto3` wired in `server.py` — a small follow-up
once those drivers are a dependency. The adapter logic itself is done.

## Phase 2 — The generate→check→refine loop (`suggest_query`)  ✅ BUILT (v0.2)

With schema in hand, close the loop:

1. agent proposes a candidate query for the user's intent,
2. `suggest_query(intent, candidate)` runs `preflight` on it,
3. if it's `expensive`/`dangerous`, Anumana returns the flags + a `rewrite`,
4. the agent refines and re-checks — bounded to ~3 iterations,
5. returns the cheapest candidate that satisfies the intent + its risk tier.

Anumana still never invents the SQL — it grades and the agent writes. The output
is "here is a query that is BOTH correct for the intent AND cheap," with the cost
proof attached. This is the "optimised query from schema understanding" ask.

## Phase 3 — Multi-DB registry (the "platform configured for many DBs" ask)  ✅ BUILT (v0.2)

Today one process = one `ANUMANA_DSN` = one DB. The user wants a platform that
holds several. Design:

- a **connection registry** (`ANUMANA_TARGETS` = named list of {name, engine,
  dsn/config, read-only role}), configured once by the operator,
- every tool gains an optional `target` arg (`preflight_query(sql, target="orders_pg")`),
- a `list_targets` tool so the agent sees what's available and picks by name,
- `describe_schema(target=...)` lets the agent discover which DB even HAS the data
  the user asked for (route the intent to the right store).

Guardrails: each target carries its own read-only credential; a target with no
cost signal (Redis) is registered as "diagnosable: false" and refused loudly, not
faked. Secrets live in the operator's config / a vault, never in tool args.

**Build status (v0.2):** `registry.py` loads `ANUMANA_TARGETS` (JSON array) plus
the legacy single `ANUMANA_DSN` (registered as target "default", so nothing
breaks). Every MCP tool gained an optional `target=<name>` arg, and `list_targets`
returns a SECRET-FREE view (name/engine/flags only — DSNs stay server-side).
Non-diagnosable engines (Redis) are refused loudly. Verified on canned config.
All four engines now have LIVE runners: Postgres/pgvector via `psycopg`, MongoDB
via `pymongo` (`explain('queryPlanner')` + sampled describe), DynamoDB via `boto3`
(`DescribeTable`; queries need no call — rule-based). Drivers are lazy-imported
and optional extras (`pip install anumana-mcp[mongodb]` / `[dynamodb]`), so a
Postgres user never loads them.

## Phase 4 — Platform tasks / policies (the "configured to do some task" ask)  ✅ BUILT (v0.2)

The heaviest piece, last. A thin policy layer so an operator can configure
standing rules across targets, e.g.:

- "block any `dangerous` query on `prod_pg`" (a gate, like the CI story),
- "every agent query on any target must pass preflight first,"
- "warn on any Dynamo full-scan on tables over X items."

This is where the paid/enterprise angle lives (the CI-gate story). Build it ONLY
after 1–3 prove out — it depends on all of them.

**Build status (v0.2):** `policy.py` loads `ANUMANA_POLICIES` (JSON array). Each
policy has a scope (target/engine/all), a condition (`risk_at_least` and/or a
`flag` code), and an action (block/warn/allow). `preflight_query` and
`suggest_query` evaluate every policy and attach a `policy` verdict; a `block`
overrides `suggest_query`'s accept. `list_policies` explains the rules. Strictest
matching action wins; **open by default** — the operator opts INTO enforcement.
Verified on canned policy sets (zero DB).
*Honesty note (gate-by-advising):* Anumana is NOT in the data path, so a 'block'
is an INSTRUCTION to the agent ("do not run this"), enforced by the agent
honouring it — not an interception. True hard enforcement would need Anumana to
sit between the agent and the DB (a proxy), which is a separate, bigger product
decision. The policy layer as built is the advisory CI-gate; the audit trail
records what was advised.

---

## Build order & why

1. **`describe_schema`** — nothing generative works without it; also independently
   useful (the agent stops guessing the schema). Smallest, highest leverage.
2. **`suggest_query`** loop — needs Phase 1.
3. **Multi-DB registry** — orthogonal; can start after Phase 1 in parallel.
4. **Policy layer** — needs 1–3.

Each phase is a separate, verifiable build (zero-DB tests with canned catalog
docs, like the adapters). We do them one at a time.

## What stays TRUE across all of it (non-negotiables)
- Never run the user's query (EXPLAIN / describe / sample-read only).
- No fake milliseconds; every output carries an accuracy tier.
- Anumana grounds + grades; the AGENT writes the query. We are not an NL→SQL tool.
- An engine with no cost signal is refused, never faked.
