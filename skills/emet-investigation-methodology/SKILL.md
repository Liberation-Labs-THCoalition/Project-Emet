---
name: emet-investigation-methodology
description: "Core methodology for driving Project Emet investigations. Covers the 13 MCP tools, their parameters, optimal investigation sequences, federation source selection, blockchain chain selection, export formats, and the execute_raw/execute distinction. Use this skill whenever building, debugging, or extending Emet investigation workflows, agent prompts, or tool integrations."
---

# Emet Investigation Methodology

## Overview
Project Emet is an autonomous investigative intelligence agent built on the FollowTheMoney (FtM) data ecosystem. It exposes 13 MCP tools through `EmetToolExecutor`, backed by a 7-source federated search, 3-chain blockchain analysis, graph analytics engine, and PII-scrubbed export pipeline.

This skill documents how to effectively sequence tools, select data sources, and interpret results when building or driving investigations.

## Tool Inventory

### Primary Investigation Tools

**search_entities** — Federated entity search across 7 sources
- `query` (required): Entity name or search term
- `entity_type`: FtM schema filter (Person, Company, LegalEntity, etc.)
- `sources`: Comma-separated source filter (opensanctions, opencorporates, icij, gleif, companies_house, edgar). Empty = all.
- `limit`: Max results per source (default 10)
- Returns: FtM entities with provenance, confidence scores, source attribution

**screen_sanctions** — Sanctions/PEP screening against 325+ lists
- `entities` (required): Array of `{name, entity_type}` objects (batch supported)
- `threshold`: Minimum match score 0-1 (default 0.7)
- Returns: Match scores, originating dataset, risk classification, last-updated dates

**trace_ownership** — Multi-hop beneficial ownership tracing
- `entity_name` (required): Company or person name
- `max_depth`: Chain depth (default 3, max 10)
- `include_officers`: Include directors/officers (default true)
- Returns: Ownership tree, shell company indicators, jurisdiction chain

**investigate_blockchain** — Three-chain blockchain investigation
- `address` (required): Blockchain address
- `chain`: ethereum, bitcoin, or tron (auto-detected from address format)
- `depth`: Transaction hop depth (default 1)
- Returns: Balance, transaction history, top counterparties, FtM Payment entities

**monitor_entity** — GDELT-powered real-time news monitoring
- `entity_name` (required): Entity to monitor
- `entity_type`: Person, Company, etc.
- `alert_types`: Filter alert types (empty = all)
- Returns: Recent articles, sentiment scores, unique sources, monitoring registration

**analyze_graph** — Network analysis on accumulated entities
- `entity_ids`: FtM entity IDs to analyze (empty = all session entities)
- `algorithm` (required): One of: community_detection, centrality, shortest_path, connected_components, pagerank, bridging_nodes, temporal_patterns
- `params`: Algorithm-specific parameters (e.g. `{source, target}` for shortest_path)
- Returns: Algorithm-specific results (communities, scores, paths, anomalies)

**osint_recon** — SpiderFoot-powered technical reconnaissance
- `target` (required): Domain, email, IP, or name
- `scan_type`: passive (no contact with target) or active (port scanning etc.)
- `modules`: Specific SpiderFoot modules (empty = auto-select)
- Returns: WHOIS, DNS, breach data, social media, FtM entities

### Support Tools

**generate_report** — Report generation from accumulated findings
- `title` (required): Report title
- `format`: markdown, ftm_bundle, or timeline
- `entity_ids`: Specific entities to include (empty = all)
- `include_graph`: Include graph visualization data
- `include_timeline`: Include temporal analysis

**ingest_documents** — Document ingestion from Datashare or DocumentCloud
- `source` (required): datashare or documentcloud
- `project_id`: Project/collection ID
- `query`: Search within documents
- `limit`: Max documents to ingest

**check_alerts** — Check monitoring alerts
- `entity_name`: Filter to specific entity
- `severity`: Minimum severity

**list_workflows / run_workflow** — Predefined investigation templates
- Available: corporate_ownership, person_investigation, sanctions_screening, domain_investigation, due_diligence

**conclude** — End investigation (agent loop only)

## Optimal Investigation Sequences

### Corporate Investigation (most common)
```
1. search_entities(query="Company Name", entity_type="Company")
   → Establishes entity across jurisdictions, gets FtM IDs
2. screen_sanctions(entities=[{name, type}])
   → Immediate risk classification
3. trace_ownership(entity_name="Company Name", max_depth=5)
   → Reveals beneficial owners, shell layers, nominee directors
4. search_entities(query="<discovered UBO name>", entity_type="Person")
   → Cross-reference beneficial owners
5. screen_sanctions(entities=[{discovered persons}])
   → Screen the people behind the company
6. monitor_entity(entity_name="Company Name")
   → Recent news, ongoing monitoring
7. analyze_graph(algorithm="community_detection")
   → Reveal clusters in the ownership network
8. analyze_graph(algorithm="bridging_nodes")
   → Find brokers connecting separate communities
9. generate_report(title="...", include_graph=true)
10. conclude()
```

### Sanctions Evasion Investigation
```
1. screen_sanctions(entities=[target]) → confirm designation
2. search_entities(query=target) → find corporate vehicles
3. trace_ownership(entity_name=each company) → find nominees/fronts
4. investigate_blockchain(address=any crypto addresses found)
   → Especially Tron for USDT-TRC20 evasion
5. analyze_graph(algorithm="community_detection") → find networks
6. monitor_entity(entity_name=target) → ongoing news
```

