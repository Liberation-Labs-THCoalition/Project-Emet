"""Tests for data federation, FtM converters, rate limiting, and blockchain.

Covers:
    - FtM converters for all four sources + blockchain
    - Rate limiter (token bucket + monthly counter)
    - Response cache
    - FederatedSearch deduplication and parallel fan-out (mocked)
    - Blockchain address detection
    - Blockchain client request formatting (mocked)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from emet.ftm.external.converters import (
    gleif_record_to_ftm,
    gleif_search_to_ftm_list,
    icij_node_to_ftm,
    icij_search_to_ftm_list,
    oc_company_to_ftm,
    oc_officer_to_ftm,
    oc_search_to_ftm_list,
    yente_result_to_ftm,
    yente_search_to_ftm_list,
)
from emet.ftm.external.rate_limit import (
    MonthlyCounter,
    ResponseCache,
    TokenBucketLimiter,
)
from emet.ftm.external.federation import (
    FederatedSearch,
    FederationConfig,
    _name_similarity,
)
from emet.ftm.external.blockchain import (
    BlockstreamClient,
    EtherscanClient,
    EtherscanConfig,
    crypto_address_to_ftm,
    detect_chain,
)


# ====================================================================
# Converter tests
# ====================================================================


class TestYenteConverters:
    def test_yente_result_passthrough(self) -> None:
        result = {
            "id": "os-abc123",
            "schema": "Person",
            "properties": {"name": ["Vladimir Putin"]},
            "score": 0.95,
            "datasets": ["ru_sanctions_list"],
        }
        entity = yente_result_to_ftm(result)
        assert entity["schema"] == "Person"
        assert entity["properties"]["name"] == ["Vladimir Putin"]
        assert entity["_provenance"]["source"] == "opensanctions"
        assert entity["_provenance"]["match_score"] == 0.95
        assert entity["_provenance"]["confidence"] == 1.0

    def test_yente_search_list(self) -> None:
        response = {
            "results": [
                {"id": "a1", "schema": "Person", "properties": {"name": ["Test A"]}},
                {"id": "a2", "schema": "Company", "properties": {"name": ["Test B Corp"]}},
            ]
        }
        entities = yente_search_to_ftm_list(response)
        assert len(entities) == 2
        assert entities[0]["schema"] == "Person"
        assert entities[1]["schema"] == "Company"


class TestOpenCorporatesConverters:
    def test_company_conversion(self) -> None:
        oc_data = {
            "company": {
                "name": "Shell Corp Ltd",
                "jurisdiction_code": "gb",
                "company_number": "12345678",
                "incorporation_date": "2020-01-15",
                "current_status": "Active",
                "company_type": "Private Limited Company",
                "registered_address_in_full": "123 Main St, London, UK",
                "opencorporates_url": "https://opencorporates.com/companies/gb/12345678",
            }
        }
        entity = oc_company_to_ftm(oc_data)
        assert entity["schema"] == "Company"
        assert entity["properties"]["name"] == ["Shell Corp Ltd"]
        assert entity["properties"]["jurisdiction"] == ["gb"]
        assert entity["properties"]["registrationNumber"] == ["12345678"]
        assert entity["_provenance"]["source"] == "opencorporates"

    def test_officer_conversion(self) -> None:
        oc_data = {
            "officer": {
                "name": "John Smith",
                "position": "Director",
                "nationality": "British",
                "company": {"name": "Shell Corp Ltd"},
            }
        }
        entity = oc_officer_to_ftm(oc_data)
        assert entity["schema"] == "Person"
        assert entity["properties"]["name"] == ["John Smith"]
        assert entity["_relationship_hints"]["type"] == "Directorship"
        assert entity["_relationship_hints"]["organization_name"] == "Shell Corp Ltd"

    def test_search_list_conversion(self) -> None:
        response = {
            "results": {
                "companies": [
                    {"company": {"name": "Corp A", "jurisdiction_code": "us_de"}},
                    {"company": {"name": "Corp B", "jurisdiction_code": "gb"}},
                ]
            }
        }
        entities = oc_search_to_ftm_list(response)
        assert len(entities) == 2


class TestICIJConverters:
    def test_entity_node(self) -> None:
        node = {
            "node_id": 12345,
            "type": "entity",
            "name": "Offshore Holdings Ltd",
            "jurisdiction": "VGB",
            "country_codes": "VGB;PAN",
            "incorporation_date": "2005-03-01",
            "sourceID": "Panama Papers",
        }
        entity = icij_node_to_ftm(node)
        assert entity["schema"] == "Company"
        assert entity["properties"]["name"] == ["Offshore Holdings Ltd"]
        assert "VGB" in entity["properties"]["country"]
        assert "PAN" in entity["properties"]["country"]
        assert entity["_provenance"]["source"] == "icij_offshore_leaks"
        assert entity["_icij_metadata"]["source_datasets"] == ["Panama Papers"]

    def test_officer_node(self) -> None:
        node = {"node_id": 999, "type": "officer", "name": "John Doe"}
        entity = icij_node_to_ftm(node)
        assert entity["schema"] == "Person"

    def test_search_list(self) -> None:
        response = {"data": [{"node_id": 1, "name": "A"}, {"node_id": 2, "name": "B"}]}
        entities = icij_search_to_ftm_list(response)
        assert len(entities) == 2


class TestGLEIFConverters:
    def test_lei_record(self) -> None:
        record = {
            "attributes": {
                "lei": "5493001KJTIIGC8Y1R12",
                "entity": {
                    "legalName": {"name": "Deutsche Bank AG"},
                    "jurisdiction": "DE",
                    "legalAddress": {
                        "addressLines": ["Taunusanlage 12"],
                        "city": "Frankfurt",
                        "country": "DE",
                        "postalCode": "60325",
                    },
                    "otherNames": [
                        {"name": "Deutsche Bank"},
                        {"name": "DB AG"},
                    ],
                    "status": "ACTIVE",
                },
                "registration": {
                    "initialRegistrationDate": "2012-06-06T15:00:00Z",
                    "status": "ISSUED",
                    "managingLou": "EVK05KS7XY1DEII3R011",
                },
            }
        }
        entity = gleif_record_to_ftm(record)
        assert entity["schema"] == "Company"
        assert entity["properties"]["name"] == ["Deutsche Bank AG"]
        assert entity["properties"]["leiCode"] == ["5493001KJTIIGC8Y1R12"]
        assert entity["properties"]["jurisdiction"] == ["DE"]
        assert "Deutsche Bank" in entity["properties"]["alias"]
        assert entity["_provenance"]["confidence"] == 0.98

    def test_search_list(self) -> None:
        response = {
            "data": [
                {"attributes": {"lei": "ABC", "entity": {"legalName": {"name": "Test"}}}},
            ]
        }
        entities = gleif_search_to_ftm_list(response)
        assert len(entities) == 1


# ====================================================================
# Rate limiter tests
# ====================================================================


class TestTokenBucketLimiter:
    @pytest.mark.asyncio
    async def test_allows_burst(self) -> None:
        limiter = TokenBucketLimiter(rate=10, burst=3)
        # Should allow 3 immediate requests
        for _ in range(3):
            await limiter.acquire()
        assert limiter.available_tokens < 1.0

    @pytest.mark.asyncio
    async def test_refills_over_time(self) -> None:
        limiter = TokenBucketLimiter(rate=100)  # Fast refill
        await limiter.acquire()
        await asyncio.sleep(0.05)  # Wait a bit
        assert limiter.available_tokens > 0


class TestMonthlyCounter:
    def test_counts_requests(self) -> None:
        counter = MonthlyCounter(monthly_limit=10, source_name="test")
        assert counter.can_request()
        counter.record(5)
        assert counter.remaining == 5
        counter.record(5)
        assert counter.remaining == 0
        assert not counter.can_request()

    def test_usage_stats(self) -> None:
        counter = MonthlyCounter(monthly_limit=200, source_name="OpenCorporates")
        counter.record(50)
        stats = counter.usage
        assert stats["used"] == 50
        assert stats["limit"] == 200
        assert stats["remaining"] == 150
        assert stats["usage_percent"] == 25.0


class TestResponseCache:
    def test_get_set(self) -> None:
        cache = ResponseCache(default_ttl=60)
        key = cache.make_key("test", "endpoint", {"q": "hello"})
        assert cache.get(key) is None
        cache.set(key, {"result": "data"})
        assert cache.get(key) == {"result": "data"}

    def test_ttl_expiry(self) -> None:
        cache = ResponseCache(default_ttl=0.01)  # 10ms TTL
        key = cache.make_key("test", "endpoint", {"q": "hello"})
        cache.set(key, "data")
        time.sleep(0.02)
        assert cache.get(key) is None

    def test_max_entries_eviction(self) -> None:
        cache = ResponseCache(default_ttl=60, max_entries=3)
        for i in range(5):
            cache.set(f"key_{i}", f"value_{i}")
        assert len(cache._store) <= 3

    def test_deterministic_keys(self) -> None:
        cache = ResponseCache()
        key1 = cache.make_key("source", "endpoint", {"a": 1, "b": 2})
        key2 = cache.make_key("source", "endpoint", {"b": 2, "a": 1})
        assert key1 == key2  # Same params, different order

    def test_stats(self) -> None:
        cache = ResponseCache()
        key = "test_key"
        cache.get(key)  # miss
        cache.set(key, "val")
        cache.get(key)  # hit
        cache.get(key)  # hit
        assert cache.stats["hits"] == 2
        assert cache.stats["misses"] == 1
        assert cache.stats["hit_rate"] > 0.6


# ====================================================================
# Federation tests
# ====================================================================


class TestNameSimilarity:
    def test_identical(self) -> None:
        assert _name_similarity("Deutsche Bank AG", "Deutsche Bank AG") == 1.0

    def test_case_insensitive(self) -> None:
        assert _name_similarity("Deutsche Bank", "deutsche bank") == 1.0

    def test_corporate_suffix_stripped(self) -> None:
        """Corporate suffixes are stripped, so 'Deutsche Bank AG' == 'Deutsche Bank'."""
        assert _name_similarity("Deutsche Bank AG", "Deutsche Bank") == 1.0
        assert _name_similarity("Shell Plc", "Shell") == 1.0
        assert _name_similarity("Apple Inc", "Apple") == 1.0

    def test_partial_overlap(self) -> None:
        """Genuinely different names with some shared tokens."""
        sim = _name_similarity("East India Trading", "West India Trading")
        assert 0.3 < sim < 1.0

    def test_no_overlap(self) -> None:
        assert _name_similarity("Apple Inc", "Deutsche Bank AG") == 0.0

    def test_empty(self) -> None:
        assert _name_similarity("", "Test") == 0.0


class TestFederatedSearchDeduplication:
    def test_dedup_removes_near_duplicates(self) -> None:
        federation = FederatedSearch(FederationConfig(
            enable_opensanctions=False,
            enable_opencorporates=False,
            enable_icij=False,
            enable_gleif=False,
        ))

        entities = [
            {
                "schema": "Company",
                "properties": {"name": ["Deutsche Bank AG"]},
                "_provenance": {"source": "gleif", "confidence": 0.98},
            },
            {
                "schema": "Company",
                "properties": {"name": ["Deutsche Bank AG"]},
                "_provenance": {"source": "opencorporates", "confidence": 0.95},
            },
            {
                "schema": "Company",
                "properties": {"name": ["Apple Inc"]},
                "_provenance": {"source": "gleif", "confidence": 0.98},
            },
        ]

        deduped = federation._deduplicate(entities)
        assert len(deduped) == 2
        # GLEIF should win (higher confidence)
        db = next(e for e in deduped if "Deutsche" in e["properties"]["name"][0])
        assert db["_provenance"]["source"] == "gleif"
        assert len(db.get("_also_found_in", [])) == 1
        assert db["_also_found_in"][0]["source"] == "opencorporates"

    def test_dedup_preserves_distinct_entities(self) -> None:
        federation = FederatedSearch(FederationConfig(
            enable_opensanctions=False,
            enable_opencorporates=False,
            enable_icij=False,
            enable_gleif=False,
        ))

        entities = [
            {"schema": "Company", "properties": {"name": ["Alpha Corp"]}, "_provenance": {"source": "a", "confidence": 1}},
            {"schema": "Company", "properties": {"name": ["Beta Ltd"]}, "_provenance": {"source": "b", "confidence": 1}},
            {"schema": "Company", "properties": {"name": ["Gamma GmbH"]}, "_provenance": {"source": "c", "confidence": 1}},
        ]

        deduped = federation._deduplicate(entities)
        assert len(deduped) == 3

    def test_dedup_merges_corporate_suffix_variants(self) -> None:
        """REGRESSION: 'Deutsche Bank AG' vs 'Deutsche Bank' were not merging."""
        federation = FederatedSearch(FederationConfig(
            enable_opensanctions=False,
            enable_opencorporates=False,
            enable_icij=False,
            enable_gleif=False,
        ))

        entities = [
            {"schema": "Company", "properties": {"name": ["Deutsche Bank AG"]}, "_provenance": {"source": "gleif", "confidence": 0.98}},
            {"schema": "Company", "properties": {"name": ["Deutsche Bank"]}, "_provenance": {"source": "opensanctions", "confidence": 0.90}},
            {"schema": "Company", "properties": {"name": ["Shell Plc"]}, "_provenance": {"source": "opencorporates", "confidence": 0.95}},
            {"schema": "Company", "properties": {"name": ["Shell"]}, "_provenance": {"source": "icij", "confidence": 0.85}},
        ]

        deduped = federation._deduplicate(entities)
        assert len(deduped) == 2, f"Expected 2 after dedup, got {len(deduped)}: {[e['properties']['name'] for e in deduped]}"

    def test_dedup_does_not_false_merge_different_companies(self) -> None:
        """Companies with overlapping tokens but different names stay separate."""
        federation = FederatedSearch(FederationConfig(
            enable_opensanctions=False,
            enable_opencorporates=False,
            enable_icij=False,
            enable_gleif=False,
        ))

        entities = [
            {"schema": "Company", "properties": {"name": ["Goldman Sachs"]}, "_provenance": {"source": "a", "confidence": 1}},
            {"schema": "Company", "properties": {"name": ["Morgan Stanley"]}, "_provenance": {"source": "b", "confidence": 1}},
            {"schema": "Person", "properties": {"name": ["John Smith"]}, "_provenance": {"source": "c", "confidence": 1}},
            {"schema": "Person", "properties": {"name": ["Jane Smith"]}, "_provenance": {"source": "d", "confidence": 1}},
        ]

        deduped = federation._deduplicate(entities)
        assert len(deduped) == 4, "Different entities must not be merged"


class TestFederatedSearchSourceStatus:
    def test_source_status_disabled(self) -> None:
        federation = FederatedSearch(FederationConfig(
            enable_aleph=False,
            enable_opensanctions=False,
            enable_opencorporates=False,
            enable_icij=False,
            enable_gleif=False,
            enable_companies_house=False,
            enable_edgar=False,
        ))
        status = federation.source_status
        assert status["enabled_sources"] == []

    def test_source_status_enabled(self) -> None:
        federation = FederatedSearch(FederationConfig(
            enable_opensanctions=True,
            enable_opencorporates=True,
            enable_icij=True,
            enable_gleif=True,
        ))
        status = federation.source_status
        assert "opensanctions" in status["enabled_sources"]
        assert "opencorporates" in status["enabled_sources"]
        assert "icij" in status["enabled_sources"]
        assert "gleif" in status["enabled_sources"]


# ====================================================================
# Blockchain tests
# ====================================================================


class TestAddressDetection:
    def test_ethereum_address(self) -> None:
        assert detect_chain("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08") == "ethereum"

    def test_bitcoin_legacy(self) -> None:
        assert detect_chain("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2") == "bitcoin"

    def test_bitcoin_segwit(self) -> None:
        assert detect_chain("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq") == "bitcoin"

    def test_invalid_address(self) -> None:
        assert detect_chain("not-a-crypto-address") is None

    def test_empty_string(self) -> None:
        assert detect_chain("") is None


class TestEtherscanClient:
    @pytest.fixture
    def etherscan(self) -> EtherscanClient:
        return EtherscanClient(EtherscanConfig(api_key="test"))

    @pytest.mark.asyncio
    async def test_get_balance_parses_response(self, etherscan: EtherscanClient) -> None:
        mock_response = {"status": "1", "result": "1000000000000000000"}  # 1 ETH

        with patch.object(etherscan, "_get", new_callable=AsyncMock, return_value=mock_response):
            result = await etherscan.get_balance("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08")

        assert result["balance_eth"] == 1.0
        assert result["chain"] == "ethereum"

    @pytest.mark.asyncio
    async def test_get_transactions_parses_list(self, etherscan: EtherscanClient) -> None:
        mock_response = {
            "status": "1",
            "result": [
                {"hash": "0xabc", "from": "0x111", "to": "0x222", "value": "1000000000000000000"},
                {"hash": "0xdef", "from": "0x222", "to": "0x111", "value": "500000000000000000"},
            ]
        }

        with patch.object(etherscan, "_get", new_callable=AsyncMock, return_value=mock_response):
            txs = await etherscan.get_transactions("0x111")

        assert len(txs) == 2

    @pytest.mark.asyncio
    async def test_get_transactions_handles_no_results(self, etherscan: EtherscanClient) -> None:
        mock_response = {"status": "0", "message": "No transactions found", "result": "No transactions found"}

        with patch.object(etherscan, "_get", new_callable=AsyncMock, return_value=mock_response):
            txs = await etherscan.get_transactions("0x000")

        assert txs == []


class TestBlockstreamClient:
    @pytest.fixture
    def blockstream(self) -> BlockstreamClient:
        return BlockstreamClient()

    @pytest.mark.asyncio
    async def test_get_address_info(self, blockstream: BlockstreamClient) -> None:
        mock_data = {
            "chain_stats": {
                "funded_txo_sum": 100000000,  # 1 BTC received
                "spent_txo_sum": 50000000,  # 0.5 BTC spent
                "tx_count": 10,
            },
            "mempool_stats": {
                "funded_txo_sum": 0,
                "spent_txo_sum": 0,
                "tx_count": 0,
            },
        }

        with patch.object(blockstream, "_get", new_callable=AsyncMock, return_value=mock_data):
            result = await blockstream.get_address_info("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

        assert result["balance_btc"] == 0.5
        assert result["tx_count"] == 10
        assert result["chain"] == "bitcoin"


class TestCryptoFtMConversion:
    def test_eth_address_to_ftm(self) -> None:
        entity = crypto_address_to_ftm(
            "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08",
            "ethereum",
        )
        assert entity["schema"] == "Thing"
        assert "Ethereum Wallet" in entity["properties"]["name"][0]
        assert entity["_provenance"]["source"] == "blockchain_ethereum"
        assert entity["_crypto_metadata"]["chain"] == "ethereum"

    def test_btc_address_to_ftm(self) -> None:
        entity = crypto_address_to_ftm(
            "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
            "bitcoin",
        )
        assert entity["schema"] == "Thing"
        assert "Bitcoin Wallet" in entity["properties"]["name"][0]

    def test_address_with_summary(self) -> None:
        summary = {
            "balance_eth": 1.5,
            "transaction_count": 42,
            "top_counterparties": [{"address": "0xabc", "tx_count": 10}],
        }
        entity = crypto_address_to_ftm("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08", "ethereum", summary)
        assert entity["_crypto_metadata"]["tx_count"] == 42
