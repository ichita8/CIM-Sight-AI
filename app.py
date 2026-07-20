import streamlit as st
import tempfile
import os
import re
import html as html_module
from analyzer import analyze_cim, get_severity_color, get_overall_risk

def md_to_html(text):
    """Convert simple markdown to safe HTML for rendering inside divs"""
    if not text:
        return ""
    text = html_module.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = text.replace('\n', '<br>')
    return text

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CIM-Sight AI — Forensic CIM Audit Engine",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────
# STYLING — obsidian / phosphor-gold forensic theme
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap');

    .stApp {
        background: #080A0E;
        color: #D4DCE9;
        font-family: 'Inter', sans-serif;
    }
    #MainMenu, footer, header { visibility: hidden; }

    .hero-title {
        font-size: 42px; font-weight: 900; letter-spacing: -0.03em;
        color: #D4DCE9; margin-bottom: 4px; line-height: 1.1;
    }
    .hero-title .gold { color: #C9A84C; }
    .hero-sub {
        font-family: 'JetBrains Mono', monospace; font-size: 12px;
        letter-spacing: 0.15em; color: #C9A84C; text-transform: uppercase;
        margin-bottom: 8px;
    }
    .hero-desc { font-size: 15px; color: #64748B; max-width: 640px; line-height: 1.7; }

    .status-strip {
        font-family: 'JetBrains Mono', monospace; font-size: 11px;
        letter-spacing: 0.05em; color: #64748B; margin: 16px 0 24px;
    }
    .status-strip .live { color: #3DD68C; }

    .flag-card {
        border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
        overflow: hidden; margin-bottom: 16px; background: #0F1117;
    }
    .flag-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 14px 20px; border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .cat-badge {
        font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700;
        letter-spacing: 0.12em; text-transform: uppercase; padding: 4px 10px;
        border-radius: 4px; background: rgba(201,168,76,0.15); color: #C9A84C;
    }
    .sev-badge {
        font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700;
        letter-spacing: 0.1em; padding: 4px 10px; border-radius: 4px;
    }
    .flag-quote {
        font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #64748B;
        border-left: 3px solid #C9A84C; padding: 10px 16px;
        background: rgba(201,168,76,0.05); border-radius: 0 6px 6px 0;
        margin: 0 20px 14px; line-height: 1.6;
    }
    .flag-analysis { font-size: 13px; color: #B0BAC9; line-height: 1.7; padding: 0 20px 18px; }

    .verified-box {
        border: 1px solid rgba(0,245,160,0.25); border-radius: 12px;
        background: rgba(0,245,160,0.04); padding: 18px 22px; margin-bottom: 24px;
    }
    .verified-title {
        font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700;
        letter-spacing: 0.1em; color: #3DD68C; text-transform: uppercase; margin-bottom: 12px;
    }
    .verified-item { font-size: 13px; color: #B0BAC9; line-height: 1.7; margin-bottom: 6px; }

    .risk-banner {
        border-radius: 12px; padding: 22px 26px; margin: 8px 0 24px;
        font-size: 14px; line-height: 1.7;
    }

    div.stButton > button {
        background: #C9A84C; color: #080A0E; font-weight: 800;
        letter-spacing: 0.05em; border: none; border-radius: 8px;
        padding: 12px 28px; font-size: 14px;
    }
    div.stButton > button:hover { background: #F0C060; color: #080A0E; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────
st.markdown('<div class="hero-sub">Institutional Deal Intelligence · Beta</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">CIM-Sight AI — <span class="gold">The Cynical MD Engine</span></div>', unsafe_allow_html=True)
st.markdown('<div class="hero-desc">Upload a Confidential Information Memorandum. A deterministic arithmetic engine verifies every margin and growth claim, then a 120B-parameter LLM hunts for hidden risks, aggressive projections, and management-language tells — the way a 20-year Managing Director would.</div>', unsafe_allow_html=True)
st.markdown('<div class="status-strip">MODEL: GPT-OSS-120B &nbsp;·&nbsp; ENGINE: CYNICAL MD v1.0 + ARITHMETIC CHECKER &nbsp;·&nbsp; STATUS: <span class="live">● LIVE</span></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# API KEY - read from Streamlit Secrets (no user input needed)
# ─────────────────────────────────────────────────────────────
api_key = None
try:
    api_key = st.secrets["CEREBRAS_API_KEY"]
except Exception:
    api_key = os.environ.get("CEREBRAS_API_KEY")

if not api_key:
    api_key = st.text_input(
        "Cerebras API Key",
        type="password",
        placeholder="csk-...",
        help="Get a free key at cloud.cerebras.ai. Stored only for this session.",
    )

# ─────────────────────────────────────────────────────────────
# FILE UPLOAD
# ─────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader("Upload CIM (PDF)", type=["pdf"], label_visibility="collapsed")

col_a, col_b = st.columns([1, 4])
with col_a:
    analyze_clicked = st.button("🔍 ANALYZE CIM", use_container_width=True)

# ─────────────────────────────────────────────────────────────
# RUN ANALYSIS
# ─────────────────────────────────────────────────────────────
if analyze_clicked:
    if not api_key:
        st.error("Cerebras API key not found. Add CEREBRAS_API_KEY to Streamlit Secrets.")
    elif not uploaded_file:
        st.error("Please upload a CIM PDF first.")
    else:
        with st.spinner("Extracting document → running arithmetic checks → activating MD Engine..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            try:
                results = analyze_cim(tmp_path, api_key=api_key)
                st.session_state["results"] = results
            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")
            finally:
                os.unlink(tmp_path)

# ─────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────
if "results" in st.session_state:
    results = st.session_state["results"]
    red_flags = results.get("red_flags", [])
    rule_findings = results.get("rule_findings", [])

    st.markdown("---")

    # Metrics row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Red Flags", len(red_flags))
    c2.metric("Verified Math Issues", len(rule_findings))
    high_count = len([f for f in red_flags if "HIGH" in f.get("severity", "").upper()])
    c3.metric("High Severity", high_count)
    c4.metric("Chars Analyzed", f"{results.get('text_length', 0):,}")

    if results.get('text_length', 0) >= 100000:
        st.warning("This document exceeded the 100,000 character analysis limit. The engine processed the first 100k characters. For complete coverage, consider splitting the PDF or deleting unnecessary parts.")

    # ── Deterministic engine findings (verified, no LLM) ──
    if rule_findings:
        items_html = "".join(
            f'<div class="verified-item"><b>[{f["severity"]}] {f["category"]}</b> — {f["detail"]}</div>'
            for f in rule_findings
        )
        st.markdown(
            f'<div class="verified-box"><div class="verified-title">✓ Verified by Arithmetic Engine (deterministic, no AI)</div>{items_html}</div>',
            unsafe_allow_html=True,
        )

    # ── Overall risk assessment ──
    overall = get_overall_risk(results.get("raw_analysis", ""))
    if overall:
        st.markdown(
            f'<div style="background: #14161C; border: 1px solid rgba(201,168,76,0.3); border-radius: 8px; padding: 20px; margin: 16px 0;">'
            f'<div style="font-family: monospace; font-size: 11px; font-weight: bold; letter-spacing: 0.1em; color: #C9A84C; text-transform: uppercase; margin-bottom: 12px;">Overall Risk Assessment</div>'
            f'<div style="font-size: 14px; line-height: 1.7; color: #B0BAC9;">{md_to_html(overall)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Red flags ──
    st.markdown("### 🚨 Red Flags")
    if not red_flags:
        st.info("No structured red flags parsed. See raw analysis below.")
    for flag in red_flags:
        sev = flag.get("severity", "MEDIUM").upper()
        sev_color = get_severity_color(sev)
        category = flag.get("category", "UNKNOWN")
        quote = md_to_html(flag.get("quote", "No quote extracted."))
        explanation = md_to_html(flag.get("explanation", ""))
        
        st.markdown(
            f'<div style="background: #14161C; border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; overflow: hidden; margin-bottom: 16px;">'
            f'<div style="display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid rgba(255,255,255,0.07); flex-wrap: wrap; gap: 8px;">'
            f'<span style="font-family: monospace; font-size: 10px; font-weight: bold; letter-spacing: 0.12em; text-transform: uppercase; padding: 4px 10px; border-radius: 4px; background: rgba(201,168,76,0.15); color: #C9A84C;">{html_module.escape(category)}</span>'
            f'<span style="font-family: monospace; font-size: 10px; font-weight: bold; letter-spacing: 0.1em; padding: 4px 10px; border-radius: 4px; background: rgba(255,255,255,0.05); color: {sev_color};">{sev}</span>'
            f'</div>'
            f'<div style="padding: 20px;">'
            f'<div style="font-family: monospace; font-size: 12px; color: #B0BAC9; border-left: 3px solid #C9A84C; padding: 10px 16px; background: rgba(201,168,76,0.05); border-radius: 0 6px 6px 0; margin-bottom: 16px; line-height: 1.6;">{quote}</div>'
            f'<div style="font-size: 13px; line-height: 1.7; color: #B0BAC9;">{explanation}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Raw output ──
    with st.expander("View Raw MD Engine Output"):
        st.text(results.get("raw_analysis", ""))

# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div style="font-family:JetBrains Mono,monospace; font-size:11px; color:#4A5568; text-align:center;">'
    'CIM-SIGHT AI · Built by Ichita Kawabata · For Institutional Analyst Use Only · Not Financial Advice'
    '</div>',
    unsafe_allow_html=True,
)
