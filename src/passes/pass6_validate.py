"""Pass 6: validation and flagging of extracted policies."""
import json
from typing import Any, Dict, List

from pydantic import BaseModel


VALIDATION_PROMPT = """You are a policy validation assistant. Given a policy JSON, check:
- Are scope/conditions/actions/exceptions non-empty when appropriate?
- Are dates valid (YYYY-MM-DD or null)?
- Is owner present (or mark unknown)?
Respond as JSON with keys:
{
  "issues": ["list of issues or empty"],
  "needs_review": true/false,
  "confidence": 0.0-1.0
}"""


def _basic_checks(policy: Dict[str, Any]) -> List[str]:
    issues = []
    conds = policy.get("conditions", [])
    acts = policy.get("actions", [])
    if not conds and not acts:
        issues.append("empty_conditions_actions")
    md = policy.get("metadata", {})
    eff = md.get("effective_date")
    if eff and not isinstance(eff, str):
        issues.append("invalid_effective_date")
    if not md.get("owner"):
        issues.append("missing_owner")
    return issues


def run(policy: Dict[str, Any], llm_client: Any) -> Dict[str, Any]:
    """Run rule checks and LLM self-critique to flag issues; update status."""
    issues = _basic_checks(policy)
    try:
        class ValOut(BaseModel):
            issues: List[str]
            needs_review: bool
            confidence: float | None
        llm_result = llm_client.invoke_json(VALIDATION_PROMPT + "\n\nPolicy JSON:\n" + json.dumps(policy), schema=ValOut)
    except Exception:
        llm_result = {}
    llm_issues = llm_result.get("issues", [])
    if isinstance(llm_issues, list):
        issues.extend(llm_issues)
    needs_review = bool(llm_result.get("needs_review", False) or len(issues) > 0)
    confidence = llm_result.get("confidence")

    prov = policy.get("provenance", {})
    low_conf = prov.get("low_confidence", [])
    if needs_review:
        low_conf.append("validation_issues")
    prov["validation_issues"] = issues
    prov["low_confidence"] = list(dict.fromkeys(low_conf))
    if confidence is not None:
        prov["confidence_score"] = confidence if prov.get("confidence_score") is None else min(
            prov["confidence_score"], confidence
        )
    policy["provenance"] = prov

    status = policy.get("processing_status", {})
    status["extraction"] = "complete"
    policy["processing_status"] = status
    return policy
