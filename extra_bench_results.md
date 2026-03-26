# Extra Benchmark Results: Final Experiments Only

## 1. Scope

This document reports only the **final experiment configuration and final results** used for analysis.

Included:

- Final embedding ablation artifacts.
- Final external benchmark results (two-seed runs, seeds 42 and 43).
- Final protocol-sensitivity slice (`asserted_probe` vs `generated_response`, matched 20-example subsets).
- Focused analysis of where PolicyLLM excels vs fails.

Primary artifacts:

- `PolicyLLM/results/embedding_ablation/final_run/summary.json`
- `PolicyLLM/results/external/seed42_run/summary.json`
- `PolicyLLM/results/external/seed43_run/summary.json`
- `PolicyLLM/results/external/variance_seed42_43.json`
- `PolicyLLM/results/external/protocol_compare_asserted_vs_generated_20.json`

---

## 2. Final Experiment Configuration

## 2.1 Common settings

- Backbone model: `gpt-4o-mini`
- External benchmark seed runs: `42`, `43`
- Dev/test protocol (classification tasks):
  - 10-example dev split for calibration
  - 50-example test split for reporting
  - threshold(s) frozen after dev calibration
- Splits: deterministic, stratified, persisted split IDs
- Caching: extraction/bundle cache keyed by document hash

## 2.2 Final evaluation protocol choices

- PolicyLLM primary external protocol: `asserted_probe` (bundle-consistency probe)
- Baseline context truncation: disabled (`baseline_max_chars=0`, full text)
- `unfair_tos` bundle mode: `extracted_reference` (not legacy static handcrafted bundle)
- Privacy entailment negative template: "does not state" path used
- CUAD contract selection: `random` (not max-coverage)
- `run_all` summaries include baseline rows

## 2.3 Embedding ablation configuration

- Evaluated embedding models for RAG methods:
  - `all-MiniLM-L6-v2`
  - `BAAI/bge-large-en-v1.5`
  - `text-embedding-3-small`
- RAG embedding backend updates used in final runs:
  - backend-selectable embedding models
  - vector normalization before cosine scoring
  - OpenAI embedding batching and fail-fast behavior if key/client missing

---

## 3. Final Results

## 3.1 Embedding ablation (final)

Source: `results/embedding_ablation/final_run/summary.json`

| Method | Embedding | Policy Recall | Policy Precision | Condition F1 | Compliance % |
|---|---|---:|---:|---:|---:|
| RAG retrieval only | all-MiniLM-L6-v2 | 0.22 | 0.38 | 0.00 | 95.8 |
| RAG + Z3 hybrid | all-MiniLM-L6-v2 | 0.22 | 0.37 | 0.00 | 100.0 |
| RAG retrieval only | BAAI/bge-large-en-v1.5 | 0.09 | 0.22 | 0.00 | 95.8 |
| RAG + Z3 hybrid | BAAI/bge-large-en-v1.5 | 0.08 | 0.22 | 0.00 | 100.0 |
| RAG retrieval only | text-embedding-3-small | 0.13 | 0.30 | 0.00 | 100.0 |
| RAG + Z3 hybrid | text-embedding-3-small | 0.14 | 0.34 | 0.00 | 95.8 |

Notes:

- Best RAG recall/precision in this set is with MiniLM, not with larger/newer embedders.
- In this artifact set, the auto-carried `PolicyLLM (Ours)` ablation row is placeholder zeroed in the generated summary output; interpret RAG ablation rows directly.

## 3.2 External benchmarks (final, seed variance)

Source: `results/external/variance_seed42_43.json`

### Classification tasks (Accuracy / Macro-F1)

| Benchmark | Method | Accuracy (mean +/- std) | Macro-F1 (mean +/- std) |
|---|---|---:|---:|
| ContractNLI | PolicyLLM | 0.480 +/- 0.000 | 0.393 +/- 0.004 |
| ContractNLI | Vanilla LLM | 0.810 +/- 0.030 | 0.809 +/- 0.031 |
| ContractNLI | System Prompt | 0.860 +/- 0.060 | 0.860 +/- 0.060 |
| LegalBench::privacy_policy_entailment | PolicyLLM | 0.970 +/- 0.010 | 0.970 +/- 0.010 |
| LegalBench::privacy_policy_entailment | Vanilla LLM | 0.830 +/- 0.050 | 0.824 +/- 0.055 |
| LegalBench::unfair_tos | PolicyLLM | 0.410 +/- 0.050 | 0.382 +/- 0.076 |
| LegalBench::unfair_tos | Vanilla LLM | 0.570 +/- 0.010 | 0.524 +/- 0.014 |

