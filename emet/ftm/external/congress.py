"""Congressional STOCK Act periodic transaction report (PTR) adapter.

Bridges two data paths for congressional stock trade disclosures:
  - "Sovereign" congress scraper output: a flat JSON list of PTR records at
    ``<data_dir>/transactions.json`` (produced by a separate scraper project
    that already parses House/Senate financial disclosure filings).
  - A standalone async House Clerk financial-disclosure index puller, used
    when the Sovereign data directory isn't present. Hits the real House
    Clerk endpoint pattern for the annual zipped XML filer index.

FtM entity conversion:
  - Member of Congress   → Person entity
  - Traded asset         → Security entity
  - Reported transaction → Ownership entity linking Person ↔ Security

Members of Congress are public figures by definition, so Person entities
are always emitted here — unlike e.g. FEC's individual-donor suppression,
no suppression logic is needed in this adapter.

Reference: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CongressConfig:
    """Configuration for the Congress STOCK Act adapter.

    ``data_dir`` points at the directory produced by the Sovereign congress
    scraper (containing ``transactions.json``). Falls back to the
    ``EMET_CONGRESS_DATA_DIR`` env var, then to ``"congress_data"``, when
    left empty.
    """
    data_dir: str = ""
    house_index_url: str = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
    timeout_seconds: float = 20.0

    def resolved_data_dir(self) -> str:
        return self.data_dir or os.getenv("EMET_CONGRESS_DATA_DIR", "congress_data")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CongressAdapter:
    """Adapter over congressional STOCK Act periodic transaction reports."""

    def __init__(self, config: CongressConfig | None = None) -> None:
        self._config = config or CongressConfig()

    # -----------------------------------------------------------------------
    # Sovereign scraper output (transactions.json)
    # -----------------------------------------------------------------------

    def load_disclosures(self) -> list[dict[str, Any]]:
        """Read ``<data_dir>/transactions.json``.

        Returns an empty list (never raises) if the directory/file doesn't
        exist or the JSON is malformed.
        """
        data_dir = self._config.resolved_data_dir()
        path = Path(data_dir) / "transactions.json"

        if not path.exists():
            logger.debug("Congress data file not found: %s", path)
            return []

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load congress disclosures from %s: %s", path, exc)
            return []

        if not isinstance(data, list):
            logger.warning("Congress disclosures file %s did not contain a JSON list", path)
            return []

        return data

    def search_member(self, name: str, limit: int = 20) -> list[dict[str, Any]]:
        """Case-insensitive substring match against the ``member`` field."""
        query = name.lower()
        results: list[dict[str, Any]] = []
        for record in self.load_disclosures():
            member = str(record.get("member", ""))
            if query in member.lower():
                results.append(record)
            if len(results) >= limit:
                break
        return results

    def holdings_summary(self, ticker: str) -> dict[str, Any]:
        """Aggregate all disclosures for a ticker.

        Buys count positive toward ``net_amount_low``/``net_amount_high``,
        sells count negative. ``exchange`` and other directions are ignored
        for the net amount but still counted toward member/date tracking.
        """
        ticker_upper = ticker.upper()
        buy_count = 0
        sell_count = 0
        members: list[str] = []
        net_low = 0
        net_high = 0
        most_recent: str | None = None
        most_recent_parsed: datetime | None = None

        for record in self.load_disclosures():
            if str(record.get("ticker", "")).upper() != ticker_upper:
                continue

            direction = str(record.get("direction", "")).lower()
            amount_low = record.get("amount_low") or 0
            amount_high = record.get("amount_high") or 0

            if direction == "buy" or direction == "purchase":
                buy_count += 1
                net_low += amount_low
                net_high += amount_high
            elif direction == "sell":
                sell_count += 1
                net_low -= amount_low
                net_high -= amount_high

            member = record.get("member", "")
            if member and member not in members:
                members.append(member)

            tx_date = record.get("transaction_date", "")
            parsed = _parse_date(tx_date)
            if parsed and (most_recent_parsed is None or parsed > most_recent_parsed):
                most_recent_parsed = parsed
                most_recent = tx_date

        return {
            "ticker": ticker_upper,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "members": members,
            "net_amount_low": net_low,
            "net_amount_high": net_high,
            "most_recent_transaction_date": most_recent,
        }

    # -----------------------------------------------------------------------
    # House Clerk financial-disclosure index (fallback source)
    # -----------------------------------------------------------------------

    async def fetch_house_index(self, year: int | None = None) -> list[dict[str, Any]]:
        """Fetch the House Clerk annual financial-disclosure ZIP index.

        The real endpoint returns a ZIP of XML filer-index entries. This
        adapter doesn't implement full ZIP/XML parsing — it fetches the
        bytes and, if the response looks like a ZIP, returns a single
        summary entry so callers know data was retrieved. On any network
        error, logs a warning and returns [] (never raises), matching this
        repo's pattern of graceful degradation on source failure.
        """
        resolved_year = year or datetime.now().year
        url = self._config.house_index_url.format(year=resolved_year)
        headers = {
            "User-Agent": "Emet-Investigation-Agent admin@example.com",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._config.timeout_seconds,
                headers=headers,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content = resp.content
                content_type = resp.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch House Clerk index for %s: %s", resolved_year, exc)
            return []

        looks_like_zip = "zip" in content_type.lower() or content[:2] == b"PK"
        if not looks_like_zip:
            logger.warning(
                "House Clerk index response for %s did not look like a ZIP", resolved_year
            )
            return []

        return [
            {
                "note": "zip_index_fetched",
                "year": resolved_year,
                "size_bytes": len(content),
            }
        ]

    # -----------------------------------------------------------------------
    # FtM conversion
    # -----------------------------------------------------------------------

    def search_member_ftm(self, name: str) -> dict[str, Any]:
        """search_member() results, flattened into FtM entities."""
        records = self.search_member(name)
        entities: list[dict[str, Any]] = []
        for record in records:
            entities.extend(self.disclosure_to_ftm(record))
        return {
            "query": name,
            "result_count": len(records),
            "entities": entities,
        }

    def holdings_summary_ftm(self, ticker: str) -> dict[str, Any]:
        """holdings_summary() wrapped with an FtM Security entity."""
        summary = self.holdings_summary(ticker)
        security_entity = {
            "id": f"congress-security:{summary['ticker']}",
            "schema": "Security",
            "properties": {
                "name": [summary["ticker"]],
                "ticker": [summary["ticker"]],
            },
            "_provenance": _provenance(
                source="congress_stock_act",
                source_id=summary["ticker"],
                source_url="https://disclosures-clerk.house.gov/public_disc/",
                confidence=0.9,
            ),
        }
        return {
            **summary,
            "security_entity": security_entity,
        }

    @staticmethod
    def disclosure_to_ftm(record: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert one transactions.json record into 3 FtM entities.

        Returns [Person, Security, Ownership].
        """
        member = record.get("member", "")
        chamber = str(record.get("chamber", "")).lower()
        ticker = record.get("ticker", "")
        asset_name = record.get("asset_name", "")
        direction = record.get("direction", "")
        amount_range = record.get("amount_range", "")
        transaction_date = record.get("transaction_date", "")
        doc_id = record.get("doc_id", "")
        state = record.get("state", "")

        person_id = f"congress-member:{_slugify(member)}"
        security_key = ticker or asset_name
        security_id = f"congress-security:{security_key}"
        ownership_id = f"congress-ownership:{doc_id}-{ticker}"

        if chamber == "senate":
            position = "U.S. Senate"
        elif chamber == "house":
            position = "U.S. House of Representatives"
        else:
            position = chamber

        person_props: dict[str, list[str]] = {}
        if member:
            person_props["name"] = [member]
        if position:
            person_props["position"] = [position]
        if state:
            person_props["description"] = [f"State: {state}"]

        person_entity = {
            "id": person_id,
            "schema": "Person",
            "properties": person_props,
            "_provenance": _provenance(
                source="congress_stock_act",
                source_id=doc_id,
                source_url="https://disclosures-clerk.house.gov/public_disc/",
                confidence=0.9,
            ),
        }

        security_props: dict[str, list[str]] = {}
        name_value = asset_name or ticker
        if name_value:
            security_props["name"] = [name_value]
        if ticker:
            security_props["ticker"] = [ticker]

        security_entity = {
            "id": security_id,
            "schema": "Security",
            "properties": security_props,
            "_provenance": _provenance(
                source="congress_stock_act",
                source_id=doc_id,
                source_url="https://disclosures-clerk.house.gov/public_disc/",
                confidence=0.9,
            ),
        }

        ownership_props: dict[str, list[str]] = {
            "owner": [person_id],
            "asset": [security_id],
        }
        if direction:
            ownership_props["role"] = [direction]
        normalized_date = _parse_date(transaction_date)
        if normalized_date:
            ownership_props["startDate"] = [normalized_date.strftime("%Y-%m-%d")]
        if amount_range:
            ownership_props["summary"] = [amount_range]

        ownership_entity = {
            "id": ownership_id,
            "schema": "Ownership",
            "properties": ownership_props,
            "_provenance": _provenance(
                source="congress_stock_act",
                source_id=doc_id,
                source_url="https://disclosures-clerk.house.gov/public_disc/",
                confidence=0.9,
            ),
        }

        return [person_entity, security_entity, ownership_entity]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Lowercase, whitespace/punctuation → hyphens, for stable entity ids."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def _parse_date(value: str) -> datetime | None:
    """Leniently parse MM/DD/YYYY dates, tolerating single-digit month/day."""
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
