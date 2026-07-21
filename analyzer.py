from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rule_checks import run_rule_based_checks


ANALYSIS_CHARACTER_LIMIT = 100_000
DEFAULT_MAX_PAGES = 100
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot be converted into usable Markdown."""


class ConfigurationError(RuntimeError):
    """Raised when a required application configuration value is missing."""


CYNICAL_MD_PROMPT = """
You are a Managing Director at a top-tier investment bank with 20+ years of
experience reviewing Confidential Information Memorandums (CIMs). Your job is
not to summarize the CIM. Audit it for material, document-supported risks.

Identify only genuine red flags across these categories:
1. MATH ERRORS
2. AGGRESSIVE PROJECTIONS
3. CUSTOMER CONCENTRATION RISK
4. DEBT & LIABILITY RED FLAGS
5. MANAGEMENT LANGUAGE TELLS
6. MARGIN INCONSISTENCIES

For every finding, use exactly this machine-readable structure (no Markdown in
the RED FLAG, Severity, or Quote labels):

RED FLAG #<number> | <CATEGORY NAME>
Severity: <HIGH | MEDIUM | LOW>
Quote: "<exact supporting quotation from the document>"
Why It's Suspicious: <specific, concise explanation>
---

Do not invent facts or quotes. After the findings, include a section titled
OVERALL RISK ASSESSMENT with a concise summary and a LOW, MEDIUM, HIGH, or
CRITICAL risk rating.
""".strip()


@lru_cache(maxsize=1)
def _get_docling_converter() -> Any:
    """Build one PDF-only Docling converter per process.

    Docling loads document models lazily; caching the converter avoids repeating
    configuration work on every Streamlit rerun.
    """
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise PdfExtractionError(
            "Docling is not installed. Run `pip install -r requirements.txt` "
            "before analyzing a CIM."
        ) from exc

    pipeline_options = PdfPipelineOptions()
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)},
    )


def extract_text_from_pdf(pdf_path: str | Path, max_pages: int = DEFAULT_MAX_PAGES) -> str:
    """Convert the first ``max_pages`` of a PDF into Docling Markdown.

    Docling's page range is one-indexed and inclusive. Using a page range (not
    ``max_num_pages``) preserves the prior app behavior of analyzing the first
    100 pages instead of rejecting a document that exceeds that size.
    """
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise PdfExtractionError("The uploaded PDF could not be found.")
    if path.suffix.lower() != ".pdf":
        raise PdfExtractionError("CIM-Sight currently accepts PDF files only.")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer.")

    try:
        result = _get_docling_converter().convert(
            path,
            raises_on_error=True,
            max_num_pages=max_pages,
        )
        document = getattr(result, "document", None)
        if document is None:
            raise PdfExtractionError("Docling could not create a document from this PDF.")
        markdown = document.export_to_markdown()
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(
            "Docling could not extract this PDF. Confirm that it is a readable, "
            "unencrypted PDF and try again."
        ) from exc

    if not isinstance(markdown, str) or not markdown.strip():
        raise PdfExtractionError("Docling extracted no readable text from this PDF.")
    return markdown.strip()


def _get_cerebras_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("CEREBRAS_API_KEY")
    if not key or not key.strip():
        raise ConfigurationError(
            "A Cerebras API key is required. Add CEREBRAS_API_KEY to Streamlit "
            "Secrets, an environment variable, or the app's key field."
        )
    return key.strip()


def analyze_cim(
    pdf_path: str | Path,
    api_key: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Run Docling extraction, deterministic checks, and Cerebras analysis."""
    raw_text = extract_text_from_pdf(pdf_path, max_pages=max_pages)
    was_truncated = len(raw_text) > ANALYSIS_CHARACTER_LIMIT
    analysis_text = raw_text[:ANALYSIS_CHARACTER_LIMIT]
    if was_truncated:
        analysis_text += "\n\n[Document truncated for LLM analysis after 100,000 characters.]"

    rule_results = run_rule_based_checks(analysis_text)
    rule_findings = rule_results["findings"]
    rule_context = ""
    if rule_findings:
        rule_context = (
            "\n\n--- PRE-COMPUTED ARITHMETIC FINDINGS (VERIFY THESE) ---\n"
            + rule_results["summary"]
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ConfigurationError(
            "The OpenAI-compatible client is not installed. Run `pip install -r "
            "requirements.txt`."
        ) from exc

    client = OpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=_get_cerebras_api_key(api_key),
    )
    try:
        response = client.chat.completions.create(
            model=os.environ.get("CEREBRAS_MODEL", DEFAULT_CEREBRAS_MODEL),
            messages=[
                {"role": "system", "content": CYNICAL_MD_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "--- CIM DOCUMENT MARKDOWN ---\n\n"
                        f"{analysis_text}{rule_context}"
                    ),
                },
            ],
            max_tokens=8_000,
            temperature=0.0,
        )
        llm_analysis = response.choices[0].message.content
    except (IndexError, AttributeError, TypeError) as exc:
        raise RuntimeError("Cerebras returned an empty or malformed analysis response.") from exc
    except Exception as exc:
        raise RuntimeError(
            "Cerebras analysis failed. Verify the API key, model access, and network connection."
        ) from exc

    if not isinstance(llm_analysis, str) or not llm_analysis.strip():
        raise RuntimeError("Cerebras returned an empty analysis response.")

    return {
        "raw_analysis": llm_analysis.strip(),
        "red_flags": parse_red_flags(llm_analysis),
        "rule_findings": rule_findings,
        "text_length": len(analysis_text),
        "source_text_length": len(raw_text),
        "was_truncated": was_truncated,
        "doc_preview": raw_text[:500],
    }


