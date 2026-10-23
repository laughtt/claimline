"""Reconcile the two drivers' fact sets (spec §3 step 4 and §9).

Plain code on purpose: the LLM never decides the status of a fact. The only
judgement it may make is whether two free-text values mean the same thing,
passed in as ``same_meaning``.
"""

import re
from dataclasses import dataclass, field
from typing import Callable

AGREED = "AGREED"
ONLY_A = "ONLY_A"
ONLY_B = "ONLY_B"
CONFLICT = "CONFLICT"

# Numeric fields: values within this tolerance count as the same.
# A field may carry its subject after "@" ("speed_kmh@A"); the tolerance
# applies to the base name.
NUMERIC_TOLERANCE = {"speed_kmh": 10}
# "19:40" and "around 7:45 pm" are the same moment for a crash report
TIME_TOLERANCE_MIN = 10
TIME_RE = re.compile(r"(\d{1,2})[:.h](\d{2})\s*([ap])?\.?\s*m?\b", re.IGNORECASE)

# Derived row: at a crossing both drivers can't have had a green light
SIGNAL_CROSS = "signal_state@crossing"


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
    base = field_name.split("@")[0]
    if base == "time":
        ma, mb = _minutes(a), _minutes(b)
        return ma is not None and mb is not None and abs(ma - mb) <= TIME_TOLERANCE_MIN
    tolerance = NUMERIC_TOLERANCE.get(base)
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
        elif same_meaning and not _is_measured(name) and same_meaning(name, a.value, b.value):
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

    # Each driver usually only states their own light, so the two greens
    # land in different fields and would never meet above
    own_a, own_b = best_a.get("signal_state@A"), best_b.get("signal_state@B")
    if own_a and own_b and _normalize(own_a.value) == _normalize(own_b.value) == "green":
        result.append(ReconciledFact(
            field=SIGNAL_CROSS,
            status=CONFLICT,
            value_a=f"A's light {own_a.value}",
            value_b=f"B's light {own_b.value}",
            evidence_a=own_a.evidence,
            evidence_b=own_b.evidence,
        ))
    return result


def _is_measured(field_name: str) -> bool:
    """Numbers and times have tolerances; a meaning judge must not override them."""
    base = field_name.split("@")[0]
    return base == "time" or base in NUMERIC_TOLERANCE


def _minutes(value: str) -> int | None:
    match = TIME_RE.search(str(value))
    if not match:
        return None
    hours, minutes, half = int(match.group(1)), int(match.group(2)), (match.group(3) or "").lower()
    if half == "p" and hours < 12:
        hours += 12
    elif half == "a" and hours == 12:
        hours = 0
    return hours * 60 + minutes


def _best_per_field(facts: list[Fact]) -> dict[str, Fact]:
    best: dict[str, Fact] = {}
    for f in facts:
        if f.field not in best or f.confidence > best[f.field].confidence:
            best[f.field] = f
    return best
