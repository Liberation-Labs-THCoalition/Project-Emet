# Emet Competitive Feature Adoption Roadmap

**Version**: 2.0
**Date**: 2026-02-21
**Status**: ✅ Complete (all 9 sprints implemented)
**Context**: Competitive landscape analysis identified ~15 high-impact capabilities from OSINT, compliance, journalism, and AI agent competitors that Emet can adopt within its architecture and budget constraints.

## Implementation Summary

| Sprint | Status | Tests | Key Deliverables |
|--------|--------|-------|------------------|
| 1. LLM Abstraction | ✅ | — | Ollama/Anthropic/Stub clients, cascading fallback, factory |
| 2+3. Data Federation + Blockchain | ✅ | 40 | FtM converters, parallel async search, rate limiting, ETH/BTC clients |
| 4. Graph Analytics | ✅ | 37 | NetworkX engine, 7 investigative algorithms, Gephi/CSV/D3 export |
| 5. Export & Reporting | ✅ | 24 | Markdown reports, FtM bundles, temporal pattern detection |
| 6. Monitoring | ✅ | 21 | Change detection, snapshot diffing, sanctions alerts |
| 7. Document Ingestion | ✅ | 24 | Datashare + DocumentCloud adapters, NER→FtM conversion |
| 8. LLM Skill Integration | ✅ | 30 | SkillLLMHelper, 6 methodology prompts, structured output |
| 9. Integration & Hardening | ✅ | 18 | Full pipeline test, 194 total tests passing |

**Total new code**: ~8,500 lines across 20 modules
**Total new tests**: 194 (all passing in 2.5s)

---

## Constraints

| Constraint | Detail |
|---|---|
| **Developer capacity** | Solo developer, mix of full-time sprints with gaps between |
| **LLM provider** | Open-source local models (Ollama) as default; Claude API as fallback when local unavailable or hardware-limited |
| **Budget** | Free tiers only for all external APIs |
| **API access** | OpenSanctions (free), OpenCorporates (free tier: 200 req/month), ICIJ Offshore Leaks (free), GLEIF (free, CC0), Etherscan (free tier: 5 req/sec), Blockstream (free). No Google Pinpoint (requires journalist credentials). |
| **Timeline** | Sprint-based, not calendar-fixed. Each sprint is ~1–2 weeks of focused work. Gaps between sprints assumed. |

---

## Architecture Changes Required

### A1. Provider-Agnostic LLM Abstraction

**Current state**: `emet/cognition/llm_client.py` is Anthropic-only (`AnthropicClient`). Model router already has `local/default` path in seed tier but no actual local model client.

**Target state**: Abstract `LLMClient` interface with three backends:
- `OllamaClient` — default, connects to local Ollama server (llama3.2, mistral, deepseek-coder, etc.)
- `AnthropicClient` — existing code, used as fallback
- `StubClient` — returns canned responses for testing (replaces current regex-based skill chip logic)

**Design**:
```
emet/cognition/
├── llm_client.py          → rename to llm_base.py (LLMClient ABC + LLMResponse)
├── llm_anthropic.py       → current AnthropicClient, minimal changes
├── llm_ollama.py          → new OllamaClient using httpx to Ollama REST API
├── llm_stub.py            → new StubClient for testing
├── llm_factory.py         → factory that reads config, returns appropriate client
├── model_router.py        → extend to map tiers to local model names
├── efe.py                 → unchanged
└── orchestrator.py        → unchanged (uses LLMClient interface)
```

**Model tier mapping for Ollama**:
| Tier | Anthropic | Ollama (default) | Notes |
|---|---|---|---|
| FAST | claude-3-5-haiku | llama3.2:3b or phi3:mini | Intent classification, extraction |
| BALANCED | claude-sonnet-4 | mistral:7b or llama3.1:8b | Synthesis, analysis |
| POWERFUL | claude-opus-4 | deepseek-r1:14b or llama3.1:70b | Complex reasoning (hardware dependent) |

**Fallback logic**: If Ollama is unreachable or model not loaded → fall back to Anthropic API if key configured → fall back to StubClient with warning. This cascading ensures Emet always runs.

**Config** (in `emet/config/settings.py`):
```python
LLM_PROVIDER: str = "ollama"          # "ollama" | "anthropic" | "stub"
OLLAMA_HOST: str = "http://localhost:11434"
OLLAMA_MODELS: dict = {
    "fast": "llama3.2:3b",
    "balanced": "mistral:7b",
    "powerful": "deepseek-r1:14b",
}
ANTHROPIC_API_KEY: str = ""            # existing, used as fallback
LLM_FALLBACK_ENABLED: bool = True      # auto-fallback to next provider
```

