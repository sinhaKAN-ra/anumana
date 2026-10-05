"""Adapter-level tests: Mongo, Dynamo, the registry guard, and instance caching."""
import pytest

from anumana.engine import preflight
from anumana.adapters import get_adapter


def test_mongo_collscan_flagged(mongo_collscan):
    pf = preflight(mongo_collscan, '{"find":"orders","filter":{"status":"paid"}}',
                   engine="mongodb")
    assert pf.risk_tier in ("expensive", "dangerous")
    assert "MONGO_COLLSCAN" in {f.code for f in pf.flags}


def test_mongo_ixscan_clean(mongo_ixscan):
    pf = preflight(mongo_ixscan,
                   '{"find":"orders","filter":{"status":"paid"},'
                   '"projection":{"id":1},"limit":20}', engine="mongo")
    assert pf.risk_tier == "cheap"
    assert pf.flags == []


def test_dynamo_scan_is_dangerous():
    q = '{"op":"Scan","TableName":"orders","FilterExpression":"status = :s"}'
    pf = preflight(lambda s: None, q, engine="dynamodb")
    codes = {f.code for f in pf.flags}
    assert "DYNAMO_FULL_SCAN" in codes
    assert "DYNAMO_FILTER_WITHOUT_KEY" in codes


def test_dynamo_keyed_query_is_cheap():
    q = ('{"op":"Query","TableName":"orders",'
         '"KeyConditionExpression":"pk = :u","IndexName":"by_user","Limit":50}')
    pf = preflight(lambda s: None, q, engine="dynamo")
    assert pf.risk_tier == "cheap"
    assert pf.flags == []


def test_unknown_engine_fails_loudly():
    with pytest.raises(ValueError, match="No Anumana adapter"):
        get_adapter("redis")


def test_adapter_instances_are_cached():
    # stateless adapters are reused, not re-allocated per call
    assert get_adapter("postgres") is get_adapter("postgres")
    assert get_adapter("mongodb") is get_adapter("mongo")  # same class, same instance
