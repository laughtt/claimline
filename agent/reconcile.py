"""Reconcile the two drivers' fact sets (spec §3 step 4 and §9).

Plain code on purpose: the LLM never decides the status of a fact. The only
judgement it may make is whether two free-text values mean the same thing,
passed in as ``same_meaning``.
"""

from dataclasses import dataclass, field
from typing import Callable

AGREED = "AGREED"
ONLY_A = "ONLY_A"
ONLY_B = "ONLY_B"
CONFLICT = "CONFLICT"

# Numeric fields: values within this tolerance count as the same
NUMERIC_TOLERANCE = {"speed_kmh": 10}


@dataclass
class Fact:
    field: str
    value: str
    party: str
    confidence: float = 1.0
    evidence: list = field(default_factory=list)
    language: str = "es"


@dataclass
class ReconciledFact:
    field: str
    status: str
    value_a: str | None
    value_b: str | None
    evidence_a: list
    evidence_b: list


def _normalize(value: str) -> str:
    return " ".join(str(value).lower().split())


def _exact_or_numeric_match(field_name: str, a: str, b: str) -> bool:
    if _normalize(a) == _normalize(b):
        return True
    tolerance = NUMERIC_TOLERANCE.get(field_name)
    if tolerance is not None:
        try:
            return abs(float(a) - float(b)) <= tolerance
        except ValueError:
            return False
    return False


def reconcile(
    facts_a: list[Fact],
    facts_b: list[Fact],
    same_meaning: Callable[[str, str, str], bool] | None = None,
) -> list[ReconciledFact]:
    """Compare field by field. If a driver gave a field twice, the most confident value wins."""
    best_a = _best_per_field(facts_a)
    best_b = _best_per_field(facts_b)

    result = []
    for name in sorted(set(best_a) | set(best_b)):
        a, b = best_a.get(name), best_b.get(name)
        if a and not b:
            status = ONLY_A
        elif b and not a:
            status = ONLY_B
        elif _exact_or_numeric_match(name, a.value, b.value):
            status = AGREED
        elif same_meaning and same_meaning(name, a.value, b.value):
            status = AGREED
        else:
            status = CONFLICT
        result.append(ReconciledFact(
            field=name,
            status=status,
            value_a=a.value if a else None,
            value_b=b.value if b else None,
            evidence_a=a.evidence if a else [],
            evidence_b=b.evidence if b else [],
        ))
    return result


def _best_per_field(facts: list[Fact]) -> dict[str, Fact]:
    best: dict[str, Fact] = {}
    for f in facts:
        if f.field not in best or f.confidence > best[f.field].confidence:
            best[f.field] = f
    return best
