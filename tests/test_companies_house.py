"""Tests for emet.ftm.external.companies_house."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.companies_house import (
    CompaniesHouseClient,
    CompaniesHouseConfig,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_SAMPLE_COMPANY = {
    "company_name": "SHELL PLC",
    "company_number": "04366849",
    "company_status": "active",
    "date_of_creation": "2002-02-05",
    "jurisdiction": "england-wales",
    "registered_office_address": {
        "address_line_1": "Shell Centre",
        "locality": "London",
        "postal_code": "SE1 7NA",
        "country": "United Kingdom",
    },
    "sic_codes": ["06100", "06200"],
}

_SAMPLE_SEARCH_RESULT = {
    "total_results": 1,
    "items": [
        {
            "title": "SHELL PLC",
            "company_number": "04366849",
            "company_status": "active",
            "address_snippet": "Shell Centre, London, SE1 7NA",
            "date_of_creation": "2002-02-05",
        }
    ],
}

_SAMPLE_OFFICER = {
    "name": "DOE, John Arthur",
    "officer_role": "director",
    "appointed_on": "2020-01-15",
    "nationality": "British",
    "date_of_birth": {"month": 6, "year": 1975},
}

_SAMPLE_PSC_INDIVIDUAL = {
    "kind": "individual-person-with-significant-control",
    "name": "Mr John Smith",
    "nationality": "British",
    "natures_of_control": [
        "ownership-of-shares-75-to-100-percent",
        "voting-rights-75-to-100-percent",
    ],
}

_SAMPLE_PSC_CORPORATE = {
    "kind": "corporate-entity-person-with-significant-control",
    "name": "Offshore Holdings Ltd",
    "identification": {
        "country_registered": "British Virgin Islands",
        "registration_number": "BVI12345",
    },
    "natures_of_control": [
        "ownership-of-shares-75-to-100-percent",
    ],
}


# ---------------------------------------------------------------------------
# FtM conversion tests
# ---------------------------------------------------------------------------


class TestCompanyToFtm:
    def test_basic_conversion(self):
        client = CompaniesHouseClient()
        entity = client.company_to_ftm(_SAMPLE_COMPANY)

        assert entity["schema"] == "Company"
        assert entity["properties"]["name"] == ["SHELL PLC"]
        assert entity["properties"]["registrationNumber"] == ["04366849"]
        assert entity["properties"]["jurisdiction"] == ["england-wales"]
        assert entity["properties"]["incorporationDate"] == ["2002-02-05"]
        assert "Shell Centre" in entity["properties"]["address"][0]

    def test_search_result_format(self):
        client = CompaniesHouseClient()
        item = _SAMPLE_SEARCH_RESULT["items"][0]
        entity = client.company_to_ftm(item)

        assert entity["schema"] == "Company"
        assert entity["properties"]["name"] == ["SHELL PLC"]
        assert entity["properties"]["address"] == ["Shell Centre, London, SE1 7NA"]

    def test_source_url_generated(self):
        client = CompaniesHouseClient()
        entity = client.company_to_ftm(_SAMPLE_COMPANY)
        url = entity["properties"]["sourceUrl"][0]
        assert "04366849" in url
        assert "company-information.service.gov.uk" in url

    def test_sic_codes_as_classification(self):
        client = CompaniesHouseClient()
        entity = client.company_to_ftm(_SAMPLE_COMPANY)
        assert entity["properties"]["classification"] == ["06100", "06200"]

    def test_default_jurisdiction_gb(self):
        company = {"company_name": "Test Ltd", "company_number": "12345"}
        entity = CompaniesHouseClient.company_to_ftm(company)
        assert entity["properties"]["jurisdiction"] == ["gb"]


class TestOfficerToFtm:
    def test_person_and_directorship(self):
        client = CompaniesHouseClient()
        person, directorship = client.officer_to_ftm(_SAMPLE_OFFICER, "04366849")

        assert person["schema"] == "Person"
        assert person["properties"]["name"] == ["DOE, John Arthur"]
        assert person["properties"]["nationality"] == ["British"]
        assert person["properties"]["birthDate"] == ["1975-06"]

        assert directorship["schema"] == "Directorship"
        assert directorship["properties"]["role"] == ["director"]
        assert directorship["properties"]["startDate"] == ["2020-01-15"]


class TestPscToFtm:
    def test_individual_psc(self):
        client = CompaniesHouseClient()
        entities = client.psc_to_ftm(_SAMPLE_PSC_INDIVIDUAL, "04366849")

        assert len(entities) == 2
        person = entities[0]
        ownership = entities[1]

        assert person["schema"] == "Person"
        assert person["properties"]["name"] == ["Mr John Smith"]
        assert ownership["schema"] == "Ownership"
        assert "75-to-100" in ownership["properties"]["role"][0]

    def test_corporate_psc(self):
        client = CompaniesHouseClient()
        entities = client.psc_to_ftm(_SAMPLE_PSC_CORPORATE, "04366849")

        assert len(entities) == 2
        corp = entities[0]
        ownership = entities[1]

        assert corp["schema"] == "Company"
        assert corp["properties"]["name"] == ["Offshore Holdings Ltd"]
        assert corp["properties"]["jurisdiction"] == ["British Virgin Islands"]
        assert corp["properties"]["registrationNumber"] == ["BVI12345"]
        assert ownership["schema"] == "Ownership"
        assert ownership["properties"]["owner"] == ["Offshore Holdings Ltd"]


# ---------------------------------------------------------------------------
# API call tests (mocked HTTP)
# ---------------------------------------------------------------------------


class TestCompaniesHouseAPI:
    @pytest.mark.asyncio
    async def test_search_companies(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _SAMPLE_SEARCH_RESULT
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CompaniesHouseClient()
            result = await client.search_companies("Shell")

        assert result["total_results"] == 1
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_search_companies_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _SAMPLE_SEARCH_RESULT
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CompaniesHouseClient()
            result = await client.search_companies_ftm("Shell")

        assert result["result_count"] == 1
        assert len(result["entities"]) == 1
        assert result["entities"][0]["schema"] == "Company"

    @pytest.mark.asyncio
    async def test_api_key_sent_as_basic_auth(self):
        config = CompaniesHouseConfig(api_key="test-key-123")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": []}
            mock_response.raise_for_status.return_value = None
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = CompaniesHouseClient(config=config)
            await client.search_companies("test")

            # Verify auth was passed to AsyncClient
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["auth"] == ("test-key-123", "")
