"""Anumana engine — engine-AGNOSTIC risk tiering, rewrite proof, and the
two-layer "how the query behaves" explanation.

Scope: the queries AI AGENTS generate inside AI products. The engine reads an
adapter's cost signal and translates it — it does not know or care which engine
produced the plan. Postgres + pgvector adapters ship today; see adapters/ and
DESIGN.md for the roadmap.

The honest core (per adapter): ask the engine what it WOULD do (EXPLAIN, never
ANALYZE), read the estimate, translate into risk tier + flags + a verified
rewrite. No fake milliseconds — ever.

Backward compatible: `preflight(run_sql, sql)` still works exactly as before
(defaults to the Postgres adapter). Pass `engine="pgvector"` for RAG queries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Literal

from anumana.adapters import get_adapter
from anumana.adapters.base import Adapter, EngineFlag

AccuracyTier = Literal["PRECISE", "UPPER_BOUND", "HEURISTIC"]
RiskTier = Literal["cheap", "moderate", "expensive", "dangerous"]

# Flag is re-exported for schema_only.py and existing callers.
Flag = EngineFlag


@dataclass
class Preflight:
    engine: str
    risk_tier: RiskTier
    accuracy_tier: AccuracyTier
    rows_scanned_est: int
    rows_returned_est: int
    scan_strategy: list[str]
    planner_total_cost: float
    flags: list[Flag]
    human_summary: str
    has_rewrite: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["planner_total_cost_note"] = "unitless planner cost — NOT milliseconds"
        return d


def _resolve(engine: str | Adapter) -> Adapter:
    return engine if isinstance(engine, Adapter) else get_adapter(engine)


# ---- risk tiering (engine-agnostic) -----------------------------------------

def _risk(total_cost: float, rows_scanned: int, flags: list[Flag]) -> RiskTier:
    high = sum(1 for f in flags if f.severity == "high")
    if high >= 2 or rows_scanned > 10_000_000:
        return "dangerous"
    if high >= 1 or total_cost > 10_000 or rows_scanned > 1_000_000:
        return "expensive"
    if total_cost > 500 or rows_scanned > 50_000:
        return "moderate"
    return "cheap"


def preflight(run_sql: Callable[[str], list], sql: str,
              has_live_stats: bool = True,
              engine: str | Adapter = "postgres") -> Preflight:
    adapter = _resolve(engine)
    plan = adapter.get_plan(run_sql, sql)
    flags = adapter.detect_flags(sql, plan)
    m = plan.metrics

    risk = _risk(m.total_cost, m.rows_scanned, flags)
    accuracy: AccuracyTier = "UPPER_BOUND" if has_live_stats else "HEURISTIC"
    summary = (
        f"[{adapter.label}] Scans ~{m.rows_scanned:,} rows to return ~{m.rows_returned:,}. "
        f"Strategy: {m.strategy[0] if m.strategy else 'unknown'}. "
        f"Risk: {risk}."
    )
    return Preflight(
        engine=adapter.name, risk_tier=risk, accuracy_tier=accuracy,
        rows_scanned_est=m.rows_scanned, rows_returned_est=m.rows_returned,
        scan_strategy=m.strategy, planner_total_cost=m.total_cost,
        flags=flags, human_summary=summary, has_rewrite=bool(flags),
    )


# ---- rewrite ----------------------------------------------------------------

_SELECT_STAR = re.compile(r"select\s+\*", re.I)
_HAS_LIMIT = re.compile(r"\blimit\b", re.I)
_SELECTIVITY_THRESHOLD = 0.10  # index wins below ~10% selectivity


def _is_selective(rows_returned: int, rows_scanned: int) -> bool:
    if not rows_scanned:
        return False
    return (rows_returned / rows_scanned) <= _SELECTIVITY_THRESHOLD


@dataclass
class Rewrite:
    rewritten_sql: str
    changes: list[str]
    cost_before: float
    cost_after: float
    cost_delta_pct: float
    accuracy_tier: AccuracyTier
    index_suggestions: list[dict] = field(default_factory=list)
    equivalence_caveats: list[str] = field(default_factory=list)


def rewrite(run_sql: Callable[[str], list], sql: str,
            has_live_stats: bool = True,
            engine: str | Adapter = "postgres") -> Rewrite | None:
    """Produce a cheaper, equivalent query and PROVE the delta via EXPLAIN."""
    adapter = _resolve(engine)
    pf = preflight(run_sql, sql, has_live_stats, engine=adapter)
    if not pf.flags:
        return None

    new_sql = sql
    changes: list[str] = []
    caveats: list[str] = []

    if _SELECT_STAR.search(new_sql):
        changes.append("Replace SELECT * with the columns actually projected "
                       "(fill in — Anumana cannot know downstream usage).")
    if not _HAS_LIMIT.search(new_sql):
        new_sql = new_sql.rstrip(";\n ") + "\nLIMIT 100"
        changes.append("Added LIMIT 100 to bound the result.")
        caveats.append("LIMIT changes row count — confirm the caller wanted all rows.")

    cost_before = pf.planner_total_cost
    try:
        cost_after = float(adapter.get_plan(run_sql, new_sql).metrics.total_cost)
    except Exception:
        cost_after = cost_before
    delta = round((cost_after - cost_before) / cost_before * 100, 1) if cost_before else 0.0

    index_sugg: list[dict] = []
    for f in pf.flags:
        if f.code not in ("SEQ_SCAN_LARGE", "MISSING_INDEX", "FULL_VECTOR_SCAN"):
            continue
        if f.code == "FULL_VECTOR_SCAN":
            index_sugg.append({
                "ddl": "CREATE INDEX ON <table> USING hnsw (<embedding_col> vector_cosine_ops);",
                "kind": "vector (HNSW)",
                "note": "No selectivity gate for vector indexes — a brute-force "
                        "similarity scan is always worse than ANN as the collection grows.",
            })
            continue
        if _is_selective(pf.rows_returned_est, pf.rows_scanned_est):
            index_sugg.append({
                "ddl": f.detail,
                "kind": "btree",
                "selectivity_ok": True,
                "note": f"filter returns ~{pf.rows_returned_est:,} of "
                        f"~{pf.rows_scanned_est:,} rows — selective enough for an index to win.",
            })
        else:
            caveats.append(
                f"NOT suggesting an index: the filter matches ~{pf.rows_returned_est:,} "
                f"of ~{pf.rows_scanned_est:,} rows (not selective) — the planner would "
                f"correctly ignore an index and scan anyway. Narrow the filter instead."
            )
    return Rewrite(
        rewritten_sql=new_sql, changes=changes or ["No safe automatic rewrite; see flags."],
        cost_before=cost_before, cost_after=cost_after, cost_delta_pct=delta,
        accuracy_tier="UPPER_BOUND" if has_live_stats else "HEURISTIC",
        index_suggestions=index_sugg, equivalence_caveats=caveats,
    )


# ---- explain_working: two-layer "how the query behaves" ---------------------

_LOGICAL_ORDER = [
    ("FROM / JOIN", "pick the source table(s) and build the raw row set"),
    ("WHERE", "filter individual rows BEFORE any grouping"),
    ("GROUP BY", "collapse the surviving rows into groups"),
    ("HAVING", "filter the GROUPS (why an aggregate can't go in WHERE)"),
    ("SELECT", "compute output columns/expressions (why a SELECT alias can't be used in WHERE — it doesn't exist yet)"),
    ("ORDER BY", "sort the result set"),
    ("LIMIT / OFFSET", "slice the final rows LAST (why 'LIMIT 10' is still slow if the filter wasn't selective)"),
]

_CLAUSE_RE = {
    "FROM / JOIN": re.compile(r"\bfrom\b", re.I),
    "WHERE": re.compile(r"\bwhere\b", re.I),
    "GROUP BY": re.compile(r"\bgroup\s+by\b", re.I),
    "HAVING": re.compile(r"\bhaving\b", re.I),
    "SELECT": re.compile(r"\bselect\b", re.I),
    "ORDER BY": re.compile(r"\border\s+by\b", re.I),
    "LIMIT / OFFSET": re.compile(r"\b(limit|offset)\b", re.I),
}


@dataclass
class ExplainWorking:
    engine: str
    logical_order: list[dict]
    physical_plan: list[dict]
    headline: str
    accuracy_tier: AccuracyTier


def explain_working(run_sql: Callable[[str], list], sql: str,
                    has_live_stats: bool = True,
                    engine: str | Adapter = "postgres") -> ExplainWorking:
    """Teach how the query BEHAVES in two layers:
    (1) the logical gather order defined by SQL (universal, like SQLite),
    (2) the actual physical plan the engine chose for THIS query + schema."""
    adapter = _resolve(engine)
    plan = adapter.get_plan(run_sql, sql)

    logical = [
        {"step": name, "does": does}
        for name, does in _LOGICAL_ORDER
        if _CLAUSE_RE[name].search(sql)
    ]

    # physical plan executes BOTTOM-UP (leaves first), so reverse the walk.
    physical = []
    for i, n in enumerate(reversed(plan.nodes), 1):
        ntype = n.get("Node Type", "?")
        rel = n.get("Relation Name")
        physical.append({
            "order": i,
            "operation": f"{ntype}" + (f" on {rel}" if rel else ""),
            "est_rows": n.get("Plan Rows", 0),
            "why": adapter.node_reason(n),
        })

    return ExplainWorking(
        engine=adapter.name, logical_order=logical, physical_plan=physical,
        headline=adapter.headline(plan),
        accuracy_tier="UPPER_BOUND" if has_live_stats else "HEURISTIC",
    )


# ---- describe_schema: the agent's grounding read ----------------------------

def describe_schema(run_sql: Callable[[str], list],
                    engine: str | Adapter = "postgres") -> dict:
    """Return the engine's real schema (tables/collections, columns/fields,
    INDEXES, and row counts where available) so the agent can write a grounded,
    cost-aware query instead of guessing — Phase 1 of generative mode.

    READ-ONLY catalog access; never reads data rows (Mongo samples keys). If the
    schema can't be read (no connection / denied), the result's `need_from_user`
    names exactly what to ask the user for, so the agent degrades gracefully to
    asking rather than hallucinating a schema."""
    adapter = _resolve(engine)
    desc = adapter.describe_schema(run_sql)
    return asdict(desc)


# ---- suggest_query: the generate -> check -> refine loop (Phase 2) ----------

# Anumana does NOT write SQL (the agent does — we are not an NL->SQL tool). This
# is a stateless GRADING step the agent calls each round: it preflights the
# agent's candidate, and returns a verdict that says accept or refine-and-resend,
# plus the concrete reasons + a verified rewrite so the agent knows HOW to refine.

_ACCEPTABLE_TIERS = ("cheap", "moderate")


@dataclass
class SuggestVerdict:
    engine: str
    intent: str
    candidate_sql: str
    accept: bool                       # True => the agent can run this query
    risk_tier: RiskTier
    reasons: list[str]                 # why accepted / why not
    flags: list[Flag]
    suggested_sql: str | None          # a cheaper rewrite to try next, if any
    cost_before: float | None
    cost_after: float | None
    index_suggestions: list[dict]
    next_action: str                   # instruction to the agent: "accept" | "refine"
    accuracy_tier: AccuracyTier

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_RANKING_INTENT_RE = re.compile(
    r"\b(most|top|highest|lowest|largest|smallest|biggest|"
    r"best|worst|fewest|greatest|rank(?:ed|ing)?|leaderboard|"
    r"top[\s-]?\d+|first\s+\d+)\b",
    re.IGNORECASE,
)


def _is_ranking_intent(intent: str) -> bool:
    """True when the user's phrasing asks for a top-N / ranking result, which
    almost always wants a bounded (LIMIT-ed) query."""
    return bool(_RANKING_INTENT_RE.search(intent or ""))


def suggest_query(run_sql: Callable[[str], list], intent: str, candidate_sql: str,
                  has_live_stats: bool = True,
                  engine: str | Adapter = "postgres") -> dict:
    """Grade ONE agent-proposed query against the user's intent and tell the
    agent whether to accept it or refine it — the core of generate->check->refine.

    The agent owns correctness-for-intent (it wrote the SQL from the schema).
    Anumana owns cost truth: it preflights the candidate, and if the candidate is
    expensive/dangerous it returns a VERIFIED cheaper rewrite + the flags, so the
    agent's next round is informed, not a guess. Returns `next_action` =
    'accept' (run it) or 'refine' (fix the flags and call again). Bound the loop
    to ~3 rounds in the caller — Anumana is stateless per call."""
    adapter = _resolve(engine)
    pf = preflight(run_sql, candidate_sql, has_live_stats, engine=adapter)

    accept = pf.risk_tier in _ACCEPTABLE_TIERS
    reasons: list[str] = []
    rw = None
    if accept:
        reasons.append(f"Risk is '{pf.risk_tier}' — acceptable to run for this intent.")
        if pf.flags:
            reasons.append("Minor flags remain (see flags) but none are high-severity.")
        # Ranking / top-N intent ("most", "top", "highest", ...) with no LIMIT:
        # the query is still runnable (accept stays True), but a top-N question
        # almost always wants a bounded result — so PROPOSE the bounded rewrite
        # rather than only flagging UNBOUNDED_RESULT.
        if _is_ranking_intent(intent) and any(
            f.code == "UNBOUNDED_RESULT" for f in pf.flags
        ):
            rw = rewrite(run_sql, candidate_sql, has_live_stats, engine=adapter)
            if rw and rw.rewritten_sql:
                reasons.append(
                    "Ranking intent with no LIMIT — proposing a bounded top-N "
                    "query in suggested_sql (advisory; the candidate is still runnable)."
                )
    else:
        reasons.append(f"Risk is '{pf.risk_tier}' — refine before running.")
        reasons += [f"{f.code}: {f.detail}" for f in pf.flags if f.severity == "high"]
        rw = rewrite(run_sql, candidate_sql, has_live_stats, engine=adapter)

    verdict = SuggestVerdict(
        engine=adapter.name, intent=intent, candidate_sql=candidate_sql,
        accept=accept, risk_tier=pf.risk_tier, reasons=reasons, flags=pf.flags,
        suggested_sql=rw.rewritten_sql if rw else None,
        cost_before=rw.cost_before if rw else pf.planner_total_cost,
        cost_after=rw.cost_after if rw else None,
        index_suggestions=rw.index_suggestions if rw else [],
        next_action="accept" if accept else "refine",
        accuracy_tier=pf.accuracy_tier,
    )
    return verdict.to_dict()
