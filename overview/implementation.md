# Policy Extraction Pipeline Implementation Guide (Group 1)

## Overview
Detailed **end-to-end implementation** for Policy Extraction (§3.2): multi-pass LLM pipeline producing structured policy components + governance metadata from regularized documents.

**Scope**: Group 1 only. Output → Group 2 formalization (decision graphs/SMT).

**Targets**: 
- Extraction F1: ~87% (vs single-pass GPT-4o: 79.8%)
- Human review: <10% policies
- Runtime: 2-5min/doc (100 pages)

## High-Level Flow
```
Raw Docs → REGULARIZATION → Canonical JSON → EXTRACTION (6 Passes) → Policy JSONL + Index
```

## 1. Document Regularization

### Input Formats & Tools
| Format | Priority | Library/API | Latency (100pg) | Cost |
|--------|----------|-------------|-----------------|------|
| PDF Native | 1 | PyMuPDF (fitz) | 10s | $0 |
| PDF Scanned | 2 | Google Document AI v2 (GCP) | 45s | $0.015 ($1.50/1000pg) |
| Word/DocX | 3 | python-docx | 15s | $0 |
| Markdown/HTML | 4 | BeautifulSoup + markdown | 8s | $0 |
| Plain TXT | 5 | Direct | 2s | $0 |

### Canonical JSON Output
```json
{
  "doc_id": "sha256_hash",
  "filename": "policy_v3.pdf",
  "provenance": {
    "method": "pdf_native|ocr|docx|md|txt",
    "ocr_confidence": 0.92,
    "pages": 47,
    "tool": "document_ai_v2.0"
  },
  "pages": [{"page_num":1, "text_blocks":[], "tables":[]}],
  "sections": [
    {
      "section_id": "sec1.2",
      "level": 2,
      "heading": "Privacy Requirements",
      "paragraphs": [{"text":"...", "span":{"start":1234,"end":1567}}],
      "tables": [{"rows":[[]], "span":{}}],
      "children": ["sec1.2.1"]
    }
  ],
  "full_text": "complete text"
}
```

**Implementation**:
```python
def regularize(filename: str) -> dict:
    if filename.endswith('.pdf'):
        if is_text_extractable(filename):  # PyMuPDF check
            return pdf_native(filename)
        else:
            return document_ai_ocr(filename)  # Google Document AI (config: project/location/processor)
    # ... docx, md, etc.
```

**Regularization Cost**: $0.015/doc (avg, assuming 20% scanned).

## 2. LLM Configuration

| Model | Provider | Input $ | Output $ | Latency/call | Notes |
|-------|----------|---------|----------|--------------|-------|
| `mistral:latest` | Ollama (local) | $0 | $0 | local | Default until API keys configured |
| `gpt-4o-2024-12-17` | OpenAI | $2.50/M | $10.00/M | 2-5s | Cloud option |
| `claude-3-5-sonnet-20241022` | Anthropic | $3.00/M | $15.00/M | 3-7s | Cloud option |
| `claude-sonnet-4.5` | AWS Bedrock | N/A (metered by Bedrock) | N/A | 3-7s | Use Bedrock ARN + region |

**Settings**: temp=0.1, max_tokens=4096, `response_format={"type": "json_object"}`

**Local default**: Use `provider=ollama`, `model_id=mistral:latest` for cost-free local runs until API keys are provided, then swap to cloud providers as needed.

**Bedrock wiring**: Set `provider=bedrock_claude`, `model_id=arn:aws:bedrock:us-east-2:660201002087:inference-profile/global.anthropic.claude-sonnet-4-5-20250929-v1:0`, `region=us-east-2`, optional `top_k=250`, `performance=standard`. Auth via AWS credential chain (no keys in code).

**OpenAI/Anthropic wiring**: Set `provider=chatgpt` or `provider=anthropic` and supply API keys via env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Response format is JSON; retries/backoff handled in `LLMClient`.

**LLM output validation**: Each pass calls `LLMClient.invoke_json` with a Pydantic schema for the expected JSON shape (classification, components, metadata, validation). Validation errors trigger retries/fail-fast, reducing malformed outputs and keeping the enrichment schema consistent.

