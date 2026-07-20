"""Reconcile the deterministic arithmetic findings with the LLM's red flags.

The arithmetic engine and the LLM can surface the *same* issue (e.g. a stated
margin that doesn't match the math). Rendering both produces duplicate — and
occasionally contradictory — cards. This module drops the LLM flag that merely
restates a verified arithmetic finding and marks that finding as AI-corroborated,
so the deterministic ("verified") result is the single source of truth.
"""
import re

_PCT_RE = re.compile(r"([0-9]{1,4}(?:\.[0-9]+)?)\s*%")

# Only the LLM's own math category is deduped against the arithmetic engine.
# Interpretive categories (e.g. MARGIN INCONSISTENCIES, AGGRESSIVE PROJECTIONS)
# may share numbers yet make a genuinely different point, so they are kept.
_MATH_CATEGORY = "MATH ERRORS"

# How many percentage values an LLM flag must share with a finding to be a dup.
_MIN_SHARED_PCTS = 2


def _percentages(text: str) -> set:
    """Percentage values in the text, rounded to one decimal for comparison."""
    return {round(float(x), 1) for x in _PCT_RE.findall(text or "")}


def _flag_text(flag: dict) -> str:
    return f"{flag.get('quote', '')} {flag.get('explanation', '')}"


def deduplicate_flags(red_flags: list, rule_findings: list) -> tuple:
    """Suppress LLM flags already covered by the arithmetic engine.

    An LLM flag is a duplicate when it is a MATH ERRORS flag that shares at
    least ``_MIN_SHARED_PCTS`` percentage values with a deterministic finding.
    Matched findings get ``ai_corroborated = True`` (mutated in place).

    Returns ``(kept_flags, rule_findings)``.
    """
    finding_pcts = [(_percentages(f.get("detail", "")), f) for f in rule_findings]
    kept = []
    for flag in red_flags:
        category = (flag.get("category") or "").strip().upper()
        is_duplicate = False
        if category == _MATH_CATEGORY:
            flag_pcts = _percentages(_flag_text(flag))
            for finding_pct, finding in finding_pcts:
                if len(flag_pcts & finding_pct) >= _MIN_SHARED_PCTS:
                    finding["ai_corroborated"] = True
                    is_duplicate = True
                    break
        if not is_duplicate:
            kept.append(flag)
    return kept, rule_findings
