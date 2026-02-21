"""Stub LLM client — deterministic responses for testing.

Returns canned responses that make the test suite pass without any
external dependencies. This is the final fallback when both Ollama
and Anthropic are unavailable.

Responses are keyword-matched to simulate basic intent classification
and entity extraction. Not intended for real investigation work.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from emet.cognition.llm_base import (
    LLMClient,
    LLMProvider,
    LLMResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canned response patterns
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "entity_search": ["search", "find", "lookup", "who is", "look up"],
    "network_analysis": ["network", "graph", "connections", "relationship", "linked"],
    "nlp_extraction": ["extract", "parse", "entities in", "names in", "text"],
    "cross_reference": ["cross-reference", "match", "compare", "verify against"],
    "document_analysis": ["document", "read", "pdf", "analyze this file"],
    "data_quality": ["quality", "clean", "validate", "check data"],
    "financial_investigation": ["financial", "money", "payment", "transaction", "bank", "follow the money"],
    "corporate_research": ["company", "corporate", "shell", "ownership", "subsidiary", "registered"],
    "government_accountability": ["government", "procurement", "contract", "tender", "official"],
    "environmental_investigation": ["environment", "pollution", "emission", "waste", "climate"],
    "labor_investigation": ["labor", "worker", "employment", "wage", "safety"],
    "story_development": ["story", "narrative", "write", "angle", "pitch", "draft"],
    "verification": ["verify", "fact-check", "confirm", "source check", "evidence"],
    "monitoring": ["monitor", "alert", "watch", "track", "notify", "changes"],
    "resources": ["resource", "guide", "database", "tool", "help me find"],
}


class StubClient(LLMClient):
    """Deterministic stub client for testing.

    Parameters
    ----------
    default_response:
        Text returned for any prompt that doesn't match a pattern.
    latency_ms:
        Simulated latency (not actually delayed — just recorded in metadata).
    """

    def __init__(
        self,
        default_response: str = "I understand. Here is my analysis based on the available data.",
        latency_ms: int = 0,
    ) -> None:
        self._default_response = default_response
        self._latency_ms = latency_ms
        self._call_log: list[dict[str, Any]] = []

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.STUB

    @property
    def call_log(self) -> list[dict[str, Any]]:
        """Access recorded calls for test assertions."""
        return self._call_log

    def reset(self) -> None:
        """Clear the call log."""
        self._call_log.clear()

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
        self._call_log.append({
            "method": "complete",
            "prompt": prompt,
            "system": system,
            "tier": tier,
            "max_tokens": max_tokens,
        })

        # Estimate token counts from character length
        prompt_tokens = len(prompt) // 4
        response_text = self._default_response
        output_tokens = len(response_text) // 4

        return LLMResponse(
            text=response_text,
            model=f"stub/{tier}",
            provider=LLMProvider.STUB,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,
            stop_reason="end_turn",
            metadata={"simulated_latency_ms": self._latency_ms},
        )

    async def classify_intent(
        self,
        message: str,
        domains: list[str],
    ) -> tuple[str, float]:
        self._call_log.append({
            "method": "classify_intent",
            "message": message,
            "domains": domains,
        })

        message_lower = message.lower()

        # Keyword matching against domain patterns
        best_domain = "general"
        best_score = 0.0

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if domain not in domains:
                continue
            hits = sum(1 for kw in keywords if kw in message_lower)
            if hits > 0:
                score = min(0.5 + (hits * 0.15), 0.95)
                if score > best_score:
                    best_score = score
                    best_domain = domain

        # If no keyword match, try first available domain
        if best_score == 0.0 and domains:
            best_domain = domains[0]
            best_score = 0.3

        return best_domain, best_score

    async def generate_content(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        tier: str = "balanced",
        system: str | None = None,
    ) -> str:
        self._call_log.append({
            "method": "generate_content",
            "prompt": prompt,
            "context": context,
            "tier": tier,
        })
        return self._default_response

    async def extract_entities(
        self,
        text: str,
        entity_schema: dict[str, str],
    ) -> dict[str, Any]:
        self._call_log.append({
            "method": "extract_entities",
            "text": text,
            "schema": entity_schema,
        })

        # Simple regex-based extraction for testing
        result: dict[str, Any] = {}
        for name, description in entity_schema.items():
            desc_lower = description.lower()
            if "person" in desc_lower or "name" in desc_lower:
                # Try to find capitalized names
                names = re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text)
                result[name] = names[0] if names else None
            elif "organization" in desc_lower or "company" in desc_lower:
                # Try to find org-like patterns
                orgs = re.findall(r"\b[A-Z][A-Za-z]+ (?:Inc|Corp|Ltd|LLC|GmbH|AG|SA|Group|Holdings)\b", text)
                result[name] = orgs[0] if orgs else None
            elif "date" in desc_lower:
                dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
                result[name] = dates[0] if dates else None
            elif "amount" in desc_lower or "money" in desc_lower:
                amounts = re.findall(r"[\$€£]\s?[\d,]+(?:\.\d{2})?", text)
                result[name] = amounts[0] if amounts else None
            elif "location" in desc_lower or "place" in desc_lower or "country" in desc_lower:
                # Return None — too hard to extract without real NLP
                result[name] = None
            else:
                result[name] = None

        return result

    async def health_check(self) -> bool:
        """Stub is always healthy."""
        return True