**System Prefix** (all passes):
```
You are a precise policy extraction system for enterprise compliance.
Extract ONLY from the provided section text. Follow JSON schema exactly.
Flag uncertainty in "reason" field. Never hallucinate.
```

**Per-doc cost breakdown** (100pg, 120 sections, 70% policy-relevant):
```
Pass 1: 120 calls × 100tok/call = 12k tok → $0.10
Pass 2: 84 calls × 800tok = 67k → $0.35  
Pass 3: Hybrid (20% LLM) → $0.05
Pass 5: 84 calls × 400tok = 34k → $0.18
Pass 6: 84 calls × 200tok = 17k → $0.09
TOTAL LLM: ~$0.77/doc
```

## 3. Multi-Pass Extraction (Parallel per Section)

**Process**: `for section in canonical.sections: pipeline(section)`

### Pass 1: Section Classification
**Input**: `{"section_id": "...", "heading": "...", "paragraphs": [...]}`  
**Prompt** (150tok):
```
Classify section: policy-relevant (policy/procedure/guideline) OR non-policy (intro/defs/background)?
{"is_policy": bool, "confidence": 0.0-1.0, "reason": "1 sentence"}
```
**Output**: Skip 30% sections (non-policy)  
**Cost**: $0.10/doc  
**Time**: 10s total

### Pass 2: Component Extraction
**Input**: Full section text (~500 words)  
**Schema**:
```json
{
  "scope": "string (who/what applies: customers/products/etc)",
  "conditions": ["list: triggers/prereqs/time/money constraints"],
  "actions": ["list: required OR prohibited behaviors"],
  "exceptions": ["list: overrides/edge cases/priorities"],
  "extraction_notes": "any ambiguities"
}
```
**Error handling**: `{"error": "insufficient_policy_content"}`  
**Cost**: $0.35/doc  
**Time**: 20s per pass

### Pass 3: Entity Extraction (Hybrid)
**Non-LLM first** (90% coverage, 2s):
```python
PATTERNS = {
    "date": r"\b(Jan|Feb)\w* \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}\b",
    "amount": r"\$\d+(?:,\d{3})*(?:\.\d{2})?",
    "percent": r"\d+(?:\.\d+)?\%"
}
nlp = spacy.load("en_core_web_sm")
```
**LLM fallback** (ambiguous cases):  
`Tag: [{"type":"date|amount|role|product", "value":"...", "span":{"start":123,"end":156}}]`  
**Cost**: $0.05/doc  
**Time**: 10s

### Pass 4: Global Merge/Dedup (Batch)
**Input**: All Pass2 outputs from doc  
1. Embed components (`sentence-transformers/all-MiniLM-L6-v2`)
2. Cosine sim > 0.90 → LLM: `{"merge": true, "canonical_components": {...}}`
3. Cross-ref: "see §4.1" → link metadata  
**Cost**: $0.10/doc  
**Time**: 30s

### Pass 5: Governance Metadata
**Input**: Policy components + full doc context  
**Schema**:
```json
{
  "source": "doc_id#sec1.2",
  "owner": "Dept/Team (infer conservatively or 'unknown')",
  "effective_date": "YYYY-MM-DD (parse or null)",
  "domain": "refund|privacy|escalation|security|hr|other",
  "regulatory_linkage": "GDPR|HIPAA|SEC|FTC|null",
  "confidence": 0-1
}
```
**Cost**: $0.18/doc  
**Time**: 15s per policy

### Pass 6: Validation + Flagging
**Rules** (0.5s): Empty fields? Invalid dates?  
**LLM** (200tok): `"Is complete/consistent? Issues?"`  
**Flag thresholds**: conf<0.7 OR >20% issues OR owner='unknown'  
**Cost**: $0.09/doc  
**Time**: 10s

## 4. Output Storage (JSONL, Enrichment Pattern)

