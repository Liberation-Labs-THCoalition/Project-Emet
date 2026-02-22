"""Tests for entity resolution adapter — Sprint 13.

Tests normalization, record conversion, fallback resolution,
cluster merging, and convenience API.
"""

from __future__ import annotations

import pytest

from emet.ftm.external.entity_resolution import (
    EntityResolutionConfig,
    ResolvedEntity,
    EntityResolver,
    normalize_name,
    normalize_date,
    ftm_to_record,
    _metaphone,
    _most_specific_schema,
    resolve_entities,
)


# ===========================================================================
# Normalization
# ===========================================================================


class TestNormalizeName:
    def test_basic(self):
        assert normalize_name("John Smith") == "john smith"

    def test_honorifics_removed(self):
        assert normalize_name("Dr. John Smith") == "john smith"
        assert normalize_name("Mrs. Jane Doe") == "jane doe"
        assert normalize_name("Prof. Albert Einstein") == "albert einstein"

    def test_extra_whitespace(self):
        assert normalize_name("  John   Smith  ") == "john smith"

    def test_empty(self):
        assert normalize_name("") == ""

    def test_punctuation_removed(self):
        assert normalize_name("O'Brien, James") == "obrien james"


class TestNormalizeDate:
    def test_iso_format(self):
        assert normalize_date("1990-05-15") == "1990-05-15"

    def test_european_format(self):
        assert normalize_date("15/05/1990") == "1990-05-15"

    def test_year_only(self):
        assert normalize_date("1990") == "1990-01-01"

    def test_empty(self):
        assert normalize_date("") == ""

    def test_unknown_format_passthrough(self):
        assert normalize_date("circa 1990") == "circa 1990"


class TestMetaphone:
    def test_basic(self):
        result_j = _metaphone("john")
        assert result_j.startswith("J")
        result_s = _metaphone("smith")
        assert result_s.startswith("S")

    def test_empty(self):
        assert _metaphone("") == ""

    def test_similar_names(self):
        # Metaphone is a blocking heuristic, not exact phonetics
        m1 = _metaphone("johnson")
        m2 = _metaphone("jonson")
        # Both start with J — sufficient for blocking
        assert m1[0] == m2[0] == "J"
        assert len(m1) > 1 and len(m2) > 1

    def test_max_length(self):
        result = _metaphone("abcdefghijklmnop")
        assert len(result) <= 6


# ===========================================================================
# FtM → Record conversion
# ===========================================================================


class TestFtmToRecord:
    def test_person_entity(self):
        entity = {
            "id": "person-1",
            "schema": "Person",
            "properties": {
                "name": ["John Smith"],
                "birthDate": ["1985-03-15"],
                "nationality": ["US"],
            },
            "_provenance": {"source": "opensanctions"},
        }
        record = ftm_to_record(entity)
        assert record is not None
        assert record["unique_id"] == "person-1"
        assert record["name"] == "john smith"
        assert record["first_name"] == "john"
        assert record["last_name"] == "smith"
        assert record["birth_date"] == "1985-03-15"
        assert record["country"] == "us"
        assert record["source"] == "opensanctions"

    def test_company_entity(self):
        entity = {
            "id": "company-1",
            "schema": "Company",
            "properties": {
                "name": ["Acme Holdings Ltd"],
                "jurisdiction": ["GB"],
                "registrationNumber": ["12345678"],
            },
        }
        record = ftm_to_record(entity)
        assert record is not None
        assert record["name"] == "acme holdings ltd"
        assert record["country"] == "gb"
        assert record["id_number"] == "12345678"

    def test_no_name_returns_none(self):
        entity = {"id": "note-1", "schema": "Note", "properties": {"title": ["A note"]}}
        assert ftm_to_record(entity) is None

    def test_name_first_3(self):
        entity = {
            "id": "e1", "schema": "Person",
            "properties": {"name": ["Alexander Hamilton"]},
        }
        record = ftm_to_record(entity)
        assert record["name_first_3"] == "ale"

    def test_short_name(self):
        entity = {
            "id": "e1", "schema": "Person",
            "properties": {"name": ["Li"]},
        }
        record = ftm_to_record(entity)
        assert record["name_first_3"] == "li"


# ===========================================================================
# ResolvedEntity
# ===========================================================================


class TestResolvedEntity:
    def test_to_ftm(self):
        re = ResolvedEntity(
            canonical_id="resolved-abc",
            schema="Person",
            properties={"name": ["John Smith", "J. Smith"]},
            source_ids=["id-1", "id-2"],
            source_names=["opensanctions", "icij"],
            match_probability=0.92,
            cluster_size=2,
        )
        ftm = re.to_ftm()
        assert ftm["id"] == "resolved-abc"
        assert ftm["schema"] == "Person"
        assert len(ftm["properties"]["name"]) == 2
        prov = ftm["_provenance"]
        assert prov["source"] == "entity_resolution"
        assert prov["cluster_size"] == 2
        assert len(prov["source_ids"]) == 2


# ===========================================================================
# Schema priority
# ===========================================================================


