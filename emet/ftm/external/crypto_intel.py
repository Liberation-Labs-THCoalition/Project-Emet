"""On-chain intelligence — mixer detection, address labeling, risk scoring, clustering.

This module is a pure-Python analysis/labeling layer over blockchain data that
has already been fetched (e.g. by :mod:`emet.ftm.external.blockchain`). It does
NOT make any network calls itself — everything here operates on transaction
dicts already in hand.

Capabilities:
    - Curated public registries of known mixer/tumbler, DeFi protocol, and
      exchange hot-wallet addresses (Ethereum mainnet).
    - ``classify_address``: label a single address against those registries.
    - ``assess_risk``: composite, evidence-backed risk scoring over a
      transaction history for a given address.
    - ``cluster_by_common_input``: UTXO co-spend clustering heuristic for
      Bitcoin-style transaction sets.

This intentionally generalizes the simpler ``_extract_cluster`` /
``_assess_risk`` helpers in :mod:`emet.ftm.external.augmentation` into a
standalone, better-documented, registry-backed module. The originals in
``augmentation.py`` are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Curated public registries (every entry auditable/public)
# ---------------------------------------------------------------------------
#
# NOTE: these are illustrative, well-known mainnet addresses drawn from public
# reporting (OFAC SDN list, protocol documentation, and public block explorer
# labels). In production this registry should be refreshed programmatically
# from the OFAC SDN list (https://sanctionssearch.ofac.treas.gov/ and the
# machine-readable SDN XML/CSV feed) plus a maintained exchange/DeFi label
# feed (e.g. Etherscan's public label-word-cloud or a paid attribution API).
# Do not treat this as exhaustive or as legal/compliance advice.

# OFAC-designated mixers/tumblers.
# Tornado Cash pools + router sanctioned 2022-08-08 (OFAC SDN list).
# Sinbad.io sanctioned 2023-11-29 (successor to Blender.io, North Korea-linked).
MIXER_ADDRESSES: dict[str, str] = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": "Tornado Cash: 0.1 ETH pool",
    "0x47ce0c6ed5b0ee3f31c6206f83c9b64a97e5b3d5": "Tornado Cash: 1 ETH pool",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": "Tornado Cash: 10 ETH pool",
    "0x5d64f6f34d80c8b3d6c3aa9e7ac6b45b1d2e21c9": "Tornado Cash: 100 ETH pool",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": "Tornado Cash: Router",
    "0xf7b10d603907658f690da534e9b7dbc4dae40b6": "Sinbad.io: mixer wallet",
}

# DeFi protocol contracts -> human labels (well-known mainnet addresses).
DEFI_PROTOCOLS: dict[str, str] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2: Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3: Router",
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9": "Aave V2: LendingPool",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave V3: Pool",
    "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7": "Curve: 3pool",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch: Aggregation Router V5",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x: Exchange Proxy",
    "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer: Vault",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap: Router",
}

# Known exchange hot wallets -> labels (publicly-documented, widely cited).
EXCHANGE_WALLETS: dict[str, str] = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance: Hot Wallet 14",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance: Hot Wallet 16",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase: Hot Wallet 1",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase: Hot Wallet 2",
}


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------


@dataclass
class AddressLabel:
    """Result of classifying a single address against the curated registries."""
    address: str
    is_mixer: bool = False
    is_defi: bool = False
    is_exchange: bool = False
    label: str = ""            # human-readable, e.g. "Tornado Cash: 1 ETH pool"
    category: str = "unknown"  # "mixer" | "defi" | "exchange" | "unknown"


def classify_address(address: str) -> AddressLabel:
    """Classify an address against the mixer/DeFi/exchange registries.

    Lowercase-normalizes the address before lookup (registries are keyed in
    lowercase). If an address somehow appears in multiple registries, mixer
    wins over exchange, which wins over DeFi — mixer contact is the strongest
    illicit-finance signal and should never be shadowed by a weaker label.
    """
    normalized = address.strip().lower()

    if normalized in MIXER_ADDRESSES:
        return AddressLabel(
            address=address,
            is_mixer=True,
            label=MIXER_ADDRESSES[normalized],
            category="mixer",
        )

    if normalized in EXCHANGE_WALLETS:
        return AddressLabel(
            address=address,
            is_exchange=True,
            label=EXCHANGE_WALLETS[normalized],
            category="exchange",
        )

    if normalized in DEFI_PROTOCOLS:
        return AddressLabel(
            address=address,
            is_defi=True,
            label=DEFI_PROTOCOLS[normalized],
            category="defi",
        )

    return AddressLabel(address=address)


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


@dataclass
class RiskFactor:
    """A single, evidence-backed contribution to a composite risk score."""
    name: str
    weight: float  # contribution to composite score, 0-1
    evidence: str  # human-readable, defensible, names the actual match found


@dataclass
class RiskAssessment:
    """Composite risk assessment for an address, built from named factors."""
    address: str
    score: float = 0.0
    risk_level: str = "low"  # "low" | "medium" | "high" | "critical"
    factors: list[RiskFactor] = field(default_factory=list)
    explanation: str = ""


# Same thresholds as ShellScore in emet/graph/algorithms.py.
_RISK_LEVEL_THRESHOLDS = (
    (0.7, "critical"),
    (0.5, "high"),
    (0.3, "medium"),
)

_HIGH_VOLUME_TX_THRESHOLD = 100
_DEFI_LAYERING_MIN_PROTOCOLS = 3

_MIXER_CONTACT_MAX_WEIGHT = 0.5
_HIGH_VOLUME_WEIGHT = 0.2
_DEFI_LAYERING_WEIGHT = 0.15
_NO_EXCHANGE_TOUCHPOINT_WEIGHT = 0.15


def _risk_level_for_score(score: float) -> str:
    for threshold, level in _RISK_LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return "low"


def _tx_counterparties(tx: dict[str, Any], address: str) -> tuple[str, str]:
    """Return (to, from) addresses for a tx dict, lowercased.

    Accepts Etherscan-style {'to':.., 'from':.., 'hash':..} txs (the only
    shape this function needs to understand — Bitcoin-style clustering is
    handled separately by cluster_by_common_input).
    """
    to_addr = str(tx.get("to", "") or "").lower()
    from_addr = str(tx.get("from", "") or "").lower()
    return to_addr, from_addr


def assess_risk(address: str, transactions: list[dict[str, Any]]) -> RiskAssessment:
    """Assess composite on-chain risk for ``address`` given its transactions.

    ``transactions`` is a list of tx dicts with at least 'to'/'from' style
    address fields (Etherscan-style: ``{'to':.., 'from':.., 'hash':..}``).

    Factors (composed additively, capped at 1.0):
      - mixer_contact (weight up to 0.5): direct tx to/from any
        MIXER_ADDRESSES entry — strongest single signal. Weight scales with
        the number of distinct mixer addresses contacted (more distinct
        mixer pools/services touched -> closer to the 0.5 cap), independent
        of how many factors are present.
      - high_volume (weight up to 0.2): tx count > 100 in the provided window.
      - defi_layering (weight up to 0.15): interactions with 3+ distinct
        DEFI_PROTOCOLS contracts (layering through multiple protocols is a
        common obfuscation pattern).
      - no_exchange_touchpoint (weight up to 0.15): funds never touch a known
        EXCHANGE_WALLETS address. Only added if at least one other factor is
        already active — a clean, low-volume, no-defi wallet with no
        exchange contact isn't inherently risky, it's just unused.
    """
    normalized_address = address.strip().lower()
    factors: list[RiskFactor] = []

    # --- mixer_contact ---
    mixer_hits: dict[str, list[str]] = {}  # mixer address -> [tx hashes]
    defi_hits: set[str] = set()
    touches_exchange = False

    for tx in transactions:
        to_addr, from_addr = _tx_counterparties(tx, normalized_address)
        tx_hash = str(tx.get("hash", tx.get("txid", "")) or "")

        for counterparty in (to_addr, from_addr):
            if not counterparty or counterparty == normalized_address:
                continue
            if counterparty in MIXER_ADDRESSES:
                mixer_hits.setdefault(counterparty, []).append(tx_hash)
            if counterparty in DEFI_PROTOCOLS:
                defi_hits.add(counterparty)
            if counterparty in EXCHANGE_WALLETS:
                touches_exchange = True

    if mixer_hits:
        # Scale toward the 0.5 cap with number of distinct mixer contacts;
        # a single mixer contact already carries most of the weight since
        # mixer contact alone is highly probative.
        distinct = len(mixer_hits)
        weight = min(_MIXER_CONTACT_MAX_WEIGHT, 0.35 + 0.05 * (distinct - 1))

        evidence_parts = []
        for mixer_addr, tx_hashes in mixer_hits.items():
            label = MIXER_ADDRESSES[mixer_addr]
            hash_preview = ", ".join(h for h in tx_hashes if h)
            count = len(tx_hashes)
            part = f"{count} direct interaction(s) with {label} ({mixer_addr})"
            if hash_preview:
                part += f" (txs: {hash_preview})"
            evidence_parts.append(part)

        factors.append(RiskFactor(
            name="mixer_contact",
            weight=weight,
            evidence="; ".join(evidence_parts),
        ))

    # --- high_volume ---
    tx_count = len(transactions)
    if tx_count > _HIGH_VOLUME_TX_THRESHOLD:
        factors.append(RiskFactor(
            name="high_volume",
            weight=_HIGH_VOLUME_WEIGHT,
            evidence=f"{tx_count} transactions observed in the provided window "
                     f"(exceeds threshold of {_HIGH_VOLUME_TX_THRESHOLD})",
        ))

    # --- defi_layering ---
    if len(defi_hits) >= _DEFI_LAYERING_MIN_PROTOCOLS:
        labels = sorted(DEFI_PROTOCOLS[a] for a in defi_hits)
        factors.append(RiskFactor(
            name="defi_layering",
            weight=_DEFI_LAYERING_WEIGHT,
            evidence=f"Interactions with {len(defi_hits)} distinct DeFi protocols: "
                     f"{', '.join(labels)}",
        ))

    # --- no_exchange_touchpoint (only meaningful alongside another factor) ---
    if factors and not touches_exchange:
        factors.append(RiskFactor(
            name="no_exchange_touchpoint",
            weight=_NO_EXCHANGE_TOUCHPOINT_WEIGHT,
            evidence=f"None of the {tx_count} observed transactions touch a known "
                     f"exchange hot wallet from the EXCHANGE_WALLETS registry",
        ))

    score = min(1.0, sum(f.weight for f in factors))
    risk_level = _risk_level_for_score(score)

    if factors:
        explanation = (
            f"Composite risk score {score:.2f} ({risk_level}) driven by: "
            + "; ".join(f"{f.name} (+{f.weight:.2f})" for f in factors)
        )
    else:
        explanation = (
            f"No risk factors triggered across {tx_count} observed transaction(s); "
            "score is 0.0 (low)."
        )

    return RiskAssessment(
        address=address,
        score=score,
        risk_level=risk_level,
        factors=factors,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# UTXO co-spend clustering
# ---------------------------------------------------------------------------


class _UnionFind:
    """Minimal union-find (disjoint set) for address clustering."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _extract_tx_inputs(tx: dict[str, Any]) -> list[str]:
    """Extract input addresses from a single tx dict.

    Supports both the Blockstream vin/prevout shape:
        {'vin': [{'prevout': {'scriptpubkey_address': '...'}}, ...], ...}
    and the simpler shape:
        {'inputs': ['addr1', 'addr2', ...]}
    """
    if "inputs" in tx:
        return [str(a).strip() for a in tx.get("inputs", []) if a]

    inputs: list[str] = []
    for vin in tx.get("vin", []):
        prevout = vin.get("prevout") or {}
        addr = prevout.get("scriptpubkey_address")
        if addr:
            inputs.append(str(addr).strip())
    return inputs


