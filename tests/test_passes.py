import types

import src.passes.pass1_classify as p1
import src.passes.pass2_components as p2
import src.passes.pass3_entities as p3
import src.passes.pass4_merge as p4


class StubLLM:
    def __init__(self, responses):
        self.responses = responses

    def invoke_json(self, prompt, schema=None):
        # return the first matching response based on a key substring
        for key, value in self.responses.items():
            if key in prompt:
                return value
        return next(iter(self.responses.values()))


def test_pass1_classify():
    llm = StubLLM({"is_policy": {"is_policy": True, "confidence": 0.9, "reason": "test"}})
    section = {"heading": "Policy", "paragraphs": [{"text": "Do X", "span": {"start": 0, "end": 4, "page": 1}}]}
    res = p1.run(section, llm)
    assert res["is_policy"] is True


def test_pass2_components():
    llm = StubLLM(
        {
            "scope": {
                "scope": {
                    "customer_segments": ["all"],
                    "product_categories": ["all"],
                    "channels": ["online"],
                    "regions": ["all"],
                },
                "conditions": [],
                "actions": [],
                "exceptions": [],
            }
        }
    )
    section = {"heading": "Test", "paragraphs": [{"text": "Rule", "span": {"start": 0, "end": 4, "page": 1}}]}
    res = p2.run(section, llm)
    assert res["scope"]["customer_segments"] == ["all"]
    assert isinstance(res["conditions"], list)


def test_pass3_entities_span_propagation():
    llm = StubLLM({})
    section = {
        "section_id": "sec1",
        "paragraphs": [{"text": "Customers may return items within 30 days.", "span": {"start": 0, "end": 46, "page": 2}}],
        "page": 2,
    }
    comps = {"scope": {}, "conditions": [], "actions": [], "exceptions": []}
    ents = p3.run(section, comps, llm)
    assert any(ent["span"]["page"] == 2 and ent["span"]["section_id"] == "sec1" for ent in ents)


def test_pass4_merge_evidence():
    pol1 = {
        "doc_id": "doc",
        "scope": {"customer_segments": ["all"], "product_categories": [], "channels": [], "regions": []},
        "conditions": [],
        "actions": [],
        "exceptions": [],
        "entities": [],
        "metadata": {"domain": "refund"},
        "provenance": {"evidence_count": 1, "passes_used": [1], "low_confidence": [], "source_spans": []},
    }
    pol2 = {
        "doc_id": "doc",
        "scope": {"customer_segments": ["all"], "product_categories": [], "channels": [], "regions": []},
        "conditions": [],
        "actions": [],
        "exceptions": [],
        "entities": [],
        "metadata": {"domain": "refund"},
        "provenance": {"evidence_count": 1, "passes_used": [1], "low_confidence": [], "source_spans": []},
    }
    merged = p4.run([pol1, pol2], llm_client=None, sim_threshold=0.99)
    assert len(merged) == 1
    assert merged[0]["provenance"]["evidence_count"] >= 2
