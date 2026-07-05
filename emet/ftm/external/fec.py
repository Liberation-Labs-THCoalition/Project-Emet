"""OpenFEC (Federal Election Commission) campaign-finance adapter for Project Emet.

Provides async access to the OpenFEC public API:
  - Candidate search (federal candidates for office)
  - Committee search (campaign committees, PACs, party committees)
  - Individual contributions (Schedule A) lookup

Free. A `DEMO_KEY` API key works for light use; a real key can be supplied
via ``FEC_API_KEY`` or ``FECConfig.api_key``.

FtM entity conversion:
  - Candidate     -> Person entity (public figures by definition)
  - Committee     -> Organization entity
  - Contribution  -> Payment entity linking contributor -> committee

Targeting policy: this adapter treats federal candidates and committees as
public figures/organizations that are always in scope. Individual (private
person) *donors* surfaced via Schedule A are suppressed by default
(``suppress_individual_donors=True``) — the Payment entity is simply not
emitted rather than emitted with a redacted name. This does not apply to
candidates themselves, who are public figures by the nature of running for
federal office.

Reference: https://api.open.fec.gov/developers/
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.open.fec.gov/v1"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FECConfig:
    """Configuration for the OpenFEC API.

    ``api_key`` falls back to the ``FEC_API_KEY`` environment variable, and
    then to the public ``DEMO_KEY`` (rate-limited, suitable for light use).
    """
    api_key: str = ""
    base_url: str = _BASE_URL
    timeout_seconds: float = 20.0
    max_results: int = 20
    suppress_individual_donors: bool = True

    def resolved_api_key(self) -> str:
        return self.api_key or os.getenv("FEC_API_KEY", "DEMO_KEY")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FECClient:
    """Async client for the OpenFEC campaign-finance API."""

    def __init__(self, config: FECConfig | None = None) -> None:
        self._config = config or FECConfig()

    async def search_candidates(
        self,
        query: str,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Search for federal candidates by name."""
        max_results = limit or self._config.max_results
        params = {
            "q": query,
            "api_key": self._config.resolved_api_key(),
            "per_page": str(max_results),
        }

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(
                f"{self._config.base_url}/candidates/search/",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = data.get("results", [])
        return results[:max_results]

    async def search_committees(
        self,
        query: str,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Search for campaign committees/PACs by name."""
        max_results = limit or self._config.max_results
        params = {
            "q": query,
            "api_key": self._config.resolved_api_key(),
            "per_page": str(max_results),
        }

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(
                f"{self._config.base_url}/committees/",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = data.get("results", [])
        return results[:max_results]

    async def get_contributions(
        self,
        committee_id: str = "",
        contributor_name: str = "",
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Get individual contributions (Schedule A) for a committee and/or contributor."""
        max_results = limit or self._config.max_results
        params: dict[str, str] = {
            "api_key": self._config.resolved_api_key(),
            "per_page": str(max_results),
        }
        if committee_id:
            params["committee_id"] = committee_id
        if contributor_name:
            params["contributor_name"] = contributor_name

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(
                f"{self._config.base_url}/schedules/schedule_a/",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = data.get("results", [])
        return results[:max_results]

    # -----------------------------------------------------------------------
    # FtM conversion
    # -----------------------------------------------------------------------

    async def search_candidates_ftm(
        self,
        query: str,
        limit: int = 0,
    ) -> dict[str, Any]:
        """Search candidates and return FtM entities."""
        candidates = await self.search_candidates(query, limit=limit)
        entities = [self.candidate_to_ftm(c) for c in candidates]
        return {
            "query": query,
            "result_count": len(entities),
            "entities": entities,
        }

    async def search_committees_ftm(
        self,
        query: str,
        limit: int = 0,
    ) -> dict[str, Any]:
        """Search committees and return FtM entities."""
        committees = await self.search_committees(query, limit=limit)
        entities = [self.committee_to_ftm(c) for c in committees]
        return {
            "query": query,
            "result_count": len(entities),
            "entities": entities,
        }

    async def get_contributions_ftm(
        self,
        committee_id: str = "",
        contributor_name: str = "",
        limit: int = 0,
    ) -> dict[str, Any]:
        """Get contributions and return FtM entities.

        Applies ``self._config.suppress_individual_donors`` when converting;
        suppressed contributions are dropped rather than emitted redacted.
        """
        contributions = await self.get_contributions(
            committee_id=committee_id,
            contributor_name=contributor_name,
            limit=limit,
        )
        suppress = self._config.suppress_individual_donors
        entities = [
            entity
            for c in contributions
            if (entity := self.contribution_to_ftm(c, suppress_individual=suppress)) is not None
        ]
        return {
            "committee_id": committee_id,
            "contributor_name": contributor_name,
            "result_count": len(entities),
            "entities": entities,
        }

    @staticmethod
    def candidate_to_ftm(candidate: dict[str, Any]) -> dict[str, Any]:
        """Convert an OpenFEC candidate record to an FtM Person entity.

        Federal candidates are public figures by definition -- this is the
        one context in this adapter where individual-suppression does NOT
        apply. Suppression only ever applies to Schedule A *donors*.
        """
        candidate_id = candidate.get("candidate_id", "")
        name = candidate.get("name", "")

        props: dict[str, list[str]] = {}
        if name:
            props["name"] = [name]

        position_bits = [
            bit
            for bit in (candidate.get("office"), candidate.get("state"))
            if bit
        ]
        if position_bits:
            props["position"] = [" - ".join(position_bits)]

        if candidate.get("party"):
            props["political"] = [candidate["party"]]

        notes: list[str] = []
        if candidate.get("incumbent_challenge_full"):
            notes.append(candidate["incumbent_challenge_full"])
        if candidate.get("election_years"):
            years = ", ".join(str(y) for y in candidate["election_years"])
            notes.append(f"Election years: {years}")
        if notes:
            props["notes"] = ["; ".join(notes)]

        return {
            "id": f"fec-candidate:{candidate_id}",
            "schema": "Person",
            "properties": {k: v for k, v in props.items() if v and v[0]},
            "_provenance": _provenance(
                source="fec",
                source_id=candidate_id,
                source_url=f"https://www.fec.gov/data/candidate/{candidate_id}/" if candidate_id else "",
                confidence=0.95,
            ),
        }

    @staticmethod
    def committee_to_ftm(committee: dict[str, Any]) -> dict[str, Any]:
        """Convert an OpenFEC committee record to an FtM Organization entity."""
        committee_id = committee.get("committee_id", "")
        name = committee.get("name", "")

        props: dict[str, list[str]] = {}
        if name:
            props["name"] = [name]
        if committee.get("committee_type_full"):
            props["legalForm"] = [committee["committee_type_full"]]
        if committee.get("designation_full"):
            props["classification"] = [committee["designation_full"]]
        if committee.get("state"):
            props["country"] = [committee["state"]]
        if committee.get("treasurer_name"):
            props["notes"] = [f"Treasurer: {committee['treasurer_name']}"]

        return {
            "id": f"fec-committee:{committee_id}",
            "schema": "Organization",
            "properties": {k: v for k, v in props.items() if v and v[0]},
            "_provenance": _provenance(
                source="fec",
                source_id=committee_id,
                source_url=f"https://www.fec.gov/data/committee/{committee_id}/" if committee_id else "",
                confidence=0.95,
            ),
        }

    @staticmethod
    def contribution_to_ftm(
        contribution: dict[str, Any],
        suppress_individual: bool = True,
    ) -> dict[str, Any] | None:
        """Convert an OpenFEC Schedule A contribution to an FtM Payment entity.

        Links contributor -> committee via ``_relationship_hints``. When
        ``suppress_individual`` is True (the default, per this repo's
        organizations-and-public-figures-only targeting policy), returns
        None instead of an entity that would expose a private individual
        donor's identity -- the Payment entity is suppressed entirely
        rather than emitted with a redacted name. When False, emits the
        full Payment entity with the contributor name in the relationship
        hints, for transparency-research contexts where that has been
        explicitly authorized elsewhere in the system.
        """
        if suppress_individual:
            return None

        sub_id = contribution.get("sub_id", "")
        contributor_name = contribution.get("contributor_name", "")
        amount = contribution.get("contribution_receipt_amount")
        date = contribution.get("contribution_receipt_date", "")
        committee = contribution.get("committee", {}) or {}
        committee_id = committee.get("committee_id", "")
        committee_name = committee.get("name", "")

        props: dict[str, list[str]] = {}
        if amount is not None:
            props["amountUsd"] = [str(amount)]
        if date:
            props["date"] = [date]
        notes: list[str] = []
        if contribution.get("contributor_employer"):
            notes.append(f"Employer: {contribution['contributor_employer']}")
        if contribution.get("contributor_occupation"):
            notes.append(f"Occupation: {contribution['contributor_occupation']}")
        if notes:
            props["notes"] = ["; ".join(notes)]

        return {
            "id": f"fec-contribution:{sub_id}" if sub_id else f"fec-contribution:{contributor_name}-{committee_id}",
            "schema": "Payment",
            "properties": {k: v for k, v in props.items() if v and v[0]},
            "_provenance": _provenance(
                source="fec",
                source_id=sub_id,
                source_url="https://www.fec.gov/data/receipts/individual-contributions/",
                confidence=0.9,
            ),
            "_relationship_hints": {
                "type": "Payment",
                "payer_name": contributor_name,
                "beneficiary_id": f"fec-committee:{committee_id}" if committee_id else "",
                "beneficiary_name": committee_name,
            },
        }
