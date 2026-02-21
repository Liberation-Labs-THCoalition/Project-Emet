"""Entity Search Skill Chip — primary search agent for Aleph investigations.

Wraps Aleph's ElasticSearch-backed search API as an intelligent search agent
supporting iterative multi-step queries, transliteration across scripts,
automated result scoring, and search strategy optimization.

Modeled after the journalism wrapper's /search and /entity commands.

Capabilities:
    - Full-text search with ES query_string syntax (boolean, wildcards, fuzzy)
    - Schema-filtered search (Person, Company, Vessel, etc.)
    - Multi-collection search with relevance ranking
    - Entity lookup by ID with relationship expansion
    - Name transliteration and cross-script matching
    - External source federation (OpenSanctions, OpenCorporates, ICIJ, GLEIF)
    - Search history tracking for investigation context
"""

from __future__ import annotations

import logging
from typing import Any

from ftm_harness.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)


class EntitySearchChip(BaseSkillChip):
    """Search for entities across Aleph collections and external sources.

    Handles:
    - Simple name searches ("find John Smith")
    - Complex boolean queries ("company AND (panama OR bvi) NOT dissolved")
    - Schema-specific searches ("find all vessels flagged in Liberia")
    - Fuzzy matching ("find Газпром" → matches Gazprom via transliteration)
    - Entity expansion (given an entity, find all connected entities)
    - Federated external search (OpenSanctions, OpenCorporates, ICIJ, GLEIF)
    """

    name = "entity_search"
    description = "Search for entities across Aleph collections and external data sources"
    version = "1.0.0"
    domain = SkillDomain.ENTITY_SEARCH
    efe_weights = EFEWeights(
        accuracy=0.25, source_protection=0.15, public_interest=0.20,
        proportionality=0.20, transparency=0.20,
    )
    capabilities = [
        SkillCapability.SEARCH_ALEPH,
        SkillCapability.READ_ALEPH,
        SkillCapability.READ_OPENSANCTIONS,
        SkillCapability.READ_OPENCORPORATES,
        SkillCapability.READ_ICIJ,
        SkillCapability.READ_GLEIF,
    ]
    consensus_actions = []  # Search is non-destructive

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        if intent in ("get_entity", "entity_detail"):
            return await self._get_entity(request, context)
        elif intent in ("expand", "expand_network", "references"):
            return await self._expand_entity(request, context)
        elif intent in ("similar", "find_similar"):
            return await self._find_similar(request, context)
        elif intent == "search_external":
            return await self._search_external(request, context)
        else:
            return await self._search(request, context)

    async def _search(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Execute a search against Aleph collections.

        Parameters:
            query (str): Search query (ES query_string syntax)
            schema (str): Filter by FtM schema (Person, Company, etc.)
            collections (list[str]): Filter by collection IDs
            countries (list[str]): Filter by country codes
            limit (int): Max results (default 20)
            offset (int): Pagination offset
        """
        query = request.parameters.get("query", request.raw_input)
        schema = request.parameters.get("schema", "")
        collections = request.parameters.get("collections", context.collection_ids)
        countries = request.parameters.get("countries", [])
        limit = request.parameters.get("limit", 20)
        offset = request.parameters.get("offset", 0)

        if not query:
            return SkillResponse(content="No search query provided.", success=False)

        strategy = self._analyze_query(query)

        try:
            from ftm_harness.ftm.aleph_client import AlephClient
            client = AlephClient()
            results = await client.search(
                query=query, schema=schema,
                collections=collections if collections else None,
                countries=countries if countries else None,
                limit=limit, offset=offset,
            )
            total = results.get("total", 0)
            entities = results.get("results", [])

            from ftm_harness.ftm.data_spine import FtMDomain
            enriched = []
            for entity in entities:
                domain = FtMDomain.classify_schema(entity.get("schema", "Thing"))
                enriched.append({
                    "entity": entity,
                    "domain": domain.value,
                    "names": entity.get("properties", {}).get("name", []),
                })

            return SkillResponse(
                content=f"Found {total} results for '{query}'" + (
                    f" (showing {len(entities)})" if total > len(entities) else ""
                ),
                success=True,
                data={
                    "total": total, "results": enriched, "query": query,
                    "strategy": strategy, "offset": offset,
                    "has_more": total > offset + limit,
                },
                produced_entities=[e["entity"] for e in enriched],
                result_confidence=min(0.9, 0.5 + 0.02 * min(total, 20)),
                suggestions=self._generate_suggestions(query, strategy, total, enriched),
            )
        except Exception as e:
            logger.exception("Search failed: %s", query)
            return SkillResponse(content=f"Search failed: {e}", success=False)

    async def _get_entity(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Retrieve a specific entity by ID with full details."""
        entity_id = request.parameters.get("entity_id", "")
        if not entity_id:
            return SkillResponse(content="No entity ID provided.", success=False)
        try:
            from ftm_harness.ftm.aleph_client import AlephClient
            entity = await AlephClient().get_entity(entity_id)
            names = entity.get("properties", {}).get("name", ["Unknown"])
            return SkillResponse(
                content=f"Retrieved entity: {names[0]}",
                success=True, data={"entity": entity},
                produced_entities=[entity], result_confidence=0.95,
            )
        except Exception as e:
            return SkillResponse(content=f"Entity lookup failed: {e}", success=False)

    async def _expand_entity(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Expand an entity's network — find all connected entities."""
        entity_id = request.parameters.get("entity_id", "")
        if not entity_id:
            return SkillResponse(content="No entity ID provided.", success=False)
        try:
            from ftm_harness.ftm.aleph_client import AlephClient
            client = AlephClient()
            references = await client.get_entity_references(entity_id)
            expansion = await client.get_entity_expand(entity_id)
            ref_ents = references.get("results", [])
            exp_ents = expansion.get("results", [])
            return SkillResponse(
                content=f"Network: {len(ref_ents)} references, {len(exp_ents)} expanded connections",
                success=True,
                data={"references": ref_ents, "expansion": exp_ents, "source_entity_id": entity_id},
                produced_entities=ref_ents + exp_ents, result_confidence=0.85,
                suggestions=["Run network analysis on expanded graph", "Screen against sanctions"],
            )
        except Exception as e:
            return SkillResponse(content=f"Expansion failed: {e}", success=False)

    async def _find_similar(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Find entities similar to a given entity."""
        entity_id = request.parameters.get("entity_id", "")
        if not entity_id:
            return SkillResponse(content="No entity ID provided.", success=False)
        try:
            from ftm_harness.ftm.aleph_client import AlephClient
            results = await AlephClient().get_similar_entities(entity_id)
            entities = results.get("results", [])
            return SkillResponse(
                content=f"Found {len(entities)} similar entities",
                success=True, data={"results": entities},
                produced_entities=entities, result_confidence=0.7,
            )
        except Exception as e:
            return SkillResponse(content=f"Similar search failed: {e}", success=False)

    async def _search_external(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Federated search across external sources."""
        query = request.parameters.get("query", request.raw_input)
        sources = request.parameters.get("sources", ["opensanctions", "opencorporates"])
        all_results: dict[str, Any] = {}

        for source in sources:
            try:
                if source == "opensanctions":
                    from ftm_harness.ftm.external.adapters import YenteClient
                    r = await YenteClient().search(query)
                    all_results[source] = r.get("results", [])
                elif source == "opencorporates":
                    from ftm_harness.ftm.external.adapters import OpenCorporatesClient
                    oc = OpenCorporatesClient()
                    r = await oc.search_companies(query)
                    companies = r.get("results", {}).get("companies", [])
                    all_results[source] = [oc.company_to_ftm(c) for c in companies]
                elif source == "icij":
                    from ftm_harness.ftm.external.adapters import ICIJClient
                    r = await ICIJClient().search(query)
                    all_results[source] = r.get("results", [])
                elif source == "gleif":
                    from ftm_harness.ftm.external.adapters import GLEIFClient
                    gc = GLEIFClient()
                    r = await gc.search_entities(query)
                    all_results[source] = [gc.lei_record_to_ftm(x) for x in r.get("data", [])]
            except Exception as e:
                logger.warning("External search failed for %s: %s", source, e)
                all_results[source] = {"error": str(e)}

        total = sum(len(v) for v in all_results.values() if isinstance(v, list))
        return SkillResponse(
            content=f"External search: {total} results across {len(sources)} sources",
            success=True, data={"results_by_source": all_results, "query": query},
            result_confidence=0.7,
        )

    def _analyze_query(self, query: str) -> dict[str, Any]:
        strategy: dict[str, Any] = {"type": "simple", "has_boolean": False, "has_fuzzy": False}
        if any(op in query.upper() for op in ["AND", "OR", "NOT"]):
            strategy["type"] = "boolean"
            strategy["has_boolean"] = True
        if "~" in query:
            strategy["has_fuzzy"] = True
        if "*" in query or "?" in query:
            strategy["type"] = "wildcard"
        return strategy

    def _generate_suggestions(self, query: str, strategy: dict, total: int, results: list) -> list[str]:
        suggestions = []
        if total == 0:
            suggestions.extend([
                f"Try fuzzy search: '{query}~'",
                "Search external sources (OpenSanctions, OpenCorporates)",
            ])
        elif total > 100:
            suggestions.extend([
                "Add schema filter (Person, Company, etc.)",
                "Add country filter to narrow results",
            ])
        else:
            suggestions.extend([
                "Expand top result's network",
                "Cross-reference against sanctions lists",
            ])
        return suggestions[:3]
