from __future__ import annotations
from dataclasses import dataclass, field
from .config import ExperimentConfig


@dataclass
class SourceSpan:
    start: int
    end: int
    page_number: int


@dataclass
class ExtractionResult:
    text: str
    spans: list = field(default_factory=list)
    page_count: int = 0
    tables: list = field(default_factory=list)
    parser: str = "standard"

    def page_for_offset(self, offset: int):
        for span in self.spans:
            if span.start <= offset < span.end:
                return span.page_number
        return None

    def paragraphs(self):
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


def _extract_standard(pdf_path, config):
    """Standard text extraction: raw page text only, NO table structure."""
    import fitz
    spans, parts = [], []
    cursor = 0
    doc = fitz.open(pdf_path)
    max_pages = min(config.max_pages, doc.page_count)
    for i in range(max_pages):
        page_text = doc[i].get_text("text") or ""
        if i > 0:
            page_text = "\n\n" + page_text
        start, end = cursor, cursor + len(page_text)
        spans.append(SourceSpan(start, end, i + 1))
        parts.append(page_text)
        cursor = end
    doc.close()
    return ExtractionResult(text="".join(parts), spans=spans,
                            page_count=max_pages, tables=[], parser="standard")


def _extract_pymupdf(pdf_path, config):
    """Structure-preserving: page text + markdown tables appended inline."""
    import fitz
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
        start, end = cursor, cursor + len(page_text)
        spans.append(SourceSpan(start, end, i + 1))
        parts.append(page_text)
        cursor = end
    doc.close()
    return ExtractionResult(text="".join(parts), spans=spans,
                            page_count=max_pages, tables=tables, parser="pymupdf")


def _extract_docling(pdf_path, config):
    try:
        from docling.document_converter import DocumentConverter
    except Exception as e:
        raise RuntimeError("Docling not installed. Use parser='pymupdf'.") from e
    md = DocumentConverter().convert(pdf_path).document.export_to_markdown()
    return ExtractionResult(text=md, spans=[SourceSpan(0, len(md), 1)],
                            page_count=1, parser="docling")


def _table_to_markdown(rows):
    lines = []
    for r in rows:
        cells = [(c or "").replace("\n", " ") for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    if lines:
        lines.insert(1, "| " + " | ".join(["---"] * len(rows[0])) + " |")
    return "\n".join(lines)
