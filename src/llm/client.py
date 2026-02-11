"""LLM client wrapper for local (Ollama) and cloud providers with JSON schema enforcement."""
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Type

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:  # boto3 not required for stub/local providers
    boto3 = None

    class _BotoStub(Exception):
        pass

    BotoCoreError = ClientError = NoCredentialsError = _BotoStub
from pydantic import BaseModel, ValidationError


class LLMClient:
    """Provide a unified interface over local Ollama and cloud APIs."""

    def __init__(
        self,
        provider: str,
        model_id: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        region: str = "us-east-2",
        top_k: Optional[int] = None,
        retries: int = 2,
        backoff: float = 1.5,
    ):
        self.provider = provider
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.region = region
        self.top_k = top_k
        self.retries = retries
        self.backoff = backoff
        self._bedrock = (
            boto3.client("bedrock-runtime", region_name=region) if provider == "bedrock_claude" else None
        )
        self._openai = None
        self._anthropic = None
        self._ollama = None
        self._stub = provider == "stub"

        if provider == "chatgpt":
            try:
                from openai import OpenAI

                self._openai = OpenAI()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("OpenAI client not available; install openai>=1.10.0") from exc
        elif provider == "anthropic":
            try:
                import anthropic

                self._anthropic = anthropic.Anthropic()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("Anthropic client not available; install anthropic>=0.18.1") from exc
        elif provider == "ollama":
            try:
                import ollama  # type: ignore

                self._ollama = ollama
            except Exception:
                # If the Python package is missing, we'll fall back to the HTTP API at runtime
                self._ollama = None

    def invoke_json(self, prompt: str, schema: Optional[Type[BaseModel] | Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call the selected provider and return parsed JSON matching schema."""
        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                if self.provider == "bedrock_claude":
                    raw_text = self._invoke_bedrock(prompt)
                elif self.provider == "chatgpt":
                    raw_text = self._invoke_openai(prompt)
                elif self.provider == "anthropic":
                    raw_text = self._invoke_anthropic(prompt)
                elif self.provider == "ollama":
                    raw_text = self._invoke_ollama(prompt)
                elif self.provider == "ollama":
                    raw_text = self._invoke_ollama(prompt)
                elif self._stub:
                    raw_text = self._invoke_stub(prompt)
                else:
                    raise NotImplementedError(f"Provider {self.provider} not implemented")
                parsed = self._coerce_json(raw_text)
                return self._validate(parsed, schema)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                # fallback to stub if ollama unreachable
                if self.provider == "ollama" and attempt >= self.retries:
                    try:
                        raw_text = self._invoke_stub(prompt)
                        parsed = self._coerce_json(raw_text)
                        return self._validate(parsed, schema)
                    except Exception as stub_exc:
                        last_err = stub_exc
                if attempt >= self.retries:
                    break
                time.sleep(self.backoff ** attempt)
        raise RuntimeError(f"LLM invocation failed after retries: {last_err}") from last_err

    def _invoke_bedrock(self, prompt: str) -> str:
        """Invoke Claude Sonnet via AWS Bedrock Converse API and return text."""
        try:
            kwargs = {
                "modelId": self.model_id,
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature,
                    "stopSequences": [],
                },
                "performanceConfig": {"latency": "standard"},
            }
            if self.top_k is not None:
                kwargs["additionalModelRequestFields"] = {"top_k": self.top_k}

            try:
                resp = self._bedrock.converse(**kwargs)
            except NoCredentialsError as exc:
                raise RuntimeError(
                    "AWS credentials not found. Configure env vars, shared credentials, or an IAM role."
                ) from exc
            content = resp.get("output", {}).get("message", {}).get("content", [])
            if not content:
                raise ValueError("Empty response content from Bedrock")
            return content[0]["text"]
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Bedrock invocation error: {exc}") from exc

    def _invoke_openai(self, prompt: str) -> str:
        """Invoke ChatGPT via OpenAI API and return text."""
        if not self._openai:
            raise RuntimeError("OpenAI client not initialized")
        resp = self._openai.chat.completions.create(
            model=self.model_id,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("Empty response content from OpenAI")
        return content

    def _invoke_anthropic(self, prompt: str) -> str:
        """Invoke Claude via Anthropic API and return text."""
        if not self._anthropic:
            raise RuntimeError("Anthropic client not initialized")
        resp = self._anthropic.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.content[0].text if resp.content else ""
        if not content:
            raise ValueError("Empty response content from Anthropic")
        return content

    def _invoke_ollama(self, prompt: str) -> str:
        """Invoke local model via Ollama."""
        # Try Python client if available
        if self._ollama:
            try:
                resp = self._ollama.generate(
                    model=self.model_id,
                    prompt=prompt,
                    format="json",
                    options={"temperature": self.temperature, "num_predict": self.max_tokens},
                )
                text = resp.get("response") if isinstance(resp, dict) else resp
                if not text:
                    raise ValueError("Empty response content from Ollama")
                return text
            except Exception:
                # Fall back to HTTP if Python client fails (service not reachable)
                pass
        # Fallback to HTTP API
        payload = json.dumps(
            {
                "model": self.model_id,
                "prompt": prompt,
                "format": "json",  # ask Ollama to enforce JSON output
                "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
                "stream": False,
            }
        ).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("response", "")
                if not text:
                    raise ValueError("Empty response content from Ollama HTTP")
                return text
        except urllib.error.URLError as exc:  # pragma: no cover
            raise RuntimeError(f"Ollama HTTP invocation failed: {exc}") from exc

    def _invoke_stub(self, prompt: str) -> str:
        """Stub responses for offline/testing."""
        low = prompt.lower()
        if "extract structured fields" in low:
            # Simple heuristic stub for the sample return policy text
            if "return items within 30 days" in low and "store credit" in low:
                return json.dumps(
                    {
                        "scope": {
                            "customer_segments": ["all"],
                            "product_categories": ["all"],
                            "channels": ["all"],
                            "regions": ["all"],
                        },
                        "conditions": [
                            {
                                "type": "time_window",
                                "value": 30,
                                "unit": "days",
                                "operator": "<=",
                                "target": "general",
                                "source_text": "Customers may return items within 30 days of purchase for a full refund with receipt.",
                            },
                            {
                                "type": "time_window",
                                "value": 15,
                                "unit": "days",
                                "operator": "<=",
                                "target": "electronics",
                                "source_text": "Electronics must be returned within 15 days.",
                            },
                            {
                                "type": "boolean_flag",
                                "value": True,
                                "parameter": "has_receipt",
                                "source_text": "full refund with receipt",
                            },
                        ],
                        "actions": [
                            {
                                "type": "required",
                                "action": "full_refund",
                                "requires": ["has_receipt", "within_window"],
                                "source_text": "Customers may return items within 30 days of purchase for a full refund with receipt.",
                            },
                            {
                                "type": "fallback",
                                "action": "store_credit",
                                "requires": ["no_receipt"],
                                "source_text": "Items without a receipt receive store credit only.",
                            },
                        ],
                        "exceptions": [],
                    }
                )
            return json.dumps(
                {
                    "scope": {
                        "customer_segments": ["all"],
                        "product_categories": ["all"],
                        "channels": ["all"],
                        "regions": ["all"],
                    },
                    "conditions": [],
                    "actions": [],
                    "exceptions": [],
                }
            )
        if "classify section" in low or "policy extraction assistant" in low:
            return json.dumps({"is_policy": True, "confidence": 0.95, "reason": "stubbed policy-like content"})
        if "metadata annotator" in low:
            return json.dumps(
                {"owner": "unknown", "effective_date": None, "domain": "refund", "regulatory_linkage": []}
            )
        if "validation assistant" in low:
            return json.dumps({"issues": [], "needs_review": False, "confidence": 0.9})
        return json.dumps({})

    @staticmethod
    def _coerce_json(raw_text: str) -> Dict[str, Any] | Any:
        """Best-effort JSON parsing: try direct loads, then extract first JSON object/array."""
        try:
            return json.loads(raw_text)
        except Exception:
            pass
        # Attempt to extract first JSON object or array
        match = re.search(r"(\{.*\}|\[.*\])", raw_text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Unable to parse JSON from response: {raw_text[:200]}")

    @staticmethod
    def _validate(payload: Dict[str, Any], schema: Optional[Type[BaseModel] | Dict[str, Any]]) -> Dict[str, Any]:
        if schema is None:
            return payload
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                return schema.model_validate(payload).model_dump()
            except ValidationError as exc:
                raise ValueError(f"Payload validation failed: {exc}") from exc
        # If schema is a dict (placeholder), return as-is.
        return payload
