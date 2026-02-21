# Emet — Architecture

## Overview

The Emet is an agentic investigative journalism framework built on the [**Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture, adapted for the **FollowTheMoney (FtM) data ecosystem** and OCCRP's Aleph investigative platform.

It orchestrates a swarm of specialized skill chips (agents) that collaboratively search, analyze, cross-reference, and verify investigative leads — all while operating within a strict journalism ethics governance layer.

```
┌───────────────────────────────────────────────────────────┐
│                         Emet                              │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Orchestrator (Supervisor)               │  │
│  │   Keyword routing → EFE scoring → LLM fallback      │  │
│  └──────────────┬──────────────────────┬───────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────┐  ┌───────────▼────────────────┐  │
│  │   Cognition Layer   │  │    Governance Layer         │  │
│  │  • EFE Calculator   │  │  • VALUES.json constitution │  │
│  │  • Model Router     │  │  • Consensus Gates          │  │
│  │  • LLM Abstraction  │  │  • OTel audit trail         │  │
│  │    Ollama → Claude   │  │                             │  │
│  │    → Stub (cascade)  │  │                             │  │
│  └──────────────┬──────┘  └───────────┬────────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────────────────────▼───────────────┐  │
│  │              Kintsugi Engine (unchanged)             │  │
│  │   Shadow verification • Self-repair • Resilience    │  │
│  └──────────────┬──────────────────────┬───────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────┐  ┌───────────▼────────────────┐  │
│  │   Memory (CMA)      │  │    Security Layer           │  │
│  │  • 3-stage pipeline │  │  • Intent Capsules          │  │
│  │  • Investigation    │  │  • Security Shield          │  │
│  │    context          │  │  • Behavior Monitor         │  │
│  └─────────────────────┘  └────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              FtM Data Spine                          │  │
│  │   Aleph API • FtM entities • Federation • Blockchain│  │
│  └──────────────┬──────────────────────┬───────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────┐  ┌───────────▼────────────────┐  │
│  │   Graph Analytics   │  │    Export & Reporting       │  │
│  │  • NetworkX engine  │  │  • Markdown reports         │  │
│  │  • 7 algorithms     │  │  • FtM bundles (Aleph)     │  │
│  │  • Multi-format     │  │  • Timeline analysis        │  │
│  │    export           │  │  • GEXF/CSV/D3/Cytoscape   │  │
│  └──────────────┬──────┘  └───────────┬────────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────────────────────▼───────────────┐  │
│  │    Monitoring: ChangeDetector + SnapshotDiffer       │  │
│  │    Sanctions alerts • Property changes • New entities│  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Skill Chips (15 agents)                 │  │
│  │   + SkillLLMHelper (structured output, evidence     │  │
│  │     grounding, 6 methodology prompts, token tracking)│  │
│  │                                                     │  │
│  │  Investigation:  entity_search, cross_reference,    │  │
│  │    document_analysis, nlp_extraction,               │  │
│  │    network_analysis, data_quality                   │  │
│  │                                                     │  │
│  │  Specialized:  financial_investigation,             │  │
│  │    government_accountability,                       │  │
│  │    environmental_investigation,                     │  │
│  │    labor_investigation, corporate_research          │  │
│  │                                                     │  │
│  │  Monitoring:  monitoring                            │  │
│  │  Publication: verification, story_development       │  │
│  │  Resources:   resources                             │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

## Seven-Layer Architecture

### Layer 1: Orchestrator (Supervisor)

The orchestrator routes incoming requests to skill chips using a three-stage classification pipeline:

1. **Keyword matching**: Fast scan against a 130+ keyword routing table mapping terms to 14 investigation domains
2. **EFE scoring**: When multiple domains match or confidence is low, the Expected Free Energy calculator scores candidate domains using domain-specific weight profiles
3. **LLM fallback**: For ambiguous requests, an LLM classifier provides final domain assignment

Each domain has its own EFE weight profile reflecting journalism priorities:
- High-risk domains (financial investigation, verification, publication) → powerful models
- Discovery domains (entity search, monitoring) → fast models
- Analysis domains (network, NLP, cross-reference) → balanced models

### Layer 2: Cognition (EFE)

The Expected Free Energy engine provides active-inference-informed decision making:

- **Risk component**: Divergence between predicted and desired investigation outcomes
- **Ambiguity component**: Uncertainty in current evidence
- **Epistemic component**: Expected information gain from the proposed action

Twelve domain-specific weight profiles bias decisions toward journalism priorities. Publication decisions are risk-averse (risk=0.50); monitoring is curiosity-driven (epistemic=0.60); digital security is maximally cautious (risk=0.60).

### Layer 3: Kintsugi Engine (unchanged from Kintsugi)

The self-repairing core provides:
- **Shadow verification**: Parallel execution paths that cross-check results
- **Self-repair**: Automatic recovery from partial failures
- **Resilience**: Graceful degradation when services are unavailable

This layer is entirely domain-agnostic and transfers verbatim from Project-Kintsugi.

### Layer 4: Memory (CMA — unchanged)

The three-stage Contextual Memory Architecture:
- **Working memory**: Current investigation session state
- **Episodic memory**: Investigation event history and decision log
- **Semantic memory**: Learned patterns and investigation templates

Investigation context maps to BDI (Beliefs-Desires-Intentions):
- **Beliefs**: Current entity evidence and confidence levels
- **Desires**: Investigation hypotheses to prove or disprove
- **Intentions**: Active leads and next investigative steps

### Layer 5: Security (unchanged)

- **Intent Capsules**: Wrap every skill chip invocation with declared intent
- **Security Shield**: Pre-execution validation of proposed actions
- **Behavior Monitor**: Post-execution anomaly detection
- **Sandbox**: Isolated execution for untrusted operations

### Layer 6: Governance (adapted)

- **VALUES.json**: Journalism ethics constitution (Five Pillars: accuracy, source protection, public interest, proportionality, transparency)
- **Consensus Gates**: Human editorial approval required for publication, entity modification, and sensitive operations
- **OTel audit trail**: Every agent action is traced for accountability
- **Bloom accountability**: Prevents unilateral high-impact decisions

### Layer 7: FtM Data Spine (NEW)

The central integration layer connecting all skill chips to the FtM ecosystem:

- **Aleph API client**: Async wrapper for search, entity CRUD, cross-referencing, document ingest, streaming, entity sets, and notifications
- **FtM entity factory**: Validated entity creation with convenience methods for Person, Company, Ownership, Directorship, Payment
- **InvestigationEntity**: Harness-level wrapper adding confidence, provenance, and investigation context to FtM entities
- **External adapters**: OpenSanctions/yente (sanctions screening), OpenCorporates (corporate registries), ICIJ Offshore Leaks, GLEIF LEI (corporate identity)

## Skill Chip Architecture

Every skill chip inherits from `BaseSkillChip` and declares:

| Attribute | Purpose |
|-----------|---------|
| `domain` | Investigation domain for routing |
| `efe_weights` | Five Pillar weights for ethical prioritization |
| `capabilities` | Required API/tool access |
| `consensus_actions` | Actions requiring human approval |

### Skill Chip Catalog

| Chip | Domain | Key Capabilities |
|------|--------|-----------------|
| `entity_search` | Entity Search | Aleph search, entity expansion, external federation |
| `cross_reference` | Cross Reference | Xref triggering, match review, sanctions screening |
| `document_analysis` | Document Analysis | File upload, OCR, re-ingest, table extraction |
| `nlp_extraction` | NLP Extraction | NER, relationship extraction, financial patterns |
| `network_analysis` | Network Analysis | Graph building, centrality, community detection, ownership chains |
| `data_quality` | Data Quality | Validation, deduplication, normalization |
| `financial_investigation` | Financial | Ownership tracing, shell detection, sanctions exposure |
| `government_accountability` | Government | Campaign finance, FOIA, procurement, revolving door |
| `environmental_investigation` | Environmental | Pollution, permits, emissions, environmental justice |
| `labor_investigation` | Labor | OSHA, wage theft, supply chain labor, forced labor |
| `corporate_research` | Corporate | Company search, officers, corporate genealogy |
| `monitoring` | Monitoring | Watchlists, alerts, sanctions monitoring |
| `verification` | Verification | Fact-checking, source assessment, defamation review |
| `story_development` | Publication | Timelines, story outlines, methodology docs |
| `resources` | Resources | Training, methodology guides, tool reference |

## Data Flow

```
User Request
    │
    ▼
Orchestrator (classify → route)
    │
    ▼
Skill Chip (handle request)
    │
    ├──▶ Aleph API (search / CRUD / ingest)
    │       │
    │       ▼
    │    FtM Entities
    │
    ├──▶ Federated Search (parallel async fan-out)
    │    ├── OpenSanctions / yente
    │    ├── OpenCorporates
    │    ├── ICIJ Offshore Leaks
    │    ├── GLEIF
    │    └── (dedup + cache + rate limit)
    │       │
    │       ▼
    │    FtM Entities (converted + provenance)
    │
    ├──▶ Blockchain (Etherscan ETH / Blockstream BTC)
    │       │
    │       ▼
    │    FtM Entities (addresses, transactions)
    │
    ├──▶ Document Sources (Datashare / DocumentCloud)
    │       │
    │       ▼
    │    FtM Document + NER entities + Mention links
    │
    ├──▶ Graph Analytics Engine (NetworkX)
    │    ├── FtM entities → MultiDiGraph
    │    ├── Algorithms: brokers, communities, cycles,
    │    │   key players, hidden paths, anomalies, shell score
    │    └── Export: GEXF, GraphML, CSV, D3, Cytoscape
    │       │
    │       ▼
    │    Graph findings + export files
    │
    ├──▶ LLM Analysis (via SkillLLMHelper)
    │    ├── Ollama (local, default)
    │    ├── → Anthropic (cloud fallback)
    │    └── → Stub (test fallback)
    │       │
    │       ▼
    │    Structured findings (JSON) + token tracking
    │
    ├──▶ Timeline Analysis
    │       │
    │       ▼
    │    Temporal events + burst/coincidence patterns
    │
    └──▶ Export Pipeline
         ├── Markdown investigation report
         ├── FtM bundle (JSONL/zip for Aleph re-import)
         └── Graph visualization files
    │
    ▼
SkillResponse
    │
    ├── produced_entities: [FtM entity dicts]
    ├── result_confidence: float
    ├── suggestions: [next steps]
    ├── requires_consensus: bool
    └── consensus_action: str | None
    │
    ▼
Governance Check (consensus gate if required)
    │
    ▼
Response to User

    ┌──────────────────────────────────┐
    │  Background: Monitoring Loop     │
    │  ChangeDetector.check_all()      │
    │  → Federated search snapshots    │
    │  → SnapshotDiffer                │
    │  → ChangeAlert (new entity,      │
    │    sanctions, property changes)   │
    └──────────────────────────────────┘
```

## Modules Transferred from Kintsugi (unchanged)

These modules transfer verbatim — the Kintsugi architecture is domain-agnostic:

- `kintsugi_engine/` — Shadow verification, self-repair, resilience
- `memory/` — CMA three-stage memory pipeline
- `security/` — Intent Capsules, Shield, Monitor, Sandbox
- `plugins/` — Plugin SDK, loader, registry
- `multitenancy/` — Per-investigation isolation
- `models/` — Database models
- `api/` — FastAPI routes
- `adapters/` — Platform adapters
- `integrations/` — External service integrations
- `tuning/` — Model tuning utilities
- `config/` — Configuration management
- `db.py` — Database connection

## Modules Adapted for Journalism

- `cognition/efe.py` — 12 investigation-specific EFE weight profiles
- `cognition/orchestrator.py` — 130+ keyword routing table for investigation domains
- `bdi/` — Investigation BDI templates (beliefs=evidence, desires=hypotheses, intentions=leads)
- `governance/` — VALUES.json rewritten for journalism ethics

## Modules New for FtM

- `ftm/data_spine.py` — FtM entity factory, domain classification, investigation wrappers
- `ftm/aleph_client.py` — Async Aleph REST API client
- `ftm/external/adapters.py` — OpenSanctions, OpenCorporates, ICIJ, GLEIF clients

## New Subsystems (Sprints 1–9)

### LLM Abstraction Layer (`cognition/llm_*`)

Provider-agnostic LLM interface with cascading fallback:

- `llm_base.py`: `LLMClient` ABC with `complete`, `classify_intent`, `generate_content`, `extract_entities` methods. `LLMResponse` dataclass with text, model, provider, token counts, cost.
- `llm_ollama.py`: Local Ollama client. Tier mapping: fast→llama3.2:3b, balanced→mistral:7b, powerful→llama3.1:70b.
- `llm_anthropic.py`: Anthropic Claude client. Cloud fallback when local unavailable.
- `llm_stub.py`: Canned-response client with `call_log` for test assertions.
- `llm_factory.py`: `get_llm_client()` factory reading `LLM_PROVIDER` config. `FallbackLLMClient` wraps a chain (Ollama → Anthropic → Stub) and cascades on failure.

### Data Federation (`ftm/external/`)

Parallel async search across multiple data sources:

- `converters.py`: FtM converters for yente, OpenCorporates, ICIJ, GLEIF — normalizing each source's response format into standard FtM entities with provenance tracking.
- `federation.py`: `FederatedSearch` with async fan-out to all sources simultaneously. Deduplication by entity name/ID similarity. Rate limiting and response caching per source. Graceful degradation (partial results if some sources fail).
- `rate_limit.py`: `TokenBucketLimiter` (per-second), `MonthlyCounter` (budget caps), `ResponseCache` (TTL-based in-memory).

### Blockchain Investigation (`ftm/external/blockchain.py`)

- `EtherscanClient`: ETH address validation, balance lookup, transaction history, counterparty analysis, FtM entity conversion.
- `BlockstreamClient`: BTC address validation, balance, transaction history.
- Automatic address type detection (ETH vs BTC by format).

### Graph Analytics Engine (`graph/`)

NetworkX-based investigative graph analysis:

- `ftm_loader.py`: `FtMGraphLoader` converts FtM entity lists to NetworkX MultiDiGraph. Handles all 11 FtM relationship schemas. Edge weighting by relationship strength (Ownership=1.0 → UnknownLink=0.3). Safety cap at 50K nodes.
- `algorithms.py`: `InvestigativeAnalysis` with 7 algorithms:
  - `find_brokers()`: Betweenness centrality for intermediary detection
  - `find_communities()`: Louvain (or label propagation) clustering
  - `find_circular_ownership()`: Johnson's algorithm for ownership cycles
  - `find_key_players()`: PageRank + degree centrality composite
  - `find_hidden_connections()`: All shortest paths between entities
  - `find_structural_anomalies()`: Fan-out, bridge nodes, missing officers
  - `shell_company_topology_score()`: Composite 0–1 risk from graph signals
- `exporters.py`: `GraphExporter` for GEXF (Gephi), GraphML, Cytoscape JSON, D3 JSON, CSV.
- `engine.py`: `GraphEngine` orchestrating the full workflow — build from entities, Aleph, or federation → analysis → export.

### Export & Reporting (`export/`)

Investigation output pipeline:

- `markdown.py`: `MarkdownReport` generates structured Markdown with executive summary, entity inventory (grouped by schema), network analysis findings, timeline, data sources, methodology & limitations.
- `ftm_bundle.py`: `FtMBundleExporter` for Aleph re-import. JSONL, zip bundle with manifest.json, bytes for API responses. Enables round-trip: investigate in Emet → export → import into Aleph.
- `timeline.py`: `TimelineAnalyzer` extracts dated events from 11 FtM date properties, detects temporal patterns:
  - Burst detection: N entities created within M days (shell company indicator)
  - Coincidence detection: incorporation timing near payment timing

### Monitoring (`monitoring/`)

Change detection for ongoing investigations:

- `ChangeAlert`: Structured alert with type (new_entity, changed_property, new_sanction, removed_entity), severity, provenance.
- `SnapshotDiffer`: Compares two entity snapshots to detect all change types. Automatic sanctions detection from schema/topic fields.
- `ChangeDetector`: Persistent monitoring with JSON file storage, query registration, scheduled checks against federated search, snapshot management.

### Document Ingestion (`ftm/external/document_sources.py`)

Adapters for established document processing tools (Emet does not perform OCR — it ingests results from tools that do):

- `DatashareClient`: Queries self-hosted ICIJ Datashare instances. Search, get_document, get_named_entities, search_to_ftm. NER results converted to Person/Organization FtM entities linked to source documents via Mention entities.
- `DocumentCloudClient`: Queries MuckRock/IRE DocumentCloud API. Search, get_document, get_text, search_to_ftm, health_check.

### Skill Chip LLM Integration (`skills/llm_integration.py`)

Shared LLM infrastructure for skill chips:

- `SkillLLMHelper`: Wraps LLM client with investigative methodology prompts, evidence grounding (FtM entity formatting), structured JSON output parsing, token/cost tracking.
- 6 methodology-encoding system prompts: `investigative_base`, `entity_extraction`, `corporate_analysis`, `story_development`, `verification`, `financial_analysis`.
- High-level methods: `analyze`, `analyze_structured`, `extract_entities`, `classify_risk`, `generate_narrative`, `verify_claims`.
- `parse_json_response()`: Robust parser handling markdown fences, preamble text, embedded JSON.
- `TokenUsage`: Cross-workflow tracking of input/output tokens, cost, and per-call breakdown.
