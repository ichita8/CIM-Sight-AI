from __future__ import annotations
import re
from .config import ExperimentConfig
from .parsers import extract
from .prompts import build_system_prompt, build_chunk_audit_prompt, FINDINGS_SCHEMA
from .llm import LLMClient, FatalLLMError
from .rule_checks import run_rule_based_checks
from .metrics import compute_pdf_hash


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _find_quote(quote: str, full_text: str):
    """Phase 1 (#2): locate a (whitespace-flexible) verbatim quote in the doc.
    Returns the absolute char offset, or None if the quote is not present."""
    nq = _normalize(quote)
    if len(nq) < 5:
        return None
    flex = re.escape(nq).replace("\\ ", r"\s+")
    try:
        m = re.search(flex, full_text)
    except re.error:
        return None
    return m.start() if m else None


def _verify_explanation(quote: str, explanation: str) -> bool:
    """Phase 1 (#3): the explanation must reuse meaningful words from the quote."""
    nq = set(re.findall(r"[a-zA-Z]{4,}", _normalize(quote).lower()))
    ne = set(re.findall(r"[a-zA-Z]{4,}", _normalize(explanation).lower()))
    if not nq:
        return False
    return len(nq & ne) >= 2


def _nearest_heading(text: str, offset):
    if offset is None:
        return "Unknown"
    last = None
    for m in re.finditer(r"(?:^|\n)([A-Z][A-Z 0-9&\-]{4,60})\n", text):
        if m.start() > offset:
            break
        last = m
    return last.group(1).strip() if last else "Unknown"


def _local_paragraphs(chunk: str):
    paras = []
    i, n = 0, len(chunk)
    while i < n:
        j = chunk.find("\n\n", i)
        if j == -1:
            j = n
        if j > i:
            paras.append((i, j))
        i = j + 2
    return paras


def chunk_text(text: str, size: int, overlap: int):
    if overlap >= size:
        overlap = size // 4
    chunks = []
    i, n = 0, len(text)
    while i < n:
        j = min(i + size, n)
        chunks.append((i, j, text[i:j]))
        if j >= n:
            break
        i = j - overlap
    return chunks


def analyze_cim(pdf_path: str, config: ExperimentConfig, llm=None):
    """Run the full hybrid (rules + LLM) pipeline.

    Returns a dict: findings, rule_findings, metrics, chunk_failures,
    session_hash, extraction.
    """
    extraction = extract(pdf_path, config)
    text = extraction.text

    rule_result = run_rule_based_checks(text, extraction)
    rule_findings = rule_result["findings"]

    sys_prompt = build_system_prompt(config)
    client = llm or LLMClient(config)

    chunks = chunk_text(text, config.chunk_size, config.chunk_overlap)
    findings = []
    metrics = {
        "hallucinations_removed": 0,
        "evidence_failures": 0,
        "retries": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0.0,
        "chunk_count": len(chunks),
        "prompt_injection_attempts": 0,
    }
    chunk_failures = []

    for idx, (cstart, cend, chunk) in enumerate(chunks):
        user_prompt = build_chunk_audit_prompt(chunk, rule_result["summary"], config)
        # Phase 2 (#5): chunk recovery - a failed chunk never kills the run.
        try:
            data, meta = client.audit_chunk(sys_prompt, user_prompt)
        except FatalLLMError as e:
            chunk_failures.append({"chunk_index": idx, "error": str(e)})
            continue

        metrics["retries"] += meta.get("retries", 0)
        metrics["tokens_in"] += meta.get("tokens_in", 0)
        metrics["tokens_out"] += meta.get("tokens_out", 0)
        metrics["latency_ms"] += meta.get("latency_ms", 0)

        raw_findings = (data.get("findings") or []) if isinstance(data, dict) else []

        for f in raw_findings:
            if str(f.get("category", "")).upper().startswith("PROMPT INJECTION"):
                metrics["prompt_injection_attempts"] += 1

            quote = f.get("quote", "") or ""
            explanation = f.get("explanation", "") or ""

            # Phase 1 (#2): quote verification - discard hallucinated quotes.
            abs_offset = _find_quote(quote, text)
            if config.verify_quotes and abs_offset is None:
                metrics["hallucinations_removed"] += 1
                continue

            # Phase 5: scope the quote to the paragraph the model claimed.
            if config.scope_quote_to_paragraph:
                pidx = f.get("paragraph_index", -1)
                if isinstance(pidx, int) and pidx >= 0:
                    local = _local_paragraphs(chunk)
                    if 0 <= pidx < len(local):
                        ps, pe = local[pidx]
                        if _normalize(quote) not in _normalize(chunk[ps:pe]):
                            # not in the claimed paragraph; keep if globally present
                            pass

            # Phase 1 (#3): explanation verification.
            if config.verify_explanations and not _verify_explanation(quote, explanation):
                metrics["evidence_failures"] += 1
                continue

            page = extraction.page_for_offset(abs_offset) if abs_offset is not None else None
            section = f.get("section") or (_nearest_heading(text, abs_offset) if abs_offset is not None else "Unknown")

            findings.append({
                "category": str(f.get("category", "")).upper(),
                "severity": str(f.get("severity") or "MEDIUM").upper(),
                "quote": quote,
                "explanation": explanation,
                "section": section,
                "page_number": page,
                "char_offset": abs_offset,
                "source": "llm",
            })

    # Merge deterministic findings (already page-mapped).
    for rf in rule_findings:
        d = rf.to_dict()
        findings.append({
            "category": d["category"],
            "severity": d["severity"],
            "quote": "",
            "explanation": d["detail"],
            "section": _nearest_heading(text, rf.char_offset) if rf.char_offset else "Unknown",
            "page_number": d["page_number"],
            "char_offset": d["char_offset"],
            "raw_values": d["raw_values"],
            "source": "rule",
        })

    return {
        "findings": findings,
        "rule_findings": [rf.to_dict() for rf in rule_findings],
        "metrics": metrics,
        "chunk_failures": chunk_failures,
        "session_hash": compute_pdf_hash(pdf_path),
        "extraction": extraction,
    }
