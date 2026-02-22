# Emet Competitive Feature Adoption Roadmap v3.0

**Version**: 3.0
**Date**: 2026-02-22
**Status**: 🔄 Planning (Sprints 10–19)
**Predecessor**: [COMPETITIVE_ROADMAP.md](COMPETITIVE_ROADMAP.md) v2.0 — Sprints 1–9 complete
**Philosophy**: Integration-first. Wrap battle-tested open-source tools rather than reimplementing. Emet is the investigative brain that orchestrates specialist tools, not a monolith.

---

## Executive Summary

Sprints 1–9 closed the most critical competitive gaps: LLM abstraction, federated search, blockchain, graph analytics, export/reporting, monitoring, document ingestion, and LLM-powered analysis. This roadmap addresses the **remaining 10 competitor "unique" features** identified in the competitive landscape analysis, using open-source integrations wherever possible.

**Total estimated effort**: ~10.5 sprints (down from 14+ if building from scratch)
**New external integrations**: 8 open-source projects
**New internal builds**: 3 modules (MCP server, workflow engine, batch processor)

---

## Sprints 1–9 Recap (Complete)

| Sprint | Competitive Gap Closed | Competitors Matched |
|--------|----------------------|---------------------|
| 1. LLM Abstraction | Single-provider lock-in | LangChain, CrewAI (multi-model) |
| 2+3. Federation + Blockchain | Siloed data, no crypto | Maltego (data partners), Chainalysis (ETH/BTC) |
| 4. Graph Analytics | No network analysis | Maltego, i2, Palantir (graph algorithms) |
| 5. Export & Reporting | No structured output | Aleph Pro (bundles), Palantir (timeline) |
| 6. Monitoring | No proactive alerts | ComplyAdvantage, Recorded Future (screening) |
| 7. Document Ingestion | No document pipeline | Datashare, DocumentCloud (NER) |
| 8. LLM Skills | No AI-powered analysis | NYT toolkit, Videris (AI investigation) |
| 9. Hardening | Fragile integration | All (production readiness) |

**Delivered**: ~8,500 lines, 20 modules, 311 tests passing

---

## Sprints 10–19: Integration-First Roadmap

### Sprint 10: MCP Server + Investigation Memory

**Competitive gap**: No ecosystem play. Emet is isolated; other AI agents can't use it.
**Who has it**: LangChain (90M+ downloads), Microsoft Agent Framework, Anthropic Claude
**Integration target**: [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) (Apache 2.0, Python, 1.3k stars)

**Effort**: 1 sprint
**Deliverables**:

#### 10a. Emet MCP Server

Expose Emet's capabilities as MCP tools that any MCP-compatible client (Claude, GPT, Cursor, VS Code, etc.) can call:

| MCP Tool | Maps To | Description |
|----------|---------|-------------|
| `emet_search_entities` | `FederatedSearch.search()` | Search across all data sources |
| `emet_check_sanctions` | `SanctionsChip.execute()` | Screen entity against sanctions lists |
| `emet_analyze_graph` | `GraphEngine` methods | Run investigative graph algorithms |
| `emet_shell_score` | `ShellCompanyChip.execute()` | Score entity for shell company indicators |
| `emet_generate_report` | `MarkdownReport.generate()` | Generate investigation report |
| `emet_check_blockchain` | `EtherscanClient` / `BlockstreamClient` | Look up wallet/address |
| `emet_monitor_entity` | `ChangeDetector.register_query()` | Set up change monitoring |

**Implementation**: Thin wrapper over our existing FastAPI endpoints using `mcp-server-python`. The FastAPI already serves the same functionality — MCP is a protocol adapter.

```
emet/mcp/
├── __init__.py
├── server.py           → MCP server entry point
├── tools.py            → Tool definitions mapping to Emet capabilities
└── converters.py       → MCP ↔ FtM type converters
```

#### 10b. Investigation Memory (mcp-memory-service integration)

Adapt mcp-memory-service's architecture to give Emet persistent investigation memory:

**What we take from mcp-memory-service**:
- **Dream-inspired consolidation**: Decay scoring for investigation leads (old leads lose priority unless reinforced by new evidence). Association discovery between entities across investigations. Compression of redundant findings. Archival of closed investigation threads.
- **Memory type ontology**: Map to investigation types — `observation` (entity sighting), `decision` (investigative judgment), `learning` (pattern discovered), `error` (dead end / false lead), `pattern` (recurring scheme)
- **Knowledge graph with typed relationships**: `causes`, `fixes`, `supports`, `follows`, `related`, `contradicts` — maps directly to investigative reasoning chains
- **Hybrid BM25 + vector search**: Exact match for entity names + semantic search for investigation context
- **5ms local reads** via SQLite-vec: Fast enough for real-time investigation support

**What we adapt for Emet**:
- Investigation-specific decay: Financial leads decay slower than social media mentions. Sanctions hits never decay. User-bookmarked entities are pinned.
- FtM-aware associations: Entity relationships from graph analysis automatically create memory associations
- Case-scoped memory: Memories tagged by investigation/case, queryable within or across cases

```
emet/memory/
├── __init__.py
├── investigation_memory.py  → Wraps mcp-memory-service storage
├── decay.py                 → Investigation-specific decay policies
├── case_manager.py          → Case/investigation scoping
└── ftm_associations.py      → Auto-associate from FtM relationships
```

**Config**:
```python
MEMORY_BACKEND: str = "sqlite_vec"          # "sqlite_vec" | "hybrid"
MEMORY_DB_PATH: str = "~/.emet/memory.db"
MEMORY_DECAY_ENABLED: bool = True
MEMORY_CONSOLIDATION_SCHEDULE: str = "daily" # "daily" | "weekly" | "manual"
```

**Strategic value**: This is the highest-leverage sprint. MCP server turns Emet into infrastructure. Investigation memory turns it into a persistent investigative partner rather than a stateless tool.

---

### Sprint 11: SpiderFoot Integration (Technical OSINT)

