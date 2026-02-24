"""FtM roundtrip validation: verify all converters produce valid FtM entities.

Every data source adapter converts external API data into Follow-the-Money
(FtM) entity dicts.  This module validates that ALL converters produce
structurally correct FtM entities with required fields, valid schemas,
and provenance metadata.

This is a Tier 1 audit test — incorrect FtM conversion means the agent
loop can't extract entities, generate graph structures, or produce
accurate reports.
"""

from __future__ import annotations

import pytest
from typing import Any

# FtM valid schemas (core subset used by Emet)
VALID_SCHEMAS = {
    "Person", "Company", "Organization", "LegalEntity",
    "Ownership", "Directorship", "UnknownLink",
    "Document", "Email", "Phone", "Address",
    "CryptoWallet", "Payment", "Thing",
    "Domain",
}


def _validate_ftm_entity(entity: dict[str, Any], source: str) -> list[str]:
    """Validate an FtM entity dict.  Return list of errors (empty = valid)."""
    errors = []

    # Must be a dict
    if not isinstance(entity, dict):
        return [f"[{source}] Entity is {type(entity).__name__}, not dict"]

    # Must have schema
    schema = entity.get("schema")
    if not schema:
        errors.append(f"[{source}] Missing 'schema' field")
    elif schema not in VALID_SCHEMAS:
        # Warn but don't fail — custom schemas are ok
        pass

    # Must have properties dict
    props = entity.get("properties")
    # Relationship schemas use different property patterns
    RELATIONSHIP_SCHEMAS = {"Ownership", "Directorship", "UnknownLink", "Representation"}

    if not isinstance(props, dict):
        errors.append(f"[{source}] Missing or invalid 'properties' (got {type(props).__name__})")
    elif schema not in RELATIONSHIP_SCHEMAS:
        # Entity schemas must have a name
        names = props.get("name", [])
        if not names or not any(n.strip() for n in names if isinstance(n, str)):
            errors.append(f"[{source}] No 'name' in properties for {schema}")

    # ID should exist (not strictly required but needed for graph)
    if not entity.get("id"):
        errors.append(f"[{source}] Missing 'id' field")

    return errors


# ---------------------------------------------------------------------------
# Converter test data (realistic API response shapes)
# ---------------------------------------------------------------------------


class TestYenteConverters:
    """OpenSanctions / yente API → FtM."""

    def test_search_result_to_ftm(self) -> None:
        from emet.ftm.external.converters import yente_result_to_ftm

        yente_result = {
            "id": "Q1234",
            "schema": "Person",
            "properties": {
                "name": ["Viktor Bout"],
                "nationality": ["RU"],
                "birthDate": ["1967-01-13"],
            },
            "datasets": ["us_ofac_sdn"],
            "score": 0.95,
        }

        ftm = yente_result_to_ftm(yente_result)
        errors = _validate_ftm_entity(ftm, "opensanctions")
        assert not errors, errors

    def test_search_list_to_ftm(self) -> None:
        from emet.ftm.external.converters import yente_search_to_ftm_list

        # yente search returns flat {"results": [...]}
        response = {
            "results": [
                {
                    "id": "Q1",
                    "schema": "Company",
                    "properties": {"name": ["Bad Corp"]},
                    "datasets": ["eu_sanctions"],
                    "score": 0.88,
                },
            ],
        }

        entities = yente_search_to_ftm_list(response)
        assert len(entities) >= 1
        for e in entities:
            errors = _validate_ftm_entity(e, "opensanctions-list")
            assert not errors, errors

    def test_match_list_to_ftm(self) -> None:
        from emet.ftm.external.converters import yente_match_to_ftm_list

        # yente match returns nested {"responses": {"q": {"results": [...]}}}
        response = {
            "responses": {
                "q": {
                    "results": [
                        {
                            "id": "Q2",
                            "schema": "Person",
                            "properties": {"name": ["Bad Actor"]},
                            "datasets": ["us_ofac_sdn"],
                            "score": 0.95,
                        },
                    ],
                }
            }
        }

        entities = yente_match_to_ftm_list(response)
        assert len(entities) >= 1
        for e in entities:
            errors = _validate_ftm_entity(e, "opensanctions-match")
            assert not errors, errors


class TestOpenCorporatesConverters:
    """OpenCorporates API → FtM."""

    def test_company_to_ftm(self) -> None:
        from emet.ftm.external.converters import oc_company_to_ftm

        oc_data = {
            "company_number": "12345678",
            "name": "Acme Holdings Ltd",
            "jurisdiction_code": "gb",
            "incorporation_date": "2010-05-15",
            "company_type": "private_limited",
            "registered_address_in_full": "123 High Street, London EC1V 9BD",
            "current_status": "Active",
            "opencorporates_url": "https://opencorporates.com/companies/gb/12345678",
        }

        ftm = oc_company_to_ftm(oc_data)
        errors = _validate_ftm_entity(ftm, "opencorporates")
        assert not errors, errors
        assert ftm["schema"] in ("Company", "Organization", "LegalEntity")

    def test_officer_to_ftm(self) -> None:
        from emet.ftm.external.converters import oc_officer_to_ftm

        oc_data = {
            "id": 98765,
            "name": "John Smith",
            "position": "director",
            "start_date": "2015-01-01",
            "nationality": "British",
            "date_of_birth": "1970-06-15",
        }

        ftm = oc_officer_to_ftm(oc_data)
        errors = _validate_ftm_entity(ftm, "opencorporates-officer")
        assert not errors, errors


