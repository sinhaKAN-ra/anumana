"""Anumana policy layer — Phase 4 of generative mode.

Preflight/suggest TELL the agent about cost. A policy layer lets an OPERATOR set
standing rules that are ENFORCED across targets — the enterprise / CI-gate story:

    "block any 'dangerous' query on prod_pg"
    "warn on any Dynamo full-scan"
    "every agent query on any target must pass preflight first"  (observed via audit)

A policy is pure data (operator config), evaluated DETERMINISTICALLY against a
preflight result. Anumana does not decide policy — the operator does; Anumana
only reports verdicts. The agent still runs the query itself, so a 'block' is an
INSTRUCTION to the agent ("do not run this"), not an interception — Anumana never
sits in the data path. That honesty matters: we gate by advising, and the audit
trail records what was advised.

Config source: ANUMANA_POLICIES, a JSON array. Example:

    ANUMANA_POLICIES='[
      {"name":"no-dangerous-on-prod","scope":{"target":"prod_pg"},
       "when":{"risk_at_least":"dangerous"},"action":"block"},
      {"name":"warn-full-scan","scope":{"engine":"dynamodb"},
       "when":{"flag":"DYNAMO_FULL_SCAN"},"action":"warn"}
    ]'

Scope matches by target name, engine, or all (empty scope = all). `when` matches
a minimum risk tier and/or a specific flag code. Action is block | warn | allow.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

_RISK_ORDER = {"cheap": 0, "moderate": 1, "expensive": 2, "dangerous": 3}
_ACTIONS = ("block", "warn", "allow")


@dataclass
class Policy:
    name: str
    scope: dict = field(default_factory=dict)     # {target?, engine?}  empty = all
    when: dict = field(default_factory=dict)      # {risk_at_least?, flag?}
    action: str = "warn"                          # block | warn | allow

    def matches_scope(self, target: str | None, engine: str) -> bool:
        if "target" in self.scope and self.scope["target"] != target:
            return False
        if "engine" in self.scope and self.scope["engine"] != engine:
            return False
        return True

    def matches_condition(self, risk: str, flag_codes: set[str]) -> bool:
        ok = True
        if "risk_at_least" in self.when:
            threshold = _RISK_ORDER.get(self.when["risk_at_least"], 99)
            ok = ok and _RISK_ORDER.get(risk, 0) >= threshold
        if "flag" in self.when:
            ok = ok and self.when["flag"] in flag_codes
        # a `when` with neither key matches everything in scope (a blanket rule)
        return ok


@dataclass
class PolicyVerdict:
    """The result of evaluating all policies against one preflight."""
    decision: str                      # "block" | "warn" | "allow"
    matched: list[dict] = field(default_factory=list)   # which policies fired
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PolicySet:
    def __init__(self, policies: list[Policy] | None = None) -> None:
        self.policies = policies or []

    @classmethod
    def from_env(cls) -> "PolicySet":
        raw = os.environ.get("ANUMANA_POLICIES")
        if not raw:
            return cls([])
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"ANUMANA_POLICIES is not valid JSON: {e}") from e
        pols = []
        for e in entries:
            action = (e.get("action") or "warn").lower()
            if action not in _ACTIONS:
                raise ValueError(f"policy {e.get('name')!r}: action must be one of {_ACTIONS}")
            pols.append(Policy(name=e.get("name", "unnamed"),
                               scope=e.get("scope", {}), when=e.get("when", {}),
                               action=action))
        return cls(pols)

    def evaluate(self, *, target: str | None, engine: str, risk: str,
                 flag_codes: set[str]) -> PolicyVerdict:
        """Evaluate every policy; the STRICTEST matching action wins
        (block > warn > allow). No policies configured => allow (open by default;
        the operator opts INTO enforcement)."""
        fired: list[Policy] = [
            p for p in self.policies
            if p.matches_scope(target, engine) and p.matches_condition(risk, flag_codes)
        ]
        if not fired:
            return PolicyVerdict(decision="allow", matched=[],
                                 message="No policy matched — allowed.")
        strictness = {"allow": 0, "warn": 1, "block": 2}
        decision = max((p.action for p in fired), key=lambda a: strictness[a])
        matched = [{"name": p.name, "action": p.action,
                    "scope": p.scope, "when": p.when} for p in fired]
        if decision == "block":
            msg = ("BLOCKED by operator policy — do NOT run this query. "
                   f"Fired: {[p.name for p in fired if p.action=='block']}. "
                   "Refine it until it passes, or ask the operator to amend the policy.")
        elif decision == "warn":
            msg = ("WARNING from operator policy — you may run it, but it violates a "
                   f"standing rule. Fired: {[p.name for p in fired if p.action=='warn']}.")
        else:
            msg = "Allowed."
        return PolicyVerdict(decision=decision, matched=matched, message=msg)


# module-level singleton (reload-able for tests)
_POLICIES: PolicySet | None = None


def policies() -> PolicySet:
    global _POLICIES
    if _POLICIES is None:
        _POLICIES = PolicySet.from_env()
    return _POLICIES


def reset_policies() -> None:
    global _POLICIES
    _POLICIES = None
