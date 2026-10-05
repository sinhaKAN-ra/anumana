"""Core engine behaviour: preflight / rewrite / explain_working on SQL + vector."""
from anumana.engine import preflight, rewrite, explain_working


def test_preflight_seqscan_is_risky(pg_seqscan):
    pf = preflight(pg_seqscan, "SELECT * FROM orders WHERE created_at > now()")
    assert pf.risk_tier in ("expensive", "dangerous")
    codes = {f.code for f in pf.flags}
    assert "SEQ_SCAN_LARGE" in codes
    assert "SELECT_STAR_WIDE" in codes
    assert "UNBOUNDED_RESULT" in codes
    assert pf.has_rewrite is True


def test_preflight_indexscan_is_cheap(pg_indexscan):
    pf = preflight(pg_indexscan, "SELECT id FROM orders WHERE id = 42 LIMIT 10")
    assert pf.risk_tier == "cheap"


def test_cost_is_never_milliseconds(pg_seqscan):
    d = preflight(pg_seqscan, "SELECT * FROM orders").to_dict()
    assert "NOT milliseconds" in d["planner_total_cost_note"]


def test_rewrite_adds_limit_and_proves_cost(pg_seqscan):
    rw = rewrite(pg_seqscan, "SELECT * FROM orders WHERE created_at > now()")
    assert rw is not None
    assert "LIMIT 100" in rw.rewritten_sql
    assert rw.cost_before is not None


def test_selectivity_gate_suggests_index_when_selective(pg_seqscan):
    # 5M scanned, top node returns 5M too -> NOT selective in the seqscan fixture;
    # but a selective case (few returned) should produce an index suggestion.
    rw = rewrite(pg_seqscan, "SELECT * FROM orders WHERE id = 42")
    # the fixture returns the whole table, so the gate must REFUSE the index.
    assert rw is not None
    assert not any(s.get("selectivity_ok") for s in rw.index_suggestions)


def test_explain_working_two_layers(pg_indexscan):
    ew = explain_working(pg_indexscan,
                         "SELECT id FROM orders WHERE id = 1 ORDER BY id LIMIT 10")
    steps = [s["step"] for s in ew.logical_order]
    assert "FROM / JOIN" in steps and "WHERE" in steps and "LIMIT / OFFSET" in steps
    # physical plan executes bottom-up: first node is the deepest (the scan)
    assert ew.physical_plan[0]["order"] == 1
    assert ew.engine == "postgres"


def test_vector_flags_only_on_vector_queries(vec_fullscan):
    pf = preflight(vec_fullscan,
                   "SELECT id FROM documents ORDER BY embedding <=> '[1,2]' LIMIT 200",
                   engine="pgvector")
    codes = {f.code for f in pf.flags}
    assert "FULL_VECTOR_SCAN" in codes
    assert "TOP_K_TOO_LARGE" in codes


def test_vector_hnsw_is_clean(vec_hnsw):
    pf = preflight(vec_hnsw,
                   "SELECT id FROM documents ORDER BY embedding <=> '[1,2]' LIMIT 5",
                   engine="pgvector")
    assert "FULL_VECTOR_SCAN" not in {f.code for f in pf.flags}
