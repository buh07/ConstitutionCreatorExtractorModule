"""Pipeline orchestrator for regularization and multi-pass extraction."""
import logging
import os
import time
from typing import Any, Dict, List

try:
    import ray  # type: ignore
except Exception:
    ray = None

from src.config import Config
from src.llm.client import LLMClient
from src.regularize import router
from src.passes import pass1_classify, pass2_components, pass3_entities, pass4_merge, pass5_metadata, pass6_validate
from src.storage.writer import write_index, write_policies_jsonl

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


def _section_dict(section: Any) -> Dict[str, Any]:
    return section.model_dump() if hasattr(section, "model_dump") else dict(section)


def _source_span(section: Dict[str, Any]) -> Dict[str, Any]:
    spans = []
    for para in section.get("paragraphs", []):
        span = para.get("span") if isinstance(para, dict) else None
        if span and isinstance(span, dict):
            spans.append(span)
    if not spans:
        return {"start": 0, "end": 0, "page": section.get("page"), "section_id": section.get("section_id")}
    start = min(s.get("start", 0) for s in spans)
    end = max(s.get("end", 0) for s in spans)
    page = spans[0].get("page")
    return {"start": start, "end": end, "page": page, "section_id": section.get("section_id")}


def _init_policy(doc_id: str, section: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "processing_status": {
            "extraction": "pending",
            "formalization": "pending",
            "conflict_detection": "pending",
            "layer_assignment": "pending",
        },
        "policy_id": f"POL-{section.get('section_id', 'unknown')}",
        "origin": "explicit",
        "doc_id": doc_id,
        "scope": {},
        "conditions": [],
        "actions": [],
        "exceptions": [],
        "entities": [],
        "metadata": {"source": f"{doc_id}#{section.get('section_id', '')}"},
        "provenance": {
            "passes_used": [],
            "low_confidence": [],
            "confidence_score": None,
            "source_spans": [_source_span(section)],
            "evidence_count": 1,
        },
    }


def run_pipeline(input_path: str, output_dir: str, tenant_id: str, batch_id: str, config: Config) -> None:
    """
    End-to-end execution. Regularize documents, run passes, and write
    JSON outputs (policies.jsonl + index.json).
    """
    logger.info("Starting pipeline for %s", input_path)
    t0 = time.time()
    canonical = router.regularize(input_path, config)
    t_reg = time.time() - t0
    logger.info("Regularization complete: %s sections", len(canonical.sections))
    llm = LLMClient(
        provider=config.llm.provider,
        model_id=config.llm.model_id,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        region=config.llm.region,
        top_k=config.llm.top_k,
        retries=config.llm.retries,
        backoff=config.llm.backoff,
    )

    policies: List[Dict[str, Any]] = []
    t_pass = time.time()
    sections = [_section_dict(sec) for sec in canonical.sections]

    def _process_section(sec_dict: Dict[str, Any], doc_id: str, cfg_dict: Dict[str, Any]) -> Dict[str, Any] | None:
        local_llm = LLMClient(
            provider=cfg_dict["llm"]["provider"],
            model_id=cfg_dict["llm"]["model_id"],
            temperature=cfg_dict["llm"]["temperature"],
            max_tokens=cfg_dict["llm"]["max_tokens"],
            region=cfg_dict["llm"]["region"],
            top_k=cfg_dict["llm"]["top_k"],
            retries=cfg_dict["llm"]["retries"],
            backoff=cfg_dict["llm"]["backoff"],
        )
        cls = pass1_classify.run(sec_dict, local_llm)
        if not cls.get("is_policy"):
            return None
        policy = _init_policy(doc_id, sec_dict)
        policy["processing_status"]["extraction"] = "in_progress"
        policy["provenance"]["passes_used"].append(1)
        comps = pass2_components.run(sec_dict, local_llm)
        policy["scope"] = comps.get("scope", {})
        policy["conditions"] = comps.get("conditions", [])
        policy["actions"] = comps.get("actions", [])
        policy["exceptions"] = comps.get("exceptions", [])
        policy["provenance"]["passes_used"].append(2)
        ents = pass3_entities.run(sec_dict, comps, local_llm)
        policy["entities"] = ents
        policy["provenance"]["passes_used"].append(3)
        return policy

    if config.parallel.enabled and ray:
        cfg_dict = {
            "llm": {
                "provider": config.llm.provider,
                "model_id": config.llm.model_id,
                "temperature": config.llm.temperature,
                "max_tokens": config.llm.max_tokens,
                "region": config.llm.region,
                "top_k": config.llm.top_k,
                "retries": config.llm.retries,
                "backoff": config.llm.backoff,
            }
        }

        @ray.remote
        def process_section_remote(sec):
            return _process_section(sec, canonical.doc_id, cfg_dict)

        num_workers = config.parallel.num_workers or len(sections)
        refs = [process_section_remote.remote(sec) for sec in sections]
        results = ray.get(refs)
        policies = [p for p in results if p]
    else:
        for sec_dict in sections:
            policy = _process_section(sec_dict, canonical.doc_id, {"llm": config.llm.__dict__})
            if policy:
                policies.append(policy)

    # Pass 4: merge
    policies = pass4_merge.run(policies, llm, sim_threshold=config.merge.similarity_threshold)
    for p in policies:
        if 4 not in p.get("provenance", {}).get("passes_used", []):
            p["provenance"]["passes_used"].append(4)

    # Pass 5: metadata
    for i, pol in enumerate(policies):
        policies[i] = pass5_metadata.run(pol, canonical.model_dump() if hasattr(canonical, "model_dump") else {}, llm)
        policies[i]["provenance"]["passes_used"].append(5)

    # Pass 6: validation
    for i, pol in enumerate(policies):
        policies[i] = pass6_validate.run(pol, llm)
        policies[i]["provenance"]["passes_used"].append(6)

    t_pass = time.time() - t_pass
    # Write outputs
    os.makedirs(output_dir, exist_ok=True)
    policies_path = os.path.join(output_dir, f"{canonical.doc_id}-{batch_id}.jsonl")
    write_policies_jsonl(policies, policies_path)

    # Simple index
    domains: Dict[str, int] = {}
    flagged = 0
    for p in policies:
        dom = p.get("metadata", {}).get("domain") or "unknown"
        domains[dom] = domains.get(dom, 0) + 1
        if p.get("provenance", {}).get("low_confidence"):
            flagged += 1
    flagged_pct = (flagged / len(policies) * 100) if policies else 0.0
    index = {
        "doc_id": canonical.doc_id,
        "batch_id": batch_id,
        "num_policies": len(policies),
        "flagged_pct": flagged_pct,
        "domains": domains,
    }
    index_path = os.path.join(output_dir, f"{canonical.doc_id}-{batch_id}-index.json")
    write_index(index, index_path)
    logger.info(
        "Pipeline completed: %d policies, flagged_pct=%.2f, domains=%s",
        len(policies),
        flagged_pct,
        domains,
    )
    logger.info("Timings: regularization=%.2fs, passes=%.2fs", t_reg, t_pass)
