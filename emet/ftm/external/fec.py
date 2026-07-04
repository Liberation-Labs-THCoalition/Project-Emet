"""FEC campaign-finance adapter.

Wraps the Federal Election Commission's OpenFEC API
(https://api.open.fec.gov) to trace political money: which committees a
candidate controls, and who contributes to a committee.

The FEC publishes bulk, public, legally-disclosed data. A free API key
is available at https://api.open.fec.gov/developers/. Without a key the
adapter uses the shared ``DEMO_KEY`` (heavily rate-limited) so it still
functions for light use / tests.

FtM output:
    - ``Person`` for candidates (publicRole = office sought)
    - ``Organization`` for committees (PACs, campaign committees)
    - ``Membership`` linking candidate -> principal committee
    - ``Payment`` for individual contributions (contributor -> committee)

Candidates, PACs, and corporate/organizational donors are public
actors. Individual small-dollar contributors are natural persons; the
adapter exposes them only in aggregate by default (``include_individual
_donors=False``) to respect the targeting policy — flip it on explicitly
only when the public-interest justification is documented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FECConfig:
    """Configuration for the OpenFEC API."""

    api_key: str = "DEMO_KEY"
    host: str = "https://api.open.fec.gov/v1"
    timeout_seconds: float = 20.0
    # Whether to emit FtM entities for individual (natural-person) donors.
    # Off by default per the targeting policy.
    include_individual_donors: bool = False

    @classmethod
    def from_env(cls) -> "FECConfig":
        import os

        return cls(api_key=os.getenv("FEC_API_KEY", "") or "DEMO_KEY")


# ---------------------------------------------------------------------------
# FtM converters
# ---------------------------------------------------------------------------


def candidate_to_ftm(cand: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenFEC candidate record to an FtM ``Person``."""
    cand_id = cand.get("candidate_id", "")
    props: dict[str, list[str]] = {"name": [cand.get("name", "")]}
    office = cand.get("office_full") or cand.get("office", "")
    if office:
        props["position"] = [f"Candidate for {office}"]
    if cand.get("party_full"):
        props["political"] = [cand["party_full"]]
    if cand.get("state"):
        props["state"] = [cand["state"]]
    props["country"] = ["us"]
    return {
        "id": f"fec:candidate:{cand_id}",
        "schema": "Person",
        "properties": props,
        "_provenance": _provenance(
            source="fec",
            source_id=cand_id,
            source_url=f"https://www.fec.gov/data/candidate/{cand_id}/",
            confidence=0.95,
        ),
    }


