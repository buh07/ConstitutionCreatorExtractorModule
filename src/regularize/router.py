"""Format detection and routing for document regularization."""
import hashlib
import os
import pathlib
import re
from typing import List

from src.config import Config
from src.schemas.canonical import CanonicalDocument, Page, Paragraph, Section, Span, Table, TextBlock
from . import docx as docx_extract
from . import html_md as html_md_extract
from . import pdf_native as pdf_native_extract
from . import pdf_ocr as pdf_ocr_extract


def _split_blocks_with_tables(text: str) -> tuple[list[str], list[list[list[str]]]]:
    """Split text into paragraphs and table rows using simple heuristics."""
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) >= 2:
            # attempt table detection: at least two lines and 2+ cells per line
            rows: List[List[str]] = []
            valid = True
            for ln in lines:
                if "|" in ln:
                    cells = [c.strip() for c in ln.split("|") if c.strip()]
                elif "\t" in ln:
                    cells = [c.strip() for c in ln.split("\t") if c.strip()]
                else:
                    cells = re.split(r"\s{2,}", ln)
                    cells = [c.strip() for c in cells if c.strip()]
                if len(cells) < 2:
                    valid = False
                    break
                rows.append(cells)
            if valid and len(rows) >= 2:
                tables.append(rows)
                continue
        paragraphs.append(block.strip())
    return paragraphs, tables


def _draft_from_plain_texts(texts: List[str]) -> List[dict]:
    """Create a single section draft from plain page texts with table heuristics."""
    paragraphs: List[dict] = []
    tables: List[dict] = []
    for text in texts:
        para_blocks, table_blocks = _split_blocks_with_tables(text)
        paragraphs.extend([{"text": p, "page": idx + 1} for idx, p in enumerate(para_blocks)])
        tables.extend([{"rows": tbl, "page": idx + 1} for idx, tbl in enumerate(table_blocks)])
    return [{"heading": None, "level": 1, "paragraphs": paragraphs, "tables": tables, "section_id": "sec1"}]


def _hash_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_canonical_from_sections(
    section_drafts: List[dict],
    pages_text: List[str],
    filename: str,
    method: str,
    tool: str,
    ocr_confidence: float | None = None,
    doc_id: str | None = None,
) -> CanonicalDocument:
    if doc_id is None:
        doc_id = _hash_file(filename)

    full_text_parts: List[str] = []
    sections: List[Section] = []
    offset = 0

    for idx, draft in enumerate(section_drafts, start=1):
        heading = draft.get("heading")
        level = draft.get("level", 1)
        paragraphs: List[Paragraph] = []
        tables: List[Table] = []

        if heading:
            heading_start = offset
            full_text_parts.append(heading)
            heading_end = heading_start + len(heading)
            offset = heading_end + 2
            full_text_parts.append("\n\n")

        for para_item in draft.get("paragraphs", []):
            if isinstance(para_item, dict):
                para_text = para_item.get("text", "")
                para_page = para_item.get("page")
            else:
                para_text = str(para_item)
                para_page = draft.get("page")
            start = offset
            full_text_parts.append(para_text)
            end = start + len(para_text)
            paragraphs.append(Paragraph(text=para_text, span=Span(start=start, end=end, page=para_page)))
            offset = end + 2
            full_text_parts.append("\n\n")

        for table_item in draft.get("tables", []):
            if isinstance(table_item, dict):
                table_rows = table_item.get("rows", [])
                table_page = table_item.get("page")
            else:
                table_rows = table_item
                table_page = draft.get("page")
            table_text = "\n".join([" | ".join(row) for row in table_rows])
            start = offset
            full_text_parts.append(table_text)
            end = start + len(table_text)
            tables.append(Table(rows=table_rows, span=Span(start=start, end=end, page=table_page)))
            offset = end + 2
            full_text_parts.append("\n\n")

        sections.append(
            Section(
                section_id=draft.get("section_id") or f"sec{idx}",
                level=level,
                heading=heading,
                paragraphs=paragraphs,
                tables=tables,
                children=[],
            )
        )

    full_text = "".join(full_text_parts)
    pages: List[Page] = []
    page_offset = 0
    for i, text in enumerate(pages_text):
        page_num = i + 1
        text_block_span = Span(start=page_offset, end=page_offset + len(text), page=page_num)
        text_block = TextBlock(text=text, span=text_block_span)
        pages.append(Page(page_num=page_num, text_blocks=[text_block], tables=[]))
        page_offset += len(text)
        if i < len(pages_text) - 1:
            page_offset += 2  # account for join separators if used upstream

    provenance = {
        "method": method,
        "ocr_confidence": ocr_confidence,
        "pages": len(pages_text),
        "tool": tool,
    }

    return CanonicalDocument(
        doc_id=doc_id,
        filename=os.path.basename(filename),
        provenance=provenance,
        pages=pages,
        sections=sections,
        full_text=full_text,
    )


def regularize(input_path: str, config: Config) -> CanonicalDocument:
    """Detect format (pdf/docx/md/txt) and return canonical document."""
    path = pathlib.Path(input_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        # Check native extractability; fall back to OCR if configured.
        if pdf_native_extract.is_text_extractable(str(path)):
            section_drafts, pages_text = pdf_native_extract.extract_pdf_native(str(path))
            return _build_canonical_from_sections(
                section_drafts,
                pages_text,
                filename=str(path),
                method="pdf_native",
                tool="pymupdf",
                ocr_confidence=None,
            )

        # Fallback to OCR if configured
        if config.docai:
            pages_text, ocr_conf = pdf_ocr_extract.extract_pdf_ocr(str(path), config.docai)
            section_drafts = _draft_from_plain_texts(pages_text)
            return _build_canonical_from_sections(
                section_drafts,
                pages_text,
                filename=str(path),
                method="ocr",
                tool="document_ai",
                ocr_confidence=ocr_conf,
            )
        raise ValueError("No extractable text found in PDF and no OCR configuration provided")

    if ext == ".docx":
        section_drafts, pages_text = docx_extract.extract_docx(str(path))
        return _build_canonical_from_sections(
            section_drafts,
            pages_text,
            filename=str(path),
            method="docx",
            tool="python-docx",
            ocr_confidence=None,
        )

    if ext in {".html", ".htm", ".md", ".markdown"}:
        section_drafts, pages_text = html_md_extract.extract_html_md(str(path))
        return _build_canonical_from_sections(
            section_drafts,
            pages_text,
            filename=str(path),
            method="html_md",
            tool="bs4/markdown",
            ocr_confidence=None,
        )

    # Fallback: treat as plain text.
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    section_drafts = _draft_from_plain_texts([text])
    return _build_canonical_from_sections(
        section_drafts,
        [text],
        filename=str(path),
        method="txt",
        tool="plain",
        ocr_confidence=None,
    )
