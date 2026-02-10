"""Canonical document schema (Pydantic models) used by regularization."""
from typing import List, Optional

from pydantic import BaseModel, Field


class Span(BaseModel):
    """Character offsets into the full_text (inclusive start, exclusive end)."""

    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    page: Optional[int] = Field(None, ge=1)
    section_id: Optional[str] = None


class Paragraph(BaseModel):
    text: str
    span: Span


class TextBlock(BaseModel):
    text: str
    span: Span


class Table(BaseModel):
    rows: List[List[str]] = Field(default_factory=list)
    span: Optional[Span] = None


class Page(BaseModel):
    page_num: int = Field(..., ge=1)
    text_blocks: List[TextBlock] = Field(default_factory=list)
    tables: List[Table] = Field(default_factory=list)


class Section(BaseModel):
    section_id: str
    level: int = Field(..., ge=0)
    heading: Optional[str] = None
    paragraphs: List[Paragraph] = Field(default_factory=list)
    tables: List[Table] = Field(default_factory=list)
    children: List[str] = Field(default_factory=list)


class Provenance(BaseModel):
    method: str  # pdf_native | ocr | docx | md | txt
    ocr_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    pages: Optional[int] = Field(None, ge=0)
    tool: Optional[str] = None


class CanonicalDocument(BaseModel):
    doc_id: str
    filename: str
    provenance: Provenance
    pages: List[Page] = Field(default_factory=list)
    sections: List[Section] = Field(default_factory=list)
    full_text: str