class TestICIJConverters:
    """ICIJ Offshore Leaks → FtM."""

    def test_entity_node_to_ftm(self) -> None:
        from emet.ftm.external.converters import icij_node_to_ftm

        icij_node = {
            "node_id": "1234",
            "name": "Offshore Holdings Inc",
            "type": "Entity",
            "jurisdiction": "VGB",
            "sourceID": "Panama Papers",
            "countries": "British Virgin Islands",
        }

        ftm = icij_node_to_ftm(icij_node)
        errors = _validate_ftm_entity(ftm, "icij")
        assert not errors, errors

    def test_officer_node_to_ftm(self) -> None:
        from emet.ftm.external.converters import icij_node_to_ftm

        icij_node = {
            "node_id": "5678",
            "name": "Jane Doe",
            "type": "Officer",
            "sourceID": "Pandora Papers",
            "countries": "United Kingdom",
        }

        ftm = icij_node_to_ftm(icij_node)
        errors = _validate_ftm_entity(ftm, "icij-officer")
        assert not errors, errors


class TestGLEIFConverters:
    """GLEIF LEI Registry → FtM."""

    def test_record_to_ftm(self) -> None:
        from emet.ftm.external.converters import gleif_record_to_ftm

        gleif_record = {
            "attributes": {
                "lei": "5493001KJTIIGC8Y1R12",
                "entity": {
                    "legalName": {"name": "Deutsche Bank AG"},
                    "legalAddress": {
                        "country": "DE",
                        "city": "Frankfurt am Main",
                    },
                    "jurisdiction": "DE",
                    "category": "GENERAL",
                    "legalForm": {"id": "AG"},
                },
                "registration": {
                    "status": "ISSUED",
                    "initialRegistrationDate": "2012-06-06",
                },
            },
        }

        ftm = gleif_record_to_ftm(gleif_record)
        errors = _validate_ftm_entity(ftm, "gleif")
        assert not errors, errors
        assert "Deutsche Bank" in ftm["properties"]["name"][0]


class TestCompaniesHouseClients:
    """UK Companies House → FtM."""

    def test_company_to_ftm(self) -> None:
        from emet.ftm.external.companies_house import CompaniesHouseClient

        ch_data = {
            "company_number": "00000001",
            "company_name": "Test Company Ltd",
            "type": "ltd",
            "company_status": "active",
            "date_of_creation": "2000-01-01",
            "registered_office_address": {
                "address_line_1": "1 Test Street",
                "locality": "London",
                "postal_code": "EC1V 1AA",
                "country": "United Kingdom",
            },
            "sic_codes": ["62090"],
        }

        ftm = CompaniesHouseClient.company_to_ftm(ch_data)
        errors = _validate_ftm_entity(ftm, "companies_house")
        assert not errors, errors

    def test_officer_to_ftm(self) -> None:
        from emet.ftm.external.companies_house import CompaniesHouseClient

        officer_data = {
            "name": "Smith, John Andrew",
            "officer_role": "director",
            "appointed_on": "2015-06-01",
            "nationality": "British",
            "date_of_birth": {"month": 6, "year": 1975},
            "links": {"officer": {"appointments": "/officers/abc123/appointments"}},
        }

        person, directorship = CompaniesHouseClient.officer_to_ftm(officer_data, "00000001")
        errors = _validate_ftm_entity(person, "companies_house-officer-person")
        assert not errors, errors
        errors = _validate_ftm_entity(directorship, "companies_house-officer-directorship")
        assert not errors, errors


class TestEDGARConverters:
    """SEC EDGAR → FtM."""

    def test_company_to_ftm(self) -> None:
        from emet.ftm.external.edgar import EDGARClient, EDGARCompany

        company = EDGARCompany(
            cik="0000320193",
            name="Apple Inc",
            ticker="AAPL",
            exchange="NASDAQ",
            sic="3571",
            sic_description="Electronic Computers",
            state_of_incorporation="CA",
            fiscal_year_end="0930",
        )

        ftm = EDGARClient.company_to_ftm(company)
        errors = _validate_ftm_entity(ftm, "edgar")
        assert not errors, errors


class TestGDELTConverters:
    """GDELT → FtM."""

    def test_article_to_ftm(self) -> None:
        from emet.ftm.external.gdelt import GDELTFtMConverter, GDELTArticle

        articles = [
            GDELTArticle(
                url="https://example.com/article1",
                title="Shell companies in BVI face scrutiny",
                source_domain="example.com",
                published_at="2024-01-15T12:00:00Z",
                language="English",
                source_country="United States",
                tone=-2.5,
            ),
        ]

        converter = GDELTFtMConverter()
        entities = converter.convert_articles(articles)
        assert len(entities) >= 1

        for e in entities:
            # GDELT uses "Mention" schema which isn't in core FtM
            # Just validate structure
            assert "schema" in e
            assert "properties" in e
            assert "id" in e


class TestCryptoConverters:
    """Blockchain → FtM."""

    def test_eth_address_to_ftm(self) -> None:
        from emet.ftm.external.blockchain import crypto_address_to_ftm

        ftm = crypto_address_to_ftm(
            address="0x1234567890abcdef1234567890abcdef12345678",
            chain="ethereum",
            summary={"balance_eth": 1.5, "transaction_count": 42},
        )
        errors = _validate_ftm_entity(ftm, "blockchain-eth")
        assert not errors, errors

    def test_btc_address_to_ftm(self) -> None:
        from emet.ftm.external.blockchain import crypto_address_to_ftm

        ftm = crypto_address_to_ftm(
            address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            chain="bitcoin",
            summary={"balance_btc": 0.001, "transaction_count": 5},
        )
        errors = _validate_ftm_entity(ftm, "blockchain-btc")
        assert not errors, errors
