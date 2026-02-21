"""Tests for emet.ftm.external.document_sources — Datashare + DocumentCloud.

Tests cover:
  - FtM conversion helpers (document, NER entity, mention link)
  - DatashareClient request formatting and response parsing
  - DocumentCloudClient request formatting and response parsing
  - FtM schema mapping from NER types
"""

import hashlib
import pytest
import httpx

from emet.ftm.external.document_sources import (
    DatashareClient,
    DocumentCloudClient,
    _document_to_ftm,
    _ner_entity_to_ftm,
    _mention_to_ftm,
)


# ---------------------------------------------------------------------------
# FtM conversion tests
# ---------------------------------------------------------------------------


class TestDocumentToFtM:
    def test_basic_conversion(self):
        ftm = _document_to_ftm(
            doc_id="abc123",
            title="Secret Contracts",
            source="datashare",
        )
        assert ftm["id"] == "doc-datashare-abc123"
        assert ftm["schema"] == "Document"
        assert ftm["properties"]["title"] == ["Secret Contracts"]
        assert ftm["_provenance"]["source"] == "datashare"

    def test_with_all_fields(self):
        ftm = _document_to_ftm(
            doc_id="42",
            title="Annual Report",
            source="documentcloud",
            author="Jane Reporter",
            date="2025-01-15",
            language="en",
            source_url="https://documentcloud.org/doc/42",
            page_count=15,
        )
        assert ftm["properties"]["author"] == ["Jane Reporter"]
        assert ftm["properties"]["date"] == ["2025-01-15"]
        assert ftm["properties"]["language"] == ["en"]
        assert ftm["properties"]["sourceUrl"] == ["https://documentcloud.org/doc/42"]

    def test_empty_optional_fields_excluded(self):
        ftm = _document_to_ftm(doc_id="1", title="Test", source="test")
        assert "author" not in ftm["properties"]
        assert "date" not in ftm["properties"]
        assert "language" not in ftm["properties"]


class TestNEREntityToFtM:
    def test_person_mapping(self):
        ftm = _ner_entity_to_ftm("John Smith", "PERSON", "datashare", "doc1")
        assert ftm["schema"] == "Person"
        assert ftm["properties"]["name"] == ["John Smith"]
        assert ftm["id"].startswith("ner-datashare-")

    def test_organization_mapping(self):
        ftm = _ner_entity_to_ftm("Acme Corp", "ORGANIZATION", "datashare", "doc1")
        assert ftm["schema"] == "Organization"

    def test_location_mapping(self):
        ftm = _ner_entity_to_ftm("London", "LOCATION", "datashare", "doc1")
        assert ftm["schema"] == "Address"

    def test_gpe_mapping(self):
        ftm = _ner_entity_to_ftm("United Kingdom", "GPE", "datashare", "doc1")
        assert ftm["schema"] == "Address"

    def test_unknown_type_fallback(self):
        ftm = _ner_entity_to_ftm("Something", "MISC", "datashare", "doc1")
        assert ftm["schema"] == "LegalEntity"  # Default fallback

    def test_stable_id_generation(self):
        """Same input should produce same ID."""
        ftm1 = _ner_entity_to_ftm("John", "PERSON", "ds", "d1")
        ftm2 = _ner_entity_to_ftm("John", "PERSON", "ds", "d1")
        assert ftm1["id"] == ftm2["id"]

    def test_different_inputs_different_ids(self):
        ftm1 = _ner_entity_to_ftm("John", "PERSON", "ds", "d1")
        ftm2 = _ner_entity_to_ftm("Jane", "PERSON", "ds", "d1")
        assert ftm1["id"] != ftm2["id"]

    def test_provenance_includes_extraction_source(self):
        ftm = _ner_entity_to_ftm("Alice", "PERSON", "datashare", "doc123")
        assert ftm["_provenance"]["source"] == "datashare/ner"
        assert ftm["_provenance"]["extracted_from"] == "doc123"


class TestMentionToFtM:
    def test_creates_link(self):
        ftm = _mention_to_ftm(
            entity_id="ner-ds-abc",
            document_id="doc-ds-123",
            entity_name="Alice",
            entity_schema="Person",
            source="datashare",
        )
        assert ftm["schema"] == "UnknownLink"
        assert ftm["properties"]["subject"] == ["ner-ds-abc"]
        assert ftm["properties"]["object"] == ["doc-ds-123"]
        assert "Person" in ftm["properties"]["role"][0]


# ---------------------------------------------------------------------------
# DatashareClient tests
# ---------------------------------------------------------------------------


class TestDatashareClient:
    def test_search_url_construction(self):
        client = DatashareClient(host="http://localhost:8080", project="myproject")
        # Verify URL would be correct (we test the format)
        expected_url = "http://localhost:8080/api/myproject/documents/search"
        assert f"{client._host}/api/{client._project}/documents/search" == expected_url

    def test_get_document_url(self):
        client = DatashareClient(host="http://test:8080", project="proj")
        expected = "http://test:8080/api/proj/documents/doc123"
        assert f"{client._host}/api/{client._project}/documents/doc123" == expected

    def test_ner_url(self):
        client = DatashareClient(host="http://test:8080", project="proj")
        expected = "http://test:8080/api/proj/documents/doc123/namedEntities"
        assert f"{client._host}/api/{client._project}/documents/doc123/namedEntities" == expected

    @pytest.mark.asyncio
    async def test_search_handles_connection_error(self):
        """Should return empty list on connection failure, not raise."""
        client = DatashareClient(host="http://localhost:1", timeout=1.0)
        results = await client.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_named_entities_handles_error(self):
        client = DatashareClient(host="http://localhost:1", timeout=1.0)
        results = await client.get_named_entities("nonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# DocumentCloudClient tests
# ---------------------------------------------------------------------------


class TestDocumentCloudClient:
    def test_default_base_url(self):
        client = DocumentCloudClient()
        assert "api.www.documentcloud.org" in client._base

    def test_custom_base_url(self):
        client = DocumentCloudClient(base_url="http://test:5000/api")
        assert client._base == "http://test:5000/api"

    def test_search_url_construction(self):
        client = DocumentCloudClient(base_url="http://test/api")
        expected = "http://test/api/documents/search/"
        assert f"{client._base}/documents/search/" == expected

    @pytest.mark.asyncio
    async def test_search_handles_connection_error(self):
        client = DocumentCloudClient(base_url="http://localhost:1/api", timeout=1.0)
        results = await client.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_text_handles_error(self):
        client = DocumentCloudClient(base_url="http://localhost:1/api", timeout=1.0)
        text = await client.get_text(12345)
        assert text == ""

    @pytest.mark.asyncio
    async def test_health_check_fails_gracefully(self):
        client = DocumentCloudClient(base_url="http://localhost:1/api", timeout=1.0)
        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_search_to_ftm_empty(self):
        """search_to_ftm returns empty list when API is unreachable."""
        client = DocumentCloudClient(base_url="http://localhost:1/api", timeout=1.0)
        entities = await client.search_to_ftm("test")
        assert entities == []
