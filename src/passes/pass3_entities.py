"""Pass 3: entity extraction (regex baseline, optional spaCy/LLM fallback)."""
import os
import re
from typing import Any, Dict, List, Optional

# Lazy spaCy loader to avoid heavy imports during testing
_NLP = None


def _get_spacy():
    global _NLP
    if _NLP is not None:
        return _NLP
    try:
        import spacy  # type: ignore
        _NLP = spacy.load("en_core_web_sm")
    except Exception:
        _NLP = None
    return _NLP


# Simple regexes for dates/amounts/percents
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b", re.IGNORECASE)
AMOUNT_PATTERN = re.compile(r"\$\d+(?:,\d{3})*(?:\.\d{2})?")
PERCENT_PATTERN = re.compile(r"\d+(?:\.\d+)?%")
# also catch simple day spans like "30 days"
DAYSPAN_PATTERN = re.compile(r"\b\d+\s+days\b", re.IGNORECASE)


def _find_spans(
    pattern: re.Pattern,
    text: str,
    section_id: Optional[str],
    page: Optional[int],
    ent_type: str,
) -> List[Dict[str, Any]]:
    ents = []
    for m in pattern.finditer(text):
        ents.append(
            {
                "type": ent_type,
                "value": m.group(0),
                "span": {"start": m.start(), "end": m.end(), "page": page, "section_id": section_id},
            }
        )
    return ents


def _spacy_entities(text: str, section_id: Optional[str], page: Optional[int]) -> List[Dict[str, Any]]:
    nlp = _get_spacy()
    if not nlp:
        return []
    doc = nlp(text)
    mapped = []
    for ent in doc.ents:
        etype = ent.label_.lower()
        if etype in {"money"}:
            mapped_type = "amount"
        elif etype in {"date", "time"}:
            mapped_type = "date"
        elif etype in {"percent"}:
            mapped_type = "percent"
        elif etype in {"org", "person", "gpe"}:
            mapped_type = "role"
        else:
            continue
        mapped.append(
            {
                "type": mapped_type,
                "value": ent.text,
                "span": {"start": ent.start_char, "end": ent.end_char, "page": page, "section_id": section_id},
            }
        )
    return mapped


def _llm_fallback(text: str, llm_client: Any) -> List[Dict[str, Any]]:
    prompt = """Extract entities from the text. Respond as a JSON list of objects with fields: type (date|amount|role|product|percent|other), value, span:{start,end}. If uncertain, skip.
Text:
"""
    try:
        res = llm_client.invoke_json(prompt + text)
        return res if isinstance(res, list) else []
    except Exception:
        return []


def run(section: Dict[str, Any], components: Dict[str, Any], llm_client: Any) -> List[Dict[str, Any]]:
    """Return detected entities with spans and types."""
    paras = [p.get("text", "") if isinstance(p, dict) else str(p) for p in section.get("paragraphs", [])]
    text = "\n\n".join(paras)
    section_id = section.get("section_id")
    # derive page from first paragraph span if present
    page = None
    if section.get("paragraphs"):
        first_span = section["paragraphs"][0].get("span") if isinstance(section["paragraphs"][0], dict) else None
        if first_span and isinstance(first_span, dict):
            page = first_span.get("page")
    page = page or section.get("page")

    entities: List[Dict[str, Any]] = []
    entities.extend(_find_spans(DATE_PATTERN, text, section_id, page, "date"))
    entities.extend(_find_spans(DAYSPAN_PATTERN, text, section_id, page, "date"))
    entities.extend(_find_spans(AMOUNT_PATTERN, text, section_id, page, "amount"))
    entities.extend(_find_spans(PERCENT_PATTERN, text, section_id, page, "percent"))
    # spaCy entities optional (set ENABLE_SPACY_ENTS=1 to enable); otherwise skip heavy deps
    if os.getenv("ENABLE_SPACY_ENTS", "0") == "1":
        entities.extend(_spacy_entities(text, section_id, page))

    # Optional LLM fallback for ambiguous cases
    if llm_client:
        llm_entities = _llm_fallback(text, llm_client) or []
        for ent in llm_entities:
            span = ent.get("span") or {}
            span.setdefault("page", page)
            span.setdefault("section_id", section_id)
            ent["span"] = span
            entities.append(ent)

    # Deduplicate by (type, value, start, end)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for ent in entities:
        span = ent.get("span", {}) or {}
        # attach page/section if missing
        if span is not None:
            if span.get("page") is None:
                span["page"] = page
            if span.get("section_id") is None:
                span["section_id"] = section_id
            ent["span"] = span
        key = (ent.get("type"), ent.get("value"), span.get("start"), span.get("end"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ent)

    return uniq
