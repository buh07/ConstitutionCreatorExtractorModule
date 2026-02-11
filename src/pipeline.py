"""Pipeline orchestrator for regularization and multi-pass extraction."""
import json
import logging
import os
import shutil
import time
from collections import defaultdict
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
            "validation_issues": [],
        },
    }


_SCOPE_KEYS = ["customer_segments", "product_categories", "channels", "regions"]


def _regex_scope(section: Dict[str, Any], enable_regex: bool) -> Dict[str, List[str]]:
    """Heuristic scope extraction from section text."""
    if not enable_regex:
        return {k: [] for k in _SCOPE_KEYS}
    text_parts = []
    for para in section.get("paragraphs", []):
        if isinstance(para, dict):
            text_parts.append(para.get("text", ""))
        else:
            text_parts.append(str(para))
    text = "\n".join(text_parts).lower()
    product_categories = []
    channels = []
    if "electronic" in text:
        product_categories.append("electronics")
    if "chatbot" in text or "bot" in text:
        channels.append("chatbot")
    return {
        "customer_segments": [],
        "product_categories": list(dict.fromkeys(product_categories)),
        "channels": list(dict.fromkeys(channels)),
        "regions": [],
    }


def _normalize_scope(scope: Dict[str, List[str]], section: Dict[str, Any], scope_cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Ensure scope keys exist; default based on configured fallback; add regex cues if enabled."""
    fallback = (scope_cfg.get("fallback") or "all").lower() if scope_cfg else "all"
    enable_regex = scope_cfg.get("enable_regex", True) if scope_cfg else True
    scope = scope or {}
    # merge regex hints
    regex_scope = _regex_scope(section, enable_regex)
    for key in _SCOPE_KEYS:
        vals = scope.get(key) or []
        regex_vals = regex_scope.get(key) or []
        merged = list(dict.fromkeys([*vals, *regex_vals]))
        scope[key] = merged
    empty = all(not scope.get(k) for k in _SCOPE_KEYS)
    if empty:
        if fallback == "unknown":
            scope = {k: ["unknown"] for k in _SCOPE_KEYS}
        elif fallback == "none":
            scope = {k: [] for k in _SCOPE_KEYS}
        else:
            scope = {k: ["all"] for k in _SCOPE_KEYS}
    else:
        for key in _SCOPE_KEYS:
            scope.setdefault(key, [])
            if not scope[key] and fallback in {"all", "unknown"}:
                scope[key] = [fallback]
    return scope


def _assign_policy_ids(policies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign policy IDs per domain using POL-{DOMAIN}-{###} convention."""
    counters: Dict[str, int] = defaultdict(int)
    for pol in policies:
        domain = (pol.get("metadata", {}).get("domain") or "other").upper()
        counters[domain] += 1
        seq = counters[domain]
        pol["policy_id"] = f"POL-{domain}-{seq:03d}"
    return policies


def _normalize_requires(policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize action.requires entries to align with condition parameters/targets.
    - Map 'no_receipt' → 'has_receipt_false' if a has_receipt condition exists.
    - Map 'within_window' → derived from time_window conditions (e.g., within_time_window).
    Leaves unknown tokens untouched.
    """
    conds = policy.get("conditions", []) or []
    actions = policy.get("actions", []) or []
    # derive known flags
    has_receipt_flag = any(c.get("parameter") == "has_receipt" for c in conds)
    has_time_window = any(c.get("type") == "time_window" for c in conds)
    for act in actions:
        requires = []
        for req in act.get("requires", []):
            if req == "no_receipt" and has_receipt_flag:
                requires.append("has_receipt_false")
            elif req == "within_window" and has_time_window:
                requires.append("within_time_window")
            else:
                requires.append(req)
        act["requires"] = requires
    policy["actions"] = actions
    return policy


def _merge_components(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two component outputs conservatively."""
    merged = {}
    # scope: prefer one with more specified entries
    prim_scope = primary.get("scope", {})
    sec_scope = secondary.get("scope", {})
    def _score_scope(sc: Dict[str, List[str]]) -> int:
        return sum(len(v) for v in sc.values() if v)
    merged["scope"] = prim_scope if _score_scope(prim_scope) >= _score_scope(sec_scope) else sec_scope
    # lists: union
    merged["conditions"] = _merge_lists_unique(primary.get("conditions", []), secondary.get("conditions", []))
    merged["actions"] = _merge_lists_unique(primary.get("actions", []), secondary.get("actions", []))
    merged["exceptions"] = _merge_lists_unique(primary.get("exceptions", []), secondary.get("exceptions", []))
    return merged


def _consensus_metadata(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer non-empty metadata fields, falling back to secondary."""
    md = primary.get("metadata", {}).copy()
    sec = secondary.get("metadata", {})
    for key in ["owner", "effective_date", "domain", "regulatory_linkage"]:
        if key == "regulatory_linkage":
            md[key] = md.get(key) or sec.get(key) or []
        else:
            md[key] = md.get(key) or sec.get(key)
    return {"metadata": md}


def _dynamic_max_tokens(section: Dict[str, Any], default_max: int) -> int:
    """
    Estimate a tighter max_tokens per section based on length.
    Approx tokens ~= len(text)/4; clamp to [64, 512] and never exceed configured max.
    """
    paras = [p.get("text", "") if isinstance(p, dict) else str(p) for p in section.get("paragraphs", [])]
    text = "\n\n".join(paras)
    approx_tokens = max(1, len(text) // 4)
    return min(default_max, 512, max(64, approx_tokens))


def _ingest_stage5(stage5_input: str, output_dir: str, doc_id: str, batch_id: str) -> None:
    """Copy provided Stage 5 runtime JSONs into a dedicated folder under out/."""
    stage5_dir = os.path.join(output_dir, "stage5")
    os.makedirs(stage5_dir, exist_ok=True)
    paths: List[str] = []
    if os.path.isfile(stage5_input):
        paths = [stage5_input]
    elif os.path.isdir(stage5_input):
        for fname in os.listdir(stage5_input):
            if fname.endswith(".json") or fname.endswith(".jsonl"):
                paths.append(os.path.join(stage5_input, fname))
    for src in paths:
        dest_name = f"{doc_id}-{batch_id}-{os.path.basename(src)}"
        shutil.copy(src, os.path.join(stage5_dir, dest_name))


def _generate_stage5(policies: List[Dict[str, Any]], output_dir: str, doc_id: str, batch_id: str) -> None:
    """
    Create basic Stage 5 runtime JSON stubs (pre/during/post-generation) per policy.
    Stored under out/stage5/.
    """
    stage5_dir = os.path.join(output_dir, "stage5")
    os.makedirs(stage5_dir, exist_ok=True)
    path = os.path.join(stage5_dir, f"{doc_id}-{batch_id}-stage5.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for pol in policies:
            pid = pol.get("policy_id")
            actions = pol.get("actions", [])
            logic_rules = []
            for act in actions:
                natural = act.get("source_text") or act.get("action")
                if not natural:
                    continue
                logic_rules.append({"policy_id": pid, "natural_language": natural})
            stage5_obj = {
                "policy_id": pid,
                "pre_generation": {
                    "retrieved_policies": [
                        {"policy_id": pid, "relevance_score": 1.0, "priority_level": None}
                    ]
                },
                "during_generation": {
                    "injected_logic_rules": logic_rules,
                    "priority_guidance": {"highest_active": {"policy_id": pid, "priority_level": None}},
                },
                "post_generation": {
                    "checks": [],
                    "compliance_score": {"weights": {}, "per_check": {}, "final": None},
                    "action": "pass",
                },
            }
            f.write(json.dumps(stage5_obj, ensure_ascii=False))
            f.write("\n")


def run_pipeline(input_path: str, output_dir: str, tenant_id: str, batch_id: str, config: Config, stage5_input: str | None = None) -> None:
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
        max_tokens = _dynamic_max_tokens(sec_dict, cfg_dict["llm"]["max_tokens"])
        local_llm = LLMClient(
            provider=cfg_dict["llm"]["provider"],
            model_id=cfg_dict["llm"]["model_id"],
            temperature=cfg_dict["llm"]["temperature"],
            max_tokens=max_tokens,
            region=cfg_dict["llm"]["region"],
            top_k=cfg_dict["llm"]["top_k"],
            retries=cfg_dict["llm"]["retries"],
            backoff=cfg_dict["llm"]["backoff"],
        )
        double_enabled = cfg_dict.get("double_run", {}).get("enabled", False)

        def _classify_once():
            return pass1_classify.run(sec_dict, local_llm)

        cls = _classify_once()
        if double_enabled:
            cls2 = _classify_once()
            # prefer higher confidence; if tie and any is_policy true, choose that
            if cls2.get("confidence", 0) > cls.get("confidence", 0):
                cls = cls2
            elif cls2.get("confidence", 0) == cls.get("confidence", 0) and cls2.get("is_policy") and not cls.get("is_policy"):
                cls = cls2
        if not cls.get("is_policy"):
            return None
        policy = _init_policy(doc_id, sec_dict)
        policy["processing_status"]["extraction"] = "in_progress"
        policy["provenance"]["passes_used"].append(1)
        def _components_once():
            return pass2_components.run(sec_dict, local_llm)

        comps = _components_once()
        if double_enabled:
            comps2 = _components_once()
            comps = _merge_components(comps, comps2)
            policy["provenance"].setdefault("low_confidence", []).append("double_run_components")
        policy["scope"] = _normalize_scope(comps.get("scope", {}), sec_dict, cfg_dict.get("scope", {}))
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
            },
            "double_run": {"enabled": config.double_run.enabled},
            "scope": {"fallback": config.scope.fallback, "enable_regex": config.scope.enable_regex},
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
            policy = _process_section(
                sec_dict,
                canonical.doc_id,
                {
                    "llm": config.llm.__dict__,
                    "double_run": {"enabled": config.double_run.enabled},
                    "scope": {"fallback": config.scope.fallback, "enable_regex": config.scope.enable_regex},
                },
            )
            if policy:
                policies.append(policy)

    # Pass 4: merge
    policies = pass4_merge.run(policies, llm, sim_threshold=config.merge.similarity_threshold)
    for p in policies:
        if 4 not in p.get("provenance", {}).get("passes_used", []):
            p["provenance"]["passes_used"].append(4)

    # Pass 5: metadata
    for i, pol in enumerate(policies):
        resolver_cfg = config.metadata_resolver.__dict__ if config.metadata_resolver else {}
        if config.double_run.enabled:
            m1 = pass5_metadata.run(pol, canonical.model_dump() if hasattr(canonical, "model_dump") else {}, llm, resolver_cfg)
            m2 = pass5_metadata.run(pol, canonical.model_dump() if hasattr(canonical, "model_dump") else {}, llm, resolver_cfg)
            merged_md = _consensus_metadata(m1, m2)
            m1.update(merged_md)
            policies[i] = m1
            policies[i]["provenance"].setdefault("low_confidence", []).append("double_run_metadata")
        else:
            policies[i] = pass5_metadata.run(pol, canonical.model_dump() if hasattr(canonical, "model_dump") else {}, llm, resolver_cfg)
        policies[i]["provenance"]["passes_used"].append(5)

    # Normalize requires based on conditions
    policies = [_normalize_requires(pol) for pol in policies]

    # Assign policy IDs after domains are inferred
    policies = _assign_policy_ids(policies)

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

    # Stage 5: generate stubs if enabled, ingest if provided
    if config.stage5.generate:
        _generate_stage5(policies, output_dir, canonical.doc_id, batch_id)
    if stage5_input and config.stage5.ingest:
        _ingest_stage5(stage5_input, output_dir, canonical.doc_id, batch_id)

    logger.info(
        "Pipeline completed: %d policies, flagged_pct=%.2f, domains=%s",
        len(policies),
        flagged_pct,
        domains,
    )
    logger.info("Timings: regularization=%.2fs, passes=%.2fs", t_reg, t_pass)