Per-doc: `.../{doc_id}/{batch_id}.jsonl`, one JSON object per line. Follows the enrichment pattern (common header + structured components) from `overview/Output Format Definition JSON Enrichment Pattern.md`. Example Stage 1 (Extraction) object:

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
    {"type": "time_window", "value": 15, "unit": "days", "operator": "<=", "target": "electronics", "source_text": "Electronics must be returned within 15 days"}
  ],
  "actions": [
    {"type": "required", "action": "full_refund", "requires": ["has_receipt", "within_window"], "source_text": "Customers may return items within 30 days of purchase for a full refund"},
    {"type": "fallback", "action": "store_credit", "requires": ["no_receipt"], "source_text": "Items without receipt receive store credit only"}
  ],
  "exceptions": [
    {"description": "Electronics: 15-day override on 30-day window", "source_text": "Electronics must be returned within 15 days"}
  ],
  "entities": [
    {"type": "date", "value": "30 days", "span": {"start": 128, "end": 135, "page": 2, "section_id": "sec2.3"}}
  ],
  "metadata": {
    "source": "constitution_v2#sec2.3",
    "owner": "Customer Service Dept",
    "effective_date": "2024-01-15",
    "domain": "refund",
    "regulatory_linkage": ["FTC Cooling-Off Rule"]
  },
  "provenance": {
    "passes_used": [1, 2, 3, 4, 5, 6],
    "low_confidence": [],
    "confidence_score": 0.90,
    "source_spans": [{"start": 0, "end": 260, "page": 2, "section_id": "sec2.3"}]
  }
}
```

Later stages enrich the same object in place (add `formal`, `conflicts`, `layer_assignment`), never mutating prior fields. No separate index file is required under this pattern.

## 5. Complete Cost/Runtime Table (100-Page Doc)

| Stage | Time | LLM Calls | Input Tok | Output Tok | Cost |
|-------|------|-----------|-----------|------------|------|
| Regularization | 45s | 0 | - | - | $0.015 |
| Pass 1 | 10s | 120 | 12k | 6k | $0.10 |
| Pass 2 | 45s | 84 | 67k | 25k | $0.35 |
| Pass 3 | 10s | 17 | 5k | 3k | $0.05 |
| Pass 4 | 30s | 10 | 8k | 4k | $0.10 |
| Pass 5 | 35s | 84 | 34k | 12k | $0.18 |
| Pass 6 | 10s | 84 | 17k | 8k | $0.09 |
| **Total** | **3:15** | **399** | **143k** | **58k** | **$0.92** |

**Scaling**:
- 10 pages: ~$0.10, 45s
- 50 pages: ~$0.45, 2.5min
- 100 pages: ~$0.92, 3.3min
- 500 pages: ~$4.60, 16min (parallel: 4min on 4-core)
- 1000 pages: ~$9.20, 32min (parallel: 8min on 4-core)

## 6. Code Stack
```
extraction/
├── regularize.py      # PyMuPDF/documentai/docx/BS4
├── llm_client.py      # OpenAI/Anthropic + jsonformer
├── passes/
│   ├── pass1_classify.py
│   ├── pass2_components.py
│   ├── pass3_entities.py
│   ├── pass4_merge.py
│   ├── pass5_metadata.py
│   └── pass6_validate.py
├── merge.py           # Embeddings + clustering
├── validate.py        # Rules + LLM critique
├── storage.py         # S3 JSONL + index
└── main.py            # CLI: python main.py input_dir/ tenant_id
```

**Dependencies**:
```
Python 3.11+
pymupdf==1.23.8
python-docx==1.1.0
google-cloud-documentai==2.24.0
beautifulsoup4==4.12.3
spacy==3.7.2
sentence-transformers==2.3.1
openai==1.10.0
anthropic==0.18.1
pydantic==2.6.1
boto3==1.34.34
ray==2.9.2
```

**Parallelization**: Ray distributes sections across cores:
```python
@ray.remote
def process_section(section):
    return pipeline(section)

results = ray.get([process_section.remote(s) for s in sections])
```

## 7. Edge Cases & Robustness
- **Malformed LLM output**: Pydantic validation + 3x retry with backoff
- **Rate limits**: Async queue + automatic model fallback (GPT-4o → Claude)
- **Low OCR confidence**: Flag + notify (`ocr_confidence < 0.8`)
- **No policies found**: Empty JSONL + index `{"num_policies": 0}`
- **Duplicate policies**: Pass 4 merge catches sim>0.9
- **Missing metadata**: owner='unknown', effective_date=null → flagged

## 7.1 Optional Enhancements (from concept-graph ideas)
- **Local LLM mode**: Add an Ollama/Mistral path in the LLM client for cheap prompt tuning on Pass 1/2 without Bedrock/OpenAI cost.
- **Evidence aggregation in merge**: In Pass 4, treat repeated overlaps like “same pair” evidence—aggregate/weight duplicate clauses before LLM merge, alongside embeddings.
- **Proximity signal**: Use co-occurrence within the same section/table/paragraph as a prior for linking or implicit policy discovery before invoking an LLM.

## 8. Testing Plan
```
Unit tests:
  pytest passes/test_pass2.py  # Mock section → expected JSON
  