def cluster_by_common_input(transactions: list[dict[str, Any]]) -> list[list[str]]:
    """Cluster addresses via the UTXO common-input (co-spend) heuristic.

    Bitcoin-style wallets typically sign all inputs of a transaction with
    keys they control, so addresses that co-occur as multiple inputs of the
    same transaction are almost certainly controlled by the same wallet
    software/entity. This builds a graph where addresses are nodes and an
    edge connects any two addresses that co-occur as inputs in the same
    transaction, then returns the connected components.

    ``transactions`` may be a mix of the Blockstream vin/prevout shape
    (``{'vin': [{'prevout': {'scriptpubkey_address': '...'}}, ...], ...}``)
    or the simpler ``{'inputs': ['addr1', 'addr2', ...]}`` shape.

    Addresses that never co-occur with another address as inputs (e.g. a
    lone input, or a single-input tx) are excluded — there is no co-spend
    evidence to cluster them with anything, so they are not returned as
    singleton clusters.

    Returns clusters as a list of address lists, each de-duplicated and
    sorted, largest cluster first (ties broken by the sorted address list
    for determinism).
    """
    uf = _UnionFind()
    seen_addresses: set[str] = set()
    multi_input_addresses: set[str] = set()

    for tx in transactions:
        inputs = _extract_tx_inputs(tx)
        # De-duplicate within a single tx (an address paying itself as
        # multiple inputs of the same tx shouldn't fabricate co-spend edges).
        distinct_inputs = list(dict.fromkeys(inputs))

        for addr in distinct_inputs:
            seen_addresses.add(addr)

        if len(distinct_inputs) < 2:
            continue

        multi_input_addresses.update(distinct_inputs)
        first = distinct_inputs[0]
        for addr in distinct_inputs[1:]:
            uf.union(first, addr)

    groups: dict[str, list[str]] = {}
    for addr in multi_input_addresses:
        root = uf.find(addr)
        groups.setdefault(root, []).append(addr)

    clusters = [sorted(set(members)) for members in groups.values()]
    clusters.sort(key=lambda c: (-len(c), c))
    return clusters
