"""CourtListener / RECAP court-records adapter.

Wraps the Free Law Project's CourtListener REST API (v4,
https://www.courtlistener.com/api/rest/v4/) which fronts the RECAP
Archive — a free, public mirror of PACER federal court documents plus
state case law. This gives Emet litigation context on an entity:
lawsuits, bankruptcies, enforcement actions, and the parties/attorneys
involved.

Auth: an optional free API token (https://www.courtlistener.com/help/api/)
raises rate limits. The adapter works token-less for light use.

FtM output:
    - ``LegalEntity`` / ``Person`` for each named party
    - ``Document`` for the docket (the case record)
    - ``Representation`` linking party -> attorney where available

Litigation records name organizations and, often, natural persons who
are parties to public court proceedings. Court filings are public
record; the targeting policy still governs downstream reporting.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CourtListenerConfig:
    """Configuration for the CourtListener API."""

    api_token: str = ""
    host: str = "https://www.courtlistener.com/api/rest/v4"
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "CourtListenerConfig":
        import os

        return cls(api_token=os.getenv("COURTLISTENER_API_TOKEN", ""))


# ---------------------------------------------------------------------------
# FtM converters
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower().strip()).strip("-")[:80]


def docket_to_ftm(docket: dict[str, Any]) -> dict[str, Any]:
    """Convert a CourtListener docket record to an FtM ``Document``."""
    docket_id = str(docket.get("id", ""))
    case_name = docket.get("case_name", "") or docket.get("case_name_full", "")
    props: dict[str, list[str]] = {"title": [case_name]}
    if docket.get("docket_number"):
        props["docketNumber"] = [docket["docket_number"]]
    if docket.get("court"):
        props["publisher"] = [str(docket["court"])]
    if docket.get("date_filed"):
        props["date"] = [docket["date_filed"]]
    if docket.get("nature_of_suit"):
        props["summary"] = [docket["nature_of_suit"]]
    abs_url = docket.get("absolute_url", "")
    source_url = f"https://www.courtlistener.com{abs_url}" if abs_url else ""
    if source_url:
        props["sourceUrl"] = [source_url]
    return {
        "id": f"courtlistener:docket:{docket_id}",
        "schema": "Document",
        "properties": props,
        "_provenance": _provenance(
            source="courtlistener",
            source_id=docket_id,
            source_url=source_url,
            confidence=0.9,
        ),
    }


def party_to_ftm(name: str, is_org: bool | None = None) -> dict[str, Any]:
    """Convert a named party to an FtM ``Company`` or ``Person``.

    If ``is_org`` is not given, guesses from corporate-suffix cues.
    """
    if is_org is None:
        is_org = bool(
            re.search(
                r"\b(inc|corp|llc|llp|ltd|co|company|bank|trust|foundation|"
                r"association|university|department|commission|agency|"
                r"united states|city of|county of|state of)\b",
                name.lower(),
            )
        )
    schema = "Company" if is_org else "Person"
    return {
        "id": f"courtlistener:party:{schema.lower()}:{_slug(name)}",
        "schema": schema,
        "properties": {"name": [name]},
        "_provenance": _provenance(
            source="courtlistener", source_id=_slug(name), confidence=0.75
        ),
    }


def docket_with_parties_to_ftm(docket: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a docket plus its parties into a list of FtM entities."""
    entities = [docket_to_ftm(docket)]
    docket_entity = entities[0]
    for party in docket.get("parties", []) or []:
        pname = party.get("name", "") if isinstance(party, dict) else str(party)
        if not pname:
            continue
        party_entity = party_to_ftm(pname)
        entities.append(party_entity)
        # Link party -> docket as an interest / involvement.
        link_id = f"courtlistener:involved:{_slug(pname)}:{docket_entity['id']}"
        entities.append(
            {
                "id": link_id,
                "schema": "Interest",
                "properties": {
                    "party": [party_entity["id"]],
                    "asset": [docket_entity["id"]],
                    "role": [
                        party.get("party_type", "party")
                        if isinstance(party, dict)
                        else "party"
                    ],
                },
                "_provenance": _provenance(
                    source="courtlistener", confidence=0.75
                ),
                "_relationship": {
                    "party": party_entity["id"],
                    "asset": docket_entity["id"],
                },
            }
        )
    return entities


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CourtListenerClient:
    """Async client for the CourtListener v4 REST API."""

    def __init__(self, config: CourtListenerConfig | None = None) -> None:
        self._config = config or CourtListenerConfig()

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "Emet-Investigation-Agent"}
        if self._config.api_token:
            headers["Authorization"] = f"Token {self._config.api_token}"
        return headers

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._config.host,
            timeout=self._config.timeout_seconds,
            headers=self._headers(),
        ) as client:
            resp = await client.get(endpoint, params=params)
            resp.raise_for_status()
            return resp.json()

    async def search_dockets(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Full-text search across dockets/opinions (the ``/search/`` API)."""
        return await self._get(
            "/search/",
            {"q": query, "type": "r", "order_by": "score desc"},
        )

    async def get_docket(self, docket_id: str) -> dict[str, Any]:
        """Fetch a single docket by id."""
        return await self._get(f"/dockets/{docket_id}/", {})

    async def search_dockets_ftm(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Federation entry point: search litigation, emit FtM entities."""
        response = await self.search_dockets(query, limit)
        results = response.get("results", [])[:limit]
        entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in results:
            entity = docket_to_ftm(row)
            if entity["id"] not in seen:
                seen.add(entity["id"])
                entities.append(entity)
            # Search results carry party names as a flat list.
            for pname in row.get("party", []) or []:
                party_entity = party_to_ftm(pname)
                if party_entity["id"] not in seen:
                    seen.add(party_entity["id"])
                    entities.append(party_entity)
        return {"query": query, "entity_count": len(entities), "entities": entities}
