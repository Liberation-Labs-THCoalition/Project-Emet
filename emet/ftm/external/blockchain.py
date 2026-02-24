"""Blockchain explorer API clients for cryptocurrency investigation.

Provides basic on-chain investigation capabilities for Bitcoin,
Ethereum, and Tron via free public APIs. This covers the 80% case
of crypto investigation (balance checks, transaction history,
counterparty identification) without Chainalysis's $200K/year
proprietary attribution database.

Data sources:
    - Etherscan (Ethereum): Free tier at 5 req/sec, 100K req/day
    - Blockstream (Bitcoin): Free, no key required
    - Tronscan (Tron): Free, no key required

What this does:
    - Wallet balance lookup
    - Transaction history
    - Token transfer tracking (ERC-20)
    - Counterparty identification (top transaction partners)

What this does NOT do (Chainalysis/Elliptic territory):
    - Wallet clustering (mapping multiple addresses to same owner)
    - Mixer/tumbler detection
    - Smart contract analysis
    - DeFi protocol parsing
    - Exchange attribution
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from emet.ftm.external.converters import _provenance
from emet.ftm.external.rate_limit import TokenBucketLimiter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Address pattern detection
# ---------------------------------------------------------------------------

ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
BTC_ADDRESS_RE = re.compile(r"^(bc1[a-zA-HJ-NP-Z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
TRX_ADDRESS_RE = re.compile(r"^T[a-km-zA-HJ-NP-Z1-9]{33}$")


def detect_chain(address: str) -> str | None:
    """Detect which blockchain an address belongs to.

    Returns ``"ethereum"``, ``"bitcoin"``, ``"tron"``, or ``None``.
    """
    address = address.strip()
    if ETH_ADDRESS_RE.match(address):
        return "ethereum"
    if BTC_ADDRESS_RE.match(address):
        return "bitcoin"
    if TRX_ADDRESS_RE.match(address):
        return "tron"
    return None


# ---------------------------------------------------------------------------
# Etherscan (Ethereum)
# ---------------------------------------------------------------------------


@dataclass
class EtherscanConfig:
    """Configuration for Etherscan API.

    Free tier: 5 requests/second, 100K requests/day.
    Get a free API key at https://etherscan.io/apis
    """
    api_key: str = ""
    host: str = "https://api.etherscan.io/api"
    timeout_seconds: float = 15.0
    rate_limit_per_sec: float = 5.0


class EtherscanClient:
    """Async client for the Etherscan API (Ethereum).

    Provides balance lookups, transaction history, and ERC-20 token
    transfer tracking for Ethereum addresses.
    """

    def __init__(self, config: EtherscanConfig | None = None) -> None:
        self._config = config or EtherscanConfig()
        self._limiter = TokenBucketLimiter(rate=self._config.rate_limit_per_sec)

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make a rate-limited GET request to Etherscan."""
        await self._limiter.acquire()

        if self._config.api_key:
            params["apikey"] = self._config.api_key

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(self._config.host, params=params)
            resp.raise_for_status()
            data = resp.json()

            # Etherscan returns status "0" for errors
            if data.get("status") == "0" and data.get("message") != "No transactions found":
                logger.warning("Etherscan error: %s", data.get("result", data.get("message")))

            return data

    async def get_balance(self, address: str) -> dict[str, Any]:
        """Get ETH balance for an address.

        Returns balance in Wei and ETH.
        """
        data = await self._get({
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
        })

        balance_wei = int(data.get("result", "0"))
        balance_eth = balance_wei / 1e18

        return {
            "address": address,
            "balance_wei": balance_wei,
            "balance_eth": balance_eth,
            "chain": "ethereum",
        }

    async def get_transactions(
        self,
        address: str,
        page: int = 1,
        offset: int = 20,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        """Get normal (external) transactions for an address."""
        data = await self._get({
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": offset,
            "sort": sort,
        })

        txs = data.get("result", [])
        if isinstance(txs, str):
            return []
        return txs

    async def get_internal_transactions(
        self,
        address: str,
        page: int = 1,
        offset: int = 20,
    ) -> list[dict[str, Any]]:
        """Get internal (contract) transactions for an address."""
        data = await self._get({
            "module": "account",
            "action": "txlistinternal",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": offset,
            "sort": "desc",
        })

        txs = data.get("result", [])
        if isinstance(txs, str):
            return []
        return txs

    async def get_token_transfers(
        self,
        address: str,
        page: int = 1,
        offset: int = 20,
    ) -> list[dict[str, Any]]:
        """Get ERC-20 token transfers for an address."""
        data = await self._get({
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": offset,
            "sort": "desc",
        })

        txs = data.get("result", [])
        if isinstance(txs, str):
            return []
        return txs

    async def get_address_summary(self, address: str) -> dict[str, Any]:
        """Get a comprehensive summary of an Ethereum address.

        Returns balance, transaction count, top counterparties, and
        recent activity.
        """
        balance_data = await self.get_balance(address)
        txs = await self.get_transactions(address, offset=50)

        # Analyze counterparties
        counterparties: dict[str, dict[str, Any]] = {}
        total_in_wei = 0
        total_out_wei = 0

        for tx in txs:
            value_wei = int(tx.get("value", "0"))
            is_incoming = tx.get("to", "").lower() == address.lower()

            counterparty = tx.get("from", "") if is_incoming else tx.get("to", "")
            counterparty = counterparty.lower()

            if is_incoming:
                total_in_wei += value_wei
            else:
                total_out_wei += value_wei

            if counterparty and counterparty != address.lower():
                if counterparty not in counterparties:
                    counterparties[counterparty] = {
                        "address": counterparty,
                        "tx_count": 0,
                        "total_value_wei": 0,
                    }
                counterparties[counterparty]["tx_count"] += 1
                counterparties[counterparty]["total_value_wei"] += value_wei

        # Sort by total value
        top_counterparties = sorted(
            counterparties.values(),
            key=lambda c: c["total_value_wei"],
            reverse=True,
        )[:10]

        return {
            **balance_data,
            "transaction_count": len(txs),
            "total_received_eth": total_in_wei / 1e18,
            "total_sent_eth": total_out_wei / 1e18,
            "top_counterparties": top_counterparties,
        }


# ---------------------------------------------------------------------------
# Blockstream (Bitcoin)
# ---------------------------------------------------------------------------


@dataclass
class BlockstreamConfig:
    """Configuration for Blockstream API (Bitcoin).

    Free access, no API key required.
    """
    host: str = "https://blockstream.info/api"
    timeout_seconds: float = 15.0


class BlockstreamClient:
    """Async client for the Blockstream API (Bitcoin).

    Provides address lookups and transaction history for Bitcoin.
    """

    def __init__(self, config: BlockstreamConfig | None = None) -> None:
        self._config = config or BlockstreamConfig()

    async def _get(self, endpoint: str) -> Any:
        """Make a GET request to Blockstream API."""
        url = f"{self._config.host}{endpoint}"
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def get_address_info(self, address: str) -> dict[str, Any]:
        """Get address balance and transaction counts."""
        data = await self._get(f"/address/{address}")

        chain_stats = data.get("chain_stats", {})
        mempool_stats = data.get("mempool_stats", {})

        funded_sat = chain_stats.get("funded_txo_sum", 0) + mempool_stats.get("funded_txo_sum", 0)
        spent_sat = chain_stats.get("spent_txo_sum", 0) + mempool_stats.get("spent_txo_sum", 0)
        balance_sat = funded_sat - spent_sat

        return {
            "address": address,
            "balance_sat": balance_sat,
            "balance_btc": balance_sat / 1e8,
            "total_received_sat": funded_sat,
            "total_sent_sat": spent_sat,
            "tx_count": chain_stats.get("tx_count", 0) + mempool_stats.get("tx_count", 0),
            "chain": "bitcoin",
        }

    async def get_transactions(self, address: str) -> list[dict[str, Any]]:
        """Get recent transactions for a Bitcoin address.

        Returns up to 25 most recent confirmed transactions.
        """
        return await self._get(f"/address/{address}/txs")

    async def get_utxos(self, address: str) -> list[dict[str, Any]]:
        """Get unspent transaction outputs (UTXOs) for an address."""
        return await self._get(f"/address/{address}/utxo")

    async def get_address_summary(self, address: str) -> dict[str, Any]:
        """Get comprehensive Bitcoin address summary."""
        info = await self.get_address_info(address)
        txs = await self.get_transactions(address)

        # Analyze transaction patterns
        counterparties: dict[str, int] = {}  # address → tx count

        for tx in txs[:25]:  # Limit analysis to recent txs
            for vout in tx.get("vout", []):
                scriptpubkey_address = vout.get("scriptpubkey_address", "")
                if scriptpubkey_address and scriptpubkey_address != address:
                    counterparties[scriptpubkey_address] = (
                        counterparties.get(scriptpubkey_address, 0) + 1
                    )

        top_counterparties = sorted(
            [{"address": addr, "tx_count": count} for addr, count in counterparties.items()],
            key=lambda c: c["tx_count"],
            reverse=True,
        )[:10]

        return {
            **info,
            "recent_tx_count": len(txs),
            "top_counterparties": top_counterparties,
        }


# ---------------------------------------------------------------------------
# FtM conversion
# ---------------------------------------------------------------------------


def crypto_address_to_ftm(
    address: str,
    chain: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a cryptocurrency address to an FtM entity.

    Uses the ``Thing`` schema with custom properties since FtM doesn't
    have a native crypto wallet schema.
    """
    props: dict[str, list[str]] = {
        "name": [f"{chain.title()} Wallet {address[:8]}...{address[-6:]}"],
    }

    if chain == "ethereum":
        props["description"] = [f"Ethereum address: {address}"]
        source_url = f"https://etherscan.io/address/{address}"
    elif chain == "tron":
        props["description"] = [f"Tron address: {address}"]
        source_url = f"https://tronscan.org/#/address/{address}"
    else:
        props["description"] = [f"Bitcoin address: {address}"]
        source_url = f"https://blockstream.info/address/{address}"

    entity: dict[str, Any] = {
        "id": f"crypto:{chain}:{address}",
        "schema": "Thing",  # FtM doesn't have CryptoWallet — use Thing
        "properties": props,
        "_provenance": _provenance(
            source=f"blockchain_{chain}",
            source_id=address,
            source_url=source_url,
            confidence=1.0,
        ),
        "_crypto_metadata": {
            "chain": chain,
            "address": address,
        },
    }

    if summary:
        entity["_crypto_metadata"].update({
            "balance": summary.get(f"balance_{chain[:3]}", summary.get("balance_btc", summary.get("balance_eth", 0))),
            "tx_count": summary.get("transaction_count", summary.get("tx_count", 0)),
            "top_counterparties": summary.get("top_counterparties", []),
        })

    return entity


def crypto_transaction_to_ftm(
    tx: dict[str, Any],
    chain: str,
) -> dict[str, Any]:
    """Convert a blockchain transaction to an FtM Payment entity."""
    if chain == "ethereum":
        value_str = str(int(tx.get("value", "0")) / 1e18) + " ETH"
        from_addr = tx.get("from", "")
        to_addr = tx.get("to", "")
        tx_hash = tx.get("hash", "")
        timestamp = tx.get("timeStamp", "")
        source_url = f"https://etherscan.io/tx/{tx_hash}"
    else:
        # Bitcoin txs are more complex (multiple inputs/outputs)
        value_str = ""
        from_addr = ""
        to_addr = ""
        tx_hash = tx.get("txid", "")
        timestamp = str(tx.get("status", {}).get("block_time", ""))
        source_url = f"https://blockstream.info/tx/{tx_hash}"

    props: dict[str, list[str]] = {}
    if value_str:
        props["amountUsd"] = [value_str]  # Not actually USD, but closest FtM property
    if timestamp:
        props["date"] = [timestamp]

    return {
        "schema": "Payment",
        "properties": props,
        "_provenance": _provenance(
            source=f"blockchain_{chain}",
            source_id=tx_hash,
            source_url=source_url,
            confidence=1.0,
        ),
        "_relationship_hints": {
            "payer_address": from_addr,
            "beneficiary_address": to_addr,
            "chain": chain,
            "tx_hash": tx_hash,
        },
    }


# ---------------------------------------------------------------------------
# Tron (Tronscan) — free API, no key required
# ---------------------------------------------------------------------------


@dataclass
class TronscanConfig:
    """Configuration for Tronscan API.  Free, no authentication."""
    base_url: str = "https://apilist.tronscanapi.com/api"
    timeout_seconds: float = 20.0
    max_transactions: int = 50


class TronscanClient:
    """Async client for the Tronscan API.

    Tronscan provides free access to Tron blockchain data.
    Tron is the chain of choice for sanctions evasion and illicit payments
    due to cheap USDT-TRC20 transfers (~$1 fee vs $5–$50 on Ethereum).
    """

    def __init__(self, config: TronscanConfig | None = None) -> None:
        self._config = config or TronscanConfig()

    async def get_account_info(self, address: str) -> dict[str, Any]:
        """Get account overview for a Tron address."""
        url = f"{self._config.base_url}/accountv2?address={address}"

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def get_transactions(
        self,
        address: str,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Get transactions for a Tron address."""
        max_txs = limit or self._config.max_transactions
        url = (
            f"{self._config.base_url}/transaction"
            f"?sort=-timestamp&count=true&limit={max_txs}&start=0"
            f"&address={address}"
        )

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", [])

    async def get_trc20_transfers(
        self,
        address: str,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Get TRC-20 token transfers (USDT, etc.) for an address.

        This is the critical data for sanctions evasion tracking —
        most illicit Tron activity uses USDT-TRC20.
        """
        max_txs = limit or self._config.max_transactions
        url = (
            f"{self._config.base_url}/filter/trc20/transfers"
            f"?limit={max_txs}&start=0&sort=-timestamp"
            f"&relatedAddress={address}"
        )

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        return data.get("token_transfers", [])

    async def get_address_summary(self, address: str) -> dict[str, Any]:
        """Get combined summary of a Tron address."""
        account = await self.get_account_info(address)
        txs = await self.get_transactions(address, limit=20)
        trc20 = await self.get_trc20_transfers(address, limit=20)

        # Extract balance (in SUN, divide by 1e6 for TRX)
        balance_sun = account.get("balance", 0)
        balance_trx = balance_sun / 1_000_000

        # Count USDT transfers specifically
        usdt_transfers = [
            t for t in trc20
            if t.get("tokenInfo", {}).get("tokenAbbr", "").upper() == "USDT"
        ]

        # Top counterparties
        counterparties: dict[str, int] = {}
        for tx in txs:
            owner = tx.get("ownerAddress", "")
            to = tx.get("toAddress", "")
            peer = to if owner == address else owner
            if peer:
                counterparties[peer] = counterparties.get(peer, 0) + 1

        sorted_peers = sorted(counterparties.items(), key=lambda x: -x[1])[:5]

        return {
            "address": address,
            "chain": "tron",
            "balance_trx": balance_trx,
            "transaction_count": account.get("transactions", 0),
            "trc20_transfer_count": len(trc20),
            "usdt_transfer_count": len(usdt_transfers),
            "top_counterparties": [
                {"address": addr, "tx_count": count}
                for addr, count in sorted_peers
            ],
            "transactions": txs[:10],
            "trc20_transfers": trc20[:10],
        }


def tron_transaction_to_ftm(tx: dict[str, Any]) -> dict[str, Any]:
    """Convert a Tron transaction to FtM Payment entity."""
    from_addr = tx.get("ownerAddress", "")
    to_addr = tx.get("toAddress", "")
    tx_hash = tx.get("hash", "")
    timestamp = str(tx.get("timestamp", ""))
    value = tx.get("amount", 0)
    value_trx = value / 1_000_000 if value else 0

    props: dict[str, list[str]] = {}
    if value_trx:
        props["amountUsd"] = [f"{value_trx:.6f} TRX"]
    if timestamp:
        props["date"] = [timestamp]

    return {
        "schema": "Payment",
        "properties": props,
        "_provenance": _provenance(
            source="blockchain_tron",
            source_id=tx_hash,
            source_url=f"https://tronscan.org/#/transaction/{tx_hash}",
            confidence=1.0,
        ),
        "_relationship_hints": {
            "payer_address": from_addr,
            "beneficiary_address": to_addr,
            "chain": "tron",
            "tx_hash": tx_hash,
        },
    }


# ---------------------------------------------------------------------------
# Unified BlockchainAdapter
# ---------------------------------------------------------------------------


@dataclass
class BlockchainConfig:
    """Configuration for the unified blockchain adapter."""
    etherscan_config: EtherscanConfig = field(default_factory=EtherscanConfig)
    blockstream_config: BlockstreamConfig = field(default_factory=BlockstreamConfig)
    tronscan_config: TronscanConfig = field(default_factory=TronscanConfig)


class BlockchainAdapter:
    """Unified adapter across ETH, BTC, and Tron chains.

    Routes requests to the appropriate chain client and returns
    FtM entities + raw data.
    """

    def __init__(self, config: BlockchainConfig | None = None) -> None:
        cfg = config or BlockchainConfig()
        self._eth = EtherscanClient(cfg.etherscan_config)
        self._btc = BlockstreamClient(cfg.blockstream_config)
        self._tron = TronscanClient(cfg.tronscan_config)

    async def get_eth_address(self, address: str) -> dict[str, Any]:
        """Investigate an Ethereum address."""
        summary = await self._eth.get_address_summary(address)
        entity = crypto_address_to_ftm(address, "ethereum", summary)
        txs = summary.get("transactions", [])
        tx_entities = [crypto_transaction_to_ftm(tx, "ethereum") for tx in txs[:10]]
        return {
            "address": address,
            "chain": "ethereum",
            "entities": [entity] + tx_entities,
            **summary,
        }

    async def get_btc_address(self, address: str) -> dict[str, Any]:
        """Investigate a Bitcoin address."""
        summary = await self._btc.get_address_summary(address)
        entity = crypto_address_to_ftm(address, "bitcoin", summary)
        txs = summary.get("transactions", [])
        tx_entities = [crypto_transaction_to_ftm(tx, "bitcoin") for tx in txs[:10]]
        return {
            "address": address,
            "chain": "bitcoin",
            "entities": [entity] + tx_entities,
            **summary,
        }

    async def get_tron_address(self, address: str) -> dict[str, Any]:
        """Investigate a Tron address."""
        summary = await self._tron.get_address_summary(address)
        entity = crypto_address_to_ftm(address, "tron", summary)
        txs = summary.get("transactions", [])
        tx_entities = [tron_transaction_to_ftm(tx) for tx in txs[:10]]
        return {
            "address": address,
            "chain": "tron",
            "entities": [entity] + tx_entities,
            **summary,
        }
