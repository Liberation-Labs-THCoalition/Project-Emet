"""Entity resolution adapter using Splink for probabilistic record linkage.

Investigative journalism generates duplicates across sources — the same
person appears in OpenSanctions, ICIJ, OpenCorporates, and Aleph with
slightly different names, dates, or identifiers.  Entity resolution
merges these into canonical entities.

Uses Splink (Ministry of Justice UK, MIT license) for:
  - Fellegi-Sunter probabilistic matching
  - Expectation-Maximization parameter estimation
  - Configurable comparison levels (exact, levenshtein, jaro-winkler)
  - Scalable to millions of records via DuckDB backend

Pipeline:
  FtM entities → normalized records → Splink comparison → clusters
  → merged FtM entities with cross-references

Reference:
  Splink: https://github.com/moj-analytical-services/splink (MIT)
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class EntityResolutionConfig:
    """Configuration for entity resolution."""
    match_threshold: float = 0.85       # Probability threshold for match
    blocking_rules: list[str] = field(default_factory=lambda: [
        "l.first_name_metaphone = r.first_name_metaphone",
        "l.name_first_3 = r.name_first_3",
    ])
    comparison_columns: list[str] = field(default_factory=lambda: [
        "name", "birth_date", "country", "id_number",
    ])
    max_pairs: int = 1_000_000          # Max comparison pairs
    backend: str = "duckdb"             # duckdb or spark
    retain_intermediate: bool = False   # Keep intermediate match details


# ---------------------------------------------------------------------------
# Record normalization
# ---------------------------------------------------------------------------


@dataclass
class ResolvedEntity:
    """A resolved (merged) entity with provenance from all source records."""
    canonical_id: str
    schema: str
    properties: dict[str, list[str]]
    source_ids: list[str]               # Original entity IDs that merged
    source_names: list[str]             # Source labels (e.g., "opensanctions", "icij")
    match_probability: float = 0.0
    cluster_size: int = 1

    def to_ftm(self) -> dict[str, Any]:
        """Convert to FtM entity format."""
        return {
            "id": self.canonical_id,
            "schema": self.schema,
            "properties": self.properties,
            "_provenance": {
                "source": "entity_resolution",
                "source_ids": self.source_ids,
                "source_names": self.source_names,
                "match_probability": self.match_probability,
                "cluster_size": self.cluster_size,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            },
        }


def normalize_name(name: str) -> str:
    """Normalize a name for comparison.

    Strips honorifics, normalizes whitespace, lowercases.
    """
    if not name:
        return ""
    # Remove common honorifics/titles
    honorifics = r'\b(mr|mrs|ms|dr|prof|sir|lord|dame|hon|rev)\b\.?'
    result = re.sub(honorifics, '', name.lower(), flags=re.IGNORECASE)
    # Normalize whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    # Remove punctuation except hyphens
    result = re.sub(r"[^\w\s-]", "", result)
    return result


def normalize_date(date_str: str) -> str:
    """Normalize date string to YYYY-MM-DD."""
    if not date_str:
        return ""
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()


def ftm_to_record(entity: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an FtM entity to a flat record for Splink comparison.

    Returns None for entities that can't be meaningfully resolved
    (e.g., Notes, Documents without names).
    """
    schema = entity.get("schema", "")
    props = entity.get("properties", {})
    entity_id = entity.get("id", "")

    # Only resolve named entities
    names = props.get("name", [])
    if not names:
        return None

    name = names[0] if names else ""
    normalized = normalize_name(name)

    record: dict[str, Any] = {
        "unique_id": entity_id,
        "name": normalized,
        "name_original": name,
        "schema": schema,
        "name_first_3": normalized[:3] if len(normalized) >= 3 else normalized,
    }

    # Schema-specific fields
    if schema in ("Person",):
        parts = normalized.split()
        record["first_name"] = parts[0] if parts else ""
        record["last_name"] = parts[-1] if len(parts) > 1 else ""
        record["first_name_metaphone"] = _metaphone(record["first_name"])

        birth_dates = props.get("birthDate", [])
        record["birth_date"] = normalize_date(birth_dates[0]) if birth_dates else ""

        nationalities = props.get("nationality", [])
        record["country"] = nationalities[0].lower() if nationalities else ""

    elif schema in ("Company", "Organization", "LegalEntity"):
        countries = props.get("country", props.get("jurisdiction", []))
        record["country"] = countries[0].lower() if countries else ""

        reg_numbers = props.get("registrationNumber", props.get("idNumber", []))
        record["id_number"] = reg_numbers[0] if reg_numbers else ""

    # Source provenance
    prov = entity.get("_provenance", {})
    record["source"] = prov.get("source", "unknown")

    return record


