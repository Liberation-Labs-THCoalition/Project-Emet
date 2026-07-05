"""SEC EDGAR API adapter for Project Emet.

Provides async access to SEC's EDGAR Full-Text Search and Company Search:
  - Company search by name or CIK
  - Filing search (10-K, 10-Q, 8-K, 13-F, etc.)
  - Beneficial ownership (Schedules 13D/13G)
  - Insider trading (Forms 3, 4, 5)
  - Recent filings feed

Free. No API key. SEC requires a User-Agent header with contact info.

FtM entity conversion:
  - Filer          → Company/Person entity
  - Filing         → Document (with date, type, URL)
  - Insider trade  → Note linked to Person + Company

Reference: https://efts.sec.gov/LATEST/search-index?q=
           https://www.sec.gov/cgi-bin/browse-edgar
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_COMPANY_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
_FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"
_SEARCH_API = "https://efts.sec.gov/LATEST/search-index"
_CURRENT_EVENTS_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

# Atom feed namespace used by the EDGAR "getcurrent" firehose.
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# "4 - ACME CORP (0001234567) (Reporting)" -> form="4", company="ACME CORP", cik="0001234567"
# Note the separator is " - " (whitespace on both sides) rather than a bare "-", since form
# types like "8-K" or "SC 13D" may themselves contain hyphens/spaces.
_TITLE_RE = re.compile(r"^\s*(?P<form>.+?)\s+-\s+(?P<company>.+?)\s*\((?P<cik>\d{1,10})\)")
# The <summary> text is HTML that ElementTree unescapes into plain text containing literal
# tags, e.g. "<b>Filed:</b> 2024-03-15 <b>AccNo:</b> 0001234567-24-000001 ..." -- tolerate the
# tags being present or already stripped.
_FILED_RE = re.compile(r"Filed:\s*(?:</b>)?\s*(?P<date>\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_ACCNO_RE = re.compile(r"AccNo:\s*(?:</b>)?\s*(?P<acc>\d{10}-\d{2}-\d{6})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class EDGARConfig:
    """Configuration for SEC EDGAR API.

    No API key needed. SEC requires a User-Agent with company/email.
    """
    user_agent: str = "Emet-Investigation-Agent admin@example.com"
    timeout_seconds: float = 20.0
    max_results: int = 40


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class EDGARFiling:
    """A single SEC filing."""
    accession_number: str = ""
    filing_type: str = ""       # 10-K, 10-Q, 8-K, 13-F, SC 13D, etc.
    filing_date: str = ""
    company_name: str = ""
    cik: str = ""
    description: str = ""
    document_url: str = ""


@dataclass
class EDGARCompany:
    """A company/person entity from EDGAR."""
    cik: str = ""
    name: str = ""
    ticker: str = ""
    exchange: str = ""
    sic: str = ""
    sic_description: str = ""
    state_of_incorporation: str = ""
    fiscal_year_end: str = ""
    entity_type: str = ""       # e.g. "operating" or "individual"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class EDGARClient:
    """Async client for SEC EDGAR APIs.

    Uses the EDGAR Full-Text Search System (EFTS) and submissions API.
    """

    def __init__(self, config: EDGARConfig | None = None) -> None:
        self._config = config or EDGARConfig()
        self._headers = {
            "User-Agent": self._config.user_agent,
            "Accept": "application/json",
        }

    async def search_companies(
        self,
        query: str,
        limit: int = 0,
    ) -> list[EDGARCompany]:
        """Search for companies/filers by name."""
        max_results = limit or self._config.max_results
        url = f"https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2000-01-01&forms=10-K&from=0&size={max_results}"

        # Use the company tickers JSON for simpler search
        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            # Try company_tickers.json for exact matches
            resp = await client.get(
                "https://www.sec.gov/files/company_tickers.json",
            )
            resp.raise_for_status()
            tickers_data = resp.json()

        results: list[EDGARCompany] = []
        query_lower = query.lower()
        for _key, item in tickers_data.items():
            name = item.get("title", "")
            ticker = item.get("ticker", "")
            cik = str(item.get("cik_str", ""))
            if query_lower in name.lower() or query_lower == ticker.lower():
                results.append(EDGARCompany(
                    cik=cik.zfill(10),
                    name=name,
                    ticker=ticker,
                ))
            if len(results) >= max_results:
                break

        return results

    async def get_company_filings(
        self,
        cik: str,
        filing_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[EDGARFiling]:
        """Get recent filings for a company by CIK."""
        cik_padded = cik.zfill(10)
        url = f"{_SUBMISSIONS_URL}/CIK{cik_padded}.json"

        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        company_name = data.get("name", "")
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        filings: list[EDGARFiling] = []
        for i in range(min(len(forms), limit * 3)):  # scan more to filter
            form = forms[i] if i < len(forms) else ""
            if filing_types and form not in filing_types:
                continue

            acc = accessions[i] if i < len(accessions) else ""
            acc_clean = acc.replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""

            filings.append(EDGARFiling(
                accession_number=acc,
                filing_type=form,
                filing_date=dates[i] if i < len(dates) else "",
                company_name=company_name,
                cik=cik_padded,
                description=descriptions[i] if i < len(descriptions) else "",
                document_url=f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_clean}/{doc}" if doc else "",
            ))
            if len(filings) >= limit:
                break

        return filings

    async def search_filings(
        self,
        query: str,
        forms: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 0,
    ) -> list[EDGARFiling]:
        """Full-text search across SEC filings via EFTS."""
        max_results = limit or self._config.max_results
        params: dict[str, str] = {
            "q": f'"{query}"',
            "from": "0",
            "size": str(max_results),
        }
        if forms:
            params["forms"] = forms
        if date_from:
            params["startdt"] = date_from
        if date_to:
            params["enddt"] = date_to

        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        filings: list[EDGARFiling] = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            filings.append(EDGARFiling(
                filing_type=src.get("form_type", ""),
                filing_date=src.get("file_date", ""),
                company_name=src.get("display_names", [""])[0] if src.get("display_names") else "",
                cik=src.get("entity_id", ""),
                description=src.get("display_names", [""])[0] if src.get("display_names") else "",
            ))

        return filings

    async def fetch_recent_filings(
        self,
        forms: list[str] | None = None,
        count: int = 40,
    ) -> list[EDGARFiling]:
        """Fetch the real-time EDGAR 'getcurrent' Atom firehose of the latest filings
        across all filers, optionally filtered to specific form types.

        The `getcurrent` endpoint only accepts a single `type` param per request, so when
        multiple `forms` are given this fetches once per form and merges the results. If
        `forms` is None/empty, does a single fetch with type='' to get all forms.
        """
        form_list = forms or [""]

        all_filings: list[EDGARFiling] = []
        seen_accessions: set[str] = set()

        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            headers=self._headers,
        ) as client:
            for form in form_list:
                params = {
                    "action": "getcurrent",
                    "type": form,
                    "company": "",
                    "dateb": "",
                    "owner": "include",
                    "count": str(count),
                    "output": "atom",
                }
                try:
                    resp = await client.get(_CURRENT_EVENTS_URL, params=params)
                    resp.raise_for_status()
                    root = ET.fromstring(resp.text)
                except (httpx.HTTPError, ET.ParseError) as e:
                    logger.warning("EDGAR current-events fetch failed for form '%s': %s", form, e)
                    continue

                for entry in root.findall("atom:entry", _ATOM_NS):
                    filing = self._parse_current_event_entry(entry)
                    if filing is None:
                        continue
                    if filing.accession_number and filing.accession_number in seen_accessions:
                        continue
                    if filing.accession_number:
                        seen_accessions.add(filing.accession_number)
                    all_filings.append(filing)

        all_filings.sort(key=lambda f: f.filing_date, reverse=True)
        return all_filings[:count]

    @staticmethod
    def _parse_current_event_entry(entry: ET.Element) -> EDGARFiling | None:
        """Parse a single Atom <entry> from the EDGAR 'getcurrent' feed into an EDGARFiling."""
        title_el = entry.find("atom:title", _ATOM_NS)
        summary_el = entry.find("atom:summary", _ATOM_NS)
        title = (title_el.text or "") if title_el is not None else ""
        summary = (summary_el.text or "") if summary_el is not None else ""

        title_match = _TITLE_RE.match(title)
        if not title_match:
            return None

        form = title_match.group("form").strip()
        company_name = title_match.group("company").strip()
        cik = title_match.group("cik").strip().zfill(10)

        filed_match = _FILED_RE.search(summary)
        accno_match = _ACCNO_RE.search(summary)
        filing_date = filed_match.group("date") if filed_match else ""
        accession_number = accno_match.group("acc") if accno_match else ""

        # The Atom feed doesn't expose the primary document's filename, only the accession
        # number, so document_url points at the filing's index directory rather than a
        # specific primary document (matching get_company_filings when no doc is known).
        acc_clean = accession_number.replace("-", "")
        document_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/"
            if acc_clean
            else ""
        )

        return EDGARFiling(
            accession_number=accession_number,
            filing_type=form,
            filing_date=filing_date,
            company_name=company_name,
            cik=cik,
            description="",
            document_url=document_url,
        )

    # -----------------------------------------------------------------------
    # FtM conversion
    # -----------------------------------------------------------------------

    async def search_companies_ftm(
        self,
        query: str,
        limit: int = 0,
    ) -> dict[str, Any]:
        """Search companies and return FtM entities."""
        companies = await self.search_companies(query, limit=limit)
        entities = [self.company_to_ftm(c) for c in companies]
        return {
            "query": query,
            "result_count": len(entities),
            "entities": entities,
        }

    async def get_filings_ftm(
        self,
        cik: str,
        filing_types: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get filings and return FtM entities."""
        filings = await self.get_company_filings(cik, filing_types, limit)
        entities = [self.filing_to_ftm(f) for f in filings]
        return {
            "cik": cik,
            "filing_count": len(filings),
            "entities": entities,
        }

    async def fetch_recent_filings_ftm(
        self,
        forms: list[str] | None = None,
        count: int = 40,
    ) -> dict[str, Any]:
        """Fetch the real-time EDGAR firehose and return FtM entities."""
        filings = await self.fetch_recent_filings(forms=forms, count=count)
        entities = [self.filing_to_ftm(f) for f in filings]
        return {
            "forms": forms or ["all"],
            "filing_count": len(filings),
            "entities": entities,
        }

    @staticmethod
    def company_to_ftm(company: EDGARCompany) -> dict[str, Any]:
        """Convert an EDGAR company to FtM Company entity."""
        props: dict[str, list] = {
            "name": [company.name],
        }
        if company.cik:
            props["registrationNumber"] = [company.cik]
        if company.ticker:
            props["ticker"] = [company.ticker]
        if company.sic_description:
            props["sector"] = [company.sic_description]
        if company.state_of_incorporation:
            props["jurisdiction"] = [company.state_of_incorporation]

        return {
            "id": f"sec-edgar-{company.cik or company.name}",
            "schema": "Company",
            "properties": props,
            "datasets": ["sec_edgar"],
        }

    @staticmethod
    def filing_to_ftm(filing: EDGARFiling) -> dict[str, Any]:
        """Convert an EDGAR filing to FtM Document entity."""
        props: dict[str, list] = {
            "title": [f"{filing.filing_type}: {filing.company_name}"],
        }
        if filing.filing_date:
            props["date"] = [filing.filing_date]
        if filing.document_url:
            props["sourceUrl"] = [filing.document_url]
        if filing.description:
            props["summary"] = [filing.description]
        if filing.filing_type:
            props["type"] = [filing.filing_type]

        return {
            "id": f"sec-filing-{filing.accession_number or filing.filing_date}",
            "schema": "Document",
            "properties": props,
            "datasets": ["sec_edgar"],
        }
