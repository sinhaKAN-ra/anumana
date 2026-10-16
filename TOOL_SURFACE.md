# Anumana MCP tool contract

The implemented tool definitions in `src/anumana/server.py` are the source of
truth. All tools return JSON text. Client-generated server prefixes may precede
the names below. Tool names are stable; the old `connect_schema` and
`explain_working` design sketches are not published tools.

## Connections and schema

`list_targets()` lists configured target names, engines, diagnosability, and
notes without connection secrets. With one configured target, callers may omit
`target`; with multiple targets they must select its exact name.

`describe_schema_tool(target: str | None = None)` reads the schema before query
work: tables/collections, columns/fields, indexes and cached row estimates where
available. Results include `accuracy` (LIVE, SAMPLED, DECLARED or NONE), `tables`,
`notes`, and `need_from_user` on failure. MongoDB fields are sampled from a
document per collection; this is disclosed and is not metadata-only access.

`list_policies()` returns operator block/warn/allow policies. Policies do not
provide query execution capability. Implicit single-target selection evaluates
against the resolved target name.

Configure connections server-side with ANUMANA_DSN / ANUMANA_ENGINE, or the
ANUMANA_TARGETS JSON array. There is no tool for submitting credentials.

## Planner preflight

`preflight_query(sql: str, target: str | None = None)` returns `engine`,
`risk_tier` (cheap, moderate, expensive, dangerous), `accuracy_tier`, estimated
rows scanned/returned, `scan_strategy`, `planner_total_cost`, `flags`,
`human_summary`, `has_rewrite`, and `policy`.

`row_estimates_available` and `planner_cost_available` identify unavailable
metrics. Legacy numeric fields remain zero when unavailable; that zero does not
mean zero work. SQLite, MongoDB and DynamoDB report HEURISTIC access patterns.
MySQL/MariaDB can supply row estimates without a numeric optimizer cost.
Planner costs are unitless, not milliseconds. Estimates never guarantee runtime.

For SQL engines, `sql` is one statement; stacked statements are rejected before
the driver is called. Unterminated and ambiguous backslash quoting is refused.
The server issues EXPLAIN without ANALYZE. For MongoDB, `sql` is a JSON find
request with supported fields: find, filter, projection, sort, limit, skip,
hint, collation, maxTimeMS. It explicitly requests queryPlanner verbosity.
For DynamoDB, `sql` is a JSON Query/Scan request; preflight judges its shape
without calling Query or Scan. Key-condition presence does not prove it matches
the real key schema or predict capacity charges.

`preflight_vector_search(sql: str, target: str | None = None)` requires a
pgvector target, adds vector-specific flags and applies operator policy. It
cannot estimate ANN recall. A policy block is not bypassed by using this tool.

`preflight_schema_only(ddl: str, sql: str)` analyses supplied CREATE TABLE /
CREATE INDEX DDL without a database connection. It returns HEURISTIC findings,
not live planner costs or verified savings. No target is required.

## Rewrite and candidate grading

`rewrite_query(sql: str, target: str | None = None)` returns a proposed rewrite
when flags exist; otherwise `{"rewrite": null, "reason": "..."}`. The proposal
contains `rewritten_sql`, `changes`, `cost_before`, nullable `cost_after` and
`cost_delta_pct`, `accuracy_tier`, `index_suggestions`, and
`equivalence_caveats`.

The automatic LIMIT proposal is deliberately conservative: plain SELECT only,
without existing LIMIT/FETCH, nested SELECT, set operations or locking clauses.
It changes row count and is advisory, not a semantically equivalent rewrite.
Other SQL requires agent-authored changes and a fresh preflight. JSON requests
are never rewritten by appending SQL. Projection changes remain advice because
the engine cannot know downstream column requirements.

`rewrite_verified` means numeric candidate costs were successfully re-planned;
`verified_cheaper` additionally requires strictly lower cost. Neither proves
semantic equivalence. Failed or unavailable replanning yields null after/delta
values and a `verification_note`; it is never reported as a successful proof.

For PostgreSQL, simple selective sequential-scan predicates can produce quoted
btree DDL proposals using the plan's real relation/column and cached cardinality.
A dedicated runner checks an already installed HypoPG extension. It EXPLAINs
the **same original SQL** with and without a session-local hypothetical index,
then resets and closes the connection. It never installs extensions, creates a
real index, or executes the candidate. Unsupported/complex predicates receive
no automatic btree proposal. HypoPG is optional; missing or failed simulation
leaves the proposal explicitly unverified.

Index proposals report `simulation_status`, and, after successful simulation,
`simulated_with`, `simulated_cost_before`, `simulated_cost_after`,
`simulated_cost_delta_pct`, `hypothetical_index_used`, and `verified_cheaper`.
HypoPG simulation is separate from rewrite savings and does not verify HNSW
indexes. Simple vector ordering on one known relation can produce HNSW DDL
matching its cosine, L2 or inner-product metric; complex expressions receive no
guessed index. Vector type, metric and recall still require review.

`suggest_query(intent: str, candidate_sql: str, target: str | None = None)`
grades an agent-written candidate and returns `accept`, `next_action`
(accept/refine), reasons, risk/accuracy, flags, proposed SQL, costs, and policy.
It also forwards rewrite verification status and equivalence caveats. A policy
block overrides an otherwise acceptable risk tier. The caller should bound
refinement to about three rounds. Accept means acceptable estimated cost, not
permission to execute or proof of intent correctness.

## Explanation

`explain_query_working(sql: str, target: str | None = None)` returns logical SQL
clause order, bottom-up physical steps, a headline, and accuracy tier. The
PostgreSQL headline ranks local operator cost rather than choosing a cumulative
Limit wrapper. LIMIT may stop input early; blocking sorts/aggregates can still
require substantial work.

## Execution and verification boundaries

There is no run_query or arbitrary execution tool. Schema changes are proposals
requiring a separate workflow. Live-runner availability and live-verification
status are separate; see SUPPORTED_ENGINES.md. Unit fixtures do not establish
end-to-end support for an untested engine.
