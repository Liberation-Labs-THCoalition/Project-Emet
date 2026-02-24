"""External data source adapters for investigative journalism.

These adapters provide async interfaces to the major external data sources
that complement Aleph. Each returns data in FtM-compatible formats or raw
dicts that skill chips convert to FtM entities.

Data Sources:
    - OpenSanctions / yente: 325+ sanctions and PEP lists, native FtM
    - OpenCorporates: 200M+ companies from 145+ jurisdictions
    - ICIJ Offshore Leaks: 810K+ offshore entities from major leaks
    - GLEIF: Global Legal Entity Identifier index (LEI)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenSanctions / yente API
# ---------------------------------------------------------------------------


@dataclass
class YenteConfig:
    """Configuration for OpenSanctions yente screening API."""
    host: str = "https://api.opensanctions.org"
    api_key: str = ""
    timeout_seconds: float = 20.0


class YenteClient:
    """Async client for the OpenSanctions yente entity matching API.

    yente provides entity matching and search against 325+ aggregated
    sanctions, PEP, and watchlist datasets — all in native FtM format.
    This is the single most important external data source for Aleph
    investigations.

    Endpoints:
        GET /search/{dataset}    — Full-text search
        POST /match/{dataset}    — Entity matching (batch)
        GET /entities/{entity_id} — Entity lookup by ID
    """

    def __init__(self, config: YenteConfig | None = None) -> None:
        self._config = config or YenteConfig()
        self._headers: dict[str, str] = {}
        if self._config.api_key:
            self._headers["Authorization"] = f"ApiKey {self._config.api_key}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.host,
            headers=self._headers,
            timeout=self._config.timeout_seconds,
        )

    async def search(
        self,
        query: str,
        dataset: str = "default",
        schema: str = "",
        countries: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Full-text search across OpenSanctions datasets."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if schema:
            params["schema"] = schema
        if countries:
            params["countries"] = countries

        async with self._client() as client:
            resp = await client.get(f"/search/{dataset}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def match_entity(
        self,
        entity_data: dict[str, Any],
        dataset: str = "default",
    ) -> dict[str, Any]:
        """Match an FtM entity against OpenSanctions datasets.

        Parameters
        ----------
        entity_data:
            FtM entity dict (schema, properties). Does not need an ID.
        """
        async with self._client() as client:
            resp = await client.post(
                f"/match/{dataset}",
                json={"queries": {"q": entity_data}},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        """Retrieve a specific entity by its OpenSanctions ID."""
        async with self._client() as client:
            resp = await client.get(f"/entities/{entity_id}")
            resp.raise_for_status()
            return resp.json()

    async def screen_entities(
        self,
        entities: list[dict[str, Any]],
        dataset: str = "default",
    ) -> list[dict[str, Any]]:
        """Screen multiple entities against sanctions lists.

        Returns matches for each input entity, sorted by match score.
        """
        results = []
        async with self._client() as client:
            for entity in entities:
                try:
                    resp = await client.post(
                        f"/match/{dataset}",
                        json={"queries": {"q": entity}},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results.append({
                        "input": entity,
                        "matches": data.get("responses", {}).get("q", {}).get("results", []),
                    })
                except Exception as e:
                    logger.warning("Screening failed for entity: %s", e)
                    results.append({"input": entity, "matches": [], "error": str(e)})
        return results


# ---------------------------------------------------------------------------
# OpenCorporates API
# ---------------------------------------------------------------------------


@dataclass
class OpenCorporatesConfig:
    """Configuration for the OpenCorporates API.

    Note: Free tier allows 200 requests/month. Journalists and NGOs
    can apply for unrestricted free access via opencorporates.com.
    """
    host: str = "https://api.opencorporates.com/v0.4.8"
    api_token: str = ""
    timeout_seconds: float = 20.0


class OpenCorporatesClient:
    """Async client for the OpenCorporates API.

    Covers 200M+ companies from 145+ jurisdictions. Provides company
    search, officer search, jurisdiction lookups, and a reconciliation
    API for entity matching.
    """

    def __init__(self, config: OpenCorporatesConfig | None = None) -> None:
        self._config = config or OpenCorporatesConfig()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.host,
            timeout=self._config.timeout_seconds,
        )

    async def search_companies(
        self,
        query: str,
        jurisdiction: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for companies by name."""
        params: dict[str, Any] = {"q": query, "per_page": limit}
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction
        if self._config.api_token:
            params["api_token"] = self._config.api_token

        async with self._client() as client:
            resp = await client.get("/companies/search", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_company(
        self, jurisdiction: str, company_number: str
    ) -> dict[str, Any]:
        """Get a specific company by jurisdiction and registration number."""
        params: dict[str, Any] = {}
        if self._config.api_token:
            params["api_token"] = self._config.api_token

        async with self._client() as client:
            resp = await client.get(
                f"/companies/{jurisdiction}/{company_number}",
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def search_officers(
        self,
        query: str,
        jurisdiction: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for company officers (directors, secretaries, etc.)."""
        params: dict[str, Any] = {"q": query, "per_page": limit}
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction
        if self._config.api_token:
            params["api_token"] = self._config.api_token

        async with self._client() as client:
            resp = await client.get("/officers/search", params=params)
            resp.raise_for_status()
            return resp.json()

    def company_to_ftm(self, oc_company: dict[str, Any]) -> dict[str, Any]:
        """Convert an OpenCorporates company record to FtM entity dict."""
        company = oc_company.get("company", oc_company)
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
        if company.get("opencorporates_url"):
            props["sourceUrl"] = [company["opencorporates_url"]]

        return {
            "schema": "Company",
            "properties": {k: v for k, v in props.items() if v and v[0]},
        }


# ---------------------------------------------------------------------------
# ICIJ Offshore Leaks API
# ---------------------------------------------------------------------------


@dataclass
class ICIJConfig:
    """Configuration for the ICIJ Offshore Leaks API.

    As of January 2025, ICIJ uses a Reconciliation API (W3C standard)
    instead of the old REST search endpoint.
    """
    host: str = "https://offshoreleaks.icij.org"
    reconcile_path: str = "/api/v1/reconcile"
    timeout_seconds: float = 45.0  # Reconciliation can be slow


# Map our entity types to ICIJ reconciliation types
_ICIJ_RECONCILE_TYPES: dict[str, str] = {
    "person": "https://offshoreleaks.icij.org/schema/oldb/officer",
    "people": "https://offshoreleaks.icij.org/schema/oldb/officer",
    "officer": "https://offshoreleaks.icij.org/schema/oldb/officer",
    "company": "https://offshoreleaks.icij.org/schema/oldb/entity",
    "organization": "https://offshoreleaks.icij.org/schema/oldb/entity",
    "entity": "https://offshoreleaks.icij.org/schema/oldb/entity",
    "intermediary": "https://offshoreleaks.icij.org/schema/oldb/intermediary",
    "address": "https://offshoreleaks.icij.org/schema/oldb/address",
}


class ICIJClient:
    """Async client for the ICIJ Offshore Leaks database.

    Contains 810K+ offshore entities from five major leak investigations:
    Panama Papers, Paradise Papers, Offshore Leaks, Bahamas Leaks, and
    Pandora Papers.

    Uses the W3C Reconciliation API (introduced January 2025).
    """

    def __init__(self, config: ICIJConfig | None = None) -> None:
        self._config = config or ICIJConfig()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.host,
            timeout=self._config.timeout_seconds,
        )

    async def search(
        self,
        query: str,
        entity_type: str = "",
        country: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search the Offshore Leaks database via the Reconciliation API.

        Returns results in a normalized format compatible with
        icij_search_to_ftm_list().
        """
        import json as _json

        # Build reconciliation query
        recon_query: dict[str, Any] = {"query": query, "limit": limit}

        # Add type constraint if specified
        type_uri = _ICIJ_RECONCILE_TYPES.get(entity_type.lower(), "")
        if type_uri:
            recon_query["type"] = type_uri

        queries_payload = _json.dumps({"q0": recon_query})

        async with self._client() as client:
            resp = await client.post(
                self._config.reconcile_path,
                data={"queries": queries_payload},
            )
            resp.raise_for_status()
            data = resp.json()

        # Normalize reconciliation response → list of node-like dicts
        results = []
        for match in data.get("q0", {}).get("result", []):
            # Extract type from the reconciliation type URI
            types = match.get("types", [])
            node_type = "entity"
            if types:
                type_name = types[0].get("name", "Entity").lower()
                node_type = type_name

            results.append({
                "node_id": match.get("id", ""),
                "name": match.get("name", ""),
                "type": node_type,
                "description": match.get("description", ""),
                "_reconciliation_score": match.get("score", 0),
            })

        return {"results": results}

    async def get_entity(self, node_id: str) -> dict[str, Any]:
        """Get a specific entity from the Offshore Leaks database.

        Note: The direct node API may not be available. Falls back
        to reconciliation search by ID.
        """
        async with self._client() as client:
            # Try the node detail endpoint first
            try:
                resp = await client.get(f"/api/v1/nodes/{node_id}")
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass

        # Fallback: not available in reconciliation API
        return {"error": "Node detail not available", "node_id": node_id}

    async def get_relationships(self, node_id: str) -> dict[str, Any]:
        """Get all relationships for an entity.

        Note: The direct relationship API may not be available.
        """
        async with self._client() as client:
            try:
                resp = await client.get(f"/api/v1/nodes/{node_id}/relationships")
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass

        return {"error": "Relationship detail not available", "node_id": node_id}


# ---------------------------------------------------------------------------
# GLEIF LEI API
# ---------------------------------------------------------------------------


@dataclass
class GLEIFConfig:
    """Configuration for the GLEIF LEI API.

    Free access, no registration required. CC0 license.
    """
    host: str = "https://api.gleif.org/api/v1"
    timeout_seconds: float = 20.0


class GLEIFClient:
    """Async client for the Global LEI Foundation API.

    Provides entity identification ("who is who") and corporate
    relationship data ("who owns whom") via Legal Entity Identifiers.
    """

    def __init__(self, config: GLEIFConfig | None = None) -> None:
        self._config = config or GLEIFConfig()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.host,
            timeout=self._config.timeout_seconds,
        )

    async def search_entities(
        self,
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Full-text search for legal entities by name."""
        async with self._client() as client:
            resp = await client.get(
                "/lei-records",
                params={"filter[fulltext]": query, "page[size]": limit},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_entity_by_lei(self, lei: str) -> dict[str, Any]:
        """Lookup a legal entity by its LEI code."""
        async with self._client() as client:
            resp = await client.get(f"/lei-records/{lei}")
            resp.raise_for_status()
            return resp.json()

    async def get_direct_parent(self, lei: str) -> dict[str, Any]:
        """Get the direct parent (owner) of a legal entity."""
        async with self._client() as client:
            resp = await client.get(
                f"/lei-records/{lei}/direct-parent-relationship"
            )
            resp.raise_for_status()
            return resp.json()

    async def get_ultimate_parent(self, lei: str) -> dict[str, Any]:
        """Get the ultimate parent of a legal entity."""
        async with self._client() as client:
            resp = await client.get(
                f"/lei-records/{lei}/ultimate-parent-relationship"
            )
            resp.raise_for_status()
            return resp.json()

    async def get_children(self, lei: str) -> dict[str, Any]:
        """Get direct children (subsidiaries) of a legal entity."""
        async with self._client() as client:
            resp = await client.get(
                f"/lei-records/{lei}/direct-child-relationships"
            )
            resp.raise_for_status()
            return resp.json()

    def lei_record_to_ftm(self, record: dict[str, Any]) -> dict[str, Any]:
        """Convert a GLEIF LEI record to FtM entity dict."""
        attrs = record.get("attributes", {})
        entity_data = attrs.get("entity", {})
        legal_name = entity_data.get("legalName", {}).get("name", "")
        jurisdiction = entity_data.get("jurisdiction", "")

        props: dict[str, list[str]] = {
            "name": [legal_name],
            "leiCode": [attrs.get("lei", "")],
        }
        if jurisdiction:
            props["jurisdiction"] = [jurisdiction]

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

        return {
            "schema": "Company",
            "properties": {k: v for k, v in props.items() if v and v[0]},
        }
