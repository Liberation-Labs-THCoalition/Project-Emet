# Emet

**Investigative Journalism Agentic Framework**

An AI-powered multi-agent system for investigative journalism, built on the [Kintsugi](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture and the [FollowTheMoney](https://followthemoney.tech/) data ecosystem.

## What It Does

Emet orchestrates 15 specialized AI agents ("skill chips") that collaboratively investigate corruption, financial crime, government accountability, and corporate misconduct — all while operating within a strict journalism ethics governance layer.

**Core capabilities:**
- Search entities across OCCRP Aleph, OpenSanctions, OpenCorporates, ICIJ Offshore Leaks, and GLEIF
- Federated search with parallel async fan-out, deduplication, rate limiting, and caching
- Cross-reference entities between datasets with automated sanctions screening
- Graph analytics engine (NetworkX): circular ownership, broker detection, community clustering, shell company scoring, key player ranking, hidden connection tracing, structural anomaly detection
- Export to Gephi (GEXF), GraphML, CSV, D3.js, and Cytoscape.js for visualization
- Blockchain investigation: Ethereum (Etherscan) and Bitcoin (Blockstream) address analysis
- Document ingestion from Datashare (ICIJ) and DocumentCloud (MuckRock/IRE) with NER→FtM conversion
- Temporal pattern detection: burst analysis, coincidence detection across entity timelines
- Investigation reports in Markdown with executive summary, entity inventory, and network findings
- FtM bundle export (JSONL/zip) for round-trip Aleph re-import
- Change detection and monitoring: snapshot diffing, sanctions alerts, property change tracking
- LLM-powered analysis via local Ollama (default) with Anthropic Claude fallback
- Verify findings and assess source reliability before publication

**Specialized investigation domains:**
- Financial investigation (shell companies, money trails, sanctions exposure)
- Government accountability (campaign finance, FOIA, procurement, revolving door)
- Environmental investigation (pollution, permits, climate disclosure)
- Labor investigation (OSHA, wage theft, forced labor screening)
- Corporate research (registries, officers, corporate genealogy)

## Architecture

Seven-layer architecture inherited from Kintsugi, adapted for journalism:

| Layer | Component | Status |
|-------|-----------|--------|
| 1 | **Orchestrator** — keyword/EFE/LLM routing to 14 domains | Adapted |
| 2 | **Cognition (EFE)** — 12 investigation-specific weight profiles | Adapted |
| 2a | **LLM Abstraction** — Ollama (local) → Anthropic (cloud) → Stub (test) with cascading fallback | **New** |
| 3 | **Kintsugi Engine** — shadow verification, self-repair | Unchanged |
| 4 | **Memory (CMA)** — investigation context, BDI state | Unchanged |
| 5 | **Security** — Intent Capsules, Shield, Monitor | Unchanged |
| 6 | **Governance** — VALUES.json, Consensus Gates, OTel | Adapted |
| 7 | **FtM Data Spine** — Aleph API, entity factory, federated search, blockchain | **New** |
| 8 | **Graph Analytics** — NetworkX engine, 7 investigative algorithms, multi-format export | **New** |
| 9 | **Export & Reporting** — Markdown reports, FtM bundles, temporal analysis | **New** |
| 10 | **Monitoring** — Change detection, snapshot diffing, sanctions alerts | **New** |

See [ARCHITECTURE.md](ARCHITECTURE.md) for full technical documentation.

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (for Aleph services)
- An Aleph instance (OpenAleph, Aleph Pro, or local Docker)
- API keys for external services (optional but recommended):
  - OpenSanctions API key
  - OpenCorporates API token
  - Aleph API key

## Quick Start

```bash
# Clone
git clone https://github.com/Liberation-Labs-THCoalition/Project-Emet.git
cd Project-Emet

# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your API keys and Aleph instance URL

# Run (development)
uvicorn emet.api.main:app --reload --port 8000

# Run (Docker)
docker-compose up -d
```

## Configuration

Environment variables (`.env`):

```bash
# Aleph connection
ALEPH_HOST=http://localhost:8080
ALEPH_API_KEY=your-api-key

# External sources
OPENSANCTIONS_API_KEY=your-key
OPENCORPORATES_TOKEN=your-token

# LLM providers (cascading: Ollama → Anthropic → Stub)
LLM_PROVIDER=ollama              # ollama | anthropic | stub
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODELS=llama3.2:3b,mistral:7b,llama3.1:70b  # fast,balanced,powerful
LLM_FALLBACK_ENABLED=true        # Fall through to next provider on failure
ANTHROPIC_API_KEY=your-key        # Only needed if using Anthropic

# Blockchain (optional, free tiers)
ETHERSCAN_API_KEY=your-key        # 5 req/sec free tier
# Blockstream BTC API requires no key

# Document sources (optional)
DATASHARE_HOST=http://localhost:8080
DATASHARE_PROJECT=local-datashare

# Monitoring
EMET_MONITORING_DIR=.emet_monitoring  # Snapshot storage

# Database
DATABASE_URL=postgresql://ftm:ftm@localhost:5432/emet

# Redis (for Celery task queue)
REDIS_URL=redis://localhost:6379/0
```

## Skill Chips

| Chip | Domain | Description |
|------|--------|-------------|
| `entity_search` | Investigation | Search Aleph + external sources |
| `cross_reference` | Investigation | Entity matching, sanctions screening |
| `document_analysis` | Investigation | File ingest, OCR, table extraction |
| `nlp_extraction` | Investigation | NER, relationship extraction, patterns |
| `network_analysis` | Investigation | Graph algorithms, ownership chains |
| `data_quality` | Investigation | Validation, dedup, normalization |
| `financial_investigation` | Specialized | Money trails, shell detection |
| `government_accountability` | Specialized | Campaign finance, FOIA, procurement |
| `environmental_investigation` | Specialized | Pollution, permits, climate |
| `labor_investigation` | Specialized | OSHA, wage theft, forced labor |
| `corporate_research` | Specialized | Company registries, officers |
| `monitoring` | Monitoring | Watchlists, alerts, sanctions monitor |
| `verification` | Publication | Fact-checking, source assessment |
| `story_development` | Publication | Timelines, outlines, methodology |
| `resources` | Resources | Training, guides, reference |

## Ethics & Governance

All agent actions are governed by [VALUES.json](VALUES.json), which implements the **Five Pillars of Journalism**:

1. **Accuracy** (weight: 0.25) — Every claim traceable to source material
2. **Source Protection** (weight: 0.25) — Source identity never exposed without consent
3. **Public Interest** (weight: 0.20) — Investigation scope proportionate to significance
4. **Proportionality** (weight: 0.15) — Least intrusive method preferred
5. **Transparency** (weight: 0.15) — Methodology documented and auditable

**Consensus Gates** require human editorial approval for:
- Publishing findings
- Confirming entity matches
- Accessing sensitive source data
- Flagging entities as suspicious

**AI Ethics**: AI-generated findings are always flagged and require human verification. The system never fabricates evidence, impersonates sources, or publishes without human review.

## Project Structure

```
Project-Emet/
├── emet/
│   ├── cognition/              # LLM abstraction + routing
│   │   ├── llm_base.py         # LLMClient ABC, LLMResponse dataclass
│   │   ├── llm_ollama.py       # Local Ollama client (default)
│   │   ├── llm_anthropic.py    # Anthropic Claude client (fallback)
│   │   ├── llm_stub.py         # Canned-response client (testing)
│   │   ├── llm_factory.py      # Provider factory + FallbackLLMClient
│   │   ├── efe.py              # EFE active inference calculator
│   │   ├── orchestrator.py     # Keyword/EFE/LLM routing
│   │   └── model_router.py     # Tier-to-model mapping
│   ├── kintsugi_engine/        # Self-repairing core (from Kintsugi)
│   ├── memory/                 # CMA pipeline (from Kintsugi)
│   ├── security/               # Intent Capsules, Shield, Monitor
│   ├── governance/             # Consensus gates, OTel, Bloom
│   ├── bdi/                    # Beliefs-Desires-Intentions models
│   ├── plugins/                # Plugin SDK and loader
│   ├── multitenancy/           # Per-investigation isolation
│   ├── ftm/                    # FollowTheMoney integration layer
│   │   ├── data_spine.py       # FtM entity factory + domain classification
│   │   ├── aleph_client.py     # Async Aleph REST API client
│   │   └── external/           # Federated data sources
│   │       ├── adapters.py     # Yente, OpenCorporates, ICIJ, GLEIF clients
│   │       ├── converters.py   # FtM converters for all 4 sources
│   │       ├── federation.py   # FederatedSearch (parallel async fan-out)
│   │       ├── rate_limit.py   # Token bucket, monthly counter, response cache
│   │       ├── blockchain.py   # Etherscan (ETH) + Blockstream (BTC) clients
│   │       └── document_sources.py  # Datashare + DocumentCloud adapters
│   ├── graph/                  # Network analysis engine
│   │   ├── ftm_loader.py       # FtM entities → NetworkX MultiDiGraph
│   │   ├── algorithms.py       # 7 investigative algorithms
│   │   ├── exporters.py        # GEXF, GraphML, CSV, D3, Cytoscape export
│   │   └── engine.py           # GraphEngine orchestrator
│   ├── export/                 # Investigation output pipeline
│   │   ├── markdown.py         # Markdown report generator
│   │   ├── ftm_bundle.py       # FtM JSONL/zip export for Aleph re-import
│   │   └── timeline.py         # Temporal event extraction + pattern detection
│   ├── monitoring/             # Change detection + alerts
│   │   └── __init__.py         # ChangeDetector, SnapshotDiffer, ChangeAlert
│   ├── skills/                 # Investigation skill chips
│   │   ├── base.py             # BaseSkillChip + domain enums
│   │   ├── llm_integration.py  # SkillLLMHelper + methodology prompts
│   │   ├── investigation/      # Core investigation agents (6 chips)
│   │   ├── specialized/        # Domain-specific agents (5 chips)
│   │   ├── publication/        # Verification + story development (2 chips)
│   │   └── resources/          # Training and reference (1 chip)
│   ├── models/                 # Database models
│   ├── api/                    # FastAPI routes
│   ├── config/                 # Configuration
│   └── db.py                   # Database connection
├── migrations/                 # Alembic database migrations
├── tests/                      # 311 tests (E2E, integration, unit)
├── docs/                       # COMPETITIVE_ROADMAP, PILOT_PLAN, USER_GUIDE
├── VALUES.json                 # Journalism ethics constitution
├── ARCHITECTURE.md             # Technical architecture docs
├── docker-compose.yml          # Docker services
└── pyproject.toml              # Python package config
```

## Testing

```bash
# Full test suite (311 tests, ~3 seconds)
python -m pytest tests/ -q

# Individual suites
python tests/test_e2e.py                        # 51 E2E smoke tests
PYTHONPATH=. python tests/test_integration.py   # 66 integration tests (mock Aleph)
python -m pytest tests/test_graph.py            # 37 graph analytics tests
python -m pytest tests/test_federation.py       # 40 federation + blockchain tests
python -m pytest tests/test_export.py           # 24 export pipeline tests
python -m pytest tests/test_monitoring.py       # 21 monitoring tests
python -m pytest tests/test_document_sources.py # 24 document source tests
python -m pytest tests/test_llm_integration.py  # 30 LLM integration tests
python -m pytest tests/test_integration_pipeline.py  # 18 cross-module pipeline tests
```

No external services required — all tests use stubs, mocks, and synthetic datasets. The E2E tests verify graceful degradation when Aleph/external APIs are unreachable.

## Provenance & Heritage

Emet's core infrastructure is derived from [**Project-Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi), a domain-agnostic self-repairing agentic harness. The `kintsugi_engine/` directory, memory architecture (CMA), BDI cognition, EFE active inference routing, security layer, and plugin system transfer directly — they are intentionally domain-agnostic and work unchanged. The journalism-specific layers (skill chips, FtM data spine, Aleph integration, ethics constitution) are new.

The name "Emet" (אמת) is Hebrew for "truth." In Jewish folklore, it is the word inscribed on the forehead of the Golem — a construct animated to protect its community.

Built on:
- [**Project-Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) — Self-repairing agentic harness (7 layers, BDI cognition, EFE routing)
- [**FollowTheMoney**](https://followthemoney.tech/) — OCCRP's data model for organized crime and corruption investigations
- [**Aleph**](https://github.com/alephdata/aleph) — OCCRP's investigative data platform (search, cross-reference, ingest)
- [**OpenSanctions / yente**](https://www.opensanctions.org/) — 325+ sanctions and PEP lists
- [**OpenCorporates**](https://opencorporates.com/) — 200M+ companies from 145+ jurisdictions
- [**ICIJ Offshore Leaks**](https://offshoreleaks.icij.org/) — 810K+ offshore entities
- [**GLEIF**](https://www.gleif.org/) — Global Legal Entity Identifier index

## License

**Emet Source-Available License v1.0** — See [LICENSE](LICENSE) for full terms.

Emet is **source-available, not open source**. The code is public for transparency, security auditing, and trust — but usage rights depend on who you are and what you're doing:

- **Investigative journalists, newsrooms, press freedom orgs, anti-corruption NGOs, and academic journalism programs** → Free. No cost, no catch. This is who Emet was built for.
- **Everyone else** (compliance, KYC/AML, due diligence, corporate intelligence, litigation support) → Commercial license required. Contact humboldtnomad@gmail.com.
- **Nobody, under any license** → may use Emet for surveillance of journalists, press suppression, targeting whistleblowers, mass surveillance, or circumventing press freedom protections. These restrictions are non-negotiable and grounded in international human rights law.

For commercial licensing inquiries: **humboldtnomad@gmail.com**
