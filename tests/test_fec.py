"""Tests for OpenFEC campaign-finance API adapter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.fec import FECClient, FECConfig


class TestFECConfig:
    def test_defaults(self):
        config = FECConfig()
        assert config.base_url == "https://api.open.fec.gov/v1"
        assert config.timeout_seconds == 20.0
        assert config.max_results == 20
        assert config.suppress_individual_donors is True
        assert config.api_key == ""

    def test_resolved_api_key_falls_back_to_demo_key(self, monkeypatch):
        monkeypatch.delenv("FEC_API_KEY", raising=False)
        config = FECConfig()
        assert config.resolved_api_key() == "DEMO_KEY"

    def test_resolved_api_key_uses_env(self, monkeypatch):
        monkeypatch.setenv("FEC_API_KEY", "env-key-123")
        config = FECConfig()
        assert config.resolved_api_key() == "env-key-123"

    def test_resolved_api_key_prefers_explicit(self, monkeypatch):
        monkeypatch.setenv("FEC_API_KEY", "env-key-123")
        config = FECConfig(api_key="explicit-key")
        assert config.resolved_api_key() == "explicit-key"


class TestFECFtMConversion:
    def test_candidate_to_ftm(self):
        candidate = {
            "candidate_id": "P00000001",
            "name": "SMITH, JANE",
            "party": "DEM",
            "office": "P",
            "state": "US",
            "incumbent_challenge_full": "Incumbent",
            "election_years": [2024, 2026],
        }
        entity = FECClient.candidate_to_ftm(candidate)
        assert entity["id"] == "fec-candidate:P00000001"
        assert entity["schema"] == "Person"
        assert entity["properties"]["name"] == ["SMITH, JANE"]
        assert entity["properties"]["political"] == ["DEM"]
        assert "P" in entity["properties"]["position"][0]
        assert "2024" in entity["properties"]["notes"][0]
        assert entity["_provenance"]["source"] == "fec"
        assert entity["_provenance"]["source_id"] == "P00000001"

    def test_candidate_to_ftm_minimal(self):
        candidate = {"candidate_id": "P00000002", "name": "DOE, JOHN"}
        entity = FECClient.candidate_to_ftm(candidate)
        assert entity["schema"] == "Person"
        assert entity["properties"]["name"] == ["DOE, JOHN"]
        assert "position" not in entity["properties"]
        assert "notes" not in entity["properties"]

    def test_committee_to_ftm(self):
        committee = {
            "committee_id": "C00000001",
            "name": "FRIENDS OF JANE SMITH",
            "committee_type_full": "Presidential",
            "designation_full": "Principal campaign committee",
            "state": "US",
            "treasurer_name": "Bob Treasurer",
        }
        entity = FECClient.committee_to_ftm(committee)
        assert entity["id"] == "fec-committee:C00000001"
        assert entity["schema"] == "Organization"
        assert entity["properties"]["name"] == ["FRIENDS OF JANE SMITH"]
        assert entity["properties"]["legalForm"] == ["Presidential"]
        assert "Bob Treasurer" in entity["properties"]["notes"][0]
        assert entity["_provenance"]["source"] == "fec"

    def test_committee_to_ftm_minimal(self):
        committee = {"committee_id": "C00000002", "name": "SOME PAC"}
        entity = FECClient.committee_to_ftm(committee)
        assert entity["schema"] == "Organization"
        assert "legalForm" not in entity["properties"]

    def test_contribution_to_ftm_suppressed_by_default(self):
        contribution = {
            "sub_id": "123456789",
            "contributor_name": "DOE, JOHN",
            "contributor_employer": "ACME INC",
            "contributor_occupation": "ENGINEER",
            "contribution_receipt_amount": 500.0,
            "contribution_receipt_date": "2024-03-01",
            "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
        }
        entity = FECClient.contribution_to_ftm(contribution)
        assert entity is None

    def test_contribution_to_ftm_suppressed_explicit_true(self):
        contribution = {
            "sub_id": "123456789",
            "contributor_name": "DOE, JOHN",
            "contribution_receipt_amount": 500.0,
            "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
        }
        entity = FECClient.contribution_to_ftm(contribution, suppress_individual=True)
        assert entity is None

    def test_contribution_to_ftm_unsuppressed(self):
        contribution = {
            "sub_id": "123456789",
            "contributor_name": "DOE, JOHN",
            "contributor_employer": "ACME INC",
            "contributor_occupation": "ENGINEER",
            "contribution_receipt_amount": 500.0,
            "contribution_receipt_date": "2024-03-01",
            "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
        }
        entity = FECClient.contribution_to_ftm(contribution, suppress_individual=False)
        assert entity is not None
        assert entity["schema"] == "Payment"
        assert entity["id"] == "fec-contribution:123456789"
        assert entity["properties"]["amountUsd"] == ["500.0"]
        assert entity["properties"]["date"] == ["2024-03-01"]
        assert "ACME INC" in entity["properties"]["notes"][0]
        assert entity["_relationship_hints"]["payer_name"] == "DOE, JOHN"
        assert entity["_relationship_hints"]["beneficiary_id"] == "fec-committee:C00000001"
        assert entity["_relationship_hints"]["beneficiary_name"] == "FRIENDS OF JANE SMITH"
        assert entity["_provenance"]["source"] == "fec"

    def test_contribution_to_ftm_unsuppressed_no_sub_id(self):
        contribution = {
            "contributor_name": "DOE, JOHN",
            "contribution_receipt_amount": 250.0,
            "committee": {"committee_id": "C00000009", "name": "SOME PAC"},
        }
        entity = FECClient.contribution_to_ftm(contribution, suppress_individual=False)
        assert entity is not None
        assert entity["id"] == "fec-contribution:DOE, JOHN-C00000009"


class TestFECClient:
    @pytest.mark.asyncio
    async def test_search_candidates(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "candidate_id": "P00000001",
                    "name": "SMITH, JANE",
                    "party": "DEM",
                    "office": "P",
                    "state": "US",
                    "incumbent_challenge_full": "Incumbent",
                    "election_years": [2024],
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            results = await client.search_candidates("smith")

        assert len(results) == 1
        assert results[0]["name"] == "SMITH, JANE"

        call_args = mock_client.get.call_args
        assert "candidates/search" in call_args.args[0]
        params = call_args.kwargs["params"]
        assert "api_key" in params
        assert params["q"] == "smith"

    @pytest.mark.asyncio
    async def test_search_committees(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "committee_id": "C00000001",
                    "name": "FRIENDS OF JANE SMITH",
                    "committee_type_full": "Presidential",
                    "designation_full": "Principal campaign committee",
                    "state": "US",
                    "treasurer_name": "Bob Treasurer",
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            results = await client.search_committees("friends of jane")

        assert len(results) == 1
        assert results[0]["committee_id"] == "C00000001"

        call_args = mock_client.get.call_args
        assert "committees" in call_args.args[0]
        params = call_args.kwargs["params"]
        assert "api_key" in params

    @pytest.mark.asyncio
    async def test_get_contributions(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "contributor_name": "DOE, JOHN",
                    "contributor_employer": "ACME INC",
                    "contributor_occupation": "ENGINEER",
                    "contribution_receipt_amount": 500.0,
                    "contribution_receipt_date": "2024-03-01",
                    "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
                    "sub_id": "123456789",
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            results = await client.get_contributions(committee_id="C00000001")

        assert len(results) == 1
        assert results[0]["sub_id"] == "123456789"

        call_args = mock_client.get.call_args
        assert "schedules/schedule_a" in call_args.args[0]
        params = call_args.kwargs["params"]
        assert params["committee_id"] == "C00000001"
        assert "api_key" in params

    @pytest.mark.asyncio
    async def test_search_candidates_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"candidate_id": "P00000001", "name": "SMITH, JANE", "party": "DEM"},
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            result = await client.search_candidates_ftm("smith")

        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Person"
        assert result["entities"][0]["id"] == "fec-candidate:P00000001"

    @pytest.mark.asyncio
    async def test_search_committees_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            result = await client.search_committees_ftm("friends of jane")

        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Organization"
        assert result["entities"][0]["id"] == "fec-committee:C00000001"

    @pytest.mark.asyncio
    async def test_get_contributions_ftm_suppressed_by_default(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "contributor_name": "DOE, JOHN",
                    "contribution_receipt_amount": 500.0,
                    "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
                    "sub_id": "123456789",
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient()
            result = await client.get_contributions_ftm(committee_id="C00000001")

        assert result["result_count"] == 0
        assert result["entities"] == []

    @pytest.mark.asyncio
    async def test_get_contributions_ftm_unsuppressed(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "contributor_name": "DOE, JOHN",
                    "contribution_receipt_amount": 500.0,
                    "committee": {"committee_id": "C00000001", "name": "FRIENDS OF JANE SMITH"},
                    "sub_id": "123456789",
                },
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = FECClient(FECConfig(suppress_individual_donors=False))
            result = await client.get_contributions_ftm(committee_id="C00000001")

        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Payment"
        assert result["entities"][0]["_relationship_hints"]["payer_name"] == "DOE, JOHN"
