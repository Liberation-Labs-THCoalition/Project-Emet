"""Anthropic Claude API client — cloud LLM fallback.

Used when local Ollama models are unavailable or when a task exceeds
local model capabilities. Carries a non-zero cost per token and sends
investigation data to Anthropic's servers — users should be aware of
the privacy implications for sensitive investigations.

Requires: ``ANTHROPIC_API_KEY`` in environment or settings.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from emet.cognition.llm_base import (
    LLMClient,
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMUnavailableError,
)
from emet.cognition.model_router import CostTracker, ModelRouter, ModelTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier mapping
# ---------------------------------------------------------------------------

_TIER_TO_MODEL_TIER: dict[str, ModelTier] = {
    "fast": ModelTier.FAST,
    "balanced": ModelTier.BALANCED,
    "powerful": ModelTier.POWERFUL,
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AnthropicClient(LLMClient):
    """Async Anthropic client with tiered model routing and cost tracking.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    model_router:
        Router for resolving tiers to concrete model IDs.
    cost_tracker:
        Optional cost tracker for budget enforcement.
    """

    def __init__(
        self,
        api_key: str,
        model_router: ModelRouter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "No Anthropic API key provided. Set ANTHROPIC_API_KEY in environment "
                "or switch to Ollama: LLM_PROVIDER=ollama"
            )

        self._client = AsyncAnthropic(api_key=api_key)
        self._router = model_router or ModelRouter()
        self._cost_tracker = cost_tracker

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.ANTHROPIC

    def _resolve_model(self, tier: str) -> str:
        model_tier = _TIER_TO_MODEL_TIER.get(tier, ModelTier.BALANCED)
        return self._router.resolve(model_tier)

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
        model_id = self._resolve_model(tier)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                system=system or "",
                messages=messages,
                temperature=temperature,
                stop_sequences=stop_sequences or [],
            )
        except Exception as e:
            # Map connection-type errors to LLMUnavailableError for fallback
            error_str = str(e).lower()
            if any(k in error_str for k in ("connection", "timeout", "unreachable", "rate_limit")):
                raise LLMUnavailableError(f"Anthropic API unreachable: {e}") from e
            raise LLMError(f"Anthropic API error: {e}") from e

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._router.estimate_cost(model_id, input_tokens, output_tokens)

        if self._cost_tracker:
            self._cost_tracker.record(model_id, cost)

        return LLMResponse(
            text=text,
            model=model_id,
            provider=LLMProvider.ANTHROPIC,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            stop_reason=response.stop_reason,
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
            result = json.loads(response.text.strip())
            domain = result.get("domain", "general")
            confidence = float(result.get("confidence", 0.5))

            if domain not in domains:
                logger.warning("LLM returned unknown domain %r, falling back", domain)
                domain = "general"
                confidence = 0.3

            return domain, confidence
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse LLM classification response: %s", e)
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
            return json.loads(response.text.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse entity extraction response")
            return {}

    async def health_check(self) -> bool:
        """Check if Anthropic API is reachable with a minimal call."""
        try:
            resp = await self.complete(
                "Respond with exactly: OK",
                max_tokens=10,
                temperature=0.0,
                tier="fast",
            )
            return "OK" in resp.text
        except Exception:
            return False
