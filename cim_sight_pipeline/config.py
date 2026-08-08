from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ParserName = Literal["standard", "pymupdf", "docling"]
PromptName = Literal["generic", "cim_sight"]


@dataclass
class ExperimentConfig:
    """
    Central configuration for one CIM-Sight AI analysis run.

    parser:
        standard  = raw PDF text extraction
        pymupdf   = PyMuPDF extraction with table-to-Markdown conversion
        docling   = Docling Markdown extraction

    prompt:
        generic   = baseline prompt
        cim_sight = domain-specific financial auditing prompt
    """

    parser: ParserName = "standard"
    prompt: PromptName = "cim_sight"

    model: str = "gpt-oss-120b"
    temperature: float = 0.0
    max_tokens: int = 4096

    max_pages: int = 100

    chunk_size: int = 12000
    chunk_overlap: int = 1000

    verify_quotes: bool = True
    verify_explanations: bool = True
    scope_quote_to_paragraph: bool = True

    max_retries: int = 3
    retry_base_delay: float = 1.5

    metadata: dict = field(default_factory=dict)


PRESETS = {
    "Standard + Generic": ExperimentConfig(
        parser="standard",
        prompt="generic",
        temperature=0.0,
    ),

    "Standard + CIM-Sight": ExperimentConfig(
        parser="standard",
        prompt="cim_sight",
        temperature=0.0,
    ),

    "PyMuPDF + Generic": ExperimentConfig(
        parser="pymupdf",
        prompt="generic",
        temperature=0.0,
    ),

    "PyMuPDF + CIM-Sight": ExperimentConfig(
        parser="pymupdf",
        prompt="cim_sight",
        temperature=0.0,
    ),

    "Docling + Generic": ExperimentConfig(
        parser="docling",
        prompt="generic",
        temperature=0.0,
    ),

    "Docling + CIM-Sight": ExperimentConfig(
        parser="docling",
        prompt="cim_sight",
        temperature=0.0,
    ),
}


def get_preset(name: str) -> ExperimentConfig:
    """Return a fresh copy of a named experiment preset."""
    try:
        config = PRESETS[name]
    except KeyError:
        raise ValueError(f"Unknown experiment preset: {name}")

    return ExperimentConfig(
        parser=config.parser,
        prompt=config.prompt,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_pages=config.max_pages,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        verify_quotes=config.verify_quotes,
        verify_explanations=config.verify_explanations,
        scope_quote_to_paragraph=config.scope_quote_to_paragraph,
        max_retries=config.max_retries,
        retry_base_delay=config.retry_base_delay,
        metadata=dict(config.metadata),
    )


def all_presets() -> list[str]:
    """Return available preset names in display order."""
    return list(PRESETS.keys())


@dataclass
class SourceSpan:
    """
    Maps a section of extracted text to its original PDF page.
    """

    start: int
    end: int
    page_number: int


@dataclass
class ExtractionResult:
    """
    Result returned by the PDF parsing layer.
    """

    text: str
    spans: list[SourceSpan] = field(default_factory=list)
    page_count: int = 0
    tables: list = field(default_factory=list)
    parser: str = "standard"

    def page_for_offset(self, offset: int) -> int | None:
        """Return the source page containing an absolute character offset."""
        for span in self.spans:
            if span.start <= offset < span.end:
                return span.page_number
        return None

    def paragraphs(self) -> list[tuple[int, int, int]]:
        """
        Return paragraph ranges as absolute offsets.

        Each tuple is:
            (start_offset, end_offset, page_number)
        """
        paragraphs = []
        i = 0
        n = len(self.text)

        while i < n:
            j = self.text.find("\n\n", i)

            if j == -1:
                j = n

            if j > i:
                page = self.page_for_offset(i)
                paragraphs.append((i, j, page or 0))

            i = j + 2

        return paragraphs


