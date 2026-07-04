"""Tests for on-chain intelligence: mixers, DeFi labels, clustering."""

from __future__ import annotations

from emet.ftm.external.blockchain import detect_chain
from emet.ftm.external.crypto_intel import (
    analyze_chain_activity,
    cluster_by_common_input,
    label_address,
)

TORNADO = "0x8589427373d6d84e98730d7795d8f6f8731fda16"
UNISWAP = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"


class TestChainDetection:
    def test_solana_detected(self):
        assert detect_chain("4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T") == "solana"

    def test_tron_precedence_over_solana(self):
        # A valid Tron address must resolve to tron, not solana.
        assert detect_chain("TJRyWwFs9wTFGZg3JbrVriFbNfCug5tDeC") == "tron"

    def test_unknown(self):
        assert detect_chain("not-an-address!!") is None


class TestLabeling:
    def test_mixer_label(self):
        assert label_address(TORNADO)["category"] == "mixer"

    def test_defi_label(self):
        assert label_address(UNISWAP)["category"] == "defi"

    def test_exchange_label(self):
        assert label_address(BINANCE)["category"] == "exchange"

    def test_unknown_label(self):
        assert label_address("0x" + "1" * 40) is None

    def test_case_insensitive(self):
        assert label_address(TORNADO.upper())["category"] == "mixer"


class TestAnalysis:
    def test_mixer_interaction_flags_high_risk(self):
        summary = {
            "transaction_count": 50,
            "top_counterparties": [{"address": TORNADO, "direction": "sent_to"}],
        }
        analysis = analyze_chain_activity("0x" + "a" * 40, "ethereum", summary)
        assert len(analysis.mixer_flags) == 1
        assert analysis.risk_level == "high"
        assert analysis.risk_score >= 0.6

    def test_clean_address_low_risk(self):
        summary = {
            "transaction_count": 5,
            "top_counterparties": [{"address": UNISWAP, "direction": "sent_to"}],
        }
        analysis = analyze_chain_activity("0x" + "b" * 40, "ethereum", summary)
        assert not analysis.mixer_flags
        assert analysis.risk_level == "low"
        assert len(analysis.defi_interactions) == 1

    def test_counterparties_from_raw_transactions(self):
        summary = {
            "transaction_count": 2,
            "transactions": [{"to": TORNADO}, {"from": BINANCE}],
        }
        analysis = analyze_chain_activity("0x" + "c" * 40, "ethereum", summary)
        assert analysis.mixer_flags
        assert analysis.exchange_interactions


class TestClustering:
    def test_common_input_clusters(self):
        txs = [{"inputs": [{"address": "bc1seed"}, {"address": "bc1sibling"}]}]
        cluster = cluster_by_common_input("bc1seed", txs)
        assert set(cluster.members) == {"bc1seed", "bc1sibling"}
        assert cluster.confidence == 0.8

    def test_no_co_inputs_no_cluster(self):
        txs = [{"inputs": [{"address": "bc1other"}]}]
        cluster = cluster_by_common_input("bc1seed", txs)
        assert cluster.members == ["bc1seed"]
        assert cluster.confidence == 0.0

    def test_vin_prevout_shape(self):
        txs = [
            {
                "vin": [
                    {"prevout": {"scriptpubkey_address": "bc1seed"}},
                    {"prevout": {"scriptpubkey_address": "bc1co"}},
                ]
            }
        ]
        cluster = cluster_by_common_input("bc1seed", txs)
        assert "bc1co" in cluster.members
