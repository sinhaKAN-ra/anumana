"""Anumana multi-DB registry — Phase 3 of generative mode.

Today one process = one ANUMANA_DSN = one database. A platform needs to hold
SEVERAL databases and let the agent pick which one a request is about. This
module is that registry.

Config source (operator-set, once): the ANUMANA_TARGETS env var holds a JSON
array of named targets. Example:

    ANUMANA_TARGETS='[
      {"name":"orders_pg","engine":"postgres","dsn":"postgres://ro@h/orders"},
      {"name":"docs_vec","engine":"pgvector","dsn":"postgres://ro@h/docs"},
      {"name":"events_mongo","engine":"mongodb","uri":"mongodb://ro@h/events"},
      {"name":"sessions_ddb","engine":"dynamodb","region":"us-east-1"}
    ]'

A single legacy ANUMANA_DSN still works — it is registered as a target named
"default" (engine postgres unless ANUMANA_ENGINE overrides), so nothing that
worked before breaks.

Guardrails baked in:
  - every target declares its engine; an engine with NO cost signal (redis, …)
    is registered as diagnosable=False and REFUSED loudly, never faked.
  - connection secrets live in the config value, never in a tool argument the
    model sees — the agent references a target BY NAME; the DSN stays server-side.
  - credentials should be READ-ONLY roles (Anumana only EXPLAINs/describes), and
    the registry carries a `read_only` flag so an operator's intent is explicit.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

# engines Anumana can actually diagnose (have a cost signal). Anything else is
# registered but refused — we never pretend to foresee a cost we cannot read.
# Cassandra/DynamoDB have no planner but a DETERMINISTIC rule-based cost signal
# (partition-key presence), so they count as diagnosable. Redis (no planner, no
# predictable rule) is deliberately NOT here.
_DIAGNOSABLE = {"postgres", "postgresql", "pg", "pgvector", "vector",
                "mongodb", "mongo", "dynamodb", "dynamo",
                "sqlite", "sqlite3", "mysql", "mariadb",
                "redshift", "bigquery", "bq", "clickhouse", "snowflake",
                "falkordb", "falkor", "cassandra", "scylla", "scylladb"}


@dataclass
class Target:
    name: str
    engine: str
    #: connection handle kept SERVER-SIDE — never serialized into tool output.
    connection: dict = field(default_factory=dict, repr=False)
    read_only: bool = True
    diagnosable: bool = True
    note: str = ""

    def public(self) -> dict:
        """Safe view for the agent: NO connection secrets, just name/engine/flags."""
        return {
            "name": self.name,
            "engine": self.engine,
            "read_only": self.read_only,
            "diagnosable": self.diagnosable,
            "note": self.note,
        }


class Registry:
    def __init__(self) -> None:
        self._targets: dict[str, Target] = {}

    # ---- loading ------------------------------------------------------------
    def load_from_env(self) -> "Registry":
        """Load ANUMANA_TARGETS (JSON array) plus a legacy single ANUMANA_DSN."""
        raw = os.environ.get("ANUMANA_TARGETS")
        if raw:
            try:
                for entry in json.loads(raw):
                    self.add(entry)
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(f"ANUMANA_TARGETS is not valid JSON: {e}") from e

        legacy = os.environ.get("ANUMANA_DSN")
        if legacy and "default" not in self._targets:
            self.add({
                "name": "default",
                "engine": os.environ.get("ANUMANA_ENGINE", "postgres"),
                "dsn": legacy,
            })
        return self

    def add(self, entry: dict) -> Target:
        name = entry.get("name")
        engine = (entry.get("engine") or "postgres").strip().lower()
        if not name:
            raise ValueError(f"target missing 'name': {entry!r}")
        # pull connection fields out so they stay server-side
        conn = {k: v for k, v in entry.items()
                if k in ("dsn", "uri", "region", "profile", "database", "path")}
        diagnosable = engine in _DIAGNOSABLE
        t = Target(
            name=name, engine=engine, connection=conn,
            read_only=bool(entry.get("read_only", True)),
            diagnosable=diagnosable,
            note=entry.get("note", "" if diagnosable else
                 f"engine '{engine}' has no pre-run cost signal — not diagnosable"),
        )
        self._targets[name] = t
        return t

    # ---- access -------------------------------------------------------------
    def list(self) -> list[dict]:
        """Public, secret-free list for the agent."""
        return [t.public() for t in self._targets.values()]

    def get(self, name: str | None) -> Target:
        """Resolve a target by name. With one target and no name, return it.
        Fails loudly on unknown name or on a non-diagnosable engine."""
        if name is None:
            if len(self._targets) == 1:
                return next(iter(self._targets.values()))
            raise ValueError(
                "Multiple targets configured — specify target=<name>. "
                f"Available: {sorted(self._targets)}"
            )
        t = self._targets.get(name)
        if t is None:
            raise ValueError(
                f"No target named {name!r}. Available: {sorted(self._targets)}"
            )
        if not t.diagnosable:
            raise ValueError(
                f"Target {name!r} is engine '{t.engine}', which has no pre-run "
                f"cost signal — Anumana refuses to fake a diagnosis for it."
            )
        return t

    def is_empty(self) -> bool:
        return not self._targets


# module-level singleton, loaded lazily so import never needs the env set.
_REGISTRY: Registry | None = None


def registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry().load_from_env()
    return _REGISTRY


def reset_registry() -> None:
    """Test hook — force a reload on next registry() call."""
    global _REGISTRY
    _REGISTRY = None
