"""Pass 5: attach governance metadata to policies."""
from typing import Any, Dict, List

from pydantic import BaseModel

METADATA_PROMPT = """You are a policy metadata annotator. Given a policy and its section heading/text, infer:
- owner: responsible team/person (or 'unknown' if not clear)
- effective_date: YYYY-MM-DD if stated; else null
- domain: one of [refund, privacy, escalation, security, hr, other]
- regulatory_linkage: list of related regulations (e.g., GDPR, FTC, HIPAA) or [] if none
Respond as JSON with keys: owner, effective_date, domain, regulatory_linkage (array)."""


def _find_section_text(section_id: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    heading = ""
    section_text = ""
    for sec in sections:
        if sec.get("section_id") == section_id:
            heading = sec.get("heading") or ""
            paras = [p.get("text", "") if isinstance(p, dict) else str(p) for p in sec.get("paragraphs", [])]
            section_text = "\n\n".join(paras)
            break
    return {"heading": heading, "text": section_text}


def run(policy: Dict[str, Any], doc_context: Dict[str, Any], llm_client: Any) -> Dict[str, Any]:
    """Infer metadata and return updated policy."""
    source_spans: List[Dict[str, Any]] = policy.get("provenance", {}).get("source_spans", [])
    sections = doc_context.get("sections", []) if doc_context else []
    section_id = source_spans[0].get("section_id") if source_spans else None

    heading = ""
    section_text = ""
    if section_id:
        found = _find_section_text(section_id, sections)
        heading = found["heading"]
        section_text = found["text"]
    else:
        # fallback: concatenate section texts
        paras = []
        for sec in sections:
            paras.extend([p.get("text", "") if isinstance(p, dict) else str(p) for p in sec.get("paragraphs", [])])
        section_text = "\n\n".join(paras)

    prompt = f"{METADATA_PROMPT}\n\nHeading: {heading}\n\nText:\n{section_text}"
    class MetadataOut(BaseModel):
        owner: str | None
        effective_date: str | None
        domain: str | None
        regulatory_linkage: List[str]
    inferred = llm_client.invoke_json(prompt, schema=MetadataOut)

    md = policy.get("metadata", {})
    # set source if missing
    if not md.get("source") and section_id:
        md["source"] = f"{policy.get('doc_id')}#{section_id}"
    md["owner"] = inferred.get("owner", md.get("owner"))
    md["effective_date"] = inferred.get("effective_date", md.get("effective_date"))
    md["domain"] = inferred.get("domain", md.get("domain"))
    md["regulatory_linkage"] = inferred.get("regulatory_linkage", md.get("regulatory_linkage", []))
    policy["metadata"] = md

    # track metadata inference in provenance
    prov = policy.get("provenance", {})
    low_conf = prov.get("low_confidence", [])
    if not md.get("owner") or md.get("owner") == "unknown":
        low_conf.append("owner_inference")
    prov["low_confidence"] = list(dict.fromkeys(low_conf))
    policy["provenance"] = prov
    return policy
