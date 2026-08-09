from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import os


@dataclass
class ExperimentConfig:
    """Config-driven architecture. Each preset is one cell of the 2x2 factorial
    design: {Standard, PyMuPDF} parsing x {Generic, CIM-Sight} prompting.

    Temperature is held constant at 0.0 across all four conditions to minimize
    creativity/hallucination (a controlled constant in the experiment).
    """
    name: str = "default"
    parser: str = "pymupdf"            # "standard" | "pymupdf"
    prompt_style: str = "cim"          # "generic" | "cim"
    model: str = "gpt-oss-120b"
    base_url: str = "https://api.cerebras.ai/v1"
    api_key_env: str = "CEREBRAS_API_KEY"
    temperature: float = 0.0
    max_pages: int = 100
    chunk_size: int = 6000
    chunk_overlap: int = 400
    max_retries: int = 4
    base_backoff: float = 1.5
    verify_quotes: bool = True
    verify_explanations: bool = True
    scope_quote_to_paragraph: bool = True

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["api_key"] = "***" if self.api_key else ""
        return d


# 2x2 factorial design — the four experimental conditions.
PRESETS = {
    # Condition 1: Standard text + Generic prompt (full baseline)
    "baseline_standard_generic": ExperimentConfig(
        name="baseline_standard_generic", parser="standard", prompt_style="generic"),
    # Condition 2: Standard text + CIM-Sight prompt (prompting effect only)
    "prompt_only_standard_cim": ExperimentConfig(
        name="prompt_only_standard_cim", parser="standard", prompt_style="cim"),
    # Condition 3: PyMuPDF markdown + Generic prompt (parsing effect only)
    "parser_only_pymupdf_generic": ExperimentConfig(
        name="parser_only_pymupdf_generic", parser="pymupdf", prompt_style="generic"),
    # Condition 4: PyMuPDF markdown + CIM-Sight prompt (full CIM-Sight AI)
    "full_cim_sight": ExperimentConfig(
        name="full_cim_sight", parser="pymupdf", prompt_style="cim"),
}


def get_preset(name: str) -> ExperimentConfig:
    """Return a COPY of the preset so callers (e.g. the Streamlit sliders) cannot
    mutate the shared singleton stored in PRESETS."""
    if name not in PRESETS:
        raise ValueError("Unknown preset '%s'. Available: %s" % (name, list(PRESETS)))
    return replace(PRESETS[name])


def all_presets() -> list:
    """Return all available experiment preset names."""
    return list(PRESETS)
