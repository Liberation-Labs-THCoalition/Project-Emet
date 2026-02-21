# Emet — Architecture

## Overview

The Emet is an agentic investigative journalism framework built on the [**Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture, adapted for the **FollowTheMoney (FtM) data ecosystem** and OCCRP's Aleph investigative platform.

It orchestrates a swarm of specialized skill chips (agents) that collaboratively search, analyze, cross-reference, and verify investigative leads — all while operating within a strict journalism ethics governance layer.

```
┌───────────────────────────────────────────────────────────┐
│                    Emet                            │
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
│  │  • LLM Client       │  │  • OTel audit trail         │  │
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
│  │              FtM Data Spine (NEW)                    │  │
│  │   Aleph API • FtM entities • External sources       │  │
│  └──────────────┬──────────────────────┬───────────────┘  │
│                 │                      │                   │
│  ┌──────────────▼──────────────────────▼───────────────┐  │
│  │              Skill Chips (15 agents)                 │  │
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
    ├──▶ External Sources (OpenSanctions / OpenCorporates / ICIJ / GLEIF)
    │       │
    │       ▼
    │    FtM Entities (converted)
    │
    ├──▶ NLP Pipeline (spaCy / transformers)
    │       │
    │       ▼
    │    Extracted Entities + Relationships
    │
    └──▶ Network Analysis (NetworkX / igraph)
            │
            ▼
         Graph Metrics + Visualizations
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
- `skills/` — 15 journalism skill chips (replacing 22 nonprofit chips)
