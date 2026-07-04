"""On-chain intelligence: mixer detection, DeFi labels, wallet clustering.

Layers analytic signal on top of the raw explorer data from
``blockchain.py``. None of this needs a paid attribution database — it
uses public, well-known address labels plus structural heuristics:

    - **Mixer / tumbler detection** — flags interaction with known
      coin-mixing services (Tornado Cash routers, Wasabi/Samourai
      coordinators, Sinbad, etc.). Interacting with a mixer is a strong
      obfuscation signal in sanctions-evasion and laundering cases.
    - **DeFi protocol labels** — resolves counterparty addresses to
      known protocol contracts (Uniswap, Aave, Curve, 1inch, …) so an
      investigator can see *what* an address was doing, not just where
      value went.
    - **Wallet clustering** — groups addresses likely under common
      control via the co-spend / common-input heuristic (Bitcoin) and
      repeated-counterparty heuristic (account-model chains).

The label registries are intentionally small, curated, and auditable —
extend them from public OFAC SDN crypto listings and Etherscan public
name tags. Every flag carries its evidence so reports stay defensible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known-address registries (public, curated, auditable)
# ---------------------------------------------------------------------------

# Known mixer / tumbler contracts and coordinators. Lower-cased.
# Sources: OFAC SDN crypto designations, Etherscan public name tags.
KNOWN_MIXERS: dict[str, str] = {
    # Tornado Cash routers / pools (OFAC-designated Aug 2022)
    "0x8589427373d6d84e98730d7795d8f6f8731fda16": "Tornado Cash: Router",
    "0x722122df12d4e14e13ac3b6895a86e84145b6967": "Tornado Cash: Proxy",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": "Tornado Cash: 10 ETH",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": "Tornado Cash: 10 ETH pool",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": "Tornado Cash: 100 ETH pool",
    # Sinbad.io (OFAC-designated Nov 2023, Bitcoin)
    "bc1qw2c3lxufxqe2x9s4rdzh65tpf4d7fs3xtev9na": "Sinbad.io mixer",
}

# Known DeFi protocol contracts → human label. Lower-cased.
DEFI_LABELS: dict[str, str] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2: Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3: Router",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap: Universal Router",
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9": "Aave: Lending Pool V2",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave: Pool V3",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch: Aggregation Router V5",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x: Exchange Proxy",
    "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer: Vault",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap: Router",
}

# Known centralized-exchange deposit/hot wallets → label. Lower-cased.
KNOWN_EXCHANGES: dict[str, str] = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance: Hot Wallet 14",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance: Hot Wallet 15",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase 1",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase 2",
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": "Coinbase 10",
}


def _norm(addr: str) -> str:
    return (addr or "").strip().lower()


def label_address(address: str) -> dict[str, Any] | None:
    """Resolve an address to a known label, if any.

    Returns ``{"label": str, "category": "mixer"|"defi"|"exchange"}`` or
    ``None`` when the address is unknown.
    """
    a = _norm(address)
    if a in KNOWN_MIXERS:
        return {"label": KNOWN_MIXERS[a], "category": "mixer"}
    if a in DEFI_LABELS:
        return {"label": DEFI_LABELS[a], "category": "defi"}
    if a in KNOWN_EXCHANGES:
        return {"label": KNOWN_EXCHANGES[a], "category": "exchange"}
    return None


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------


@dataclass
class MixerFlag:
    """A detected interaction with a known mixer/tumbler."""

    counterparty: str
    label: str
    direction: str  # "sent_to" | "received_from"
    evidence: str = ""


@dataclass
class ChainAnalysis:
    """Structured on-chain intelligence for one address."""

    address: str
    chain: str
    mixer_flags: list[MixerFlag] = field(default_factory=list)
    defi_interactions: list[dict[str, str]] = field(default_factory=list)
    exchange_interactions: list[dict[str, str]] = field(default_factory=list)
    risk_score: float = 0.0
    risk_level: str = "low"
    risk_factors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


def _counterparties(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract counterparty address records from an explorer summary."""
    cps: list[dict[str, Any]] = []
    cps.extend(summary.get("top_counterparties", []) or [])
    # Also scan raw transactions for from/to.
    for tx in summary.get("transactions", []) or []:
        for key, direction in (("from", "received_from"), ("to", "sent_to")):
            addr = tx.get(key)
            if addr:
                cps.append({"address": addr, "direction": direction})
    return cps