---

### A2. Graph Analytics Engine

**Current state**: `NetworkAnalysisChip` defines graph algorithms conceptually but has no actual NetworkX integration — the handlers return mock/skeleton results.

**Target state**: Real `GraphEngine` class that:
1. Builds NetworkX graphs from FtM entity collections (using `RELATIONSHIP_EDGES` mapping already defined)
2. Runs standard graph algorithms with investigative interpretations
3. Exports to multiple formats (GEXF, GraphML, JSON)
4. Integrates with shell company detection chip for topology-based detection

**Design**:
```
emet/graph/
├── __init__.py
├── engine.py              → GraphEngine: build, query, export
├── algorithms.py          → Investigative wrappers around NetworkX algorithms
├── ftm_loader.py          → FtM entities → NetworkX graph conversion
└── exporters.py           → GEXF, GraphML, Cytoscape JSON, summary stats
```

**Core algorithms** (all from NetworkX, no custom implementation needed):
| Algorithm | NetworkX function | Investigative use |
|---|---|---|
| Betweenness centrality | `nx.betweenness_centrality()` | Identify brokers/intermediaries in ownership networks |
| PageRank | `nx.pagerank()` | Rank entities by structural "importance" |
| Community detection | `community.louvain_communities()` | Find corporate clusters and related entity groups |
| Shortest path | `nx.shortest_path()` | Trace connection chains between entities |
| K-core decomposition | `nx.k_core()` | Find tightly-connected inner circles |
| Cycle detection | `nx.simple_cycles()` | Detect circular ownership (shell company indicator) |
| Bridge detection | `nx.bridges()` | Find critical links whose removal disconnects groups |
| Connected components | `nx.connected_components()` | Identify isolated vs. interconnected networks |

**Shell company detection enhancement** — topology features to add to existing heuristic scoring:
- Circular ownership chains (A → B → C → A)
- Fan-out structures (single owner → 10+ entities in different jurisdictions)
- Jurisdiction bridge nodes (entity that connects clusters in different countries)
- Temporal burst patterns (N entities incorporated within M days at same address)
- Missing officer/director edges (company with no directorship relationships)

---

### A3. Data Federation Layer

**Current state**: Four external API clients exist in `emet/ftm/external/adapters.py` with real httpx code. Each returns raw API responses. No unified query interface or FtM conversion pipeline.

**Target state**: Federation layer that:
1. Accepts a query (entity name, identifier, etc.)
2. Fans out to all configured data sources in parallel
3. Converts results to FtM entities
4. Deduplicates and scores matches
5. Returns unified result set with provenance tracking

**Design**:
```
emet/ftm/external/
├── __init__.py
├── adapters.py            → existing clients (unchanged)
├── blockchain.py          → new: Etherscan + Blockstream clients
├── documents.py           → new: Datashare + DocumentCloud API clients
├── federation.py          → new: parallel fan-out, dedup, unified response
└── converters.py          → new: source-specific → FtM conversion functions
```

**Rate limit management** (critical for free tiers):
| Source | Free tier limit | Strategy |
|---|---|---|
| OpenSanctions | Unlimited (public API) | Normal async |
| OpenCorporates | 200 req/month | Aggressive caching, user warning at 80% |
| ICIJ Offshore Leaks | Unspecified, generous | Normal async with backoff |
| GLEIF | Unlimited, CC0 | Normal async |
| Etherscan | 5 req/sec, 100K/day | Token bucket rate limiter |
| Blockstream | Generous, no key | Normal async with backoff |
| Datashare | Self-hosted, no limit | Depends on user's instance |
| DocumentCloud | Free, rate-limited | Backoff on 429 |

---

### A4. Export & Reporting Pipeline

**Current state**: No export capability. Investigation results exist only in memory/API responses.

**Target state**: Multiple export formats for actionable output.

**Design**:
```
emet/export/
├── __init__.py
├── markdown.py            → investigation summary as Markdown
├── pdf.py                 → formatted PDF report (via weasyprint or reportlab)
├── ftm_bundle.py          → FtM entity JSON bundle (re-importable to Aleph)
├── graph_export.py        → GEXF/GraphML for Gephi visualization
├── timeline.py            → chronological event timeline (JSON + Markdown)
└── csv_export.py          → tabular data export for spreadsheet analysis
```

---

## Sprint Plan

### Sprint 1: LLM Provider Abstraction
**Effort**: ~5 days
**Closes competitive gap with**: All AI agent frameworks (LangChain, CrewAI, etc.) that support multiple providers
**Prerequisite for**: All subsequent sprints (skill chips need working LLM)

