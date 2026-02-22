"""Tests for dataset augmentation and blockchain clustering — Sprint 17.

Tests augmentation engine, name scoring, blockchain clustering
heuristics, and risk assessment.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Any

from emet.ftm.external.augmentation import (
    AugmentationConfig,
    AugmentationResult,
    AugmentationMatch,
    DatasetAugmenter,
    BlockchainClusterer,
    ClusterResult,
    _get_name,
    _simple_name_score,
    _extract_cluster,
    _assess_risk,
)


# ===========================================================================
# Configuration
# ===========================================================================


class TestAugmentationConfig:
    def test_defaults(self):
        cfg = AugmentationConfig()
        assert cfg.min_match_score == 0.65
        assert "opensanctions" in cfg.sources
        assert "opencorporates" in cfg.sources
        assert cfg.enable_blockchain is False

    def test_custom(self):
        cfg = AugmentationConfig(
            min_match_score=0.8,
            sources=["opensanctions"],
            enable_blockchain=True,
        )
        assert cfg.min_match_score == 0.8
        assert len(cfg.sources) == 1


# ===========================================================================
# Helpers
# ===========================================================================


class TestGetName:
    def test_name_property(self):
        entity = {"properties": {"name": ["John Smith"]}}
        assert _get_name(entity) == "John Smith"

    def test_title_fallback(self):
        entity = {"properties": {"title": ["Report"]}}
        assert _get_name(entity) == "Report"

    def test_empty(self):
        assert _get_name({}) == ""
        assert _get_name({"properties": {}}) == ""


class TestSimpleNameScore:
    def test_exact_match(self):
        assert _simple_name_score("John Smith", "John Smith") == 1.0

    def test_partial_match(self):
        score = _simple_name_score("John Smith", "John Doe")
        assert 0.0 < score < 1.0  # "John" matches

    def test_no_match(self):
        assert _simple_name_score("Alice", "Bob") == 0.0

    def test_empty_strings(self):
        assert _simple_name_score("", "test") == 0.0
        assert _simple_name_score("test", "") == 0.0

    def test_case_insensitive(self):
        assert _simple_name_score("JOHN SMITH", "john smith") == 1.0

    def test_subset_match(self):
        score = _simple_name_score("John", "John Smith Jones")
        assert score == pytest.approx(1 / 3)


# ===========================================================================
# Blockchain clustering helpers
# ===========================================================================


class TestExtractCluster:
    def test_common_input_heuristic(self):
        seed = "0xAAA"
        txs = [
            {"inputs": ["0xAAA", "0xBBB", "0xCCC"], "from": "0xAAA"},
            {"inputs": ["0xAAA", "0xDDD"], "from": "0xAAA"},
        ]
        cluster = _extract_cluster(seed, txs, max_depth=1)
        assert "0xbbb" in cluster
        assert "0xccc" in cluster
        assert "0xddd" in cluster
        assert "0xaaa" not in cluster  # Seed excluded

    def test_seed_not_in_inputs_ignored(self):
        seed = "0xAAA"
        txs = [
            {"inputs": ["0xXXX", "0xYYY"], "from": "0xXXX"},
        ]
        cluster = _extract_cluster(seed, txs, max_depth=1)
        assert cluster == []

    def test_empty_transactions(self):
        cluster = _extract_cluster("0xAAA", [], max_depth=1)
        assert cluster == []

    def test_from_field_fallback(self):
        seed = "0xAAA"
        txs = [{"from": "0xAAA"}]
        cluster = _extract_cluster(seed, txs, max_depth=1)
        # from field is used as single-element input list
        assert cluster == []  # Only seed itself

    def test_cluster_cap(self):
        seed = "0xAAA"
        inputs = [f"0x{i:04d}" for i in range(100)]
        inputs.append("0xAAA")
        txs = [{"inputs": inputs}]
        cluster = _extract_cluster(seed, txs, max_depth=1)
        assert len(cluster) <= 50


class TestAssessRisk:
    def test_large_cluster(self):
        flags = _assess_risk({"transactions": []}, list(range(25)))
        assert "large_cluster" in flags

    def test_high_tx_volume(self):
        txs = [{"hash": f"tx{i}"} for i in range(150)]
        flags = _assess_risk({"transactions": txs}, [])
        assert "high_tx_volume" in flags

    def test_flagged_labels(self):
        flags = _assess_risk(
            {"transactions": [], "labels": ["Tornado Cash", "sanctioned entity"]},
            [],
        )
        assert any("tornado" in f.lower() for f in flags)
        assert any("sanctioned" in f.lower() for f in flags)

    def test_clean(self):
        flags = _assess_risk({"transactions": [{"hash": "tx1"}]}, ["0x1"])
        assert flags == []


# ===========================================================================
# Augmentation result
# ===========================================================================


class TestAugmentationResult:
    def test_summary(self):
        result = AugmentationResult(
            original_count=10,
            enriched_count=15,
            new_entities_found=5,
            new_relationships_found=5,
            sources_queried=["opensanctions", "icij"],
        )
        s = result.summary()
        assert s["original_count"] == 10
        assert s["new_entities_found"] == 5
        assert len(s["sources_queried"]) == 2


# ===========================================================================
# Dataset augmenter (mocked sources)
# ===========================================================================


class TestDatasetAugmenter:
    @pytest.mark.asyncio
    async def test_augment_basic(self):
        augmenter = DatasetAugmenter(AugmentationConfig(
            sources=["opensanctions"],
            min_match_score=0.5,
        ))

        mock_entity = {
            "id": "match-1",
            "schema": "Person",
            "properties": {"name": ["John Smith Match"]},
        }

        with patch.object(augmenter, "_query_source", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [
                {"entity": mock_entity, "score": 0.8, "type": "fuzzy"},
            ]

            entities = [
                {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
            ]
            result = await augmenter.augment(entities)

        assert result.original_count == 1
        assert result.new_entities_found == 1
        assert result.new_relationships_found == 1
        assert len(result.matches) == 1
        assert result.matches[0].match_score == 0.8

    @pytest.mark.asyncio
    async def test_augment_below_threshold_skipped(self):
        augmenter = DatasetAugmenter(AugmentationConfig(
            sources=["opensanctions"],
            min_match_score=0.9,
        ))

        with patch.object(augmenter, "_query_source", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [
                {"entity": {"id": "x"}, "score": 0.5, "type": "fuzzy"},  # Below threshold
            ]

            entities = [{"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}}]
            result = await augmenter.augment(entities)

        assert result.new_entities_found == 0
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_augment_handles_errors(self):
        augmenter = DatasetAugmenter(AugmentationConfig(sources=["opensanctions"]))

        with patch.object(augmenter, "_query_source", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = Exception("API down")

            entities = [{"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}}]
            result = await augmenter.augment(entities)

        assert len(result.errors) == 1
        assert "API down" in result.errors[0]
        assert result.new_entities_found == 0

    @pytest.mark.asyncio
    async def test_augment_no_names_skipped(self):
        augmenter = DatasetAugmenter(AugmentationConfig(sources=["opensanctions"]))

        with patch.object(augmenter, "_query_source", new_callable=AsyncMock) as mock_query:
            entities = [{"id": "e1", "schema": "Entity", "properties": {}}]
            result = await augmenter.augment(entities)

        mock_query.assert_not_called()  # No names = nothing to query

    @pytest.mark.asyncio
    async def test_augment_multiple_sources(self):
        augmenter = DatasetAugmenter(AugmentationConfig(
            sources=["opensanctions", "icij"],
            min_match_score=0.5,
        ))

        with patch.object(augmenter, "_query_source", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [
                {"entity": {"id": "m1", "schema": "Person", "properties": {"name": ["Match"]}}, "score": 0.7},
            ]

            entities = [{"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}}]
            result = await augmenter.augment(entities)

        assert mock_query.call_count == 2  # Called for each source
        assert result.new_entities_found == 2


# ===========================================================================
# Blockchain clusterer (mocked)
# ===========================================================================


class TestBlockchainClusterer:
    @pytest.mark.asyncio
    async def test_cluster_basic(self):
        clusterer = BlockchainClusterer()

        mock_tx_data = {
            "address": "0xAAA",
            "transactions": [
                {"inputs": ["0xAAA", "0xBBB"], "value": 1.5},
                {"inputs": ["0xAAA", "0xCCC"], "value": 2.0},
            ],
        }

        mock_adapter = AsyncMock()
        mock_adapter.investigate_address.return_value = mock_tx_data

        with patch.dict("sys.modules", {
            "emet.ftm.external.blockchain": MagicMock(
                BlockchainAdapter=MagicMock(return_value=mock_adapter),
                BlockchainConfig=MagicMock(),
            ),
        }):
            result = await clusterer.cluster_address("0xAAA", chain="ethereum")

        assert result.seed_address == "0xAAA"
        assert result.cluster_size >= 2
        assert result.total_value_transferred == 3.5
        assert len(result.entities) >= 2

    @pytest.mark.asyncio
    async def test_cluster_api_failure(self):
        clusterer = BlockchainClusterer()

        mock_adapter = AsyncMock()
        mock_adapter.investigate_address.side_effect = Exception("API error")

        with patch.dict("sys.modules", {
            "emet.ftm.external.blockchain": MagicMock(
                BlockchainAdapter=MagicMock(return_value=mock_adapter),
                BlockchainConfig=MagicMock(),
            ),
        }):
            result = await clusterer.cluster_address("0xAAA")

        assert result.cluster_size == 0
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_cluster_entities_are_ftm(self):
        clusterer = BlockchainClusterer()

        mock_tx_data = {
            "address": "0xAAA",
            "transactions": [
                {"inputs": ["0xAAA", "0xBBB"], "value": 1.0},
            ],
        }

        mock_adapter = AsyncMock()
        mock_adapter.investigate_address.return_value = mock_tx_data

        with patch.dict("sys.modules", {
            "emet.ftm.external.blockchain": MagicMock(
                BlockchainAdapter=MagicMock(return_value=mock_adapter),
                BlockchainConfig=MagicMock(),
            ),
        }):
            result = await clusterer.cluster_address("0xAAA", chain="bitcoin")

        for entity in result.entities:
            assert entity["schema"] == "CryptoWallet"
            assert "_provenance" in entity
            assert entity["_provenance"]["chain"] == "bitcoin"
