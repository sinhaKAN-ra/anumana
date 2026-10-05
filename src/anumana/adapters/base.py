"""Adapter interface — the contract every engine adapter implements.

The engine-agnostic layers (risk tiering, plain-English explanation, rewrite
proof) sit ON TOP of this. An adapter's job is only three things:

  1. get_plan(run_sql, query)  -> a normalized plan + the raw engine plan
  2. detect_flags(query, plan) -> deterministic overhead flags
  3. extract_metrics(plan)     -> normalized rows_scanned / rows_returned / cost

So adding an engine never touches the risk/English/rewrite code — you only
teach Anumana how to READ that engine's cost signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, runtime_checkable

Severity = Literal["low", "medium", "high"]


@dataclass
class EngineFlag:
    """A deterministic overhead finding — never an LLM guess."""
    code: str
    detail: str
    severity: Severity


@dataclass
class EngineMetrics:
    """Normalized numbers every adapter must produce, so the risk tiering is
    engine-agnostic. For engines with no row planner (DynamoDB), rows_* may be
    0 and the adapter leans on flags + a rule-based cost instead."""
    rows_scanned: int = 0
    rows_returned: int = 0
    total_cost: float = 0.0
    cost_is_unitless: bool = True  # planner cost is NOT milliseconds — ever
    strategy: list[str] = field(default_factory=list)


@dataclass
class PlanResult:
    """What get_plan returns: the raw engine plan plus a normalized view the
    cross-engine layers can walk without knowing the engine."""
    raw: Any                     # the engine's own plan object (PG JSON, Mongo doc, ...)
    nodes: list[dict]            # flattened, normalized plan nodes (depth-first)
    metrics: EngineMetrics
    has_live_stats: bool = True  # False in schema-only / rule-based modes


@dataclass
class SchemaTable:
    """One table / collection, normalized across engines. Fields the engine
    cannot supply are left empty and `caveats` says why (honesty rail)."""
    name: str
    columns: list[dict] = field(default_factory=list)   # [{name, type}]
    indexes: list[dict] = field(default_factory=list)   # [{name, columns, kind}]
    row_count: int | None = None                        # None when unknown
    caveats: list[str] = field(default_factory=list)


@dataclass
class SchemaDescription:
    """What describe_schema returns, so the agent can write a grounded query
    instead of guessing the schema. Either `tables` is populated, OR
    `need_from_user` names exactly what to ask the user for (no connection /
    read denied) — never both empty silently."""
    engine: str
    tables: list[SchemaTable] = field(default_factory=list)
    accuracy: Literal["LIVE", "SAMPLED", "DECLARED", "NONE"] = "NONE"
    need_from_user: str | None = None   # set when the schema could not be read
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class Adapter(Protocol):
    """The engine contract. `name` is used in diagnostics and the registry."""

    name: str
    #: human label shown in output, e.g. "Postgres" / "pgvector (RAG)"
    label: str

    def get_plan(
        self, run_sql: Callable[[str], list], query: str
    ) -> PlanResult:
        """Ask the engine what it WOULD do, without running the query.
        For SQL engines this is EXPLAIN (never ANALYZE)."""
        ...

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        """Deterministic overhead flags from the plan + the query text."""
        ...

    def node_reason(self, node: dict) -> str:
        """Plain-English reason for one physical plan node (for explain_working)."""
        ...

    def headline(self, plan: PlanResult) -> str:
        """The one sentence a dev needs about the dominant cost."""
        ...

    def describe_schema(
        self, run_sql: Callable[[str], list]
    ) -> SchemaDescription:
        """Read the engine's OWN catalog so the agent can write a grounded query.
        READ-ONLY catalog access — never reads data rows (Mongo samples keys,
        disclosed). On failure, returns a SchemaDescription whose
        `need_from_user` names what to ask the user for."""
        ...
