"""
Deterministic, rule-based arithmetic checks for CIM-Sight AI.
Runs BEFORE the LLM. No AI involved — pure Python verification.
This is what makes CIM-Sight a true hybrid (rules + LLM) engine.
"""
from __future__ import annotations
import re
from typing import Any, Optional

MARGIN_TOLERANCE_PCT = 0.5
GROWTH_TOLERANCE_PCT = 1.0
CAP_TABLE_TOLERANCE_PCT = 1.5

PERCENTAGE_BREAKDOWN_CUES = re.compile(
    r"\b(breakdown|mix|allocation|composition|split|distribution|concentration|cap\s*table|ownership)\b",
    re.IGNORECASE,
)

# Fixed: \b around $ never matched because $ is a non-word character.
# Now uses two alternation groups: group(1) for named currencies,
# group(2) for symbols ($, €, £).
CURRENCY_PATTERN = re.compile(
    r"\b(USD|EUR|GBP|CAD)\b|(\$|€|£)",
    re.IGNORECASE,
)


def _finding(
    category: str,
    severity: str,
    detail: str,
    *,
    char_offset: int | None = None,
    raw_values: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "detail": detail,
        "char_offset": char_offset,
        "raw_values": raw_values or [],
        "page_number": None,
        "table_id": None,
        "paragraph_id": None,
        "ocr_confidence": None,
    }


def _to_number(raw: str) -> Optional[float]:
    if not raw:
        return None
    value = raw.strip().replace(",", "").replace("$", "").replace("%", "")
    value = re.sub(r"\s+", "", value)
    multiplier = 1.0
    if value and value[-1].lower() in {"k", "m", "b"}:
        unit = value[-1].lower()
        multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}[unit]
        value = value[:-1]
    try:
        return float(value) * multiplier
    except ValueError:
        return None


def _find_financial_amounts(text: str, label: str) -> list[tuple[int, float, str]]:
    pattern = re.compile(
        rf"\b{re.escape(label)}\b(?!\s+margin\b)[^0-9$]{{0,45}}"
        r"(?P<amount>\$?\s*[0-9][0-9,.]*(?:\s*[kKmMbB])?)(?P<pct>\s*%)?",
        re.IGNORECASE,
    )
    amounts: list[tuple[int, float, str]] = []
    for match in pattern.finditer(text):
        if match.group("pct"):
            continue
        raw = match.group("amount")
        if "$" not in raw and not re.search(r"[kKmMbB]\s*$", raw):
            continue
        number = _to_number(raw)
        if number is not None:
            amounts.append((match.start(), number, raw.strip()))
    return amounts


