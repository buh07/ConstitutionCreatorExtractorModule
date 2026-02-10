"""Native PDF text extraction (PyMuPDF) with basic heading and table detection."""
import re
from typing import List, Tuple

import fitz  # PyMuPDF


def is_text_extractable(path: str, min_chars: int = 50) -> bool:
    """Heuristic to decide if PDF has extractable text (else fallback to OCR)."""
    with fitz.open(path) as doc:
        total = sum(len(page.get_text()) for page in doc)
    return total >= min_chars


def _maybe_table(text: str) -> List[List[str]] | None:
    """Heuristic table detection: split lines by pipes/tabs/2+ spaces; require >1 row with 2+ cols."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    rows: List[List[str]] = []
    for ln in lines:
        if "|" in ln:
            cells = [c.strip() for c in ln.split("|") if c.strip()]
        elif "\t" in ln:
            cells = [c.strip() for c in ln.split("\t") if c.strip()]
        else:
            cells = re.split(r"\s{2,}", ln)
            cells = [c.strip() for c in cells if c.strip()]
        if len(cells) < 2:
            return None
        rows.append(cells)
    return rows if len(rows) >= 2 else None


def extract_pdf_native(path: str) -> Tuple[List[dict], List[str]]:
    """
    Return (sections, pages_text) for text-based PDFs.

    Sections contain heading/level/paragraphs/tables.
    """
    sections: List[dict] = []
    pages_text: List[str] = []

    def is_heading(text: str) -> bool:
        line = text.strip()
        if not line:
            return False
        if len(line) <= 80 and (line.isupper() or line.endswith(":")):
            return True
        if re.match(r"^\d+(\.\d+)*\\s", line):
            return True
        return False

    def heading_level(text: str) -> int:
        line = text.strip()
        m = re.match(r"^(\d+(\.\d+)*)", line)
        if m:
            return min(len(m.group(1).split(".")), 6)
        if line.isupper():
            return 1
        return 2

    current_section: dict | None = None

    with fitz.open(path) as doc:
        for page in doc:
            blocks = page.get_text("blocks")
            page_text_parts: List[str] = []
            for b in sorted(blocks, key=lambda x: (x[1], x[0])):  # sort by y, then x
                text = b[4].strip()
                if not text:
                    continue
                page_text_parts.append(text)
                table_rows = _maybe_table(text)
                if is_heading(text):
                    if current_section:
                        sections.append(current_section)
                    current_section = {
                        "heading": text.split("\n")[0].strip(),
                        "level": heading_level(text),
                        "paragraphs": [],
                        "tables": [],
                        "page": page.number + 1,
                    }
                elif table_rows:
                    if not current_section:
                        current_section = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": page.number + 1}
                    current_section["tables"].append({"rows": table_rows, "page": page.number + 1})
                else:
                    if not current_section:
                        current_section = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": page.number + 1}
                    current_section["paragraphs"].append({"text": text, "page": page.number + 1})
            pages_text.append("\n\n".join(page_text_parts))

    if current_section:
        sections.append(current_section)
    return sections, pages_text
