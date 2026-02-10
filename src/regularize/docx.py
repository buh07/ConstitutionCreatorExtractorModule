"""DOCX parsing (python-docx) with heading and table preservation."""
from typing import List, Tuple

import docx  # python-docx


def _heading_level(style_name: str) -> int:
    if style_name and style_name.lower().startswith("heading"):
        parts = style_name.split()
        for p in parts:
            if p.isdigit():
                return min(int(p), 6)
    return 2


def extract_docx(path: str) -> Tuple[List[dict], List[str]]:
    """Return (sections, pages_text) preserving headings and tables."""
    document = docx.Document(path)
    sections: List[dict] = []
    pages_text: List[str] = []

    current: dict | None = None
    text_accum: List[str] = []

    for block in document.element.body:
        if block.tag.endswith("p"):
            para = docx.text.paragraph.Paragraph(block, document)
            text = para.text.strip()
            if not text:
                continue
            text_accum.append(text)
            style_name = para.style.name if para.style else ""
            if style_name.lower().startswith("heading"):
                if current:
                    sections.append(current)
                current = {
                    "heading": text,
                    "level": _heading_level(style_name),
                    "paragraphs": [],
                    "tables": [],
                    "page": 1,
                }
            else:
                if not current:
                    current = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": 1}
                current["paragraphs"].append({"text": text, "page": 1})
        elif block.tag.endswith("tbl"):
            table = docx.table.Table(block, document)
            rows = []
            for row in table.rows:
                rows.append([cell.text.strip() for cell in row.cells])
            if not current:
                current = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": 1}
            current["tables"].append({"rows": rows, "page": 1})
            text_accum.append("\n".join([" | ".join(r) for r in rows]))

    if current:
        sections.append(current)

    pages_text.append("\n\n".join(text_accum))
    return sections, pages_text
