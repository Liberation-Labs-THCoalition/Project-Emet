"""FtM entity converters for external data source responses.

Each converter transforms a source-specific API response into a
FollowTheMoney entity dict suitable for the DataSpine and graph engine.

Every converted entity includes ``_provenance`` metadata tracking:
    - ``source``: which data source produced this entity
    - ``source_url``: direct URL to the original record (when available)
    - ``source_id``: the source's native identifier
    - ``retrieved_at``: ISO timestamp of retrieval
    - ``confidence``: how reliable the conversion is (0–1)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provenance helper
# ---------------------------------------------------------------------------


def _provenance(
    source: str,
    source_id: str = "",
    source_url: str = "",
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Build a provenance metadata dict."""
    return {
        "source": source,
        "source_id": source_id,
        "source_url": source_url,
        "confidence": confidence,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# OpenSanctions / yente
# ---------------------------------------------------------------------------


def yente_result_to_ftm(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a yente search/match result to FtM entity dict.

    yente already returns native FtM format, so this is mostly a
    pass-through with provenance tagging.
    """
    entity = {
        "id": result.get("id", ""),
        "schema": result.get("schema", "Thing"),
        "properties": result.get("properties", {}),
        "_provenance": _provenance(
            source="opensanctions",
            source_id=result.get("id", ""),
            source_url=f"https://opensanctions.org/entities/{result.get('id', '')}",
            confidence=1.0,  # Native FtM — no conversion loss
        ),
    }

    # Add match score if present (from matching endpoint)
    if "score" in result:
        entity["_provenance"]["match_score"] = result["score"]

    # Add dataset info
    if "datasets" in result:
        entity["_provenance"]["datasets"] = result["datasets"]

    return entity


def yente_search_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a yente search response to list of FtM entities."""
    results = response.get("results", [])
    return [yente_result_to_ftm(r) for r in results]


def yente_match_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a yente match response to list of FtM entities."""
    query_results = response.get("responses", {}).get("q", {}).get("results", [])
    return [yente_result_to_ftm(r) for r in query_results]


# ---------------------------------------------------------------------------
# OpenCorporates
# ---------------------------------------------------------------------------


def oc_company_to_ftm(oc_data: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenCorporates company record to FtM Company entity."""
    company = oc_data.get("company", oc_data)

    props: dict[str, list[str]] = {
        "name": [company.get("name", "")],
    }

    if company.get("jurisdiction_code"):
        props["jurisdiction"] = [company["jurisdiction_code"]]
    if company.get("company_number"):
        props["registrationNumber"] = [company["company_number"]]
    if company.get("incorporation_date"):
        props["incorporationDate"] = [company["incorporation_date"]]
    if company.get("dissolution_date"):
        props["dissolutionDate"] = [company["dissolution_date"]]
    if company.get("registered_address_in_full"):
        props["address"] = [company["registered_address_in_full"]]
    if company.get("current_status"):
        props["status"] = [company["current_status"]]
    if company.get("company_type"):
        props["legalForm"] = [company["company_type"]]

    source_url = company.get("opencorporates_url", "")
    oc_id = f"{company.get('jurisdiction_code', '')}/{company.get('company_number', '')}"

    return {
        "schema": "Company",
        "properties": {k: v for k, v in props.items() if v and v[0]},
        "_provenance": _provenance(
            source="opencorporates",
            source_id=oc_id,
            source_url=source_url,
            confidence=0.95,
        ),
    }


def oc_officer_to_ftm(oc_data: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenCorporates officer record to FtM Person entity."""
    officer = oc_data.get("officer", oc_data)

    props: dict[str, list[str]] = {
        "name": [officer.get("name", "")],
    }

    if officer.get("nationality"):
        props["nationality"] = [officer["nationality"]]
    if officer.get("date_of_birth"):
        props["birthDate"] = [officer["date_of_birth"]]

    # Also extract the directorship relationship info
    position = officer.get("position") or officer.get("role", "")
    company_name = ""
    if officer.get("company"):
        company_name = officer["company"].get("name", "")

    entity = {
        "schema": "Person",
        "properties": {k: v for k, v in props.items() if v and v[0]},
        "_provenance": _provenance(
            source="opencorporates",
            source_id=officer.get("id", ""),
            source_url=officer.get("opencorporates_url", ""),
            confidence=0.90,
        ),
    }

    # Attach relationship hints for graph construction
    if position or company_name:
        entity["_relationship_hints"] = {
            "type": "Directorship",
            "position": position,
            "organization_name": company_name,
        }

    return entity


def oc_search_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert an OpenCorporates company search response to FtM list."""
    companies = response.get("results", {}).get("companies", [])
    return [oc_company_to_ftm(c) for c in companies]


def oc_officer_search_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert an OpenCorporates officer search response to FtM list."""
    officers = response.get("results", {}).get("officers", [])
    return [oc_officer_to_ftm(o) for o in officers]


# ---------------------------------------------------------------------------
# ICIJ Offshore Leaks
# ---------------------------------------------------------------------------


_ICIJ_TYPE_TO_SCHEMA: dict[str, str] = {
    "entity": "Company",
    "officer": "Person",
    "intermediary": "LegalEntity",
    "address": "Address",
    "other": "Thing",
}


def icij_node_to_ftm(node: dict[str, Any]) -> dict[str, Any]:
    """Convert an ICIJ Offshore Leaks node to FtM entity."""
    node_type = node.get("type", "entity").lower()
    schema = _ICIJ_TYPE_TO_SCHEMA.get(node_type, "Thing")

    props: dict[str, list[str]] = {}

    name = node.get("name", "") or node.get("original_name", "")
    if name:
        props["name"] = [name]

    if node.get("country_codes"):
        # ICIJ uses semicolon-separated country codes
        countries = [c.strip() for c in str(node["country_codes"]).split(";") if c.strip()]
        if countries:
            props["country"] = countries

    if node.get("jurisdiction"):
        props["jurisdiction"] = [node["jurisdiction"]]

    if node.get("incorporation_date"):
        props["incorporationDate"] = [node["incorporation_date"]]

    if node.get("inactivation_date"):
        props["dissolutionDate"] = [node["inactivation_date"]]

    if node.get("address"):
        props["address"] = [node["address"]]

    if node.get("note"):
        props["notes"] = [node["note"]]

    # Tag with source datasets
    source_datasets = []
    if node.get("sourceID"):
        source_datasets = [s.strip() for s in str(node["sourceID"]).split(";") if s.strip()]

    node_id = str(node.get("node_id", node.get("id", "")))

    return {
        "schema": schema,
        "properties": {k: v for k, v in props.items() if v and v[0]},
        "_provenance": _provenance(
            source="icij_offshore_leaks",
            source_id=node_id,
            source_url=f"https://offshoreleaks.icij.org/nodes/{node_id}",
            confidence=0.85,  # Historical leak data, may be outdated
        ),
        "_icij_metadata": {
            "node_type": node_type,
            "source_datasets": source_datasets,
            "status": node.get("status", ""),
        },
    }


def icij_search_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ICIJ search response to list of FtM entities."""
    # ICIJ API returns different structures depending on endpoint
    if isinstance(response, list):
        return [icij_node_to_ftm(n) for n in response]
    nodes = response.get("data", response.get("results", []))
    if isinstance(nodes, list):
        return [icij_node_to_ftm(n) for n in nodes]
    return []


def icij_relationships_to_ftm(
    node_id: str,
    relationships: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert ICIJ relationship data to FtM relationship entities."""
    entities: list[dict[str, Any]] = []

    for rel in relationships.get("data", relationships.get("results", [])):
        rel_type = rel.get("type", "").lower()

        # Map ICIJ relationship types to FtM schemas
        if "officer" in rel_type or "director" in rel_type:
            schema = "Directorship"
        elif "intermediary" in rel_type or "registered" in rel_type:
            schema = "Representation"
        elif "address" in rel_type:
            schema = "Address"
        else:
            schema = "UnknownLink"

        entity = {
            "schema": schema,
            "properties": {},
            "_provenance": _provenance(
                source="icij_offshore_leaks",
                source_id=f"{node_id}-{rel.get('node_id', '')}",
                source_url=f"https://offshoreleaks.icij.org/nodes/{node_id}",
                confidence=0.80,
            ),
            "_relationship_hints": {
                "source_node": node_id,
                "target_node": str(rel.get("node_id", "")),
                "relationship_type": rel_type,
            },
        }
        entities.append(entity)

    return entities


# ---------------------------------------------------------------------------
# GLEIF
# ---------------------------------------------------------------------------


def gleif_record_to_ftm(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a GLEIF LEI record to FtM Company entity."""
    attrs = record.get("attributes", {})
    entity_data = attrs.get("entity", {})

    legal_name = entity_data.get("legalName", {}).get("name", "")
    jurisdiction = entity_data.get("jurisdiction", "")
    lei = attrs.get("lei", "")

    props: dict[str, list[str]] = {
        "name": [legal_name],
    }

    if lei:
        props["leiCode"] = [lei]
    if jurisdiction:
        props["jurisdiction"] = [jurisdiction]

    # Legal address
    legal_address = entity_data.get("legalAddress", {})
    if legal_address:
        parts = [
            legal_address.get("addressLines", [""])[0] if legal_address.get("addressLines") else "",
            legal_address.get("city", ""),
            legal_address.get("region", ""),
            legal_address.get("country", ""),
            legal_address.get("postalCode", ""),
        ]
        addr = ", ".join(p for p in parts if p)
        if addr:
            props["address"] = [addr]
        if legal_address.get("country"):
            props["country"] = [legal_address["country"]]

    # Other names
    other_names = entity_data.get("otherNames", [])
    if other_names:
        aliases = [n.get("name", "") for n in other_names if n.get("name")]
        if aliases:
            props["alias"] = aliases

    # Registration
    registration = attrs.get("registration", {})
    if registration.get("initialRegistrationDate"):
        props["incorporationDate"] = [registration["initialRegistrationDate"][:10]]

    entity_status = entity_data.get("status", "")

    return {
        "schema": "Company",
        "properties": {k: v for k, v in props.items() if v and v[0]},
        "_provenance": _provenance(
            source="gleif",
            source_id=lei,
            source_url=f"https://search.gleif.org/#/record/{lei}" if lei else "",
            confidence=0.98,  # Official registry data
        ),
        "_gleif_metadata": {
            "entity_status": entity_status,
            "registration_status": registration.get("status", ""),
            "managing_lou": registration.get("managingLou", ""),
        },
    }


def gleif_search_to_ftm_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert GLEIF search response to list of FtM entities."""
    records = response.get("data", [])
    return [gleif_record_to_ftm(r) for r in records]


def gleif_relationship_to_ftm(
    child_lei: str,
    parent_response: dict[str, Any],
    relationship_type: str = "direct",
) -> dict[str, Any] | None:
    """Convert a GLEIF parent relationship to FtM Ownership entity."""
    rel_data = parent_response.get("data", {})
    if not rel_data:
        return None

    attrs = rel_data.get("attributes", {})
    relationship = attrs.get("relationship", {})

    parent_record = relationship.get("startNode", {})
    parent_lei = parent_record.get("id", "")

    if not parent_lei:
        return None

    props: dict[str, list[str]] = {}
    if relationship.get("startDate"):
        props["startDate"] = [relationship["startDate"][:10]]

    return {
        "schema": "Ownership",
        "properties": props,
        "_provenance": _provenance(
            source="gleif",
            source_id=f"{parent_lei}-{child_lei}",
            source_url=f"https://search.gleif.org/#/record/{child_lei}",
            confidence=0.98,
        ),
        "_relationship_hints": {
            "owner_lei": parent_lei,
            "asset_lei": child_lei,
            "relationship_type": relationship_type,
        },
    }