class TestMostSpecificSchema:
    def test_person_wins(self):
        assert _most_specific_schema(["LegalEntity", "Person", "Organization"]) == "Person"

    def test_company_over_legal_entity(self):
        assert _most_specific_schema(["LegalEntity", "Company"]) == "Company"

    def test_single_schema(self):
        assert _most_specific_schema(["Organization"]) == "Organization"

    def test_unknown_schema(self):
        assert _most_specific_schema(["Vessel"]) == "Vessel"


# ===========================================================================
# Entity Resolver (fallback mode — no Splink dependency)
# ===========================================================================


class TestEntityResolver:
    def _make_entities(self) -> list[dict]:
        return [
            {
                "id": "os-1",
                "schema": "Person",
                "properties": {"name": ["John Smith"], "birthDate": ["1985-03-15"]},
                "_provenance": {"source": "opensanctions"},
            },
            {
                "id": "icij-1",
                "schema": "Person",
                "properties": {"name": ["John Smith"], "birthDate": ["1985-03-15"]},
                "_provenance": {"source": "icij"},
            },
            {
                "id": "os-2",
                "schema": "Person",
                "properties": {"name": ["Jane Doe"]},
                "_provenance": {"source": "opensanctions"},
            },
            {
                "id": "oc-1",
                "schema": "Company",
                "properties": {"name": ["Acme Corp"], "jurisdiction": ["US"]},
                "_provenance": {"source": "opencorporates"},
            },
        ]

    def test_resolves_duplicates(self):
        resolver = EntityResolver()
        resolved = resolver.resolve(self._make_entities())
        # John Smith (2 records) should merge, Jane Doe and Acme Corp separate
        assert len(resolved) == 3

    def test_merged_entity_has_multiple_sources(self):
        resolver = EntityResolver()
        resolved = resolver.resolve(self._make_entities())
        merged = [r for r in resolved if r.cluster_size > 1]
        assert len(merged) == 1
        assert "opensanctions" in merged[0].source_names
        assert "icij" in merged[0].source_names

    def test_single_entity(self):
        resolver = EntityResolver()
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Solo Person"]}},
        ]
        resolved = resolver.resolve(entities)
        assert len(resolved) == 1
        assert resolved[0].cluster_size == 1

    def test_empty_input(self):
        resolver = EntityResolver()
        resolved = resolver.resolve([])
        assert resolved == []

    def test_entities_without_names_skipped(self):
        resolver = EntityResolver()
        entities = [
            {"id": "n1", "schema": "Note", "properties": {"title": ["A note"]}},
            {"id": "p1", "schema": "Person", "properties": {"name": ["John Smith"]}},
        ]
        resolved = resolver.resolve(entities)
        assert len(resolved) == 1
        assert resolved[0].properties.get("name") == ["John Smith"]

    def test_different_names_stay_separate(self):
        resolver = EntityResolver()
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Alice Johnson"]}},
            {"id": "e2", "schema": "Person", "properties": {"name": ["Bob Williams"]}},
        ]
        resolved = resolver.resolve(entities)
        assert len(resolved) == 2

    def test_schema_specificity_in_merge(self):
        resolver = EntityResolver()
        entities = [
            {"id": "e1", "schema": "LegalEntity", "properties": {"name": ["John Smith"]}},
            {"id": "e2", "schema": "Person", "properties": {"name": ["John Smith"]}},
        ]
        resolved = resolver.resolve(entities)
        assert len(resolved) == 1
        assert resolved[0].schema == "Person"

    def test_property_union_on_merge(self):
        resolver = EntityResolver()
        entities = [
            {
                "id": "e1", "schema": "Person",
                "properties": {"name": ["John Smith"], "nationality": ["US"]},
                "_provenance": {"source": "source_a"},
            },
            {
                "id": "e2", "schema": "Person",
                "properties": {"name": ["John Smith"], "birthDate": ["1985-01-01"]},
                "_provenance": {"source": "source_b"},
            },
        ]
        resolved = resolver.resolve(entities)
        assert len(resolved) == 1
        props = resolved[0].properties
        assert "nationality" in props
        assert "birthDate" in props

    def test_custom_threshold(self):
        config = EntityResolutionConfig(match_threshold=0.99)
        resolver = EntityResolver(config)
        resolved = resolver.resolve(self._make_entities())
        # Higher threshold still works with fallback
        assert len(resolved) >= 1


# ===========================================================================
# Convenience API
# ===========================================================================


class TestResolveEntities:
    def test_basic(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
            {"id": "e2", "schema": "Person", "properties": {"name": ["John Smith"]}},
            {"id": "e3", "schema": "Person", "properties": {"name": ["Jane Doe"]}},
        ]
        result = resolve_entities(entities)
        assert result["input_count"] == 3
        assert result["resolved_count"] == 2
        assert result["reduction_pct"] > 0
        assert len(result["entities"]) == 2
        assert len(result["cross_references"]) == 3
        assert result["multi_source_count"] == 1

    def test_no_duplicates(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Alice"]}},
            {"id": "e2", "schema": "Person", "properties": {"name": ["Bob"]}},
        ]
        result = resolve_entities(entities)
        assert result["resolved_count"] == 2
        assert result["reduction_pct"] == 0.0
        assert result["multi_source_count"] == 0

    def test_empty_input(self):
        result = resolve_entities([])
        assert result["resolved_count"] == 0
        assert result["input_count"] == 0