KNOWN_CATEGORIES = (
    "MATH ERRORS",
    "AGGRESSIVE PROJECTIONS",
    "CUSTOMER CONCENTRATION RISK",
    "DEBT & LIABILITY RED FLAGS",
    "MANAGEMENT LANGUAGE TELLS",
    "MARGIN INCONSISTENCIES",
)


def _clean_markdown(text: str) -> str:
    return re.sub(r"[*`#_]", "", text).strip()


def _normalise_category(text: str) -> str:
    candidate = _clean_markdown(text).upper().replace("DEBT AND", "DEBT &")
    candidate = re.sub(r"\s+", " ", candidate)
    for category in KNOWN_CATEGORIES:
        if category in candidate or candidate in category:
            return category
    return "UNKNOWN"


def parse_red_flags(analysis_text: str) -> list[dict[str, str]]:
    """Parse only well-formed, evidence-bearing red flags from LLM output."""
    if not analysis_text:
        return []

    red_flags: list[dict[str, str]] = []
    sections = re.split(r"(?im)^[ \t]*RED[ \t]+FLAG\b", analysis_text)
    for section in sections[1:]:
        severity_match = re.search(
            r"(?im)^\s*severity\s*:\s*(HIGH|MEDIUM|LOW|CRITICAL)\b", section
        )
        if not severity_match:
            continue

        lines = [line.strip() for line in section.splitlines() if line.strip()]
        header_lines = lines[:4]
        header = header_lines[0] if header_lines else ""
        number_match = re.search(r"#?\s*(\d+)\b", header)
        category = "UNKNOWN"
        for line in header_lines:
            category = _normalise_category(line.split("|", 1)[-1])
            if category != "UNKNOWN":
                break

        quote_match = re.search(
            r"(?ims)^\s*quote\s*:\s*(.*?)(?=^\s*why\s+it['’]?s\s+"
            r"suspicious\s*:|^\s*---\s*$|\Z)",
            section,
        )
        explanation_match = re.search(
            r"(?ims)^\s*why\s+it['’]?s\s+suspicious\s*:\s*(.*?)(?="
            r"^\s*---\s*$|^\s*overall\s+risk\s+assessment\b|\Z)",
            section,
        )
        quote = _clean_markdown(quote_match.group(1)).strip('"\' ') if quote_match else ""
        explanation = _clean_markdown(explanation_match.group(1)) if explanation_match else ""
        if not quote and not explanation:
            continue

        red_flags.append(
            {
                "number": number_match.group(1) if number_match else "",
                "category": category,
                "severity": severity_match.group(1).upper(),
                "quote": quote,
                "explanation": explanation,
            }
        )
    return red_flags


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
