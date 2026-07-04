# Emet — Fable 5 Upgrade

_Investigative intelligence agent — audit, data-source expansion, graph
intelligence, blockchain, reporting, and TruthStrike integration._

**Branch:** `fable-upgrade-2026`
**Baseline:** 1,751 tests passing / 33 skipped (main, pre-upgrade)
**Scope:** additive — no existing capability removed; every new module is
tested and wired into the federation / API / graph layers it belongs to.

---

## 1. Audit — state of the codebase before this upgrade

The pre-upgrade repo is substantially real: ~37.5K LOC across the `emet/`
package, a working NetworkX graph engine, reportlab PDF pipeline,
FollowTheMoney data spine, an autonomous agent loop, and MCP + HTTP + CLI
interfaces. It is **not** vaporware — but it had specific, load-bearing gaps.

### What works (FUNCTIONAL)
- **Federated search** across OpenSanctions/yente, OpenCorporates, GLEIF,
  UK Companies House, and Aleph — real endpoints, auth, token-bucket +
  monthly rate limiting, response caching, Jaccard dedup, graceful
  degradation.
- **Blockchain** — Ethereum (Etherscan), Bitcoin (Blockstream), Tron
  (Tronscan) with balance/tx/counterparty analysis and FtM conversion.
- **Graph engine** — NetworkX; brokers, communities (Louvain/label-prop),
  circular ownership, key players, shortest-path, shell-topology scoring.
- **Interactive visualizer** — self-contained Cytoscape.js HTML.
- **Export** — GEXF, GraphML, Cytoscape/D3 JSON, CSV, branded PDF,
  Markdown, FtM bundle.
- **Entity resolution** — Splink probabilistic linkage with a pure-python
  fallback.
- **Audit archive** — gzipped JSONL, SHA-256 integrity, per-session.
- **Agent loop** — LLM decision + heuristic/EFE fallback, two-mode safety
  harness, BDI layer.

### What was stubbed / broken (fixed here where noted)
- **`augmentation.py` was broken against every real client** — it called
  `YenteClient.match(...)`, `OpenCorporatesClient.search_companies(per_page=...)`,
  `GLEIFClient.search(...)`, and `BlockchainAdapter.investigate_address(...)`
  — none of which existed. Tests mocked `_query_source` wholesale, hiding it.
  **→ Fixed** (§2, §4).
- **ICIJ Offshore Leaks** — reconciliation-only; `get_entity` /
  `get_relationships` return `{"error": ...}`. (Left as-is; documented.)
- **SEC EDGAR** — `search_companies` was a ticker-JSON substring hack
  (misses non-ticker filers), and there was **no real-time feed**.
  **→ Real-time Atom feed added** (§2).
- **MCP `trace_ownership`** — accepted `max_depth` but ignored it; never
  walked a chain. **→ Real UBO tracer added to the graph engine** (§3).
- **No "organizations & public figures only" enforcement** — the rule
  lived only in VALUES.json / LICENSE / CLAUDE.md prose. **→ Enforced in
  code** (§5).
- **Audit trail recorded what/when but not WHO.** **→ Actor identity
  added** (§5).
- **No JSON-LD export, no evidence-chain object, no unified confidence,
  no timeline visualization.** **→ All added** (§4).

### Test coverage
1,751 unit tests, all mock-based (no live-network/integration tests, no
VCR cassettes). "FUNCTIONAL" means endpoint URLs, auth, and response
parsing are correctly wired — not verified against live APIs. This
upgrade adds **~90 new tests** in the same mock-based style.

---

## 2. Data-source expansion

New adapters follow the repo's established `FooConfig` / `FooClient` /
`foo_*_to_ftm` convention and register into `FederationConfig` /
`FederatedSearch.source_methods`, so they participate in federated search,
caching, and dedup automatically.

| Source | Module | Status | Notes |
|--------|--------|--------|-------|
| **Congressional disclosures** | `ftm/external/congress.py` | **NEW** | STOCK Act PTRs. Bridges the Sovereign `congress_scraper` (`EMET_CONGRESS_DATA_DIR`) **and** has a standalone async House Clerk ZIP/XML index puller. Emits Person + Security + Ownership(interest). |
| **FEC campaign finance** | `ftm/external/fec.py` | **NEW** | OpenFEC candidates/committees/contributions → Person/Organization/Payment. Individual natural-person donors suppressed by default (targeting policy). |
| **CourtListener / RECAP** | `ftm/external/courtlistener.py` | **NEW** | Free Law Project v4 API → Document(docket) + parties + Interest links. |
| **SEC EDGAR real-time** | `ftm/external/edgar.py` | **UPGRADED** | Added `fetch_recent_filings[_ftm]()` using the `getcurrent` Atom firehose — filter by form (`4`, `SC 13D`, `8-K`). Fills the "real-time" gap. |
| OpenCorporates | (existing) | FUNCTIONAL | Already present and registered. |
| ICIJ Offshore Leaks | (existing) | PARTIAL | Reconciliation API; unchanged. |
| Property records | — | **NOT ADDED** | No unified free/legal API exists (county assessors are fragmented, mostly non-API). Deferred honestly rather than shipped as a stub. See §7. |

