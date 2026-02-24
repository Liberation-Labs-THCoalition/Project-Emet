"""UK Companies House API adapter for Project Emet.

Provides async access to Companies House public data API:
  - Company search (name, number, SIC codes)
  - Company profile (registered address, officers, status)
  - Officer search and appointments
  - Persons with Significant Control (PSC) — beneficial ownership
  - Filing history

600M+ records. Free for basic use (with API key from
https://developer.company-information.service.gov.uk).

FtM entity conversion:
  - Company       → Company entity
  - Officer       → Person + Directorship
  - PSC (person)  → Person + Ownership
  - PSC (company) → Company + Ownership (shell chain tracing)
  - Filing        → Document/Note

Reference: https://developer-specs.company-information.service.gov.uk/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.company-information.service.gov.uk"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CompaniesHouseConfig:
    """Configuration for UK Companies House API.

    API key is free — register at:
    https://developer.company-information.service.gov.uk/manage-applications
    """
    api_key: str = ""
    timeout_seconds: float = 20.0
    max_results: int = 50


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CompaniesHouseClient:
    """Async client for the UK Companies House API.

    All endpoints use HTTP Basic Auth with api_key as username, empty password.
    """

    def __init__(self, config: CompaniesHouseConfig | None = None) -> None:
        self._config = config or CompaniesHouseConfig()

    def _client(self) -> httpx.AsyncClient:
        auth = (self._config.api_key, "") if self._config.api_key else None
        return httpx.AsyncClient(
            base_url=_BASE_URL,
            auth=auth,
            timeout=self._config.timeout_seconds,
        )

    # --- Search ---

    async def search_companies(
        self,
        query: str,
        items_per_page: int = 0,
    ) -> dict[str, Any]:
        """Search for companies by name.

        Returns:
            Dict with 'items' list of company summaries.
        """
        limit = items_per_page or self._config.max_results
        async with self._client() as client:
            resp = await client.get(
                "/search/companies",
                params={"q": query, "items_per_page": limit},
            )
            resp.raise_for_status()
            return resp.json()

    async def search_officers(
        self,
        query: str,
        items_per_page: int = 0,
    ) -> dict[str, Any]:
        """Search for officers (directors, secretaries) by name."""
        limit = items_per_page or self._config.max_results
        async with self._client() as client:
            resp = await client.get(
                "/search/officers",
                params={"q": query, "items_per_page": limit},
            )
            resp.raise_for_status()
            return resp.json()

    # --- Company details ---

    async def get_company(self, company_number: str) -> dict[str, Any]:
        """Get full company profile by registration number."""
        async with self._client() as client:
            resp = await client.get(f"/company/{company_number}")
            resp.raise_for_status()
            return resp.json()

    async def get_officers(
        self,
        company_number: str,
        items_per_page: int = 50,
    ) -> dict[str, Any]:
        """List officers for a company."""
        async with self._client() as client:
            resp = await client.get(
                f"/company/{company_number}/officers",
                params={"items_per_page": items_per_page},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_pscs(
        self,
        company_number: str,
        items_per_page: int = 50,
    ) -> dict[str, Any]:
        """Get Persons with Significant Control (beneficial owners)."""
        async with self._client() as client:
            resp = await client.get(
                f"/company/{company_number}/persons-with-significant-control",
                params={"items_per_page": items_per_page},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_filing_history(
        self,
        company_number: str,
        items_per_page: int = 25,
    ) -> dict[str, Any]:
        """Get filing history for a company."""
        async with self._client() as client:
            resp = await client.get(
                f"/company/{company_number}/filing-history",
                params={"items_per_page": items_per_page},
            )
            resp.raise_for_status()
            return resp.json()

    # --- FtM conversions ---

    async def search_companies_ftm(
        self,
        query: str,
        items_per_page: int = 0,
    ) -> dict[str, Any]:
        """Search and convert results to FtM entities."""
        data = await self.search_companies(query, items_per_page)
        items = data.get("items", [])
        entities = [self.company_to_ftm(c) for c in items]

        return {
            "query": query,
            "result_count": data.get("total_results", len(items)),
            "entities": entities,
        }

    async def get_company_ftm(
        self, company_number: str
    ) -> dict[str, Any]:
        """Get company profile + officers + PSCs as FtM entities."""
        profile = await self.get_company(company_number)
        entities = [self.company_to_ftm(profile)]

        try:
            officers_data = await self.get_officers(company_number)
            for item in officers_data.get("items", []):
                person, directorship = self.officer_to_ftm(item, company_number)
                entities.append(person)
                entities.append(directorship)
        except Exception as exc:
            logger.warning("Failed to fetch officers for %s: %s", company_number, exc)

        try:
            pscs_data = await self.get_pscs(company_number)
            for item in pscs_data.get("items", []):
                ftm_entities = self.psc_to_ftm(item, company_number)
                entities.extend(ftm_entities)
        except Exception as exc:
            logger.warning("Failed to fetch PSCs for %s: %s", company_number, exc)

        return {
            "company_number": company_number,
            "entity_count": len(entities),
            "entities": entities,
        }

    # --- Converters ---

    @staticmethod
    def company_to_ftm(ch_company: dict[str, Any]) -> dict[str, Any]:
        """Convert a Companies House company record to FtM Company entity."""
        props: dict[str, list[str]] = {
            "name": [ch_company.get("company_name", ch_company.get("title", ""))],
        }

        if ch_company.get("company_number"):
            props["registrationNumber"] = [ch_company["company_number"]]
        if ch_company.get("jurisdiction"):
            props["jurisdiction"] = [ch_company["jurisdiction"]]
        else:
            props["jurisdiction"] = ["gb"]

        # Incorporation / dissolution
        if ch_company.get("date_of_creation"):
            props["incorporationDate"] = [ch_company["date_of_creation"]]
        if ch_company.get("date_of_cessation"):
            props["dissolutionDate"] = [ch_company["date_of_cessation"]]

        # Status
        status = ch_company.get("company_status", "")
        if status:
            props["status"] = [status]

        # Address
        addr = ch_company.get("registered_office_address", {})
        if isinstance(addr, dict):
            parts = [
                addr.get("address_line_1", ""),
                addr.get("address_line_2", ""),
                addr.get("locality", ""),
                addr.get("region", ""),
                addr.get("postal_code", ""),
                addr.get("country", ""),
            ]
            full = ", ".join(p for p in parts if p)
            if full:
                props["address"] = [full]
        elif isinstance(addr, str) and addr:
            props["address"] = [addr]

        # Address (search result format)
        snippet_addr = ch_company.get("address_snippet", "")
        if snippet_addr and "address" not in props:
            props["address"] = [snippet_addr]

        # SIC codes
        sic = ch_company.get("sic_codes", [])
        if sic:
            props["classification"] = sic

        # Source URL
        cn = ch_company.get("company_number", "")
        if cn:
            props["sourceUrl"] = [f"https://find-and-update.company-information.service.gov.uk/company/{cn}"]

        return {
            "id": f"ch:{cn}" if cn else f"ch:{props.get('name', [''])[0]}",
            "schema": "Company",
            "properties": {k: v for k, v in props.items() if v and v[0]},
        }

    @staticmethod
    def officer_to_ftm(
        officer: dict[str, Any],
        company_number: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Convert a Companies House officer to FtM Person + Directorship."""
        name = officer.get("name", "")
        role = officer.get("officer_role", "director")

        # Extract officer ID from links if available
        officer_id = ""
        links = officer.get("links", {})
        if isinstance(links, dict):
            appt_link = links.get("officer", {}).get("appointments", "")
            if appt_link:
                officer_id = appt_link.split("/officers/")[-1].split("/")[0]

        person: dict[str, Any] = {
            "id": f"ch-officer:{officer_id}" if officer_id else f"ch-officer:{name}",
            "schema": "Person",
            "properties": {"name": [name]},
        }

        nationality = officer.get("nationality")
        if nationality:
            person["properties"]["nationality"] = [nationality]

        dob = officer.get("date_of_birth", {})
        if isinstance(dob, dict) and dob.get("year"):
            month = str(dob.get("month", 1)).zfill(2)
            person["properties"]["birthDate"] = [f"{dob['year']}-{month}"]

        directorship: dict[str, Any] = {
            "id": f"ch-dir:{officer_id or name}:{company_number}",
            "schema": "Directorship",
            "properties": {
                "director": [name],
                "organization": [company_number],
                "role": [role],
            },
        }

        appointed = officer.get("appointed_on")
        if appointed:
            directorship["properties"]["startDate"] = [appointed]

        resigned = officer.get("resigned_on")
        if resigned:
            directorship["properties"]["endDate"] = [resigned]

        return person, directorship

    @staticmethod
    def psc_to_ftm(
        psc: dict[str, Any],
        company_number: str,
    ) -> list[dict[str, Any]]:
        """Convert a PSC record to FtM entities (Person/Company + Ownership)."""
        entities: list[dict[str, Any]] = []
        kind = psc.get("kind", "")
        name = psc.get("name", psc.get("name_elements", {}).get("surname", ""))

        natures = psc.get("natures_of_control", [])
        control_summary = "; ".join(natures) if natures else "significant control"

        if "individual" in kind:
            psc_id = psc.get("links", {}).get("self", name)
            person: dict[str, Any] = {
                "id": f"ch-psc:{psc_id}",
                "schema": "Person",
                "properties": {"name": [name]},
            }
            nationality = psc.get("nationality")
            if nationality:
                person["properties"]["nationality"] = [nationality]
            entities.append(person)

            entities.append({
                "id": f"ch-ownership:{psc_id}:{company_number}",
                "schema": "Ownership",
                "properties": {
                    "owner": [name],
                    "asset": [company_number],
                    "role": [control_summary],
                },
            })

        elif "corporate" in kind or "legal" in kind:
            corp_name = psc.get("name", "")
            reg_num = psc.get("identification", {}).get("registration_number", "")
            entities.append({
                "id": f"ch-psc-corp:{reg_num or corp_name}",
                "schema": "Company",
                "properties": {
                    "name": [corp_name],
                    "jurisdiction": [psc.get("identification", {}).get("country_registered", "")],
                    "registrationNumber": [reg_num],
                },
            })
            entities.append({
                "id": f"ch-ownership:{reg_num or corp_name}:{company_number}",
                "schema": "Ownership",
                "properties": {
                    "owner": [corp_name],
                    "asset": [company_number],
                    "role": [control_summary],
                },
            })

        return entities
