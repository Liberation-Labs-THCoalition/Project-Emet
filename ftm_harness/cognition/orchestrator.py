"""Hierarchical Supervisor routing for investigative journalism workflows.

The :class:`Orchestrator` maps incoming requests to *investigation domains*
(entity_search, cross_reference, document_analysis, ...) using keyword
matching with an optional LLM classification fallback for ambiguous requests.

When multiple candidate domains are detected or keyword confidence is below
threshold, the EFE calculator is invoked to score each candidate and select
the best policy, applying domain-specific weight profiles.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ftm_harness.cognition.efe import (
    CROSS_REFERENCE_WEIGHTS,
    DATA_QUALITY_WEIGHTS,
    DEFAULT_WEIGHTS,
    DIGITAL_SECURITY_WEIGHTS,
    DOCUMENT_ANALYSIS_WEIGHTS,
    EFECalculator,
    EFEScore,
    EFEWeights,
    ENTITY_SEARCH_WEIGHTS,
    FINANCIAL_INVESTIGATION_WEIGHTS,
    GOVERNMENT_ACCOUNTABILITY_WEIGHTS,
    MONITORING_WEIGHTS,
    NETWORK_ANALYSIS_WEIGHTS,
    NLP_EXTRACTION_WEIGHTS,
    PUBLICATION_WEIGHTS,
    VERIFICATION_WEIGHTS,
)
from ftm_harness.cognition.model_router import ModelRouter, ModelTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain-specific EFE weight mapping
# ---------------------------------------------------------------------------

DOMAIN_EFE_WEIGHTS: dict[str, EFEWeights] = {
    "entity_search": ENTITY_SEARCH_WEIGHTS,
    "cross_reference": CROSS_REFERENCE_WEIGHTS,
    "document_analysis": DOCUMENT_ANALYSIS_WEIGHTS,
    "nlp_extraction": NLP_EXTRACTION_WEIGHTS,
    "network_analysis": NETWORK_ANALYSIS_WEIGHTS,
    "financial_investigation": FINANCIAL_INVESTIGATION_WEIGHTS,
    "government_accountability": GOVERNMENT_ACCOUNTABILITY_WEIGHTS,
    "monitoring": MONITORING_WEIGHTS,
    "verification": VERIFICATION_WEIGHTS,
    "publication": PUBLICATION_WEIGHTS,
    "data_quality": DATA_QUALITY_WEIGHTS,
    "digital_security": DIGITAL_SECURITY_WEIGHTS,
    "general": DEFAULT_WEIGHTS,
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record of a routing outcome."""

    skill_domain: str
    confidence: float
    reasoning: str
    model_tier: ModelTier
    efe_score: Optional[EFEScore] = None


@dataclass
class OrchestratorConfig:
    """Configuration for the :class:`Orchestrator`."""

    routing_table: dict[str, str] = field(default_factory=dict)
    fallback_domain: str = "general"
    confidence_threshold: float = 0.6


# ---------------------------------------------------------------------------
# Investigation-specific routing table
# ---------------------------------------------------------------------------