### Congress ↔ Sovereign bridge
The mission asked to connect to `congress_scraper.py` from the Sovereign
pipeline. `CongressAdapter.load_disclosures()` reads that scraper's
`transactions.json` output when `EMET_CONGRESS_DATA_DIR` points at its
`congress_data/` dir; `search_member()` and `holdings_summary()` turn it
into FtM entities and per-ticker holding summaries. When the Sovereign
repo isn't present, `fetch_house_index()` pulls the House Clerk feed
directly so Emet stays standalone.

---

## 3. Graph intelligence

### Beneficial ownership (UBO) tracer — `graph/algorithms.py`
`InvestigativeAnalysis.trace_beneficial_ownership(entity_id, max_depth,
min_effective_pct)` walks **incoming** Ownership edges recursively,
multiplying `share_pct` down the chain to compute each owner's **effective
stake** in the target. Terminal owners are the ultimate beneficial owners.

- Uses the `share_pct` the loader already captured (previously unused by
  any algorithm).
- Parses `"50%"`, `"50"`, `"50.0"`, `0.5`, `["25%"]`; unknown percentages
  propagate as `None` rather than silently assuming 100%.
- Detects and breaks cycles; bounds depth; sorts UBOs by effective stake.
- Returns an `OwnershipTrace` with a journalist-readable `explanation`.

### Anomaly detection — fan-in implemented
`find_structural_anomalies()` documented fan-in but never implemented it.
Added: entities owned by ≥5 distinct parents are flagged
(`fan_in_ownership`), severity escalating with parent count and
jurisdiction spread — a pooled-SPV / layering-hub signal.

### Entity resolution
Already functional (Splink + fallback); left in place. Network
visualization is already interactive (Cytoscape.js).

---

## 4. Blockchain upgrade

### Multi-chain — Solana added — `ftm/external/blockchain.py`
- **`SolanaClient`** — public JSON-RPC (`getBalance`,
  `getSignaturesForAddress`) + Solscan; `SolanaConfig`.
- `detect_chain()` now returns `solana` (checked after Tron, which is a
  stricter base58 subset).
- `BlockchainAdapter` gains `get_sol_address()` and a chain-agnostic
  **`investigate_address(address, chain="")`** that auto-detects, fetches,
  and layers intelligence — this is the method `augmentation.py` and MCP
  tools expected but that never existed.

### On-chain intelligence — `ftm/external/crypto_intel.py` (NEW)
- **Mixer/tumbler detection** — curated registry of OFAC-designated
  mixers (Tornado Cash pools/routers, Sinbad); interaction = strong
  obfuscation signal.
- **DeFi protocol labels** — Uniswap/Aave/Curve/1inch/0x/Balancer/Sushi
  contracts resolved to human labels.
- **Exchange labels** — known Binance/Coinbase hot wallets.
- **Risk scoring** — 0–1 with named, defensible factors (mixer contact,
  volume, DeFi layering, no-exchange-touchpoint).
- **Wallet clustering** — `cluster_by_common_input()` (co-spend heuristic
  for UTXO chains).

Every registry entry is public and auditable; every flag carries its
evidence string so reports stay defensible.

### `augmentation.py` repaired
`_query_source` now delegates to `FederatedSearch` (correct, tested client
signatures + converters) instead of the non-existent ad-hoc methods.

---

## 5. Reporting

- **JSON-LD export** — `GraphExporter.to_jsonld()` maps FtM schemas onto
  schema.org / FtM vocab with `@context` + `@graph`; relationships become
  typed objects referencing endpoints by `@id`. (Previously: no linked-data
  export anywhere.)
- **Evidence chain + confidence** — `export/evidence.py` (NEW).
  `Claim` binds an assertion to `SourceRef`s (built from the `_provenance`
  adapters already attach). `score_confidence()` aggregates a 0–1 score:
  best supporting source, corroboration from **distinct** sources
  (diminishing returns), multiplicative contradiction penalty.
  `EvidenceChain` emits footnoted Markdown and flags **unsupported
  claims** so they can't be published as fact.
