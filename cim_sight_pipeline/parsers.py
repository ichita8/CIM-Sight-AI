from __future__ import annotations
from dataclasses import dataclass, field
from .config import ExperimentConfig


@dataclass
class SourceSpan:
    """Absolute char offset range in the full document text + page number."""
    start: int
    end: int
    page_number: int


@dataclass
class ExtractionResult:
    text: str
    spans: list = field(default_factory=list)   # list[SourceSpan]
    page_count: int = 0
    tables: list = field(default_factory=list)  # list[str] markdown tables
    parser: str = "standard"

    def page_for_offset(self, offset: int):
        """Phase 3 (#9): provenance via absolute offsets -> page mapping."""
        for span in self.spans:
            if span.start <= offset < span.end:
                return span.page_number
        return None

    def paragraphs(self):
        """Return list of (start, end, page) for every paragraph (absolute offsets)."""
        paras = []
        i, n = 0, len(self.text)
        while i < n:
            j = self.text.find("\n\n", i)
            if j == -1:
                j = n
            if j > i:
                page = self.page_for_offset(i)
                paras.append((i, j, page if page else 0))
            i = j + 2
        return paras


def extract(pdf_path: str, config: ExperimentConfig) -> ExtractionResult:
    if config.parser == "standard":
        return _extract_standard(pdf_path, config)
    if config.parser == "pymupdf":
        return _extract_pymupdf(pdf_path, config)
    if config.parser == "docling":
        return _extract_docling(pdf_path, config)
    raise ValueError("Unknown parser: %s" % config.parser)


def _extract_standard(pdf_path: str, config: ExperimentConfig) -> ExtractionResult:
    """Standard text extraction: raw page text only, NO table structure.

    This is the 'Standard Text' condition — what a basic PDF-to-text tool
    produces. Tables collapse into unstructured columns of numbers with no
    row/column relationships preserved.
    """
    import fitz  # PyMuPDF
    spans, parts = [], []
    cursor = 0
    doc = fitz.open(pdf_path)
    max_pages = min(config.max_pages, doc.page_count)
    for i in range(max_pages):
        page_text = doc[i].get_text("text") or ""
        if i > 0:
            page_text = "\n\n" + page_text
        start = cursor
        end = cursor + len(page_text)
        spans.append(SourceSpan(start=start, end=end, page_number=i + 1))
        parts.append(page_text)
        cursor = end
    doc.close()
    return ExtractionResult(text="".join(parts), spans=spans,
                            page_count=max_pages, tables=[], parser="standard")


def _extract_pymupdf(pdf_path: str, config: ExperimentConfig) -> ExtractionResult:
    """Structure-preserving extraction: page text PLUS reconstructed markdown
    tables appended inline. This is the 'PyMuPDF Markdown' condition —
    table row/column structure is preserved for the model.
    """
    import fitz  # PyMuPDF
    spans, tables, parts = [], [], []
    cursor = 0
    doc = fitz.open(pdf_path)
    max_pages = min(config.max_pages, doc.page_count)
    for i in range(max_pages):
        page = doc[i]
        page_text = page.get_text("text") or ""
        try:
            page_tables = []
            for t in page.find_tables().tables:
                rows = t.extract()
                if rows:
                    md = _table_to_markdown(rows)
                    tables.append(md)
                    page_tables.append(md)
            if page_tables:
                page_text = page_text.rstrip() + "\n\n" + "\n\n".join(page_tables)
        except Exception:
            pass
        if i > 0:
            page_text = "\n\n" + page_text
        start = cursor
        end = cursor + len(page_text)
        spans.append(SourceSpan(start=start, end=end, page_number=i + 1))
        parts.append(page_text)
        cursor = end
    doc.close()
    return ExtractionResult(text="".join(parts), spans=spans,
                            page_count=max_pages, tables=tables, parser="pymupdf")


def _extract_docling(pdf_path: str, config: ExperimentConfig) -> ExtractionResult:
    try:
        from docling.document_converter import DocumentConverter
    except Exception as e:
        raise RuntimeError(
            "Docling is not installed. Install with: pip install 'docling'. "
            "For Streamlit Community Cloud use parser='pymupdf' instead."
        ) from e
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    md = result.document.export_to_markdown()
    spans = [SourceSpan(start=0, end=len(md), page_number=1)]
    return ExtractionResult(text=md, spans=spans, page_count=1, parser="docling")


def _table_to_markdown(rows):
    lines = []
    for r in rows:
        cells = [(c or "").replace("\n", " ") for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    if lines:
        lines.insert(1, "| " + " | ".join(["---"] * len(rows[0])) + " |")
    return "\n".join(lines)
