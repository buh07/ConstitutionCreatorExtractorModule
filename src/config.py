"""Configuration loader for the extraction pipeline."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
class DoubleRunConfig:
    enabled: bool = False


@dataclass
class MetadataResolverConfig:
    use_regex: bool = True
    tenant_owner_default: Optional[str] = None
    tenant_effective_date_default: Optional[str] = None
    tenant_regulatory_linkage_default: List[str] = field(default_factory=list)
    domain_defaults: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ScopeConfig:
    fallback: str = "all"  # all | unknown | none
    enable_regex: bool = True


@dataclass
class Stage5Config:
    generate: bool = False  # write Stage 5 runtime JSONs
    ingest: bool = True  # allow ingesting provided Stage 5 JSONs


@dataclass
class Config:
    llm: LLMConfig
    regularization: RegularizationConfig
    merge: MergeConfig
    validation: ValidationConfig
    docai: Optional[DocAIConfig] = None
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    double_run: DoubleRunConfig = field(default_factory=DoubleRunConfig)
    stage5: Stage5Config = field(default_factory=Stage5Config)
    metadata_resolver: MetadataResolverConfig = field(default_factory=MetadataResolverConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)


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
    dr_defaults = {"enabled": False}
    s5_defaults = {"generate": False, "ingest": True}
    md_defaults = {
        "use_regex": True,
        "tenant_owner_default": None,
        "tenant_effective_date_default": None,
        "tenant_regulatory_linkage_default": [],
        "domain_defaults": {},
    }
    scope_defaults = {"fallback": "all", "enable_regex": True}

    llm_cfg = LLMConfig(**_merge_defaults(raw.get("llm", {}), llm_defaults))
    reg_cfg = RegularizationConfig(**_merge_defaults(raw.get("regularization", {}), reg_defaults))
    merge_cfg = MergeConfig(**_merge_defaults(raw.get("merge", {}), merge_defaults))
    val_cfg = ValidationConfig(**_merge_defaults(raw.get("validation", {}), val_defaults))
    docai_raw = raw.get("docai")
    docai_cfg = DocAIConfig(**docai_raw) if docai_raw else None
    par_cfg = ParallelConfig(**_merge_defaults(raw.get("parallel", {}), par_defaults))
    dr_cfg = DoubleRunConfig(**_merge_defaults(raw.get("double_run", {}), dr_defaults))
    s5_cfg = Stage5Config(**_merge_defaults(raw.get("stage5", {}), s5_defaults))
    md_cfg = MetadataResolverConfig(**_merge_defaults(raw.get("metadata_resolver", {}), md_defaults))
    scope_cfg = ScopeConfig(**_merge_defaults(raw.get("scope", {}), scope_defaults))

    return Config(
        llm=llm_cfg,
        regularization=reg_cfg,
        merge=merge_cfg,
        validation=val_cfg,
        docai=docai_cfg,
        parallel=par_cfg,
        double_run=dr_cfg,
        stage5=s5_cfg,
        metadata_resolver=md_cfg,
        scope=scope_cfg,
    )
