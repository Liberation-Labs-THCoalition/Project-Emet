"""Tests for SEC EDGAR API adapter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.edgar import (
    EDGARClient,
    EDGARConfig,
    EDGARCompany,
    EDGARFiling,
)


class TestEDGARConfig:
    def test_defaults(self):
        config = EDGARConfig()
        assert "Emet" in config.user_agent
        assert config.timeout_seconds == 20.0
        assert config.max_results == 40


class TestEDGARFtMConversion:
    def test_company_to_ftm(self):
        company = EDGARCompany(
            cik="0001234567",
            name="Acme Corp",
            ticker="ACME",
            sic_description="Manufacturing",
            state_of_incorporation="DE",
        )
        entity = EDGARClient.company_to_ftm(company)
        assert entity["schema"] == "Company"
        assert "Acme Corp" in entity["properties"]["name"]
        assert "ACME" in entity["properties"]["ticker"]
        assert entity["datasets"] == ["sec_edgar"]

    def test_filing_to_ftm(self):
        filing = EDGARFiling(
            accession_number="0001234567-24-000001",
            filing_type="10-K",
            filing_date="2024-03-15",
            company_name="Acme Corp",
            cik="0001234567",
            description="Annual report",
            document_url="https://www.sec.gov/Archives/edgar/data/0001234567/filing.htm",
        )
        entity = EDGARClient.filing_to_ftm(filing)
        assert entity["schema"] == "Document"
        assert "10-K" in entity["properties"]["title"][0]
        assert entity["properties"]["date"] == ["2024-03-15"]

    def test_company_to_ftm_minimal(self):
        company = EDGARCompany(cik="", name="Unknown")
        entity = EDGARClient.company_to_ftm(company)
        assert entity["schema"] == "Company"
        assert "registrationNumber" not in entity["properties"]


class TestEDGARClient:
    @pytest.mark.asyncio
    async def test_search_companies(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME CORP"},
            "1": {"cik_str": 7654321, "ticker": "FOO", "title": "FOO INDUSTRIES"},
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            results = await client.search_companies("acme")

        assert len(results) == 1
        assert results[0].name == "ACME CORP"
        assert results[0].ticker == "ACME"

    @pytest.mark.asyncio
    async def test_search_companies_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME CORP"},
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            result = await client.search_companies_ftm("acme")

        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Company"

    @pytest.mark.asyncio
    async def test_get_company_filings(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "ACME CORP",
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K", "10-Q"],
                    "filingDate": ["2024-03-15", "2024-02-01", "2024-01-10"],
                    "accessionNumber": ["001-24-000001", "001-24-000002", "001-24-000003"],
                    "primaryDocument": ["filing.htm", "report.htm", "quarterly.htm"],
                    "primaryDocDescription": ["Annual report", "Current report", "Quarterly"],
                },
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            filings = await client.get_company_filings("1234567", filing_types=["10-K"], limit=5)

        assert len(filings) == 1
        assert filings[0].filing_type == "10-K"
        assert filings[0].company_name == "ACME CORP"


class TestEDGARFederation:
    """Test that EDGAR is wired into federation."""

    def test_federation_includes_edgar(self):
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        fed = FederatedSearch(FederationConfig())
        assert "edgar" in fed._clients

    def test_federation_can_disable_edgar(self):
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        fed = FederatedSearch(FederationConfig(enable_edgar=False))
        assert "edgar" not in fed._clients