### Extraction task (Precision / Recall)

| Benchmark | Method | Precision (mean +/- std) | Recall (mean +/- std) |
|---|---|---:|---:|
| CUAD | PolicyLLM | 0.763 +/- 0.008 | 0.294 +/- 0.028 |
| CUAD | RAG Extractor | 0.400 +/- 0.100 | 0.067 +/- 0.011 |
| CUAD | Keyword + Rules | 0.350 +/- 0.150 | 0.039 +/- 0.017 |

## 3.3 Protocol sensitivity (final supplementary slice)

Source: `results/external/protocol_compare_asserted_vs_generated_20.json`

Matched 20-example slices (seed 42), `generated_response - asserted_probe` deltas:

| Benchmark | Method | Delta Accuracy | Delta Macro-F1 |
|---|---|---:|---:|
| ContractNLI | PolicyLLM | -0.100 | -0.161 |
| ContractNLI | System Prompt | -0.050 | -0.047 |
| ContractNLI | Vanilla LLM | 0.000 | 0.000 |
| LegalBench::privacy_policy_entailment | PolicyLLM | -0.450 | -0.499 |
| LegalBench::privacy_policy_entailment | Vanilla LLM | 0.000 | 0.000 |
| LegalBench::unfair_tos | PolicyLLM | +0.100 | +0.048 |
| LegalBench::unfair_tos | Vanilla LLM | 0.000 | 0.000 |

---

## 4. Where The Pipeline Excels vs Fails

## 4.1 Where PolicyLLM excels

1. Privacy policy entailment (asserted-probe protocol).

- PolicyLLM: `0.970 +/- 0.010` accuracy vs vanilla `0.830 +/- 0.050`.
- This aligns with the pipeline’s strength: rule-grounded policy semantics and consistency checking.

2. CUAD coarse clause extraction precision.

- PolicyLLM precision: `0.763 +/- 0.008`, clearly above RAG (`0.400`) and keyword rules (`0.350`).
- Precision-led behavior indicates extracted clauses are often correct when predicted.

Interpretation:

- The pipeline performs best when tasks are close to **structured policy interpretation/extraction** rather than open-ended legal inference.

## 4.2 Where PolicyLLM fails

1. ContractNLI (3-way textual inference).

- PolicyLLM: `0.480 +/- 0.000` accuracy, well below vanilla/system-prompt baselines.
- Failure mode in saved predictions: class collapse due to weak score separability.
  - Seed 42: heavy `not_mentioned` overprediction.
  - Seed 43: heavy `entailment` overprediction.
- This indicates the single enforcement score + thresholds is a poor surrogate for 3-way NLI semantics.

2. LegalBench `unfair_tos` (normative fairness judgment).

- PolicyLLM: `0.410 +/- 0.050` vs vanilla `0.570 +/- 0.010`.
- Balanced split is enforced in final runs (25/25 test), so this is not a class-imbalance artifact.
- Failure mode: large overlap in score distributions for `unfair` and `not_unfair`, making thresholding unstable.
- Substantive issue: legal fairness labels are partly normative/subjective; bundle-consistency scoring does not fully capture that judgment space.

## 4.3 Overall takeaway from final experiments

- Strong on **structure-grounded policy tasks** (privacy entailment in probe mode, CUAD precision).
- Weak on **subjective or broad inference tasks** (ContractNLI, `unfair_tos`).
- This pattern is consistent with PolicyLLM’s architecture: extraction + rule enforcement is not equivalent to general legal reasoning.

---

## 5. Final Reporting Boundaries

Supported claims from final experiments:

- Embedding upgrades alone did not rescue RAG baselines in this setup.
- PolicyLLM shows strong transfer on selected structure-aligned tasks.
- PolicyLLM underperforms on inference-heavy/normative tasks.

Claims to avoid:

- Treating asserted-probe performance as universal end-to-end generation performance.
- Claiming broad legal-NLP superiority from these pilots.

