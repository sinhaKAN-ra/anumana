# Anumana Query Preflight — prepared listing draft

## Short description

A database-aware agent skill with workflows for all 12 Anumana adapter families,
engine readiness states, MCP setup templates and an engine-by-engine test plan.

## Description

Help your coding agent review the queries it writes before execution. Anumana
Query Preflight pairs a reusable workflow skill with the separately installed,
free Anumana MCP server.

The package covers PostgreSQL, pgvector, SQLite, MySQL/MariaDB, MongoDB,
DynamoDB, Amazon Redshift, Google BigQuery, Snowflake, ClickHouse, FalkorDB and
Cassandra/ScyllaDB. It teaches the agent to select the right native query format,
inspect schema and access patterns, preserve results when proposing changes,
respect policy decisions and report what is actually verified.

Coverage means engine-specific guidance and readiness tracking, not a claim
that every database has a live integration. In the current development checkout:

- PostgreSQL and SQLite have live test evidence for tested paths.
- pgvector, MySQL/MariaDB, MongoDB, DynamoDB and Redshift have connected runners
  awaiting live verification.
- BigQuery, Snowflake, ClickHouse, FalkorDB and Cassandra/ScyllaDB have adapters
  and prepared review workflows, but no live MCP runner yet.

Included: SKILL.md; 12 engine profiles; a machine-readable status catalog; local
setup instructions; published-baseline and development-checkout MCP templates;
examples; and an incremental verification checklist. Offline DDL checking is a
limited generic SQL heuristic. JSON, Cypher and CQL have separate native-format
review guidance rather than pretending the SQL checker can plan them.

The complete catalog describes development preparation. Published server 0.2.1
may not include the same code. Baseline templates pin that release; development
templates require a local checkout containing the intended changes. A fresh
public clone cannot obtain uncommitted maintainer changes. This draft should be
reviewed against the server release/source actually distributed at launch.

Requires Python 3.10+, a compatible agent with MCP access, local server setup,
and your own service/read-only credentials for connected-engine checks. No
hosted database, query execution, guaranteed savings, measured runtime/recall or
validated cloud billing is included. Missing runners are not activated by the
skill; untested engines remain explicitly provisional.

Anumana MCP is free and open source. A purchase pays for the packaged workflow,
setup resources and engine-specific preparation. It does not unlock exclusive
server features. This package is MIT licensed, including redistribution rights.
No paid support or future-update subscription is promised.

Project: https://github.com/sinhaKAN-ra/anumana
Website: https://anumana.vercel.app

## Submission fields

- Title: Anumana Query Preflight
- Category: Data & Databases
- Suggested tags: SQL, databases, MCP, PostgreSQL, pgvector, MongoDB, DynamoDB,
  query review, agent skills
- Price: choose in Creator Studio; no price has been committed.
- Upload: dist/anumana-query-preflight.zip
- State: prepared package; engine tests and listing publication happen separately.

## Rebuild and upload

From the repo root:

```sh
python3 packaging/sync_engine_coverage.py
python3 packaging/build_agensi.py
```

The website list is generated from the same status catalog as the skill. The
ZIP has SKILL.md at its root, valid name/description frontmatter, and only the
approved skill resources. Filled credentials and arbitrary local files are
excluded. Local validation does not guarantee marketplace approval.

Sign in to Agensi, enable creator mode as Joeri described, upload the ZIP, paste
this accurate description, choose a price and follow the dashboard's review and
payout flow. The website links to the marketplace homepage until a reviewed
Anumana listing URL exists. Set AGENSI_LISTING_URL in site/app.js once available.

Requirements source: Joeri's supplied email and
https://www.agensi.io/learn/how-to-sell-skills-on-agensi

Keep the readiness disclosure in the public description while tests are pending.
After validating one engine, update its profile/status catalog and the repo's
verified_live/SUPPORTED_ENGINES.md evidence, then regenerate the website and ZIP.
Do not bump the MCP package version or publish merely to package the skill.
