"""HTML/Markdown normalization with heading and table preservation."""
from typing import List, Tuple

from bs4 import BeautifulSoup
import markdown


def extract_html_md(path: str) -> Tuple[List[dict], List[str]]:
    """Parse HTML/Markdown into (sections, pages_text)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    if path.lower().endswith((".md", ".markdown")):
        html = markdown.markdown(raw)
    else:
        html = raw

    soup = BeautifulSoup(html, "html.parser")
    sections: List[dict] = []
    text_accum: List[str] = []

    def level_from_tag(tag_name: str) -> int:
        if tag_name.startswith("h") and tag_name[1:].isdigit():
            return min(int(tag_name[1:]), 6)
        return 2

    current: dict | None = None
    for elem in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table"]):
        if elem.name.startswith("h"):
            if current:
                sections.append(current)
            current = {
                "heading": elem.get_text(strip=True),
                "level": level_from_tag(elem.name),
                "paragraphs": [],
                "tables": [],
                "page": 1,
            }
            text_accum.append(current["heading"])
        elif elem.name == "p":
            text = elem.get_text(strip=True)
            if not text:
                continue
            text_accum.append(text)
            if not current:
                current = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": 1}
            current["paragraphs"].append({"text": text, "page": 1})
        elif elem.name == "table":
            rows = []
            for row in elem.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            if rows:
                text_accum.append("\n".join([" | ".join(r) for r in rows]))
                if not current:
                    current = {"heading": None, "level": 1, "paragraphs": [], "tables": [], "page": 1}
                current["tables"].append({"rows": rows, "page": 1})

    if current:
        sections.append(current)

    pages_text = ["\n\n".join(text_accum)]
    return sections, pages_text