def extract(pdf_path: str, config: ExperimentConfig) -> ExtractionResult:
    """
    Dispatch extraction to the parser selected by ExperimentConfig.

    This function is kept here for backwards compatibility with the
    current analyzer.py implementation.
    """

    if config.parser == "standard":
        return _extract_standard(pdf_path, config)

    if config.parser == "pymupdf":
        return _extract_pymupdf(pdf_path, config)

    if config.parser == "docling":
        return _extract_docling(pdf_path, config)

    raise ValueError(f"Unknown parser: {config.parser}")


def _extract_standard(
    pdf_path: str,
    config: ExperimentConfig,
) -> ExtractionResult:
    """
    Standard baseline extraction.

    Uses PyMuPDF's raw page text without attempting to reconstruct
    table structure.
    """
    import fitz

    spans = []
    parts = []
    cursor = 0

    doc = fitz.open(pdf_path)

    try:
        max_pages = min(config.max_pages, doc.page_count)

        for i in range(max_pages):
            page_text = doc[i].get_text("text") or ""

            if i > 0:
                page_text = "\n\n" + page_text

            start = cursor
            end = cursor + len(page_text)

            spans.append(
                SourceSpan(
                    start=start,
                    end=end,
                    page_number=i + 1,
                )
            )

            parts.append(page_text)
            cursor = end

    finally:
        doc.close()

    return ExtractionResult(
        text="".join(parts),
        spans=spans,
        page_count=max_pages,
        tables=[],
        parser="standard",
    )


def _extract_pymupdf(
    pdf_path: str,
    config: ExperimentConfig,
) -> ExtractionResult:
    """
    Legacy PyMuPDF structure-preserving parser.

    This is retained so existing experiments remain reproducible.
    """
    import fitz

    spans = []
    tables = []
    parts = []
    cursor = 0

    doc = fitz.open(pdf_path)

    try:
        max_pages = min(config.max_pages, doc.page_count)

        for i in range(max_pages):
            page = doc[i]
            page_text = page.get_text("text") or ""

            try:
                page_tables = []

                for table in page.find_tables().tables:
                    rows = table.extract()

                    if rows:
                        markdown = _table_to_markdown(rows)
                        tables.append(markdown)
                        page_tables.append(markdown)

                if page_tables:
                    page_text = (
                        page_text.rstrip()
                        + "\n\n"
                        + "\n\n".join(page_tables)
                    )

            except Exception:
                # Table extraction is supplemental. Raw page text
                # should remain available even if table detection fails.
                pass

            if i > 0:
                page_text = "\n\n" + page_text

            start = cursor
            end = cursor + len(page_text)

            spans.append(
                SourceSpan(
                    start=start,
                    end=end,
                    page_number=i + 1,
                )
            )

            parts.append(page_text)
            cursor = end

    finally:
        doc.close()

    return ExtractionResult(
        text="".join(parts),
        spans=spans,
        page_count=max_pages,
        tables=tables,
        parser="pymupdf",
    )


def _extract_docling(
    pdf_path: str,
    config: ExperimentConfig,
) -> ExtractionResult:
    """
    Docling Markdown parser.

    Docling is used specifically to test structure-preserving
    document conversion. It is NOT structured financial-data extraction.
    """

    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError(
            "Docling is not installed. Add 'docling' to requirements.txt "
            "before using parser='docling'."
        ) from exc

    converter = DocumentConverter()
    result = converter.convert(pdf_path)

    markdown = result.document.export_to_markdown()

    return ExtractionResult(
        text=markdown,
        spans=[
            SourceSpan(
                start=0,
                end=len(markdown),
                page_number=1,
            )
        ],
        page_count=1,
        tables=[],
        parser="docling",
    )


def _table_to_markdown(rows) -> str:
    """Convert extracted table rows into Markdown."""
    if not rows:
        return ""

    lines = []

    for row in rows:
        cells = [
            str(cell or "").replace("\n", " ")
            for cell in row
        ]

        lines.append("| " + " | ".join(cells) + " |")

    if lines:
        column_count = len(rows[0])

        lines.insert(
            1,
            "| "
            + " | ".join(["---"] * column_count)
            + " |",
        )

    return "\n".join(lines)
