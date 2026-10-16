"""Core roadmap regression coverage, including a real temporary SQLite DB."""
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from anumana.adapters import get_adapter
from anumana.engine import describe_schema, explain_working, preflight, rewrite, suggest_query
from anumana.server import _mongo_runner, _sqlite_runner
from anumana.sql_text import bounded_candidate, single_statement


@pytest.mark.parametrize("sql", [
    "SELECT 1; DELETE FROM orders", "SELECT 1; /* note */ SELECT 2",
    "SELECT 1;;", "SELECT 'unfinished", "SELECT 1 /* unfinished",
])
@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_stacked_or_malformed_sql_never_reaches_driver(sql, engine):
    def forbidden(_sql):
        pytest.fail("Invalid SQL reached driver")
    with pytest.raises(ValueError):
        get_adapter(engine).get_plan(forbidden, sql)


@pytest.mark.parametrize("sql", [
    "SELECT ';' AS marker; -- note", "SELECT $$a;b$$;",
    'SELECT "semi;colon" FROM "table";', "SELECT 1 /* outer /* nested */ comment */;",
])
def test_statement_guard_allows_quoted_delimiters(sql):
    assert single_statement(sql)


def test_bounding_respects_literals_and_trailing_comments():
    assert bounded_candidate("SELECT 'LIMIT' AS label; -- note").endswith("\nLIMIT 100")
    assert bounded_candidate("SELECT id FROM orders LIMIT 2") is None
    assert bounded_candidate("WITH x AS (SELECT 1) SELECT * FROM x") is None
    assert bounded_candidate("SELECT * FROM (SELECT 1) x") is None


def test_sqlite_end_to_end_readonly(tmp_path):
    path = tmp_path / "catalog.db"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "order details" (id INTEGER PRIMARY KEY, status TEXT)')
        db.execute('CREATE INDEX "status index" ON "order details" (status)')
    run = _sqlite_runner(str(path))
    schema = describe_schema(run, "sqlite")
    table = schema["tables"][0]
    assert table["name"] == "order details"
    assert [c["name"] for c in table["columns"]] == ["id", "status"]
    assert table["indexes"][0]["columns"] == ["status"]
    pf = preflight(run, 'SELECT id FROM "order details" WHERE status = \'paid\' LIMIT 10', engine="sqlite")
    assert pf.accuracy_tier == "HEURISTIC"
    assert not pf.planner_cost_available
    assert any("Search" in step for step in pf.scan_strategy)
    rw = rewrite(run, 'SELECT * FROM "order details"', engine="sqlite")
    assert rw.accuracy_tier == "HEURISTIC"
    assert rw.cost_after is None and not rw.rewrite_verified
    with pytest.raises(sqlite3.OperationalError):
        run('DELETE FROM "order details"')


def test_mongo_runner_uses_explicit_queryplanner(monkeypatch):
    calls = []
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def get_default_database(self):
            return self
        def command(self, command):
            calls.append(command)
            return {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}
        def close(self):
            calls.append("closed")
    monkeypatch.setitem(sys.modules, "pymongo", SimpleNamespace(MongoClient=Client))
    request = {"find": "orders", "filter": {"status": "paid"},
               "sort": {"id": -1}, "projection": {"id": 1}, "limit": 10}
    _mongo_runner("mongodb://localhost/app")(json.dumps(request))
    assert calls == [{"explain": request, "verbosity": "queryPlanner"}, "closed"]


@pytest.mark.parametrize("winning", [
    {"queryPlan": {"stage": "FETCH", "inputStage": {"stage": "IXSCAN", "indexName": "status_1"}}},
    {"stage": "OR", "inputStages": [{"stage": "IXSCAN"}, {"stage": "COLLSCAN"}]},
    {"stage": "SHARD_MERGE", "shards": [{"winningPlan": {"stage": "COLLSCAN"}}]},
])
def test_mongo_walks_sbe_branches_and_shards(winning):
    run = lambda _: [{"queryPlanner": {"winningPlan": winning}}]
    pf = preflight(run, '{"find":"orders","projection":{"id":1},"limit":10}', engine="mongodb")
    assert pf.accuracy_tier == "HEURISTIC"
    assert "0 rows" not in pf.human_summary
    has_scan = "COLLSCAN" in json.dumps(winning)
    assert ("MONGO_COLLSCAN" in {f.code for f in pf.flags}) == has_scan


def test_mongo_zero_limit_is_unbounded(mongo_ixscan):
    pf = preflight(mongo_ixscan, '{"find":"orders","projection":{},"limit":0}', engine="mongo")
    assert {"MONGO_UNBOUNDED", "MONGO_NO_PROJECTION"} <= {f.code for f in pf.flags}


