"""Anumana MCP server — foresight for the queries AI agents write.

Exposes the engine as MCP tools for Claude / Cursor / Windsurf / Codex / Kiro
and any MCP-compatible agent. Scope: the queries AI AGENTS generate — text-to-
SQL and RAG / vector search — across one OR MANY configured databases.

Requires: pip install "mcp[cli]" "psycopg[binary]"   (+ pymongo / boto3 for those engines)
Run:      ANUMANA_DSN=postgres://readonly@host/db python3 -m anumana.server
Multi-DB: ANUMANA_TARGETS='[{"name":"orders","engine":"postgres","dsn":"..."}]'

We only ever run EXPLAIN (never EXPLAIN ANALYZE) / describe catalogs, so nothing
executes the agent's query. Read-only roles are the right ask and defence in depth.

The tool DESCRIPTIONS are the entire discovery mechanism: an MCP agent reads them
at connect time and decides, from the description alone, whether to call a tool.
"""
from __future__ import annotations

import json

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - lets the file import without the dep
    FastMCP = None  # type: ignore

from anumana.engine import (  # noqa: E402
    preflight, rewrite, explain_working, describe_schema,
    suggest_query as _engine_suggest_query,
)
from anumana.schema_only import analyse_static  # noqa: E402
from anumana.registry import registry  # noqa: E402
from anumana.policy import policies  # noqa: E402


def _dumps(obj) -> str:
    return json.dumps(obj, default=lambda o: o.__dict__, indent=2)


# ---- per-engine runner factory ---------------------------------------------
# Resolve a target (by name) to (run_sql_callable, engine_name). The callable is
# what the engine layer calls to EXPLAIN / describe. Each engine builds its own.

def _runner_for(target_name: str | None):
    """Return (run_sql, engine) for a named target, or raise with guidance."""
    reg = registry()
    if reg.is_empty():
        raise RuntimeError(
            "No targets configured. Set ANUMANA_DSN (single DB) or ANUMANA_TARGETS "
            "(JSON array of named DBs), or use preflight_schema_only with DDL."
        )
    t = reg.get(target_name)          # fails loudly on unknown / non-diagnosable
    engine = t.engine
    conn = t.connection

    if engine in ("postgres", "postgresql", "pg", "pgvector", "vector"):
        return _pg_runner(conn["dsn"]), engine
    if engine in ("redshift",):
        # Redshift speaks the Postgres wire protocol — same psycopg runner.
        return _pg_runner(conn["dsn"]), engine
    if engine in ("mongodb", "mongo"):
        return _mongo_runner(conn.get("uri")), engine
    if engine in ("dynamodb", "dynamo"):
        return _dynamo_runner(conn.get("region"), conn.get("profile")), engine
    if engine in ("sqlite", "sqlite3"):
        return _sqlite_runner(conn.get("path") or conn.get("dsn")), engine
    if engine in ("mysql", "mariadb"):
        return _mysql_runner(conn.get("dsn")), engine
    # Adapters exist and are offline-verified for these, but a live runner is not
    # wired yet — they come online one engine at a time as each is connected and
    # tested. Fail with a clear, honest message (not a crash).
    if engine in ("bigquery", "bq", "clickhouse", "snowflake",
                  "falkordb", "falkor", "cassandra", "scylla", "scylladb"):
        raise RuntimeError(
            f"The {engine!r} adapter is implemented and offline-verified, but its "
            f"live runner is not wired into the server yet (it's being brought "
            f"online one engine at a time). Use preflight_schema_only for offline "
            f"analysis, or track progress in SUPPORTED_ENGINES.md."
        )
    raise RuntimeError(f"No runner for engine {engine!r}")


def _pg_runner(dsn: str):
    import psycopg  # lazy — only when a PG target is actually used

    def run_sql(sql: str):
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)  # EXPLAIN / catalog read only — never agent DML
                return [row[0] if len(row) == 1 else row for row in cur.fetchall()]

    return run_sql


