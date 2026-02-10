1. # Output Format Definition: JSON Enrichment Pattern

   Each module **enriches a single JSON object step by step**. Previous stage fields are never modified — only new keys are added.

   ------

   ## Common Header

   Every policy JSON includes these top-level fields:

   ```json
   {
     "schema_version": "1.0",
     "processing_status": {
       "extraction": "pending",
       "formalization": "pending",
       "conflict_detection": "pending",
       "layer_assignment": "pending"
     },
     "policy_id": "POL-REFUND-001",
     "origin": "explicit",
     ...
   }
   ```

   - `schema_version`: Tracks format changes across iterations
   - `processing_status`: Completion status per stage (`pending` / `complete` / `failed`)
   - `origin`: `"explicit"` (extracted from documents) or `"implicit"` (mined from decision logs)

   ### Policy ID Naming Convention

   | Origin   | Format                   | Example                             |
   | -------- | ------------------------ | ----------------------------------- |
   | Explicit | `POL-{DOMAIN}-{SEQ}`     | `POL-REFUND-001`, `POL-PRIVACY-003` |
   | Implicit | `POL-IMP-{DOMAIN}-{SEQ}` | `POL-IMP-REFUND-012`                |

   - `{DOMAIN}`: Matches the `metadata.domain` value (uppercase)
   - `{SEQ}`: Zero-padded 3-digit sequence, unique per domain
   - One source document may produce multiple policy IDs (e.g., `return_policy_v3.2` → `POL-REFUND-001`, `POL-REFUND-002`, `POL-REFUND-003`)

   ### Stage Failure Handling

   | Failed Stage       | Next Stage?                        | Action                                                       |
   | ------------------ | ---------------------------------- | ------------------------------------------------------------ |
   | Extraction         | ❌ All blocked                      | Fix source input, re-run                                     |
   | Formalization      | ❌ Conflict Detection blocked       | Policy enters "extraction-only" mode; can still be used in system prompt / RAG as raw text, but no Z3 verification |
   | Conflict Detection | ✅ Layer Assignment proceeds        | Flag `"conflict_detection": "failed"`, assign layers without conflict info, log warning |
   | Layer Assignment   | ✅ Runtime uses default layer (RAG) | Flag `"layer_assignment": "failed"`, all policies default to RAG layer |

   ------

   ## Stage 1: Policy Extraction

   > **CREATE** policy_id, origin, scope, conditions, actions, exceptions, metadata **IN JSON**

   ### Allowed Type Enums

   **Condition types:**

   | Type               | Description                  | Example                       |
   | ------------------ | ---------------------------- | ----------------------------- |
   | `time_window`      | Duration-based constraint    | Return within 30 days         |
   | `amount_threshold` | Monetary limit               | Orders over $50               |
   | `customer_tier`    | Customer segment requirement | VIP, Gold, Standard           |
   | `product_category` | Product-specific condition   | Electronics, Perishables      |
   | `geographic`       | Location-based constraint    | US-only, EU residents         |
   | `boolean_flag`     | Binary state                 | Has receipt, Is authenticated |
   | `role_requirement` | Agent/employee role needed   | Manager approval              |

   **Action types:**

   | Type                 | Description                                 | Example                    |
   | -------------------- | ------------------------------------------- | -------------------------- |
   | `required`           | Must be performed when conditions met       | Issue full refund          |
   | `prohibited`         | Must never occur                            | Never disclose PII         |
   | `fallback`           | Alternative when primary action unavailable | Store credit if no receipt |
   | `conditional`        | Depends on additional runtime factors       | Escalate if amount > $500  |
   | `discovered_pattern` | Implicit policy only — mined behavior       | Auto-approve VIP refunds   |

   ### Structured Value Format

   All `value` fields must be structured for Z3 compatibility:

   ```json
   // ❌ NOT this (free text, cannot be parsed by Z3)
   {"type": "time_window", "value": "30 days"}
   
   // ✅ This (structured, directly translatable to Z3)
   {"type": "time_window", "value": 30, "unit": "days", "operator": "<="}
   {"type": "amount_threshold", "value": 50, "unit": "USD", "operator": ">"}
   {"type": "boolean_flag", "value": true, "parameter": "has_receipt"}
   {"type": "customer_tier", "value": "VIP", "operator": "=="}
   ```

   ### Structured Scope Format

   Scope must be structured for query matching at Pre-Generation (Stage 5-1):

   ```json
   // ❌ NOT this (free text, requires LLM interpretation every time)
   "scope": "All customers, all product categories"
   
   // ✅ This (structured, enables programmatic matching)
   "scope": {
     "customer_segments": ["all"],
     "product_categories": ["all"],
     "channels": ["online", "in-store"],
     "regions": ["all"]
   }
   ```

   ### Explicit Policy Example

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
     "scope": {
       "customer_segments": ["all"],
       "product_categories": ["all"],
       "channels": ["online", "in-store"],
       "regions": ["all"]
     },
     "conditions": [
       {
         "type": "time_window",
         "value": 30,
         "unit": "days",
         "operator": "<=",
         "target": "general",
         "source_text": "Customers may return items within 30 days of purchase"
       },
       {
         "type": "time_window",
         "value": 15,
         "unit": "days",
         "operator": "<=",
         "target": "electronics",
         "source_text": "Electronics must be returned within 15 days"
       }
     ],
     "actions": [
       {
         "type": "required",
         "action": "full_refund",
         "requires": ["has_receipt", "within_window"],
         "source_text": "Customers may return items within 30 days of purchase for a full refund"
       },
       {
         "type": "fallback",
         "action": "store_credit",
         "requires": ["no_receipt"],
         "source_text": "Items without receipt receive store credit only"
       }
     ],
     "exceptions": [
       {
         "description": "Electronics: 15-day override on 30-day general window",
         "source_text": "Electronics must be returned within 15 days"
       }
     ],
     "metadata": {
       "source": "return_policy_v3.2, §4.1",
       "owner": "Customer Service Dept.",
       "effective_date": "2024-01-15",
       "domain": "refund",
       "regulatory_linkage": ["FTC Cooling-Off Rule"]
     }
   }
   ```

   ### Implicit Policy Example

   ```json
   {
     "schema_version": "1.0",
     "processing_status": {
       "extraction": "complete",
       "formalization": "pending",
       "conflict_detection": "pending",
       "layer_assignment": "pending"
     },
     "policy_id": "POL-IMP-REFUND-003",
     "origin": "implicit",
     "discovery": {
       "confidence": 0.87,
       "support": 124,
       "source_log": "cs_tickets_2024Q1.csv",
       "human_validated": false
     },
     "scope": {
       "customer_segments": ["VIP"],
       "product_categories": ["all"],
       "channels": ["all"],
       "regions": ["all"]
     },
     "conditions": [
       {
         "type": "amount_threshold",
         "value": 200,
         "unit": "USD",
         "operator": ">",
         "target": "VIP",
         "source_text": null
       }
     ],
     "actions": [
       {
         "type": "discovered_pattern",
         "action": "auto_approve_refund",
         "requires": ["VIP_status", "amount_over_200"],
         "source_text": null
       }
     ],
     "exceptions": [],
     "metadata": {
       "source": "cs_tickets_2024Q1.csv (mined)",
       "owner": "TBD",
       "effective_date": null,
       "domain": "refund",
       "regulatory_linkage": []
     }
   }
   ```

   > **Note**: Implicit policies have no `source_text`. They are **not activated** for enforcement until `human_validated` is set to `true`.

   ### Source Text Reconstruction Verification

   Every component includes a `source_text` field to enable extraction quality verification.

   **Verification method:**

   1. Split the original document into sentences
   2. Check that each sentence maps to at least one component's `source_text`
   3. **Unmapped sentences = extraction gaps** → report gap rate

   **Automated verification (supplementary):**

   - Extracted JSON → LLM reconstructs natural language → compare against original using NLI (entailment) model
   - `coverage = entailed_sentences / total_policy_sentences`

   ------

   ## Stage 2: Policy Formalization

   > **ADD** formal (formalization_type, logic_rules, constraints, decision_graph) **IN JSON**

   ### Formalization Type Selection Criteria

   | Criteria                                                     | → formalization_type | Rationale                       |
   | ------------------------------------------------------------ | -------------------- | ------------------------------- |
   | ≤2 conditions, no sequential dependency                      | `conditional`        | Simple rules, Z3-verifiable     |
   | ≥3 conditions with sequential dependency (step A result feeds step B) | `procedural`         | Multi-step workflow needs graph |
   | Mixed: some conditions are simple, others form a workflow    | `both`               | Generate both representations   |

   **Who decides?** LLM analyzes the extracted components and assigns the type. If uncertain, defaults to `both`.

   ```json
   {
     "policy_id": "POL-REFUND-001",
     "processing_status": {
       "extraction": "complete",
       "formalization": "complete",
       "conflict_detection": "pending",
       "layer_assignment": "pending"
     },
     "formal": {
       "formalization_type": "both",
       "logic_rules": [
         {
           "rule_id": "R-REFUND-001a",
           "antecedent": "(category != electronics) ∧ (days_since_purchase <= 30) ∧ (has_receipt = true)",
           "consequent": "full_refund",
           "z3_expr": "(and (not (= category electronics)) (<= days 30) (= receipt true))"
         },
         {
           "rule_id": "R-REFUND-001b",
           "antecedent": "(category = electronics) ∧ (days_since_purchase <= 15) ∧ (has_receipt = true)",
           "consequent": "full_refund",
           "z3_expr": "(and (= category electronics) (<= days 15) (= receipt true))"
         },
         {
           "rule_id": "R-REFUND-001c",
           "antecedent": "(has_receipt = false)",
           "consequent": "store_credit",
           "z3_expr": "(= receipt false)"
         }
       ],
       "constraints": [
         {
           "constraint_id": "C-REFUND-001",
           "type": "invariant",
           "expression": "□(refund_amount <= original_purchase_price)",
           "z3_expr": "(assert (forall ((r Refund)) (<= (amount r) (price r))))"
         }
       ],
       "decision_graph": {
         "root": "has_receipt",
         "nodes": {
           "has_receipt": {"type": "condition", "true": "within_30_days", "false": "under_50"},
           "within_30_days": {"type": "condition", "true": "full_refund", "false": "mgr_approval"},
           "under_50": {"type": "condition", "true": "store_credit", "false": "reject"}
         },
         "terminals": ["full_refund", "mgr_approval", "store_credit", "reject"]
       }
     }
   }
   ```

   > **Note**: `z3_expr` is stored as SMT-LIB2 syntax strings. Parsed at solver invocation time.

   > **`z3_expr` generation**: LLM translates `antecedent`/`consequent` into SMT-LIB2 strings. A syntax validator checks the output is parseable by Z3 before storing. If validation fails, `processing_status.formalization` is set to `"failed"` and the policy falls back to text-only mode.

   ------

   ## Stage 3: Conflict Detection & Resolution

   > **ADD** conflicts **IN JSON**

   This stage performs two operations:

   1. **Priority assignment**: Map each policy's metadata (`regulatory_linkage`, `domain`, `owner`, etc.) to a 5-level priority
   2. **Conflict detection + resolution**: When conflicts are found, compare priorities to resolve or escalate

   Priority is **not** assigned in Stage 1. Metadata is raw material only — priority is determined **within the conflict context** where it has actionable meaning.

   ### Priority Level Criteria (Paper §3.4.4)

   | Level | Name                | Determination Rule                                           |
   | ----- | ------------------- | ------------------------------------------------------------ |
   | 1     | Legal/Regulatory    | `regulatory_linkage` is non-empty                            |
   | 2     | Core Company Values | `domain` ∈ {safety, privacy, ethics}                         |
   | 3     | Company-wide Policy | `owner` is cross-departmental OR `domain` is general operations |
   | 4     | Department-specific | `owner` is a specific department                             |
   | 5     | Situational         | `effective_date` has expiry OR tagged as temporary           |

   ### Resolution Cases

   | Case                      | Condition                  | Resolution                              |
   | ------------------------- | -------------------------- | --------------------------------------- |
   | Different priority levels | Level 1 vs Level 3, etc.   | ✅ Automatic (higher wins)               |
   | Same priority level       | Level 3 vs Level 3, etc.   | ❌ Escalate to `owner`                   |
   | Semantic conflict         | Intent-level contradiction | ❌ Requires human judgment in most cases |

   ### JSON Example

   ```json
   {
     "policy_id": "POL-REFUND-001",
     "processing_status": {
       "extraction": "complete",
       "formalization": "complete",
       "conflict_detection": "complete",
       "layer_assignment": "pending"
     },
     "conflicts": [
       {
         "conflict_id": "CF-012",
         "type": "logical",
         "detector": "smt",
         "policy_a": {
           "id": "POL-REFUND-001",
           "priority_level": 1,
           "priority_reason": "regulatory_linkage exists (FTC Cooling-Off Rule)"
         },
         "policy_b": {
           "id": "POL-SHIPPING-007",
           "priority_level": 3,
           "priority_reason": "company-wide policy (no regulatory linkage)"
         },
         "counterexample": {"amount": 60, "category": "general"},
         "severity": "high",
         "resolution": {
           "method": "priority",
           "winner": "POL-REFUND-001",
           "reason": "Level 1 (regulatory) overrides Level 3 (company-wide)"
         }
       },
       {
         "conflict_id": "CF-015",
         "type": "semantic",
         "detector": "llm",
         "policy_a": {
           "id": "POL-REFUND-001",
           "priority_level": 3,
           "priority_reason": "company-wide policy"
         },
         "policy_b": {
           "id": "POL-COMPETE-009",
           "priority_level": 3,
           "priority_reason": "company-wide policy"
         },
         "similarity_score": 0.82,
         "explanation": "Suggesting alternatives may include competitor products",
         "severity": "medium",
         "resolution": {
           "method": "manual",
           "status": "pending_review",
           "escalated_to": "Customer Service Dept.",
           "reason": "Same priority level (3 vs 3), requires human judgment"
         }
       }
     ]
   }
   ```

   - **Logical conflict** (`detector: "smt"`): Includes Z3 counterexample
   - **Semantic conflict** (`detector: "llm"`): Includes similarity score + natural language explanation
   - Each conflict includes **both policies' priority_level and reasoning**
   - No conflicts → `"conflicts": []`

   ------

   ## Stage 4: Layer Assignment

   > **ADD** layer_assignment **IN JSON**

   ```json
   {
     "policy_id": "POL-REFUND-001",
     "processing_status": {
       "extraction": "complete",
       "formalization": "complete",
       "conflict_detection": "complete",
       "layer_assignment": "complete"
     },
     "layer_assignment": {
       "scores": {
         "stability": 0.85,
         "criticality": 0.9,
         "context_dependence": 0.4,
         "strictness": 0.8
       },
       "assigned_layers": ["system_prompt", "rag", "guardrail"],
       "primary_layer": "guardrail"
     }
   }
   ```

   ### Layer Assignment Criteria

   | Layer         | stability | criticality | context_dep | strictness | Update Cycle |
   | ------------- | --------- | ----------- | ----------- | ---------- | ------------ |
   | Fine-tuning   | ≥0.8      | ≥0.7        | ≤0.3        | any        | Quarterly    |
   | System Prompt | ≥0.6      | any         | ≤0.5        | any        | Per deploy   |
   | Runtime RAG   | any       | any         | ≥0.6        | ≤0.7       | Real-time    |
   | Guardrail     | any       | ≥0.8        | any         | ≥0.8       | Real-time    |

   - Policies with `criticality ≥ 0.8` are assigned to **multiple layers simultaneously** (defense-in-depth)

   ### Score Assignment

   The four scores are assigned by **LLM classification** with the following rubric:

   | Score                | High (≥0.8)                                    | Low (≤0.3)                                   |
   | -------------------- | ---------------------------------------------- | -------------------------------------------- |
   | `stability`          | Rarely changes (e.g., GDPR compliance)         | Changes frequently (e.g., seasonal promos)   |
   | `criticality`        | Violation causes legal/financial harm          | Violation causes minor UX issue              |
   | `context_dependence` | Outcome varies per query (e.g., refund amount) | Always the same (e.g., "never disclose PII") |
   | `strictness`         | Zero tolerance for violation                   | Soft guideline, best-effort                  |

   ------

   ## Stage 5: Runtime Enforcement (Paper §3.6)

   > Stages 1–4 are **Offline** (building the policy JSON). Stage 5 is **Online** (processing live queries).

   Stage 5 **consumes** the completed policy JSONs (read-only). Runtime JSONs are separate objects, one per query.

   ### 5-1. Pre-Generation

   Collect relevant policies **before** sending the query to the LLM.

   ```json
   {
     "query_id": "Q-20240601-0042",
     "raw_query": "I bought a TV 20 days ago and lost the receipt. Can I get a refund?",
     "pre_generation": {
       "classified_domain": "refund",
       "retrieved_policies": [
         {
           "policy_id": "POL-REFUND-001",
           "relevance_score": 0.94,
           "assigned_layer": "guardrail",
           "priority_level": 1
         },
         {
           "policy_id": "POL-REFUND-003",
           "relevance_score": 0.87,
           "assigned_layer": "rag",
           "priority_level": 3
         }
       ],
       "context_injection": {
         "system_prompt_policies": ["POL-PRIVACY-012", "POL-SAFETY-015"],
         "rag_policies": ["POL-REFUND-001", "POL-REFUND-003"],
         "guardrail_policies": ["POL-REFUND-001", "POL-PII-008"]
       }
     }
   }
   ```

   **Execution order:**

   1. Classify query by `domain` (using metadata's `domain` field)
   2. Retrieve relevant policies via DPR (permission-aware)
   3. Route each policy to its assigned layer (from `layer_assignment`)

   ### 5-2. During-Generation

   Guidance injected **while** the LLM generates its response.

   ```json
   {
     "query_id": "Q-20240601-0042",
     "during_generation": {
       "injected_logic_rules": [
         {
           "rule_id": "R-REFUND-001c",
           "natural_language": "No receipt → store credit only",
           "z3_expr": "(= receipt false)"
         }
       ],
       "injected_constraints": [
         {
           "constraint_id": "C-REFUND-001",
           "natural_language": "Refund amount must not exceed original purchase price"
         }
       ],
       "injected_decision_graph": {
         "policy_id": "POL-REFUND-001",
         "traversal_path": ["has_receipt=false", "under_50=false"],
         "terminal_action": "reject",
         "serialized_steps": [
           "Step 1: Check if customer has receipt → No",
           "Step 2: Check if purchase amount ≤ $50 → No (TV, >$50)",
           "Step 3: → Reject (no store credit for no-receipt items over $50)"
         ]
       },
       "priority_guidance": {
         "highest_active": {"policy_id": "POL-REFUND-001", "priority_level": 1},
         "instruction": "FTC Cooling-Off Rule linked policy takes precedence"
       }
     }
   }
   ```

   **Execution order:**

   1. `logic_rules` + `constraints` → injected as explicit compliance requirements
   2. `decision_graph` → serialized step-by-step as chain-of-thought scaffold
   3. On conflict, `priority_level` guidance ensures higher-priority policy wins

   **Graph traversal**: The LLM extracts query parameters from the user's message (e.g., `has_receipt=false`, `amount=$TV`) and traverses the decision graph accordingly. If parameter extraction is ambiguous, the LLM asks the user for clarification before traversing.

   ### 5-3. Post-Generation

   Verification **after** the LLM produces its response.

   ```json
   {
     "query_id": "Q-20240601-0042",
     "generated_response": "Unfortunately, without a receipt we cannot process a cash refund for your TV. However, we can offer store credit...",
     "post_generation": {
       "checks": [
         {
           "check_type": "rule_pattern",
           "checker": "regex",
           "policy_id": "POL-PII-008",
           "result": "pass",
           "score": 1.0,
           "detail": "No PII detected in response"
         },
         {
           "check_type": "logical_consistency",
           "checker": "smt",
           "policy_id": "POL-REFUND-001",
           "result": "pass",
           "score": 0.95,
           "detail": "Response consistent with no-receipt → store credit rule"
         },
         {
           "check_type": "semantic_compliance",
           "checker": "llm",
           "policy_id": "POL-REFUND-001",
           "result": "pass",
           "score": 0.94,
           "detail": "Tone appropriate, correct policy cited"
         }
       ],
       "compliance_score": {
         "weights": {"rule_pattern": 0.2, "logical_consistency": 0.4, "semantic_compliance": 0.4},
         "per_check": {"rule_pattern": 1.0, "logical_consistency": 0.95, "semantic_compliance": 0.94},
         "final": 0.956
       },
       "action": "pass",
       "audit_trail": {
         "applied_policies": ["POL-REFUND-001", "POL-REFUND-003", "POL-PII-008"],
         "decision_path": "has_receipt=false → under_50=false → reject",
         "source_documents": ["return_policy_v3.2 §4.1"]
       }
     }
   }
   ```

   ### Compliance Score Calculation

   ```
   final_score = (w_rule × score_rule) + (w_logic × score_logic) + (w_semantic × score_semantic)
   ```

   Default weights:

   | Check                       | Weight | Rationale                     |
   | --------------------------- | ------ | ----------------------------- |
   | `rule_pattern` (regex)      | 0.2    | Binary checks, low complexity |
   | `logical_consistency` (SMT) | 0.4    | Hard constraint verification  |
   | `semantic_compliance` (LLM) | 0.4    | Nuanced policy adherence      |

   If any single check returns `"result": "fail"` with `score < 0.5`, the final action is automatically `escalate` regardless of weighted average.

   ### Action Thresholds

   | compliance_score (final) | action         | Description                                            |
   | ------------------------ | -------------- | ------------------------------------------------------ |
   | ≥ 0.95                   | `pass`         | Deliver response as-is                                 |
   | 0.85 – 0.94              | `auto_correct` | Auto-fix violation, log diff in audit_trail            |
   | 0.70 – 0.84              | `regenerate`   | Discard response, regenerate with stronger constraints |
   | < 0.70                   | `escalate`     | Route to `owner` (includes uncovered policy scenarios) |

   ### Auto-Correct Audit

   When `action` is `auto_correct`, the audit trail records what changed:

   ```json
   "audit_trail": {
     "applied_policies": ["POL-REFUND-001"],
     "decision_path": "has_receipt=false → under_50=false → reject",
     "source_documents": ["return_policy_v3.2 §4.1"],
     "auto_corrections": [
       {
         "original_fragment": "We can offer you a full refund as store credit.",
         "corrected_fragment": "We can offer you store credit for the purchase amount.",
         "reason": "Original implied 'full refund' which contradicts no-receipt policy",
         "policy_id": "POL-REFUND-001"
       }
     ]
   }
   ```

   ------

   ## Summary: Full Pipeline

   ```
   [Offline: Build Policy JSON]
   
   Documents/Logs → [Stage 1: Extraction] → CREATE JSON (scope, conditions, actions, exceptions, metadata)
                                                 ↓
                                          [Stage 2: Formalization] → ADD formal (logic_rules, constraints, decision_graph)
                                                 ↓
                                          [Stage 3: Conflict Detection] → ADD conflicts + priority assignment/resolution
                                                 ↓
                                          [Stage 4: Layer Assignment] → ADD layer_assignment (scores + layer placement)
                                                 ↓
                                          Completed Policy JSON → stored in policy knowledge base
   
   ─────────────────────────────────────────────────────────────────
   
   [Online: Per-Query Real-Time Processing]
   
   Customer Query → [Stage 5-1: Pre-Generation] → Retrieve policies + prepare layer-specific injection
                                                        ↓
                                                 [Stage 5-2: During-Generation] → Inject rules/graph/priority into LLM context
                                                        ↓
                                                 [Stage 5-3: Post-Generation] → Verify response + compliance score + action
                                                        ↓
                                                 pass / auto_correct / regenerate / escalate
   ```

   ### Core Principles

   - **Stages 1–4 (Offline)**: Pure enrichment — never modify previous fields, only add new keys
   - **Stage 5 (Online)**: Completed policy JSONs are consumed **read-only**; runtime JSONs are separate per-query objects
   - `processing_status` tracks offline pipeline progress
   - `source_text` enables source document reconstruction verification
   - `audit_trail` enables runtime decision traceability
   - Implicit policies remain **inactive** until `human_validated: true`
   - Stage failures are handled per the failure table (see Common Header section)

   ------

   ## Open Discussion Items

   ### Must Decide Before Implementation

   1. **Compliance score weights**: Are the default weights (0.2 / 0.4 / 0.4) acceptable, or should they be configurable per domain?
   2. **Graph traversal ambiguity**: When the LLM cannot extract a parameter from the query (e.g., user doesn't mention the purchase amount), what is the fallback? Ask user? Assume worst case?
   3. **Runtime JSON storage**: Where are Stage 5 runtime JSONs persisted? (Log DB? Separate audit system? Both?)
   4. **Decision graph visualization**: Do we need a debug UI to visualize graph traversal per query?
   5. **`z3_expr` validation**: Should Z3 syntax validation be blocking (fail the stage) or non-blocking (log warning, continue without Z3)?