def analyze_chain_activity(
    address: str, chain: str, summary: dict[str, Any]
) -> ChainAnalysis:
    """Run mixer/DeFi/exchange detection and risk scoring on explorer data.

    ``summary`` is the dict returned by ``BlockchainAdapter.get_*_address``
    (balance, transaction_count, top_counterparties, transactions).
    """
    analysis = ChainAnalysis(address=address, chain=chain)

    seen: set[str] = set()
    for cp in _counterparties(summary):
        cp_addr = cp.get("address", "")
        if not cp_addr:
            continue
        key = _norm(cp_addr)
        if key in seen:
            continue
        seen.add(key)

        labeled = label_address(cp_addr)
        if not labeled:
            continue
        direction = cp.get("direction", "interacted_with")
        if labeled["category"] == "mixer":
            analysis.mixer_flags.append(
                MixerFlag(
                    counterparty=cp_addr,
                    label=labeled["label"],
                    direction=direction,
                    evidence=f"{direction} {labeled['label']} ({cp_addr})",
                )
            )
        elif labeled["category"] == "defi":
            analysis.defi_interactions.append(
                {"address": cp_addr, "protocol": labeled["label"], "direction": direction}
            )
        elif labeled["category"] == "exchange":
            analysis.exchange_interactions.append(
                {"address": cp_addr, "exchange": labeled["label"], "direction": direction}
            )

    _score_risk(analysis, summary)
    return analysis


def _score_risk(analysis: ChainAnalysis, summary: dict[str, Any]) -> None:
    """Compute a 0–1 risk score with named, defensible factors."""
    score = 0.0
    if analysis.mixer_flags:
        score += 0.6
        analysis.risk_factors.append(
            f"Interacted with {len(analysis.mixer_flags)} known mixer(s)"
        )
    tx_count = summary.get("transaction_count", summary.get("tx_count", 0)) or 0
    if tx_count > 1000:
        score += 0.15
        analysis.risk_factors.append(f"High transaction volume ({tx_count})")
    if len(analysis.defi_interactions) > 5:
        score += 0.1
        analysis.risk_factors.append("Heavy DeFi usage (layering surface)")
    if not analysis.exchange_interactions and analysis.mixer_flags:
        score += 0.1
        analysis.risk_factors.append("No exchange touchpoints — pure obfuscation path")

    analysis.risk_score = round(min(score, 1.0), 3)
    if analysis.risk_score >= 0.6:
        analysis.risk_level = "high"
    elif analysis.risk_score >= 0.3:
        analysis.risk_level = "medium"
    else:
        analysis.risk_level = "low"


# ---------------------------------------------------------------------------
# Wallet clustering (co-spend / common-input heuristic)
# ---------------------------------------------------------------------------


@dataclass
class WalletCluster:
    """A set of addresses inferred to share common control."""

    seed_address: str
    chain: str
    members: list[str] = field(default_factory=list)
    heuristic: str = ""
    confidence: float = 0.0


def cluster_by_common_input(
    seed_address: str,
    transactions: list[dict[str, Any]],
    chain: str = "bitcoin",
) -> WalletCluster:
    """Cluster addresses via the common-input-ownership heuristic.

    In UTXO chains, all input addresses of a single transaction are
    (almost always) controlled by one entity. We collect every address
    that appears as a co-input alongside the seed.
    """
    members: set[str] = {_norm(seed_address)}
    for tx in transactions:
        inputs = tx.get("inputs") or tx.get("vin") or []
        input_addrs = set()
        for inp in inputs:
            if isinstance(inp, dict):
                addr = (
                    inp.get("address")
                    or inp.get("prevout", {}).get("scriptpubkey_address", "")
                )
            else:
                addr = str(inp)
            if addr:
                input_addrs.add(_norm(addr))
        if _norm(seed_address) in input_addrs:
            members |= input_addrs

    members.discard("")
    return WalletCluster(
        seed_address=seed_address,
        chain=chain,
        members=sorted(members),
        heuristic="common-input-ownership",
        confidence=0.8 if len(members) > 1 else 0.0,
    )
