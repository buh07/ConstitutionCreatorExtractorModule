"""Pass 1: classify sections as policy vs non-policy using an LLM."""
from typing import Any, Dict

from pydantic import BaseModel, Field

CLASSIFY_PROMPT = """You are a policy extraction assistant. Given a section with heading and text, decide if it is policy-relevant (policy/procedure/guideline) or non-policy (intro/background/definitions/marketing/legal boilerplate). Respond in JSON:
{
  "is_policy": true/false,
  "confidence": 0.0-1.0,
  "reason": "one sentence"
}
Use only the provided text. Be conservative: classify as policy only if it contains actionable rules, requirements, procedures, or constraints."""


class ClassifyResponse(BaseModel):
    is_policy: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


def run(section: Dict[str, Any], llm_client: Any) -> Dict[str, Any]:
    """Return classification with confidence and reason."""
    heading = section.get("heading") or ""
    paras = [p.get("text", "") if isinstance(p, dict) else str(p) for p in section.get("paragraphs", [])]
    text = "\n\n".join(paras)
    prompt = f"{CLASSIFY_PROMPT}\n\nHeading: {heading}\n\nText:\n{text}"
    return llm_client.invoke_json(prompt, schema=ClassifyResponse)
