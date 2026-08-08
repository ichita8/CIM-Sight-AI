"""Streamlit interface for CIM-Sight AI v2.0 (config-driven pipeline)."""
from __future__ import annotations
import html
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from cim_sight_pipeline import analyze_cim
from cim_sight_pipeline.config import ExperimentConfig, get_preset, all_presets
from cim_sight_pipeline.metrics import ExperimentLogger


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
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


def _severity_color(severity: str) -> str:
    return {
        "HIGH": "#ef4444",
        "CRITICAL": "#b91c1c",
        "MEDIUM": "#fbbf24",
        "LOW": "#60a5fa",
    }.get((severity or "").upper(), "#94a3b8")


def _overall_risk(findings: list) -> str:
    high = sum(1 for f in findings if f.get("severity", "").upper() in {"HIGH", "CRITICAL"})
    med = sum(1 for f in findings if f.get("severity", "").upper() == "MEDIUM")
    if high >= 3:
        return "CRITICAL"
    if high >= 1:
        return "HIGH"
    if med >= 2:
        return "MEDIUM"
    return "LOW"


def _format_provenance(item: dict) -> str:
    parts = []
    if item.get("page_number") is not None:
        parts.append(f"p.{item['page_number']}")
    if item.get("section") and item.get("section") != "Unknown":
        parts.append(str(item["section"]))
    if item.get("char_offset") is not None:
        parts.append(f"offset {item['char_offset']}")
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
            "source": flag.get("source"),
        }
    )


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="CIM-Sight AI v2.0 — Forensic CIM Audit Engine",
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
    '<div class="hero-title">CIM-Sight AI v2.0 — <span class="gold">The Cynical MD Engine</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="subtle">2×2 factorial experiment: {Standard, PyMuPDF} parsing × '
    "{Generic, CIM-Sight} prompting · T=0.0 · prompt-injection defense · quote "
    'verification · absolute-offset provenance.</p>',
    unsafe_allow_html=True,
)

# --- API key ---------------------------------------------------------------
configured_key = _load_api_key()
if configured_key:
    os.environ["CEREBRAS_API_KEY"] = configured_key
    st.caption("Cerebras API key loaded from secure configuration.")
else:
    key_input = st.text_input(
        "Cerebras API Key",
        type="password",
        placeholder="Paste a Cerebras API key",
        help="Used only for this analysis request; it is not written to disk.",
    )
    if key_input:
        os.environ["CEREBRAS_API_KEY"] = key_input

# --- Config selector ------------------------------------------------------
preset_names = all_presets()
preset_choice = st.selectbox("Experiment preset", preset_names, index=0)
cfg = get_preset(preset_choice)

left, mid, right = st.columns([1, 1, 2])
with left:
    cfg.max_pages = st.number_input("Pages to analyze", min_value=1, max_value=500, value=100, step=1)
with mid:
    cfg.temperature = st.slider("Temperature", 0.0, 1.0, cfg.temperature, 0.1)
with right:
    analyze_clicked = st.button("🔍 ANALYZE CIM", use_container_width=True)

uploaded_file = st.file_uploader("Upload CIM (PDF)", type=["pdf"])

if analyze_clicked:
    if not os.environ.get("CEREBRAS_API_KEY"):
        st.error("Add a Cerebras API key before running the analysis.")
    elif uploaded_file is None:
        st.error("Upload a CIM PDF first.")
    else:
        temporary_path: Path | None = None
        with st.spinner("Extracting PDF → deterministic checks → chunked LLM audit..."):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    temporary_path = Path(tmp.name)
                results = analyze_cim(temporary_path, cfg)
                st.session_state["results"] = results
                st.session_state["feedback_log"] = []
                ExperimentLogger().log(cfg, results)
            except Exception as exc:
                st.session_state.pop("results", None)
                st.error(f"Analysis failed: {exc}")
            finally:
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink()

results = st.session_state.get("results")
if results:
    st.markdown("---")
    findings = results["findings"]
    rule_findings = results["rule_findings"]
    metrics = results["metrics"]
    chunk_failures = results.get("chunk_failures", [])

    m = st.columns(6)
    m[0].metric("Total Flags", len(findings))
    m[1].metric("Rule-Verified", len(rule_findings))
    m[2].metric("High Severity", sum(f["severity"] in {"HIGH", "CRITICAL"} for f in findings))
    m[3].metric("Chunks", metrics.get("chunk_count", 1))
    m[4].metric("Hallucinations Filtered", metrics.get("hallucinations_removed", 0))
    m[5].metric("Injection Attempts", metrics.get("prompt_injection_attempts", 0))

    with st.expander("Run metrics & reliability"):
        mc = st.columns(4)
        mc[0].metric("LLM Retries", metrics.get("retries", 0))
        mc[1].metric("Tokens In", metrics.get("tokens_in", 0))
        mc[2].metric("Tokens Out", metrics.get("tokens_out", 0))
        mc[3].metric("Latency (s)", round(metrics.get("latency_ms", 0) / 1000, 1))
        st.caption(f"Session hash: `{results.get('session_hash')}` · Evidence failures: {metrics.get('evidence_failures', 0)}")
        if chunk_failures:
            st.warning(f"{len(chunk_failures)} chunk(s) failed and were skipped:")
            st.json(chunk_failures)

    if rule_findings:
        st.subheader("Verified arithmetic findings (deterministic)")
        for rf in rule_findings:
            st.markdown(
                f"**{_to_safe_html(rf['severity'])} · {_to_safe_html(rf['category'])}** — "
                f"{_to_safe_html(rf['detail'])}",
                unsafe_allow_html=True,
            )

    risk = _overall_risk(findings)
    st.subheader("Overall risk assessment")
    st.markdown(
        f'<span style="color:{_severity_color(risk)};font-weight:700;font-size:20px">'
        f"{_to_safe_html(risk)}</span> · "
        f"{len(findings)} flag(s) across {metrics.get('chunk_count', 1)} chunk(s).",
        unsafe_allow_html=True,
    )

    st.subheader("Red flags")
    llm_flags = [f for f in findings if f.get("source") == "llm"]
    if not llm_flags:
        st.info("No LLM flags were returned. Review rule findings above or the run metrics.")
    for index, flag in enumerate(llm_flags):
        severity = flag["severity"]
        st.markdown(
            f'<div class="flag-card"><b>{_to_safe_html(flag["category"])}</b> '
            f'<span style="color:{_severity_color(severity)}">{_to_safe_html(severity)}</span><br><br>'
            f'<div class="quote">{_to_safe_html(flag.get("quote") or "No quote extracted.")}</div><br>'
            f'{_to_safe_html(flag.get("explanation") or "")}<br>'
            f'<span class="meta">{_to_safe_html(_format_provenance(flag))} · source: {flag.get("source")}</span>'
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

st.markdown("---")
st.caption("CIM-SIGHT AI v2.0 · For institutional analyst use only · Not financial advice")
