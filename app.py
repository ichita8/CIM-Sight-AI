import streamlit as st
import tempfile
import os
from analyzer import analyze_cim, get_severity_color, get_overall_risk

# Page config
st.set_page_config(
    page_title="CIM-Sight AI",
    page_icon="ðŸ”",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%);
        padding: 2.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        border: 1px solid #2a2a4a;
    }
    
    .main-title {
        font-size: 2.8rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: -1px;
        margin: 0;
    }
    
    .main-subtitle {
        color: #8892b0;
        font-size: 1rem;
        margin-top: 0.5rem;
        font-weight: 400;
    }
    
    .badge {
        display: inline-block;
        background: #0f3460;
        color: #4fc3f7;
        padding: 0.2rem 0.8rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-top: 0.8rem;
        border: 1px solid #1565c0;
    }

    .red-flag-card {
        background: #0d1117;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1.2rem;
        border-left: 4px solid;
        border-top: 1px solid #21262d;
        border-right: 1px solid #21262d;
        border-bottom: 1px solid #21262d;
    }
    
    .flag-header {
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 0.5rem;
    }
    
    .flag-category {
        font-size: 1.1rem;
        font-weight: 600;
        color: #e6edf3;
        margin-bottom: 1rem;
    }
    
    .severity-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-bottom: 1rem;
    }
    
    .quote-box {
        background: #161b22;
        border-left: 3px solid #58a6ff;
        padding: 0.8rem 1rem;
        border-radius: 0 6px 6px 0;
        margin: 0.8rem 0;
        font-style: italic;
        color: #8b949e;
        font-size: 0.9rem;
        line-height: 1.6;
    }
    
    .explanation-text {
        color: #c9d1d9;
        font-size: 0.92rem;
        line-height: 1.7;
        margin-top: 0.8rem;
    }
    
    .risk-summary {
        background: linear-gradient(135deg, #1a0a0a, #2d1515);
        border: 1px solid #5c1a1a;
        border-radius: 10px;
        padding: 1.5rem;
        margin-top: 2rem;
    }
    
    .stats-row {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    
    .stat-card {
        background: #0d1117;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 1rem 1.5rem;
        text-align: center;
        flex: 1;
    }
    
    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
    }
    
    .stat-label {
        font-size: 0.75rem;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .upload-area {
        border: 2px dashed #30363d;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        background: #0d1117;
        margin-bottom: 1rem;
    }
    
    div[data-testid="stFileUploader"] {
        background: #0d1117;
        border-radius: 10px;
    }

    .stButton > button {
        background: linear-gradient(135deg, #1565c0, #0d47a1);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 2rem;
        font-weight: 600;
        font-size: 0.95rem;
        width: 100%;
        transition: all 0.2s;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, #1976d2, #1565c0);
        transform: translateY(-1px);
    }
    
    .section-divider {
        border: none;
        border-top: 1px solid #21262d;
        margin: 2rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <div class="main-title">ðŸ” CIM-Sight AI</div>
    <div class="main-subtitle">AI-Powered Private Market Deal Screener â€” Built for IB & PE Workflows</div>
    <div class="badge">CYNICAL MD ENGINE v1.0</div>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### âš™ï¸ Configuration")
    api_key = st.text_input(
        "Groq API Key",
        type="password",
        placeholder="gsk_...",
        help="Free API key from console.groq.com â€” no credit card needed"
    )
    
    st.markdown("---")
    st.markdown("### ðŸ“‹ How It Works")
    st.markdown("""
    1. **Upload** your CIM (PDF)
    2. **AI extracts** all financial tables and key text
    3. **Cynical MD Engine** hunts for red flags
    4. **Review** flagged items with severity scores
    """)
    
    st.markdown("---")
    st.markdown("### ðŸŽ¯ Red Flag Categories")
    categories = [
        ("ðŸ”¢", "Math Errors"),
        ("ðŸ“ˆ", "Aggressive Projections"),
        ("ðŸ‘¥", "Customer Concentration"),
        ("ðŸ’³", "Debt & Liabilities"),
        ("ðŸ—£ï¸", "Management Language"),
        ("ðŸ“Š", "Margin Inconsistencies"),
    ]
    for emoji, cat in categories:
        st.markdown(f"{emoji} {cat}")

# Main content
col1, col2 = st.columns([3, 2])

with col1:
    st.markdown("### ðŸ“„ Upload CIM Document")
    uploaded_file = st.file_uploader(
        "Drop your CIM here",
        type=["pdf"],
        help="Upload a Confidential Information Memorandum in PDF format"
    )
    
    if uploaded_file:
        file_size = len(uploaded_file.getvalue()) / (1024 * 1024)
        st.success(f"âœ… **{uploaded_file.name}** uploaded ({file_size:.1f} MB)")

with col2:
    st.markdown("### ðŸš€ Run Analysis")
    st.markdown("The Cynical MD Engine will hunt for hidden risks, math errors, and financial red flags.")
    
    analyze_btn = st.button("ðŸ” Analyze CIM", disabled=not (uploaded_file and api_key))
    
    if not api_key:
        st.warning("âš ï¸ Add your API key in the sidebar to begin")
    elif not uploaded_file:
        st.info("ðŸ“Ž Upload a CIM PDF to get started")

st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

# Analysis
if analyze_btn and uploaded_file and api_key:
    with st.spinner("ðŸ” Cynical MD Engine analyzing your CIM... This takes 30-60 seconds."):
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name
            
            # Run analysis
            results = analyze_cim(tmp_path, api_key)
            os.unlink(tmp_path)
            
            # Store in session state
            st.session_state["results"] = results
            st.session_state["filename"] = uploaded_file.name
            
        except Exception as e:
            st.error(f"âŒ Analysis failed: {str(e)}")

# Display results
if "results" in st.session_state:
    results = st.session_state["results"]
    red_flags = results.get("red_flags", [])
    
    # Stats row
    high_count = sum(1 for f in red_flags if "HIGH" in f.get("severity", "").upper() or "CRITICAL" in f.get("severity", "").upper())
    med_count = sum(1 for f in red_flags if "MEDIUM" in f.get("severity", "").upper())
    low_count = sum(1 for f in red_flags if "LOW" in f.get("severity", "").upper())
    
    st.markdown(f"## ðŸ“Š Analysis Results â€” {st.session_state.get('filename', 'CIM')}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ðŸš¨ Total Red Flags", len(red_flags))
    c2.metric("ðŸ”´ High Severity", high_count)
    c3.metric("ðŸŸ¡ Medium Severity", med_count)
    c4.metric("ðŸŸ¢ Low Severity", low_count)
    
    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)
    
    # Tab layout
    tab1, tab2 = st.tabs(["ðŸš¨ Red Flags", "ðŸ“ Full Analysis"])
    
    with tab1:
        if red_flags:
            # Sort by severity
            severity_order = {"HIGH": 0, "CRITICAL": 0, "MEDIUM": 1, "LOW": 2}
            sorted_flags = sorted(red_flags, key=lambda x: severity_order.get(x.get("severity", "MEDIUM").upper().split()[0], 1))
            
            for flag in sorted_flags:
                severity = flag.get("severity", "MEDIUM").upper()
                color = get_severity_color(severity)
                
                # Severity badge color
                if "HIGH" in severity or "CRITICAL" in severity:
                    badge_bg = "#3d0000"
                    badge_color = "#ff6b6b"
                elif "MEDIUM" in severity:
                    badge_bg = "#3d2000"
                    badge_color = "#ffaa00"
                else:
                    badge_bg = "#1a1a00"
                    badge_color = "#ffd700"
                
                st.markdown(f"""
                <div class="red-flag-card" style="border-left-color: {color};">
                    <div class="flag-header" style="color: {color};">ðŸš¨ RED FLAG #{flag.get('number', '?')}</div>
                    <div class="flag-category">{flag.get('category', 'UNKNOWN')}</div>
                    <div class="severity-badge" style="background: {badge_bg}; color: {badge_color};">
                        â— {severity}
                    </div>
                    <div class="quote-box">"{flag.get('quote', 'No direct quote available')}"</div>
                    <div class="explanation-text"><strong>Why It's Suspicious:</strong><br>{flag.get('explanation', '')}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No structured red flags were parsed. See the Full Analysis tab for raw output.")
    
    with tab2:
        # Overall risk assessment highlight
        overall = get_overall_risk(results.get("raw_analysis", ""))
        if overall:
            st.markdown(f"""
            <div class="risk-summary">
                <h3 style="color: #ff6b6b; margin-top: 0;">âš ï¸ OVERALL RISK ASSESSMENT</h3>
                <div style="color: #c9d1d9; line-height: 1.8; font-size: 0.95rem;">{overall.replace('OVERALL RISK ASSESSMENT', '').strip()}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("**Full Raw Analysis Output:**")
        st.text_area("", value=results.get("raw_analysis", ""), height=600, label_visibility="collapsed")
