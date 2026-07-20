import os
import re
from functools import lru_cache

from docling.document_converter import DocumentConverter

from rule_checks import run_rule_based_checks

CYNICAL_MD_PROMPT = """
You are a Managing Director at a top-tier investment bank with 20+ years of experience reviewing Confidential Information Memorandums (CIMs).
You have seen dozens of deals collapse due to hidden risks, inflated projections, and misleading financials buried in these documents.

Your job is NOT to summarize this CIM. Your job is to be a cynical, aggressive auditor hunting for anything that smells off.

Analyze the provided CIM text and identify red flags across these 6 categories:

1. MATH ERRORS - Revenue, EBITDA, margin, or growth figures that don't add up or contradict each other across sections
2. AGGRESSIVE PROJECTIONS - Hockey-stick growth, unrealistic CAGR assumptions, or projections with no credible justification
3. CUSTOMER CONCENTRATION RISK - Over-reliance on a single client, customer, or revenue stream
4. DEBT & LIABILITY RED FLAGS - Buried obligations, off-balance-sheet items, unusual debt structures, or covenant risks
5. MANAGEMENT LANGUAGE TELLS - Vague, evasive, overly promotional, or suspiciously hedged language around key metrics
6. MARGIN INCONSISTENCIES - Gross/EBITDA/net margins that shift suspiciously between periods without clear explanation

For EACH red flag you find, output it in EXACTLY this format - no markdown, no asterisks, no bold, no emojis:

RED FLAG #[number] | [CATEGORY NAME]
Severity: [HIGH / MEDIUM / LOW]
Quote: "[exact quoted text from the document]"
Why It's Suspicious: [Your MD-level explanation of the specific concern; be direct, specific, and brutal]

---

Critical Format Rules:
- The delimiter line must start with "RED FLAG" and use a pipe | to separate number and category
- Do NOT use ** or ## or any markdown formatting anywhere in the delimiter, category, or severity lines.
- Use the exact category names listed above (e.g. "MATH ERRORS", not "Math Error").
- The Quote and Why It's Suspicious fields may use **bold** markdown for emphasis.

Rules:
- Only flag things that are genuinely suspicious. Don't manufacture issues.
- Be specific. Reference exact numbers, percentages, and page context when possible.
- Think like someone who has watched deals blow up. What would make you walk away from this deal?
- After all red flags, add a section called "OVERALL RISK ASSESSMENT" with a paragraph summary and an overall deal risk rating: LOW / MEDIUM / HIGH / CRITICAL
"""


@lru_cache(maxsize=1)
def _get_converter() -> DocumentConverter:
    """Build the Docling converter once and reuse it (model load is expensive)."""
    return DocumentConverter()


def extract_text_from_pdf(pdf_path: str, max_pages: int = 100) -> str:
    """Extract markdown text from a PDF using the Docling document engine."""
    try:
        converter = _get_converter()
        result = converter.convert(pdf_path, page_range=(1, max_pages))
        return result.document.export_to_markdown()
    except Exception as e:
        raise Exception(f"Failed to extract PDF text: {str(e)}")


def analyze_cim(pdf_path: str, api_key: str = None) -> dict:
    """Run the full CIM analysis pipeline"""

    # Step 1: Extract text
    raw_text = extract_text_from_pdf(pdf_path)

    # Truncate if too long
    if len(raw_text) > 100000:
        raw_text = raw_text[:100000] + "\n\n[Document truncated for analysis - first 100,000 characters processed]"

    # Step 2: Run deterministic rule-based checks FIRST
    rule_results = run_rule_based_checks(raw_text)
    rule_findings = rule_results.get("findings", [])

    # Step 3: Run Cerebras LLM analysis
    from openai import OpenAI
    client = OpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=api_key or os.environ.get("CEREBRAS_API_KEY")
    )

    # Include rule-based findings in the prompt so the LLM is aware
    rule_context = ""
    if rule_findings:
        rule_context = "\n\n--- PRE-COMPUTED ARITHMETIC FINDINGS (verify these) ---\n" + rule_results.get("summary", "")

    response = client.chat.completions.create(
        model="gpt-oss-120b",
        messages=[
            {
                "role": "system",
                "content": CYNICAL_MD_PROMPT
            },
            {
                "role": "user",
                "content": f"--- CIM DOCUMENT TEXT BELOW ---\n\n{raw_text}{rule_context}"
            }
        ],
        max_tokens=8000,
        temperature=0.0
    )

    analysis = response.choices[0].message.content

    # Step 4: Parse red flags
    red_flags = parse_red_flags(analysis)

    return {
        "raw_analysis": analysis,
        "red_flags": red_flags,
        "rule_findings": rule_findings,
        "text_length": len(raw_text),
        "doc_preview": raw_text[:500]
    }