**Deliverables**:
1. `LLMClient` abstract base class with `complete()`, `classify_intent()`, `generate_content()`, `extract_entities()` methods matching existing `AnthropicClient` signatures
2. `OllamaClient` implementing the interface via Ollama's REST API (`POST /api/generate`, `POST /api/chat`)
3. `StubClient` for deterministic testing
4. Refactored `AnthropicClient` implementing the same interface
5. `LLMFactory` that reads `LLM_PROVIDER` config and returns appropriate client with cascading fallback
6. Updated `model_router.py` with Ollama model name mappings per tier
7. Updated `settings.py` with new config fields
8. Tests: unit tests for each client, integration test confirming fallback chain

**Acceptance criteria**:
- `LLM_PROVIDER=ollama` → Emet uses local Ollama models for all skill chip operations
- `LLM_PROVIDER=anthropic` → existing behavior unchanged
- `LLM_PROVIDER=ollama` with Ollama offline → automatic fallback to Anthropic if API key configured, else StubClient
- All 51 E2E tests still pass (using StubClient)
- New test: round-trip through Ollama for intent classification (requires Ollama running)

**Notes**:
- Ollama REST API is simple: `POST http://localhost:11434/api/chat` with `{"model": "mistral:7b", "messages": [...]}`
- Response format differs from Anthropic — needs parsing adapter
- Token counting: Ollama returns `eval_count` and `prompt_eval_count` — map to `input_tokens`/`output_tokens`
- Cost tracking: local models are $0.00, but track token counts for performance monitoring

---

### Sprint 2: Data Federation — Live External Sources
**Effort**: ~5 days
**Closes competitive gap with**: Maltego (multi-source integration), Orbis (corporate data), World-Check (sanctions screening)
**Prerequisite for**: Sprint 4 (graph analytics needs real data)

**Deliverables**:
1. Verify/fix all four existing adapter clients against live APIs:
   - OpenSanctions/yente: test `search()`, `match_entity()`, `screen_entities()` against `api.opensanctions.org`
   - OpenCorporates: test `search_companies()`, `get_company()`, `search_officers()` (watch 200/month limit — use test sparingly)
   - ICIJ Offshore Leaks: test `search()`, `get_entity()`, `get_relationships()`
   - GLEIF: test `search_entities()`, `get_entity_by_lei()`, `get_direct_parent()`, `get_ultimate_parent()`, `get_children()`
2. FtM converters: complete `company_to_ftm()` and `lei_record_to_ftm()` (exist), add `yente_to_ftm()` (trivial — yente returns native FtM), `icij_to_ftm()`, `officer_to_ftm()`
3. `FederatedSearch` class:
   - `search_entity(name, entity_type, jurisdictions)` → fans out to all configured sources via `asyncio.gather()`
   - Deduplication by name similarity (Levenshtein or similar) + jurisdiction matching
   - Provenance tagging: each result carries `source`, `source_url`, `confidence_score`, `retrieved_at`
   - Results returned as list of FtM entity dicts with `_provenance` metadata
4. Rate limiter utility class (token bucket for Etherscan, counter for OpenCorporates)
5. Caching layer: `aiohttp` response cache or simple dict cache with TTL (avoid redundant API calls during investigation)
6. Config additions: API keys/tokens in settings, per-source enable/disable flags
7. Integration test: federated search for a well-known entity (e.g., "Gazprom") across all sources

**Acceptance criteria**:
- Federated search returns results from at least 3 sources for a common entity name
- FtM conversion produces valid entities (pass through `followthemoney` library validation if available)
- Rate limits are respected (OpenCorporates counter tracks monthly usage, Etherscan respects 5/sec)
- Cache prevents duplicate API calls within same investigation session
- Graceful degradation: if one source is down, others still return results

---

### Sprint 3: Blockchain Basics
**Effort**: ~3 days
**Closes competitive gap with**: Chainalysis (basic crypto investigation), Elliptic (transaction tracing)
**Not attempting**: Wallet attribution, clustering, or advanced blockchain forensics (that's Chainalysis's $200K/year moat)

**Deliverables**:
1. `EtherscanClient` in `emet/ftm/external/blockchain.py`:
   - `get_balance(address)` → ETH balance
   - `get_transactions(address, page, offset)` → transaction list
   - `get_token_transfers(address)` → ERC-20 token transfers
   - `get_internal_transactions(address)` → internal (contract) transactions
   - Rate limiter: 5 req/sec token bucket
2. `BlockstreamClient`:
   - `get_address_info(address)` → BTC balance, tx count
   - `get_transactions(address)` → transaction list
   - `get_utxos(address)` → unspent outputs
