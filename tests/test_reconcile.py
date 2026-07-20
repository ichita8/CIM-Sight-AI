"""Tests for reconcile.deduplicate_flags.

Uses flag/finding shapes taken from a real analysis run of the sample CIM.
"""
from reconcile import deduplicate_flags, _percentages


def _rule_findings():
    return [
        {
            "category": "MATH ERRORS",
            "severity": "HIGH",
            "detail": (
                "Stated gross margin is 55.0%, but gross (20,000,000) / "
                "revenue (50,000,000) = 40.00%. Discrepancy of 15.00 pts."
            ),
        },
        {
            "category": "MATH ERRORS",
            "severity": "HIGH",
            "detail": (
                "Stated growth of 100.0% from 30,000,000 to 50,000,000, "
                "but actual growth = 66.7%."
            ),
        },
    ]


def _red_flags():
    return [
        {
            "category": "MATH ERRORS",
            "severity": "HIGH",
            "quote": "Gross Profit: $20,000,000. Gross margin of 55%.",
            "explanation": "$20M / $50M = 40% gross margin, not 55%; a 15-point discrepancy.",
        },
        {
            "category": "MATH ERRORS",
            "severity": "HIGH",
            "quote": "grew from $30,000,000 to $50,000,000, representing growth of 100%.",
            "explanation": "Growth is actually 66.7%, not 100%.",
        },
        {
            "category": "AGGRESSIVE PROJECTIONS",
            "severity": "HIGH",
            "quote": "reach $200,000,000 within three years, roughly 300%.",
            "explanation": "CAGR is ~58.7%, not 300%.",
        },
        {
            "category": "CUSTOMER CONCENTRATION RISK",
            "severity": "HIGH",
            "quote": "Customer A accounts for 72% of total revenue.",
            "explanation": "Over-reliance on a single customer.",
        },
        {
            "category": "MARGIN INCONSISTENCIES",
            "severity": "HIGH",
            "quote": "Gross margin was 40% in FY2021, 48% in FY2022, and 55% in FY2023.",
            "explanation": "Rapid margin expansion from 40% to 55% is unexplained.",
        },
    ]


def test_math_duplicates_are_suppressed():
    kept, findings = deduplicate_flags(_red_flags(), _rule_findings())
    categories = [f["category"] for f in kept]
    # The two MATH ERRORS cards that restate the arithmetic engine are gone.
    assert "MATH ERRORS" not in categories
    assert len(kept) == 3


def test_matched_findings_are_marked_corroborated():
    _, findings = deduplicate_flags(_red_flags(), _rule_findings())
    assert all(f.get("ai_corroborated") for f in findings)


def test_interpretive_flags_are_kept_even_if_numbers_overlap():
    """MARGIN INCONSISTENCIES shares 40% and 55% with the margin finding but is
    a distinct point, so it must NOT be suppressed."""
    kept, _ = deduplicate_flags(_red_flags(), _rule_findings())
    categories = [f["category"] for f in kept]
    assert "MARGIN INCONSISTENCIES" in categories
    assert "AGGRESSIVE PROJECTIONS" in categories
    assert "CUSTOMER CONCENTRATION RISK" in categories


def test_single_shared_percentage_is_not_enough():
    findings = [{"category": "MATH ERRORS", "detail": "margin 55.0% vs 40.00%"}]
    flags = [{
        "category": "MATH ERRORS",
        "quote": "something about 55% only",
        "explanation": "no other shared number here",
    }]
    kept, _ = deduplicate_flags(flags, findings)
    assert len(kept) == 1  # only one shared pct (55) → kept


def test_no_rule_findings_keeps_all_flags():
    flags = _red_flags()
    kept, findings = deduplicate_flags(flags, [])
    assert len(kept) == len(flags)
    assert findings == []


def test_percentages_helper_rounds():
    assert _percentages("40.00% and 66.70%") == {40.0, 66.7}
    assert _percentages("") == set()
