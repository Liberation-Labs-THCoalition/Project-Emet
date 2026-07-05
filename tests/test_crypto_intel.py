"""Tests for on-chain intelligence: mixer detection, labeling, risk scoring,
and UTXO clustering — emet.ftm.external.crypto_intel."""

from __future__ import annotations

from emet.ftm.external.crypto_intel import (
    MIXER_ADDRESSES,
    DEFI_PROTOCOLS,
    EXCHANGE_WALLETS,
    AddressLabel,
    RiskFactor,
    RiskAssessment,
    classify_address,
    assess_risk,
    cluster_by_common_input,
)


# ===========================================================================
# classify_address
# ===========================================================================


class TestClassifyAddress:
    def test_known_mixer_address(self):
        mixer_addr = next(iter(MIXER_ADDRESSES))
        result = classify_address(mixer_addr)
        assert isinstance(result, AddressLabel)
        assert result.is_mixer is True
        assert result.is_defi is False
        assert result.is_exchange is False
        assert result.category == "mixer"
        assert result.label == MIXER_ADDRESSES[mixer_addr]

    def test_known_mixer_address_case_insensitive(self):
        mixer_addr = next(iter(MIXER_ADDRESSES))
        result = classify_address(mixer_addr.upper())
        assert result.is_mixer is True
        assert result.category == "mixer"

    def test_known_defi_address(self):
        defi_addr = next(iter(DEFI_PROTOCOLS))
        result = classify_address(defi_addr)
        assert result.is_defi is True
        assert result.is_mixer is False
        assert result.is_exchange is False
        assert result.category == "defi"
        assert result.label == DEFI_PROTOCOLS[defi_addr]

    def test_known_exchange_address(self):
        exch_addr = next(iter(EXCHANGE_WALLETS))
        result = classify_address(exch_addr)
        assert result.is_exchange is True
        assert result.is_mixer is False
        assert result.is_defi is False
        assert result.category == "exchange"
        assert result.label == EXCHANGE_WALLETS[exch_addr]

    def test_unknown_address(self):
        unknown = "0x000000000000000000000000000000deadbeef"
        result = classify_address(unknown)
        assert result.category == "unknown"
        assert result.is_mixer is False
        assert result.is_defi is False
        assert result.is_exchange is False
        assert result.label == ""

    def test_registries_are_disjoint(self):
        # Sanity check on the curated data itself: no address should appear
        # in more than one registry (would silently trigger the mixer >
        # exchange > defi priority rule and mask a data-entry mistake).
        mixer_keys = set(MIXER_ADDRESSES)
        defi_keys = set(DEFI_PROTOCOLS)
        exch_keys = set(EXCHANGE_WALLETS)
        assert not (mixer_keys & defi_keys)
        assert not (mixer_keys & exch_keys)
        assert not (defi_keys & exch_keys)


# ===========================================================================
# assess_risk
# ===========================================================================