3. FtM conversion:
   - Bitcoin/Ethereum addresses → `CryptoWallet` entity (custom FtM schema extension or use `Thing` with properties)
   - Transactions → `Payment` entities linking wallet entities
4. Integration with `FinancialInvestigationChip`:
   - When financial trail analysis encounters a cryptocurrency address pattern (0x... for ETH, bc1.../1.../3... for BTC), route to blockchain client
   - Return transaction summary: total in, total out, largest counterparties, temporal pattern
5. Tests: unit tests with mocked responses, one live integration test per chain

**Acceptance criteria**:
- Given an Ethereum address, Emet returns balance, top 20 transactions, and identifies largest counterparty addresses
- Given a Bitcoin address, Emet returns balance and transaction summary
- Crypto entities integrate with graph engine (wallet addresses become nodes, transactions become edges)
- Free tier rate limits strictly enforced

**Scope explicitly excluded**:
- Wallet clustering (mapping multiple addresses to same owner)
- Mixer/tumbler detection
- Smart contract analysis
- DeFi protocol interaction parsing
- Token price lookups

---

### Sprint 4: Graph Analytics Engine
**Effort**: ~7 days
**Closes competitive gap with**: Maltego (visual graph analysis), Sayari (network intelligence), i2 Analyst's Notebook (link analysis)
**Highest-impact sprint for OCCRP pitch**

**Deliverables**:
1. `emet/graph/engine.py` — `GraphEngine` class:
   - `build_from_entities(entities: list[dict]) -> nx.Graph` — constructs graph from FtM entity list
   - `build_from_aleph(collection_id: str) -> nx.Graph` — fetches entities from Aleph, builds graph
   - `build_from_federation(query: str) -> nx.Graph` — runs federated search, builds graph from results
   - Graph stored as NetworkX `MultiDiGraph` (directed, allows multiple edges between same nodes)
   - Node attributes: FtM schema, properties, provenance source
   - Edge attributes: relationship type, dates, weight (based on relationship strength)

2. `emet/graph/ftm_loader.py` — FtM → graph conversion:
   - Uses `RELATIONSHIP_EDGES` mapping from existing `network_analysis.py`
   - Handles all 10 FtM relationship types
   - Resolves entity references (Ownership.owner → Person node, Ownership.asset → Company node)
   - Handles multi-valued properties (entity with multiple names → single node with name list)

3. `emet/graph/algorithms.py` — investigative algorithm wrappers:
   ```python
   class InvestigativeAnalysis:
       def find_brokers(graph) -> list[BrokerResult]
           # Betweenness centrality, filtered to top N, with investigative interpretation
       
       def find_communities(graph) -> list[CommunityResult]
           # Louvain community detection, with cross-jurisdiction flagging
       
       def find_circular_ownership(graph) -> list[CycleResult]
           # Cycle detection filtered to ownership/control edges
       
       def find_key_players(graph) -> list[KeyPlayerResult]
           # PageRank + degree centrality composite score
       
       def find_hidden_connections(entity_a, entity_b, graph) -> list[PathResult]
           # All shortest paths + intermediate node analysis
       
       def find_structural_anomalies(graph) -> list[AnomalyResult]
           # Fan-out detection, orphan nodes, bridge nodes, jurisdiction clustering
       
       def shell_company_topology_score(entity_id, graph) -> ShellScore
           # Composite score from: circular ownership, fan-out, jurisdiction bridges,
           # missing officer edges, temporal burst patterns
   ```
   Each result type includes: entities involved, algorithm used, confidence score, human-readable explanation.

4. `emet/graph/exporters.py`:
   - `to_gexf(graph, path)` — for Gephi (NetworkX native support)
   - `to_graphml(graph, path)` — standard graph format
   - `to_cytoscape_json(graph)` — for eventual web UI visualization
   - `to_summary_stats(graph)` → dict with node count, edge count, density, component count, diameter

5. Updated `NetworkAnalysisChip`:
   - Replace skeleton handlers with real `GraphEngine` calls
   - Add new intents: `find_circular_ownership`, `find_structural_anomalies`, `shell_topology_score`

6. Updated `ShellCompanyDetectionChip` (in `corporate_research.py`):
   - Add graph topology features to existing heuristic scoring
   - Composite score = (heuristic score * 0.5) + (topology score * 0.5) when graph available
   - Fall back to heuristic-only when graph not built

7. Tests:
   - Unit tests with synthetic graph fixtures (10-node ownership network with known properties)
   - Integration test: build graph from mock Aleph data (23-entity "Operation Sunrise" dataset), run all algorithms, verify expected results
   - Benchmark: graph build + all algorithms on 1,000-node synthetic graph < 5 seconds

