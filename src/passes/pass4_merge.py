"""Pass 4: merge/deduplicate policies across sections with evidence aggregation."""
import os
from typing import Any, Dict, List, Tuple

_EMB_MODEL = None
np = None


def _load_emb_model():
    global _EMB_MODEL, np
    if _EMB_MODEL is not None:
        return _EMB_MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore

        _EMB_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        globals()["np"] = np
    except Exception:
        _EMB_MODEL = None
    return _EMB_MODEL


def _canon_scope(scope: Dict[str, List[str]]) -> Tuple:
    return (
        tuple(sorted(scope.get("customer_segments", []))),
        tuple(sorted(scope.get("product_categories", []))),
        tuple(sorted(scope.get("channels", []))),
        tuple(sorted(scope.get("regions", []))),
    )


def _canon_actions(actions: List[Dict[str, Any]]) -> Tuple:
    return tuple(sorted([a.get("action", "") for a in actions]))


def _canon_conditions(conditions: List[Dict[str, Any]]) -> Tuple:
    canon = []
    for c in conditions:
        canon.append(
            (
                c.get("type"),
                c.get("value"),
                c.get("unit"),
                c.get("operator"),
                c.get("target"),
                c.get("parameter"),
            )
        )
    return tuple(sorted(canon))


def _merge_lists_unique(existing: List[Any], new_items: List[Any]) -> List[Any]:
    seen = set()
    merged: List[Any] = []
    for item in existing + new_items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _text_signature(pol: Dict[str, Any]) -> str:
    scope = pol.get("scope", {})
    conditions = pol.get("conditions", [])
    actions = pol.get("actions", [])
    exceptions = pol.get("exceptions", [])
    parts = [
        "scope:" + " ".join(scope.get("customer_segments", []) + scope.get("product_categories", []) + scope.get("channels", []) + scope.get("regions", [])),
        "conditions:" + " ".join([str(c) for c in conditions]),
        "actions:" + " ".join([str(a) for a in actions]),
        "exceptions:" + " ".join([str(e) for e in exceptions]),
    ]
    return "\n".join(parts)


def _proximity_bonus(base: Dict[str, Any], other: Dict[str, Any]) -> int:
    """Cheap proximity prior: bonus evidence if they share section_id in source spans."""
    base_spans = base.get("provenance", {}).get("source_spans", [])
    other_spans = other.get("provenance", {}).get("source_spans", [])
    base_sections = {s.get("section_id") for s in base_spans if isinstance(s, dict)}
    other_sections = {s.get("section_id") for s in other_spans if isinstance(s, dict)}
    if base_sections & other_sections:
        return 1
    return 0


