"""Anumana — foresight for the queries AI agents write.

Pre-flight cost + rewrite + execution-order explanation for the queries that AI
coding agents generate inside AI products: text-to-SQL today, RAG / vector
search (pgvector) alongside it. Engine-agnostic via adapters.

Public API:
    from anumana.engine import preflight, rewrite, explain_working
    from anumana.adapters import get_adapter, PostgresAdapter, PgVectorAdapter
    from anumana.schema_only import analyse_static
    from anumana.server import main            # console entry point

    # SQL (default) and vector (RAG) use the same calls, different engine:
    preflight(run_sql, sql)                       # Postgres
    preflight(run_sql, vector_sql, engine="pgvector")   # RAG similarity search
"""
__version__ = "0.2.0"
