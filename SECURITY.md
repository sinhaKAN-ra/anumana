# Security Policy

## Reporting a vulnerability

If you find a security issue in Anumana, please **do not open a public issue**.
Email the maintainer directly at **nomore.report@gmail.com** with:

- a description of the issue,
- steps to reproduce,
- the version / commit affected.

You'll get an acknowledgement as soon as possible, and we'll work with you on a
fix and coordinated disclosure.

## Security model — what Anumana does and doesn't touch

Anumana is designed to be safe to point at a production database:

- **It never executes your query.** Every adapter uses `EXPLAIN` (never
  `EXPLAIN ANALYZE`), a dry run (BigQuery), `GRAPH.EXPLAIN` (FalkorDB, never
  `PROFILE`), or read-only catalog reads. The agent's SQL is analysed, not run.
- **Read-only credentials are the documented default.** Anumana only needs
  `EXPLAIN` / catalog privileges. Use a read-only role as defence in depth.
- **Connection secrets stay server-side.** The agent references a target *by
  name*; the DSN/URI lives in the server's env (`ANUMANA_DSN` /
  `ANUMANA_TARGETS`) and is never serialised into tool output.
- **No telemetry.** Anumana makes no outbound network calls other than to the
  database target(s) you configure.

## Hardening recommendations

- Always use a **read-only** database role for `ANUMANA_DSN`.
- Keep `ANUMANA_DSN` / `ANUMANA_TARGETS` in your agent host's secret store, not
  in a committed file.
- Scope the read-only role to only the schema(s) you want analysed.