**Acceptance criteria**:
- Build graph from 23-entity Operation Sunrise test dataset
- Correctly identify circular ownership if present in test data
- Betweenness centrality identifies expected broker entities
- Community detection groups related entities
- GEXF export opens correctly in Gephi (manual verification)
- Shell company topology scoring produces meaningful scores (not all zeros or all ones)

---

### Sprint 5: Export & Reporting
**Effort**: ~4 days
**Closes competitive gap with**: All competitors (every tool from Maltego to Orbis generates reports)

**Deliverables**:
1. `emet/export/markdown.py`:
   - `InvestigationReport` class that assembles: executive summary, entity table, network summary, timeline of key events, data sources consulted, confidence assessments
   - Generated from investigation state (entities, relationships, skill chip outputs, graph analysis results)
   - Clean Markdown with tables, suitable for journalist consumption

2. `emet/export/ftm_bundle.py`:
   - Export investigation entities as FtM JSON Lines (`.ftm.json`) — the standard format for Aleph import
   - Include provenance metadata as FtM `Mention` entities
   - Bundle as zip with entities + relationships + metadata

3. `emet/export/graph_export.py`:
   - Wrapper around graph engine exporters
   - Add investigation metadata to graph files (title, date, source counts)
   - GEXF with visual attributes pre-configured (node size by PageRank, color by entity type)

4. `emet/export/timeline.py`:
   - Extract all dated events from investigation entities
   - Sort chronologically
   - Output as JSON (for eventual UI) and Markdown
   - Flag suspicious temporal patterns (burst of activity, gaps, date coincidences)

5. `emet/export/csv_export.py`:
   - Entity table as CSV (one row per entity, columns for key properties)
   - Relationship table as CSV (source, target, type, dates)
   - Suitable for import into spreadsheet tools or Tableau

6. API endpoint: `POST /investigations/{id}/export` with format parameter

7. Tests: generate all export formats from test investigation, verify each is valid/parseable

**Acceptance criteria**:
- Markdown report is readable and contains all investigation data
- FtM bundle successfully imports into Aleph (requires manual test against live Aleph instance — defer if no access)
- GEXF opens in Gephi with meaningful visualization
- CSV imports cleanly into a spreadsheet
- Timeline correctly sorts events and flags temporal clusters

---

### Sprint 6: Temporal Analysis & Monitoring
**Effort**: ~4 days
**Closes competitive gap with**: Recorded Future (monitoring), ComplyAdvantage (continuous screening)

**Deliverables**:
1. `emet/analysis/temporal.py`:
   - `TemporalAnalyzer` class that extracts dates from FtM entities and identifies:
     - **Burst patterns**: N entities with dates within M days of each other
     - **Suspicious coincidences**: incorporation date near contract award, directorship change near sanctions announcement
     - **Gaps**: unexplained periods of inactivity in otherwise active entities
     - **Sequencing anomalies**: events that happen in wrong order (e.g., company receives payment before incorporation)
   - Configurable thresholds per pattern type
   - Returns scored findings with human-readable explanations

2. `emet/monitoring/change_detector.py`:
   - `ChangeDetector` that re-runs federated searches on a schedule and diffs results:
     - New entities matching tracked names/patterns
     - Changed properties on tracked entities (status changes, new addresses, new officers)
     - New sanctions/PEP hits on tracked persons
     - New Aleph documents in tracked collections
   - State stored in PostgreSQL (tracked queries, previous results, change history)
   - Notification output: structured alert with entity, change type, old value, new value, timestamp

3. Updated `MonitoringChip`:
   - Wire `set_alert` and `check_alerts` intents to `ChangeDetector`
   - Add `temporal_analysis` intent to `TemporalAnalyzer`

4. Simple scheduling:
   - For pilot: manual trigger via API endpoint (`POST /monitoring/check`)
   - For beta: optional cron-based scheduling via config
   - No complex job queue (overkill for pilot scale)

5. Tests: synthetic change detection scenario (entity property changes between two API calls)

**Acceptance criteria**:
- Temporal analyzer identifies planted burst pattern in test data
- Change detector identifies added/modified/removed entities between two search snapshots
- Alert output includes all required fields (entity, change type, values, timestamp)
- No persistent background processes required (runs on-demand or via external cron)

---

### Sprint 7: Document Ingestion Adapters
**Effort**: ~3 days
**Closes competitive gap with**: Google Pinpoint (document analysis), Datashare (document processing)
**Note**: Emet does NOT do document processing — it ingests results from tools that do.