class TestAssessRisk:
    def test_mixer_contact_factor(self):
        wallet = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        mixer_addr = next(iter(MIXER_ADDRESSES))
        txs = [
            {"hash": "0xabc111", "from": wallet, "to": mixer_addr},
            {"hash": "0xabc222", "from": wallet, "to": mixer_addr},
            {"hash": "0xabc333", "from": mixer_addr, "to": wallet},
        ]

        result = assess_risk(wallet, txs)

        assert isinstance(result, RiskAssessment)
        mixer_factors = [f for f in result.factors if f.name == "mixer_contact"]
        assert len(mixer_factors) == 1
        factor = mixer_factors[0]
        assert mixer_addr in factor.evidence
        assert MIXER_ADDRESSES[mixer_addr] in factor.evidence
        # All three tx hashes should be named in the evidence string.
        assert "0xabc111" in factor.evidence
        assert "0xabc222" in factor.evidence
        assert "0xabc333" in factor.evidence

        assert result.score > 0
        assert result.risk_level == _expected_level(result.score)

    def test_high_volume_no_mixer_or_defi(self):
        wallet = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        benign_counterparty = "0xcccccccccccccccccccccccccccccccccccccccc"
        txs = [
            {"hash": f"0xtx{i}", "from": wallet, "to": benign_counterparty}
            for i in range(150)
        ]

        result = assess_risk(wallet, txs)

        factor_names = {f.name for f in result.factors}
        assert "high_volume" in factor_names
        assert "mixer_contact" not in factor_names
        assert "defi_layering" not in factor_names

        high_volume_factor = next(f for f in result.factors if f.name == "high_volume")
        assert "150" in high_volume_factor.evidence

        assert result.risk_level == _expected_level(result.score)

    def test_clean_low_tx_wallet_no_exchange_touchpoint_absent(self):
        wallet = "0xdddddddddddddddddddddddddddddddddddddddd"
        benign_counterparty = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        txs = [
            {"hash": "0xclean1", "from": wallet, "to": benign_counterparty},
            {"hash": "0xclean2", "from": benign_counterparty, "to": wallet},
        ]

        result = assess_risk(wallet, txs)

        assert result.factors == []
        assert result.score == 0.0
        assert result.risk_level == "low"

        factor_names = {f.name for f in result.factors}
        assert "no_exchange_touchpoint" not in factor_names

    def test_no_exchange_touchpoint_present_alongside_other_factor(self):
        wallet = "0xffffffffffffffffffffffffffffffffffffffff"
        mixer_addr = next(iter(MIXER_ADDRESSES))
        txs = [{"hash": "0xmixtx", "from": wallet, "to": mixer_addr}]

        result = assess_risk(wallet, txs)

        factor_names = {f.name for f in result.factors}
        assert "mixer_contact" in factor_names
        assert "no_exchange_touchpoint" in factor_names

        no_exch_factor = next(
            f for f in result.factors if f.name == "no_exchange_touchpoint"
        )
        assert "EXCHANGE_WALLETS" in no_exch_factor.evidence or "exchange" in no_exch_factor.evidence.lower()

    def test_exchange_touchpoint_suppresses_no_exchange_factor(self):
        wallet = "0x1111111111111111111111111111111111111a"
        mixer_addr = next(iter(MIXER_ADDRESSES))
        exch_addr = next(iter(EXCHANGE_WALLETS))
        txs = [
            {"hash": "0xmixtx", "from": wallet, "to": mixer_addr},
            {"hash": "0xexchtx", "from": wallet, "to": exch_addr},
        ]

        result = assess_risk(wallet, txs)

        factor_names = {f.name for f in result.factors}
        assert "mixer_contact" in factor_names
        assert "no_exchange_touchpoint" not in factor_names

    def test_defi_layering_factor(self):
        wallet = "0x2222222222222222222222222222222222222b"
        defi_addrs = list(DEFI_PROTOCOLS)[:3]
        txs = [
            {"hash": f"0xdefi{i}", "from": wallet, "to": addr}
            for i, addr in enumerate(defi_addrs)
        ]

        result = assess_risk(wallet, txs)

        factor_names = {f.name for f in result.factors}
        assert "defi_layering" in factor_names
        defi_factor = next(f for f in result.factors if f.name == "defi_layering")
        for addr in defi_addrs:
            assert DEFI_PROTOCOLS[addr] in defi_factor.evidence

    def test_score_capped_at_one(self):
        wallet = "0x3333333333333333333333333333333333333c"
        mixer_addrs = list(MIXER_ADDRESSES)
        defi_addrs = list(DEFI_PROTOCOLS)[:3]
        txs = [
            {"hash": f"0xmix{i}", "from": wallet, "to": addr}
            for i, addr in enumerate(mixer_addrs)
        ]
        txs += [
            {"hash": f"0xdefi{i}", "from": wallet, "to": addr}
            for i, addr in enumerate(defi_addrs)
        ]
        txs += [
            {"hash": f"0xbulk{i}", "from": wallet, "to": "0x9999999999999999999999999999999999999d"}
            for i in range(150)
        ]

        result = assess_risk(wallet, txs)
        assert result.score <= 1.0


def _expected_level(score: float) -> str:
    if score >= 0.7:
        return "critical"
    if score >= 0.5:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


# ===========================================================================
# cluster_by_common_input
# ===========================================================================


class TestClusterByCommonInput:
    def test_simple_inputs_shape_transitive_closure(self):
        transactions = [
            {"inputs": ["addrA", "addrB"]},
            {"inputs": ["addrB", "addrC"]},
            {"inputs": ["addrD"]},  # unrelated, single input
        ]

        clusters = cluster_by_common_input(transactions)

        # A, B, C should be merged via transitive closure through B.
        merged = [c for c in clusters if set(c) >= {"addrA", "addrB", "addrC"}]
        assert len(merged) == 1
        assert merged[0] == sorted(["addrA", "addrB", "addrC"])

        # D never co-occurs with anything, so it must not appear anywhere.
        all_addrs = {a for cluster in clusters for a in cluster}
        assert "addrD" not in all_addrs

    def test_blockstream_vin_prevout_shape(self):
        transactions = [
            {
                "vin": [
                    {"prevout": {"scriptpubkey_address": "addrA"}},
                    {"prevout": {"scriptpubkey_address": "addrB"}},
                ]
            },
            {
                "vin": [
                    {"prevout": {"scriptpubkey_address": "addrB"}},
                    {"prevout": {"scriptpubkey_address": "addrC"}},
                ]
            },
            {
                "vin": [
                    {"prevout": {"scriptpubkey_address": "addrD"}},
                ]
            },
        ]

        clusters = cluster_by_common_input(transactions)

        merged = [c for c in clusters if set(c) >= {"addrA", "addrB", "addrC"}]
        assert len(merged) == 1
        assert merged[0] == sorted(["addrA", "addrB", "addrC"])

        all_addrs = {a for cluster in clusters for a in cluster}
        assert "addrD" not in all_addrs

    def test_mixed_shapes_and_ordering_largest_first(self):
        transactions = [
            {"inputs": ["x1", "x2", "x3", "x4"]},
            {
                "vin": [
                    {"prevout": {"scriptpubkey_address": "y1"}},
                    {"prevout": {"scriptpubkey_address": "y2"}},
                ]
            },
        ]

        clusters = cluster_by_common_input(transactions)

        assert len(clusters) == 2
        assert clusters[0] == ["x1", "x2", "x3", "x4"]
        assert clusters[1] == ["y1", "y2"]

    def test_empty_input(self):
        assert cluster_by_common_input([]) == []

    def test_no_multi_input_transactions_yields_no_clusters(self):
        transactions = [
            {"inputs": ["solo1"]},
            {"vin": [{"prevout": {"scriptpubkey_address": "solo2"}}]},
        ]
        assert cluster_by_common_input(transactions) == []
