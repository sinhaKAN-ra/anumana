"""Runnable demo — proves the engine works with ZERO database and ZERO deps.

A fake `run_sql` returns a canned EXPLAIN (FORMAT JSON) plan, exactly shaped like
real Postgres output, for the classic "SELECT * ... no index ... no LIMIT" case.

Run:  python3 src/demo.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from anumana.engine import preflight, rewrite  # noqa: E402

# A real Postgres EXPLAIN (FORMAT JSON) doc for a Seq Scan over a big table.
_FAKE_PLAN = [{
    "Plan": {
        "Node Type": "Limit",
        "Total Cost": 15629.12,
        "Plan Rows": 12,
        "Plans": [{
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Total Cost": 15629.12,
            "Plan Rows": 40000000,
        }],
    }
}]


# A pgvector similarity search with NO vector index -> brute-force Seq Scan.
_FAKE_VECTOR_PLAN = [{
    "Plan": {
        "Node Type": "Limit",
        "Total Cost": 88421.0,
        "Plan Rows": 200,
        "Plans": [{
            "Node Type": "Seq Scan",
            "Relation Name": "documents",
            "Total Cost": 88421.0,
            "Plan Rows": 2000000,
        }],
    }
}]


def fake_run_sql(sql: str):
    # Return the same SQL plan regardless of query — enough to exercise the engine.
    return [{"QUERY PLAN": _FAKE_PLAN}]


def fake_run_vector(sql: str):
    return [{"QUERY PLAN": _FAKE_VECTOR_PLAN}]


SQL = "SELECT * FROM orders WHERE created_at > now() - interval '7 days'"
VECTOR_SQL = (
    "SELECT id, chunk FROM documents "
    "ORDER BY embedding <=> '[0.1,0.2,0.3]' LIMIT 200"
)


def _dump(label, obj):
    print(f"\n{label}:")
    print(json.dumps(obj, indent=2, default=lambda o: o.__dict__))


def main():
    print("=" * 70)
    print("ANUMANA — foresight for AI-agent queries (no DB, no deps)")
    print("=" * 70)

    # ---- 1. text-to-SQL (the classic agent query) --------------------------
    print(f"\n[1] TEXT-TO-SQL\nQuery:\n  {SQL}")
    pf = preflight(fake_run_sql, SQL, has_live_stats=True)
    _dump("PRE-FLIGHT", pf.to_dict())
    rw = rewrite(fake_run_sql, SQL, has_live_stats=True)
    _dump("REWRITE", rw.__dict__)
    print(f"\nVERDICT: risk={pf.risk_tier}  flags={[f.code for f in pf.flags]}")
    print(f"planner cost {rw.cost_before} -> {rw.cost_after} ({rw.cost_delta_pct}%)")

    # ---- 2. RAG / vector search (the dominant AI workload) -----------------
    print("\n" + "-" * 70)
    print(f"[2] RAG / VECTOR SEARCH (engine='pgvector')\nQuery:\n  {VECTOR_SQL}")
    vpf = preflight(fake_run_vector, VECTOR_SQL, engine="pgvector")
    _dump("PRE-FLIGHT", vpf.to_dict())
    print(f"\nVERDICT: risk={vpf.risk_tier}  flags={[f.code for f in vpf.flags]}")
    print("  ^ FULL_VECTOR_SCAN + TOP_K_TOO_LARGE are vector-specific — a plain")
    print("    SQL check would miss them. This is the RAG wedge.")

    print("\n" + "=" * 70)
    print("NOTE: planner cost is unitless, NOT milliseconds — by design.")
    print("=" * 70)


if __name__ == "__main__":
    main()
