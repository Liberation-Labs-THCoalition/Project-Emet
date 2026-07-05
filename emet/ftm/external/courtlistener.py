"""CourtListener / RECAP (Free Law Project) adapter for Project Emet.

Provides async access to the CourtListener REST API for federal court
records:
  - RECAP docket search (federal case search across PACER-derived data)
  - Docket detail lookup (parties, judge, dates, case metadata)

Free and public. Unauthenticated access works at a lower rate limit; an
optional API token (``COURTLISTENER_API_TOKEN``) raises the rate limit via
``Authorization: Token {api_token}``.

FtM entity conversion:
  - Docket           -> Document entity (case metadata, source URL)
  - Party            -> Person or Company/LegalEntity entity
  - Party <-> Docket -> Representation relationship ("is involved in this
                        case", using Representation as the closest existing
                        relationship schema for docket participation)

Reference: https://www.courtlistener.com/api/rest-info/
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"

# Substrings (case-insensitive, matched against whitespace-separated tokens
# or as a bare substring) that indicate a party name refers to an
# organization rather than an individual person.
_ORG_MARKERS = (
    "inc",
    "llc",
    "corp",
    "corporation",
    "company",
    "ltd",
    "llp",
    "plc",
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CourtListenerConfig:
    """Configuration for the CourtListener/RECAP API.

    ``api_token`` is optional -- it falls back to the
    ``COURTLISTENER_API_TOKEN`` environment variable, and unauthenticated
    requests still work (at a lower rate limit) if neither is set.
    """
    api_token: str = ""
    base_url: str = _BASE_URL
    timeout_seconds: float = 20.0
    max_results: int = 20


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CourtListenerClient:
    """Async client for the CourtListener/RECAP federal court-records API."""

    def __init__(self, config: CourtListenerConfig | None = None) -> None:
        self._config = config or CourtListenerConfig()
        api_token = self._config.api_token or os.getenv("COURTLISTENER_API_TOKEN", "")
        self._headers: dict[str, str] = {}
        if api_token:
            self._headers["Authorization"] = f"Token {api_token}"

    async def search_dockets(self, query: str, limit: int = 0) -> list[dict[str, Any]]:
        """Search RECAP dockets by free-text query."""
        max_results = limit or self._config.max_results
        params = {
            "q": query,
            "type": "r",
        }

        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            resp = await client.get(
                f"{self._config.base_url}/search/",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = data.get("results", [])
        return results[:max_results]

    async def get_docket(self, docket_id: str | int) -> dict[str, Any]:
        """Fetch a single docket's full detail by id.

        On a 404/error response, logs a warning and returns ``{}`` rather
        than raising, matching this repo's graceful-degradation pattern for
        external source failures.
        """
        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            try:
                resp = await client.get(f"{self._config.base_url}/dockets/{docket_id}/")
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("CourtListener docket lookup failed for %s: %s", docket_id, exc)
                return {}
            return resp.json()

    # -----------------------------------------------------------------------
    # FtM conversion
    # -----------------------------------------------------------------------

    async def search_dockets_ftm(self, query: str, limit: int = 0) -> dict[str, Any]:
        """Search dockets and return flattened FtM entities."""
        dockets = await self.search_dockets(query, limit=limit)
        entities: list[dict[str, Any]] = []
        for docket in dockets:
            entities.extend(self.docket_to_ftm(docket))
        return {
            "query": query,
            "result_count": len(dockets),
            "entities": entities,
        }

    async def get_docket_ftm(self, docket_id: str | int) -> dict[str, Any]:
        """Fetch a docket and return its FtM entities."""
        docket = await self.get_docket(docket_id)
        entities = self.docket_to_ftm(docket) if docket else []
        return {
            "docket_id": docket_id,
            "entities": entities,
        }

    @staticmethod
    def docket_to_ftm(docket: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert a CourtListener docket record into a list of FtM entities.

        Emits one Document entity for the docket itself, one Person/Company
        entity per party (when party data is present), and one
        Representation relationship entity per party linking that party to
        the docket. Search-result dockets are lighter-weight than
        ``get_docket`` results and may not include a ``parties`` key at
        all -- that's handled gracefully by simply skipping party/
        relationship entities in that case.
        """
        docket_id = str(docket.get("id", ""))
        case_name = docket.get("case_name") or docket.get("caseName", "")
        date_filed = docket.get("date_filed") or docket.get("dateFiled", "")
        court = docket.get("court", "")
        docket_number = docket.get("docket_number") or docket.get("docketNumber", "")
        source_url = f"https://www.courtlistener.com/docket/{docket_id}/"

        provenance = _provenance(
            source="courtlistener",
            source_id=docket_id,
            source_url=source_url,
            confidence=0.9,
        )

        doc_id = f"courtlistener-docket:{docket_id}"
        doc_props: dict[str, list[str]] = {}
        if case_name:
            doc_props["title"] = [case_name]
        if date_filed:
            doc_props["date"] = [date_filed]
        if source_url:
            doc_props["sourceUrl"] = [source_url]
        if court or docket_number:
            doc_props["summary"] = [f"{court}: docket {docket_number}"]

        entities: list[dict[str, Any]] = [
            {
                "id": doc_id,
                "schema": "Document",
                "properties": doc_props,
                "_provenance": dict(provenance),
            }
        ]

        for party in docket.get("parties", []) or []:
            name = party.get("name", "")
            if not name:
                continue

            party_id = f"courtlistener-party:{_slugify(name)}"
            schema = "Company" if _looks_like_organization(name) else "Person"

            entities.append({
                "id": party_id,
                "schema": schema,
                "properties": {"name": [name]},
                "_provenance": dict(provenance),
            })

            party_types = party.get("party_types") or []
            role = "party"
            if party_types:
                first_type = party_types[0]
                if isinstance(first_type, dict):
                    role = first_type.get("party_type") or "party"
                elif isinstance(first_type, str):
                    role = first_type

            entities.append({
                "id": f"courtlistener-rep:{docket_id}-{_slugify(name)}",
                "schema": "Representation",
                "properties": {
                    "agent": [party_id],
                    "client": [doc_id],
                    "role": [role],
                },
                "_provenance": dict(provenance),
            })

        return entities


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looks_like_organization(name: str) -> bool:
    """Heuristic: does this party name look like an organization?"""
    tokens = re.split(r"[\s,.\-]+", name.lower())
    tokens = [t for t in tokens if t]
    return any(marker in tokens for marker in _ORG_MARKERS)


def _slugify(name: str) -> str:
    """Turn a party name into a stable, URL/id-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"
