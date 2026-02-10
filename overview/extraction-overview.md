# Constitution Extraction Pipeline Overview

## Executive Summary
This document describes the complete **Normalization + Extraction pipeline** for transforming company constitution documents into a structured policy base that powers AI chatbot compliance systems. The pipeline consists of two core stages: **Document Normalization** (preprocessing heterogeneous inputs into a canonical representation) and **Policy Extraction** (multi-pass structured extraction of policy components and governance metadata). 

Designed specifically for companies authoring their own AI constitutions, the pipeline prioritizes **one-time high-fidelity processing** over real-time throughput, enabling long-term reuse across deployments with minimal maintenance.

## 1. Document Normalization (Stage 1)

### Purpose
Convert arbitrary document formats (PDFs, Word, scans, HTML, Google Docs exports) into a **single, structure-preserving JSON representation** that downstream extraction can reliably process.

### Why Normalization is Necessary
1. **Format Heterogeneity**: Companies author constitutions in whatever tools they use daily. Even a single company might have v1 as Word, v2 as exported PDF, v3 as Google Doc HTML. Without normalization, extraction logic must handle 5+ formats or rely on brittle LLM "figure it out" parsing.

2. **Structural Fidelity**: Constitutions encode critical constraints in tables (risk tiers), numbered lists (procedures), section hierarchies (priorities). Layout-obliterating OCR or naive text extraction loses this information, crippling decision graph construction and RAG retrieval.

3. **Auditability**: Policy decisions must trace back to exact source locations (page 7, para 3). Normalized output preserves span mappings to original coordinates, enabling legal/compliance review.

4. **Long-term Reuse**: Constitutions change infrequently. Normalization is a **one-time cost per version**, amortized over thousands of runtime queries. Raw document chaos compounds over time; normalization creates a clean, versioned asset.

### Process
```
Raw Input → OCR/Layout (if needed) → Text Cleanup → Structural Parsing → Canonical JSON
```

**Detailed Steps:**
1. **Format Detection & Routing**
   - PDF: Extract embedded text → OCR fallback for images
   - Word/DocX: unzip → parse XML structure  
   - HTML/Markdown: parse DOM → extract semantic blocks
   - Images/Scanned PDF: OCR + layout detection

2. **OCR + Layout Reconstruction** (scans/images)
   - **Tool**: Google Document AI / AWS Textract / Mistral OCR / Adobe PDF Extract
   - **Output**: Text blocks + bounding boxes + table structure + reading order
   - **Key**: Preserve paragraphs, headings, tables as explicit objects

3. **Text Normalization**
   - Remove OCR artifacts (broken hyphenation, repeated headers/footers)
   - Normalize whitespace, bullets, numbering, quotes
   - **Preserve**: Paragraph breaks, section hierarchy, table cell relationships

4. **Structural Normalization**
```json
{
  "doc_id": "constitution_v2",
  "pages": [...],
  "sections": [
    {
      "id": "sec1.2",
      "level": 2,
      "heading": "Privacy Requirements",
      "paragraphs": [...],
      "tables": [...],
      "children": ["sec1.2.1"]
    }
  ],
  "spans": [{"start": 1234, "end": 1567, "page": 5, "section": "sec3.2"}]
}
```

### Tradeoffs & Why They Don't Apply Here
| Concern | Industry Problem | Our Solution |
|---------|------------------|-------------|
| **Latency/Cost** | Real-time OCR @ scale | One-time processing; store normalized corpus |
| **OCR Quality** | Uncontrollable scans | Customer fixes low-quality during onboarding |
| **Security** | Multi-tenant PII | Single-tenant proprietary files only |
| **Complexity** | Ongoing maintenance | Versioned corpus; edit only when constitution changes |

## 2. Policy Extraction (Stage 2)

### Input
Normalized JSON from Stage 1.

