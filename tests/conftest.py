"""Shared fixtures — canned EXPLAIN / explain() docs so the whole suite runs with
NO database and NO drivers (fast, CI-safe). Each run_sql fixture is a plain
callable returning the shape the matching adapter expects."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


# ---- Postgres canned plans --------------------------------------------------
def _pg_doc(plan):
    return [{"QUERY PLAN": [{"Plan": plan}]}]


@pytest.fixture
def pg_seqscan():
    """A big Seq Scan: SELECT *, no LIMIT -> expensive/dangerous."""
    plan = {"Node Type": "Seq Scan", "Relation Name": "orders",
            "Total Cost": 14000.0, "Plan Rows": 5_000_000}
    return lambda sql: _pg_doc(plan)


@pytest.fixture
def pg_indexscan():
    """A selective Index Scan, bounded -> cheap."""
    plan = {"Node Type": "Limit", "Total Cost": 8.4, "Plan Rows": 40,
            "Plans": [{"Node Type": "Index Scan", "Relation Name": "orders",
                       "Total Cost": 8.0, "Plan Rows": 40}]}
    return lambda sql: _pg_doc(plan)


@pytest.fixture
def pg_catalog():
    """information_schema / pg_indexes / pg_class rows for describe_schema."""
    cols = [("orders", "id", "integer"), ("orders", "created_at", "timestamp"),
            ("orders", "status", "text")]
    idx = [("orders", "orders_pkey",
            "CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (id)")]
    rows = [("orders", 500_000)]

    def run_sql(sql):
        if "information_schema.columns" in sql:
            return cols
        if "pg_indexes" in sql:
            return idx
        if "pg_class" in sql:
            return rows
        raise AssertionError(f"unexpected catalog query: {sql[:40]}")

    return run_sql


# ---- pgvector canned plans --------------------------------------------------
@pytest.fixture
def vec_fullscan():
    """Similarity search with NO vector index -> brute-force Seq Scan."""
    plan = {"Node Type": "Limit", "Total Cost": 88000.0, "Plan Rows": 200,
            "Plans": [{"Node Type": "Seq Scan", "Relation Name": "documents",
                       "Total Cost": 88000.0, "Plan Rows": 2_000_000}]}
    return lambda sql: _pg_doc(plan)


@pytest.fixture
def vec_hnsw():
    """Similarity search backed by an HNSW index -> cheap ANN path."""
    plan = {"Node Type": "Limit", "Total Cost": 12.0, "Plan Rows": 10,
            "Plans": [{"Node Type": "Index Scan", "Relation Name": "documents",
                       "Index Name": "documents_embedding_hnsw",
                       "Total Cost": 12.0, "Plan Rows": 10}]}
    return lambda sql: _pg_doc(plan)


# ---- Mongo canned explain docs ----------------------------------------------
@pytest.fixture
def mongo_collscan():
    doc = {"queryPlanner": {"namespace": "app.orders",
                            "winningPlan": {"stage": "COLLSCAN"}}}
    return lambda cmd: [doc]


@pytest.fixture
def mongo_ixscan():
    doc = {"queryPlanner": {"namespace": "app.orders",
                            "winningPlan": {"stage": "FETCH",
                                            "inputStage": {"stage": "IXSCAN",
                                                           "indexName": "status_1"}}}}
    return lambda cmd: [doc]


@pytest.fixture
def mongo_describe():
    doc = {"collections": [{"name": "orders",
                            "sample_fields": ["_id", "status", "total"],
                            "indexes": [{"name": "status_1", "key": {"status": 1}}],
                            "est_count": 120_000}]}
    return lambda cmd: [doc]


# ---- Dynamo canned describe doc ---------------------------------------------
@pytest.fixture
def dynamo_describe():
    doc = {"tables": [{"name": "orders",
                       "key_schema": {"partition_key": "user_id",
                                      "sort_key": "created_at"},
                       "gsis": [{"name": "by_status", "keys": ["status"]}],
                       "item_count": 900_000}]}
    return lambda cmd: [doc]
