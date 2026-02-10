"""Policy JSON schemas (Pydantic models) for extraction outputs (enrichment pattern)."""
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from .canonical import Span


class ProcessingStage(str):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class ProcessingStatus(BaseModel):
    extraction: str = ProcessingStage.PENDING
    formalization: str = ProcessingStage.PENDING
    conflict_detection: str = ProcessingStage.PENDING
    layer_assignment: str = ProcessingStage.PENDING


class Scope(BaseModel):
    customer_segments: List[str] = Field(default_factory=list)
    product_categories: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)


class Condition(BaseModel):
    type: str  # time_window | amount_threshold | customer_tier | product_category | geographic | boolean_flag | role_requirement | other
    value: Optional[Union[float, int, str, bool]] = None
    unit: Optional[str] = None
    operator: Optional[str] = None  # <=, >=, ==, etc.
    target: Optional[str] = None  # e.g., electronics, VIP
    parameter: Optional[str] = None  # e.g., has_receipt
    source_text: Optional[str] = None


class Action(BaseModel):
    type: str  # required | prohibited | fallback | conditional | discovered_pattern | other
    action: str
    requires: List[str] = Field(default_factory=list)
    source_text: Optional[str] = None


class ExceptionItem(BaseModel):
    description: str
    source_text: Optional[str] = None


class Entity(BaseModel):
    type: str  # date | amount | role | product | percent | other
    value: str
    span: Optional[Span] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class PolicyMetadata(BaseModel):
    source: str  # doc_id#section_id
    owner: Optional[str] = None
    effective_date: Optional[str] = None  # YYYY-MM-DD or raw string if uncertain
    domain: Optional[str] = None  # refund | privacy | escalation | security | hr | other
    regulatory_linkage: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class PolicyProvenance(BaseModel):
    passes_used: List[int] = Field(default_factory=list)
    low_confidence: List[str] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    source_spans: List[Span] = Field(default_factory=list)
    evidence_count: int = Field(1, ge=1)


class Policy(BaseModel):
    schema_version: str = "1.0"
    processing_status: ProcessingStatus = Field(default_factory=ProcessingStatus)
    policy_id: str
    origin: str  # explicit | implicit
    doc_id: str
    scope: Scope
    conditions: List[Condition] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    exceptions: List[ExceptionItem] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    metadata: PolicyMetadata
    provenance: PolicyProvenance
    # Future enrichment stages
    formal: Optional[Dict[str, Union[str, list, dict]]] = None
    conflicts: Optional[List[Dict[str, Union[str, int, float, dict]]]] = None
    layer_assignment: Optional[Dict[str, Union[str, float, dict, list]]] = None


class PolicyIndex(BaseModel):
    doc_id: str
    batch_id: str
    num_policies: int = Field(..., ge=0)
    flagged_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    domains: Dict[str, int] = Field(default_factory=dict)
