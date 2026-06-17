# CIM-Sight AI

**Institutional Deal Intelligence â€” AI-Powered CIM Screener**

Built by Ichita Kawabata Â· Georgia College Early College

---

## What It Does

CIM-Sight AI automatically audits Confidential Information Memorandums (CIMs), surfacing hidden risks, math errors, and financial red flags â€” the way a 20-year Managing Director actually would.

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
| PDF Extraction | PyMuPDF4LLM | Free |
| AI Model | Llama 3.3 70B via Groq | Free |
| Dashboard | Streamlit | Free |

**Total operating cost: $0/run**

---

## Setup

### 1. Get a Free Groq API Key
- Go to [console.groq.com](https://console.groq.com)
- Sign up (no credit card required)
- Click **API Keys** â†’ **Create API Key**
- Copy the key (starts with `gsk_...`)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the App
```bash
streamlit run app.py
```

### 4. Use It
- Open the app in your browser (usually `http://localhost:8501`)
- Paste your Groq API key in the sidebar
- Upload any CIM PDF
- Click **Analyze CIM**

---

## Project Structure

```
cimsight/
â”œâ”€â”€ app.py          # Streamlit dashboard
â”œâ”€â”€ analyzer.py     # AI pipeline + Cynical MD prompt
â”œâ”€â”€ index.html      # Landing page
â”œâ”€â”€ requirements.txt
â””â”€â”€ README.md
```

---

## Landing Page

Open `index.html` directly in a browser â€” or host it on GitHub Pages for a live URL.

---

*For institutional analyst use only. Not financial advice.*