- **Timeline visualization** — `TimelineAnalyzer.to_html()` renders a
  self-contained, offline, interactive vertical timeline (schema filter,
  pattern bands, no external CDN). Previously timeline was text/JSON only.
- PDF / CSV export already worked.

---

## 6. Privacy, audit, and the TruthStrike integration

### Targeting policy enforced — `security/target_policy.py` (NEW)
Turns "investigate organizations and public figures, not private
individuals" from prose into an enforced guardrail. `classify_target()`
→ ORGANIZATION / PUBLIC_FIGURE / PRIVATE_INDIVIDUAL / UNKNOWN using
schema, public-dataset provenance (congress/FEC/EDGAR/sanctions), and
public-role cues. `check_target()` denies private individuals unless a
**logged public-interest override** is supplied. Conservative by default:
an unknown bare person is protected, not exposed.

### Audit actor identity — `agent/audit.py`
`AuditArchive.open(session_id, goal, actor=...)` now records **who** ran
the investigation (operator id or calling service, e.g.
`{"id": "truthstrike", "type": "service"}`) on every event and in the
manifest. The archive now answers "who searched what, when" — previously
only "what, when."

### "Who funds this outlet?" endpoint — `api/routes/funding.py` (NEW)
The TruthStrike *Follow the Money* integration surface:

- `GET /api/funding/{entity}` and `POST /api/funding`.
- Enriches the entity (registries + GLEIF ownership + sanctions), builds a
  graph, runs the UBO tracer, attaches an evidence chain + confidence, and
  **enforces the targeting policy** (a bare private individual is refused).
- Logs the query with the **requester's identity** in the audit trail.
- Core logic is a framework-agnostic `lookup_funding(name, fed, ...)` with
  dependency-injected federation + audit, so it's testable without network.

TruthStrike calls `GET /api/funding/{outlet}?requester=truthstrike` for
real-time ownership lookups on media companies.

---

## 7. Known gaps / not shipped (honest accounting)

- **Property records** — no unified free/legal API; county assessors are
  fragmented and mostly non-programmatic. Would need per-county adapters
  or a paid aggregator; deferred rather than stubbed.
- **PACER/RECAP** — court records are covered via **CourtListener/RECAP**
  (free), not direct PACER (paid, per-page). This is the correct
  free/public path.
- **ICIJ node/relationship traversal** — still reconciliation-only
  upstream.
- **No live-network integration tests** — new adapters are mock-tested
  like the rest of the suite; live cassettes remain a future task.
- **HTTP API auth** — the API still has no authN/Z and wide-open CORS
  (pre-existing). The funding endpoint records requester identity but does
  not yet *authenticate* it; put it behind a gateway in production.

---

## 8. New / changed files

**New modules**
- `emet/ftm/external/congress.py`
- `emet/ftm/external/fec.py`
- `emet/ftm/external/courtlistener.py`
- `emet/ftm/external/crypto_intel.py`
- `emet/export/evidence.py`
- `emet/security/target_policy.py`
- `emet/api/routes/funding.py`

**Changed modules**
- `emet/ftm/external/federation.py` — register congress/fec/courtlistener
- `emet/ftm/external/edgar.py` — real-time Atom feed
- `emet/ftm/external/augmentation.py` — `_query_source` delegates to federation
- `emet/ftm/external/blockchain.py` — Solana + `investigate_address` + intel
- `emet/graph/algorithms.py` — UBO tracer + fan-in anomaly
- `emet/graph/exporters.py` — JSON-LD
- `emet/export/timeline.py` — interactive HTML
- `emet/agent/audit.py` — actor identity
- `emet/api/app.py` — mount funding router
- `.env.example` — new source keys

**New tests** (`tests/`): `test_congress.py`, `test_fec.py`,
`test_courtlistener.py`, `test_crypto_intel.py`,
`test_beneficial_ownership.py`, `test_reporting_upgrades.py`,
`test_target_policy.py`, `test_funding_endpoint.py`.

---

## 9. Constraints honored

- **Privacy-respecting** — organizations & public figures only, now
  enforced in code (`target_policy.py`); individual FEC donors suppressed
  by default.
- **Legal/public sources only** — House Clerk, Senate eFD, OpenFEC,
  CourtListener/RECAP, SEC EDGAR, public blockchain explorers, OFAC-
  designated mixer lists.
- **Audit trail for every query** — actor identity now recorded (who /
  what / when), integrity-hashed.
- **Open source** — all additions are plain-Python, dependency-light
  (httpx + stdlib), matching the existing stack.
