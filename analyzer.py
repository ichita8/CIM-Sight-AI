from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz as pymupdf  # PyMuPDF — lightweight, no torch, no libGL needed

from rule_checks import run_rule_based_checks

ANALYSIS_CHARACTER_LIMIT = 100_000
CHUNK_SIZE = 80_000
CHUNK_OVERLAP = 10_000
SCANNED_CHARS_PER_PAGE = 180
DEFAULT_MAX_PAGES = 150
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
MAX_LLM_RETRIES = 4


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot be converted into usable text."""


class ConfigurationError(RuntimeError):
    """Raised when a required application configuration value is missing."""


class CerebrasAnalysisError(RuntimeError):
    """Raised when the Cerebras API cannot complete analysis."""

CYNICAL_MD_PROMPT = """
You are a Managing Director at a top-tier investment bank with 20+ years of experience reviewing Confidential Information Memorandums (CIMs).
You have seen dozens of deals collapse due to hidden risks, inflated projections, and misleading financials buried in these documents.

Your job is NOT to summarize the CIM. Your job is to be a cynical, aggressive auditor hunting for anything that smells off. 

Analyze the provided CIM text and identify only genuine red flags across these 6 categories:
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

Do not invent facts or quotes. After the findings, include a section titled
OVERALL RISK ASSESSMENT with a concise summary and a LOW, MEDIUM, HIGH, or
CRITICAL risk rating.
""".strip()

@dataclass
class SourceSpan:
    paragraph_id: str | None = None
    table_id: str | None = None
    page_number: int | None = None
    text: str = ""
    ocr_confidence: float | None = None


@dataclass
class ExtractionResult:
    markdown: str
    source_spans: list[SourceSpan] = field(default_factory=list)
    used_ocr: bool = False
    table_count: int = 0


def _convert_pdf(path: Path, *, max_pages: int) -> ExtractionResult:
    """Extract text + tables from a PDF using PyMuPDF (fitz).

    Replaces the Docling-based converter.  No torch, no system libraries,
    no model downloads — works on Streamlit Community Cloud free tier.
    """
    doc = pymupdf.open(str(path))
    if doc.is_encrypted:
        doc.close()
        raise PdfExtractionError(
            "This PDF is encrypted. Remove the password protection and try again."
        )

    pages_to_read = min(doc.page_count, max(1, max_pages))
    markdown_parts: list[str] = []
    spans: list[SourceSpan] = []
    table_count = 0

    for page_idx in range(pages_to_read):
        page = doc[page_idx]
        page_number = page_idx + 1

        # --- Text ---
        page_text = page.get_text("text")
        if page_text.strip():
            markdown_parts.append(page_text.strip())
            spans.append(
                SourceSpan(
                    paragraph_id=f"page_{page_number}",
                    page_number=page_number,
                    text=page_text.strip(),
                    ocr_confidence=None,
                )
            )

        # --- Tables (best-effort; PyMuPDF 1.23+) ---
        try:
            table_finder = page.find_tables()
            for table in table_finder.tables:
                table_md = table.to_markdown()
                if table_md and table_md.strip():
                    table_count += 1
                    markdown_parts.append(table_md.strip())
                    spans.append(
                        SourceSpan(
                            table_id=f"table_{table_count}",
                            page_number=page_number,
                            text=table_md.strip(),
                            ocr_confidence=None,
                        )
                    )
        except Exception:
            pass  # table detection is optional — never let it crash extraction

    doc.close()

    markdown = "\n\n".join(markdown_parts)
    if not markdown.strip():
        raise PdfExtractionError(
            "No readable text was found in this PDF. "
            "It may be a scanned document with no embedded text layer."
        )

    return ExtractionResult(
        markdown=markdown.strip(),
        source_spans=spans,
        used_ocr=False,
        table_count=table_count,
    )


def extract_document_from_pdf(
    pdf_path: str | Path,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> ExtractionResult:
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise PdfExtractionError("The uploaded PDF could not be found.")
    if path.suffix.lower() != ".pdf":
        raise PdfExtractionError("CIM-Sight currently accepts PDF files only.")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer.")

    try:
        return _convert_pdf(path, max_pages=max_pages)
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(
            f"Could not extract this PDF. Confirm that it is a readable, "
            f"unencrypted PDF and try again. ({type(exc).__name__}: {exc})"
        ) from exc


def extract_text_from_pdf(pdf_path: str | Path, max_pages: int = DEFAULT_MAX_PAGES) -> str:
    """Backward-compatible helper returning the full Markdown only."""
    return extract_document_from_pdf(pdf_path, max_pages=max_pages).markdown
def attach_provenance_to_findings(
    findings: list[dict[str, Any]],
    markdown: str,
    source_spans: list[SourceSpan],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for finding in findings:
        provenance = resolve_provenance(
            "",
            markdown,
            source_spans,
            char_offset=finding.get("char_offset"),
        )
        enriched.append({**finding, **provenance, "raw_extracted_values": finding.get("raw_values", [])})
    return enriched
def iter_text_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict[str, Any]]:
    if len(text) <= chunk_size:
        return [{"index": 0, "start": 0, "end": len(text), "text": text, "is_partial": False}]
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "text": text[start:end],
                "is_partial": end < len(text),
            }
        )
        if end >= len(text):
            break
        start = max(end - overlap, 0)
        index += 1
    return chunks
def _clean_markdown(text: str) -> str:
    return re.sub(r"[*`#_]", "", text).strip()
def _normalise_category(text: str) -> str:
    candidate = _clean_markdown(text).upper().replace("DEBT AND", "DEBT &")
    candidate = re.sub(r"\s+", " ", candidate)
    for category in KNOWN_CATEGORIES:
        if category in candidate or candidate in category:
            return category
    return "UNKNOWN"
def parse_red_flags(
    analysis_text: str,
    *,
    markdown: str = "",
    source_spans: list[SourceSpan] | None = None,
) -> list[dict[str, Any]]:
    """Parse red flags, keeping partial matches and attaching provenance."""
    if not analysis_text:
        return []
    red_flags: list[dict[str, Any]] = []
    sections = re.split(r"(?im)^[ \t]*RED[ \t]+FLAG\b", analysis_text)
    for section in sections[1:]:
        severity_match = re.search(
            r"(?im)^\s*severity\s*:\s*(HIGH|MEDIUM|LOW|CRITICAL)\b",
            section,
        )
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        header_lines = lines[:4]
        number_match = re.search(r"#?\s*(\d+)\b", header_lines[0] if header_lines else "")
        category = "UNKNOWN"
        for line in header_lines:
            category = _normalise_category(line.split("|", 1)[-1])
            if category != "UNKNOWN":
                break
        quote_match = re.search(
            r"(?ims)^\s*quote\s*:\s*(.*?)(?=^\s*why\s+it['’]?s\s+"
            r"suspicious\s*:|^\s*explanation\s*:\s*|^\s*---\s*$|\Z)",
            section,
        )
        explanation_match = re.search(
            r"(?ims)^\s*(?:why\s+it['’]?s\s+suspicious|explanation)\s*:\s*(.*?)(?="
            r"^\s*---\s*$|^\s*overall\s+risk\s+assessment\b|\Z)",
            section,
        )
        quote = _clean_markdown(quote_match.group(1)).strip('"\' ') if quote_match else ""
        explanation = _clean_markdown(explanation_match.group(1)) if explanation_match else ""
        if not quote and not explanation:
            continue
        severity = severity_match.group(1).upper() if severity_match else "UNKNOWN"
        parse_quality = "complete" if severity_match and quote and explanation else "partial"
        flag: dict[str, Any] = {
            "number": number_match.group(1) if number_match else "",
            "category": category,
            "severity": severity,
            "quote": quote,
            "explanation": explanation,
            "parse_quality": parse_quality,
        }
        flag.update(resolve_provenance(quote, markdown, source_spans or []))
        red_flags.append(flag)
    return red_flags
def _dedupe_red_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    for flag in flags:
        key = (flag.get("category", ""), (flag.get("quote") or "")[:100].lower())
        if any(
            (existing.get("category", ""), (existing.get("quote") or "")[:100].lower()) == key
            for existing in unique
        ):
            continue
        unique.append(flag)
    return unique
def _get_cerebras_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("CEREBRAS_API_KEY")
    if not key or not key.strip():
        raise ConfigurationError(
            "A Cerebras API key is required. Add CEREBRAS_API_KEY to Streamlit "
            "Secrets, an environment variable, or the app's key field."
        )
    return key.strip()
def _classify_cerebras_error(exc: Exception) -> str:
    message = str(exc).lower()
    name = exc.__class__.__name__.lower()
    if "authentication" in name or "401" in message or "invalid api key" in message:
        return "Invalid Cerebras API key. Check CEREBRAS_API_KEY and try again."
    if "404" in message or "model not found" in message or "does not exist" in message or "not available" in message:
        return (
            "Cerebras model unavailable. Verify CEREBRAS_MODEL and that your account "
            f"can access {os.environ.get('CEREBRAS_MODEL', DEFAULT_CEREBRAS_MODEL)}."
        )
    if "429" in message or "rate limit" in message:
        return "Cerebras rate limit hit. Wait a minute and retry."
    if "timeout" in message or "connection" in message or "network" in message:
        return "Network error reaching Cerebras. Check your connection and retry."
    return f"Cerebras analysis failed: {exc}"
def _call_cerebras(client: Any, messages: list[dict[str, str]]) -> str:
    try:
        from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
    except ImportError as exc:
        raise ConfigurationError(
            "tenacity is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    def _is_retryable(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(token in msg for token in ("429", "503", "timeout", "connection", "temporarily"))
    @retry(
        reraise=True,
        stop=stop_after_attempt(MAX_LLM_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception(_is_retryable),
    )
    def _create() -> str:
        response = client.chat.completions.create(
            model=os.environ.get("CEREBRAS_MODEL", DEFAULT_CEREBRAS_MODEL),
            messages=messages,
            max_tokens=8_000,
            temperature=0.0,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise CerebrasAnalysisError("Cerebras returned an empty analysis response.")
        return content.strip()
    try:
        return _create()
    except Exception as exc:
        raise CerebrasAnalysisError(_classify_cerebras_error(exc)) from exc
def _analyze_chunk_with_llm(
    client: Any,
    chunk: dict[str, Any],
    verified_block: str,
    total_chunks: int,
) -> str:
    chunk_note = (
        f"This is chunk {chunk['index'] + 1} of {total_chunks} "
        f"(characters {chunk['start']:,}-{chunk['end']:,}). "
        "Only comment on risks supported by this chunk."
    )
    if chunk["is_partial"]:
        chunk_note += " This chunk ends before the full document ends."
    messages = [
        {"role": "system", "content": CYNICAL_MD_PROMPT},
        {
            "role": "user",
            "content": (
                f"{chunk_note}\n\n"
                "--- VERIFIED ARITHMETIC FINDINGS ---\n"
                f"{verified_block}\n\n"
                "--- CIM DOCUMENT MARKDOWN ---\n\n"
                f"{chunk['text']}"
            ),
        },
    ]
    header = f"### Chunk {chunk['index'] + 1}/{total_chunks}\n"
    return header + _call_cerebras(client, messages)
def analyze_cim(
    pdf_path: str | Path,
    api_key: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Run Docling extraction, deterministic checks, chunked LLM analysis."""
    extraction = extract_document_from_pdf(pdf_path, max_pages=max_pages)
    raw_text = extraction.markdown
    rule_results = run_rule_based_checks(raw_text)
    rule_findings = attach_provenance_to_findings(
        rule_results["findings"],
        raw_text,
        extraction.source_spans,
    )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ConfigurationError(
            "The OpenAI-compatible client is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    client = OpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=_get_cerebras_api_key(api_key),
    )
    chunks = iter_text_chunks(raw_text, chunk_size=ANALYSIS_CHARACTER_LIMIT)
    llm_sections: list[str] = []
    parsed_flags: list[dict[str, Any]] = []
    for chunk in chunks:
        section = _analyze_chunk_with_llm(
            client,
            chunk,
            str(rule_results["verified_block"]),
            total_chunks=len(chunks),
        )
        llm_sections.append(section)
        parsed_flags.extend(
            parse_red_flags(
                section,
                markdown=raw_text,
                source_spans=extraction.source_spans,
            )
        )
    llm_analysis = "\n\n".join(llm_sections)
    red_flags = _dedupe_red_flags(parsed_flags)
    analyzed_chars = sum(chunk["end"] - chunk["start"] for chunk in chunks)
    uncovered_ranges = []
    if len(chunks) > 1:
        for idx in range(len(chunks) - 1):
            gap_start = chunks[idx]["end"] - CHUNK_OVERLAP
            gap_end = chunks[idx + 1]["start"]
            if gap_end > gap_start:
                uncovered_ranges.append({"start": gap_start, "end": gap_end})
    return {
        "raw_analysis": llm_analysis.strip(),
        "red_flags": red_flags,
        "rule_findings": rule_findings,
        "text_length": min(len(raw_text), analyzed_chars),
        "source_text_length": len(raw_text),
        "was_truncated": len(chunks) > 1 or len(raw_text) > ANALYSIS_CHARACTER_LIMIT,
        "chunks_analyzed": len(chunks),
        "chunk_ranges": [{"start": c["start"], "end": c["end"]} for c in chunks],
        "uncovered_ranges": uncovered_ranges,
        "used_ocr": extraction.used_ocr,
        "table_count": extraction.table_count,
        "doc_preview": raw_text[:500],
    }
def get_severity_color(severity: str) -> str:
    normalized = severity.upper()
    if "HIGH" in normalized or "CRITICAL" in normalized:
        return "#FF4444"
    if "MEDIUM" in normalized:
        return "#FF9900"
    return "#FFD700"
def get_overall_risk(analysis_text: str) -> str:
    match = re.search(r"(?is)\bOVERALL\s+RISK\s+ASSESSMENT\b.*", analysis_text or "")
    return match.group(0).strip() if match else ""