def _mongo_runner(uri: str | None):
    """Live MongoDB runner (lazy pymongo). Handles two request kinds:
    - the describe sentinel  -> sample fields + getIndexes per collection
    - a query command (JSON)  -> explain('queryPlanner') on that find, NO execution
    """
    if not uri:
        raise RuntimeError("MongoDB target has no 'uri' in its config.")

    def run_sql(cmd: str):
        import pymongo  # lazy — only when a Mongo target is actually used
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        try:
            db = client.get_default_database()
            if cmd == "__anumana_describe__":
                collections = []
                for name in db.list_collection_names():
                    coll = db[name]
                    sample = coll.find_one() or {}
                    collections.append({
                        "name": name,
                        "sample_fields": list(sample.keys()),
                        "indexes": [{"name": i.get("name"), "key": dict(i.get("key", {}))}
                                    for i in coll.list_indexes()],
                        "est_count": coll.estimated_document_count(),
                    })
                return [{"collections": collections}]
            # a query: {"find":"coll","filter":{...}} -> explain the find plan only
            spec = json.loads(cmd)
            coll = db[spec["find"]]
            cur = coll.find(spec.get("filter", {}), spec.get("projection"))
            if spec.get("limit"):
                cur = cur.limit(int(spec["limit"]))
            return [cur.explain()]  # queryPlanner — does NOT run the query
        finally:
            client.close()  # don't leak a connection pool per call

    return run_sql


def _dynamo_runner(region: str | None, profile: str | None):
    """Live DynamoDB runner (lazy boto3). DynamoDB has no planner, so a QUERY
    needs no live call — the Dynamo adapter judges the request shape itself. Only
    the describe sentinel hits AWS, via DescribeTable (read-only metadata)."""
    def run_sql(cmd: str):
        if cmd != "__anumana_describe__":
            # rule-based engine: the adapter parses the request; no AWS call needed.
            return [None]
        import boto3  # lazy — only when a Dynamo target is actually used
        session = boto3.Session(profile_name=profile, region_name=region)
        ddb = session.client("dynamodb")
        tables = []
        for name in ddb.list_tables().get("TableNames", []):
            d = ddb.describe_table(TableName=name)["Table"]
            ks = {}
            for k in d.get("KeySchema", []):
                ks["partition_key" if k["KeyType"] == "HASH" else "sort_key"] = k["AttributeName"]
            gsis = [{"name": g["IndexName"],
                     "keys": [k["AttributeName"] for k in g.get("KeySchema", [])]}
                    for g in d.get("GlobalSecondaryIndexes", [])]
            tables.append({"name": name, "key_schema": ks, "gsis": gsis,
                           "item_count": d.get("ItemCount")})
        return [{"tables": tables}]

    return run_sql


def _sqlite_runner(path: str | None):
    """Live SQLite runner — opens the .db file READ-ONLY (immutable URI) so the
    agent's query can never write. EXPLAIN QUERY PLAN + PRAGMA catalog reads only."""
    if not path:
        raise RuntimeError("SQLite target has no 'path' (or 'dsn') in its config.")

    def run_sql(sql: str):
        import sqlite3  # stdlib — always available
        # read-only open: file: URI with mode=ro, so no write can occur.
        uri = f"file:{path}?mode=ro" if not str(path).startswith("file:") else path
        conn = sqlite3.connect(uri, uri=True)
        try:
            return conn.execute(sql).fetchall()  # EXPLAIN QUERY PLAN / PRAGMA only
        finally:
            conn.close()

    return run_sql


def _mysql_runner(dsn: str | None):
    """Live MySQL/MariaDB runner (lazy PyMySQL). EXPLAIN FORMAT=JSON +
    information_schema reads only — never executes the agent's query."""
    if not dsn:
        raise RuntimeError("MySQL target has no 'dsn' in its config.")

    def run_sql(sql: str):
        import pymysql  # lazy — only when a MySQL target is actually used
        from urllib.parse import urlparse
        u = urlparse(dsn)
        conn = pymysql.connect(
            host=u.hostname or "127.0.0.1", port=u.port or 3306,
            user=u.username, password=u.password or "",
            database=(u.path or "/").lstrip("/") or None,
            connect_timeout=3, read_default_group=None,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql)  # EXPLAIN / catalog read only
                rows = cur.fetchall()
                return [r[0] if isinstance(r, (list, tuple)) and len(r) == 1 else r
                        for r in rows]
        finally:
            conn.close()

    return run_sql


