---
name: blockchain-forensics
description: "Blockchain investigation methodology for Emet's three-chain analysis (Ethereum, Bitcoin, Tron). Covers USDT-TRC20 sanctions evasion patterns, mixer detection heuristics, cross-chain hop tracking, counterparty clustering, and FtM entity conversion. Use this skill when investigating blockchain addresses, tracing illicit financial flows, or analyzing cryptocurrency transaction patterns."
---

# Blockchain Forensics for Emet

## Overview
Emet supports three blockchain chains through the `investigate_blockchain` tool, backed by `BlockchainAdapter` which unifies Etherscan (ETH), Blockstream (BTC), and Tronscan (TRX) clients. This skill covers investigation methodology for each chain and cross-chain analysis patterns.

## Chain Selection Guide

### Auto-Detection
Emet detects chains from address format:
- `0x` + 40 hex chars → Ethereum
- `bc1` / `1` / `3` prefix → Bitcoin
- `T` + 33 base58 chars → Tron

### When To Check Each Chain

**Ethereum** — Check when investigating:
- DeFi protocol interactions (Uniswap, Aave, etc.)
- NFT-related money laundering
- Smart contract-based obfuscation
- ERC-20 token transfers (USDT-ERC20, USDC)
- Known Ethereum mixers (Tornado Cash — OFAC designated)

**Bitcoin** — Check when investigating:
- Large-value transfers (BTC still preferred for high-value movement)
- Ransomware payments (historically BTC-denominated)
- CoinJoin or mixer usage
- Dark market transactions
- Legacy wallets from pre-Tron era

**Tron** — Check when investigating:
- USDT stablecoin transfers (Tron carries more USDT volume than Ethereum)
- Sanctions evasion (low fees make Tron preferred for frequent small transfers)
- OFAC-designated addresses (multiple Tron addresses on SDN list)
- East Asian and Southeast Asian financial flows
- Cross-border value transfer in regions with capital controls

### Why Tron Dominates Illicit Stablecoin Flows
Tron's low transaction fees ($0.01-0.50 vs Ethereum's $2-50+) make it the default rail for:
- Sanctions evasion via USDT-TRC20
- Money laundering through rapid hop sequences
- Illicit remittance networks
- Scam/fraud cashout operations

When a sanctions investigation surfaces any stablecoin activity, **always check Tron**.

## Investigation Patterns

### Pattern 1: Address Profiling
First step for any blockchain address:
```
investigate_blockchain(address="...", chain="auto", depth=1)
```
Returns:
- Balance (current holdings)
- Transaction count and volume
- Top counterparties (most frequent/largest transactors)
- Token transfers (ERC-20 on ETH, TRC-20 on Tron)
- First/last transaction dates (address lifetime)

**Interpret:**
- High volume, many counterparties → exchange or service
- Few counterparties, regular intervals → automated/programmatic
- Single large inflow, many small outflows → distribution wallet
- Many small inflows, single large outflow → collection/aggregation wallet

### Pattern 2: Counterparty Analysis
After profiling, investigate the top counterparties:
```
investigate_blockchain(address="<top_counterparty>", depth=1)
```

Build a map of the transaction network. Key patterns:
- **Hub-and-spoke:** Central wallet distributing to many → possible money service business
- **Chain:** A→B→C→D in sequence → layering/obfuscation
- **Fan-in/fan-out:** Many sources consolidate, then redistribute → mixing behavior
- **Round-trip:** A→B→A patterns → wash trading or fake volume

### Pattern 3: USDT-TRC20 Tracking (Tron)
Emet's TronscanClient specifically tracks TRC-20 token transfers. When investigating Tron:

1. Check `trc20_transfers` in results — these are separate from native TRX transfers
2. Filter for USDT contract: `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`
3. High USDT volume with low TRX balance = address used primarily for stablecoin transit
4. Rapid in/out USDT transfers (< 1 hour hold time) = likely intermediary in layering chain

### Pattern 4: Mixer/Obfuscation Detection

**Ethereum — Tornado Cash indicators:**
- Transactions to/from known Tornado Cash contracts
- Fixed denomination deposits (0.1, 1, 10, 100 ETH)
- Time delays between deposit and withdrawal
- Different deposit and withdrawal addresses

