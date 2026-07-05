"""Tests for the CourtListener/RECAP API adapter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.courtlistener import (
    CourtListenerClient,
    CourtListenerConfig,
)


class TestCourtListenerConfig:
    def test_defaults(self):
        config = CourtListenerConfig()
        assert config.api_token == ""
        assert config.base_url == "https://www.courtlistener.com/api/rest/v4"
        assert config.timeout_seconds == 20.0
        assert config.max_results == 20

    def test_no_token_means_no_auth_header(self, monkeypatch):
        monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
        client = CourtListenerClient(CourtListenerConfig())
        assert "Authorization" not in client._headers

    def test_token_adds_auth_header(self):
        client = CourtListenerClient(CourtListenerConfig(api_token="abc123"))
        assert client._headers["Authorization"] == "Token abc123"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("COURTLISTENER_API_TOKEN", "env-token")
        client = CourtListenerClient(CourtListenerConfig())
        assert client._headers["Authorization"] == "Token env-token"


class TestDocketToFtM:
    def _full_docket(self) -> dict:
        return {
            "id": 123,
            "docket_number": "1:24-cv-00001",
            "case_name": "Acme Corp v. John Smith",
            "court": "cand",
            "date_filed": "2024-01-15",
            "date_terminated": None,
            "assigned_to_str": "Judge X",
            "parties": [
                {
                    "name": "Acme Corp",
                    "party_types": [{"party_type": "Plaintiff"}],
                },
                {
                    "name": "John Smith",
                    "party_types": [{"party_type": "Defendant"}],
                },
            ],
        }

    def test_full_docket_entities(self):
        entities = CourtListenerClient.docket_to_ftm(self._full_docket())

        # 1 Document + 2 parties + 2 Representation relationships
        assert len(entities) == 5

        doc = entities[0]
        assert doc["id"] == "courtlistener-docket:123"
        assert doc["schema"] == "Document"
        assert doc["properties"]["title"] == ["Acme Corp v. John Smith"]
        assert doc["properties"]["date"] == ["2024-01-15"]
        assert doc["properties"]["sourceUrl"] == ["https://www.courtlistener.com/docket/123/"]
        assert "cand" in doc["properties"]["summary"][0]
        assert "1:24-cv-00001" in doc["properties"]["summary"][0]

        parties = [e for e in entities if e["schema"] in ("Person", "Company")]
        assert len(parties) == 2

        company = next(e for e in parties if e["schema"] == "Company")
        assert company["properties"]["name"] == ["Acme Corp"]
        assert company["id"] == "courtlistener-party:acme-corp"

        person = next(e for e in parties if e["schema"] == "Person")
        assert person["properties"]["name"] == ["John Smith"]
        assert person["id"] == "courtlistener-party:john-smith"

        reps = [e for e in entities if e["schema"] == "Representation"]
        assert len(reps) == 2
        roles = {r["properties"]["role"][0] for r in reps}
        assert roles == {"Plaintiff", "Defendant"}
        for rep in reps:
            assert rep["properties"]["client"] == ["courtlistener-docket:123"]
            assert rep["properties"]["agent"][0].startswith("courtlistener-party:")

    def test_provenance_present(self):
        entities = CourtListenerClient.docket_to_ftm(self._full_docket())
        for entity in entities:
            prov = entity["_provenance"]
            assert prov["source"] == "courtlistener"
            assert prov["source_id"] == "123"
            assert prov["source_url"] == "https://www.courtlistener.com/docket/123/"
            assert prov["confidence"] == 0.9

    def test_docket_without_parties_key(self):
        docket = {
            "id": 456,
            "case_name": "In re Something",
            "date_filed": "2023-05-01",
            "court": "nysd",
            "docket_number": "1:23-cv-99999",
        }
        entities = CourtListenerClient.docket_to_ftm(docket)
        assert len(entities) == 1
        assert entities[0]["schema"] == "Document"
        assert entities[0]["id"] == "courtlistener-docket:456"

    def test_docket_with_empty_parties_list(self):
        docket = {"id": 789, "case_name": "Empty Parties Case", "parties": []}
        entities = CourtListenerClient.docket_to_ftm(docket)
        assert len(entities) == 1

    def test_party_missing_party_types_defaults_to_party_role(self):
        docket = {
            "id": 1,
            "case_name": "No Roles",
            "parties": [{"name": "Jane Doe"}],
        }
        entities = CourtListenerClient.docket_to_ftm(docket)
        reps = [e for e in entities if e["schema"] == "Representation"]
        assert len(reps) == 1
        assert reps[0]["properties"]["role"] == ["party"]

    def test_search_result_style_docket_camelcase(self):
        # search endpoint results use camelCase keys and no 'parties' key
        docket = {
            "docketNumber": "1:24-cv-00002",
            "caseName": "Search Result Case",
            "court": "cand",
            "dateFiled": "2024-02-01",
            "docket_absolute_url": "/docket/999/search-result-case/",
            "id": 999,
            "party": ["Party A", "Party B"],
        }
        entities = CourtListenerClient.docket_to_ftm(docket)
        # No 'parties' (plural, list-of-dicts) key present -> just the Document
        assert len(entities) == 1
        assert entities[0]["properties"]["title"] == ["Search Result Case"]
        assert entities[0]["properties"]["date"] == ["2024-02-01"]


class TestCourtListenerClient:
    @pytest.mark.asyncio
    async def test_search_dockets(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "count": 1,
            "results": [
                {
                    "docketNumber": "1:24-cv-00001",
                    "caseName": "Acme Corp v. John Smith",
                    "court": "cand",
                    "dateFiled": "2024-01-15",
                    "docket_absolute_url": "/docket/123/acme-corp-v-john-smith/",
                    "id": 123,
                    "party": ["Acme Corp", "John Smith"],
                }
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            results = await client.search_dockets("Acme Corp")

        assert len(results) == 1
        assert results[0]["caseName"] == "Acme Corp v. John Smith"
        assert results[0]["id"] == 123

    @pytest.mark.asyncio
    async def test_search_dockets_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "count": 1,
            "results": [
                {
                    "docketNumber": "1:24-cv-00001",
                    "caseName": "Acme Corp v. John Smith",
                    "court": "cand",
                    "dateFiled": "2024-01-15",
                    "id": 123,
                }
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            result = await client.search_dockets_ftm("Acme Corp")

        assert result["query"] == "Acme Corp"
        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Document"

    @pytest.mark.asyncio
    async def test_get_docket(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 123,
            "docket_number": "1:24-cv-00001",
            "case_name": "Acme Corp v. John Smith",
            "court": "cand",
            "date_filed": "2024-01-15",
            "date_terminated": None,
            "assigned_to_str": "Judge X",
            "parties": [
                {"name": "Acme Corp", "party_types": [{"party_type": "Plaintiff"}]},
                {"name": "John Smith", "party_types": [{"party_type": "Defendant"}]},
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            docket = await client.get_docket(123)

        assert docket["case_name"] == "Acme Corp v. John Smith"
        assert len(docket["parties"]) == 2

    @pytest.mark.asyncio
    async def test_get_docket_404_returns_empty_dict(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx_error_factory()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            docket = await client.get_docket(999999)

        assert docket == {}

    @pytest.mark.asyncio
    async def test_get_docket_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 123,
            "docket_number": "1:24-cv-00001",
            "case_name": "Acme Corp v. John Smith",
            "court": "cand",
            "date_filed": "2024-01-15",
            "parties": [
                {"name": "Acme Corp", "party_types": [{"party_type": "Plaintiff"}]},
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            result = await client.get_docket_ftm(123)

        assert result["docket_id"] == 123
        assert len(result["entities"]) == 3  # Document + 1 party + 1 Representation

    @pytest.mark.asyncio
    async def test_get_docket_ftm_when_docket_missing(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx_error_factory()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CourtListenerClient()
            result = await client.get_docket_ftm(999999)

        assert result["entities"] == []


def httpx_error_factory():
    import httpx

    request = httpx.Request("GET", "https://www.courtlistener.com/api/rest/v4/dockets/999999/")
    response = httpx.Response(404, request=request)

    def _raise():
        raise httpx.HTTPStatusError("Not Found", request=request, response=response)

    return _raise