### Person Investigation
```
1. search_entities(query="Person Name", entity_type="Person")
2. screen_sanctions + osint_recon in parallel
3. search_entities for any companies/entities found
4. trace_ownership on associated companies
5. investigate_blockchain if crypto addresses surface
6. analyze_graph → role in network
```

### Quick Due Diligence
Use the `run_workflow` tool with `workflow_name="due_diligence"`:
```
run_workflow(
  workflow_name="due_diligence",
  inputs={entity_name: "Company Name", entity_type: "Company"}
)
```
This chains: search → sanctions screen → ownership trace → report automatically.

## Federation Source Selection

Each federated source has strengths. The agent auto-queries all enabled sources, but understanding what each provides helps interpret results:

| Source | Best For | Free? | Notes |
|--------|----------|-------|-------|
| **OpenSanctions** | Sanctions, PEP, watchlist matches | Rate-limited | 325+ lists, fuzzy matching |
| **OpenCorporates** | Global company records (145+ jurisdictions) | 200 req/month | Best for non-UK/US companies |
| **ICIJ Offshore Leaks** | Offshore entities (Panama Papers, etc.) | Unlimited | 810K+ entities, historical |
| **GLEIF** | Legal Entity Identifiers (LEI) | Unlimited | Financial institution identification |
| **UK Companies House** | UK companies, officers, PSC | Unlimited (free key) | Real-time beneficial ownership (PSC register) |
| **SEC EDGAR** | US public companies, filings | Unlimited | 13D/13G beneficial ownership, insider trading |

**Source selection heuristics:**
- UK entity → Companies House is authoritative (real PSC data, not inferred)
- US public company → EDGAR for filings + OpenCorporates for state registrations
- Offshore/opaque jurisdiction → ICIJ + OpenCorporates
- Financial institution → GLEIF for LEI cross-reference
- Sanctions concern → OpenSanctions is always first call

## Blockchain Chain Selection

| Chain | Use Case | Key Capability |
|-------|----------|---------------|
| **Ethereum** | DeFi, smart contracts, NFTs | Token transfers, contract interactions |
| **Bitcoin** | Store of value, large transfers | UTXO analysis, wallet clustering |
| **Tron** | USDT stablecoin transfers | TRC-20 token tracking — **dominant chain for sanctions evasion** due to low fees |

**Address format auto-detection:**
- `0x` prefix → Ethereum
- `bc1`, `1`, `3` prefix → Bitcoin
- `T` prefix (base58, 34 chars) → Tron

**Why Tron matters:** OFAC has designated multiple Tron addresses. The Tron network carries more USDT volume than Ethereum due to lower transaction costs, making it the preferred rail for sanctions evasion, money laundering, and illicit finance. Always check Tron when investigating stablecoin flows.

## Graph Analysis Selection

Seven algorithms available through `analyze_graph`:

| Algorithm | What It Finds | When To Use |
|-----------|--------------|-------------|
| `community_detection` | Clusters (Louvain) | First pass — reveals network structure |
| `centrality` | Most connected/influential nodes | Identify key players |
| `bridging_nodes` | Brokers between communities | Find intermediaries, gatekeepers |
| `shortest_path` | Connection between two entities | "How is A connected to B?" |
| `connected_components` | Isolated subnetworks | Find disconnected clusters |
| `pagerank` | Influence ranking | Weight-aware importance scoring |
| `temporal_patterns` | Time-based evolution | Track network changes over time |

**Recommended sequence:** community_detection → centrality → bridging_nodes → (shortest_path if specific connection needed)

## Export & Publication Boundary

**Formats:**
- JSON: Default API/CLI export (scrubbed)
- PDF: Branded report (`--output report.pdf` in CLI, `?format=pdf` in API)
- Markdown: Via `generate_report(format="markdown")`
- FtM Bundle: JSONL/zip for Aleph re-import via `generate_report(format="ftm_bundle")`
- Timeline: Temporal event extraction via `generate_report(format="timeline")`

**Publication boundary:** All PII is scrubbed when data leaves the system (CLI export, API response, adapter message, PDF). Internal session data preserves unredacted data for continued investigation.

## Architecture Notes

### execute() vs execute_raw()
- `execute()`: MCP protocol wrapper — returns `{isError: bool, content: [...], _raw: data}`. Used by MCP server (protocol compliance).
- `execute_raw()`: Returns the raw data dict directly, raises exceptions on error. Used by agent loop, CLI, workflow engine.

**Critical:** Always use `execute_raw()` when processing results programmatically. The MCP wrapper nests the actual data under `_raw`, and calling `.get("entities")` on the wrapper returns None.

### Session State
The agent accumulates state across tool calls:
- `session.entities`: Dict of FtM entity ID → entity data
- `session.findings`: List of Finding(source, summary, confidence)
- `session.leads`: Priority queue of next investigation targets
- `session.reasoning_trace`: Full chain-of-thought log

### Safety Harness
- **Advisory mode** (internal): Logs PII detections but doesn't block
- **Enforcing mode** (publication): Scrubs PII at export boundaries
- All tool results pass through SafetyHarness before storage