**Bitcoin — CoinJoin indicators:**
- Transactions with many inputs from different addresses
- Equal-value outputs (typical of CoinJoin rounds)
- Wasabi Wallet or JoinMarket transaction patterns
- Unusual output counts (50+ outputs in single transaction)

**Tron — Layering indicators:**
- Rapid multi-hop transfers (address holds funds < 10 minutes)
- Sequential forwarding through fresh addresses
- Consistent transfer amounts across hops (minus fees)
- Addresses with zero TRX balance but high USDT volume

### Pattern 5: Cross-Chain Hop Detection
Illicit actors frequently move value between chains:

1. **Bridge detection:** Look for interactions with cross-chain bridges
   - ETH ↔ Tron: common path for moving USDT between chains
   - BTC → ETH: typically through centralized exchanges or wrapped BTC (WBTC)
2. **Exchange deposit detection:** Funds sent to known exchange deposit addresses
   - Same entity may have addresses on multiple chains
   - Timing correlation between large outflow on one chain and inflow on another
3. **Value-matching:** When you can't trace directly, look for:
   - Matching amounts (minus fees) appearing on another chain within hours
   - Regular cadence of cross-chain transfers suggesting automated operation

## FtM Entity Conversion

All blockchain data converts to FtM entities:

| Chain Data | FtM Schema | Key Properties |
|-----------|------------|----------------|
| Address | `Thing` (crypto wallet) | address, chain, balance, firstSeen, lastSeen |
| Transaction | `Payment` | amount, currency, date, sourceUrl (block explorer) |
| Counterparty relationship | Implicit via Payment sender/receiver | |

**Source URLs generated automatically:**
- Ethereum: `https://etherscan.io/address/{address}`
- Bitcoin: `https://mempool.space/address/{address}`
- Tron: `https://tronscan.org/#/address/{address}`

## Integration with Other Emet Tools

### Blockchain → Graph Analysis
After investigating blockchain addresses, the resulting FtM entities flow into the session graph:
```
1. investigate_blockchain(address="0x...") → entities added to session
2. investigate_blockchain(address="<counterparty>") → more entities
3. analyze_graph(algorithm="community_detection") → find clusters in transaction network
4. analyze_graph(algorithm="centrality") → find most important wallets
```

### Blockchain → Sanctions Screening
Cross-reference discovered addresses against OFAC's SDN list:
```
1. investigate_blockchain(address="T...") → find counterparties
2. screen_sanctions(entities=[{name: "T<address>", entity_type: "CryptoWallet"}])
```
Note: OpenSanctions includes OFAC-designated blockchain addresses.

### Blockchain → Ownership Tracing
When blockchain investigation reveals an entity name (through exchange KYC leaks, ENS names, or public attribution):
```
1. investigate_blockchain → discover entity name associated with wallet
2. search_entities(query="<entity name>") → find in corporate registries
3. trace_ownership(entity_name="<entity name>") → beneficial ownership chain
```

## Red Flags Checklist

When reviewing blockchain investigation results, flag:

- [ ] Address appears on OFAC SDN list
- [ ] Transactions with OFAC-designated mixer (Tornado Cash, Blender.io)
- [ ] High-volume USDT-TRC20 with minimal hold times (< 1 hour)
- [ ] Fan-in/fan-out patterns suggesting structured layering
- [ ] Cross-chain value matching (same amounts appearing on multiple chains)
- [ ] Fresh addresses with single-purpose transaction patterns
- [ ] Regular automated transfer cadence suggesting programmatic operation
- [ ] Counterparty clusters in sanctioned jurisdictions
- [ ] Interaction with known darknet marketplace addresses
- [ ] Peel chain patterns (gradually reducing amounts across hops)

## Limitations

- **No on-chain clustering:** Emet uses API-level data (Etherscan, Blockstream, Tronscan) not raw blockchain analysis. Wallet clustering (determining multiple addresses belong to same entity) is inferred from counterparty patterns, not UTXO heuristics.
- **Historical depth:** Free API tiers limit transaction history retrieval. Very active addresses may have truncated history.
- **Privacy chains:** Monero, Zcash shielded transactions, and other privacy-preserving chains are not supported.
- **Attribution:** Emet cannot attribute addresses to real-world identities. It can flag patterns and cross-reference with sanctions lists, but address-to-identity mapping requires external intelligence.
