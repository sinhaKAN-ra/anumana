"""Opt-in, planner/metadata-only checks against operator-provided databases.

No fixture tables are created and no candidate is executed. These tests skip
unless their dedicated ANUMANA_TEST_* connection variables are set.
"""
import json
import os

import pytest

from anumana.engine import describe_schema, preflight, rewrite
from anumana.server import _pg_runner, _mysql_runner, _mongo_runner, _dynamo_runner


def configured(name):
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Set {name} to opt in to this live check")
    return value


def test_live_postgres_planner():
    run = _pg_runner(configured("ANUMANA_TEST_POSTGRES_DSN"))
    schema = describe_schema(run)
    assert schema["accuracy"] == "LIVE"
    query = os.environ.get("ANUMANA_TEST_POSTGRES_SQL", "SELECT 1")
    pf = preflight(run, query)
    assert pf.accuracy_tier == "UPPER_BOUND"
    assert pf.planner_cost_available
    result = rewrite(run, query)
    if result:
        for proposal in result.index_suggestions:
            assert proposal["simulation_status"] in {"verified", "unavailable", "failed"}


def test_live_mysql_planner():
    run = _mysql_runner(configured("ANUMANA_TEST_MYSQL_DSN"))
    assert describe_schema(run, "mysql")["accuracy"] == "LIVE"
    result = preflight(run, os.environ.get("ANUMANA_TEST_MYSQL_SQL", "SELECT 1"), engine="mysql")
    assert result.accuracy_tier == "UPPER_BOUND"


def test_live_mongo_queryplanner():
    run = _mongo_runner(configured("ANUMANA_TEST_MONGODB_URI"))
    query = os.environ.get("ANUMANA_TEST_MONGODB_QUERY")
    if not query:
        pytest.skip("Set ANUMANA_TEST_MONGODB_QUERY to a JSON find request on an existing collection")
    # The runner must return queryPlanner only, not execution statistics.
    raw = run(query)[0]
    assert "queryPlanner" in raw and "executionStats" not in raw
    result = preflight(run, query, engine="mongodb")
    assert result.accuracy_tier == "HEURISTIC"


def test_live_dynamo_metadata():
    region = configured("ANUMANA_TEST_DYNAMODB_REGION")
    run = _dynamo_runner(region, os.environ.get("ANUMANA_TEST_DYNAMODB_PROFILE"))
    result = describe_schema(run, "dynamodb")
    assert result["accuracy"] == "LIVE"
    # Only metadata is fetched; candidate request shape is judged offline.
    for table in result["tables"]:
        pf = preflight(run, json.dumps({"op": "Scan", "TableName": table["name"]}), engine="dynamodb")
        assert pf.accuracy_tier == "HEURISTIC"
        assert "DYNAMO_FULL_SCAN" in {flag.code for flag in pf.flags}
