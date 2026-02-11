# PolicyLLM Extraction Pipeline

Turn heterogeneous policy documents into structured JSON policies (Stage 1) plus optional Stage 5 runtime stubs. The pipeline normalizes input files (PDF/DOCX/HTML/MD/TXT/OCR), runs multi-pass extraction (classify → components → entities → merge → metadata → validate), and writes `policies.jsonl` + `index.json`. Optional Stage 5 JSON stubs land in `out/stage5/`.

## Quickstart
```
python3 -m venv .venv
source .venv/bin/activate
pip install "numpy<2" "pymupdf>=1.24.10" python-docx==1.1.0 beautifulsoup4==4.12.3 markdown==3.6 \
spacy==3.7.2 "torch>=2.2,<2.5" sentence-transformers==2.3.1 boto3==1.34.34 pydantic==2.6.1 \
google-cloud-documentai==2.24.0 pyyaml pytest
python -m spacy download en_core_web_sm
ollama pull mistral

python3 -m src.cli sample_docs/sample.txt --out out --tenant tenant_sample --batch sample --config configs/config.example.yaml
```

Outputs go to `out/`:
- `docid-batch.jsonl` (policies), `docid-batch-index.json` (summary)
- `out/stage5/` (Stage 5 stubs) when `stage5.generate: true` (default)

## Config highlights (`configs/config.example.yaml`)
- `llm`: provider/model/temp/max_tokens/retries; default Ollama + `mistral:latest`
- `scope`: `fallback` (all|unknown|none), `enable_regex`
- `metadata_resolver`: regex hints + tenant/domain defaults
- `double_run`: optional consensus (runs select passes twice and merges)
- `stage5`: generate/ingest runtime JSONs
- `parallel`: per-section Ray parallelism (enable for multi-section docs)

## Runtime notes
- On a 2.3 GHz quad-core Intel i7 (no GPU), sample with 2 sections ran in ~373s (passes only; regularization negligible) using Ollama/Mistral CPU.
- Expect substantial speedups on a faster CPU/GPU or with a lighter local model and lower `max_tokens`. Parallelism helps only when multiple sections exist.

## Scope and limitations
- Stage 1 extraction only; formalization/conflict/layer assignment are pending by design.
- Stage 5 stubs are minimal; they are placeholders for runtime pre/during/post-generation artifacts.
- Metadata extraction is conservative; owner/effective_date/regulatory linkage require source signals or defaults.

## Tests
```
pytest -q
```
