"""Keyword-rule category matching. Pure stdlib.

Rules are the first line of classification: deterministic, explainable, and they
bootstrap labels for the ML model. The same rule set is loaded from the database
at runtime and used offline (as ``SEED_RULES``) when no DB is available.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    pattern: str
    category: str
    priority: int = 100  # lower wins


def compile_rules(rules: Iterable[Rule]) -> list[tuple[re.Pattern[str], Rule]]:
    """Compile and order rules so the highest-priority (lowest number) matches first."""
    ordered = sorted(rules, key=lambda r: (r.priority, r.category))
    return [(re.compile(r.pattern), r) for r in ordered]


def match_rule(text: str, compiled: list[tuple[re.Pattern[str], Rule]]) -> str | None:
    """Return the category of the first matching rule, or ``None``."""
    if not text:
        return None
    for regex, rule in compiled:
        if regex.search(text):
            return rule.category
    return None