Integration:
  sample_docs/ (10 docs) → golden JSONL comparison
  
End-to-end metrics:
  F1 on CUAD subset (scope/cond/act/exc separately)
  
Load testing:
  100 docs parallel, measure throughput/failures
```

**Success criteria**:
- Component extraction F1 >85%
- Human review flagging <10%
- 100-page doc completes in <5min

## 9. MVP Development Timeline

| Task | Duration | Deliverable |
|------|----------|-------------|
| Regularization (PDF/DocX/MD) | 1 day | canonical JSON output |
| LLM client + schema enforcement | 1 day | Pass stubs with retries |
| Pass 1-2 implementation | 1 day | Classification + components |
| Pass 3-6 implementation | 2 days | Entities, merge, metadata, validation |
| S3 storage + indexing | 1 day | JSONL writer + batch index |
| Parallelization (Ray) | 1 day | Per-section distribution |
| Testing + fixes | 2 days | Unit/integration/E2E |
| **Total** | **9 days** | **Production-ready MVP** |

## 10. Cost Summary

**Per-document (100 pages typical)**:
- Regularization: $0.015
- LLM extraction: $0.77
- Storage (S3): $0.001
- **Total: ~$0.79/doc**

**At scale (10,000 docs)**:
- Total cost: ~$7,900
- Runtime (4-core parallel): ~55 hours
- Output: ~2.5M policies (avg 250/doc)

**Budget considerations**:
- OCR-heavy corpus: +30% cost
- Complex policies (500+ pages): +5x cost/doc
- Refinement iterations: Customer-driven, no cost to pipeline

## 11. Repository Layout & Scaffolding (JSON-only extractor)

- **LLM providers**: ChatGPT or Claude via a thin `LLMClient` wrapper (schema-enforced JSON responses).
- **I/O contract**: Input = raw docs (PDF/DOCX/HTML/MD/TXT). Output = `policies.jsonl` (one policy per line) + `index.json` (batch summary). No other side effects.
- **Current scaffold** (created in this folder to start implementation):
```
src/
  cli.py                  # CLI entrypoint (argparse) → pipeline
  pipeline.py             # Orchestration stub: regularize → passes → write JSON
  regularize/
    router.py             # Format detection + routing
    pdf_native.py         # PyMuPDF-based extractor
    pdf_ocr.py            # OCR/layout extractor (Document AI/Textract equivalent)
    docx.py               # python-docx extractor
    html_md.py            # BeautifulSoup/markdown extractor
  llm/
    client.py             # ChatGPT/Claude wrapper with JSON schema enforcement
  passes/
    pass1_classify.py     # Section policy vs non-policy
    pass2_components.py   # Scope/conditions/actions/exceptions
    pass3_entities.py     # Regex+spaCy, LLM fallback
    pass4_merge.py        # Embedding-based clustering + LLM merge
    pass5_metadata.py     # Source/owner/effective_date/domain/reg_linkage
    pass6_validate.py     # Rule checks + LLM critique/flagging
  schemas/
    canonical.py          # Pydantic models for canonical doc JSON
    policy.py             # Pydantic models for policy JSONL lines
  storage/
    writer.py             # JSONL writer + index writer
configs/
  config.example.yaml     # Model settings, thresholds, ocr_conf, similarity
sample_docs/.gitkeep      # Placeholder for sample inputs
tests/
  test_pass2.py           # Placeholder test; expand with golden inputs/outputs
```
- **Next implementation steps**: fill `schemas/*` first, wire `regularize/router.py`, implement `pass2_components.py`, then connect `pipeline.py` to emit `policies.jsonl` + `index.json` into an `out/` directory.
