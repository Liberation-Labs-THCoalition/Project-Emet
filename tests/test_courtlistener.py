"""Tests for the CourtListener / RECAP adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from emet.ftm.external.courtlistener import (
    CourtListenerClient,
    CourtListenerConfig,
    docket_to_ftm,
    docket_with_parties_to_ftm,
    party_to_ftm,
)


class TestConverters:
    def test_docket_to_ftm(self):
        e = docket_to_ftm(
            {
                "id": 42,
                "case_name": "United States v. Acme Corp",
                "docket_number": "1:26-cv-001",
                "date_filed": "2026-01-01",
                "absolute_url": "/docket/42/",
            }
        )
        assert e["schema"] == "Document"
        assert e["id"] == "courtlistener:docket:42"
        assert e["properties"]["docketNumber"] == ["1:26-cv-001"]

    def test_party_org_vs_person(self):
        org = party_to_ftm("Acme Corp Inc")
        person = party_to_ftm("Jane Doe")
        assert org["schema"] == "Company"
        assert person["schema"] == "Person"

    def test_docket_with_parties(self):
        ents = docket_with_parties_to_ftm(
            {
                "id": 7,
                "case_name": "SEC v. Widgets LLC",
                "parties": [{"name": "Widgets LLC", "party_type": "Defendant"}],
            }
        )
        schemas = [e["schema"] for e in ents]
        assert "Document" in schemas
        assert "Company" in schemas
        assert "Interest" in schemas


class TestClient:
    @pytest.mark.asyncio
    async def test_search_dockets_ftm(self):
        client = CourtListenerClient(CourtListenerConfig())
        fake = {
            "results": [
                {
                    "id": 1,
                    "case_name": "US v. Shell Co",
                    "absolute_url": "/docket/1/",
                    "party": ["Shell Co", "John Roe"],
                }
            ]
        }
        with patch.object(client, "search_dockets", new=AsyncMock(return_value=fake)):
            result = await client.search_dockets_ftm("shell")
        ids = {e["id"] for e in result["entities"]}
        assert "courtlistener:docket:1" in ids
        # party names produce party entities
        assert any(e["schema"] in ("Company", "Person") for e in result["entities"])

    def test_token_header(self):
        client = CourtListenerClient(CourtListenerConfig(api_token="abc"))
        assert client._headers()["Authorization"] == "Token abc"
