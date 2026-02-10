"""Configuration loader for the extraction pipeline."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import yaml


@dataclass
class LLMConfig:
    provider: str
    model_id: str
    region: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4096
    top_k: Optional[int] = None
    retries: int = 2
    backoff: float = 1.5


@dataclass
class RegularizationConfig:
    ocr_confidence_threshold: float = 0.8
    max_pages: int = 500


@dataclass
class MergeConfig:
    similarity_threshold: float = 0.9


@dataclass
class ValidationConfig:
    confidence_threshold: float = 0.7
    flag_issue_rate: float = 0.2


@dataclass
class DocAIConfig:
    project_id: str
    location: str
    processor_id: str
    processor_version: Optional[str] = None


@dataclass
class ParallelConfig:
    enabled: bool = False
    num_workers: Optional[int] = None


@dataclass
class Config:
    llm: LLMConfig
    regularization: RegularizationConfig
    merge: MergeConfig
    validation: ValidationConfig
    docai: Optional[DocAIConfig] = None
    parallel: ParallelConfig = field(default_factory=ParallelConfig)


def _merge_defaults(data: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = defaults.copy()
    merged.update({k: v for k, v in data.items() if v is not None})
    return merged


def load_config(path: str) -> Config:
    """Load YAML config into typed Config."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    llm_defaults = {
        "provider": "bedrock_claude",
        "model_id": "",
        "region": "us-east-2",
        "temperature": 0.1,
        "max_tokens": 4096,
        "top_k": None,
        "retries": 2,
        "backoff": 1.5,
    }
    reg_defaults = {"ocr_confidence_threshold": 0.8, "max_pages": 500}
    merge_defaults = {"similarity_threshold": 0.9}
    val_defaults = {"confidence_threshold": 0.7, "flag_issue_rate": 0.2}
    par_defaults = {"enabled": False, "num_workers": None}

    llm_cfg = LLMConfig(**_merge_defaults(raw.get("llm", {}), llm_defaults))
    reg_cfg = RegularizationConfig(**_merge_defaults(raw.get("regularization", {}), reg_defaults))
    merge_cfg = MergeConfig(**_merge_defaults(raw.get("merge", {}), merge_defaults))
    val_cfg = ValidationConfig(**_merge_defaults(raw.get("validation", {}), val_defaults))
    docai_raw = raw.get("docai")
    docai_cfg = DocAIConfig(**docai_raw) if docai_raw else None
    par_cfg = ParallelConfig(**_merge_defaults(raw.get("parallel", {}), par_defaults))

    return Config(
        llm=llm_cfg,
        regularization=reg_cfg,
        merge=merge_cfg,
        validation=val_cfg,
        docai=docai_cfg,
        parallel=par_cfg,
    )
