"""Streamlit interface for the CIM-Sight AI document audit."""
from __future__ import annotations
import html
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st
from analyzer import analyze_cim, get_overall_risk
def _to_safe_html(text: object) -> str:
    return html.escape(str(text or "")).replace("\n", "<br>")
def _load_api_key() -> str | None:
    try:
        value = st.secrets.get("CEREBRAS_API_KEY")
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get("CEREBRAS_API_KEY")
def _format_provenance(item: dict) -> str:
    parts = []
    if item.get("page_number") is not None:
        parts.append(f"p.{item['page_number']}")
    if item.get("table_id"):
        parts.append(f"table {item['table_id']}")
    if item.get("paragraph_id"):
        parts.append(f"para {item['paragraph_id']}")
    if item.get("ocr_confidence") is not None:
        parts.append(f"OCR {item['ocr_confidence']:.0%}")
    if item.get("parse_quality") == "partial":
        parts.append("partial parse")
    return " · ".join(parts) if parts else "provenance unavailable"
def _record_feedback(flag: dict, verdict: str) -> None:
    st.session_state.setdefault("feedback_log", []).append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict,
            "category": flag.get("category"),
            "severity": flag.get("severity"),
            "quote": flag.get("quote"),
            "explanation": flag.get("explanation"),
            "page_number": flag.get("page_number"),
            "table_id": flag.get("table_id"),
            "paragraph_id": flag.get("paragraph_id"),
        }
    )
st.set_page_config(
    page_title="CIM-Sight AI — Forensic CIM Audit Engine",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
        .stApp { background: #080A0E; color: #D4DCE9; }
        #MainMenu, footer, header { visibility: hidden; }
        .hero-title { font-size: 42px; font-weight: 800; color: #D4DCE9; }
        .gold { color: #C9A84C; }
        .subtle { color: #94A3B8; line-height: 1.6; }
        .flag-card { background: #14161C; border: 1px solid rgba(255,255,255,.10);
                     border-radius: 12px; padding: 18px 20px; margin: 12px 0; }
        .quote { border-left: 3px solid #C9A84C; padding: 10px 14px;
                 color: #B0BAC9; background: rgba(201,168,76,.05); }
        .meta { color: #718096; font-size: 0.85rem; margin-top: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="hero-title">CIM-Sight AI — <span class="gold">The Cynical MD Engine</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="subtle">PyMuPDF extracts tables and scanned text when needed. '
    'Deterministic checks run on the full document before chunked LLM review.</p>',
    unsafe_allow_html=True,
)
configured_key = _load_api_key()
if configured_key:
    api_key = configured_key
    st.caption("Cerebras API key loaded from secure configuration.")
else:
    api_key = st.text_input(
        "Cerebras API Key",
        type="password",
        placeholder="Paste a Cerebras API key",
        help="Used only for this analysis request; it is not written to disk.",
    )
uploaded_file = st.file_uploader("Upload CIM (PDF)", type=["pdf"])
left, right = st.columns([1, 3])
with left:
    max_pages = st.number_input("Pages to analyze", min_value=1, max_value=500, value=100, step=1)
with right:
    analyze_clicked = st.button("🔍 ANALYZE CIM", use_container_width=True)
if analyze_clicked:
    if not api_key:
        st.error("Add a Cerebras API key before running the analysis.")
    elif uploaded_file is None:
        st.error("Upload a CIM PDF first.")
    else:
        temporary_path: Path | None = None
        with st.spinner("PyMuPDF → full-document math checks → chunked LLM audit..."):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temporary_file:
                    temporary_file.write(uploaded_file.getvalue())
                    temporary_path = Path(temporary_file.name)
                st.session_state["results"] = analyze_cim(
                    temporary_path,
                    api_key=api_key,
                    max_pages=int(max_pages),
                )
                st.session_state["feedback_log"] = []
            except Exception as exc:
                st.session_state.pop("results", None)
                st.error(f"Analysis failed: {exc}")
            finally:
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink()
results = st.session_state.get("results")
if results:
    st.markdown("---")
    red_flags = results["red_flags"]
    rule_findings = results["rule_findings"]
    metrics = st.columns(5)
    metrics[0].metric("Red Flags", len(red_flags))
    metrics[1].metric("Verified Math", len(rule_findings))
    metrics[2].metric("High Severity", sum(f["severity"] in {"HIGH", "CRITICAL"} for f in red_flags))
    metrics[3].metric("Chunks", results.get("chunks_analyzed", 1))
    metrics[4].metric("Tables Parsed", results.get("table_count", 0))
    if results.get("used_ocr"):
        st.info("Scanned PDF detected — OCR was enabled for extraction.")
    if results.get("was_truncated"):
        st.warning(
            f"Document analyzed in {results.get('chunks_analyzed', 1)} overlapping chunk(s). "
            f"Full extracted length: {results['source_text_length']:,} characters."
        )
        with st.expander("Chunk coverage details"):
            st.json(results.get("chunk_ranges", []))
    if rule_findings:
        st.subheader("Verified arithmetic findings")
        for finding in rule_findings:
            st.markdown(
                f"**{_to_safe_html(finding['severity'])} · "
                f"{_to_safe_html(finding['category'])}** — "
                f"{_to_safe_html(finding['detail'])}<br>"
                f'<span class="meta">{_to_safe_html(_format_provenance(finding))}</span>',
                unsafe_allow_html=True,
            )
    overall_risk = get_overall_risk(results["raw_analysis"])
    if overall_risk:
        st.subheader("Overall risk assessment")
        st.markdown(_to_safe_html(overall_risk), unsafe_allow_html=True)
    st.subheader("Red flags")
    if not red_flags:
        st.info("No structured flags were parsed. Review the raw model output below.")
    for index, flag in enumerate(red_flags):
        severity = flag["severity"]
        st.markdown(
            f'<div class="flag-card"><b>{_to_safe_html(flag["category"])}</b> '
            f'<span style="color:{get_severity_color(severity)}">{_to_safe_html(severity)}</span><br><br>'
            f'<div class="quote">{_to_safe_html(flag.get("quote") or "No quote extracted.")}</div><br>'
            f'{_to_safe_html(flag.get("explanation") or "")}<br>'
            f'<span class="meta">{_to_safe_html(_format_provenance(flag))}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        fb_left, fb_right, _ = st.columns([1, 1, 4])
        if fb_left.button("Confirm flag", key=f"confirm_{index}"):
            _record_feedback(flag, "confirmed")
            st.toast("Flag confirmed.")
        if fb_right.button("False positive", key=f"reject_{index}"):
            _record_feedback(flag, "false_positive")
            st.toast("Marked as false positive.")
    feedback_log = st.session_state.get("feedback_log", [])
    if feedback_log:
        st.download_button(
            "Download feedback JSON",
            data=json.dumps(feedback_log, indent=2),
            file_name="cim_sight_feedback.json",
            mime="application/json",
        )
    with st.expander("View raw MD Engine output"):
        st.text(results["raw_analysis"])
st.markdown("---")
st.caption("CIM-SIGHT AI · For institutional analyst use only · Not financial advice")
