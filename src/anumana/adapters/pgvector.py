"""pgvector adapter — vector-search cost diagnosis for RAG.

Why this exists: the single most common thing AI agents do today is retrieval-
augmented generation. Every "chat with your docs" fires vector similarity
searches, and those have their OWN cost traps an agent cannot foresee:

  - no vector index at all  -> brute-force full-collection distance scan
  - a metadata filter with no supporting index -> pre-filter scans everything
  - top_k far larger than needed -> over-fetch + wasted distance math
  - ef_search / probes left at a value that silently degrades recall or cost

pgvector runs INSIDE Postgres, so a similarity query still produces an EXPLAIN
plan tree. We inherit the Postgres adapter's plumbing and ADD vector-aware
flags on top — the generic SQL detector cannot see these.

Honesty rail: pgvector's planner does NOT estimate recall. We report the cost
signal it does give (index vs full scan, rows touched) and flag the recall-vs-
cost knobs as things to verify — we never invent a recall number.
"""
from __future__ import annotations

import re

from anumana.adapters.base import Adapter, EngineFlag, PlanResult
from anumana.adapters.postgres import PostgresAdapter

# vector distance operators pgvector exposes: <-> L2, <#> inner product, <=> cosine
_VECTOR_OP = re.compile(r"<(?:->|#>|=>)|<=>|<#>|<->", re.I)
_ORDER_BY_DISTANCE = re.compile(r"order\s+by\s+.*(<->|<#>|<=>)", re.I | re.S)
_LIMIT = re.compile(r"\blimit\s+(\d+)", re.I)
_HAS_WHERE = re.compile(r"\bwhere\b", re.I)

# pgvector index scan node names surface the access method in the plan text
_VECTOR_INDEX_NODES = ("Index Scan", "Index Only Scan")
_HNSW_IVF = re.compile(r"(hnsw|ivfflat)", re.I)

# a top_k above this is almost never what a RAG prompt actually needs
_TOP_K_SANE_MAX = 50


class PgVectorAdapter(PostgresAdapter):
    name = "pgvector"
    label = "pgvector (RAG / vector search)"
    verified_live = False  # inherits Postgres but pgvector path not live-tested (no pgvector DB)

    def is_vector_query(self, query: str) -> bool:
        return bool(_VECTOR_OP.search(query) or _ORDER_BY_DISTANCE.search(query))

    def detect_flags(self, query: str, plan: PlanResult) -> list[EngineFlag]:
        # start from the generic SQL flags (SELECT *, no LIMIT still apply)
        flags = super().detect_flags(query, plan)

        if not self.is_vector_query(query):
            # not a similarity search — nothing vector-specific to add
            return flags

        plan_text = _plan_text(plan.raw)
        uses_vector_index = bool(_HNSW_IVF.search(plan_text)) or any(
            n.get("Node Type") in _VECTOR_INDEX_NODES and _HNSW_IVF.search(str(n))
            for n in plan.nodes
        )
        has_seq_scan = any(n.get("Node Type") == "Seq Scan" for n in plan.nodes)

        # 1) brute-force full scan — no HNSW/IVFFlat index on the vector column
        if _ORDER_BY_DISTANCE.search(query) and (has_seq_scan or not uses_vector_index):
            flags.append(EngineFlag(
                "FULL_VECTOR_SCAN",
                "Similarity search without a vector index (HNSW / IVFFlat): "
                "every row's distance is computed brute-force. Build an HNSW index "
                "on the embedding column so the search is approximate-nearest-neighbour.",
                "high",
            ))

        # 2) top_k far larger than a RAG prompt can use
        m = _LIMIT.search(query)
        if m:
            k = int(m.group(1))
            if k > _TOP_K_SANE_MAX:
                flags.append(EngineFlag(
                    "TOP_K_TOO_LARGE",
                    f"top_k = {k}: a RAG prompt rarely needs more than "
                    f"~{_TOP_K_SANE_MAX} neighbours. Each extra candidate costs "
                    f"distance math and context tokens downstream. Lower the LIMIT.",
                    "medium",
                ))
        else:
            # a similarity search with NO limit is a classic agent mistake
            flags.append(EngineFlag(
                "UNBOUNDED_VECTOR_SEARCH",
                "Similarity search with no LIMIT returns the whole collection ranked "
                "by distance — almost never intended. Add LIMIT k (the number of "
                "neighbours your prompt actually uses).",
                "high",
            ))

        # 3) metadata pre-filter that may not be index-backed
        if _HAS_WHERE.search(query) and uses_vector_index:
            flags.append(EngineFlag(
                "VECTOR_FILTER_INTERACTION",
                "A metadata filter (WHERE) is combined with a vector index. pgvector "
                "applies the filter AFTER the ANN search by default, so a selective "
                "filter can starve results below your top_k (recall drops). Verify the "
                "filter column is indexed and consider iterative/pre-filtered search.",
                "medium",
            ))

        return flags

    def node_reason(self, node: dict) -> str:
        ntype = node.get("Node Type", "")
        if ntype in _VECTOR_INDEX_NODES and _HNSW_IVF.search(str(node)):
            return ("walks the vector index (HNSW/IVFFlat) for approximate nearest "
                    "neighbours — the fast path for similarity search")
        if ntype == "Seq Scan":
            return ("computes the distance for EVERY row (brute-force) because no "
                    "vector index is used — slow as the collection grows")
        return super().node_reason(node)

    def headline(self, plan: PlanResult) -> str:
        plan_text = _plan_text(plan.raw)
        if _HNSW_IVF.search(plan_text):
            return ("Good — the search uses a vector index (HNSW/IVFFlat) for "
                    "approximate nearest neighbours, so it does not score every embedding.")
        if any(n.get("Node Type") == "Seq Scan" for n in plan.nodes):
            return ("This similarity search scores EVERY embedding in the collection "
                    "(brute force), because no HNSW/IVFFlat index is used. It gets "
                    "linearly slower as you add documents — build a vector index.")
        return super().headline(plan)


def _plan_text(raw) -> str:
    """Extract only the index-identifying fields to grep for the access method
    (hnsw/ivfflat), instead of str()-ing the whole plan doc on every call. The
    method name lives in Index Name / Index Cond, so we collect just those from
    the plan tree — a few short strings, not the entire JSON."""
    bits: list[str] = []

    def _collect(node):
        if not isinstance(node, dict):
            return
        for k in ("Index Name", "Index Cond", "Node Type"):
            v = node.get(k)
            if v:
                bits.append(str(v))
        for child in node.get("Plans", []):
            _collect(child)

    _collect(raw)
    return " ".join(bits)


assert isinstance(PgVectorAdapter(), Adapter)
