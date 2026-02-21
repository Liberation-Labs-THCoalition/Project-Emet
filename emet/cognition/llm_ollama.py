"""Ollama LLM client — local model inference via Ollama REST API.

This is Emet's default LLM provider. Ollama runs open-source models
locally with zero API cost and full data privacy — critical for
investigative journalism where investigation details must not leave
the journalist's machine.

Requires Ollama running locally: https://ollama.ai

Tested with: llama3.2, mistral, deepseek-r1, phi3, gemma2.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from emet.cognition.llm_base import (
    LLMClient,
    LLMProvider,
    LLMResponse,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier → model mapping
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_MODELS: dict[str, str] = {
    "fast": "llama3.2:3b",
    "balanced": "mistral:7b",
    "powerful": "deepseek-r1:14b",
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OllamaClient(LLMClient):
    """Async client for local Ollama inference.

    Parameters
    ----------
    host:
        Ollama server URL. Default ``http://localhost:11434``.
    models:
        Tier → model name mapping. Falls back to ``DEFAULT_OLLAMA_MODELS``.
    timeout:
        Request timeout in seconds. Generous default because local
        inference on CPU can be slow for large models.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        models: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._models = models or dict(DEFAULT_OLLAMA_MODELS)
        self._timeout = timeout

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.OLLAMA

    def _resolve_model(self, tier: str) -> str:
        """Map tier name to concrete Ollama model tag."""
        return self._models.get(tier, self._models.get("balanced", "mistral:7b"))

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Ollama API with error handling."""
        url = f"{self._host}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as e:
            raise LLMUnavailableError(
                f"Cannot connect to Ollama at {self._host}. "
                f"Is Ollama running? Install: https://ollama.ai — Error: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMUnavailableError(
                f"Ollama request timed out after {self._timeout}s. "
                f"Model may still be loading or hardware is too slow."
            ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise LLMUnavailableError(
                    f"Model not found in Ollama. Run: ollama pull {payload.get('model', '?')}"
                ) from e
            raise

    # -- Core interface ------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: list[str] | None = None,
        tier: str = "balanced",
    ) -> LLMResponse:
        model = self._resolve_model(tier)

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if stop_sequences:
            payload["options"]["stop"] = stop_sequences

        data = await self._post("/api/chat", payload)

        # Parse Ollama response format
        message = data.get("message", {})
        text = message.get("content", "")
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)
        done_reason = data.get("done_reason", None)

        return LLMResponse(
            text=text,
            model=model,
            provider=LLMProvider.OLLAMA,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,  # Local inference is free
            stop_reason=done_reason,
            metadata={
                "total_duration_ns": data.get("total_duration", 0),
                "load_duration_ns": data.get("load_duration", 0),
                "eval_duration_ns": data.get("eval_duration", 0),
            },
        )

    async def classify_intent(
        self,
        message: str,
        domains: list[str],
    ) -> tuple[str, float]:
        domain_list = ", ".join(domains)

        prompt = (
            f"Classify the following user message into exactly one of these domains: {domain_list}\n\n"
            f'User message: "{message}"\n\n'
            f"Respond with ONLY a JSON object in this exact format:\n"
            f'{{"domain": "<chosen_domain>", "confidence": <0.0-1.0>}}\n\n'
            f"Choose the single best matching domain. If unsure, use confidence below 0.5."
        )

        response = await self.complete(
            prompt,
            tier="fast",
            max_tokens=100,
            temperature=0.0,
        )

        try:
            # Strip markdown code fences if model wraps response
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(text)
            domain = result.get("domain", "general")
            confidence = float(result.get("confidence", 0.5))

            if domain not in domains:
                logger.warning("Ollama returned unknown domain %r, falling back", domain)
                domain = "general"
                confidence = 0.3

            return domain, confidence
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse Ollama classification response: %s", e)
            return "general", 0.3

    async def generate_content(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        tier: str = "balanced",
        system: str | None = None,
    ) -> str:
        full_system = system or ""
        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            full_system = f"{full_system}\n\nContext:\n{context_str}"

        response = await self.complete(
            prompt,
            tier=tier,
            system=full_system.strip() or None,
            max_tokens=2048,
            temperature=0.7,
        )
        return response.text

    async def extract_entities(
        self,
        text: str,
        entity_schema: dict[str, str],
    ) -> dict[str, Any]:
        schema_desc = "\n".join(
            f'- "{name}": {desc}' for name, desc in entity_schema.items()
        )

        prompt = (
            f"Extract the following entities from the text:\n{schema_desc}\n\n"
            f'Text: "{text}"\n\n'
            f"Respond with ONLY a JSON object containing the extracted entities.\n"
            f"Use null for entities not found in the text."
        )

        response = await self.complete(
            prompt,
            tier="fast",
            max_tokens=500,
            temperature=0.0,
        )

        try:
            text_out = response.text.strip()
            if text_out.startswith("```"):
                text_out = text_out.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return json.loads(text_out)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Ollama entity extraction response")
            return {}

    async def health_check(self) -> bool:
        """Check if Ollama is running and a model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    if models:
                        return True
                    logger.warning("Ollama running but no models pulled")
                    return False
                return False
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Return list of locally available model tags."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