def committee_to_ftm(cmte: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenFEC committee record to an FtM ``Organization``."""
    cmte_id = cmte.get("committee_id", "")
    props: dict[str, list[str]] = {"name": [cmte.get("name", "")]}
    if cmte.get("committee_type_full"):
        props["classification"] = [cmte["committee_type_full"]]
    if cmte.get("state"):
        props["jurisdiction"] = [cmte["state"]]
    if cmte.get("treasurer_name"):
        props["summary"] = [f"Treasurer: {cmte['treasurer_name']}"]
    props["country"] = ["us"]
    return {
        "id": f"fec:committee:{cmte_id}",
        "schema": "Organization",
        "properties": props,
        "_provenance": _provenance(
            source="fec",
            source_id=cmte_id,
            source_url=f"https://www.fec.gov/data/committee/{cmte_id}/",
            confidence=0.95,
        ),
    }


def contribution_to_ftm(
    contrib: dict[str, Any], include_individual: bool = False
) -> list[dict[str, Any]]:
    """Convert a Schedule A contribution to FtM entities.

    Returns ``[contributor, Payment]`` (contributor may be an
    Organization or, if ``include_individual`` is set, a Person).
    Individual natural-person donors are skipped unless explicitly
    enabled, per the targeting policy.
    """
    is_individual = (contrib.get("entity_type") or "").upper() == "IND"
    if is_individual and not include_individual:
        return []

    name = contrib.get("contributor_name", "") or "Unknown contributor"
    cmte_id = contrib.get("committee_id", "")
    sub_id = str(contrib.get("sub_id", ""))
    amount = contrib.get("contribution_receipt_amount", 0)
    date = contrib.get("contribution_receipt_date", "") or ""

    schema = "Person" if is_individual else "Organization"
    contributor_id = f"fec:contributor:{schema.lower()}:{_slug(name)}"
    contributor = {
        "id": contributor_id,
        "schema": schema,
        "properties": {
            "name": [name],
            "country": ["us"],
        },
        "_provenance": _provenance(
            source="fec", source_id=sub_id, confidence=0.9
        ),
    }
    if contrib.get("contributor_employer"):
        contributor["properties"]["summary"] = [
            f"Employer: {contrib['contributor_employer']}"
        ]

    payment = {
        "id": f"fec:contribution:{sub_id}",
        "schema": "Payment",
        "properties": {
            "payer": [contributor_id],
            "beneficiary": [f"fec:committee:{cmte_id}"],
            "amount": [str(amount)],
            "currency": ["USD"],
            "date": [date] if date else [],
            "purpose": ["Campaign contribution"],
        },
        "_provenance": _provenance(
            source="fec",
            source_id=sub_id,
            source_url="https://www.fec.gov/data/receipts/",
            confidence=0.9,
        ),
        "_relationship": {
            "payer": contributor_id,
            "beneficiary": f"fec:committee:{cmte_id}",
        },
    }
    return [contributor, payment]


def _slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:80]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FECClient:
    """Async client for the OpenFEC API."""

    def __init__(self, config: FECConfig | None = None) -> None:
        self._config = config or FECConfig()

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "api_key": self._config.api_key}
        async with httpx.AsyncClient(
            base_url=self._config.host, timeout=self._config.timeout_seconds
        ) as client:
            resp = await client.get(endpoint, params=params)
            resp.raise_for_status()
            return resp.json()

    async def search_candidates(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search candidates by name."""
        return await self._get(
            "/candidates/search/", {"q": query, "per_page": limit, "sort": "name"}
        )

    async def search_committees(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search committees (PACs, campaign committees) by name."""
        return await self._get(
            "/committees/", {"q": query, "per_page": limit, "sort": "name"}
        )

    async def get_committee_contributions(
        self, committee_id: str, limit: int = 20
    ) -> dict[str, Any]:
        """Get recent Schedule A contributions to a committee."""
        return await self._get(
            "/schedules/schedule_a/",
            {
                "committee_id": committee_id,
                "per_page": limit,
                "sort": "-contribution_receipt_date",
            },
        )

    # -- FtM-emitting convenience methods ----------------------------------

    async def search_candidates_ftm(self, query: str, limit: int = 20) -> dict[str, Any]:
        response = await self.search_candidates(query, limit)
        entities = [candidate_to_ftm(c) for c in response.get("results", [])]
        return {"query": query, "entity_count": len(entities), "entities": entities}

    async def search_committees_ftm(self, query: str, limit: int = 20) -> dict[str, Any]:
        response = await self.search_committees(query, limit)
        entities = [committee_to_ftm(c) for c in response.get("results", [])]
        return {"query": query, "entity_count": len(entities), "entities": entities}

    async def trace_committee_money_ftm(
        self, committee_id: str, limit: int = 20
    ) -> dict[str, Any]:
        """Return the committee + its incoming contributions as FtM."""
        contribs = await self.get_committee_contributions(committee_id, limit)
        entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in contribs.get("results", []):
            for entity in contribution_to_ftm(
                row, include_individual=self._config.include_individual_donors
            ):
                if entity["id"] not in seen:
                    seen.add(entity["id"])
                    entities.append(entity)
        return {
            "committee_id": committee_id,
            "entity_count": len(entities),
            "entities": entities,
        }

    async def search_entities_ftm(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Federation entry point: search candidates + committees."""
        entities: list[dict[str, Any]] = []
        try:
            cands = await self.search_candidates_ftm(query, limit)
            entities.extend(cands["entities"])
        except httpx.HTTPError as exc:
            logger.warning("FEC candidate search failed: %s", exc)
        try:
            cmtes = await self.search_committees_ftm(query, limit)
            entities.extend(cmtes["entities"])
        except httpx.HTTPError as exc:
            logger.warning("FEC committee search failed: %s", exc)
        return {"query": query, "entity_count": len(entities), "entities": entities}
