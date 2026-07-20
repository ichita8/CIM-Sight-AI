"""Tests for the deterministic arithmetic engine (rule_checks.py).

These prove the "verified, no AI" box does what its label claims — including a
regression test for the false positive where a bare percentage (e.g. "45" in
"gross margin of 45%") was matched as if it were a dollar amount.
"""
from rule_checks import (
    _to_number,
    check_margin_consistency,
    check_growth_claims,
    check_percentage_sums,
    run_rule_based_checks,
)


def _details(findings):
    return " ".join(f["detail"] for f in findings)


# ── _to_number ────────────────────────────────────────────────────────────
def test_to_number_handles_units_and_symbols():
    assert _to_number("$1,234") == 1234.0
    assert _to_number("1.2B") == 1.2e9
    assert _to_number("50M") == 50e6
    assert _to_number("45%") == 45.0
    assert _to_number("not a number") is None


# ── check_margin_consistency ──────────────────────────────────────────────
def test_plain_margin_statement_is_not_flagged():
    """Regression: a normal 'margin of X%' sentence must NOT be flagged just
    because a bare percent number exists near the keyword."""
    text = "Total revenue was $50,000,000. Gross margin of 45% is healthy."
    assert check_margin_consistency(text) == []


def test_real_margin_mismatch_is_flagged():
    text = (
        "Total revenue: $50,000,000. Gross Profit: $20,000,000. "
        "Gross margin of 55%."
    )
    findings = check_margin_consistency(text)
    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"
    assert "40.00%" in findings[0]["detail"]


def test_consistent_margin_is_not_flagged():
    text = (
        "Total revenue: $50,000,000. Gross Profit: $20,000,000. "
        "Gross margin of 40%."
    )
    assert check_margin_consistency(text) == []


def test_margin_without_dollar_amount_is_not_flagged():
    """Only a percentage and revenue present, no dollar metric → no false flag."""
    text = "Total revenue of $50,000,000. Net margin of 12%."
    assert check_margin_consistency(text) == []


# ── check_growth_claims ───────────────────────────────────────────────────
def test_growth_mismatch_is_flagged():
    text = "Revenue grew from $30,000,000 to $50,000,000, representing growth of 100%."
    findings = check_growth_claims(text)
    assert len(findings) == 1
    assert "66.7%" in findings[0]["detail"]


def test_correct_growth_is_not_flagged():
    text = "Revenue grew from $30,000,000 to $60,000,000, a 100% increase."
    assert check_growth_claims(text) == []


# ── check_percentage_sums ─────────────────────────────────────────────────
def test_percentage_breakdown_that_misses_100_is_flagged():
    text = "Revenue mix: North America 30%, Europe 30%, Asia 37%."
    findings = check_percentage_sums(text)
    assert len(findings) == 1
    assert "97" in findings[0]["detail"]


def test_percentage_breakdown_summing_to_100_is_not_flagged():
    text = "Revenue mix: North America 30%, Europe 30%, Asia 40%."
    assert check_percentage_sums(text) == []


# ── run_rule_based_checks (integration) ───────────────────────────────────
def test_run_rule_based_checks_summary_matches_findings():
    text = "Revenue grew from $30,000,000 to $50,000,000, representing growth of 100%."
    result = run_rule_based_checks(text)
    assert result["findings"]
    assert "66.7%" in result["summary"]


def test_run_rule_based_checks_clean_document_has_no_findings():
    text = "The company operates three facilities and employs 200 people."
    result = run_rule_based_checks(text)
    assert result["findings"] == []
    assert result["summary"] == ""