**Competitive gap**: No digital footprint reconnaissance
**Who has it**: SpiderFoot (200+ modules, MIT), Recon-ng, OSINT Industries (1,500+ sources)
**Integration target**: [SpiderFoot](https://github.com/smicallef/spiderfoot) (MIT, Python 3, 200+ modules)

**Effort**: 0.5 sprint
**Deliverables**:

Run SpiderFoot as a sidecar service, call via `spiderfoot-client` (PyPI, MIT), convert results to FtM entities.

**Architecture**:
```
SpiderFoot (sidecar, port 5001)
    ↑ spiderfoot-client (Python)
    ↑
emet/ftm/external/spiderfoot.py
    → SpiderFootClient: start_scan(), get_results(), results_to_ftm()
    → SpiderFootFtMConverter: map SF event types → FtM schemas
```

**SpiderFoot event type → FtM schema mapping** (key mappings):

| SpiderFoot Event | FtM Schema | Properties |
|-----------------|------------|------------|
| `EMAILADDR` | `Email` | address, domain |
| `DOMAIN_NAME` | `Domain` | name, registrar |
| `IP_ADDRESS` | `Address` | (custom property) |
| `PHONE_NUMBER` | `Phone` | number |
| `SOCIAL_MEDIA` | `UnknownLink` | (to Person) |
| `COMPANY_NAME` | `Organization` | name |
| `PHYSICAL_ADDRESS` | `Address` | full, country |
| `DOMAIN_WHOIS` | `Ownership` | owner, registrar, dates |
| `ACCOUNT_EXTERNAL_OWNED` | `UnknownLink` | (entity linkage) |

**What we get for free**: WHOIS lookups, DNS enumeration, email verification, breach database checks (HaveIBeenPwned), social media discovery, dark web mentions, IP geolocation, subdomain discovery — all through SpiderFoot's existing 200+ modules. Most require no API keys.

**Config**:
```python
SPIDERFOOT_HOST: str = "http://localhost:5001"
SPIDERFOOT_SCAN_TYPES: list = ["passive"]  # "passive" | "active"
SPIDERFOOT_MODULES: list = []              # empty = all applicable
```

---

### Sprint 12: Investigation Workflow Automation

**Competitive gap**: Building blocks exist but no one-click investigations
**Who has it**: Blackdot Videris Automate, Genpact AML/KYC Analyst agents, ComplyAdvantage
**Integration target**: None — build internally using YAML-defined workflow templates

**Effort**: 1 sprint
**Deliverables**:

Pre-built investigation recipes that chain Emet's existing modules into complete workflows, triggered by a single command or API call.

**Workflow engine**:
```
emet/workflows/
├── __init__.py
├── engine.py              → WorkflowEngine: load, validate, execute
├── templates/             → YAML workflow definitions
│   ├── corporate_due_diligence.yaml
│   ├── pep_screening.yaml
│   ├── shell_company_investigation.yaml
│   ├── sanctions_check.yaml
│   ├── financial_trail.yaml
│   └── full_investigation.yaml
└── steps.py               → Step registry mapping names → functions
```

**Example workflow** (`corporate_due_diligence.yaml`):
```yaml
name: Corporate Due Diligence
description: Full corporate background check
inputs:
  - entity_name: string
  - jurisdiction: string (optional)

steps:
  - id: search
    action: federated_search
    params:
      query: "{{ entity_name }}"
      sources: [opensanctions, opencorporates, gleif, icij]

  - id: graph
    action: build_graph
    params:
      entities: "{{ search.results }}"

  - id: analysis
    action: graph_analysis
    params:
      graph: "{{ graph.result }}"
      algorithms: [broker_detection, community_detection, shell_scoring]

  - id: sanctions
    action: sanctions_screen
    params:
      entities: "{{ search.results }}"

  - id: blockchain
    action: blockchain_check
    params:
      entities: "{{ search.results }}"
      chains: [ethereum, bitcoin]
    condition: "{{ search.results | has_crypto_addresses }}"

  - id: report
    action: generate_report
    params:
      title: "Due Diligence: {{ entity_name }}"
      sections: [search, graph, analysis, sanctions, blockchain]
    
  - id: memory
    action: store_investigation
    params:
      case_tag: "dd-{{ entity_name | slugify }}"
      findings: "{{ report.result }}"

output:
  report: "{{ report.result }}"
  risk_score: "{{ analysis.result.shell_score }}"
  sanctions_hits: "{{ sanctions.result.matches }}"
```

**Strategic value**: This is the "demo moment" — show someone a single command that runs a complete investigation. It also makes the MCP server dramatically more useful (one tool call = full investigation).

---

### Sprint 13: Audio/Video Transcription

**Competitive gap**: Can't process audio/video evidence (leaked recordings, press conferences, wiretaps)
**Who has it**: Google Pinpoint, OpenAleph (Whisper), NYT toolkit (500+ hours of video analyzed)
**Integration target**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT, 4x faster than OpenAI Whisper, 8-bit quantization) or [WhisperX](https://github.com/m-bain/whisperX) (BSD, adds speaker diarization + word-level timestamps)

**Effort**: 0.5 sprint
**Deliverables**:

```
emet/ingest/
├── audio_transcriber.py    → WhisperTranscriber: transcribe(), diarize()
├── video_extractor.py      → Extract audio from video (ffmpeg/PyAV)
└── transcript_to_ftm.py    → NER on transcript → FtM entities + Document
```

**Pipeline**: Audio/video file → extract audio (PyAV) → faster-whisper transcription → (optional) WhisperX diarization → transcript text → existing NER pipeline (spaCy/our LLM skills) → FtM `Document` entity linked to extracted `Person`/`Organization` mentions.

**Key design decisions**:
- **faster-whisper over openai-whisper**: 4x faster, MIT license, 8-bit quantization works on CPU. No FFmpeg system dependency (uses PyAV).
- **WhisperX optional**: Adds speaker diarization (who said what) and word-level timestamps. Requires pyannote-audio license acceptance. Make it opt-in.
- **Local-first**: All processing runs locally. No audio sent to cloud APIs. Critical for sensitive investigations.

**Config**:
```python
WHISPER_MODEL: str = "base"           # "tiny" | "base" | "small" | "medium" | "large-v3"
WHISPER_DEVICE: str = "auto"          # "auto" | "cpu" | "cuda"
WHISPER_COMPUTE_TYPE: str = "int8"    # "int8" | "float16" | "float32"
WHISPER_DIARIZATION: bool = False     # Requires WhisperX + pyannote
WHISPER_LANGUAGE: str = "auto"        # ISO 639-1 code or "auto"
```

---

### Sprint 14: Entity Resolution

**Competitive gap**: Naive name-matching in FederatedSearch. "Vladimir Putin" ≠ "Владимир Путин" ≠ "V. Putin"
**Who has it**: Quantexa, IVIX (99% accuracy), Sayari (2.7B entities), Orbis
**Integration target**: [Splink](https://moj-analytical-services.github.io/splink/) (MIT, Python, won 2025 UK Civil Service Innovation Award, used by Australian Bureau of Statistics, UNHCR, UK MOJ)

**Effort**: 1 sprint
**Deliverables**:

```
emet/resolution/
├── __init__.py
├── entity_resolver.py      → EntityResolver: resolve(), merge(), score()
├── splink_adapter.py       → Splink configuration for FtM entity types
├── transliteration.py      → icu-based transliteration (Cyrillic, Arabic, Chinese)
└── blocking_rules.py       → FtM-aware blocking strategies
```

**Why Splink over dedupe**: Splink is probabilistic (Fellegi-Sunter model), scales to millions of records, has excellent documentation, and doesn't require active learning (labeled training data). It's used by national statistics agencies for census-scale deduplication. `dedupe` requires manual labeling sessions that don't fit our automated pipeline.

**Integration points**:
- `FederatedSearch`: After collecting results from all sources, run entity resolution before returning. Merge duplicates, flag near-matches.
- `GraphEngine`: Before building graph, resolve entities to prevent duplicate nodes for the same real-world entity.
- `ChangeDetector`: Resolve monitored entities against new results to catch name variations.

**Comparison features needed for FtM entities**:

| FtM Property | Comparison Method | Weight |
|-------------|-------------------|--------|
| `name` | Jaro-Winkler + Soundex + transliteration | High |
| `country` | Exact match | Medium |
| `birthDate` | Date comparison (±1 year tolerance) | High |
| `idNumber` | Exact match | Very high |
| `address` | Token sort + Levenshtein | Medium |
| `registrationNumber` | Exact match (stripped) | Very high |

**Config**:
```python
ENTITY_RESOLUTION_ENABLED: bool = True
ENTITY_RESOLUTION_THRESHOLD: float = 0.85  # Match probability threshold
ENTITY_RESOLUTION_TRANSLITERATE: bool = True
```

---

### Sprint 15: Semantic Search / RAG

**Competitive gap**: Keyword-only search across documents. Can't ask "find references to money laundering through real estate in Cyprus"
**Who has it**: Google Pinpoint (semantic search, 200K+ files), Hebbia (RAG for financial docs), NYT "diving for pearls" pattern
**Integration targets**:
- [ChromaDB](https://github.com/chroma-core/chroma) (Apache 2.0) or [LanceDB](https://github.com/lancedb/lancedb) (Apache 2.0) — local vector stores
- Ollama embedding models (already integrated) or `sentence-transformers` (Apache 2.0)

**Effort**: 1 sprint
**Deliverables**:

```
emet/search/
├── __init__.py
├── semantic_index.py       → SemanticIndex: index(), search(), hybrid_search()
├── embedder.py             → Embedder: embed_text(), embed_documents() (Ollama or sentence-transformers)
├── chunker.py              → Document chunking strategies (overlap, semantic boundaries)
└── rag_query.py            → RAGQuery: answer_from_documents() using SkillLLMHelper
```

**Pipeline**: Documents from Datashare/DocumentCloud → chunk → embed (Ollama `nomic-embed-text` or `all-MiniLM-L6-v2`) → store in ChromaDB → query via natural language → retrieve top-k chunks → pass to SkillLLMHelper for synthesis → answer with citations.

**Design decisions**:
- **ChromaDB over FAISS**: ChromaDB is persistent, has metadata filtering (filter by source, date, entity), and has a simple Python API. FAISS is faster but requires manual persistence.
- **Ollama embeddings preferred**: Already have Ollama integration from Sprint 1. `nomic-embed-text` is 768-dim, runs locally. Falls back to `sentence-transformers` if Ollama unavailable.
- **Hybrid search**: BM25 keyword + vector semantic, same pattern as mcp-memory-service's v10.8.0 approach. Configurable fusion weights.

**Config**:
```python
SEMANTIC_SEARCH_ENABLED: bool = True
SEMANTIC_BACKEND: str = "chromadb"       # "chromadb" | "lancedb"
SEMANTIC_EMBEDDING_MODEL: str = "auto"   # "auto" → Ollama if available, else sentence-transformers
SEMANTIC_CHUNK_SIZE: int = 512           # tokens per chunk
SEMANTIC_CHUNK_OVERLAP: int = 50         # overlap tokens
SEMANTIC_HYBRID_WEIGHT: float = 0.7      # semantic weight (1-x = keyword weight)
```

---

### Sprint 16: Real-Time Intelligence Feeds

**Competitive gap**: Monitoring is reactive (check-on-demand). No continuous news/filing ingestion.
**Who has it**: Recorded Future (1M+ sources), Maltego (monitoring module), ComplyAdvantage (real-time screening)
**Integration targets**:
- [GDELT](https://www.gdeltproject.org/) (free, updates every 15 minutes, 65 languages, REST API)
- [MediaCloud](https://mediacloud.org/) (open source, MIT, news archive)
- RSS/Atom feeds (government gazettes, court filings, regulatory announcements)

**Effort**: 0.5 sprint
**Deliverables**:

```
emet/feeds/
├── __init__.py
├── feed_manager.py         → FeedManager: register(), poll(), process()
├── gdelt_client.py         → GDELTClient: search(), monitor_entity()
├── mediacloud_client.py    → MediaCloudClient: search(), trending()
├── rss_client.py           → RSSClient: subscribe(), poll()
└── feed_to_ftm.py          → Convert feed items to FtM Document/Event entities
```

**Integration with existing ChangeDetector**: Feed results are processed through entity extraction, matched against monitored entities, and generate `ChangeAlert` events when matches found. The existing monitoring infrastructure handles alert delivery.

**GDELT capabilities** (all free, no API key):
- Full-text search across global news, 15-minute updates
- Tone/sentiment analysis
- Geographic coding (where events happened)
- Event taxonomy (CAMEO codes — protests, arrests, sanctions, etc.)
- Entity mention tracking

**Config**:
```python
FEEDS_ENABLED: bool = True
GDELT_POLL_INTERVAL: int = 900         # seconds (15 min default)
MEDIACLOUD_API_KEY: str = ""            # optional, for higher rate limits
RSS_FEEDS: list = []                    # list of RSS/Atom URLs
FEED_ENTITY_MATCH_THRESHOLD: float = 0.8
```

---

### Sprint 17: Visual Graph Interface (Frontend)

**Competitive gap**: No way to see investigation results visually without exporting to third-party tools
**Who has it**: Maltego (visual graph), Palantir (interactive exploration), Sayari Map, i2 Analyst's Notebook
**Integration targets**:
- [Cytoscape.js](https://js.cytoscape.org/) (MIT) or [Sigma.js](https://www.sigmajs.org/) (MIT) — graph rendering
- React (MIT) — UI framework
- Our existing `to_cytoscape_json()` and `to_d3_json()` exports

**Effort**: 2 sprints (17a + 17b)
**Deliverables**:

#### Sprint 17a: Core Graph Viewer

```
emet/web/
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── GraphViewer.jsx      → Cytoscape.js graph rendering
│   │   │   ├── EntityPanel.jsx      → Entity detail sidebar
│   │   │   ├── SearchBar.jsx        → Entity/keyword search
│   │   │   ├── FilterControls.jsx   → Filter by schema, jurisdiction, date
│   │   │   └── AlgorithmPanel.jsx   → Run graph algorithms from UI
│   │   └── api/
│   │       └── emet.js              → API client for Emet FastAPI
│   └── public/
└── api_routes.py                     → Additional API routes for frontend
```

**Features (17a)**:
- Interactive force-directed graph layout
- Click node → entity detail panel (properties, sources, sanctions status)
- Search → highlight matching nodes
- Filter by FtM schema type, jurisdiction, date range
- Color-code by schema type (Person = blue, Company = green, etc.)
- Export current view as PNG/SVG

#### Sprint 17b: Investigation Workspace

**Features (17b)**:
- Run graph algorithms from UI (broker detection, community detection, shell scoring)
- Visual highlighting of algorithm results (communities colored, brokers sized by centrality)
- Investigation timeline view (entities plotted on time axis by incorporation/birth date)
- Workflow launcher (pick a workflow template, fill params, watch results populate the graph)
- Case management (save/load investigation states)
- Integration with investigation memory (show memory associations as graph edges)

**Design decisions**:
- **Cytoscape.js over D3**: Cytoscape.js is purpose-built for network graphs. D3 is more flexible but requires much more code. Cytoscape has built-in layouts (cola, dagre, euler), gestures, and extensions.
- **Separate frontend build**: React app served statically by FastAPI. No SSR needed. Builds to static files that can be deployed anywhere.
- **API-first**: All data flows through existing FastAPI endpoints. Frontend is purely a consumer. This means the API stays useful without the frontend.

---

### Sprint 18: Dataset Augmentation + Batch Processing

**Competitive gap**: Can't process large datasets (10K+ entities) efficiently with LLM analysis
**Who has it**: NYT toolkit (screened 10K individuals in Puerto Rico investigation), IVIX (bulk entity classification)
**Integration target**: None — build on existing SkillLLMHelper with batch queue

**Effort**: 0.5 sprint
**Deliverables**:

```
emet/batch/
├── __init__.py
├── batch_processor.py      → BatchProcessor: submit(), status(), results()
├── augmentation.py         → DatasetAugmenter: classify(), enrich(), score()
└── rate_limiter.py         → Token-aware rate limiting for LLM calls
```

**Use cases**:
- Given 5,000 company names, classify each by likely industry and jurisdiction risk
- Given 10,000 person names, flag likely PEPs and generate risk narratives
- Given 1,000 transaction descriptions, categorize by suspicious activity type
- Given 500 addresses, score for shell company indicators

**Design**:
- Async queue with configurable concurrency (respect Ollama/API rate limits)
- Progress tracking (X of N complete, estimated time remaining)
- Checkpoint/resume (survives interruption)
- Results as FtM entities with LLM-generated properties stored as `notes`
- Token usage tracking per batch for cost awareness

---

### Sprint 19: Advanced Blockchain Clustering

**Competitive gap**: Single-address lookups only. Can't cluster wallets or trace through intermediaries.
**Who has it**: Chainalysis (wallet clustering, 65% market share), Elliptic (60+ chains)
**Integration target**: None — build heuristics internally. Proprietary attribution databases not available.

**Effort**: 1 sprint
**Deliverables**:

```
emet/ftm/external/blockchain_analysis.py  → extends existing blockchain.py
├── WalletClusterer: common_input_ownership(), change_address_detection()
├── TransactionTracer: trace_hops(), find_intermediaries()
├── MultiChainClient: tron_client(), solana_client()  (free APIs)
└── blockchain_graph.py → Build NetworkX graph from transaction flows
```

**Heuristics we can implement** (well-documented in academic literature):
- **Common-input-ownership**: If two addresses appear as inputs in the same transaction, they're likely controlled by the same entity
- **Change address detection**: The output address that isn't the recipient is likely a change address belonging to the sender
- **Peeling chain detection**: Sequential transactions splitting funds into a main amount + small change (common laundering pattern)

**What we cannot implement** (requires proprietary data):
- Exchange address attribution (which address belongs to Binance, Coinbase, etc.)
- Mixer/tumbler detection (requires pattern databases from Chainalysis/Elliptic)
- Cross-chain tracing (bridges create gaps we can't close)

**Multi-chain expansion**: Add Tron (TronGrid API, free) and Solana (Solana RPC, free) — both heavily used in money laundering per recent FinCEN guidance.

---

## Implementation Priority Matrix

| Sprint | Feature | Effort | Strategic Value | Dependencies |
|--------|---------|--------|----------------|--------------|
| **10** | **MCP Server + Investigation Memory** | 1 sprint | ⭐⭐⭐⭐⭐ | None |
| **11** | **SpiderFoot Integration** | 0.5 sprint | ⭐⭐⭐ | None |
| **12** | **Investigation Workflows** | 1 sprint | ⭐⭐⭐⭐⭐ | Sprint 10 (memory) |
| **13** | **A/V Transcription** | 0.5 sprint | ⭐⭐⭐ | None |
| **14** | **Entity Resolution** | 1 sprint | ⭐⭐⭐⭐ | None |
| **15** | **Semantic Search / RAG** | 1 sprint | ⭐⭐⭐⭐ | Sprint 13 (for indexing transcripts) |
| **16** | **Real-Time Feeds** | 0.5 sprint | ⭐⭐⭐ | Sprint 6 (ChangeDetector) |
| **17a** | **Graph Viewer (Core)** | 1 sprint | ⭐⭐⭐⭐⭐ | Sprint 4 (GraphEngine) |
| **17b** | **Investigation Workspace** | 1 sprint | ⭐⭐⭐⭐ | Sprint 17a |
| **18** | **Dataset Augmentation** | 0.5 sprint | ⭐⭐⭐ | Sprint 8 (SkillLLMHelper) |
| **19** | **Blockchain Clustering** | 1 sprint | ⭐⭐ | Sprint 2 (blockchain) |

**Total**: 10.5 sprints (~21–42 dev days at sprint = 2–4 days)

---

## Dependency Graph

```
Sprint 10 (MCP + Memory) ──→ Sprint 12 (Workflows)
                          ──→ Sprint 17b (Investigation Workspace)

Sprint 4  (GraphEngine)  ──→ Sprint 17a (Graph Viewer)
Sprint 17a               ──→ Sprint 17b (Investigation Workspace)

Sprint 6  (ChangeDetector) → Sprint 16 (Real-Time Feeds)
Sprint 8  (SkillLLMHelper) → Sprint 18 (Dataset Augmentation)
Sprint 2  (Blockchain)     → Sprint 19 (Blockchain Clustering)
Sprint 13 (Transcription)  → Sprint 15 (Semantic Search — index transcripts)

Independent: Sprint 11 (SpiderFoot), Sprint 13 (Transcription), Sprint 14 (Entity Resolution)
```

---

## External Integration Summary

| Tool | License | What We Use | What We Write |
|------|---------|-------------|---------------|
| **mcp-memory-service** | Apache 2.0 | Decay/consolidation architecture, knowledge graph, hybrid search | Investigation-specific decay policies, FtM associations, case scoping |
| **SpiderFoot** | MIT | 200+ OSINT modules via sidecar | FtM converter for SF event types |
| **faster-whisper** | MIT | Audio transcription engine | Pipeline wrapper + NER integration |
| **WhisperX** | BSD | Speaker diarization (optional) | Diarization-aware transcript→FtM |
| **Splink** | MIT | Probabilistic entity resolution | FtM-aware blocking rules + comparison config |
| **ChromaDB** | Apache 2.0 | Vector store for document embeddings | Chunking strategy + RAG query pipeline |
| **GDELT** | Free (API) | Global news monitoring, 15-min updates | Entity matching + ChangeAlert integration |
| **MediaCloud** | MIT | News archive search | FtM Document converter |
| **Cytoscape.js** | MIT | Graph rendering in browser | React components + Emet API integration |

---

## Constraints (Updated)

| Constraint | Detail |
|---|---|
| **Developer capacity** | Solo developer, sprint-based with gaps |
| **LLM provider** | Ollama (default) → Anthropic (fallback) → Stub (testing) |
| **Budget** | Free tiers only. No Chainalysis, Orbis, Recorded Future, etc. |
| **API access** | All Sprint 1–9 APIs + GDELT (free), MediaCloud (free tier), SpiderFoot (self-hosted), Tron/Solana RPCs (free) |
| **Hardware** | faster-whisper runs on CPU (int8 quantization). GPU optional for large transcription jobs. |
| **Frontend** | React + Cytoscape.js. No SSR, no complex build tooling. Static files served by FastAPI. |
| **Memory** | SQLite-vec for investigation memory. No cloud sync required (but hybrid backend available). |

---

## Competitive Coverage After Sprint 19

| Competitor Capability | Sprint 1–9 | Sprint 10–19 | Coverage |
|-----------------------|-----------|-------------|----------|
| Multi-provider LLM | ✅ S1 | | Full |
| Federated data search | ✅ S2 | | Full |
| Blockchain investigation | ✅ S3 | ✅ S19 (clustering) | Strong |
| Graph analytics | ✅ S4 | ✅ S17 (visual UI) | Full |
| Export/reporting | ✅ S5 | | Full |
| Change monitoring | ✅ S6 | ✅ S16 (real-time feeds) | Strong |
| Document ingestion | ✅ S7 | ✅ S13 (A/V), S15 (RAG) | Full |
| AI-powered analysis | ✅ S8 | ✅ S18 (batch) | Strong |
| Technical OSINT/recon | | ✅ S11 (SpiderFoot) | Strong |
| Entity resolution | | ✅ S14 (Splink) | Strong |
| Investigation workflows | | ✅ S12 | Full |
| Visual interface | | ✅ S17a+b | Full |
| Persistent memory | | ✅ S10 (mcp-memory) | Full |
| MCP ecosystem play | | ✅ S10 | Full |
| Semantic/RAG search | | ✅ S15 | Strong |
| Real-time intel feeds | | ✅ S16 | Partial* |
| Wallet clustering | | ✅ S19 | Partial** |

\* Partial: GDELT/MediaCloud cover news; no court filings, regulatory announcements, or proprietary intel feeds
\** Partial: Heuristic clustering only; no exchange attribution or mixer detection (requires Chainalysis-class data)

**Remaining gaps that require enterprise data/licensing** (not addressable in open-source):
- Orbis-class corporate ownership data (600M+ entities) — requires Bureau van Dijk license (~$124K/year)
- Exchange address attribution — requires Chainalysis/Elliptic license (~$200K/year)
- Real-time threat intelligence (1M+ sources) — requires Recorded Future license (~$60K/year)
- Enterprise compliance certifications (SOC 2, ISO 27001) — requires organizational audit, not code

These are market-access barriers, not engineering problems. Emet's architecture can integrate these data sources if/when licensing becomes available.

---

## Estimated Post-Completion Metrics

| Metric | After Sprint 9 | After Sprint 19 (est.) |
|--------|---------------|----------------------|
| Modules | 68 | ~85 |
| Lines of code | ~25,000 | ~35,000 |
| Tests | 311 | ~450 |
| External integrations | 6 | 14 |
| FtM schema coverage | 11 | 15+ |
| Graph export formats | 5 | 5 + interactive web |
| Supported LLM providers | 3 | 3 |
| MCP tools exposed | 0 | 7+ |
| Investigation workflows | 0 | 6+ |
| Replacement value (annual licensing) | ~$300K–500K | ~$500K–800K |
