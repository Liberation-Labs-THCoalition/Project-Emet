"""Tests for emet.ftm.external.blockchain — Solana support + investigate_address.

Existing chain clients (Etherscan/Blockstream/Tronscan) are exercised
indirectly elsewhere (test_augmentation.py, test_mock_fidelity.py); this
file covers the new Solana chain and the unified investigate_address()
dispatcher.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.blockchain import (
    detect_chain,
    SolanaClient,
    SolanaConfig,
    BlockchainAdapter,
    BlockchainConfig,
    crypto_address_to_ftm,
    sol_transaction_to_ftm,
)


SOL_ADDRESS = "DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"
ETH_ADDRESS = "0x" + "a" * 40
TRX_ADDRESS = "T" + "a" * 33


class TestDetectChainSolana:
    def test_solana_address_detected(self):
        assert detect_chain(SOL_ADDRESS) == "solana"

    def test_tron_not_misclassified_as_solana(self):
        # Tron addresses are also valid base58 but must be caught first.
        assert detect_chain(TRX_ADDRESS) == "tron"

    def test_ethereum_still_detected(self):
        assert detect_chain(ETH_ADDRESS) == "ethereum"

    def test_garbage_returns_none(self):
        assert detect_chain("not-an-address!!") is None


class TestCryptoAddressToFtmSolana:
    def test_solana_entity(self):
        entity = crypto_address_to_ftm(SOL_ADDRESS, "solana")
        assert entity["schema"] == "Thing"
        assert "Solana" in entity["properties"]["description"][0]
        assert entity["_provenance"]["source"] == "blockchain_solana"
        assert "solscan.io" in entity["_provenance"]["source_url"]


class TestSolTransactionToFtm:
    def test_basic_conversion(self):
        tx = {"signature": "sig123", "slot": 100, "blockTime": 1700000000, "err": None}
        entity = sol_transaction_to_ftm(tx)
        assert entity["schema"] == "Payment"
        assert entity["properties"]["date"] == ["1700000000"]
        assert entity["_provenance"]["source_id"] == "sig123"
        assert entity["_relationship_hints"]["chain"] == "solana"

    def test_failed_transaction_noted(self):
        tx = {"signature": "sig456", "slot": 101, "blockTime": 1700000001, "err": {"InstructionError": []}}
        entity = sol_transaction_to_ftm(tx)
        assert "failed" in entity["properties"]["notes"][0].lower()


def _mock_httpx_post(json_payloads: list[dict]):
    """Build a mocked httpx.AsyncClient context manager whose .post() returns
    successive canned JSON responses (one per call, in order)."""
    responses = []
    for payload in json_payloads:
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        responses.append(resp)

    mock_client = AsyncMock()
    mock_client.post.side_effect = responses
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestSolanaClient:
    @pytest.mark.asyncio
    async def test_get_balance(self):
        mock_client = _mock_httpx_post([{"result": {"value": 2_500_000_000}}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            client = SolanaClient()
            result = await client.get_balance(SOL_ADDRESS)

        assert result["balance_lamports"] == 2_500_000_000
        assert result["balance_sol"] == pytest.approx(2.5)
        assert result["chain"] == "solana"

    @pytest.mark.asyncio
    async def test_get_signatures(self):
        mock_client = _mock_httpx_post([{
            "result": [
                {"signature": "sig1", "slot": 1, "blockTime": 100, "err": None},
                {"signature": "sig2", "slot": 2, "blockTime": 200, "err": {"x": 1}},
            ]
        }])
        with patch("httpx.AsyncClient", return_value=mock_client):
            client = SolanaClient()
            sigs = await client.get_signatures(SOL_ADDRESS)

        assert len(sigs) == 2
        assert sigs[0]["signature"] == "sig1"

    @pytest.mark.asyncio
    async def test_rpc_error_returns_none(self):
        mock_client = _mock_httpx_post([{"error": {"code": -1, "message": "boom"}}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            client = SolanaClient()
            result = await client._rpc("getBalance", [SOL_ADDRESS])

        assert result is None

    @pytest.mark.asyncio
    async def test_get_address_summary(self):
        mock_client = _mock_httpx_post([
            {"result": {"value": 1_000_000_000}},
            {"result": [{"signature": "sig1", "slot": 1, "blockTime": 100, "err": None}]},
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            client = SolanaClient()
            summary = await client.get_address_summary(SOL_ADDRESS)

        assert summary["balance_sol"] == pytest.approx(1.0)
        assert summary["transaction_count"] == 1
        assert summary["failed_transaction_count"] == 0


class TestInvestigateAddress:
    @pytest.mark.asyncio
    async def test_auto_detect_dispatches_to_ethereum(self):
        adapter = BlockchainAdapter(BlockchainConfig())
        fake_result = {
            "address": ETH_ADDRESS,
            "chain": "ethereum",
            "entities": [],
            "transactions": [],
            "top_counterparties": [],
        }
        with patch.object(adapter, "get_eth_address", AsyncMock(return_value=fake_result)):
            result = await adapter.investigate_address(ETH_ADDRESS)

        assert result["chain"] == "ethereum"
        assert "risk_assessment" in result
        assert "address_labels" in result

    @pytest.mark.asyncio
    async def test_explicit_chain_overrides_detection(self):
        adapter = BlockchainAdapter(BlockchainConfig())
        fake_result = {
            "address": SOL_ADDRESS,
            "chain": "solana",
            "entities": [],
            "transactions": [],
            "top_counterparties": [],
        }
        with patch.object(adapter, "get_sol_address", AsyncMock(return_value=fake_result)) as mocked:
            result = await adapter.investigate_address(SOL_ADDRESS, chain="solana")

        mocked.assert_awaited_once()
        assert result["chain"] == "solana"

    @pytest.mark.asyncio
    async def test_unrecognized_address_returns_error(self):
        adapter = BlockchainAdapter(BlockchainConfig())
        result = await adapter.investigate_address("garbage!!!")
        assert result["chain"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_risk_assessment_reflects_mixer_contact(self):
        adapter = BlockchainAdapter(BlockchainConfig())
        mixer_addr = "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc"
        fake_result = {
            "address": ETH_ADDRESS,
            "chain": "ethereum",
            "entities": [],
            "transactions": [
                {"to": mixer_addr, "from": ETH_ADDRESS, "hash": "0xdead"},
            ],
            "top_counterparties": [{"address": mixer_addr, "tx_count": 1}],
        }
        with patch.object(adapter, "get_eth_address", AsyncMock(return_value=fake_result)):
            result = await adapter.investigate_address(ETH_ADDRESS, chain="ethereum")

        assert result["risk_assessment"]["score"] > 0
        assert any(f["name"] == "mixer_contact" for f in result["risk_assessment"]["factors"])
        assert result["address_labels"][mixer_addr]["category"] == "mixer"