def run(policies: List[Dict[str, Any]], llm_client: Any, sim_threshold: float = 0.9) -> List[Dict[str, Any]]:
    """
    Aggregate duplicate/overlapping policies by canonical scope/conditions/actions (strict key),
    then optional semantic merge using embeddings to combine near-duplicates (same domain/doc).
    Evidence counts and provenance are aggregated. For semantically similar clusters,
    optionally ask LLM to reconcile if provided.
    """
    buckets: Dict[Tuple, Dict[str, Any]] = {}

    for pol in policies:
        scope = pol.get("scope", {})
        conditions = pol.get("conditions", [])
        actions = pol.get("actions", [])
        metadata = pol.get("metadata", {})
        key = (
            pol.get("doc_id"),
            _canon_scope(scope),
            _canon_conditions(conditions),
            _canon_actions(actions),
            metadata.get("domain"),
        )

        if key not in buckets:
            # Initialize bucket with a copy
            buckets[key] = pol
            # Ensure evidence_count present
            if "provenance" in buckets[key]:
                buckets[key]["provenance"]["evidence_count"] = buckets[key]["provenance"].get("evidence_count", 1)
            continue

        existing = buckets[key]
        # Merge provenance evidence_count and source_spans
        prov = existing.get("provenance", {})
        new_prov = pol.get("provenance", {})
        prov["evidence_count"] = prov.get("evidence_count", 1) + new_prov.get("evidence_count", 1)
        prov["passes_used"] = _merge_lists_unique(prov.get("passes_used", []), new_prov.get("passes_used", []))
        prov["low_confidence"] = _merge_lists_unique(prov.get("low_confidence", []), new_prov.get("low_confidence", []))
        prov["source_spans"] = _merge_lists_unique(prov.get("source_spans", []), new_prov.get("source_spans", []))
        # Merge exceptions/actions/conditions/entities to avoid loss
        existing["actions"] = _merge_lists_unique(existing.get("actions", []), actions)
        existing["conditions"] = _merge_lists_unique(existing.get("conditions", []), conditions)
        existing["exceptions"] = _merge_lists_unique(existing.get("exceptions", []), pol.get("exceptions", []))
        existing["entities"] = _merge_lists_unique(existing.get("entities", []), pol.get("entities", []))
        existing["provenance"] = prov
        buckets[key] = existing

    merged = list(buckets.values())

    # Semantic merge optional; set ENABLE_EMBED_MERGE=1 to enable
    if os.getenv("ENABLE_EMBED_MERGE", "0") != "1":
        return merged
    if not _load_emb_model() or not np:
        return merged

    texts = [_text_signature(p) for p in merged]
    embeddings = _EMB_MODEL.encode(texts, normalize_embeddings=True)
    used = [False] * len(merged)
    final: List[Dict[str, Any]] = []

    for i, pol in enumerate(merged):
        if used[i]:
            continue
        used[i] = True
        # start cluster with pol
        cluster = [pol]
        for j in range(i + 1, len(merged)):
            if used[j]:
                continue
            # only consider same domain/doc_id to avoid cross-doc merges
            if pol.get("doc_id") != merged[j].get("doc_id"):
                continue
            if pol.get("metadata", {}).get("domain") != merged[j].get("metadata", {}).get("domain"):
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]))
            if sim >= sim_threshold:
                cluster.append(merged[j])
                used[j] = True
        if len(cluster) == 1:
            final.append(pol)
            continue
        # Merge cluster into first item, optionally via LLM reconciliation
        base = cluster[0]
        for other in cluster[1:]:
            prov = base.get("provenance", {})
            oprov = other.get("provenance", {})
            prov["evidence_count"] = prov.get("evidence_count", 1) + oprov.get("evidence_count", 1) + _proximity_bonus(base, other)
            prov["passes_used"] = _merge_lists_unique(prov.get("passes_used", []), oprov.get("passes_used", []))
            prov["low_confidence"] = _merge_lists_unique(prov.get("low_confidence", []), oprov.get("low_confidence", []))
            prov["source_spans"] = _merge_lists_unique(prov.get("source_spans", []), oprov.get("source_spans", []))
            base["actions"] = _merge_lists_unique(base.get("actions", []), other.get("actions", []))
            base["conditions"] = _merge_lists_unique(base.get("conditions", []), other.get("conditions", []))
            base["exceptions"] = _merge_lists_unique(base.get("exceptions", []), other.get("exceptions", []))
            base["entities"] = _merge_lists_unique(base.get("entities", []), other.get("entities", []))
            base["provenance"] = prov
        if llm_client:
            merge_prompt = """You are merging two policy JSON objects with same domain/doc. Produce a single JSON with merged scope/conditions/actions/exceptions/entities. Preserve all information; deduplicate obvious duplicates; keep structured fields intact."""
            try:
                merged_llm = llm_client.invoke_json(
                    f"{merge_prompt}\n\nPolicy A:\n{base}\n\nPolicies to merge:\n{cluster[1:]}"
                )
                if isinstance(merged_llm, dict):
                    base = merged_llm
            except Exception:
                pass
        final.append(base)

    return final