### Output
Structured policy JSONL (one object per line) following the enrichment pattern:
```json
{
  "schema_version": "1.0",
  "processing_status": {
    "extraction": "complete",
    "formalization": "pending",
    "conflict_detection": "pending",
    "layer_assignment": "pending"
  },
  "policy_id": "POL-REFUND-001",
  "origin": "explicit",
  "doc_id": "constitution_v2",
  "scope": {
    "customer_segments": ["all"],
    "product_categories": ["all"],
    "channels": ["online", "in-store"],
    "regions": ["all"]
  },
  "conditions": [
    {"type": "time_window", "value": 30, "unit": "days", "operator": "<=", "target": "general", "source_text": "Customers may return items within 30 days of purchase"},
    {"type": "time_window", "value": 15, "unit": "days", "operator": "<=", "target": "electronics", "source_text": "Electronics must be returned within 15 days"},
    {"type": "boolean_flag", "value": true, "parameter": "has_receipt", "source_text": "Receipt is required for a cash refund"}
  ],
  "actions": [
    {"type": "required", "action": "full_refund", "requires": ["has_receipt", "within_window"], "source_text": "Customers may return items within 30 days of purchase for a full refund"},
    {"type": "fallback", "action": "store_credit", "requires": ["no_receipt"], "source_text": "Items without receipt receive store credit only"}
  ],
  "exceptions": [
    {"description": "Electronics: 15-day override on 30-day window", "source_text": "Electronics must be returned within 15 days"}
  ],
  "entities": [
    {"type": "date", "value": "30 days", "span": {"start": 128, "end": 135, "page": 2, "section_id": "sec2.3"}},
    {"type": "date", "value": "15 days", "span": {"start": 182, "end": 188, "page": 3, "section_id": "sec4.1"}}
  ],
  "metadata": {
    "source": "constitution_v2#sec4.1",
    "owner": "Customer Service Dept",
    "effective_date": "2024-01-15",
    "domain": "refund",
    "regulatory_linkage": ["FTC Cooling-Off Rule"]
  },
  "provenance": {
    "passes_used": [1, 2, 3, 4, 5, 6],
    "low_confidence": [],
    "confidence_score": 0.9,
    "source_spans": [
      {"start": 0, "end": 260, "page": 2, "section_id": "sec2.3"},
      {"start": 261, "end": 520, "page": 3, "section_id": "sec4.1"}
    ]
  }
}
```

### Multi-Pass Architecture (Parallel per Section)

**Pass 1: Section Classification**
```
Input: Normalized section JSON
Prompt: "Policy-relevant (policy/procedure/guideline) or non-policy (intro/defs/background)?"
Threshold: confidence > 0.7 → proceed to extraction
```

**Pass 2: Component Extraction** (JSON Schema Enforced)
```
Schema (CUAD-adapted for constitutions):
- scope: who/what applies (chatbots, topics, user types)
- conditions: triggers/prerequisites/time constraints  
- actions: required/prohibited behaviors
- exceptions: overrides/edge cases/priorities

Example Input: "Chatbots must never disclose PII unless user provides explicit written consent or legal subpoena received within 30 days."
→ {scope: "chatbots", conditions: ["explicit_written_consent OR legal_subpoena"], 
   actions: ["never_disclose_PII"], exceptions: ["subpoena_30days"]}
```

**Pass 3: Entity Extraction**
```
Hybrid: spaCy/regex (dates/money/names) + LLM (ambiguous)
Output: Annotated components with typed entities
```

**Pass 4: Global Merge + Deduplication**
```
- Embedding similarity > 0.9 → LLM resolve overlaps
- Cross-reference linking ("see Section 4.1")
- Temporal grouping (related effective dates)
```

**Pass 5: Governance Metadata**
```
LLM prompt across full document context:
- origin: doc_id + section_id
- owner: responsible team/person  
- effective_date: activation date
- category: privacy/escalation/content_moderation/etc.
- priority_link: regulations/values ("GDPR", "customer-first")
```

**Pass 6: Validation**
```
- LLM self-critique: "Complete? Consistent? Missing scope?"
- Rule checks: no empty components, valid dates
- Flag: >20% issues → human review
```

## 3. Storage & Indexing

**Policy Base**: Versioned policy repository (PostgreSQL + vector embeddings)
**RAG Index**: Section-level + policy-level embeddings for runtime retrieval
**Graph DB**: Policy relationships, cross-references, hierarchy
**Audit Trail**: Every extraction maps back to exact source spans

## 4. Update Workflow

```
Constitution Edit → Re-normalize → Re-extract → Diff policies → 
Human review changes → Update policy base → Propagate to enforcement layers
```

## 5. Key Design Principles

1. **One-time Investment**: Normalize once, reuse forever
2. **Human-in-the-Loop**: Low-confidence extractions flagged automatically  
3. **Traceability**: Every policy traces to source spans + version
4. **Schema Enforcement**: JSON schemas prevent malformed outputs
5. **Parallel Processing**: Per-section extraction scales linearly

## 6. Expected Outcomes

- **Extraction F1**: ~87% (PolicyLLM target) on normalized input
- **Human Review**: <10% of policies flagged
- **Maintenance**: Edit only when constitution changes
- **Deployment**: Clean policy base → formalization → enforcement layers

This architecture transforms constitution authoring from ad-hoc document management into a structured, reusable asset that reliably powers production AI compliance systems.
