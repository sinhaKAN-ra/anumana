"""Live engine test via psql (no psycopg needed) against the scratch Postgres.

run_sql shells out to psql with -A -t and json output, returning rows shaped
like a DB-API cursor so engine.py is unchanged.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from anumana.engine import preflight, rewrite  # noqa: E402

PGDIR = os.environ["PGDIR"]
PSQL = ["psql", "-h", "127.0.0.1", "-p", "55432", "-U", "postgres",
        "-d", "anumana_test", "-A", "-t", "-X"]


def run_sql(sql):
    # EXPLAIN (FORMAT JSON) returns one text cell containing the json array
    out = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C"})
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    text = out.stdout.strip()
    try:
        return [json.loads(text)]          # EXPLAIN JSON path
    except json.JSONDecodeError:
        return [text]                       # non-explain (unused here)


def show(label, sql):
    print(f"\n{'='*68}\n{label}\n{'='*68}\n  {sql}")
    pf = preflight(run_sql, sql, has_live_stats=True)
    print(f"\n  risk      : {pf.risk_tier}")
    print(f"  scanned   : ~{pf.rows_scanned_est:,} rows -> ~{pf.rows_returned_est:,} returned")
    print(f"  strategy  : {' / '.join(pf.scan_strategy)}")
    print(f"  cost      : {pf.planner_total_cost} (unitless, NOT ms)")
    print(f"  flags     : {[f.code for f in pf.flags] or 'none'}")
    rw = rewrite(run_sql, sql, has_live_stats=True)
    if rw:
        print(f"  rewrite   : cost {rw.cost_before} -> {rw.cost_after} ({rw.cost_delta_pct}%)")
        for c in rw.changes:
            print(f"              - {c}")


if __name__ == "__main__":
    show("TEST 1 — slow AI-written query (SELECT *, no index, no LIMIT)",
         "SELECT * FROM orders WHERE created_at > now() - interval '7 days'")
    show("TEST 2 — same filter, bounded + projected",
         "SELECT id, total FROM orders WHERE created_at > now() - interval '7 days' LIMIT 50")