def parse_red_flags(analysis_text: str) -> list:
    """Parse the AI output into structured red flag objects"""
    red_flags = []

    KNOWN_CATEGORIES = [
        "MATH ERRORS",
        "AGGRESSIVE PROJECTIONS",
        "CUSTOMER CONCENTRATION RISK",
        "DEBT & LIABILITY RED FLAGS",
        "DEBT AND LIABILITY RED FLAGS",
        "MANAGEMENT LANGUAGE TELLS",
        "MARGIN INCONSISTENCIES",
    ]

    def clean_md(text):
        """Strip markdown formatting markers"""
        text = text.replace("**", "").replace("##", "").replace("#", "")
        return text.strip()

    def match_category(text):
        """Match text against known categories"""
        text_clean = clean_md(text)
        text_upper = text_clean.upper()
        text_norm = text_upper.replace("&", "AND")

        for known in KNOWN_CATEGORIES:
            known_norm = known.replace("&", "AND")
            if known_norm in text_norm or text_norm in known_norm:
                return known.replace("DEBT AND", "DEBT &")
        for known in KNOWN_CATEGORIES:
            keywords = known.replace("&", "AND").split()
            if len(keywords) >= 2 and all(kw in text_norm for kw in keywords[:2]):
                return known.replace("DEBT AND", "DEBT &")
        return text_clean if text_clean else "UNKNOWN"

    # KEY FIX: Only split on "RED FLAG" at the START of a line (multiline mode).
    # This prevents matching "red flag" in body text like "a classic red flag for..."
    sections = re.split(r'(?im)^[ \t]*RED[ \t]*FLAG', analysis_text)

    for section in sections[1:]:
        flag = {}
        lines = section.strip().split("\n")
        if not lines or not lines[0].strip():
            continue

        # KEY FIX: Require a Severity line — all real flags have one.
        # This filters phantom sections created by "red flag" in body text.
        has_severity = any("severity" in l.lower() for l in lines)
        if not has_severity:
            continue

        # Scan first 4 lines to find category
        category_found = False
        for i, line in enumerate(lines[:4]):
            line_clean = clean_md(line)
            if not line_clean:
                continue
            if "|" in line_clean:
                parts = line_clean.split("|", 1)
                flag["number"] = parts[0].strip()
                flag["category"] = match_category(parts[1]) if len(parts) > 1 else "UNKNOWN"
                category_found = True
                break
            matched = match_category(line_clean)
            if matched != "UNKNOWN" and matched != line_clean:
                flag["category"] = matched
                flag["number"] = ""
                category_found = True
                break
            if line_clean.startswith("#") or (line_clean and line_clean[0].isdigit()):
                flag["number"] = line_clean.lstrip("#").strip()
                continue

        if not category_found:
            flag["category"] = "UNKNOWN"
            flag.setdefault("number", "")

        full_text = "\n".join(lines)

        # Severity
        sev_line = [l for l in lines if "severity" in l.lower()]
        if sev_line:
            flag["severity"] = clean_md(re.sub(r'(?i)severity:?\s*', '', sev_line[0]))
        else:
            flag["severity"] = "MEDIUM"

        # Quote — text between "Quote:" and "Why It's Suspicious"
        quote_pos = full_text.lower().find("quote:")
        if quote_pos != -1:
            quote_start = full_text.find(":", quote_pos) + 1
            why_re = re.compile(r"(?i)why\s+it['\u2019]?s\s+suspicious")
            why_match = why_re.search(full_text, quote_start)
            if why_match:
                quote_end = why_match.start()
            else:
                quote_end = quote_start + 500
            flag["quote"] = full_text[quote_start:quote_end].strip().strip('"').strip("'")
        else:
            flag["quote"] = ""

        # Explanation — text after "Why It's Suspicious:" up to "---" or OVERALL RISK
        why_re = re.compile(r"(?i)why\s+it['\u2019]?s\s+suspicious:?")
        why_match = why_re.search(full_text)
        if why_match:
            exp_start = why_match.end()
            # Find end: "---" on its own line, or OVERALL RISK ASSESSMENT
            sep_match = re.search(r'\n\s*-{2,}', full_text[exp_start:])
            overall_match = re.search(r'(?i)overall\s+risk\s+assessment', full_text[exp_start:])
            ends = []
            if sep_match:
                ends.append(exp_start + sep_match.start())
            if overall_match:
                ends.append(exp_start + overall_match.start())
            exp_end = min(ends) if ends else len(full_text)
            flag["explanation"] = full_text[exp_start:exp_end].strip()
        else:
            flag["explanation"] = ""

        # Only keep flags with actual content
        if flag.get("quote") or flag.get("explanation"):
            red_flags.append(flag)

    return red_flags


def get_severity_color(severity: str) -> str:
    severity = severity.upper()
    if "HIGH" in severity or "CRITICAL" in severity:
        return "#FF4444"
    elif "MEDIUM" in severity:
        return "#FF9900"
    else:
        return "#FFD700"


def get_overall_risk(analysis_text: str) -> str:
    if "OVERALL RISK ASSESSMENT" in analysis_text:
        start = analysis_text.find("OVERALL RISK ASSESSMENT")
        return analysis_text[start:].strip()
    return ""
