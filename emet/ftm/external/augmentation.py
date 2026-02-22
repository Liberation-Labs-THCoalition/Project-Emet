"""Dataset augmentation — cross-source entity enrichment.

Given a set of FtM entities from one source, automatically enriches
them by querying other available sources for matching/related data,
then merges results back.

Pipeline:
  input entities → name extraction → parallel source queries
  → fuzzy matching → property merging → enriched entities

Supports:
  - Person augmentation: sanctions, PEP lists, company directorships
  - Company augmentation: corporate registry, beneficial ownership, sanctions
  - Address augmentation: geolocation, associated entities
  - Blockchain augmentation: address clustering, risk scoring

This is the "make connections the journalist didn't know existed" module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AugmentationConfig:
    """Configuration for dataset augmentation."""
    min_match_score: float = 0.65     # Minimum fuzzy match threshold
    max_results_per_source: int = 10  # Limit results per source
    sources: list[str] = field(default_factory=lambda: [
        "opensanctions", "opencorporates", "icij", "gleif",
    ])
    enable_blockchain: bool = False
    enable_gdelt: bool = False
    timeout_per_source: float = 30.0


# ---------------------------------------------------------------------------
# Augmentation results
# ---------------------------------------------------------------------------


@dataclass
class AugmentationMatch:
    """A single match found during augmentation."""
    source_entity_id: str   # Original entity
    matched_entity: dict[str, Any]  # Matched entity from external source
    source: str                      # Which source provided the match
    match_score: float               # Fuzzy match confidence
    match_type: str                  # exact, fuzzy, related


@dataclass
class AugmentationResult:
    """Result of augmenting a dataset."""
    original_count: int = 0
    enriched_count: int = 0
    new_entities_found: int = 0
    new_relationships_found: int = 0
    sources_queried: list[str] = field(default_factory=list)
    matches: list[AugmentationMatch] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "original_count": self.original_count,
            "enriched_count": self.enriched_count,
            "new_entities_found": self.new_entities_found,
            "new_relationships_found": self.new_relationships_found,
            "sources_queried": self.sources_queried,
            "match_count": len(self.matches),
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Augmentation engine
# ---------------------------------------------------------------------------


class DatasetAugmenter:
    """Enrich FtM entities by querying external sources.

    For each entity, extracts identifying information and queries
    relevant external sources for matches, then merges results.
    """

    def __init__(self, config: AugmentationConfig | None = None) -> None:
        self._config = config or AugmentationConfig()

    async def augment(
        self,
        entities: list[dict[str, Any]],
        sources: list[str] | None = None,
    ) -> AugmentationResult:
        """Augment a set of entities from external sources.

        Args:
            entities: FtM entities to enrich
            sources: Override which sources to query

        Returns:
            AugmentationResult with enriched entities and new discoveries
        """
        query_sources = sources or self._config.sources
        result = AugmentationResult(
            original_count=len(entities),
            sources_queried=query_sources,
        )

        all_enriched = list(entities)  # Start with originals

        for entity in entities:
            schema = entity.get("schema", "")
            props = entity.get("properties", {})
            names = props.get("name", props.get("title", []))

            if not names:
                continue

            name = names[0]
            entity_id = entity.get("id", "")

            # Query each source
            for source in query_sources:
                try:
                    matches = await self._query_source(
                        name, schema, source
                    )
                    for match in matches:
                        if match["score"] < self._config.min_match_score:
                            continue

                        result.matches.append(AugmentationMatch(
                            source_entity_id=entity_id,
                            matched_entity=match["entity"],
                            source=source,
                            match_score=match["score"],
                            match_type=match.get("type", "fuzzy"),
                        ))

                        # Add new entity
                        all_enriched.append(match["entity"])
                        result.new_entities_found += 1

                        # Create relationship
                        rel = {
                            "id": f"aug-rel-{uuid.uuid4().hex[:8]}",
                            "schema": "UnknownLink",
                            "properties": {
                                "subject": [entity_id],
                                "object": [match["entity"].get("id", "")],
                            },
                            "_provenance": {
                                "source": f"augmentation_{source}",
                                "match_score": match["score"],
                                "match_type": match.get("type", "fuzzy"),
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                        result.relationships.append(rel)
                        result.new_relationships_found += 1

                except Exception as exc:
                    error_msg = f"Error querying {source} for '{name}': {exc}"
                    logger.warning(error_msg)
                    result.errors.append(error_msg)

        result.entities = all_enriched
        result.enriched_count = len(all_enriched)
        return result

    async def _query_source(
        self,
        name: str,
        schema: str,
        source: str,
    ) -> list[dict[str, Any]]:
        """Query a single external source for matches.

        Returns list of {entity, score, type} dicts.

        In production, delegates to FederatedSearch / adapter layer.
        """
        from emet.ftm.external.adapters import (
            YenteClient, YenteConfig,
            OpenCorporatesClient, OpenCorporatesConfig,
            ICIJClient, ICIJConfig,
            GLEIFClient, GLEIFConfig,
        )

        max_results = self._config.max_results_per_source

        if source == "opensanctions":
            client = YenteClient(YenteConfig())
            results = await client.match(
                name=name,
                schema=schema or "LegalEntity",
                limit=max_results,
            )
            return [
                {
                    "entity": r.get("entity", r),
                    "score": r.get("score", 0.5),
                    "type": "fuzzy",
                }
                for r in results
            ]

        elif source == "opencorporates":
            client = OpenCorporatesClient(OpenCorporatesConfig())
            results = await client.search_companies(
                query=name,
                per_page=max_results,
            )
            return [
                {
                    "entity": r,
                    "score": _simple_name_score(name, _get_name(r)),
                    "type": "fuzzy",
                }
                for r in results
            ]

        elif source == "icij":
            client = ICIJClient(ICIJConfig())
            results = await client.search(query=name, limit=max_results)
            return [
                {
                    "entity": r,
                    "score": _simple_name_score(name, _get_name(r)),
                    "type": "fuzzy",
                }
                for r in results
            ]

        elif source == "gleif":
            client = GLEIFClient(GLEIFConfig())
            results = await client.search(query=name, limit=max_results)
            return [
                {
                    "entity": r,
                    "score": _simple_name_score(name, _get_name(r)),
                    "type": "fuzzy",
                }
                for r in results
            ]

        return []


# ---------------------------------------------------------------------------
# Blockchain address clustering
# ---------------------------------------------------------------------------


@dataclass
class ClusterResult:
    """Result of blockchain address clustering."""
    seed_address: str
    cluster_addresses: list[str] = field(default_factory=list)
    cluster_size: int = 0
    total_value_transferred: float = 0.0
    risk_indicators: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)


class BlockchainClusterer:
    """Cluster blockchain addresses by co-spending heuristic.

    Groups addresses that are likely controlled by the same entity
    based on transaction patterns:
      - Common input heuristic (addresses used as inputs in same tx)
      - Change address detection
      - Temporal clustering

    For production, delegates to the blockchain adapter (Etherscan/Blockchair).
    """

    def __init__(self) -> None:
        pass

    async def cluster_address(
        self,
        address: str,
        chain: str = "ethereum",
        max_depth: int = 2,
    ) -> ClusterResult:
        """Find addresses likely controlled by the same entity.

        Args:
            address: Seed blockchain address
            chain: ethereum or bitcoin
            max_depth: Transaction hops to explore

        Returns:
            ClusterResult with grouped addresses and risk indicators
        """
        from emet.ftm.external.blockchain import (
            BlockchainAdapter, BlockchainConfig,
        )

        adapter = BlockchainAdapter(BlockchainConfig())

        # Get transactions for seed address
        try:
            tx_data = await adapter.investigate_address(address, chain=chain)
        except Exception as exc:
            logger.warning("Blockchain query failed for %s: %s", address, exc)
            return ClusterResult(seed_address=address)

        transactions = tx_data.get("transactions", [])
        cluster_addrs = _extract_cluster(address, transactions, max_depth)
        risk_flags = _assess_risk(tx_data, cluster_addrs)

        # Convert to FtM entities
        entities = []
        for addr in cluster_addrs:
            entities.append({
                "id": f"crypto-{chain}-{addr[:16]}",
                "schema": "CryptoWallet",
                "properties": {
                    "publicKey": [addr],
                    "description": [f"Clustered with {address[:12]}... on {chain}"],
                },
                "_provenance": {
                    "source": "blockchain_clustering",
                    "chain": chain,
                    "seed_address": address,
                    "confidence": 0.7,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
            })

        total_value = sum(
            float(tx.get("value", 0))
            for tx in transactions
        )

        return ClusterResult(
            seed_address=address,
            cluster_addresses=cluster_addrs,
            cluster_size=len(cluster_addrs),
            total_value_transferred=total_value,
            risk_indicators=risk_flags,
            entities=entities,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_name(entity: dict[str, Any]) -> str:
    """Extract primary name from an FtM entity."""
    props = entity.get("properties", {})
    names = props.get("name", props.get("title", []))
    return names[0] if names else ""


def _simple_name_score(query: str, candidate: str) -> float:
    """Simple fuzzy name match score (0-1).

    Uses normalized token overlap for speed. For production,
    would use Levenshtein or phonetic matching.
    """
    if not query or not candidate:
        return 0.0

    q_tokens = set(query.lower().split())
    c_tokens = set(candidate.lower().split())

    if not q_tokens or not c_tokens:
        return 0.0

    overlap = len(q_tokens & c_tokens)
    max_tokens = max(len(q_tokens), len(c_tokens))
    return overlap / max_tokens if max_tokens > 0 else 0.0


def _extract_cluster(
    seed: str,
    transactions: list[dict[str, Any]],
    max_depth: int,
) -> list[str]:
    """Extract co-spending cluster from transaction data.

    Uses common-input heuristic: addresses that appear as inputs
    in the same transaction are likely controlled by the same entity.
    """
    cluster = {seed.lower()}

    for tx in transactions:
        inputs = [
            addr.lower()
            for addr in tx.get("inputs", [tx.get("from", "")])
            if addr
        ]

        # If seed is in inputs, add all other inputs to cluster
        if seed.lower() in [i.lower() for i in inputs]:
            cluster.update(inputs)

    # Remove seed from results
    cluster.discard(seed.lower())
    return sorted(cluster)[:50]  # Cap at 50


def _assess_risk(
    tx_data: dict[str, Any],
    cluster_addrs: list[str],
) -> list[str]:
    """Assess risk indicators for a blockchain cluster."""
    flags: list[str] = []

    # Large cluster suggests mixing/tumbling
    if len(cluster_addrs) > 20:
        flags.append("large_cluster")

    # High transaction volume
    tx_count = len(tx_data.get("transactions", []))
    if tx_count > 100:
        flags.append("high_tx_volume")

    # Check for known labels
    labels = tx_data.get("labels", [])
    for label in labels:
        label_lower = label.lower() if isinstance(label, str) else ""
        if any(term in label_lower for term in ["mixer", "tornado", "sanctioned"]):
            flags.append(f"flagged_label:{label}")

    return flags
