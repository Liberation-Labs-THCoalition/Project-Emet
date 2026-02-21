"""FollowTheMoney Data Spine — core integration layer.

This module wraps the ``followthemoney`` library and provides the
canonical data types that flow between all skill chips in the harness.
Every agent reads and writes FtM entities; this module ensures consistent
entity creation, validation, serialization, and schema compliance.

The FtM data model uses entities for BOTH nodes (Person, Company, Vessel)
AND relationships (Ownership, Directorship, Payment). Relationships are
full entities with their own properties — not simple graph edges. This
is a critical design decision that all skill chips must respect.

Dependencies:
    followthemoney >= 4.4
    rigour >= 0.6
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema domain classification
# ---------------------------------------------------------------------------


class FtMDomain(str, Enum):
    """High-level classification of FtM schema types.

    Used by the orchestrator to determine which skill chips should
    handle entities of different types.
    """

    # Node entities
    PERSON = "person"
    LEGAL_ENTITY = "legal_entity"   # Company, Organization, PublicBody
    ASSET = "asset"                 # Vehicle, Vessel, Airplane, RealEstate
    DOCUMENT = "document"           # Document, Pages, Page, Email, etc.
    FINANCIAL = "financial"         # BankAccount, Security, CryptoWallet
    LOCATION = "location"           # Address

    # Relationship entities (interstitial)
    OWNERSHIP = "ownership"         # Ownership, control chains
    DIRECTORSHIP = "directorship"   # Director/officer relationships
    MEMBERSHIP = "membership"       # Membership in organizations
    EMPLOYMENT = "employment"       # Employment relationships
    FAMILY = "family"               # Family connections
    FINANCIAL_LINK = "financial_link"  # Payment, Debt
    SANCTION = "sanction"           # Sanctions listings
    REPRESENTATION = "representation"  # Legal representation
    OTHER_LINK = "other_link"       # Associate, Succession, Occupancy

    @classmethod
    def classify_schema(cls, schema_name: str) -> "FtMDomain":
        """Map an FtM schema name to its domain classification."""
        mapping = {
            "Person": cls.PERSON,
            "Company": cls.LEGAL_ENTITY,
            "Organization": cls.LEGAL_ENTITY,
            "PublicBody": cls.LEGAL_ENTITY,
            "LegalEntity": cls.LEGAL_ENTITY,
            "Vehicle": cls.ASSET,
            "Vessel": cls.ASSET,
            "Airplane": cls.ASSET,
            "RealEstate": cls.ASSET,
            "Document": cls.DOCUMENT,
            "Pages": cls.DOCUMENT,
            "Page": cls.DOCUMENT,
            "Email": cls.DOCUMENT,
            "HyperText": cls.DOCUMENT,
            "PlainText": cls.DOCUMENT,
            "Table": cls.DOCUMENT,
            "Workbook": cls.DOCUMENT,
            "Image": cls.DOCUMENT,
            "Audio": cls.DOCUMENT,
            "Video": cls.DOCUMENT,
            "Package": cls.DOCUMENT,
            "Folder": cls.DOCUMENT,
            "BankAccount": cls.FINANCIAL,
            "Security": cls.FINANCIAL,
            "CryptoWallet": cls.FINANCIAL,
            "Address": cls.LOCATION,
            "Ownership": cls.OWNERSHIP,
            "Directorship": cls.DIRECTORSHIP,
            "Membership": cls.MEMBERSHIP,
            "Employment": cls.EMPLOYMENT,
            "Family": cls.FAMILY,
            "Payment": cls.FINANCIAL_LINK,
            "Debt": cls.FINANCIAL_LINK,
            "Sanction": cls.SANCTION,
            "Representation": cls.REPRESENTATION,
            "Associate": cls.OTHER_LINK,
            "Succession": cls.OTHER_LINK,
            "Occupancy": cls.OTHER_LINK,
            "UnknownLink": cls.OTHER_LINK,
        }
        return mapping.get(schema_name, cls.OTHER_LINK)


# ---------------------------------------------------------------------------
# Entity containers (harness-level wrappers around FtM entities)
# ---------------------------------------------------------------------------


@dataclass
class InvestigationEntity:
    """Harness-level wrapper around a FollowTheMoney entity.

    This is the canonical data type that flows between skill chips.
    It wraps the FtM entity dict with investigation-specific metadata
    (confidence, provenance, investigation context).

    Attributes:
        ftm_data: The raw FtM entity dict (id, schema, properties).
        confidence: Agent-assessed confidence in this entity (0.0-1.0).
        provenance: How this entity was discovered/created.
        source_chip: Which skill chip created or last modified this entity.
        investigation_id: The investigation this entity belongs to.
        collection_id: The Aleph collection ID, if applicable.
        created_at: When this wrapper was created (UTC).
        tags: Free-form tags for investigation workflow.
        verified: Whether a human has verified this entity.
        notes: Analyst notes attached during human review.
    """

    ftm_data: dict[str, Any]
    confidence: float = 0.5
    provenance: str = "unknown"
    source_chip: str = "unknown"
    investigation_id: str = ""
    collection_id: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tags: list[str] = field(default_factory=list)
    verified: bool = False
    notes: str = ""

    @property
    def entity_id(self) -> str:
        return self.ftm_data.get("id", "")

    @property
    def schema_name(self) -> str:
        return self.ftm_data.get("schema", "Thing")

    @property
    def domain(self) -> FtMDomain:
        return FtMDomain.classify_schema(self.schema_name)

    @property
    def properties(self) -> dict[str, list[str]]:
        return self.ftm_data.get("properties", {})

    @property
    def names(self) -> list[str]:
        """Return all name variants for this entity."""
        return self.properties.get("name", [])

    def get_property(self, prop: str) -> list[str]:
        """Get a property value list, or empty list if absent."""
        return self.properties.get(prop, [])

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage or transmission."""
        return {
            "ftm_data": self.ftm_data,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "source_chip": self.source_chip,
            "investigation_id": self.investigation_id,
            "collection_id": self.collection_id,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
            "verified": self.verified,
            "notes": self.notes,
        }


