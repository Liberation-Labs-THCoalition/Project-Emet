"""Federated search across external investigative data sources.

Fans out a query to all configured data sources in parallel, converts
results to FtM entities, deduplicates by name similarity, and returns
a unified result set with provenance tracking.

This is the core data acquisition layer for Emet investigations.  It
federates across free data sources to approximate what tools like
Maltego (120+ integrations) and Orbis (600M entities) provide with
proprietary data at $100K+/year.

Combined free sources: OpenSanctions (~325 datasets) + OpenCorporates
(200M+ companies) + ICIJ Offshore Leaks (810K+ entities) + GLEIF
(2.7M+ LEI records) ≈ substantial coverage at zero cost.

Usage::

    from emet.ftm.external.federation import FederatedSearch

    federation = FederatedSearch()
    results = await federation.search_entity("Gazprom", entity_type="Company")

    for entity in results:
        print(entity["schema"], entity["properties"]["name"])
        print("  Source:", entity["_provenance"]["source"])
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from emet.ftm.external.adapters import (
    GLEIFClient,
    GLEIFConfig,
    ICIJClient,
    ICIJConfig,
    OpenCorporatesClient,
    OpenCorporatesConfig,
    YenteClient,
    YenteConfig,
)
from emet.ftm.external.companies_house import (
    CompaniesHouseClient,
    CompaniesHouseConfig,
)
from emet.ftm.external.edgar import (
    EDGARClient,
    EDGARConfig,
)
from emet.ftm.external.converters import (
    gleif_search_to_ftm_list,
    icij_search_to_ftm_list,
    oc_search_to_ftm_list,
    oc_officer_search_to_ftm_list,
    yente_search_to_ftm_list,
)
from emet.ftm.external.rate_limit import (
    MonthlyCounter,
    ResponseCache,
    TokenBucketLimiter,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FederationConfig:
    """Configuration for the federated search layer."""

    # Source enable/disable
    enable_opensanctions: bool = True
    enable_opencorporates: bool = True
    enable_icij: bool = True
    enable_gleif: bool = True
    enable_companies_house: bool = True
    enable_edgar: bool = True

    # Client configs
    yente_config: YenteConfig = field(default_factory=YenteConfig)
    opencorporates_config: OpenCorporatesConfig = field(default_factory=OpenCorporatesConfig)
    icij_config: ICIJConfig = field(default_factory=ICIJConfig)
    gleif_config: GLEIFConfig = field(default_factory=GLEIFConfig)
    companies_house_config: CompaniesHouseConfig = field(default_factory=CompaniesHouseConfig)
    edgar_config: EDGARConfig = field(default_factory=EDGARConfig)

    # Rate limits
    opencorporates_monthly_limit: int = 200

    # Cache
    cache_ttl_seconds: float = 300.0  # 5 minutes
    cache_max_entries: int = 1000

    # Search
    default_limit_per_source: int = 10
    search_timeout_seconds: float = 30.0

    # Deduplication
    dedup_similarity_threshold: float = 0.85  # 0–1, name similarity for dedup


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FederatedResult:
    """Result of a federated search."""

    query: str
    entity_type: str
    entities: list[dict[str, Any]]
    source_stats: dict[str, int]  # source → result count
    errors: dict[str, str]  # source → error message
    cache_hits: int
    total_time_ms: float


# ---------------------------------------------------------------------------
# Name similarity (simple, no external deps)
# ---------------------------------------------------------------------------


_CORPORATE_SUFFIXES = {
    # English
    "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "co", "company", "plc", "llc", "llp", "lp",
    # European
    "ag", "sa", "gmbh", "nv", "bv", "se", "srl", "sarl", "oy",
    "ab", "as", "aps",
    # Other
    "pty", "pte",
    # Symbols (after lowering)
    "&",
}


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison.

    Lowercases, strips whitespace, and removes common corporate
    suffixes so that "Deutsche Bank AG" and "Deutsche Bank" compare
    as identical.
    """
    tokens = name.lower().strip().split()
    # Strip trailing corporate suffixes (may be multiple, e.g. "Pty Ltd")
    while tokens and tokens[-1].rstrip(".") in _CORPORATE_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _name_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity between two names.

    Returns 0–1.  Not as sophisticated as Levenshtein but fast and
    dependency-free.  Good enough for deduplication across sources.
    """
    a_norm = _normalize_name(a)
    b_norm = _normalize_name(b)

    if a_norm == b_norm:
        return 1.0
    if not a_norm or not b_norm:
        return 0.0

    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())

    if not a_tokens or not b_tokens:
        return 0.0

    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens

    # Jaccard similarity
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# FederatedSearch
# ---------------------------------------------------------------------------


class FederatedSearch:
    """Parallel search across all configured external data sources.

    Handles:
        - Parallel async fan-out to all sources
        - Per-source rate limiting and monthly budgeting
        - Response caching to avoid redundant calls
        - FtM entity conversion
        - Deduplication by name similarity
        - Graceful degradation (partial results if a source fails)
        - Provenance tracking on every entity
    """

    def __init__(self, config: FederationConfig | None = None) -> None:
        self._config = config or FederationConfig()

        # Initialize clients
        self._clients: dict[str, Any] = {}
        if self._config.enable_opensanctions:
            self._clients["opensanctions"] = YenteClient(self._config.yente_config)
        if self._config.enable_opencorporates:
            self._clients["opencorporates"] = OpenCorporatesClient(self._config.opencorporates_config)
        if self._config.enable_icij:
            self._clients["icij"] = ICIJClient(self._config.icij_config)
        if self._config.enable_gleif:
            self._clients["gleif"] = GLEIFClient(self._config.gleif_config)
        if self._config.enable_companies_house:
            self._clients["companies_house"] = CompaniesHouseClient(self._config.companies_house_config)
        if self._config.enable_edgar:
            self._clients["edgar"] = EDGARClient(self._config.edgar_config)

        # Rate limiters
        self._oc_counter = MonthlyCounter(
            monthly_limit=self._config.opencorporates_monthly_limit,
            source_name="OpenCorporates",
        )

        # Cache
        self._cache = ResponseCache(
            default_ttl=self._config.cache_ttl_seconds,
            max_entries=self._config.cache_max_entries,
        )

    # -- Individual source searches -----------------------------------------

    async def _search_opensanctions(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search OpenSanctions via yente API."""
        client = self._clients.get("opensanctions")
        if not client:
            return []

        cache_key = self._cache.make_key("opensanctions", "search", {"q": query, "limit": limit})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Map entity_type to yente schema filter
        schema = ""
        if entity_type.lower() in ("person", "people"):
            schema = "Person"
        elif entity_type.lower() in ("company", "organization", "org"):
            schema = "Company"

        response = await client.search(query, schema=schema, limit=limit)
        entities = yente_search_to_ftm_list(response)

        self._cache.set(cache_key, entities)
        return entities

    async def _search_opencorporates(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search OpenCorporates (company search)."""
        client = self._clients.get("opencorporates")
        if not client:
            return []

        if not self._oc_counter.can_request():
            logger.warning(
                "OpenCorporates monthly limit reached (%d/%d). Skipping.",
                self._oc_counter._count, self._oc_counter.monthly_limit,
            )
            return []

        cache_key = self._cache.make_key("opencorporates", "search", {"q": query, "limit": limit})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        self._oc_counter.record()

        entities: list[dict[str, Any]] = []

        # Company search (always, unless specifically looking for persons)
        if entity_type.lower() not in ("person", "people"):
            response = await client.search_companies(query, limit=limit)
            entities.extend(oc_search_to_ftm_list(response))

        # Officer search (if looking for persons or doing broad search)
        if entity_type.lower() in ("person", "people", "", "any"):
            self._oc_counter.record()  # counts as second request
            response = await client.search_officers(query, limit=limit)
            entities.extend(oc_officer_search_to_ftm_list(response))

        self._cache.set(cache_key, entities)
        return entities

    async def _search_icij(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search ICIJ Offshore Leaks database."""
        client = self._clients.get("icij")
        if not client:
            return []

        cache_key = self._cache.make_key("icij", "search", {"q": query, "limit": limit})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Map entity type to ICIJ type filter
        icij_type = ""
        if entity_type.lower() in ("person", "people"):
            icij_type = "officer"
        elif entity_type.lower() in ("company", "organization", "org"):
            icij_type = "entity"

        response = await client.search(query, entity_type=icij_type, limit=limit)
        entities = icij_search_to_ftm_list(response)

        self._cache.set(cache_key, entities)
        return entities

    async def _search_gleif(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search GLEIF LEI database."""
        client = self._clients.get("gleif")
        if not client:
            return []

        # GLEIF only has legal entities, skip for person searches
        if entity_type.lower() in ("person", "people"):
            return []

        cache_key = self._cache.make_key("gleif", "search", {"q": query, "limit": limit})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = await client.search_entities(query, limit=limit)
        entities = gleif_search_to_ftm_list(response)

        self._cache.set(cache_key, entities)
        return entities

    async def _search_companies_house(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search UK Companies House."""
        client = self._clients.get("companies_house")
        if not client:
            return []

        cache_key = self._cache.make_key(
            "companies_house", "search", {"q": query, "limit": limit, "type": entity_type}
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Companies House has both company and officer search
        result = await client.search_companies_ftm(query, limit=limit)
        entities = result.get("entities", [])

        self._cache.set(cache_key, entities)
        return entities

    async def _search_edgar(
        self, query: str, limit: int, entity_type: str,
    ) -> list[dict[str, Any]]:
        """Search SEC EDGAR for US-registered entities."""
        client = self._clients.get("edgar")
        if not client:
            return []

        # EDGAR only has companies/filers, skip for person-only searches
        if entity_type.lower() in ("person", "people"):
            return []

        cache_key = self._cache.make_key(
            "edgar", "search", {"q": query, "limit": limit}
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = await client.search_companies_ftm(query, limit=limit)
        entities = result.get("entities", [])

        self._cache.set(cache_key, entities)
        return entities

    # -- Federated search ---------------------------------------------------

    async def search_entity(
        self,
        query: str,
        entity_type: str = "",
        limit_per_source: int | None = None,
        sources: list[str] | None = None,
    ) -> FederatedResult:
        """Search across all configured sources for an entity.

        Parameters
        ----------
        query:
            Entity name or search query.
        entity_type:
            Filter by type: ``"person"``, ``"company"``, or ``""`` (any).
        limit_per_source:
            Max results per source. Defaults to config value.
        sources:
            Specific sources to query. None = all enabled.

        Returns
        -------
        FederatedResult with deduplicated entities and metadata.
        """
        import time
        start = time.monotonic()

        limit = limit_per_source or self._config.default_limit_per_source
        entity_type = entity_type or ""

        # Build search tasks
        tasks: dict[str, asyncio.Task] = {}

        source_methods = {
            "opensanctions": self._search_opensanctions,
            "opencorporates": self._search_opencorporates,
            "icij": self._search_icij,
            "gleif": self._search_gleif,
            "companies_house": self._search_companies_house,
            "edgar": self._search_edgar,
        }

        for source_name, method in source_methods.items():
            if sources and source_name not in sources:
                continue
            if source_name not in self._clients:
                continue
            tasks[source_name] = asyncio.create_task(
                self._safe_search(source_name, method, query, limit, entity_type)
            )

        # Wait for all with timeout
        if tasks:
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=self._config.search_timeout_seconds,
            )
            # Cancel timed-out tasks
            for task in pending:
                task.cancel()

        # Collect results
        all_entities: list[dict[str, Any]] = []
        source_stats: dict[str, int] = {}
        errors: dict[str, str] = {}

        for source_name, task in tasks.items():
            try:
                if task.done() and not task.cancelled():
                    result = task.result()
                    if isinstance(result, list):
                        all_entities.extend(result)
                        source_stats[source_name] = len(result)
                    elif isinstance(result, dict) and "error" in result:
                        errors[source_name] = result["error"]
                        source_stats[source_name] = 0
                else:
                    errors[source_name] = "timeout"
                    source_stats[source_name] = 0
            except Exception as e:
                errors[source_name] = str(e)
                source_stats[source_name] = 0

        # Deduplicate
        deduped = self._deduplicate(all_entities)

        elapsed_ms = (time.monotonic() - start) * 1000

        result = FederatedResult(
            query=query,
            entity_type=entity_type,
            entities=deduped,
            source_stats=source_stats,
            errors=errors,
            cache_hits=self._cache.stats["hits"],
            total_time_ms=round(elapsed_ms, 1),
        )

        logger.info(
            "Federated search '%s': %d entities from %d sources in %.0fms (errors: %s)",
            query, len(deduped), len(source_stats), elapsed_ms,
            list(errors.keys()) if errors else "none",
        )

        return result

    async def _safe_search(
        self,
        source: str,
        method: Any,
        query: str,
        limit: int,
        entity_type: str,
    ) -> list[dict[str, Any]] | dict[str, str]:
        """Wrap a source search with error handling."""
        try:
            return await method(query, limit, entity_type)
        except Exception as e:
            logger.warning("Source %s failed for query '%s': %s", source, query, e)
            return {"error": str(e)}

    # -- Deduplication ------------------------------------------------------

    def _deduplicate(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove near-duplicate entities by name similarity.

        When duplicates are found, the entity with higher provenance
        confidence is kept, and the duplicate's source is noted.
        """
        if not entities:
            return []

        threshold = self._config.dedup_similarity_threshold
        result: list[dict[str, Any]] = []
        seen_names: list[tuple[str, int]] = []  # (normalized_name, index_in_result)

        for entity in entities:
            names = entity.get("properties", {}).get("name", [])
            entity_name = names[0] if names else ""
            if not entity_name:
                result.append(entity)
                continue

            normalized = _normalize_name(entity_name)

            # Check against already-seen names
            is_duplicate = False
            for seen_name, seen_idx in seen_names:
                sim = _name_similarity(entity_name, seen_name)
                if sim >= threshold:
                    # Merge provenance info
                    existing = result[seen_idx]
                    existing_confidence = existing.get("_provenance", {}).get("confidence", 0)
                    new_confidence = entity.get("_provenance", {}).get("confidence", 0)

                    # Track that this entity was found in multiple sources
                    if "_also_found_in" not in existing:
                        existing["_also_found_in"] = []
                    existing["_also_found_in"].append({
                        "source": entity.get("_provenance", {}).get("source", "unknown"),
                        "source_id": entity.get("_provenance", {}).get("source_id", ""),
                        "confidence": new_confidence,
                    })

                    # If new entity has higher confidence, swap properties
                    if new_confidence > existing_confidence:
                        existing["properties"] = entity["properties"]
                        existing["_provenance"] = entity["_provenance"]

                    is_duplicate = True
                    break

            if not is_duplicate:
                seen_names.append((normalized, len(result)))
                result.append(entity)

        dedup_count = len(entities) - len(result)
        if dedup_count > 0:
            logger.debug("Deduplication removed %d/%d entities", dedup_count, len(entities))

        return result

    # -- Screening (batch entity matching) ----------------------------------

    async def screen_entity(
        self,
        entity_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Screen an entity against OpenSanctions for sanctions/PEP matches.

        Parameters
        ----------
        entity_data:
            FtM entity dict with at minimum ``schema`` and
            ``properties.name``.

        Returns
        -------
        List of matching FtM entities from OpenSanctions, sorted by
        match score.
        """
        client = self._clients.get("opensanctions")
        if not client:
            return []

        try:
            response = await client.match_entity(entity_data)
            from emet.ftm.external.converters import yente_match_to_ftm_list
            return yente_match_to_ftm_list(response)
        except Exception as e:
            logger.warning("Sanctions screening failed: %s", e)
            return []

    # -- Enrichment (single entity deep lookup) -----------------------------

    async def enrich_entity(
        self,
        name: str,
        entity_type: str = "Company",
        lei: str = "",
    ) -> dict[str, Any]:
        """Deep enrichment of a single entity across all sources.

        Goes beyond basic search: retrieves corporate ownership (GLEIF),
        offshore connections (ICIJ), sanctions status (OpenSanctions),
        and registration details (OpenCorporates).

        Returns
        -------
        Dict with: ``entity`` (best FtM entity), ``sanctions_matches``,
        ``offshore_connections``, ``ownership_chain``, ``sources_checked``.
        """
        result: dict[str, Any] = {
            "entity": None,
            "sanctions_matches": [],
            "offshore_connections": [],
            "ownership_chain": [],
            "sources_checked": [],
        }

        # 1. Federated search
        search_result = await self.search_entity(name, entity_type=entity_type)
        if search_result.entities:
            result["entity"] = search_result.entities[0]
        result["sources_checked"].extend(search_result.source_stats.keys())

        # 2. Sanctions screening
        if result["entity"]:
            matches = await self.screen_entity(result["entity"])
            result["sanctions_matches"] = matches

        # 3. GLEIF ownership chain (if LEI provided or found)
        if lei or (result["entity"] and result["entity"].get("properties", {}).get("leiCode")):
            target_lei = lei or result["entity"]["properties"]["leiCode"][0]
            gleif = self._clients.get("gleif")
            if gleif:
                try:
                    parent_resp = await gleif.get_direct_parent(target_lei)
                    from emet.ftm.external.converters import gleif_relationship_to_ftm
                    ownership = gleif_relationship_to_ftm(target_lei, parent_resp)
                    if ownership:
                        result["ownership_chain"].append(ownership)

                    ultimate_resp = await gleif.get_ultimate_parent(target_lei)
                    ultimate = gleif_relationship_to_ftm(target_lei, ultimate_resp, "ultimate")
                    if ultimate:
                        result["ownership_chain"].append(ultimate)
                except Exception as e:
                    logger.debug("GLEIF ownership lookup failed: %s", e)

        return result

    # -- Status and diagnostics ---

    @property
    def source_status(self) -> dict[str, Any]:
        """Current status of all sources."""
        return {
            "enabled_sources": list(self._clients.keys()),
            "opencorporates_usage": self._oc_counter.usage,
            "cache": self._cache.stats,
        }
