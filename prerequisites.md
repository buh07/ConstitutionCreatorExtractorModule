# Prerequisites and Setup Guide

This project extracts policies into structured JSON using a multi-pass pipeline. Below are the required tools, dependencies, and configuration steps to get started.

**Note:** The legacy `acl-extractor` folder is no longer used. Activate and install everything in the local `.venv` inside this repository.

## 1) System Requirements
- macOS/Linux with Python 3.11+
- Disk space: ~10 GB (for local models and dependencies)

## 2) Core Dependencies
Install via `pip` (or `pipx`/`pipenv`/`poetry` equivalent):
```
python3 -m venv .venv
source .venv/bin/activate
pip install "numpy<2" "pymupdf>=1.24.10" python-docx==1.1.0 beautifulsoup4==4.12.3 markdown==3.6 \
spacy==3.7.2 "torch>=2.2,<2.5" sentence-transformers==2.3.1 boto3==1.34.34 pydantic==2.6.1 \
google-cloud-documentai==2.24.0 pyyaml pytest
python -m spacy download en_core_web_sm
```

Optional but recommended:
- `en_core_web_sm` spaCy model:
```
python -m spacy download en_core_web_sm
```

## 3) Local LLM (Default: Ollama + Mistral)
1. Install Ollama: https://ollama.com/download
2. Pull a model (default in config is `mistral:latest`):
```
ollama pull mistral
```
3. Ensure the service is running (`curl http://127.0.0.1:11434/api/tags`).

## 4) Cloud LLM Options (if not using Ollama)
- **AWS Bedrock (Claude Sonnet)**: set `provider: bedrock_claude` and `model_id` to your Bedrock ARN; ensure AWS credentials are configured (env vars, `~/.aws/credentials`, or IAM role).
- **OpenAI / Anthropic (direct)**: providers are placeholders; when adding real calls, export API keys:
```
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

## 5) Google Document AI (OCR for scanned PDFs)
1. Enable Document AI in your GCP project.
2. Set credentials:
```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-key.json
```
3. Configure DocAI IDs in `configs/config.example.yaml`:
```
docai:
  project_id: your-project
  location: us
  processor_id: your-processor
  processor_version: null
```

## 6) Configuration
Edit `configs/config.example.yaml` (copy to `configs/config.yaml` if desired):
- `llm.provider`: `ollama` (default) | `bedrock_claude` | `chatgpt` | `anthropic`
- `llm.model_id`: e.g., `mistral:latest` (Ollama) or Bedrock ARN
- `llm.region`: used for Bedrock
- `llm.temperature`, `max_tokens`, `retries`, `backoff`
- `regularization`: `ocr_confidence_threshold`, `max_pages`
- `merge`: `similarity_threshold`
- `validation`: `confidence_threshold`, `flag_issue_rate`
- `scope`: `fallback` (all|unknown|none), `enable_regex`
- `metadata_resolver`: regex toggle, tenant/domain defaults
- `double_run`: enabled/disabled for consensus
- `stage5`: `generate` (default true) and `ingest` to handle runtime JSONs
- `docai`: GCP OCR settings (see above)

## 7) Project Layout (relevant files)
- `src/llm/client.py`: LLM providers (Ollama default; Bedrock active; OpenAI/Anthropic placeholders)
- `src/regularize/*`: PDF/DocX/HTML/MD/OCR normalizers
- `src/passes/`: Pass1–Pass6
- `src/schemas/`: Canonical and policy schemas (enrichment pattern)
- `configs/config.example.yaml`: Default config (copy/edit as needed)

## 8) Running the Pipeline (after orchestration is wired)
```
python -m src.cli input_path --out out_dir --tenant tenant_id --batch batch_id --config configs/config.example.yaml
```

## Notes
- Default LLM is local (Ollama). Switch providers in the config if using cloud APIs.
- Ensure Ollama service is reachable on `127.0.0.1:11434` or use a cloud provider.
- OpenAI/Anthropic direct calls are placeholders; add implementations before use.
