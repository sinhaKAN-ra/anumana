"""Anumana adapters — one per query engine.

Anumana is NOT a SQL tool. Its asset is: read an engine's own cost signal and
translate it into a risk tier + plain-English behaviour + a verified rewrite.
Any engine that exposes a cost signal (a planner, a profiler, or a predictable
rule) can get an adapter. Any engine that doesn't, cannot — and we refuse to
fake one.

Scope driver: the queries AI AGENTS generate inside AI products. That reranks
targets by what agents actually query — text-to-SQL and RAG/vector search lead,
not "every database".

    Adapter          engine                         cost signal
    ---------------  -----------------------------  -----------------------------
    PostgresAdapter  Postgres (SQL)                 EXPLAIN (FORMAT JSON)      ✅ built
    PgVectorAdapter  Postgres + pgvector (RAG)      EXPLAIN on a vector search ✅ built
    MongoAdapter     MongoDB (document)             explain(queryPlanner)     ✅ built
    DynamoAdapter    DynamoDB (serverless AI)       rule-based (no planner)   ✅ built
    SqliteAdapter    SQLite (text-to-SQL base)      EXPLAIN QUERY PLAN         ○ roadmap
    MysqlAdapter     MySQL/MariaDB                  EXPLAIN FORMAT=JSON        ○ roadmap
"""
from anumana.adapters.base import Adapter, PlanResult, EngineMetrics
from anumana.adapters.postgres import PostgresAdapter
from anumana.adapters.pgvector import PgVectorAdapter
from anumana.adapters.mongodb import MongoAdapter
from anumana.adapters.dynamodb import DynamoAdapter
from anumana.adapters.falkordb import FalkorDBAdapter
from anumana.adapters.sqlite import SqliteAdapter
from anumana.adapters.mysql import MysqlAdapter
from anumana.adapters.redshift import RedshiftAdapter
from anumana.adapters.bigquery import BigQueryAdapter
from anumana.adapters.clickhouse import ClickHouseAdapter
from anumana.adapters.snowflake import SnowflakeAdapter
from anumana.adapters.cassandra import CassandraAdapter

__all__ = [
    "Adapter",
    "PlanResult",
    "EngineMetrics",
    "PostgresAdapter",
    "PgVectorAdapter",
    "MongoAdapter",
    "DynamoAdapter",
    "FalkorDBAdapter",
    "SqliteAdapter",
    "MysqlAdapter",
    "RedshiftAdapter",
    "BigQueryAdapter",
    "ClickHouseAdapter",
    "SnowflakeAdapter",
    "CassandraAdapter",
    "get_adapter",
]

_REGISTRY = {
    "postgres": PostgresAdapter,
    "postgresql": PostgresAdapter,
    "pg": PostgresAdapter,
    "pgvector": PgVectorAdapter,
    "vector": PgVectorAdapter,
    "mongodb": MongoAdapter,
    "mongo": MongoAdapter,
    "dynamodb": DynamoAdapter,
    "dynamo": DynamoAdapter,
    "falkordb": FalkorDBAdapter,
    "falkor": FalkorDBAdapter,
    "sqlite": SqliteAdapter,
    "sqlite3": SqliteAdapter,
    "mysql": MysqlAdapter,
    "mariadb": MysqlAdapter,
    "redshift": RedshiftAdapter,
    "bigquery": BigQueryAdapter,
    "bq": BigQueryAdapter,
    "clickhouse": ClickHouseAdapter,
    "snowflake": SnowflakeAdapter,
    "cassandra": CassandraAdapter,
    "scylla": CassandraAdapter,
    "scylladb": CassandraAdapter,
}


def get_adapter(engine: str = "postgres") -> Adapter:
    """Resolve an engine name to an adapter instance.

    Adapters are STATELESS, so instances are cached and shared — a tool call
    (and its follow-up rewrite) reuses one object instead of allocating a new
    adapter each time. Unknown engines fail loudly with the supported list — we
    never silently fall back and pretend an unsupported engine is analysable.
    """
    key = (engine or "postgres").strip().lower()
    cls = _REGISTRY.get(key)
    if cls is None:
        supported = sorted(set(_REGISTRY))
        raise ValueError(
            f"No Anumana adapter for engine {engine!r}. "
            f"Supported: {supported}. "
            f"SQLite/MySQL/Mongo/DynamoDB are on the roadmap (see DESIGN.md)."
        )
    inst = _INSTANCES.get(cls)
    if inst is None:
        inst = _INSTANCES[cls] = cls()
    return inst


# one shared instance per adapter class (stateless — safe to reuse)
_INSTANCES: dict = {}
