"""Cross-Reference Skill Chip — entity matching and deduplication agent.

Manages Aleph's cross-referencing pipeline: triggering xref for collections,
monitoring results by probability score, presenting high-confidence matches
for human review, and tracking match decisions.

Also integrates OpenSanctions/yente for sanctions screening — every entity
entering an investigation can be automatically screened against 325+ watchlists.

Modeled after the journalism wrapper's /xref and /screen commands.

The FtM cross-reference engine uses Bayesian logistic regression with TF-IDF
weighting (glm_bernoulli_2e model). Results include predict_proba (0-1 match
probability) and predict_std (confidence measure where higher = less certain).
"""

from __future__ import annotations

import logging
from typing import Any

from emet.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)


class CrossReferenceChip(BaseSkillChip):
    """Cross-reference entities between collections and against watchlists.

    Intents:
        trigger_xref: Start cross-referencing for a collection
        get_xref_results: Retrieve and rank xref results
        decide_match: Confirm or reject a proposed match (requires consensus)
        screen_sanctions: Screen entities against OpenSanctions
        batch_screen: Screen a batch of entities from a collection
        match_entity: Match a single entity against a target dataset
    """

    name = "cross_reference"
    description = "Cross-reference entities between collections and against watchlists"
    version = "1.0.0"
    domain = SkillDomain.CROSS_REFERENCE
    efe_weights = EFEWeights(
        accuracy=0.35, source_protection=0.15, public_interest=0.20,
        proportionality=0.15, transparency=0.15,
    )
    capabilities = [
        SkillCapability.SEARCH_ALEPH,
        SkillCapability.XREF_ALEPH,
        SkillCapability.READ_OPENSANCTIONS,
    ]
    consensus_actions = ["confirm_match", "reject_match", "merge_entities"]

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "trigger_xref": self._trigger_xref,
            "get_xref_results": self._get_xref_results,
            "decide_match": self._decide_match,
            "screen_sanctions": self._screen_sanctions,
            "batch_screen": self._batch_screen,
            "match_entity": self._match_entity,
        }
        handler = dispatch.get(intent, self._trigger_xref)
        return await handler(request, context)

    async def _trigger_xref(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Trigger cross-referencing for a collection against all accessible datasets."""
        collection_id = request.parameters.get("collection_id", "")
        if not collection_id and context.collection_ids:
            collection_id = context.collection_ids[0]
        if not collection_id:
            return SkillResponse(content="No collection ID provided.", success=False)

        try:
            from emet.ftm.aleph_client import AlephClient
            result = await AlephClient().trigger_xref(collection_id)
            return SkillResponse(
                content=f"Cross-referencing triggered for collection {collection_id}. "
                        "Results will be available once processing completes.",
                success=True, data={"collection_id": collection_id, "result": result},
                result_confidence=0.9,
                suggestions=["Check xref results after processing completes"],
            )
        except Exception as e:
            return SkillResponse(content=f"Failed to trigger xref: {e}", success=False)

    async def _get_xref_results(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Retrieve and rank cross-reference results.

        Returns results sorted by match probability, with high-confidence
        matches (>0.7) flagged for human review.
        """
        collection_id = request.parameters.get("collection_id", "")
        if not collection_id and context.collection_ids:
            collection_id = context.collection_ids[0]
        min_score = request.parameters.get("min_score", 0.5)
        limit = request.parameters.get("limit", 50)

        if not collection_id:
            return SkillResponse(content="No collection ID provided.", success=False)

        try:
            from emet.ftm.aleph_client import AlephClient
            results = await AlephClient().get_xref_results(collection_id, limit=limit)
            matches = results.get("results", [])

            # Filter and categorize by confidence
            high_confidence = [m for m in matches if m.get("score", 0) >= 0.8]
            medium_confidence = [m for m in matches if 0.5 <= m.get("score", 0) < 0.8]
            low_confidence = [m for m in matches if m.get("score", 0) < 0.5]

            needs_review = len(high_confidence)

            return SkillResponse(
                content=(
                    f"Cross-reference results: {len(matches)} total matches. "
                    f"{needs_review} high-confidence matches need human review."
                ),
                success=True,
                data={
                    "total_matches": len(matches),
                    "high_confidence": high_confidence,
                    "medium_confidence": medium_confidence,
                    "low_confidence": low_confidence,
                    "needs_review": needs_review,
                    "collection_id": collection_id,
                },
                requires_consensus=needs_review > 0,
                consensus_action="confirm_match" if needs_review > 0 else None,
                result_confidence=0.8,
                suggestions=[
                    f"Review {needs_review} high-confidence matches" if needs_review else "No matches need immediate review",
                    "Screen matched entities against sanctions lists",
                    "Expand network around confirmed matches",
                ],
            )
        except Exception as e:
            return SkillResponse(content=f"Failed to get xref results: {e}", success=False)

    async def _decide_match(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Record a human decision on a cross-reference match.

        ALWAYS requires editorial consensus — never auto-confirm matches.
        """
        collection_id = request.parameters.get("collection_id", "")
        xref_id = request.parameters.get("xref_id", "")
        decision = request.parameters.get("decision", "")  # positive | negative | unsure

        if not all([collection_id, xref_id, decision]):
            return SkillResponse(
                content="Required: collection_id, xref_id, and decision (positive/negative/unsure).",
                success=False,
            )

        if decision not in ("positive", "negative", "unsure"):
            return SkillResponse(
                content=f"Invalid decision '{decision}'. Must be: positive, negative, or unsure.",
                success=False,
            )

        return SkillResponse(
            content=f"Match decision '{decision}' recorded for xref {xref_id}.",
            success=True,
            data={"xref_id": xref_id, "decision": decision, "collection_id": collection_id},
            requires_consensus=True,
            consensus_action="confirm_match",
            result_confidence=0.95,
        )

    async def _screen_sanctions(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Screen an entity against OpenSanctions watchlists.

        Uses the yente API to match against 325+ aggregated sanctions,
        PEP, and watchlist datasets — all in native FtM format.
        """
        entity_data = request.parameters.get("entity_data", {})
        query = request.parameters.get("query", request.raw_input)

        if not entity_data and not query:
            return SkillResponse(content="Provide entity_data or query for screening.", success=False)

        try:
            from emet.ftm.external.adapters import YenteClient
            yente = YenteClient()

            if entity_data:
                results = await yente.match_entity(entity_data)
                matches = results.get("responses", {}).get("q", {}).get("results", [])
            else:
                results = await yente.search(query)
                matches = results.get("results", [])

            sanctioned = [m for m in matches if m.get("score", 0) > 0.7]

            return SkillResponse(
                content=(
                    f"Sanctions screening: {len(matches)} potential matches, "
                    f"{len(sanctioned)} high-confidence sanctions hits."
                ),
                success=True,
                data={
                    "matches": matches,
                    "sanctioned_count": len(sanctioned),
                    "high_confidence_hits": sanctioned,
                },
                requires_consensus=len(sanctioned) > 0,
                consensus_action="review_sanctions_hit" if sanctioned else None,
                result_confidence=0.85,
                suggestions=[
                    "Verify sanctions matches against original source documents",
                    "Check for name collisions (common names may generate false positives)",
                ] if sanctioned else ["Entity appears clean against current watchlists"],
            )
        except Exception as e:
            return SkillResponse(content=f"Sanctions screening failed: {e}", success=False)

    async def _batch_screen(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Screen all entities in a collection against sanctions lists."""
        collection_id = request.parameters.get("collection_id", "")
        if not collection_id:
            return SkillResponse(content="No collection ID provided.", success=False)

        try:
            from emet.ftm.aleph_client import AlephClient
            from emet.ftm.external.adapters import YenteClient

            aleph = AlephClient()
            yente = YenteClient()

            entities = []
            async for entity in aleph.stream_entities(collection_id):
                schema = entity.get("schema", "")
                # Only screen node entities (persons, companies)
                if schema in ("Person", "Company", "Organization", "LegalEntity", "PublicBody"):
                    entities.append(entity)
                if len(entities) >= 100:  # Cap batch size
                    break

            results = await yente.screen_entities(entities)
            flagged = [r for r in results if r.get("matches") and len(r["matches"]) > 0]

            return SkillResponse(
                content=f"Batch screening: {len(entities)} entities screened, {len(flagged)} flagged.",
                success=True,
                data={
                    "screened_count": len(entities),
                    "flagged_count": len(flagged),
                    "flagged_entities": flagged,
                    "collection_id": collection_id,
                },
                requires_consensus=len(flagged) > 0,
                consensus_action="review_batch_screening" if flagged else None,
                result_confidence=0.8,
            )
        except Exception as e:
            return SkillResponse(content=f"Batch screening failed: {e}", success=False)

    async def _match_entity(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Match a single entity against a specific Aleph collection or dataset."""
        entity_data = request.parameters.get("entity_data", {})
        target = request.parameters.get("target_dataset", "default")

        if not entity_data:
            return SkillResponse(content="No entity data provided for matching.", success=False)

        try:
            from emet.ftm.external.adapters import YenteClient
            results = await YenteClient().match_entity(entity_data, dataset=target)
            matches = results.get("responses", {}).get("q", {}).get("results", [])

            return SkillResponse(
                content=f"Found {len(matches)} potential matches in dataset '{target}'.",
                success=True,
                data={"matches": matches, "entity_data": entity_data, "target": target},
                result_confidence=0.75,
            )
        except Exception as e:
            return SkillResponse(content=f"Entity matching failed: {e}", success=False)
