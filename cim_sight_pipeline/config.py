from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExperimentConfig:
    """
    Central configuration for a CIM-Sight AI analysis run.

    Current production configuration:
        parser:
            "pymupdf"

        prompt:
            "generic" or "cim_sight"
    """

    # ------------------------------------------------------------------
    # Core experiment variables
    # ------------------------------------------------------------------

    parser: str = "pymupdf"
    prompt: str = "cim_sight"

    # ------------------------------------------------------------------
    # LLM configuration
    # ------------------------------------------------------------------

    model: str = "gpt-oss-120b"
    temperature: float = 0.0
    max_tokens: int = 4096

    # Cerebras OpenAI-compatible endpoint
    base_url: str = "https://api.cerebras.ai/v1"
    api_key: str | None = None

    # ------------------------------------------------------------------
    # Document processing
    # ------------------------------------------------------------------

    max_pages: int = 100
    chunk_size: int = 12000
    chunk_overlap: int = 1000

    # ------------------------------------------------------------------
    # Evidence validation
    # ------------------------------------------------------------------

    verify_quotes: bool = True
    verify_explanations: bool = True
    scope_quote_to_paragraph: bool = True

    # ------------------------------------------------------------------
    # Reliability
    # ------------------------------------------------------------------

    max_retries: int = 3
    base_backoff: float = 1.5

    # ------------------------------------------------------------------
    # Optional experiment metadata
    # ------------------------------------------------------------------

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the configuration into a JSON-serializable dictionary.

        Used by ExperimentLogger for reproducibility.
        """
        return asdict(self)


# ----------------------------------------------------------------------
# Presets
# ----------------------------------------------------------------------

PRESETS: dict[str, ExperimentConfig] = {
    "PyMuPDF + Generic": ExperimentConfig(
        parser="pymupdf",
        prompt="generic",
    ),

    "PyMuPDF + CIM-Sight": ExperimentConfig(
        parser="pymupdf",
        prompt="cim_sight",
    ),
}


def get_preset(name: str) -> ExperimentConfig:
    """
    Return a fresh ExperimentConfig for the requested preset.

    A copy is returned so Streamlit can safely modify values such as
    max_pages and temperature without changing the global preset.
    """

    if name not in PRESETS:
        raise ValueError(
            f"Unknown experiment preset: {name}. "
            f"Available presets: {', '.join(PRESETS.keys())}"
        )

    original = PRESETS[name]

    return ExperimentConfig(
        parser=original.parser,
        prompt=original.prompt,
        model=original.model,
        temperature=original.temperature,
        max_tokens=original.max_tokens,
        base_url=original.base_url,
        api_key=original.api_key,
        max_pages=original.max_pages,
        chunk_size=original.chunk_size,
        chunk_overlap=original.chunk_overlap,
        verify_quotes=original.verify_quotes,
        verify_explanations=original.verify_explanations,
        scope_quote_to_paragraph=original.scope_quote_to_paragraph,
        max_retries=original.max_retries,
        base_backoff=original.base_backoff,
        metadata=dict(original.metadata),
    )


def all_presets() -> list[str]:
    """Return the available preset names in display order."""
    return list(PRESETS.keys())