def _err(e: Exception) -> str:
    return _dumps({"error": str(e)})


if FastMCP is not None:
    mcp = FastMCP("anumana")

    @mcp.tool()
    def list_targets() -> str:
        """List the databases Anumana is configured to analyse — each with its
        name, engine, and whether it's diagnosable. Call this FIRST in a multi-DB
        setup to see which target holds the data the user asked for, then pass
        target=<name> to the other tools. In a single-DB setup you can omit target
        and the one database is used. Never returns connection strings or secrets."""
        try:
            return _dumps({"targets": registry().list()})
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def list_policies() -> str:
        """List the operator's standing enforcement policies — the rules that can
        BLOCK or WARN on a query regardless of what you intend. Each has a name,
        scope (which target/engine), condition (risk tier and/or flag), and action
        (block/warn/allow). preflight_query and suggest_query already apply these
        and attach the verdict; call this to explain to a user WHY a query was
        blocked. No policies configured means open by default (nothing blocked)."""
        try:
            ps = policies().policies
            return _dumps({"policies": [
                {"name": p.name, "scope": p.scope, "when": p.when, "action": p.action}
                for p in ps
            ] or "none configured (open by default)"})
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def preflight_query(sql: str, target: str = None) -> str:  # type: ignore[assignment]
        """Before running ANY SQL query you (the agent) just wrote, check how
        costly it will be on the real schema — WITHOUT executing it. Returns a
        risk tier (cheap/moderate/expensive/dangerous), rows scanned vs returned,
        scan strategy, and overhead flags (missing index, SELECT *, no LIMIT, N+1
        / nested-loop blowup). EXPLAIN only — never runs the query. In a multi-DB
        setup pass target=<name> (see list_targets). For similarity search use
        preflight_vector_search; with no DB use preflight_schema_only."""
        try:
            run_sql, engine = _runner_for(target)
            pf = preflight(run_sql, sql, engine=engine).to_dict()
            verdict = policies().evaluate(
                target=target, engine=engine, risk=pf["risk_tier"],
                flag_codes={f["code"] for f in pf["flags"]},
            )
            pf["policy"] = verdict.to_dict()
            return _dumps(pf)
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def preflight_vector_search(sql: str, target: str = None) -> str:  # type: ignore[assignment]
        """Before running a VECTOR SIMILARITY SEARCH (pgvector: `ORDER BY embedding
        <-> $1 LIMIT k`, cosine `<=>`, inner-product `<#>`), check its cost WITHOUT
        running it — for any RAG / semantic-search / nearest-neighbour query you
        generate. Catches the vector traps a plain SQL check misses: brute-force
        scan with no HNSW/IVFFlat index (FULL_VECTOR_SCAN), top_k too large
        (TOP_K_TOO_LARGE), unbounded search (UNBOUNDED_VECTOR_SEARCH), and metadata-
        filter/ANN recall loss (VECTOR_FILTER_INTERACTION). EXPLAIN only. Pass
        target=<name> in a multi-DB setup; the target should be a pgvector engine."""
        try:
            run_sql, _ = _runner_for(target)
            return _dumps(preflight(run_sql, sql, engine="pgvector").to_dict())
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def rewrite_query(sql: str, target: str = None) -> str:  # type: ignore[assignment]
        """Rewrite a slow query into a cheaper, equivalent one and PROVE the
        improvement by EXPLAIN-ing both and comparing planner cost. Call after a
        preflight flags a query expensive/dangerous. Returns the rewritten query,
        what changed, before/after cost, and index suggestions — ONLY suggesting a
        btree index when the filter is selective enough to help (an HNSW index for
        a vector target). Includes equivalence caveats. Pass target=<name> in a
        multi-DB setup."""
        try:
            run_sql, engine = _runner_for(target)
            rw = rewrite(run_sql, sql, engine=engine)
            return _dumps(rw if rw else {"rewrite": None, "reason": "no overhead flags; query looks fine"})
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def explain_query_working(sql: str, target: str = None) -> str:  # type: ignore[assignment]
        """Explain in plain English HOW a query behaves — two layers: (1) the
        logical gather order (FROM -> WHERE -> GROUP BY -> HAVING -> SELECT ->
        ORDER BY -> LIMIT), why 'LIMIT 10' can still be slow; and (2) the actual
        physical plan the engine chose for THIS query, bottom-up. Call when a user
        asks why a query is slow or how it runs. Teaching tool. Pass target=<name>
        in a multi-DB setup."""
        try:
            run_sql, engine = _runner_for(target)
            return _dumps(explain_working(run_sql, sql, engine=engine))
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def describe_schema_tool(target: str = None) -> str:  # type: ignore[assignment]
        """Read a database's REAL schema — tables/collections, columns/fields,
        INDEXES, and row counts — so you can write a grounded, cost-aware query
        BEFORE guessing. Call this FIRST when a user asks for data and you don't
        already know the schema; it tells you which columns are indexed so your
        query hits an index, not a full scan. READ-ONLY catalog access — never
        reads data rows. If the schema can't be read it returns `need_from_user`
        naming what to ask the user for. Pass target=<name> in a multi-DB setup;
        combine with list_targets to find which DB has the data."""
        try:
            run_sql, engine = _runner_for(target)
            return _dumps(describe_schema(run_sql, engine=engine))
        except Exception as e:
            # a connection/credential failure still yields the ask-the-user payload
            return _dumps(describe_schema(lambda _s: (_ for _ in ()).throw(e),
                                          engine=(target or "postgres")))

    @mcp.tool()
    def suggest_query(intent: str, candidate_sql: str, target: str = None) -> str:  # type: ignore[assignment]
        """Grade a query you (the agent) wrote for a user's data request and get
        told whether to RUN it or REFINE it — the check step of generate->check->
        refine. Workflow: (1) describe_schema_tool to learn columns + indexes,
        (2) write a candidate for the user's intent, (3) call this. Returns
        `next_action`: 'accept' (cheap/moderate — run it) or 'refine' (expensive/
        dangerous — here are the high-severity flags + a VERIFIED cheaper rewrite;
        fix and call again). You write the SQL; Anumana owns cost truth. Bound your
        loop to ~3 rounds. Pass target=<name> in a multi-DB setup."""
        try:
            run_sql, engine = _runner_for(target)
            v = _engine_suggest_query(run_sql, intent, candidate_sql, engine=engine)
            verdict = policies().evaluate(
                target=target, engine=engine, risk=v["risk_tier"],
                flag_codes={f["code"] for f in v["flags"]},
            )
            v["policy"] = verdict.to_dict()
            # an operator BLOCK overrides an otherwise-acceptable verdict.
            if verdict.decision == "block":
                v["accept"] = False
                v["next_action"] = "refine"
                v["reasons"] = [verdict.message] + v["reasons"]
            return _dumps(v)
        except Exception as e:
            return _err(e)

    @mcp.tool()
    def preflight_schema_only(ddl: str, sql: str) -> str:
        """Analyse a query against pasted CREATE TABLE DDL with NO database
        connection — the zero-trust, offline front door. Call when the user gave
        you their schema (DDL) but not DB credentials. Catches SELECT *, missing
        LIMIT, un-indexed filter columns, LIKE '%...', functions on filtered
        columns. HEURISTIC only (no live counts) and says so. No target needed."""
        return _dumps(analyse_static(ddl, sql))

    def main() -> None:
        """Console entry point (pyproject [project.scripts] anumana-mcp)."""
        mcp.run()

    if __name__ == "__main__":
        main()
else:  # pragma: no cover
    def main() -> None:
        raise SystemExit("Install the MCP SDK:  pip install 'mcp[cli]' 'psycopg[binary]'")

    if __name__ == "__main__":
        main()
