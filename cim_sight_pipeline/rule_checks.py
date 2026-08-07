from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional
from .parsers import ExtractionResult

MARGIN_TOLERANCE_PCT = 0.5
GROWTH_TOLERANCE_PCT = 1.0
CAP_TABLE_TOLERANCE_PCT = 1.5

CURRENCY_PATTERN = re.compile(r"\b(USD|EUR|GBP|CAD)\b|(\$|€|£)", re.IGNORECASE)
PERCENTAGE_BREAKDOWN_CUES = re.compile(
    r"\b(breakdown|mix|allocation|composition|split|distribution|concentration|cap\s*table|ownership)\b",
    re.IGNORECASE,
)


@dataclass
class RuleFinding:
    category: str = "MATH ERRORS"
    severity: str = "MEDIUM"
    detail: str = ""
    char_offset: Optional[int] = None
    page_number: Optional[int] = None
    raw_values: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "detail": self.detail,
            "char_offset": self.char_offset,
            "page_number": self.page_number,
            "raw_values": self.raw_values,
        }


@dataclass
class FinancialFact:
    """Phase 3 (#7): structured financial fact for period-aware pairing."""
    metric: str
    period: str
    value: float
    raw: str
    char_offset: int


_METRIC_WORDS = [
    "revenue", "ebitda", "ebit", "gross profit", "net income",
    "operating income", "operating margin", "gross margin", "net margin", "ebitda margin",
]


def _to_number(raw: str) -> Optional[float]:
    if not raw:
        return None
    v = raw.strip().replace(",", "").replace("$", "").replace("%", "")
    v = re.sub(r"\s+", "", v)
    mult = 1.0
    if v and v[-1].lower() in {"k", "m", "b"}:
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[v[-1].lower()]
        v = v[:-1]
    try:
        return float(v) * mult
    except ValueError:
        return None


# Phase 3 (#8): a real parser, not one giant regex. Handles
#   "Gross Profit  FY2023  $20M", "Revenue FY24 150M", "EBITDA Q3 $4.2M" etc.
def parse_financial_lines(text: str) -> list:
    facts = []
    pattern = re.compile(
        r"([A-Za-z][A-Za-z ]{2,40}?)\b[^$\d]{0,40}?\b"
        r"(FY\s?(?:19|20)\d{2}|FY\d{2,4}|20\d{2}|Q[1-4](?:\s?(?:19|20)?\d{2})?)\b"
        r"[^$\d]{0,40}?\$?\s*([0-9][0-9,.]*(?:\s*[kKmMbB])?)",
        re.I,
    )
    for m in pattern.finditer(text):
        metric = m.group(1).strip().lower()
        if not any(w in metric for w in _METRIC_WORDS):
            continue
        val = _to_number(m.group(3))
        if val is None:
            continue
        facts.append(FinancialFact(metric, m.group(2).upper(), val, m.group(3).strip(), m.start()))
    return facts


def _norm_period(p: str) -> str:
    p = p.upper().replace(" ", "")
    m = re.fullmatch(r"FY(\d{2})", p)
    if m:
        yy = int(m.group(1))
        return ("20" if yy < 50 else "19") + m.group(1)
    if p.startswith("FY"):
        return p[2:]
    return p


def _same_period(a: str, b: str) -> bool:
    return _norm_period(a) == _norm_period(b)


def pair_by_period(facts, num_metric: str, den_metric: str):
    a = [f for f in facts if num_metric in f.metric]
    b = [f for f in facts if den_metric in f.metric]
    pairs = []
    for fa in a:
        for fb in b:
            if _same_period(fa.period, fb.period):
                pairs.append((fa, fb))
    return pairs


def check_margin_consistency(text: str, extraction: Optional[ExtractionResult] = None) -> list:
    findings = []
    facts = parse_financial_lines(text)
    for num, den in [("ebitda", "revenue"), ("ebit", "revenue"),
                     ("gross profit", "revenue"), ("net income", "revenue")]:
        for fa, fb in pair_by_period(facts, num, den):
            if fb.value <= 0:
                continue
            computed = fa.value / fb.value * 100
            for mm in re.finditer(
                r"\b(gross|ebitda|net|operating)\s+margin[^0-9]{0,25}([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
                text, re.I,
            ):
                if abs(mm.start() - fa.char_offset) < 800:
                    stated = float(mm.group(2))
                    if abs(computed - stated) > MARGIN_TOLERANCE_PCT:
                        page = extraction.page_for_offset(mm.start()) if extraction else None
                        findings.append(RuleFinding(
                            "MATH ERRORS", "HIGH",
                            "Stated %s margin is %.1f%%, but %s (%,.0f) / %s (%,.0f, %s) = %.2f%%. "
                            "Discrepancy %.2f pts." % (
                                mm.group(1), stated, num, fa.value, den, fb.value, fa.period,
                                computed, abs(computed - stated)),
                            char_offset=mm.start(), page_number=page,
                            raw_values=["%s%%" % stated, fa.raw, fb.raw],
                        ))
                    break
    return findings


