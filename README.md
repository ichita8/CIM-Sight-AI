# CIM-Sight AI v2.0

**Institutional Deal Intelligence — AI-Powered CIM Screener**

Built by Ichita Kawabata · Georgia College Early College

> For institutional analyst use only. Not financial advice.

---

## What It Does

CIM-Sight AI audits Confidential Information Memorandums (CIMs) and surfaces
hidden risks, math errors, and financial red flags the way a 20-year Managing
Director actually would — then grounds every finding in a verbatim quote and a
deterministic arithmetic check.

### v2.0 architecture (research-grade reliability)

- **Config-driven** — every run is fully specified by an `ExperimentConfig`
  (parser, prompt style, model, temperature, chunk size, verification gates).
- **Prompt-injection defense** — the system prompt is fixed and never contains
  document text; the document only appears inside `<DOCUMENT>` tags in the
  user message, so the model treats it as untrusted data.
- **Quote verification** — every LLM flag's quote is located in the extracted
  text; hallucinated quotes are discarded and counted.
- **Explanation verification** — the explanation must reuse meaningful words
  from the quote, or the flag is dropped.
- **Absolute-offset provenance** — each finding maps back to a page number via
  char-offset → source-span lookup (no fuzzy guessing).
- **Chunk recovery** — a failed LLM chunk is logged and skipped; it never
  kills the whole run.
- **Experiment logging** — every run is written to `experiments/logs/` with
  config, git commit, file hash, and metrics for reproducibility.

### 6 Red Flag Categories

1. Math Errors
2. Aggressive Projections
3. Customer Concentration Risk
4. Management Language Tells
5. Disclosure Gaps
6. Prompt Injection (text attempting to alter model behavior)

Each flag includes a **verbatim quote**, **severity rating** (HIGH / MEDIUM / LOW),
**section**, **page number**, and an **MD-level explanation**.

---

## Stack

| Component | Tool | Cost |
| --- | --- | --- |
| PDF Extraction | PyMuPDF | Free |
| AI Model | Cerebras GPT-OSS-120B | Free |
| Dashboard | Streamlit | Free |
| Experiment Logging | Local JSON | Free |

**Total operating cost: $0 / run**

---

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```
### 2. Set your Cerebras API key
Either add it to .streamlit/secrets.toml:

CEREBRAS_API_KEY = "your-key-here"
…or paste it into the app's API-key field at runtime.

### 3. Run the App
streamlit run app.py

### 4. Run the Tests
pip install -r requirements-dev.txt
pytest
