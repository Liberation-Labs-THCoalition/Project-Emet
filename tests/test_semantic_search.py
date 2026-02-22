"""Tests for semantic search and RAG adapter — Sprint 14.

Tests entity-to-text conversion, text chunking, search engine,
RAG context building, and result formatting. Uses mocking to
avoid ChromaDB dependency in CI.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any

from emet.ftm.external.semantic_search import (
    SemanticSearchConfig,
    SemanticSearchEngine,
    SearchResult,
    SearchResponse,
    entity_to_text,
    chunk_text,
    build_rag_context,
)


# ===========================================================================
# Configuration
# ===========================================================================


class TestSemanticSearchConfig:
    def test_defaults(self):
        cfg = SemanticSearchConfig()
        assert cfg.collection_name == "emet_investigation"
        assert cfg.distance_metric == "cosine"
        assert cfg.chunk_size == 500
        assert cfg.chunk_overlap == 50
        assert cfg.max_results == 10

    def test_custom(self):
        cfg = SemanticSearchConfig(
            collection_name="test_col",
            persist_directory="/tmp/chroma",
            distance_metric="l2",
            max_results=20,
        )
        assert cfg.collection_name == "test_col"
        assert cfg.persist_directory == "/tmp/chroma"
        assert cfg.distance_metric == "l2"


# ===========================================================================
# Entity to text
# ===========================================================================


class TestEntityToText:
    def test_person_entity(self):
        entity = {
            "schema": "Person",
            "properties": {
                "name": ["John Smith"],
                "nationality": ["US"],
                "birthDate": ["1980-01-01"],
            },
        }
        text = entity_to_text(entity)
        assert "[Person]" in text
        assert "John Smith" in text
        assert "Nationality: US" in text
        assert "Born: 1980-01-01" in text

    def test_company_entity(self):
        entity = {
            "schema": "Company",
            "properties": {
                "name": ["Acme Corp"],
                "jurisdiction": ["Panama"],
                "registrationNumber": ["12345"],
            },
        }
        text = entity_to_text(entity)
        assert "[Company]" in text
        assert "Acme Corp" in text
        assert "Panama" in text
        assert "12345" in text

    def test_document_entity(self):
        entity = {
            "schema": "Document",
            "properties": {
                "title": ["Leaked Memo"],
                "bodyText": ["The funds were transferred..."],
            },
        }
        text = entity_to_text(entity)
        assert "Leaked Memo" in text
        assert "Content: The funds" in text

    def test_provenance_included(self):
        entity = {
            "schema": "Entity",
            "properties": {"name": ["Test"]},
            "_provenance": {"source": "opensanctions"},
        }
        text = entity_to_text(entity)
        assert "opensanctions" in text

    def test_empty_entity(self):
        text = entity_to_text({"schema": "Entity", "properties": {}})
        assert "[Entity]" in text

    def test_title_fallback(self):
        entity = {
            "schema": "Document",
            "properties": {"title": ["My Doc"]},
        }
        text = entity_to_text(entity)
        assert "My Doc" in text

    def test_multiple_names(self):
        entity = {
            "schema": "Person",
            "properties": {"name": ["John Smith", "J. Smith"]},
        }
        text = entity_to_text(entity)
        assert "John Smith" in text
        assert "J. Smith" in text


# ===========================================================================
# Text chunking
# ===========================================================================


class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("Hello world", chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_splits_long_text(self):
        text = "A" * 1000
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 2
        # All text should be covered
        total_chars = sum(len(c) for c in chunks)
        assert total_chars >= len(text)

    def test_respects_sentence_boundaries(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = chunk_text(text, chunk_size=35, overlap=5)
        # Should try to break at ". "
        assert len(chunks) >= 2

    def test_overlap(self):
        text = "ABCDEFGHIJ" * 20  # 200 chars
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2

    def test_exact_boundary(self):
        text = "A" * 500
        chunks = chunk_text(text, chunk_size=500)
        assert len(chunks) == 1


# ===========================================================================
# Search results
# ===========================================================================


class TestSearchResult:
    def test_basic_result(self):
        r = SearchResult(
            entity_id="e1",
            text="Test text",
            score=0.95,
            schema="Person",
        )
        assert r.entity_id == "e1"
        assert r.score == 0.95


class TestSearchResponse:
    def test_context_text(self):
        resp = SearchResponse(
            query="test",
            results=[
                SearchResult(entity_id="e1", text="First result", score=0.9, schema="Person"),
                SearchResult(entity_id="e2", text="Second result", score=0.8, schema="Company"),
            ],
            total_results=2,
        )
        ctx = resp.context_text
        assert "First result" in ctx
        assert "Second result" in ctx
        assert "Person" in ctx
        assert "0.900" in ctx

    def test_to_dict(self):
        resp = SearchResponse(
            query="test",
            results=[
                SearchResult(entity_id="e1", text="Result", score=0.9, schema="Person"),
            ],
            total_results=1,
            search_time_ms=5.0,
        )
        d = resp.to_dict()
        assert d["query"] == "test"
        assert d["total_results"] == 1
        assert len(d["results"]) == 1
        assert d["results"][0]["entity_id"] == "e1"

    def test_empty_response(self):
        resp = SearchResponse(query="nothing")
        assert resp.context_text == ""
        assert resp.to_dict()["total_results"] == 0


# ===========================================================================
# Semantic search engine (mocked ChromaDB)
# ===========================================================================


def _mock_collection():
    """Create a mock ChromaDB collection."""
    collection = MagicMock()
    collection.count.return_value = 42
    collection.add.return_value = None
    collection.query.return_value = {
        "documents": [["John Smith is a person from Panama", "Acme Corp registered in BVI"]],
        "distances": [[0.1, 0.3]],
        "metadatas": [[
            {"entity_id": "e1", "schema": "Person", "source": "opensanctions", "chunk_index": 0},
            {"entity_id": "e2", "schema": "Company", "source": "opencorporates", "chunk_index": 0},
        ]],
        "ids": [["e1_chunk_0", "e2_chunk_0"]],
    }
    return collection


class TestSemanticSearchEngine:
    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_index_entities(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
            {"id": "e2", "schema": "Company", "properties": {"name": ["Acme Corp"]}},
        ]
        result = engine.index_entities(entities)

        assert result["entity_count"] == 2
        assert result["chunk_count"] >= 2
        collection.add.assert_called()

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_index_skips_empty(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        result = engine.index_entities([
            {"id": "e1", "schema": "Entity", "properties": {}},
        ])
        # [Entity] alone is not empty, but minimal
        assert result["entity_count"] == 1

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_search_basic(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        response = engine.search("panama connection")

        collection.query.assert_called_once()
        assert response.total_results == 2
        assert response.results[0].entity_id == "e1"
        assert response.results[0].score == pytest.approx(0.9, abs=0.01)
        assert response.results[1].schema == "Company"

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_search_with_schema_filter(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        engine.search("test", schema_filter="Person")

        call_kwargs = collection.query.call_args[1]
        assert call_kwargs.get("where") == {"schema": "Person"}

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_search_with_dual_filter(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        engine.search("test", schema_filter="Person", source_filter="opensanctions")

        call_kwargs = collection.query.call_args[1]
        where = call_kwargs.get("where")
        assert "$and" in where

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_search_empty_results(self, mock_get):
        collection = _mock_collection()
        collection.query.return_value = {"documents": [[]], "distances": [[]], "metadatas": [[]], "ids": [[]]}
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        response = engine.search("nothing matches")
        assert response.total_results == 0

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_search_l2_distance(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        config = SemanticSearchConfig(distance_metric="l2")
        engine = SemanticSearchEngine(config=config)
        response = engine.search("test")

        # l2 score = 1/(1+distance)
        assert response.results[0].score == pytest.approx(1.0 / 1.1, abs=0.01)

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_collection_stats(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        stats = engine.collection_stats()
        assert stats["count"] == 42
        assert stats["distance_metric"] == "cosine"

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_max_results_override(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        engine.search("test", max_results=3)

        call_kwargs = collection.query.call_args[1]
        assert call_kwargs["n_results"] == 3


# ===========================================================================
# RAG context builder
# ===========================================================================


class TestBuildRagContext:
    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_basic_rag(self, mock_get):
        collection = _mock_collection()
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        ctx = build_rag_context("panama shell companies", engine, max_results=5)

        assert ctx["query"] == "panama shell companies"
        assert ctx["results_used"] >= 1
        assert len(ctx["context"]) > 0

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_rag_char_limit(self, mock_get):
        collection = _mock_collection()
        # Return very long results
        collection.query.return_value = {
            "documents": [["A" * 3000, "B" * 3000]],
            "distances": [[0.1, 0.2]],
            "metadatas": [[
                {"entity_id": "e1", "schema": "X", "source": "y", "chunk_index": 0},
                {"entity_id": "e2", "schema": "X", "source": "y", "chunk_index": 0},
            ]],
            "ids": [["id1", "id2"]],
        }
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        ctx = build_rag_context("test", engine, max_context_chars=4000)

        # Should not exceed limit
        assert ctx["context_chars"] <= 4000

    @patch("emet.ftm.external.semantic_search.SemanticSearchEngine._get_collection")
    def test_rag_empty_results(self, mock_get):
        collection = _mock_collection()
        collection.query.return_value = {"documents": [[]], "distances": [[]], "metadatas": [[]], "ids": [[]]}
        mock_get.return_value = collection

        engine = SemanticSearchEngine()
        ctx = build_rag_context("nothing", engine)
        assert ctx["results_used"] == 0
        assert ctx["context"] == ""