@dataclass
class CrossReferenceMatch:
    """A potential match between two FtM entities."""

    source_entity: InvestigationEntity
    target_entity: InvestigationEntity
    score: float                    # Match probability (0.0-1.0)
    doubt: float                    # Inverse confidence (from FtM compare)
    match_features: dict[str, float] = field(default_factory=dict)
    status: str = "pending"         # pending | confirmed | rejected
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None

    @property
    def needs_review(self) -> bool:
        """High-probability matches above 0.7 should be human-reviewed."""
        return self.score > 0.7 and self.status == "pending"


@dataclass
class InvestigationContext:
    """Shared context for a multi-agent investigation.

    This is the BDI-equivalent for journalism: what the investigation
    believes, what it's trying to prove, and what steps it's taking.
    """

    investigation_id: str
    title: str
    hypothesis: str = ""            # The core investigative question
    collection_ids: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    known_relationships: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confirmed_facts: list[str] = field(default_factory=list)
    leads: list[str] = field(default_factory=list)
    status: str = "active"          # active | paused | completed | archived
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# FtM entity factory (wraps followthemoney library)
# ---------------------------------------------------------------------------


class FtMFactory:
    """Factory for creating FollowTheMoney entities.

    Wraps the ``followthemoney`` Python library to provide a clean
    interface for skill chips to create, validate, and manipulate
    entities without direct library coupling.

    When the ``followthemoney`` package is not installed, falls back
    to dict-based entity construction with basic validation.
    """

    def __init__(self) -> None:
        self._model = None
        try:
            from followthemoney import model
            self._model = model
            logger.info("FtM library loaded (schema count: %d)", len(model.schemata))
        except ImportError:
            logger.warning(
                "followthemoney package not installed — using dict fallback. "
                "Install with: pip install followthemoney>=4.4"
            )

    @property
    def has_ftm_library(self) -> bool:
        return self._model is not None

    def make_entity(
        self,
        schema: str,
        properties: dict[str, list[str] | str] | None = None,
        id_parts: list[str] | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a validated FtM entity dict.

        Parameters
        ----------
        schema:
            FtM schema name (e.g., 'Person', 'Company', 'Ownership').
        properties:
            Property name -> value(s) mapping. Values can be strings
            (auto-wrapped in lists) or lists of strings.
        id_parts:
            Seed values for deterministic ID generation (SHA1 hash).
            If both id_parts and entity_id are None, a random ID is used.
        entity_id:
            Explicit entity ID override.

        Returns
        -------
        dict
            FtM entity dict with keys: id, schema, properties.
        """
        if properties is None:
            properties = {}

        # Normalize all property values to lists of strings
        normalized: dict[str, list[str]] = {}
        for key, val in properties.items():
            if isinstance(val, str):
                normalized[key] = [val]
            elif isinstance(val, list):
                normalized[key] = [str(v) for v in val]
            else:
                normalized[key] = [str(val)]

        # Generate entity ID
        if entity_id is None:
            if id_parts:
                seed = ":".join(str(p) for p in id_parts)
                entity_id = hashlib.sha1(seed.encode()).hexdigest()
            else:
                import uuid
                entity_id = str(uuid.uuid4())

        if self._model is not None:
            # Use the real FtM library for validation
            try:
                proxy = self._model.make_entity(schema)
                proxy.id = entity_id
                for prop, values in normalized.items():
                    for val in values:
                        proxy.add(prop, val)
                return proxy.to_dict()
            except Exception as e:
                logger.warning("FtM library entity creation failed: %s", e)
                # Fall through to dict construction

        # Dict fallback (no schema validation)
        return {
            "id": entity_id,
            "schema": schema,
            "properties": normalized,
        }

    def make_person(
        self,
        name: str,
        birth_date: str = "",
        nationality: str = "",
        id_number: str = "",
        **extra_props: str | list[str],
    ) -> dict[str, Any]:
        """Convenience method for creating Person entities."""
        props: dict[str, list[str] | str] = {"name": name}
        if birth_date:
            props["birthDate"] = birth_date
        if nationality:
            props["nationality"] = nationality
        if id_number:
            props["idNumber"] = id_number
        props.update(extra_props)
        return self.make_entity(
            "Person",
            properties=props,
            id_parts=[name, birth_date] if birth_date else [name],
        )

    def make_company(
        self,
        name: str,
        jurisdiction: str = "",
        registration_number: str = "",
        incorporation_date: str = "",
        **extra_props: str | list[str],
    ) -> dict[str, Any]:
        """Convenience method for creating Company entities."""
        props: dict[str, list[str] | str] = {"name": name}
        if jurisdiction:
            props["jurisdiction"] = jurisdiction
        if registration_number:
            props["registrationNumber"] = registration_number
        if incorporation_date:
            props["incorporationDate"] = incorporation_date
        props.update(extra_props)
        id_parts = [name]
        if jurisdiction:
            id_parts.append(jurisdiction)
        if registration_number:
            id_parts.append(registration_number)
        return self.make_entity("Company", properties=props, id_parts=id_parts)

    def make_ownership(
        self,
        owner_id: str,
        asset_id: str,
        percentage: str = "",
        start_date: str = "",
        **extra_props: str | list[str],
    ) -> dict[str, Any]:
        """Convenience method for creating Ownership relationship entities."""
        props: dict[str, list[str] | str] = {
            "owner": owner_id,
            "asset": asset_id,
        }
        if percentage:
            props["percentage"] = percentage
        if start_date:
            props["startDate"] = start_date
        props.update(extra_props)
        return self.make_entity(
            "Ownership",
            properties=props,
            id_parts=[owner_id, asset_id],
        )

    def make_directorship(
        self,
        director_id: str,
        organization_id: str,
        role: str = "",
        start_date: str = "",
        **extra_props: str | list[str],
    ) -> dict[str, Any]:
        """Convenience method for creating Directorship relationship entities."""
        props: dict[str, list[str] | str] = {
            "director": director_id,
            "organization": organization_id,
        }
        if role:
            props["role"] = role
        if start_date:
            props["startDate"] = start_date
        props.update(extra_props)
        return self.make_entity(
            "Directorship",
            properties=props,
            id_parts=[director_id, organization_id],
        )

    def make_payment(
        self,
        payer_id: str,
        beneficiary_id: str,
        amount: str = "",
        currency: str = "",
        date: str = "",
        purpose: str = "",
        **extra_props: str | list[str],
    ) -> dict[str, Any]:
        """Convenience method for creating Payment relationship entities."""
        props: dict[str, list[str] | str] = {
            "payer": payer_id,
            "beneficiary": beneficiary_id,
        }
        if amount:
            props["amount"] = amount
        if currency:
            props["currency"] = currency
        if date:
            props["date"] = date
        if purpose:
            props["purpose"] = purpose
        props.update(extra_props)
        return self.make_entity(
            "Payment",
            properties=props,
            id_parts=[payer_id, beneficiary_id, date or ""],
        )

    def validate_entity(self, entity_dict: dict[str, Any]) -> list[str]:
        """Validate an FtM entity dict. Returns list of error messages."""
        errors = []
        if "id" not in entity_dict:
            errors.append("Missing 'id' field")
        if "schema" not in entity_dict:
            errors.append("Missing 'schema' field")
        if "properties" not in entity_dict:
            errors.append("Missing 'properties' field")
        elif not isinstance(entity_dict["properties"], dict):
            errors.append("'properties' must be a dict")
        else:
            for key, vals in entity_dict["properties"].items():
                if not isinstance(vals, list):
                    errors.append(f"Property '{key}' must be a list, got {type(vals)}")
                elif not all(isinstance(v, str) for v in vals):
                    errors.append(f"All values in property '{key}' must be strings")

        if self._model is not None and "schema" in entity_dict:
            schema_name = entity_dict["schema"]
            if schema_name not in self._model.schemata:
                errors.append(f"Unknown schema: '{schema_name}'")

        return errors

    def get_schema_names(self) -> list[str]:
        """Return all known FtM schema names."""
        if self._model is not None:
            return sorted(self._model.schemata.keys())
        # Fallback: common schemas
        return [
            "Person", "Company", "Organization", "PublicBody",
            "Vehicle", "Vessel", "Airplane", "RealEstate",
            "Document", "Address", "BankAccount", "Security",
            "Ownership", "Directorship", "Membership", "Employment",
            "Family", "Associate", "Payment", "Debt", "Sanction",
            "Representation", "Succession", "Occupancy",
        ]

    def get_relationship_schemas(self) -> list[str]:
        """Return FtM schemas that represent relationships (interstitial)."""
        return [
            "Ownership", "Directorship", "Membership", "Employment",
            "Family", "Associate", "Payment", "Debt", "Sanction",
            "Representation", "Succession", "Occupancy", "UnknownLink",
        ]

    def get_node_schemas(self) -> list[str]:
        """Return FtM schemas that represent nodes (non-interstitial)."""
        all_schemas = set(self.get_schema_names())
        rel_schemas = set(self.get_relationship_schemas())
        return sorted(all_schemas - rel_schemas)
