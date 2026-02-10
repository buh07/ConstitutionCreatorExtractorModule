"""LLM client wrapper for local (Ollama) and cloud providers with JSON schema enforcement."""
import json
import time
from typing import Any, Dict, Optional, Type

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
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
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("Ollama client not available; install ollama") from exc

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
                else:
                    raise NotImplementedError(f"Provider {self.provider} not implemented")
                parsed = json.loads(raw_text)
                return self._validate(parsed, schema)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
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
        if not self._ollama:
            raise RuntimeError("Ollama provider not initialized")
        resp = self._ollama.generate(model=self.model_id, prompt=prompt, options={"temperature": self.temperature})
        # ollama.generate returns dict with 'response'
        text = resp.get("response") if isinstance(resp, dict) else resp
        if not text:
            raise ValueError("Empty response content from Ollama")
        return text

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
