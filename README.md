# Emet

**Investigative Journalism Agentic Framework**

An AI-powered multi-agent system for investigative journalism, built on the [Kintsugi](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture and the [FollowTheMoney](https://followthemoney.tech/) data ecosystem.

## What It Does

Emet orchestrates 15 specialized AI agents ("skill chips") that collaboratively investigate corruption, financial crime, government accountability, and corporate misconduct — all while operating within a strict journalism ethics governance layer.

**Core capabilities:**
- Search entities across OCCRP Aleph, OpenSanctions, OpenCorporates, ICIJ Offshore Leaks, and GLEIF
- Cross-reference entities between datasets with automated sanctions screening
- Ingest and analyze documents (OCR, NER, relationship extraction)
- Build and analyze network graphs of corporate/financial relationships
- Trace beneficial ownership through layered corporate structures
- Monitor watchlists and receive alerts on entity changes
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
| 3 | **Kintsugi Engine** — shadow verification, self-repair | Unchanged |
| 4 | **Memory (CMA)** — investigation context, BDI state | Unchanged |
| 5 | **Security** — Intent Capsules, Shield, Monitor | Unchanged |
| 6 | **Governance** — VALUES.json, Consensus Gates, OTel | Adapted |
| 7 | **FtM Data Spine** — Aleph API, entity factory, external sources | **New** |

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
git clone https://github.com/Liberation-Labs-THCoalition/Project-FtM.git
cd Project-FtM

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

# LLM providers
ANTHROPIC_API_KEY=your-key
OPENAI_API_KEY=your-key

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
Project-FtM/
├── emet/
│   ├── cognition/          # EFE calculator, orchestrator, model router
│   ├── kintsugi_engine/    # Self-repairing core (from Kintsugi)
│   ├── memory/             # CMA pipeline (from Kintsugi)
│   ├── security/           # Intent Capsules, Shield, Monitor
│   ├── governance/         # Consensus gates, OTel, Bloom
│   ├── bdi/                # Beliefs-Desires-Intentions models
│   ├── plugins/            # Plugin SDK and loader
│   ├── multitenancy/       # Per-investigation isolation
│   ├── ftm/                # FollowTheMoney integration layer
│   │   ├── data_spine.py   # FtM entity factory + domain classification
│   │   ├── aleph_client.py # Async Aleph REST API client
│   │   └── external/       # OpenSanctions, OpenCorporates, ICIJ, GLEIF
│   ├── skills/             # Investigation skill chips
│   │   ├── base.py         # BaseSkillChip + domain enums
│   │   ├── investigation/  # Core investigation agents
│   │   ├── specialized/    # Domain-specific agents
│   │   ├── monitoring/     # Continuous monitoring
│   │   ├── publication/    # Verification + story development
│   │   └── resources/      # Training and reference
│   ├── models/             # Database models
│   ├── api/                # FastAPI routes
│   ├── config/             # Configuration
│   └── db.py               # Database connection
├── migrations/             # Alembic database migrations
├── tests/                  # Test suite
├── VALUES.json             # Journalism ethics constitution
├── ARCHITECTURE.md         # Technical architecture docs
├── docker-compose.yml      # Docker services
└── pyproject.toml          # Python package config
```

## Provenance

Built on:
- **Project-Kintsugi** — Self-repairing agentic harness (7 layers, BDI cognition, EFE routing)
- **FollowTheMoney** — OCCRP's data model for organized crime and corruption investigations
- **Aleph** — OCCRP's investigative data platform (search, cross-reference, ingest)
- **OpenSanctions / yente** — 325+ sanctions and PEP lists
- **OpenCorporates** — 200M+ companies from 145+ jurisdictions
- **ICIJ Offshore Leaks** — 810K+ offshore entities
- **GLEIF** — Global Legal Entity Identifier index

## License

MIT
