from __future__ import annotations
from dataclasses import dataclass, asdict
import os


@dataclass
class ExperimentConfig:
    """Phase 4: config-driven architecture. Every run is fully specified here."""
    name: str = "default"
    parser: str = "pymupdf"            # "pymupdf" | "docling"
    prompt_style: str = "cim"          # "generic" | "cim"
    model: str = "gpt-oss-120b"
    base_url: str = "https://api.cerebras.ai/v1"
    api_key_env: str = "CEREBRAS_API_KEY"
    temperature: float = 0.2
    max_pages: int = 100
    chunk_size: int = 6000
    chunk_overlap: int = 400
    # Phase 2: reliability
    max_retries: int = 4
    base_backoff: float = 1.5
    # Phase 1: verification gates
    verify_quotes: bool = True
    verify_explanations: bool = True
    # Phase 5: source grounding
    scope_quote_to_paragraph: bool = True

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["api_key"] = "***" if self.api_key else ""
        return d


_PRESETS = {
    "cim_pymupdf": ExperimentConfig(name="cim_pymupdf", parser="pymupdf", prompt_style="cim"),
    "cim_docling": ExperimentConfig(name="cim_docling", parser="docling", prompt_style="cim"),
    "generic_pymupdf": ExperimentConfig(name="generic_pymupdf", parser="pymupdf", prompt_style="generic"),
    "cim_low_temp": ExperimentConfig(name="cim_low_temp", parser="pymupdf", prompt_style="cim", temperature=0.0),
}


def get_preset(name: str) -> ExperimentConfig:
    if name not in _PRESETS:
        raise ValueError("Unknown preset '%s'. Available: %s" % (name, list(_PRESETS)))
    return _PRESETS[name]


def all_presets() -> list:
    return list(_PRESETS)
