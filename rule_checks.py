"""
Deterministic, rule-based arithmetic checks for CIM-Sight AI.
Runs BEFORE the LLM. No AI involved — pure Python verification.
This is what makes CIM-Sight a true hybrid (rules + LLM) engine.
"""
import re

# How far off a stated value can be before we flag it.
MARGIN_TOLERANCE_PCT = 0.5   # percentage points
GROWTH_TOLERANCE_PCT = 1.0   # percentage points


def _to_number(raw: str) -> float:
    """Convert '$1,234.5M' / '1.2B' / '45%' style strings into a float."""
    s = raw.strip().replace(",", "").replace("$", "").replace("%", "")
    mult = 1.0
    if s and s[-1] in "kKmMbB":
        unit = s[-1].lower()
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[unit]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def check_margin_consistency(text: str) -> list:
    """
    Find 'X margin of Y%' style claims where revenue + the metric are both
    present, and verify the stated percentage matches the actual division.
    """
    findings = []
    pattern = re.compile(
        r"(gross|ebitda|net|operating)\s+margin[^0-9]{0,20}([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
        re.IGNORECASE,
    )
    rev_match = re.search(
        r"(?:total\s+)?revenue[^0-9$]{0,15}\$?\s*([0-9][0-9,\.]*\s*[kKmMbB]?)",
        text, re.IGNORECASE,
    )
    revenue = _to_number(rev_match.group(1)) if rev_match else None

    for m in pattern.finditer(text):
        metric_name = m.group(1).lower()
        stated_pct = float(m.group(2))
        amt_pattern = re.compile(
            rf"{metric_name}[^0-9$]{{0,20}}\$?\s*([0-9][0-9,\.]*\s*[kKmMbB]?)",
            re.IGNORECASE,
        )
        amt_match = amt_pattern.search(text)
        amount = _to_number(amt_match.group(1)) if amt_match else None

        if revenue and amount and revenue > 0:
            computed = (amount / revenue) * 100
            diff = abs(computed - stated_pct)
            if diff > MARGIN_TOLERANCE_PCT:
                findings.append({
                    "category": "MATH ERRORS",
                    "severity": "HIGH",
                    "detail": (
                        f"Stated {metric_name} margin is {stated_pct:.1f}%, but "
                        f"{metric_name} ({amount:,.0f}) / revenue ({revenue:,.0f}) "
                        f"= {computed:.2f}%. Discrepancy of {diff:.2f} pts."
                    ),
                })
    return findings


def check_percentage_sums(text: str) -> list:
    """Flag any 'breakdown' list of percentages that sums to far from 100%."""
    findings = []
    for block in re.split(r"\n\s*\n", text):
        pcts = [float(x) for x in re.findall(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%", block)]
        if 3 <= len(pcts) <= 8:
            total = sum(pcts)
            if 90 < total < 110 and abs(total - 100) > 1.5:
                findings.append({
                    "category": "MATH ERRORS",
                    "severity": "MEDIUM",
                    "detail": (
                        f"A percentage breakdown sums to {total:.1f}% "
                        f"(should be ~100%): {pcts}"
                    ),
                })
    return findings


def check_growth_claims(text: str) -> list:
    """Verify 'grew from $A to $B (X%)' style claims."""
    findings = []
    pattern = re.compile(
        r"from\s+\$?\s*([0-9][0-9,\.]*\s*[kKmMbB]?)\s+to\s+\$?\s*"
        r"([0-9][0-9,\.]*\s*[kKmMbB]?)[^0-9%]{0,30}?([0-9]{1,4}(?:\.[0-9]+)?)\s*%",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        a = _to_number(m.group(1))
        b = _to_number(m.group(2))
        stated = float(m.group(3))
        if a and b and a > 0:
            computed = ((b - a) / a) * 100
            if abs(computed - stated) > GROWTH_TOLERANCE_PCT:
                findings.append({
                    "category": "MATH ERRORS",
                    "severity": "HIGH",
                    "detail": (
                        f"Stated growth of {stated:.1f}% from {a:,.0f} to {b:,.0f}, "
                        f"but actual growth = {computed:.1f}%."
                    ),
                })
    return findings


def run_rule_based_checks(text: str) -> dict:
    """Run all deterministic checks and return findings + a text summary."""
    findings = []
    findings += check_margin_consistency(text)
    findings += check_percentage_sums(text)
    findings += check_growth_claims(text)

    if findings:
        summary_lines = [
            f"- [{f['severity']}] {f['category']}: {f['detail']}" for f in findings
        ]
        summary = "\n".join(summary_lines)
    else:
        summary = ""

    return {"findings": findings, "summary": summary}