def check_percentage_sums(text: str, extraction: Optional[ExtractionResult] = None) -> list:
    findings = []
    for block in re.split(r"\n\s*\n", text):
        cue = PERCENTAGE_BREAKDOWN_CUES.search(block)
        if not cue:
            continue
        pcts = [float(v) for v in re.findall(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%", block)]
        if 3 <= len(pcts) <= 12:
            total = sum(pcts)
            if 90 < total < 110 and abs(total - 100) > 1.5:
                page = extraction.page_for_offset(cue.start()) if extraction else None
                findings.append(RuleFinding(
                    "MATH ERRORS", "MEDIUM",
                    "Percentage breakdown sums to %.1f%% (expected ~100%%): %s" % (total, pcts),
                    char_offset=cue.start(), page_number=page,
                    raw_values=["%s%%" % p for p in pcts],
                ))
    return findings


def check_growth_claims(text: str, extraction: Optional[ExtractionResult] = None) -> list:
    findings = []
    pattern = re.compile(
        r"from\s+\$?\s*([0-9][0-9,.]*(?:\s*[kKmMbB])?)\s+to\s+\$?\s*"
        r"([0-9][0-9,.]*(?:\s*[kKmMbB]?))[^0-9%]{0,30}?([0-9]{1,4}(?:\.[0-9]+)?)\s*%",
        re.I,
    )
    for m in pattern.finditer(text):
        start = _to_number(m.group(1))
        end = _to_number(m.group(2))
        stated = float(m.group(3))
        if start is None or end is None or start <= 0:
            continue
        computed = (end - start) / start * 100
        if abs(computed - stated) > GROWTH_TOLERANCE_PCT:
            page = extraction.page_for_offset(m.start()) if extraction else None
            findings.append(RuleFinding(
                "MATH ERRORS", "HIGH",
                "Stated growth %.1f%% from %,.0f to %,.0f, actual %.1f%%." % (stated, start, end, computed),
                char_offset=m.start(), page_number=page,
                raw_values=[m.group(1), m.group(2), "%s%%" % stated],
            ))
    return findings


def check_cap_table_math(text: str, extraction: Optional[ExtractionResult] = None) -> list:
    findings = []
    cue_re = re.compile(r"\b(cap\s*table|ownership|shareholder|fully\s+diluted)\b", re.I)
    for block in re.split(r"\n\s*\n", text):
        if not cue_re.search(block):
            continue
        pcts = [float(v) for v in re.findall(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%", block)]
        if 2 <= len(pcts) <= 15:
            total = sum(pcts)
            if 95 < total < 105 and abs(total - 100) > CAP_TABLE_TOLERANCE_PCT:
                cue = cue_re.search(block)
                page = extraction.page_for_offset(cue.start()) if extraction and cue else None
                findings.append(RuleFinding(
                    "MATH ERRORS", "HIGH",
                    "Cap table percentages sum to %.1f%% (expected ~100%%): %s" % (total, pcts),
                    char_offset=cue.start() if cue else None, page_number=page,
                    raw_values=["%s%%" % p for p in pcts],
                ))
    return findings


def check_currency_consistency(text: str, extraction: Optional[ExtractionResult] = None) -> list:
    currencies = set()
    for m in CURRENCY_PATTERN.finditer(text):
        c = (m.group(1) or m.group(2)).upper().replace("€", "EUR").replace("£", "GBP").replace("$", "USD")
        if c in {"USD", "EUR", "GBP", "CAD"}:
            currencies.add(c)
    if len(currencies) >= 2 and not re.search(r"\b(FX|foreign exchange|converted|USD/EUR)\b", text, re.I):
        return [RuleFinding(
            "MATH ERRORS", "MEDIUM",
            "Multiple currencies (%s) without an FX note." % ", ".join(sorted(currencies)),
            raw_values=sorted(currencies),
        )]
    return []


def run_rule_based_checks(text: str, extraction: Optional[ExtractionResult] = None) -> dict:
    findings = [
        *check_margin_consistency(text, extraction),
        *check_percentage_sums(text, extraction),
        *check_growth_claims(text, extraction),
        *check_cap_table_math(text, extraction),
        *check_currency_consistency(text, extraction),
    ]
    unique = list({f.detail: f for f in findings}.values())
    summary = "\n".join("- [%s] %s: %s" % (f.severity, f.category, f.detail) for f in unique)
    return {"findings": unique, "summary": summary}