_DEFAULT_ROUTING_TABLE: dict[str, str] = {
    # --- Entity Search ---
    "search": "entity_search",
    "find": "entity_search",
    "lookup": "entity_search",
    "entity": "entity_search",
    "person": "entity_search",
    "company": "entity_search",
    "organization": "entity_search",
    "vessel": "entity_search",
    "aircraft": "entity_search",
    "vehicle": "entity_search",
    "address": "entity_search",
    "aleph": "entity_search",
    "collection": "entity_search",
    "dataset": "entity_search",
    # --- Cross-Referencing ---
    "cross-reference": "cross_reference",
    "xref": "cross_reference",
    "match": "cross_reference",
    "compare": "cross_reference",
    "deduplicate": "cross_reference",
    "reconcile": "cross_reference",
    "merge": "cross_reference",
    "profile": "cross_reference",
    # --- Document Analysis ---
    "document": "document_analysis",
    "upload": "document_analysis",
    "ingest": "document_analysis",
    "ocr": "document_analysis",
    "pdf": "document_analysis",
    "extract": "document_analysis",
    "scan": "document_analysis",
    "file": "document_analysis",
    # --- NLP Extraction ---
    "ner": "nlp_extraction",
    "extract entities": "nlp_extraction",
    "name recognition": "nlp_extraction",
    "relationship extraction": "nlp_extraction",
    "language detection": "nlp_extraction",
    "classify document": "nlp_extraction",
    "categorize": "nlp_extraction",
    # --- Network Analysis ---
    "network": "network_analysis",
    "graph": "network_analysis",
    "ownership": "network_analysis",
    "beneficial owner": "network_analysis",
    "directorship": "network_analysis",
    "connection": "network_analysis",
    "centrality": "network_analysis",
    "community": "network_analysis",
    "relationship map": "network_analysis",
    "power structure": "network_analysis",
    # --- Financial Investigation ---
    "financial": "financial_investigation",
    "money trail": "financial_investigation",
    "payment": "financial_investigation",
    "transaction": "financial_investigation",
    "bank": "financial_investigation",
    "asset": "financial_investigation",
    "shell company": "financial_investigation",
    "offshore": "financial_investigation",
    "tax": "financial_investigation",
    "iban": "financial_investigation",
    "swift": "financial_investigation",
    "beneficial ownership": "financial_investigation",
    "corporate structure": "financial_investigation",
    "money laundering": "financial_investigation",
    "structuring": "financial_investigation",
    # --- Government Accountability ---
    "government": "government_accountability",
    "foia": "government_accountability",
    "public record": "government_accountability",
    "campaign finance": "government_accountability",
    "lobby": "government_accountability",
    "regulation": "government_accountability",
    "corruption": "government_accountability",
    "procurement": "government_accountability",
    "contract": "government_accountability",
    "transparency": "government_accountability",
    "ethics violation": "government_accountability",
    "public official": "government_accountability",
    # --- Monitoring ---
    "monitor": "monitoring",
    "alert": "monitoring",
    "watchlist": "monitoring",
    "sanction": "monitoring",
    "screening": "monitoring",
    "track": "monitoring",
    "watch": "monitoring",
    "notify": "monitoring",
    # --- Verification ---
    "verify": "verification",
    "fact-check": "verification",
    "corroborate": "verification",
    "confirm": "verification",
    "authenticate": "verification",
    "validate": "verification",
    "source reliability": "verification",
    # --- Publication ---
    "publish": "publication",
    "story": "publication",
    "narrative": "publication",
    "article": "publication",
    "timeline": "publication",
    "report": "publication",
    "impact": "publication",
    # --- Data Quality ---
    "clean": "data_quality",
    "deduplicate": "data_quality",
    "normalize": "data_quality",
    "validate schema": "data_quality",
    "data quality": "data_quality",
    "fix entities": "data_quality",
    # --- Digital Security ---
    "security": "digital_security",
    "encryption": "digital_security",
    "source protection": "digital_security",
    "opsec": "digital_security",
    "threat": "digital_security",
    "surveillance": "digital_security",
    "secure communication": "digital_security",
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Classify incoming messages and route them to investigation domains.

    Parameters
    ----------
    config:
        Routing configuration.  Uses sensible defaults when *None*.
    model_router:
        Used to determine model tier for the routed task.
    llm_classifier:
        Optional async callable ``(message, domains) -> (domain, confidence)``
        injected for LLM-based disambiguation.
    efe_calculator:
        Optional EFE calculator for active-inference-informed routing.
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        model_router: ModelRouter | None = None,
        llm_classifier: Callable[..., Awaitable[tuple[str, float]]] | None = None,
        efe_calculator: EFECalculator | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig(
            routing_table=dict(_DEFAULT_ROUTING_TABLE),
        )
        if not self._config.routing_table:
            self._config.routing_table = dict(_DEFAULT_ROUTING_TABLE)
        self._model_router = model_router or ModelRouter()
        self._llm_classifier = llm_classifier
        self._efe = efe_calculator or EFECalculator()

    # -- public API ---------------------------------------------------------

    async def classify_request(
        self,
        message: str,
        investigation_context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """Classify *message* into an investigation domain.

        1. Try keyword matching against the routing table.
        2. If multiple candidate domains or low confidence, use EFE scoring.
        3. If confidence still below threshold and LLM classifier exists, delegate.
        4. Otherwise fall back to ``config.fallback_domain``.
        """
        domain, confidence, reasoning, candidate_hits = self._keyword_match(message)

        efe_score: EFEScore | None = None

        if len(candidate_hits) > 1 or confidence < self._config.confidence_threshold:
            efe_score = self._score_candidates_with_efe(candidate_hits, confidence)
            if efe_score is not None:
                domain = efe_score.policy_id
                reasoning = (
                    f"EFE-selected '{domain}' "
                    f"(total={efe_score.total:.3f}, "
                    f"risk={efe_score.risk_component:.3f}, "
                    f"ambiguity={efe_score.ambiguity_component:.3f}, "
                    f"epistemic={efe_score.epistemic_component:.3f})"
                )
                confidence = max(
                    confidence, 0.5 + 0.3 * (1.0 - max(efe_score.total, 0.0))
                )

        if (
            confidence < self._config.confidence_threshold
            and self._llm_classifier is not None
        ):
            try:
                domains = list(set(self._config.routing_table.values()))
                domains.append(self._config.fallback_domain)
                llm_domain, llm_confidence = await self._llm_classifier(
                    message, domains
                )
                if llm_confidence > confidence:
                    domain = llm_domain
                    confidence = llm_confidence
                    reasoning = "LLM classification"
                    efe_score = None
            except Exception:
                logger.exception("LLM classifier failed — using keyword result")

        tier = self._tier_for_domain(domain, efe_score)
        return RoutingDecision(
            skill_domain=domain,
            confidence=confidence,
            reasoning=reasoning,
            model_tier=tier,
            efe_score=efe_score,
        )

    async def route(
        self,
        message: str,
        investigation_id: str,
        context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """Full routing pipeline: classify, validate, and log."""
        decision = await self.classify_request(message, investigation_context=context)

        log_entry: dict[str, Any] = {
            "investigation_id": investigation_id,
            "message_preview": message[:120],
            "skill_domain": decision.skill_domain,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "model_tier": decision.model_tier.value,
        }
        if decision.efe_score is not None:
            log_entry["efe_total"] = decision.efe_score.total
        logger.info("Routing decision: %s", log_entry)

        return decision

    def register_domain(self, domain: str, keywords: list[str]) -> None:
        """Add or update keywords for *domain* in the routing table."""
        for kw in keywords:
            self._config.routing_table[kw.lower()] = domain

    def get_routing_table(self) -> dict[str, str]:
        """Return a **copy** of the current routing table."""
        return dict(self._config.routing_table)

    # -- internals ----------------------------------------------------------

    def _keyword_match(
        self, message: str
    ) -> tuple[str, float, str, dict[str, int]]:
        """Return ``(domain, confidence, reasoning, hits)`` via keyword scan."""
        msg_lower = message.lower()
        hits: dict[str, int] = {}
        for keyword, domain in self._config.routing_table.items():
            count = len(re.findall(re.escape(keyword), msg_lower))
            if count:
                hits[domain] = hits.get(domain, 0) + count

        if not hits:
            return self._config.fallback_domain, 0.3, "no keyword match", hits

        best_domain = max(hits, key=hits.__getitem__)
        total_hits = sum(hits.values())
        confidence = min(0.95, 0.5 + 0.1 * hits[best_domain])
        reasoning = (
            f"keyword match: {hits[best_domain]}/{total_hits} hits for '{best_domain}'"
        )
        return best_domain, confidence, reasoning, hits

    def _score_candidates_with_efe(
        self,
        candidate_hits: dict[str, int],
        keyword_confidence: float,
    ) -> EFEScore | None:
        """Score candidate domains with EFE and return the best."""
        if not candidate_hits:
            return None

        total_hits = max(sum(candidate_hits.values()), 1)
        uncertainty = 1.0 - keyword_confidence

        scores: list[EFEScore] = []
        for domain, hit_count in candidate_hits.items():
            weights = DOMAIN_EFE_WEIGHTS.get(domain, DEFAULT_WEIGHTS)
            information_gain = hit_count / total_hits

            predicted = {
                "relevance": information_gain,
                "specificity": hit_count / total_hits,
            }
            desired = {"relevance": 1.0, "specificity": 1.0}

            score = self._efe.calculate_efe(
                policy_id=domain,
                predicted_outcome=predicted,
                desired_outcome=desired,
                uncertainty=uncertainty,
                information_gain=information_gain,
                weights=weights,
            )
            scores.append(score)

        return self._efe.select_policy(scores)

    def _tier_for_domain(
        self,
        domain: str,
        efe_score: EFEScore | None = None,
    ) -> ModelTier:
        """EFE-informed tier assignment per investigation domain.

        High-stakes domains (financial investigation, verification,
        publication) route to more powerful models. Monitoring and
        search can use fast models.
        """
        if efe_score is not None:
            if efe_score.risk_component > 0.3:
                return ModelTier.POWERFUL
            if efe_score.risk_component > 0.15:
                return ModelTier.BALANCED
            if efe_score.ambiguity_component > 0.2:
                return ModelTier.BALANCED

        # Domain-based heuristics
        high_stakes = {
            "financial_investigation", "verification", "publication",
            "digital_security", "government_accountability",
        }
        medium_stakes = {
            "cross_reference", "nlp_extraction", "network_analysis",
            "data_quality",
        }

        if domain in high_stakes:
            return ModelTier.POWERFUL
        if domain in medium_stakes:
            return ModelTier.BALANCED
        return ModelTier.FAST
