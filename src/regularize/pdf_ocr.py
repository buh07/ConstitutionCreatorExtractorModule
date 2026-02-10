"""Scanned PDF OCR + layout reconstruction using Google Document AI."""
from typing import List, Optional, Tuple

from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.auth.exceptions import DefaultCredentialsError

from src.config import DocAIConfig


def _layout_text(layout: documentai.Document.Page.Layout, full_text: str) -> str:
    """Extract text from a layout's text anchor spans."""
    if not layout or not layout.text_anchor or not layout.text_anchor.text_segments:
        return ""
    parts: List[str] = []
    for seg in layout.text_anchor.text_segments:
        start = int(getattr(seg, "start_index", 0) or 0)
        end = int(getattr(seg, "end_index", 0) or 0)
        parts.append(full_text[start:end])
    return "".join(parts)


def extract_pdf_ocr(path: str, docai_config: DocAIConfig) -> Tuple[List[str], Optional[float]]:
    """
    Use Google Document AI to OCR/layout a scanned PDF.

    Requires GOOGLE_APPLICATION_CREDENTIALS or gcloud ADC setup.
    Returns: (list of page texts, average layout confidence or None).
    """
    if not docai_config:
        raise ValueError("DocAI config is required for OCR processing")

    client_options = ClientOptions(api_endpoint=f"{docai_config.location}-documentai.googleapis.com")
    try:
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Google ADC not found. Set GOOGLE_APPLICATION_CREDENTIALS or run `gcloud auth application-default login`."
        ) from exc

    if docai_config.processor_version:
        name = client.processor_version_path(
            docai_config.project_id,
            docai_config.location,
            docai_config.processor_id,
            docai_config.processor_version,
        )
    else:
        name = client.processor_path(docai_config.project_id, docai_config.location, docai_config.processor_id)

    with open(path, "rb") as f:
        content = f.read()

    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(content=content, mime_type="application/pdf"),
    )
    result = client.process_document(request=request)
    doc = result.document

    pages_text: List[str] = []
    confidences: List[float] = []
    for page in doc.pages:
        text = _layout_text(page.layout, doc.text)
        pages_text.append(text if text else "")
        if getattr(page.layout, "confidence", None) is not None:
            confidences.append(float(page.layout.confidence))

    if not pages_text:
        pages_text = [doc.text or ""]

    avg_conf = sum(confidences) / len(confidences) if confidences else None
    return pages_text, avg_conf