**Deliverables**:
1. `emet/ftm/external/documents.py`:
   - `DatashareClient`:
     - Connects to user's self-hosted Datashare instance
     - `search(query)` → search across processed documents
     - `get_document(id)` → document metadata + extracted text
     - `get_named_entities(id)` → NER results from Datashare's processing pipeline
     - Convert named entities to FtM entities for federation
   - `DocumentCloudClient`:
     - `search(query)` → search across public/user documents
     - `get_document(id)` → document text + metadata
     - `get_entities(id)` → extracted entities (if available)
     - Note: DocumentCloud's API is at `api.www.documentcloud.org/api/`
   
2. FtM conversion:
   - Document → FtM `Document` entity with text, dates, source URL
   - Extracted persons/orgs → FtM `Person`/`Organization` entities
   - Document-entity relationships → FtM `Mention` entities

3. Integration with `DocumentAnalysisChip` and `NLPExtractionChip`:
   - When user provides document reference (URL or ID), fetch from appropriate source
   - Run Emet's own NLP extraction on top of source's extraction for richer entity identification
   - Feed results into graph engine

4. Tests: mock Datashare and DocumentCloud responses, verify FtM conversion

**Acceptance criteria**:
- Given a Datashare document ID, Emet retrieves text and entities and converts to FtM
- Given a DocumentCloud search query, Emet returns matching documents with extracted entities
- Results integrate with federated search and graph engine

---

### Sprint 8: Skill Chip LLM Integration
**Effort**: ~7 days (largest sprint — touches every chip)
**Closes competitive gap with**: NYT's internal AI toolkit, Videris Automate (agentic investigation)
**Prerequisite**: Sprint 1 (LLM provider abstraction)

**Deliverables**:
1. Update all 15 skill chips to use real LLM calls instead of regex/pattern matching:

   **Investigation chips** (6):
   | Chip | Current | LLM-backed |
   |---|---|---|
   | `EntitySearchChip` | Pattern match on intents | LLM intent classification, query reformulation |
   | `NetworkAnalysisChip` | Skeleton results | LLM interprets graph algorithm outputs in natural language |
   | `NLPExtractionChip` | Regex entity extraction | LLM-powered NER + relationship extraction |
   | `CrossReferenceChip` | String matching | LLM entity resolution (fuzzy matching, alias detection) |
   | `DocumentAnalysisChip` | Keyword extraction | LLM summarization, key finding extraction |
   | `DataQualityChip` | Rule-based checks | LLM + rules hybrid (rules for structure, LLM for semantics) |

   **Specialized chips** (5):
   | Chip | Current | LLM-backed |
   |---|---|---|
   | `FinancialInvestigationChip` | Heuristic trail following | LLM identifies financial patterns, anomalies in transaction data |
   | `CorporateResearchChip` | Rule-based shell detection | LLM + graph topology hybrid scoring |
   | `GovernmentAccountabilityChip` | Pattern matching | LLM analyzes procurement patterns, conflict-of-interest indicators |
   | `EnvironmentalInvestigationChip` | Keyword-based | LLM correlates environmental data with corporate activity |
   | `LaborInvestigationChip` | Pattern matching | LLM identifies labor violation patterns |

   **Publication chips** (2):
   | Chip | Current | LLM-backed |
   |---|---|---|
   | `StoryDevelopmentChip` | Template-based | LLM generates investigation narratives, identifies story angles |
   | `VerificationChip` | Checklist-based | LLM cross-references claims against evidence, identifies gaps |

   **Support chips** (2):
   | Chip | Current | LLM-backed |
   |---|---|---|
   | `MonitoringChip` | Timer-based | LLM summarizes changes, assesses significance |
   | `ResourcesChip` | Static lookups | LLM suggests relevant resources based on investigation context |

2. Prompt engineering:
   - System prompts per chip encoding domain expertise (investigative journalism methodology)
   - Structured output prompts (JSON response format for machine-parseable results)
   - Evidence grounding prompts (require LLM to cite specific entities/documents)
   - Uncertainty calibration prompts (require confidence scores, flag speculation)

3. Consensus gate integration:
   - LLM outputs that recommend action (publish, contact source, file FOIA) route through VALUES.json consensus gate
   - Human-in-the-loop for all high-stakes outputs
   - LLM outputs clearly labeled as AI-generated in all exports

4. Token usage tracking and cost estimation (works for both Ollama and Anthropic)

5. Tests: each chip tested with real LLM call (Ollama or Anthropic) on at least one representative input