@pytest.mark.parametrize("engine, query", [
    ("mongodb", '{"find":"orders"}'),
    ("dynamodb", '{"op":"Scan","TableName":"orders"}'),
])
def test_no_sql_limit_appended_to_nosql(engine, query):
    run = lambda _: [{"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}]
    rw = rewrite(run, query, engine=engine)
    assert rw.rewritten_sql == query
    assert rw.cost_after is None
    assert not rw.verified_cheaper


@pytest.mark.parametrize("query", [
    '{"op":"DeleteItem","TableName":"orders"}',
    '{"op":"Query","TableName":"orders","KeyConditionExpression":""}',
    '{"op":"Scan","TableName":"orders","Limit":0}',
    '{"op":"Scan","TableName":"orders","Limit":true}',
    'not json', '[]',
])
def test_dynamo_invalid_requests_rejected(query):
    with pytest.raises(ValueError):
        preflight(lambda _: pytest.fail("Dynamo must not execute data calls"), query, engine="dynamo")


def test_dynamo_field_value_cannot_spoof_key_condition():
    pf = preflight(lambda _: None, json.dumps({"op": "Query", "TableName": "orders",
        "FilterExpression": "KeyConditionExpression = :value"}), engine="dynamo")
    assert "DYNAMO_FULL_SCAN" in {f.code for f in pf.flags}
    assert pf.accuracy_tier == "HEURISTIC"


def test_headline_looks_through_cumulative_limit_costs():
    plan = {"Node Type": "Limit", "Total Cost": 10, "Plan Rows": 5,
            "Plans": [{"Node Type": "Seq Scan", "Relation Name": "orders", "Total Cost": 10, "Plan Rows": 100}]}
    result = explain_working(lambda _: [[{"Plan": plan}]], "SELECT id FROM orders LIMIT 5")
    assert "Seq Scan" in result.headline


def test_failed_rewrite_is_not_presented_as_verified():
    def run(sql):
        if "LIMIT 100" in sql:
            raise RuntimeError("planner unavailable")
        return [[{"Plan": {"Node Type": "Seq Scan", "Total Cost": 12000, "Plan Rows": 1000}}]]
    result = rewrite(run, "SELECT * FROM orders")
    assert result.cost_after is None and result.cost_delta_pct is None
    assert not result.rewrite_verified and not result.verified_cheaper
    assert "failed" in result.verification_note
    verdict = suggest_query(run, "all orders", "SELECT * FROM orders")
    assert verdict["equivalence_caveats"]
    assert not verdict["rewrite_verified"]


class SelectiveRunner:
    def __init__(self, unavailable=False):
        self.simulations = []
        self.unavailable = unavailable
    def __call__(self, sql):
        return [[{"Plan": {"Node Type": "Seq Scan", "Schema": "public", "Relation Name": "orders",
                           "Filter": "(customer_id = 42)", "Total Cost": 12000, "Plan Rows": 10}}]]
    def relation_rows(self, schema, relation):
        return 1_000_000
    def simulate_index(self, sql, ddl):
        self.simulations.append((sql, ddl))
        if self.unavailable:
            return {"simulation_status": "unavailable"}
        return {"simulation_status": "verified", "simulated_cost_before": 12000,
                "simulated_cost_after": 8, "verified_cheaper": True}


def test_index_simulation_uses_original_sql_and_real_selectivity():
    run = SelectiveRunner()
    query = "SELECT id FROM orders WHERE customer_id = 42"
    pf = preflight(run, query)
    assert pf.rows_scanned_est == 1_000_000 and pf.rows_returned_est == 10
    result = rewrite(run, query)
    assert run.simulations == [(query, 'CREATE INDEX ON "public"."orders" ("customer_id")')]
    assert result.index_suggestions[0]["verified_cheaper"]
    # The synthetic candidate cost is unchanged: don't attribute index savings to LIMIT.
    assert not result.verified_cheaper


def test_missing_hypopg_keeps_index_unverified():
    result = rewrite(SelectiveRunner(unavailable=True), "SELECT id FROM orders WHERE customer_id = 42")
    assert not result.index_suggestions[0]["verified_cheaper"]


@pytest.mark.parametrize("cost_info", [{}, {"query_cost": "12.5"}])
def test_mysql_and_mariadb_cost_availability(cost_info):
    doc = {"query_block": {"cost_info": cost_info, "nested_loop": [
        {"table": {"table_name": "orders", "access_type": "ALL", "rows": 500000}}]}}
    run = lambda _: [json.dumps(doc)]
    pf = preflight(run, "SELECT * FROM orders", engine="mysql")
    assert pf.rows_scanned_est == 500000
    assert pf.planner_cost_available == bool(cost_info)
    rw = rewrite(run, "SELECT * FROM orders", engine="mysql")
    assert rw.rewrite_verified == bool(cost_info)


def test_sqlite_uri_cannot_override_readonly(tmp_path):
    path = tmp_path / "data #1.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (id INTEGER)")
    run = _sqlite_runner(path.as_uri() + "?mode=rw")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        run("INSERT INTO items VALUES (1)")


@pytest.mark.parametrize("failure", [False, True])
def test_hypopg_same_session_and_cleanup(monkeypatch, failure):
    from anumana.postgres_runner import PostgresRunner
    commands = []
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params=None):
            commands.append((sql, params))
            self.sql = sql
            if failure and sql.startswith("EXPLAIN") and any("hypopg_create_index" in c[0] for c in commands):
                raise RuntimeError("failed hypothetical plan")
        def fetchone(self):
            return (123, "hypothetical_index") if "hypopg_create_index" in self.sql else ("public",)
        def fetchall(self):
            created = any("hypopg_create_index" in c[0] for c in commands)
            node = {"Node Type": "Index Scan" if created else "Seq Scan", "Total Cost": 8 if created else 12000}
            if created:
                node["Index Name"] = "hypothetical_index"
            return [([{"Plan": node}],)]
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            commands.append(("closed", None))
        def cursor(self):
            return Cursor()
    connections = []
    def connect(self):
        connections.append(Connection())
        return connections[-1]
    monkeypatch.setattr(PostgresRunner, "_connect", connect)
    runner = PostgresRunner("unused")
    query = "SELECT id FROM orders WHERE customer_id = 42"
    ddl = 'CREATE INDEX ON "public"."orders" ("customer_id")'
    if failure:
        with pytest.raises(RuntimeError):
            runner.simulate_index(query, ddl)
    else:
        result = runner.simulate_index(query, ddl)
        assert result["verified_cheaper"] and result["hypothetical_index_used"]
        assert result["simulated_cost_after"] == 8
    assert len(connections) == 1
    assert commands[-2][0] == 'SELECT "public".hypopg_reset()'
    assert commands[-1][0] == "closed"
    plans = [sql for sql, _ in commands if sql.startswith("EXPLAIN")]
    assert plans == [f"EXPLAIN (FORMAT JSON, VERBOSE) {query}"] * 2
    assert all(sql != ddl for sql, _ in commands)
    assert any(params == (ddl,) for _, params in commands)


