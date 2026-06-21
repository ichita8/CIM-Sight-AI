import os
import re
import pymupdf4llm
from groq import Groq

CYNICAL_MD_PROMPT = """
You are a Managing Director at a top-tier investment bank with 20+ years of experience reviewing Confidential Information Memorandums (CIMs). 
You have seen dozens of deals collapse due to hidden risks, inflated projections, and misleading financials buried in these documents.

Your job is NOT to summarize this CIM. Your job is to be a cynical, aggressive auditor â€” hunting for anything that smells off.

Analyze the provided CIM text and identify red flags across these 6 categories:

1. MATH ERRORS â€” Revenue, EBITDA, margin, or growth figures that don't add up or contradict each other across sections
2. AGGRESSIVE PROJECTIONS â€” Hockey-stick growth, unrealistic CAGR assumptions, or projections with no credible justification
3. CUSTOMER CONCENTRATION RISK â€” Over-reliance on a single client, customer, or revenue stream
4. DEBT & LIABILITY RED FLAGS â€” Buried obligations, off-balance-sheet items, unusual debt structures, or covenant risks
5. MANAGEMENT LANGUAGE TELLS â€” Vague, evasive, overly promotional, or suspiciously hedged language around key metrics
6. MARGIN INCONSISTENCIES â€” Gross/EBITDA/net margins that shift suspiciously between periods without clear explanation

For EACH red flag you find, output it in EXACTLY this format:

ðŸš¨ RED FLAG #[number] â€” [CATEGORY NAME]
Severity: [HIGH / MEDIUM / LOW]
Quote: "[exact quoted text from the document]"
Why It's Suspicious: [Your MD-level explanation of the specific concern â€” be direct, specific, and brutal]

---

Rules:
- Only flag things that are genuinely suspicious. Don't manufacture issues.
- Be specific. Reference exact numbers, percentages, and page context when possible.
- Think like someone who has watched deals blow up. What would make you walk away from this deal?
- Minimum 5 red flags, maximum 15.
- After all red flags, add a section called "OVERALL RISK ASSESSMENT" with a paragraph summary and an overall deal risk rating: LOW / MEDIUM / HIGH / CRITICAL
"""

def extract_text_from_pdf(pdf_path: str, max_pages: int = 50) -> str:
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

def analyze_cim(pdf_path: str, api_key: str) -> dict:
    """Run the full CIM analysis pipeline"""

    # Step 1: Extract text
    raw_text = extract_text_from_pdf(pdf_path)

    # Truncate if too long (Groq has ~32k context on most models)
    if len(raw_text) > 24000:
        raw_text = raw_text[:24000] + "\n\n[Document truncated for analysis â€” first 24,000 characters processed]"

    # Step 2: Run Groq analysis
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
        max_tokens=4000,
        temperature=0.3
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
    red_flags = []

    sections = analysis_text.split("ðŸš¨ RED FLAG #")

    for section in sections[1:]:
        flag = {}
        lines = section.strip().split("\n")

        if lines:
            header = lines[0]
            if "â€”" in header:
                parts = header.split("â€”", 1)
                flag["number"] = parts[0].strip()
                flag["category"] = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
            else:
                flag["number"] = header.strip()
                flag["category"] = "UNKNOWN"

        full_text = "\n".join(lines[1:])

        # Severity
        sev_line = [l for l in lines if "Severity:" in l]
        flag["severity"] = sev_line[0].replace("Severity:", "").strip() if sev_line else "MEDIUM"

        # Quote
        if 'Quote:' in full_text:
            quote_start = full_text.find('Quote:') + 6
            quote_end = full_text.find("Why It's Suspicious:")
            if quote_end == -1:
                quote_end = quote_start + 500
            flag["quote"] = full_text[quote_start:quote_end].strip().strip('"')
        else:
            flag["quote"] = ""

        # Explanation
        if "Why It's Suspicious:" in full_text:
            exp_start = full_text.find("Why It's Suspicious:") + 20
            exp_end = full_text.find("---")
            if exp_end == -1:
                exp_end = len(full_text)
            flag["explanation"] = full_text[exp_start:exp_end].strip()
        else:
            flag["explanation"] = ""

        if flag.get("category"):
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
