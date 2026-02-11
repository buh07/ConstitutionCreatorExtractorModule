"""Pass 5: attach governance metadata to policies."""
import re
from typing import Any, Dict, List, Optional

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


def _regex_owner(text: str) -> Optional[str]:
    lower = text.lower()
    patterns = [
        r"(privacy|security|legal|customer service|compliance|risk|hr|operations)\s+(team|department|dept|office)",
        r"(data protection officer|dpo)",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            return m.group(0)
    return None


def _regex_effective_date(text: str) -> Optional[str]:
    date_patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def run(policy: Dict[str, Any], doc_context: Dict[str, Any], llm_client: Any, resolver_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    inferred = {"owner": None, "effective_date": None, "domain": None, "regulatory_linkage": []}
    md_cfg = resolver_cfg or {}
    use_regex = md_cfg.get("use_regex", True)
    if use_regex:
        regex_owner = _regex_owner(section_text)
        regex_date = _regex_effective_date(section_text)
        if regex_owner:
            inferred["owner"] = regex_owner
        if regex_date:
            inferred["effective_date"] = regex_date
    try:
        if not inferred.get("owner") or not inferred.get("effective_date") or not inferred.get("domain"):
            llm_out = llm_client.invoke_json(prompt, schema=MetadataOut)
            inferred = {**inferred, **llm_out}
    except Exception:
        pass

    allowed_domains = {"refund", "privacy", "escalation", "security", "hr", "other"}
    md = policy.get("metadata", {})
    # set source if missing
    if not md.get("source") and section_id:
        md["source"] = f"{policy.get('doc_id')}#{section_id}"
    md["owner"] = inferred.get("owner", md.get("owner"))
    md["effective_date"] = inferred.get("effective_date", md.get("effective_date"))
    domain_val = (inferred.get("domain") or md.get("domain") or "other").lower()
    if domain_val not in allowed_domains:
        domain_val = "other"
    md["domain"] = domain_val
    md["regulatory_linkage"] = inferred.get("regulatory_linkage", md.get("regulatory_linkage", []))

    # Apply tenant/domain defaults if still missing
    tenant_owner_default = md_cfg.get("tenant_owner_default")
    tenant_effective_date_default = md_cfg.get("tenant_effective_date_default")
    tenant_reg_link_default = md_cfg.get("tenant_regulatory_linkage_default", [])
    domain_defaults = md_cfg.get("domain_defaults", {})
    dom_defaults = domain_defaults.get(domain_val, {}) if isinstance(domain_defaults, dict) else {}
    if not md.get("owner") and (dom_defaults.get("owner") or tenant_owner_default):
        md["owner"] = dom_defaults.get("owner") or tenant_owner_default
    if not md.get("effective_date") and (dom_defaults.get("effective_date") or tenant_effective_date_default):
        md["effective_date"] = dom_defaults.get("effective_date") or tenant_effective_date_default
    if not md.get("regulatory_linkage"):
        md["regulatory_linkage"] = dom_defaults.get("regulatory_linkage") or tenant_reg_link_default or []

    policy["metadata"] = md

    # track metadata inference in provenance
    prov = policy.get("provenance", {})
    low_conf = prov.get("low_confidence", [])
    if not md.get("owner") or md.get("owner") == "unknown":
        low_conf.append("owner_inference")
    if not md.get("effective_date"):
        low_conf.append("effective_date_missing")
    if tenant_owner_default or dom_defaults.get("owner"):
        low_conf.append("metadata_default_used")
    prov["low_confidence"] = list(dict.fromkeys(low_conf))
    policy["provenance"] = prov
    return policy