**Acceptance criteria**:
- All 15 chips produce meaningfully better results with LLM than with regex/pattern matching
- NLP extraction chip correctly identifies persons, organizations, and relationships from free text
- Story development chip generates coherent investigation narrative from entity/relationship data
- Verification chip identifies evidence gaps and suggests next investigative steps
- Total token usage per typical investigation workflow < 50K tokens (affordable on both local and API)
- All outputs include confidence scores and provenance information

---

### Sprint 9: Integration, Testing & Hardening
**Effort**: ~5 days
**Purpose**: Wire everything together, end-to-end investigation workflows

**Deliverables**:
1. End-to-end investigation workflow tests:
   - **Workflow A — Entity Investigation**: User provides entity name → federated search → graph construction → centrality/community analysis → shell company scoring → export report
   - **Workflow B — Document-Driven**: User provides document (via Datashare/DocumentCloud) → NLP extraction → entity enrichment via federation → network mapping → story development
   - **Workflow C — Financial Trail**: User provides company name → corporate research → financial trail analysis → blockchain check (if crypto addresses found) → temporal analysis → monitoring setup
   - **Workflow D — Sanctions Screening**: User provides entity list → batch OpenSanctions screening → cross-reference with ICIJ Offshore Leaks → risk scoring → export CSV

2. API endpoint updates:
   - All new capabilities exposed through FastAPI endpoints
   - Swagger/OpenAPI documentation auto-generated
   - Request/response examples in docs

3. Error handling hardening:
   - Every external API call wrapped in retry with exponential backoff
   - Graceful degradation: partial results returned if some sources fail
   - Clear error messages: "OpenCorporates monthly limit reached (180/200)" not "HTTP 429"
   - Investigation state preserved on crash (save to PostgreSQL on each step)

4. Performance benchmarking:
   - Time each operation at realistic scale
   - Identify bottlenecks (likely: LLM calls, external API latency)
   - Add async parallelism where possible

5. Security review:
   - Audit all external API calls: what data leaves the system?
   - LLM provider review: what investigation data goes to Ollama (local = safe) vs. Anthropic (cloud = review)
   - Log review: ensure no source names, investigation details, or entity identifiers in application logs
   - Document security model in ARCHITECTURE.md

6. Updated test suite: target 80+ tests (up from 51 E2E + 66 integration)

**Acceptance criteria**:
- All four workflow tests pass end-to-end
- Mean response time for federated search + graph build < 30 seconds on typical investigation
- No investigation data leaks to external services (except configured API queries)
- All endpoints documented in Swagger

---

## Sprint Sequencing & Dependencies

```
Sprint 1: LLM Abstraction ─────────────────────────────┐
                                                        │
Sprint 2: Data Federation ──────────┐                   │
                                    │                   │
Sprint 3: Blockchain ──────────────┐│                   │
                                   ││                   │
Sprint 4: Graph Analytics ←────────┘│(needs real data)  │
                                    │                   │
Sprint 5: Export & Reporting ←──────┘(needs all data)   │
                                                        │
Sprint 6: Temporal & Monitoring ←───────────────────────│(needs data + LLM)
                                                        │
Sprint 7: Document Ingestion                            │
                                                        │
Sprint 8: Skill Chip LLM Integration ←─────────────────┘(needs LLM abstraction)
                                                        
Sprint 9: Integration & Hardening ←──── all previous
```

**Parallelizable pairs** (for full-time sprint periods):
- Sprints 1 + 2 (different codepaths, no dependency)
- Sprints 3 + 7 (both are data source adapters)
- Sprints 5 + 6 (export and analysis are independent)

**Recommended order for sprint-with-gaps cadence**:
1. Sprint 1 (LLM) — foundational, unblocks 8
2. Sprint 2 (Federation) — brings real data flowing, unblocks 4
3. Sprint 4 (Graph Analytics) — highest-impact demo capability
4. Sprint 3 (Blockchain) — quick win, extends financial investigation
5. Sprint 5 (Export) — makes results tangible/usable
6. Sprint 6 (Temporal & Monitoring) — adds ongoing investigation value
7. Sprint 7 (Document Ingestion) — extends data input surface
8. Sprint 8 (Skill Chip LLM) — transforms all chips from stubs to intelligence
9. Sprint 9 (Integration) — production hardening

**Total estimated effort**: ~43 development days across 9 sprints
**Calendar time**: Highly variable with gaps. Optimistic: 3–4 months. Realistic with gaps: 5–7 months.

---

## Competitive Gaps Closed Per Sprint

