"""PostgreSQL planner runner and session-local hypothetical-index verification."""
from __future__ import annotations

from anumana.sql_text import single_statement, quote_identifier


class PostgresRunner:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._relation_cache: dict[tuple[str, str], int | None] = {}

    def _connect(self):
        import psycopg
        return psycopg.connect(self.dsn, autocommit=True, connect_timeout=5,
                              options="-c default_transaction_read_only=on")

    def __call__(self, sql: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            return [row[0] if len(row) == 1 else row for row in cur.fetchall()]

    def relation_rows(self, schema: str, relation: str) -> int | None:
        """Cached catalog estimate only: never COUNT(*) or a data scan."""
        key = (schema, relation)
        if key in self._relation_cache:
            return self._relation_cache[key]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT c.reltuples FROM pg_class c JOIN pg_namespace n "
                        "ON n.oid = c.relnamespace WHERE n.nspname = %s "
                        "AND c.relname = %s", (schema, relation))
            row = cur.fetchone()
            count = int(row[0]) if row and row[0] >= 0 else None
            self._relation_cache[key] = count
            return count

    def simulate_index(self, query: str, ddl: str) -> dict:
        """EXPLAIN identical SQL before/after an in-memory HypoPG btree index.

        Dedicated connection keeps the hypothetical index session-local and
        guarantees cleanup on close, including failures. Never installs an
        extension or creates a real index.
        """
        from anumana.adapters.postgres import PostgresAdapter
        query = single_statement(query)
        adapter = PostgresAdapter()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
                        "ON n.oid = e.extnamespace WHERE e.extname = 'hypopg'")
            row = cur.fetchone()
            if not row:
                return {"simulation_status": "unavailable", "note": "HypoPG is not installed; index benefit is unverified."}
            namespace = quote_identifier(row[0])

            def run(sql):
                cur.execute(sql)
                return [r[0] if len(r) == 1 else r for r in cur.fetchall()]

            baseline = adapter.get_plan(run, query).metrics.total_cost
            try:
                # DDL is passed as a parameter to HypoPG, never cur.execute(ddl).
                cur.execute(f"SELECT * FROM {namespace}.hypopg_create_index(%s)", (ddl,))
                created = cur.fetchone()
                if not created:
                    return {"simulation_status": "failed", "note": "HypoPG created no hypothetical index."}
                plan = adapter.get_plan(run, query)
                after = plan.metrics.total_cost
                used = any(n.get("Index Name") == created[1] for n in plan.nodes)
                return {
                    "simulation_status": "verified", "simulated_with": "hypopg",
                    "simulated_cost_before": baseline, "simulated_cost_after": after,
                    "simulated_cost_delta_pct": round((after - baseline) / baseline * 100, 1) if baseline else None,
                    "hypothetical_index_used": used,
                    "verified_cheaper": used and after < baseline,
                    "note": "Same SQL, session-local hypothetical index; planner costs, not measured runtime.",
                }
            finally:
                cur.execute(f"SELECT {namespace}.hypopg_reset()")
