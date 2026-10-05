"""Generative mode: describe_schema (Phase 1), suggest_query (Phase 2),
registry (Phase 3), policy (Phase 4). Zero DB."""
import json

import pytest

from anumana.engine import describe_schema, suggest_query


# ---- Phase 1: describe_schema ----------------------------------------------
def test_describe_schema_live_postgres(pg_catalog):
    d = describe_schema(pg_catalog, engine="postgres")
    assert d["accuracy"] == "LIVE"
    t = d["tables"][0]
    assert t["name"] == "orders"
    assert len(t["columns"]) == 3
    assert t["indexes"][0]["columns"] == ["id"]
    assert t["row_count"] == 500_000


def test_describe_schema_fallback_to_ask():
    def denied(sql):
        raise PermissionError("no USAGE")
    d = describe_schema(denied, engine="postgres")
    assert d["accuracy"] == "NONE"
    assert d["need_from_user"]  # names what to ask the user for
    assert not d["tables"]


def test_describe_schema_mongo_sampled(mongo_describe):
    d = describe_schema(mongo_describe, engine="mongodb")
    assert d["accuracy"] == "SAMPLED"
    assert d["tables"][0]["caveats"]  # honest: fields are sampled


def test_describe_schema_dynamo_keys(dynamo_describe):
    d = describe_schema(dynamo_describe, engine="dynamodb")
    cols = [c["name"] for c in d["tables"][0]["columns"]]
    assert "user_id" in cols  # partition key surfaced


# ---- Phase 2: suggest_query loop -------------------------------------------
def test_suggest_query_refines_bad_candidate(pg_seqscan):
    v = suggest_query(pg_seqscan, "last 7 days of orders",
                      "SELECT * FROM orders WHERE created_at > now()")
    assert v["next_action"] == "refine"
    assert v["accept"] is False
    assert v["suggested_sql"]  # a rewrite to try next


def test_suggest_query_accepts_good_candidate(pg_indexscan):
    v = suggest_query(pg_indexscan, "one order by id",
                      "SELECT id FROM orders WHERE id = 42 LIMIT 1")
    assert v["next_action"] == "accept"
    assert v["accept"] is True


# ---- Phase 3: registry ------------------------------------------------------
def test_registry_loads_targets_and_hides_secrets(monkeypatch):
    from anumana import registry as reg_mod
    monkeypatch.setenv("ANUMANA_TARGETS", json.dumps([
        {"name": "orders_pg", "engine": "postgres", "dsn": "postgres://ro@h/o"},
        {"name": "cache", "engine": "redis", "dsn": "redis://h"},
    ]))
    reg_mod.reset_registry()
    reg = reg_mod.registry()
    pub = reg.list()
    names = {t["name"] for t in pub}
    assert names == {"orders_pg", "cache"}
    # secrets never leak into the public view
    assert all("dsn" not in t and "uri" not in t for t in pub)
    # redis is registered but refused as non-diagnosable
    assert any(t["name"] == "cache" and t["diagnosable"] is False for t in pub)
    with pytest.raises(ValueError, match="no pre-run cost signal"):
        reg.get("cache")
    reg_mod.reset_registry()


def test_registry_legacy_single_dsn(monkeypatch):
    from anumana import registry as reg_mod
    monkeypatch.delenv("ANUMANA_TARGETS", raising=False)
    monkeypatch.setenv("ANUMANA_DSN", "postgres://ro@h/legacy")
    reg_mod.reset_registry()
    reg = reg_mod.registry()
    assert reg.get(None).name == "default"
    reg_mod.reset_registry()


# ---- Phase 4: policy --------------------------------------------------------
def test_policy_blocks_dangerous_on_scoped_target(monkeypatch):
    from anumana import policy as pol_mod
    monkeypatch.setenv("ANUMANA_POLICIES", json.dumps([
        {"name": "no-danger-prod", "scope": {"target": "prod"},
         "when": {"risk_at_least": "dangerous"}, "action": "block"},
    ]))
    pol_mod.reset_policies()
    ps = pol_mod.policies()
    v = ps.evaluate(target="prod", engine="postgres", risk="dangerous",
                    flag_codes={"SEQ_SCAN_LARGE"})
    assert v.decision == "block"
    # scope miss -> allow
    v2 = ps.evaluate(target="staging", engine="postgres", risk="dangerous",
                     flag_codes=set())
    assert v2.decision == "allow"
    pol_mod.reset_policies()


def test_policy_open_by_default(monkeypatch):
    from anumana import policy as pol_mod
    monkeypatch.delenv("ANUMANA_POLICIES", raising=False)
    pol_mod.reset_policies()
    v = pol_mod.policies().evaluate(target="x", engine="postgres",
                                    risk="dangerous", flag_codes=set())
    assert v.decision == "allow"
    pol_mod.reset_policies()