| Sprint | Competitor capability adopted | Competitors matched/exceeded |
|---|---|---|
| 1 — LLM Abstraction | Multi-provider AI support, local model privacy | LangChain (provider flexibility), Videris (AI backing) |
| 2 — Data Federation | Multi-source entity enrichment, sanctions screening | Maltego (multi-source), World-Check (sanctions, partial), Orbis (corporate, partial) |
| 3 — Blockchain | Basic crypto trail following | Chainalysis (partial — no attribution), Elliptic (partial) |
| 4 — Graph Analytics | Network analysis, centrality, community detection | Maltego (graph analysis), Sayari (network intelligence), i2 (link analysis) |
| 5 — Export | Structured output, Aleph re-import, visualization data | All competitors (every tool exports) |
| 6 — Temporal & Monitoring | Change detection, temporal pattern analysis | Recorded Future (monitoring, partial), ComplyAdvantage (screening) |
| 7 — Document Ingestion | Process documents from existing journalism tools | Pinpoint (via Datashare alternative), Datashare (native), DocumentCloud (native) |
| 8 — Skill Chip LLM | AI-powered investigation intelligence | NYT toolkit (investigation AI), Videris Automate (agentic), Wokelo (AI due diligence) |
| 9 — Integration | Production-grade reliability | Enterprise tools (hardening, error handling, security) |

---

## Post-Roadmap: What Remains Out of Reach

These capabilities require resources beyond solo developer + free tiers, and should be noted as aspirational rather than planned:

| Capability | Why out of reach | Workaround |
|---|---|---|
| Orbis-scale corporate data (600M entities) | Proprietary dataset, $100K+/year license | Federate across free sources (OC + GLEIF + ICIJ + Aleph ≈ ~410M entities) |
| Chainalysis wallet attribution | Years of proprietary clustering + law enforcement partnerships | Basic on-chain analysis + flag for manual attribution |
| Enterprise certifications (SOC 2, ISO 27001) | $50K+ audit cost, organizational requirements | Document security model, offer self-hosted deployment |
| Web UI with interactive graph visualization | Major frontend engineering effort | GEXF export → Gephi (existing tool), Cytoscape JSON for eventual UI |
| Real-time threat intelligence feeds | Recorded Future's 1M+ source ingestion pipeline | Periodic monitoring with change detection |
| Multi-language NER (20+ languages) | spaCy model training, evaluation per language | English + major European languages first (spaCy has pre-trained models) |
| Maltego-scale data partner ecosystem (120+ integrations) | Business development, API licensing, maintenance | Focus on highest-value free sources, open architecture for community contributions |

---

## Risk Register (Addendum to PILOT_PLAN.md)

| Risk | Severity | Probability | Mitigation |
|---|---|---|---|
| Ollama model quality insufficient for skill chips | High | Medium | Benchmark specific tasks against Claude API baseline; fall back to Anthropic for tasks where local models fail |
| OpenCorporates 200/month limit too restrictive | Medium | High | Aggressive caching; apply for journalist/NGO free tier (may need org credentials); prioritize GLEIF and Aleph for corporate data |
| ICIJ API changes or goes offline | Medium | Low | Cache results locally; ICIJ also publishes bulk data downloads |
| NetworkX performance at scale (10K+ nodes) | Medium | Medium | Profile early; consider graph-tool or igraph as NetworkX alternatives if bottleneck |
| LLM hallucinations in skill chip outputs | High | High | Require evidence citation in all prompts; consensus gates for action recommendations; clearly label AI-generated content |
| Free-tier rate limits cause investigation interruptions | Medium | High | Per-source rate tracking with user-visible warnings; cache aggressively; batch queries where possible |

---

## Appendix: Free-Tier API Reference

| Source | Base URL | Auth | Rate limit | Notes |
|---|---|---|---|---|
| OpenSanctions / yente | `api.opensanctions.org` | None (or API key for higher limits) | Generous, unspecified | Native FtM responses |
| OpenCorporates | `api.opencorporates.com/v0.4.8` | Optional token | 200 req/month (free) | Apply for NGO access for unlimited |
| ICIJ Offshore Leaks | `offshoreleaks.icij.org/api/v1` | None | Unspecified, generous | 810K+ entities from 5 major leaks |
| GLEIF | `api.gleif.org/api/v1` | None | Unlimited | CC0 license, 2.7M+ LEI records |
| Etherscan | `api.etherscan.io/api` | Free API key | 5 req/sec, 100K req/day | Ethereum only |
| Blockstream | `blockstream.info/api` | None | Generous, unspecified | Bitcoin only |
| Datashare | User's self-hosted instance | Depends on deployment | No external limit | ICIJ's document analysis tool |
| DocumentCloud | `api.www.documentcloud.org/api/` | Free account | Rate-limited (generous) | MuckRock's document platform |