def _metaphone(name: str) -> str:
    """Simple metaphone-like phonetic encoding for blocking.

    Not a full metaphone implementation — just consonant skeleton
    for fast blocking. Production would use jellyfish.metaphone().
    """
    if not name:
        return ""
    # Keep first letter, remove vowels, deduplicate consonants
    result = name[0].upper()
    prev = result
    for c in name[1:].upper():
        if c in "AEIOU":
            continue
        if c != prev:
            result += c
            prev = c
    return result[:6]


# ---------------------------------------------------------------------------
# Splink wrapper
# ---------------------------------------------------------------------------


class EntityResolver:
    """Entity resolution engine wrapping Splink.

    Resolves duplicate entities across sources using probabilistic
    record linkage with configurable comparison levels.
    """

    def __init__(self, config: EntityResolutionConfig | None = None) -> None:
        self._config = config or EntityResolutionConfig()

    def resolve(self, entities: list[dict[str, Any]]) -> list[ResolvedEntity]:
        """Resolve a list of FtM entities into deduplicated clusters.

        1. Convert FtM → flat records
        2. Run Splink deduplication
        3. Cluster matched pairs
        4. Merge clusters into ResolvedEntities

        Args:
            entities: List of FtM entity dicts

        Returns:
            List of ResolvedEntity (one per cluster)
        """
        # Convert to records
        records = []
        entity_map: dict[str, dict[str, Any]] = {}
        for entity in entities:
            record = ftm_to_record(entity)
            if record is not None:
                records.append(record)
                entity_map[record["unique_id"]] = entity

        if len(records) < 2:
            # Nothing to resolve
            return [
                self._single_entity(entity_map[r["unique_id"]], r)
                for r in records
            ]

        logger.info("Resolving %d records (threshold: %.2f)", len(records), self._config.match_threshold)

        # Try Splink, fall back to simple matching
        try:
            clusters = self._resolve_with_splink(records)
        except ImportError:
            logger.warning("Splink not installed, using fallback matcher")
            clusters = self._resolve_fallback(records)

        # Convert clusters to ResolvedEntities
        resolved = []
        for cluster_id, member_ids in clusters.items():
            member_entities = [entity_map[mid] for mid in member_ids if mid in entity_map]
            if not member_entities:
                continue
            resolved.append(self._merge_cluster(cluster_id, member_entities))

        logger.info("Resolved %d records → %d entities", len(records), len(resolved))
        return resolved

    def _resolve_with_splink(self, records: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Run Splink deduplication."""
        import splink
        from splink import DuckDBAPI, Linker, SettingsCreator, block_on
        import splink.comparison_library as cl

        db_api = DuckDBAPI()

        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=[
                cl.JaroWinklerAtThresholds("name", [0.92, 0.88, 0.7]),
                cl.ExactMatch("birth_date").configure(term_frequency_adjustments=True),
                cl.ExactMatch("country"),
                cl.ExactMatch("id_number").configure(term_frequency_adjustments=True),
            ],
            blocking_rules_to_generate_predictions=[
                block_on("name_first_3"),
                block_on("first_name_metaphone"),
            ],
        )

        linker = Linker(records, settings, db_api=db_api)
        linker.training.estimate_u_using_random_sampling(max_pairs=self._config.max_pairs)

        # Predict matches
        predictions = linker.inference.predict(threshold_match_probability=self._config.match_threshold)

        # Cluster
        clusters_df = linker.clustering.cluster_pairwise_predictions_at_threshold(
            predictions, threshold_match_probability=self._config.match_threshold
        )

        # Group by cluster_id
        clusters: dict[str, list[str]] = {}
        for row in clusters_df.as_pandas_dataframe().to_dict("records"):
            cid = str(row.get("cluster_id", ""))
            uid = str(row.get("unique_id", ""))
            clusters.setdefault(cid, []).append(uid)

        return clusters

    def _resolve_fallback(self, records: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Simple fallback resolution without Splink.

        Uses exact normalized name matching.  Birth date is used to
        *split* same-name groups (different DOB = different person),
        but missing DOB doesn't prevent matching.
        """
        from collections import defaultdict

        # Group by normalized name first
        name_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            name_groups[record["name"]].append(record)

        clusters: dict[str, list[str]] = {}
        cluster_idx = 0

        for name, group in name_groups.items():
            # Sub-group by birth_date if present on multiple records
            sub_groups: dict[str, list[str]] = defaultdict(list)
            for r in group:
                bd = r.get("birth_date", "")
                # Empty birth dates go into a "wildcard" bucket
                key = bd if bd else "_any_"
                sub_groups[key].append(r["unique_id"])

            # Merge "_any_" bucket with all others (missing DOB matches anything)
            any_ids = sub_groups.pop("_any_", [])

            if not sub_groups:
                # All records lack DOB — single cluster
                clusters[f"cluster-{cluster_idx}"] = any_ids
                cluster_idx += 1
            else:
                # Distribute any_ids into first sub-group (or create clusters per DOB)
                for bd_key, ids in sub_groups.items():
                    clusters[f"cluster-{cluster_idx}"] = ids + any_ids
                    any_ids = []  # Only add to first sub-group
                    cluster_idx += 1

        return clusters

    def _merge_cluster(
        self,
        cluster_id: str,
        entities: list[dict[str, Any]],
    ) -> ResolvedEntity:
        """Merge a cluster of entities into one ResolvedEntity.

        Strategy: union all property values, prefer most complete record.
        """
        if len(entities) == 1:
            return self._single_entity(entities[0], None)

        # Determine schema (most specific wins)
        schemas = [e.get("schema", "LegalEntity") for e in entities]
        schema = _most_specific_schema(schemas)

        # Merge properties (union all values, deduplicate)
        merged_props: dict[str, list[str]] = {}
        for entity in entities:
            for key, values in entity.get("properties", {}).items():
                existing = merged_props.setdefault(key, [])
                for v in values:
                    if v and v not in existing:
                        existing.append(v)

        source_ids = [e.get("id", "") for e in entities]
        source_names = list({
            e.get("_provenance", {}).get("source", "unknown")
            for e in entities
        })

        canonical_id = f"resolved-{hashlib.sha256(cluster_id.encode()).hexdigest()[:12]}"

        return ResolvedEntity(
            canonical_id=canonical_id,
            schema=schema,
            properties=merged_props,
            source_ids=source_ids,
            source_names=source_names,
            match_probability=self._config.match_threshold,
            cluster_size=len(entities),
        )

    def _single_entity(
        self,
        entity: dict[str, Any],
        record: dict[str, Any] | None,
    ) -> ResolvedEntity:
        """Wrap a single (unmatched) entity as a ResolvedEntity."""
        prov = entity.get("_provenance", {})
        return ResolvedEntity(
            canonical_id=entity.get("id", f"single-{uuid.uuid4().hex[:8]}"),
            schema=entity.get("schema", "LegalEntity"),
            properties=entity.get("properties", {}),
            source_ids=[entity.get("id", "")],
            source_names=[prov.get("source", "unknown")],
            match_probability=1.0,
            cluster_size=1,
        )


def _most_specific_schema(schemas: list[str]) -> str:
    """Pick the most specific FtM schema from a list.

    Person > Organization > Company > LegalEntity
    """
    priority = ["Person", "Company", "Organization", "LegalEntity"]
    for schema in priority:
        if schema in schemas:
            return schema
    return schemas[0] if schemas else "LegalEntity"


# ---------------------------------------------------------------------------
# Batch resolution helper
# ---------------------------------------------------------------------------


def resolve_entities(
    entities: list[dict[str, Any]],
    threshold: float = 0.85,
) -> dict[str, Any]:
    """Convenience function for entity resolution.

    Args:
        entities: List of FtM entity dicts
        threshold: Match probability threshold

    Returns:
        Dict with resolved entities, stats, and cross-reference map
    """
    config = EntityResolutionConfig(match_threshold=threshold)
    resolver = EntityResolver(config)
    resolved = resolver.resolve(entities)

    # Build cross-reference map
    xref_map: dict[str, str] = {}
    for re in resolved:
        for source_id in re.source_ids:
            xref_map[source_id] = re.canonical_id

    return {
        "resolved_count": len(resolved),
        "input_count": len(entities),
        "reduction_pct": round(
            (1 - len(resolved) / max(len(entities), 1)) * 100, 1
        ),
        "entities": [r.to_ftm() for r in resolved],
        "cross_references": xref_map,
        "multi_source_count": sum(1 for r in resolved if r.cluster_size > 1),
    }