def check_margin_consistency(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    revenue_amounts = _find_financial_amounts(text, "revenue")
    margin_pattern = re.compile(
        r"\b(gross|ebitda|net|operating)\s+margin[^0-9]{0,25}"
        r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
        re.IGNORECASE,
    )
    for margin_match in margin_pattern.finditer(text):
        metric = margin_match.group(1).lower()
        stated_pct = float(margin_match.group(2))
        metric_amounts = _find_financial_amounts(text, metric)
        if not revenue_amounts or not metric_amounts:
            continue
        _, revenue, revenue_raw = min(
            revenue_amounts, key=lambda item: abs(item[0] - margin_match.start())
        )
        _, amount, amount_raw = min(
            metric_amounts, key=lambda item: abs(item[0] - margin_match.start())
        )
        if revenue <= 0:
            continue
        computed = amount / revenue * 100
        difference = abs(computed - stated_pct)
        if difference > MARGIN_TOLERANCE_PCT:
            findings.append(
                _finding(
                    "MATH ERRORS",
                    "HIGH",
                    (
                        f"Stated {metric} margin is {stated_pct:.1f}%, but "
                        f"{metric} ({amount:,.0f}) / revenue ({revenue:,.0f}) = "
                        f"{computed:.2f}%. Discrepancy of {difference:.2f} points."
                    ),
                    char_offset=margin_match.start(),
                    raw_values=[f"{stated_pct}%", revenue_raw, amount_raw],
                )
            )
    return findings


def check_percentage_sums(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text):
        cue_match = PERCENTAGE_BREAKDOWN_CUES.search(block)
        if not cue_match:
            continue
        percentages = [
            float(value)
            for value in re.findall(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%", block)
        ]
        if 3 <= len(percentages) <= 12:
            total = sum(percentages)
            if 90 < total < 110 and abs(total - 100) > 1.5:
                findings.append(
                    _finding(
                        "MATH ERRORS",
                        "MEDIUM",
                        (
                            f"A labelled percentage breakdown sums to {total:.1f}% "
                            f"(expected approximately 100%): {percentages}"
                        ),
                        char_offset=cue_match.start(),
                        raw_values=[f"{p}%" for p in percentages],
                    )
                )
    return findings


def check_growth_claims(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    pattern = re.compile(
        r"from\s+\$?\s*([0-9][0-9,.]*\s*[kKmMbB]?)\s+to\s+\$?\s*"
        r"([0-9][0-9,.]*\s*[kKmMbB]?)[^0-9%]{0,30}?"
        r"([0-9]{1,4}(?:\.[0-9]+)?)\s*%",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        start, end, stated = (
            _to_number(match.group(1)),
            _to_number(match.group(2)),
            float(match.group(3)),
        )
        if start is None or end is None or start <= 0:
            continue
        computed = (end - start) / start * 100
        if abs(computed - stated) > GROWTH_TOLERANCE_PCT:
            findings.append(
                _finding(
                    "MATH ERRORS",
                    "HIGH",
                    (
                        f"Stated growth of {stated:.1f}% from {start:,.0f} to "
                        f"{end:,.0f}, but actual growth is {computed:.1f}%."
                    ),
                    char_offset=match.start(),
                    raw_values=[match.group(1), match.group(2), f"{stated}%"],
                )
            )
    return findings


def check_cap_table_math(text: str) -> list[dict[str, Any]]:
    """Flag ownership blocks that do not sum to ~100%."""
    findings: list[dict[str, Any]] = []
    cap_table_cue = re.compile(
        r"\b(cap\s*table|ownership|shareholder|fully\s+diluted)\b",
        re.IGNORECASE,
    )
    for block in re.split(r"\n\s*\n", text):
        if not cap_table_cue.search(block):
            continue
        percentages = [
            float(value)
            for value in re.findall(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%", block)
        ]
        if 2 <= len(percentages) <= 15:
            total = sum(percentages)
            if 95 < total < 105 and abs(total - 100) > CAP_TABLE_TOLERANCE_PCT:
                cue = cap_table_cue.search(block)
                findings.append(
                    _finding(
                        "MATH ERRORS",
                        "HIGH",
                        (
                            f"Cap table / ownership percentages sum to {total:.1f}% "
                            f"(expected ~100%): {percentages}"
                        ),
                        char_offset=cue.start() if cue else None,
                        raw_values=[f"{p}%" for p in percentages],
                    )
                )
    return findings


def check_currency_consistency(text: str) -> list[dict[str, Any]]:
    """Warn when multiple currencies appear without an explicit FX note."""
    # Fixed: handles both group(1) named currencies and group(2) symbols
    currencies = {
        (match.group(1) or match.group(2))
        .upper()
        .replace("€", "EUR")
        .replace("£", "GBP")
        .replace("$", "USD")
        for match in CURRENCY_PATTERN.finditer(text)
    }
    normalized = {c for c in currencies if c in {"USD", "EUR", "GBP", "CAD"}}
    if len(normalized) >= 2 and not re.search(
        r"\b(FX|foreign exchange|converted|USD/EUR)\b", text, re.I
    ):
        return [
            _finding(
                "MATH ERRORS",
                "MEDIUM",
                f"Multiple currencies detected ({', '.join(sorted(normalized))}) "
                "without an explicit FX / conversion note.",
                raw_values=sorted(normalized),
            )
        ]
    return []


def run_rule_based_checks(text: str) -> dict[str, object]:
    """Run all deterministic checks on the FULL extracted document text."""
    findings = [
        *check_margin_consistency(text),
        *check_percentage_sums(text),
        *check_growth_claims(text),
        *check_cap_table_math(text),
        *check_currency_consistency(text),
    ]
    unique_findings = list({finding["detail"]: finding for finding in findings}.values())
    summary = "\n".join(
        f"- [{finding['severity']}] {finding['category']}: {finding['detail']}"
        for finding in unique_findings
    )
    verified_block = (
        "The following arithmetic issues were verified deterministically. "
        "Treat them as confirmed unless the source quote clearly contradicts them:\n"
        + summary
        if unique_findings
        else "No deterministic arithmetic mismatches were found."
    )
    return {
        "findings": unique_findings,
        "summary": summary,
        "verified_block": verified_block,
    }
