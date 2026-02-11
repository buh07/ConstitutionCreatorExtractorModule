import json
import os
import sys
import types
from typing import Any, Dict

import pytest

# Stub boto3/botocore to avoid heavy deps
sys.modules.setdefault("boto3", types.ModuleType("boto3"))
botocore = types.ModuleType("botocore")
botocore.exceptions = types.SimpleNamespace(BotoCoreError=Exception, ClientError=Exception, NoCredentialsError=Exception)
sys.modules.setdefault("botocore", botocore)
sys.modules.setdefault("botocore.exceptions", botocore.exceptions)

try:
    import pydantic  # noqa: F401
except Exception:
    pytest.skip("pydantic not installed", allow_module_level=True)

# Avoid importing real LLM clients by stubbing pipeline.LLMClient
import src.pipeline as pipeline
from src.config import (
    Config,
    LLMConfig,
    MergeConfig,
    MetadataResolverConfig,
    ParallelConfig,
    RegularizationConfig,
    ValidationConfig,
)


class StubLLM:
    """Stub LLM client returning deterministic JSON for prompts."""

    def invoke_json(self, prompt: str, schema=None) -> Dict[str, Any]:
        lower = prompt.lower()
        if "classify section" in lower or "policy extraction assistant" in lower:
            return {"is_policy": True, "confidence": 0.95, "reason": "stubbed policy"}
        if "extract structured fields" in lower or "schema" in lower:
            return {
                "scope": {
                    "customer_segments": ["all"],
                    "product_categories": ["all"],
                    "channels": ["all"],
                    "regions": ["all"],
                },
                "conditions": [
                    {"type": "time_window", "value": 30, "unit": "days", "operator": "<=", "target": "general", "source_text": "within 30 days"},
                    {"type": "time_window", "value": 15, "unit": "days", "operator": "<=", "target": "electronics", "source_text": "electronics 15 days"},
                ],
                "actions": [
                    {"type": "required", "action": "full_refund", "requires": ["has_receipt", "within_window"], "source_text": "full refund with receipt"},
                    {"type": "fallback", "action": "store_credit", "requires": ["no_receipt"], "source_text": "store credit"},
                ],
                "exceptions": [
                    {"description": "Electronics override", "source_text": "electronics 15 days"}
                ],
            }
        if "metadata annotator" in lower:
            return {
                "owner": "Customer Service",
                "effective_date": None,
                "domain": "refund",
                "regulatory_linkage": [],
            }
        if "validation assistant" in lower:
            return {"issues": [], "needs_review": False, "confidence": 0.9}
        # default: return components with broad scope
        return {
            "scope": {
                "customer_segments": ["all"],
                "product_categories": ["all"],
                "channels": ["all"],
                "regions": ["all"],
            },
            "conditions": [],
            "actions": [],
            "exceptions": [],
        }


@pytest.fixture
def stub_config() -> Config:
    return Config(
        llm=LLMConfig(
            provider="ollama",
            model_id="mistral:latest",
            temperature=0.1,
            max_tokens=512,
            region="us-east-2",
            top_k=None,
            retries=0,
            backoff=1.0,
        ),
        regularization=RegularizationConfig(),
        merge=MergeConfig(similarity_threshold=0.9),
        validation=ValidationConfig(),
        docai=None,
        parallel=ParallelConfig(enabled=False, num_workers=None),
        metadata_resolver=MetadataResolverConfig(),
    )


def test_end_to_end(tmp_path, monkeypatch, stub_config):
    # Monkeypatch LLMClient in pipeline to use stubbed implementation
    monkeypatch.setattr(pipeline, "LLMClient", lambda *args, **kwargs: StubLLM())

    input_path = os.path.join("sample_docs", "sample.txt")
    pipeline.run_pipeline(input_path, str(tmp_path), tenant_id="tenant", batch_id="sample", config=stub_config)

    # Locate output files
    jsonl_files = [f for f in os.listdir(tmp_path) if f.endswith(".jsonl")]
    index_files = [f for f in os.listdir(tmp_path) if f.endswith("-index.json")]
    assert jsonl_files, "No policies JSONL written"
    assert index_files, "No index JSON written"

    with open(os.path.join(tmp_path, jsonl_files[0]), "r", encoding="utf-8") as f:
        policies = [json.loads(line) for line in f if line.strip()]
    assert len(policies) == 1
    pol = policies[0]
    assert pol["scope"]["customer_segments"] == ["all"]
    assert pol["metadata"]["domain"] == "refund"
    assert pol["processing_status"]["extraction"] in {"complete", "failed"}

    with open(os.path.join(tmp_path, index_files[0]), "r", encoding="utf-8") as f:
        index = json.load(f)
    assert index["num_policies"] == 1
    assert index["domains"].get("refund") == 1
