"""Congressional financial disclosure adapter (STOCK Act).

Ingests U.S. congressional periodic transaction reports (PTRs) — the
legally-mandated disclosures of stock/security trades by members of
Congress, their spouses, and dependent children — and converts them
into FollowTheMoney entities for the investigation graph.

Two ingestion paths, in priority order:

1. **Sovereign bridge** — reuse the ``congress_scraper`` output from the
   Sovereign market-analysis pipeline if its ``transactions.json`` is on
   disk. That scraper already parses House Clerk PDFs + Senate eFD and
   does regex/Claude extraction. Set ``EMET_CONGRESS_DATA_DIR`` to point
   at the scraper's ``congress_data`` directory.

2. **Native House Clerk index** — an async pull of the House Clerk's
   annual financial-disclosure ZIP + XML index (the same public source
   the scraper uses), so Emet works standalone without the Sovereign repo.

Data sources (all public, all legal):
    - House Clerk financial disclosures: https://disclosures-clerk.house.gov
    - Senate eFD: https://efdsearch.senate.gov

FtM output:
    - ``Person`` for each member (publicRole = "Member of Congress")
    - ``Security`` for each traded asset (keyed by ticker)
    - ``Ownership`` linking member -> security (a disclosed financial
      interest), carrying the trade direction, amount range, and dates.

Members of Congress are public officials, so this source is squarely
within the "organizations and public figures" targeting policy.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CongressConfig:
    """Configuration for the congressional disclosure adapter."""

    # Directory holding the Sovereign congress_scraper output
    # (transactions.json / herd_signals.json). Empty = disabled.
    data_dir: str = ""
    # House Clerk public disclosure host.
    house_host: str = "https://disclosures-clerk.house.gov"
    timeout_seconds: float = 30.0
    user_agent: str = "Emet-Investigation-Agent (civic research)"

    @classmethod
    def from_env(cls) -> "CongressConfig":
        return cls(data_dir=os.getenv("EMET_CONGRESS_DATA_DIR", ""))


# ---------------------------------------------------------------------------
# FtM converters
# ---------------------------------------------------------------------------


def _member_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def member_to_ftm(name: str, chamber: str = "", state: str = "") -> dict[str, Any]:
    """Convert a member of Congress to an FtM ``Person`` entity."""
    props: dict[str, list[str]] = {"name": [name]}
    role = "Member of Congress"
    if chamber:
        role = f"U.S. {chamber.title()}"
    props["position"] = [role]
    props["country"] = ["us"]
    if state:
        props["state"] = [state]
    return {
        "id": f"congress:person:{_member_slug(name)}",
        "schema": "Person",
        "properties": props,
        "_provenance": _provenance(
            source="congress",
            source_id=_member_slug(name),
            source_url="https://disclosures-clerk.house.gov",
            confidence=0.95,
        ),
    }


def security_to_ftm(ticker: str, asset_name: str = "") -> dict[str, Any]:
    """Convert a traded security to an FtM ``Security`` entity."""
    ticker = ticker.upper().strip()
    props: dict[str, list[str]] = {"ticker": [ticker]}
    props["name"] = [asset_name] if asset_name else [ticker]
    return {
        "id": f"congress:asset:{ticker}",
        "schema": "Security",
        "properties": props,
        "_provenance": _provenance(
            source="congress",
            source_id=ticker,
            confidence=0.9,
        ),
    }


def transaction_to_ftm(tx: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one disclosed transaction into FtM entities.

    Returns ``[Person, Security, Ownership]``. The ``Ownership`` entity
    represents a *disclosed financial interest* (a trade), linking the
    member to the security, and carries the direction/amount/date as
    properties so the graph engine and timeline can consume it.
    """
    member = tx.get("member", "")
    ticker = (tx.get("ticker") or "").upper().strip()
    if not member or not ticker:
        return []

    chamber = tx.get("chamber", "")
    state = tx.get("state", "")
    direction = tx.get("direction", "")
    amount_range = tx.get("amount_range", "")
    tx_date = tx.get("transaction_date", "") or tx.get("filing_date", "")
    doc_id = tx.get("doc_id", "")
    owner_code = tx.get("owner", "")

    person = member_to_ftm(member, chamber, state)
    security = security_to_ftm(ticker, tx.get("asset_name", ""))

    summary = f"{direction or 'trade'} {ticker}"
    if amount_range:
        summary += f" ({amount_range})"
    if owner_code:
        summary += f" [owner: {owner_code}]"

    ownership_props: dict[str, list[str]] = {
        "owner": [person["id"]],
        "asset": [security["id"]],
        "role": [f"disclosed {direction or 'trade'}"],
        "summary": [summary],
    }
    if tx_date:
        ownership_props["date"] = [tx_date]

    interest_id = f"congress:interest:{_member_slug(member)}:{ticker}:{tx_date}:{doc_id}"
    ownership = {
        "id": interest_id,
        "schema": "Ownership",
        "properties": ownership_props,
        "_provenance": _provenance(
            source="congress",
            source_id=doc_id,
            source_url="https://efdsearch.senate.gov"
            if chamber == "senate"
            else "https://disclosures-clerk.house.gov",
            confidence=0.9,
        ),
        "_relationship": {"owner": person["id"], "asset": security["id"]},
    }
    return [person, security, ownership]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CongressAdapter:
    """Adapter for congressional financial disclosures."""

    def __init__(self, config: CongressConfig | None = None) -> None:
        self._config = config or CongressConfig()
        self._headers = {"User-Agent": self._config.user_agent}
        self._transactions_cache: list[dict[str, Any]] | None = None

    # -- Sovereign bridge ---------------------------------------------------

    def load_disclosures(self) -> list[dict[str, Any]]:
        """Load transactions from the Sovereign scraper output.

        Reads ``<data_dir>/transactions.json``. Returns an empty list
        (and logs) if the directory is unset or the file is missing —
        never raises, so federation degrades gracefully.
        """
        if self._transactions_cache is not None:
            return self._transactions_cache

        transactions: list[dict[str, Any]] = []
        data_dir = self._config.data_dir
        if data_dir:
            path = os.path.join(data_dir, "transactions.json")
            try:
                with open(path, encoding="utf-8") as fh:
                    transactions = json.load(fh)
            except FileNotFoundError:
                logger.info("Congress transactions.json not found at %s", path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read congress disclosures: %s", exc)

        self._transactions_cache = transactions
        return transactions

    def search_member(self, name: str, limit: int = 0) -> list[dict[str, Any]]:
        """Search loaded disclosures for a member by (fuzzy) name.

        Returns FtM entities (Person + Securities + Ownership interests)
        for every disclosed trade whose member name contains the query.
        """
        query = name.lower().strip()
        transactions = self.load_disclosures()

        matched = [
            tx for tx in transactions if query in (tx.get("member", "") or "").lower()
        ]
        if limit:
            matched = matched[:limit]

        entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tx in matched:
            for entity in transaction_to_ftm(tx):
                if entity["id"] not in seen:
                    seen.add(entity["id"])
                    entities.append(entity)
        return entities

    def holdings_summary(self, name: str) -> dict[str, Any]:
        """Summarise a member's disclosed holdings by ticker."""
        query = name.lower().strip()
        transactions = self.load_disclosures()
        by_ticker: dict[str, dict[str, Any]] = {}
        member_display = name
        for tx in transactions:
            if query not in (tx.get("member", "") or "").lower():
                continue
            member_display = tx.get("member", name)
            ticker = (tx.get("ticker") or "").upper()
            if not ticker:
                continue
            slot = by_ticker.setdefault(
                ticker,
                {"ticker": ticker, "buys": 0, "sells": 0, "trades": []},
            )
            if tx.get("direction") == "buy":
                slot["buys"] += 1
            elif tx.get("direction") == "sell":
                slot["sells"] += 1
            slot["trades"].append(
                {
                    "direction": tx.get("direction", ""),
                    "amount_range": tx.get("amount_range", ""),
                    "date": tx.get("transaction_date") or tx.get("filing_date", ""),
                }
            )
        return {
            "member": member_display,
            "ticker_count": len(by_ticker),
            "holdings": list(by_ticker.values()),
        }

    # -- Native House Clerk index ------------------------------------------

    async def fetch_house_index(self, year: int | None = None) -> list[dict[str, Any]]:
        """Async pull of the House Clerk PTR index for a year.

        Downloads the annual financial-disclosure ZIP and parses the XML
        index, returning PTR filing metadata (``P`` filing type only).
        This is the standalone path that works without the Sovereign repo.
        """
        year = year or datetime.now(timezone.utc).year
        url = f"{self._config.house_host}/public_disc/financial-pdfs/{year}FD.zip"

        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds, headers=self._headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content

        return self._parse_house_zip(content, year)

    @staticmethod
    def _parse_house_zip(content: bytes, year: int) -> list[dict[str, Any]]:
        """Parse a House Clerk FD ZIP into PTR filing dicts."""
        import zipfile

        filings: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_name = f"{year}FD.xml"
            if xml_name not in zf.namelist():
                logger.warning("House ZIP missing %s", xml_name)
                return filings
            tree = ET.parse(zf.open(xml_name))
            for member in tree.getroot():
                if member.findtext("FilingType", "") != "P":
                    continue
                first = member.findtext("First", "").strip()
                last = member.findtext("Last", "").strip()
                name = " ".join(p for p in [first, last] if p)
                filings.append(
                    {
                        "member": name,
                        "chamber": "house",
                        "state": member.findtext("StateDst", "")[:2],
                        "filing_date": member.findtext("FilingDate", ""),
                        "doc_id": member.findtext("DocID", ""),
                        "year": year,
                    }
                )
        return filings