@pytest.mark.parametrize("vector", [False, True])
def test_policy_applies_to_implicit_single_target(monkeypatch, vector, pg_indexscan):
    from anumana import server, registry, policy
    if not hasattr(server, "preflight_query"):
        pytest.skip("MCP SDK not installed")
    monkeypatch.delenv("ANUMANA_DSN", raising=False)
    monkeypatch.setenv("ANUMANA_TARGETS", json.dumps([{"name": "production", "engine": "pgvector" if vector else "postgres", "dsn": "unused"}]))
    monkeypatch.setenv("ANUMANA_POLICIES", json.dumps([{"name": "blocked", "scope": {"target": "production"},
        "when": {"risk_at_least": "cheap"}, "action": "block"}]))
    registry.reset_registry()
    policy.reset_policies()
    monkeypatch.setattr(server, "_pg_runner", lambda _: pg_indexscan)
    try:
        tool = server.preflight_vector_search if vector else server.preflight_query
        result = json.loads(tool("SELECT id FROM orders LIMIT 10"))
        assert result["policy"]["decision"] == "block"
    finally:
        registry.reset_registry()
        policy.reset_policies()


def test_dynamo_describe_paginates(monkeypatch):
    from anumana.server import _dynamo_runner
    calls = []
    class Paginator:
        def paginate(self):
            return [{"TableNames": ["first"]}, {"TableNames": ["second"]}]
    class Client:
        def get_paginator(self, op):
            assert op == "list_tables"
            return Paginator()
        def describe_table(self, TableName):
            calls.append(TableName)
            return {"Table": {"KeySchema": [{"KeyType": "HASH", "AttributeName": "pk"}]}}
    client = Client()
    class Session:
        def __init__(self, **kwargs):
            pass
        def client(self, name):
            assert name == "dynamodb"
            return client
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=Session))
    run = _dynamo_runner("us-east-1", None)
    assert run('{"op":"Scan"}') == [None]
    assert calls == []  # preflight must not call Query or Scan
    result = run("__anumana_describe__")
    assert calls == ["first", "second"]
    assert len(result[0]["tables"]) == 2


@pytest.mark.parametrize("operator, opclass", [("<=>", "vector_cosine_ops"), ("<->", "vector_l2_ops"), ("<#>", "vector_ip_ops")])
def test_vector_index_proposal_matches_metric(operator, opclass, vec_fullscan):
    query = f"SELECT id FROM documents ORDER BY embedding {operator} '[1,2]' LIMIT 200"
    result = rewrite(vec_fullscan, query, engine="pgvector")
    proposal = result.index_suggestions[0]
    assert proposal["ddl"] == f'CREATE INDEX ON "public"."documents" USING hnsw ("embedding" {opclass})'
    assert not proposal["verified_cheaper"]
    assert proposal["simulation_status"] == "unsupported"


def test_complex_vector_expression_does_not_get_guessed_index(vec_fullscan):
    result = rewrite(vec_fullscan, "SELECT id FROM documents ORDER BY (embedding::halfvec) <=> '[1,2]' LIMIT 200", engine="pgvector")
    assert result.index_suggestions == []


@pytest.mark.parametrize("value", [None, "bad", "NaN", "inf", "-1"])
def test_mysql_invalid_cost_cannot_verify_rewrite(value):
    doc = {"query_block": {"cost_info": {"query_cost": value}, "table": {
        "table_name": "orders", "access_type": "ALL", "rows": 1000}}}
    run = lambda _: [json.dumps(doc)]
    result = rewrite(run, "SELECT * FROM orders", engine="mysql")
    assert not result.rewrite_verified
    assert result.cost_after is None
