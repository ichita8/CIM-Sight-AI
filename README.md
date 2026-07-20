# CIM-Sight AI

**Institutional Deal Intelligence  AI-Powered CIM Screener**

Built by Ichita Kawabata · Georgia College Early College

---

## What It Does

CIM-Sight AI automatically audits Confidential Information Memorandums (CIMs), surfacing hidden risks, math errors, and financial red flags the way a 20-year Managing Director actually would.

**6 Red Flag Categories:**
- Math Errors
- Aggressive Projections
- Customer Concentration Risk
- Debt & Liability Red Flags
- Management Language Tells
- Margin Inconsistencies

Each flag includes a **verbatim quote**, **severity rating** (HIGH / MEDIUM / LOW), and an **MD-level explanation**.

---

## Stack

| Component | Tool | Cost |
|-----------|------|------|
| PDF Extraction | Docling | Free |
| AI Model | Cerebras GPT-OSS-120B | Free |
| Dashboard | Streamlit | Free |

**Total operating cost: $0/run**

---

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the App
```bash
streamlit run app.py
```

### 3. Use It
- Open the app in your browser (usually `http://localhost:8501`)
- Upload any CIM PDF
- Click **Analyze CIM**

---

## Project Structure

```
cimsight/
app.py          # Streamlit dashboard
analyzer.py     # AI pipeline + Cynical MD prompt
index.html      # Landing page
requirements.txt
README.md
```

---

## Landing Page

Open `index.html` directly in a browser or host it on GitHub Pages for a live URL.

---

*For institutional analyst use only. Not financial advice.*
