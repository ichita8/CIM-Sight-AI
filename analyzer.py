import os
import re
import pymupdf4llm

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

def extract_text_from_pdf(pdf_path: str, max_pages: int = 100) -> str:
    """Extract markdown text from PDF using PyMuPDF4LLM"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        pages_to_extract = list(range(min(max_pages, total_pages)))
        md_text = pymupdf4llm.to_markdown(pdf_path, pages=pages_to_extract)
        return md_text
    except Exception as e:
        raise Exception(f"Failed to extract PDF text: {str(e)}")

def analyze_cim(pdf_path: str, api_key: str = None) -> dict:
    """Run the full CIM analysis pipeline"""

    # Step 1: Extract text
    raw_text = extract_text_from_pdf(pdf_path)

    # Truncate if too long (Groq has ~32k context on most models)
    if len(raw_text) > 100000:
        raw_text = raw_text[:100000] + "\n\n[Document truncated for analysis - first 100,000 characters processed]"

    # Step 2: Run Groq analysis
    from openai import OpenAI
    client = OpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=os.environ.get("CEREBRAS_API_KEY")
    )

    response = client.chat.completions.create(
        model="gpt-oss-120b",
        messages=[
            {
                "role": "system",
                "content": CYNICAL_MD_PROMPT
            },
            {
                "role": "user",
                "content": f"--- CIM DOCUMENT TEXT BELOW ---\n\n{raw_text}"
            }
        ],
        max_tokens=8000,
        temperature=0.0
    )

    analysis = response.choices[0].message.content

    # Step 3: Parse red flags
    red_flags = parse_red_flags(analysis)

    return {
        "raw_analysis": analysis,
        "red_flags": red_flags,
        "text_length": len(raw_text),
        "doc_preview": raw_text[:500]
    }

def parse_red_flags(analysis_text: str) -> list:
    """Parse the AI output into structured red flag objects"""
    import re

    red_flags = []

    KNOWN_CATEGORIES = [
        "MATH ERRORS",
        "AGGRESSIVE PROJECTIONS",
        "CUSTOMER CONCENTRATION RISKS",
        "DEBT & LIABILITY RISK",
        "MANAGEMENT LANGUAGE TELLS",
        "MARGIN INCONSISTENCIES",
    ]

    def clean_md(text):
        """Match text against known categories, return best match or cleaned text"""
        text_clean = clean_md(text)
        text_upper = text_clean.upper()
        for known in KNOWN_CATEGORIES:
            if known in text_upper or text_upper in known:
                return known
        # Partial keyword matching
        for known in KNOWN_CATEGORIES:
            keywords = known.split()
            if all(kw in text_upper for kw in keywords [:2]):
                return known
        return text_clean if text_clean else "UNKNOWN"

    Split on "RED FLAG" delimiter
    ctions = re.split(r'(?i)RED\s*FLAG', analysis_text)

    r section in sections[1:]:
        flag = {}
        lines = section.strip().split("\n")
        if not lines or not lines[0].strip():
            continue

        # Scan first 4 lines to find category
        category_found = False
        for i, line in enumerate(lines[:4]):
            lines_clean = clean_md(line)
            if not line_clean:
                continue
            # Check for pipe delimiter
            if "|" in line_clean:
                parts = line_clean.split("|", 1)
                flag["number"] = parts[0].strip()
                flag["category"] = match_category(parts[1]) if len(parts)
                category_found = True
                break                             
            # Check if line matches a known category
            matched = match_category(line_clean)
            if matched != "UNKNOWN" and matched != line_clean:
                flag["category"] = matched
                flag["number"] = ""
                category_found = True
                break
            # Check if line starts with # (number only, no category)
            if line_clean.startswith("#") or line_clean[0].isdigit():
                flag["number"] = line_clean.lstrip("#").strip()
                continue

        if not category_found:
            flag["category"] = "UNKNOWN"
            flag.setdefault("number", "")

        full_text = "\n".join(lines)

        # Severity - scan all lines
        sev_line = [l for l in lines if "Severity:" in l]
        if sev_line:
            flag["severity"] = clean_md(re.sub(r'(?i)severity:?', '', sev_line[0]))
        else
            flag["severity"] = "MEDIUM"

        # Quote
        if 'Quote:' in full_text or 'Quote :' in full_text:
            quote_start = full_text.find('Quote:')
            if quote_start == -1:
                quote_start = full_text.find('Quote :')
                quote_start += 7
            else
                quote_start+= 6
            quote_end = full_text.find("Why It's Suspicious:")
            if quote_end == -1:
                quote_end = quote_start + 500
            flag["quote"] = full_text[quote_start:quote_end].strip().strip('"').strip("'")
        else:
            flag["quote"] = ""

        # Explanation
        if "Why It's Suspicious:" in full_text:
            exp_start = full_text.find("Why It's Suspicious:") + 20
            exp_end = full_text.find("---")
            if exp_end == -1 or exp_end < exp_start:
                exp_end = len(full_text)
            flag["explanation"] = full_text[exp_start:exp_end].strip()
        else:
            flag["explanation"] = ""

        if flag.get("category") and (flag.get("quote") or flag.get("explanation")):
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
