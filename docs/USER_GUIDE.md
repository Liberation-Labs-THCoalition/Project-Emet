# Emet — User Guide

A practical guide to setting up and using the Emet investigative journalism framework.

---

## Table of Contents

1. [What is Emet?](#1-what-is-emet)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Connecting to Aleph](#5-connecting-to-aleph)
6. [Your First Investigation](#6-your-first-investigation)
7. [Working with Skill Chips](#7-working-with-skill-chips)
8. [Investigation Workflows](#8-investigation-workflows)
9. [External Data Sources](#9-external-data-sources)
10. [Ethics and Governance](#10-ethics-and-governance)
11. [API Reference](#11-api-reference)
12. [Docker Deployment](#12-docker-deployment)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What is Emet?

Emet is a multi-agent AI system that helps investigative journalists search, cross-reference, analyze, and verify data across the [FollowTheMoney](https://followthemoney.tech/) ecosystem. It orchestrates 15 specialized agents ("skill chips") that each handle a different aspect of the investigative workflow — from entity search to network analysis to pre-publication verification.

The system is built on the [Kintsugi](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture, which provides safety-critical infrastructure: shadow verification of agent outputs, ethics governance, memory management, and security monitoring.

**What it is:** An intelligent assistant that helps you work faster and more thoroughly across investigative datasets, while maintaining strict editorial controls.

**What it is not:** An autonomous investigator. Every finding requires human verification. Every publication decision requires human approval. The system never fabricates evidence, impersonates sources, or acts without oversight.

---

## 2. System Requirements

### Minimum

- Python 3.11 or later
- 4 GB RAM
- PostgreSQL 15+ (or the Docker Compose stack handles this)
- Redis 7+ (or Docker Compose)

### Recommended

- Python 3.12
- 8+ GB RAM (for NLP models)
- Docker & Docker Compose v2
- An Aleph instance (OpenAleph self-hosted, or Aleph Pro SaaS access)

### Optional Services

| Service | What For | Free Tier? |
|---------|----------|------------|
| [OpenSanctions / yente](https://opensanctions.org) | Sanctions & PEP screening | Yes (rate limited) |
| [OpenCorporates](https://opencorporates.com) | Company registry lookups | Yes (200 req/month; journalist access available) |
| [ICIJ Offshore Leaks](https://offshoreleaks.icij.org) | Offshore entity search | Yes |
| [GLEIF](https://gleif.org) | LEI corporate identity | Yes (no key needed) |
| Anthropic or OpenAI API | LLM-powered classification & extraction | No |

---

## 3. Installation

### Option A: Local Development Install

```bash
# Clone the repository
git clone https://github.com/Liberation-Labs-THCoalition/Project-Emet.git
cd Project-Emet

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with development dependencies
pip install -e ".[dev]"

# Copy the example environment file
cp .env.example .env
```

### Option B: Docker (Full Stack)

This starts the harness along with PostgreSQL and Redis — everything you need except Aleph itself.

```bash
git clone https://github.com/Liberation-Labs-THCoalition/Project-Emet.git
cd Project-Emet
cp .env.example .env
# Edit .env (see Configuration below)

docker-compose up -d
```

### Option C: Docker with Local Aleph

If you're running OpenAleph locally too, they can share the same Docker network:

```bash
# In your Aleph directory
docker-compose up -d

# In your Project-Emet directory
# Set ALEPH_HOST=http://aleph_api:8080 in .env (use the Aleph container name)
docker-compose up -d
```

### Installing NLP Models (Optional)

For enhanced entity extraction beyond Aleph's built-in NLP:

```bash
# English transformer model (best accuracy, ~500MB)
python -m spacy download en_core_web_trf

# Or the smaller statistical model (~50MB, less accurate)
python -m spacy download en_core_web_sm

# For multilingual investigations
python -m spacy download xx_ent_wiki_sm
```

---

## 4. Configuration

Edit your `.env` file with the credentials for the services you'll use. Only `ALEPH_HOST` is strictly required — everything else enables additional capabilities.

```bash
# ─── Required ────────────────────────────────────────
ALEPH_HOST=http://localhost:8080       # Your Aleph instance URL
ALEPH_API_KEY=your-api-key             # Aleph API key (from your Aleph user profile)

# ─── Database (defaults work with Docker Compose) ────
DATABASE_URL=postgresql+asyncpg://ftm:ftm@localhost:5432/emet
REDIS_URL=redis://localhost:6379/0

# ─── External Data Sources (optional) ────────────────
OPENSANCTIONS_API_KEY=                 # From opensanctions.org/account
OPENCORPORATES_API_TOKEN=              # From opencorporates.com/users/account

# ─── LLM Providers (optional, for smart routing) ─────
ANTHROPIC_API_KEY=                     # For Claude-based classification
OPENAI_API_KEY=                        # Alternative LLM provider
```

### Getting Your Aleph API Key

1. Log into your Aleph instance
2. Go to your user profile (top-right menu → Settings)
3. Under "API Key", generate or copy your key
4. Paste it as `ALEPH_API_KEY` in `.env`

### Getting an OpenSanctions Key

1. Go to [opensanctions.org](https://opensanctions.org)
2. Create an account
3. Your API key is in your account dashboard
4. Journalists and NGOs can request enhanced free access

---

## 5. Connecting to Aleph

### What is Aleph?

Aleph is OCCRP's investigative data platform. It stores entities (people, companies, vessels, documents) in the [FollowTheMoney](https://followthemoney.tech/) data model and provides search, cross-referencing, and document processing.

There are three variants:

| Variant | Access | Best For |
|---------|--------|----------|
| **Aleph Pro** (OCCRP) | By application to OCCRP | Access to OCCRP's global datasets |
| **OpenAleph** | Self-hosted (MIT license) | Your own private investigations |
| **Public Aleph** | aleph.occrp.org | Browsing public datasets |

### Verifying Your Connection

Once configured, test the connection:

```python
import asyncio
from emet.ftm.aleph_client import AlephClient, AlephConfig

async def test():
    client = AlephClient(AlephConfig(
        host="http://localhost:8080",
        api_key="your-key",
    ))
    collections = await client.list_collections(limit=5)
    print(f"Connected! Found {collections.get('total', 0)} collections.")
    for c in collections.get("results", []):
        print(f"  - {c.get('label')} (ID: {c.get('id')})")

asyncio.run(test())
```

---

## 6. Your First Investigation

Here's a walkthrough of a basic investigation workflow using the Python API directly. This demonstrates what each skill chip does and how they chain together.

### Step 1: Start an Investigation Context

```python
import asyncio
from emet.skills import get_chip
from emet.skills.base import SkillContext, SkillRequest

# Create a shared investigation context
ctx = SkillContext(
    investigation_id="inv-001",
    user_id="journalist-1",
    hypothesis="Investigate beneficial ownership of Acme Holdings Ltd",
    collection_ids=["42"],  # Your Aleph collection ID
)
```

### Step 2: Search for Entities

```python
async def search():
    chip = get_chip("entity_search")
    
    # Search Aleph
    response = await chip.handle(
        SkillRequest(intent="search", parameters={"query": "Acme Holdings"}),
        ctx,
    )
    print(response.content)
    # → "Found 12 results for 'Acme Holdings' (showing 12)"
    
    # The response contains FtM entities
    for result in response.data.get("results", [])[:3]:
        entity = result["entity"]
        print(f"  {entity['schema']}: {result['names']}")

asyncio.run(search())
```

### Step 3: Screen Against Sanctions

```python
async def screen():
    chip = get_chip("cross_reference")

    response = await chip.handle(
        SkillRequest(
            intent="screen_sanctions",
            parameters={"query": "Acme Holdings Ltd"},
        ),
        ctx,
    )
    print(response.content)
    # → "Sanctions screening: 3 potential matches, 1 high-confidence hit."
    
    if response.requires_consensus:
        print("⚠️  High-confidence sanctions hit — requires human review")
        for hit in response.data.get("high_confidence_hits", []):
            print(f"  Match: {hit}")

asyncio.run(screen())
```

### Step 4: Search External Sources

```python
async def external():
    chip = get_chip("entity_search")
    
    response = await chip.handle(
        SkillRequest(
            intent="search_external",
            parameters={
                "query": "Acme Holdings",
                "sources": ["opensanctions", "opencorporates", "icij", "gleif"],
            },
        ),
        ctx,
    )
    print(response.content)
    # → "External search: 27 results across 4 sources"
    
    for source, results in response.data.get("results_by_source", {}).items():
        count = len(results) if isinstance(results, list) else 0
        print(f"  {source}: {count} results")

asyncio.run(external())
```

### Step 5: Trace Ownership

```python
async def ownership():
    chip = get_chip("financial_investigation")
    
    response = await chip.handle(
        SkillRequest(
            intent="trace_ownership",
            parameters={
                "entity_name": "Acme Holdings Ltd",
                "max_depth": 10,
            },
        ),
        ctx,
    )
    print(response.content)
    # → "Beneficial ownership trace initiated (max depth: 10)."
    print("Data sources:", response.data.get("data_sources"))
    print("Pipeline:", response.data.get("pipeline"))

asyncio.run(ownership())
```

### Step 6: Verify Before Publishing

```python
async def verify():
    chip = get_chip("verification")
    
    response = await chip.handle(
        SkillRequest(
            intent="verify_claim",
            parameters={
                "claim": "Acme Holdings Ltd is beneficially owned by John Smith, "
                         "who is also a director of three BVI shell companies.",
                "evidence": [
                    "Aleph entity match (confidence 0.92)",
                    "OpenCorporates directorship records",
                    "ICIJ Offshore Leaks match",
                ],
            },
        ),
        ctx,
    )
    print(response.content)
    # → "Claim verification initiated."
    print("Steps:", response.data.get("verification_steps"))

asyncio.run(verify())
```

---

## 7. Working with Skill Chips

### How Skill Chips Work

Each chip is a specialized agent that handles one domain of investigation work. They all follow the same interface:

```python
chip = get_chip("chip_name")              # Instantiate from registry
response = await chip.handle(request, context)  # Execute
```

The **request** tells the chip what to do:
- `intent` — What action to take (e.g., "search", "screen_sanctions", "build_graph")
- `parameters` — Action-specific parameters (e.g., query terms, entity IDs, collection IDs)
- `raw_input` — Free-form text input (used as fallback when parameters aren't set)

The **response** tells you what happened:
- `content` — Human-readable summary
- `success` — Whether it worked
- `data` — Structured result data
- `produced_entities` — FtM entities created/found by this action
- `suggestions` — Recommended next steps
- `requires_consensus` — Whether human editorial approval is needed
- `result_confidence` — How confident the chip is in the result (0.0–1.0)

### Listing Available Chips

```python
from emet.skills import list_chips

for chip in list_chips():
    print(f"{chip['name']:30s} {chip['domain']:25s} {chip['description']}")
```

### Chip Quick Reference

#### Entity Search (`entity_search`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `search` | `query`, `schema`, `collections`, `countries`, `limit` | Full-text search across Aleph |
| `get_entity` | `entity_id` | Retrieve entity by ID |
| `expand` | `entity_id` | Find all connected entities |
| `similar` | `entity_id` | Find similar entities |
| `search_external` | `query`, `sources` | Federated search across external databases |

#### Cross-Reference (`cross_reference`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `trigger_xref` | `collection_id` | Start cross-referencing a collection |
| `get_xref_results` | `collection_id`, `min_score` | Retrieve ranked match results |
| `decide_match` | `collection_id`, `xref_id`, `decision` | Confirm/reject a match **(consensus required)** |
| `screen_sanctions` | `entity_data` or `query` | Screen entity against OpenSanctions |
| `batch_screen` | `collection_id` | Screen all entities in a collection |
| `match_entity` | `entity_data`, `target_dataset` | Match entity against a dataset |

#### Document Analysis (`document_analysis`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `upload` | `file_path`, `collection_id`, `language` | Upload a file to Aleph |
| `crawldir` | `directory`, `collection_id` | Recursively upload a directory |
| `reingest` | `collection_id` | Re-process all documents |
| `reindex` | `collection_id` | Rebuild search index |
| `classify` | `entity_id` | Classify document type |
| `extract_tables` | `entity_id` | Extract structured tables |
| `list_documents` | `collection_id` | List documents with metadata |

#### NLP Extraction (`nlp_extraction`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `extract` | `text`, `model` | Run NER on text |
| `extract_relationships` | `text` | Extract entity-entity relationships |
| `detect_language` | `text` | Detect language(s) |
| `extract_financial` | `text` | Find IBANs, amounts, SWIFT codes |
| `batch_extract` | `collection_id` | Run NLP pipeline on collection **(consensus required)** |

#### Network Analysis (`network_analysis`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `build_graph` | `collection_id` | Build network graph from entities |
| `shortest_path` | `source_entity_id`, `target_entity_id` | Find shortest connection path |
| `communities` | `algorithm` | Detect entity clusters (Louvain, etc.) |
| `centrality` | `metrics` | Calculate node importance metrics |
| `find_bridges` | — | Find entities connecting separate groups |
| `beneficial_ownership` | `entity_id`, `max_depth` | Trace ownership chain |
| `detect_cycles` | `type` | Find circular ownership/payment structures |
| `export_graph` | `format` | Export to GEXF, Cypher, GraphML, or JSON |

#### Financial Investigation (`financial_investigation`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `trace_ownership` | `entity_id` or `entity_name` | Trace beneficial ownership chain |
| `detect_shell` | `entity_id`, `entity_data` | Analyze shell company indicators |
| `money_trail` | `source_entity_id` | Follow payment chains |
| `sanctions_exposure` | `entity_id` | Direct + indirect sanctions exposure |
| `pep` | `query` | Screen for Politically Exposed Persons |
| `tax_haven` | `jurisdictions` | Analyze tax haven exposure |
| `offshore_check` | `query` | Search ICIJ Offshore Leaks |
| `lei_lookup` | `query` or `lei` | Search GLEIF LEI index |

#### Government Accountability (`government_accountability`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `campaign_finance` | `candidate`, `donor` | Analyze campaign contributions |
| `lobbying` | `entity_name` | Track lobbying disclosures |
| `procurement` | `contractor`, `agency` | Analyze government contracts |
| `foia` | `action` | Manage FOIA request tracking |
| `revolving_door` | `person_name` | Track government ↔ private sector movement |
| `conflict_of_interest` | `official_id`, `entity_id` | Detect conflicts |

#### Corporate Research (`corporate_research`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `company` | `query`, `jurisdiction` | Search OpenCorporates (200M+ companies) |
| `get_company` | `jurisdiction`, `company_number` | Get company by registration |
| `officers` | `query`, `jurisdiction` | Search company officers/directors |
| `subsidiaries` | `lei` or `query` | Map corporate tree via GLEIF |

#### Monitoring (`monitoring`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `create_watchlist` | `name`, `queries` | Create a monitoring watchlist |
| `check_watchlist` | `watchlist_id` | Run all watchlist queries |
| `monitor_entity` | `entity_id` or `entity_name` | Monitor an entity for changes |
| `monitor_collection` | `collection_id` | Monitor collection for updates |
| `sanctions_monitor` | — | Monitor sanctions list changes |
| `set_alert` | `condition`, `channel` | Configure alert rules |

#### Verification (`verification`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `fact_check` | `claim`, `evidence` | Verify claim against evidence |
| `source_reliability` | `source`, `type` | Assess source reliability |
| `corroborate` | `findings` | Check corroboration across sources |
| `legal_review` | `content`, `named_persons` | Screen for defamation risk **(consensus required)** |
| `pre_publication` | — | Full pre-publication checklist **(consensus required)** |

#### Story Development (`story_development`)

| Intent | Parameters | Description |
|--------|-----------|-------------|
| `timeline` | `events`, `collection_id` | Build investigation timeline |
| `outline` | — | Generate structured story outline |
| `key_findings` | — | Extract and rank key findings |
| `impact_assessment` | — | Assess investigation impact |
| `methodology_doc` | — | Generate methodology documentation |

---

## 8. Investigation Workflows

### Workflow A: Entity-Centered Investigation

This is the most common pattern — you have a name and want to find out everything about them.

```
1. entity_search → search("John Smith")
2. entity_search → expand(entity_id) — find connected entities
3. cross_reference → screen_sanctions(entity_data) — check watchlists
4. corporate_research → company("John Smith") — find company connections
5. financial_investigation → trace_ownership(entity_id) — follow the money
6. network_analysis → build_graph(collection_id) → centrality() — find key nodes
7. verification → fact_check(claim, evidence) — verify findings
8. story_development → outline() — structure the story
```

### Workflow B: Document-Led Investigation

You've received a cache of documents and need to extract intelligence from them.

```
1. document_analysis → upload(file_path, collection_id) — ingest documents
2. document_analysis → check_status(collection_id) — wait for processing
3. nlp_extraction → batch_extract(collection_id) — run NER across all docs
4. entity_search → search("*", collection_id) — see what was extracted
5. cross_reference → trigger_xref(collection_id) — match against all datasets
6. cross_reference → get_xref_results(collection_id) — review matches
7. network_analysis → build_graph(collection_id) — visualize relationships
```

### Workflow C: Financial Investigation

Follow the money through corporate structures.

```
1. entity_search → search("Acme Holdings") — find the entity
2. financial_investigation → detect_shell(entity_data) — shell company analysis
3. financial_investigation → trace_ownership(entity_id) — ownership chain
4. financial_investigation → offshore_check("Acme Holdings") — ICIJ check
5. financial_investigation → lei_lookup("Acme Holdings") — GLEIF identity
6. financial_investigation → sanctions_exposure(entity_id) — direct + indirect
7. financial_investigation → pep("John Smith") — PEP screening
8. network_analysis → detect_cycles(type="ownership") — circular structures
```

### Workflow D: Government Accountability

Investigate a public official or government contractor.

```
1. government_accountability → official_lookup(name) — PEP/official search
2. government_accountability → campaign_finance(candidate=name) — donors
3. government_accountability → lobbying(entity_name) — lobby connections
4. government_accountability → procurement(contractor, agency) — contracts
5. government_accountability → revolving_door(person_name) — career path
6. government_accountability → conflict_of_interest(official_id, entity_id)
7. monitoring → monitor_entity(entity_name) — ongoing monitoring
```

### Workflow E: Ongoing Monitoring

Set up continuous surveillance on investigation targets.

```
1. monitoring → create_watchlist(name, queries) — define what to watch
2. monitoring → monitor_entity(entity_name) — per-entity monitoring
3. monitoring → monitor_collection(collection_id) — collection changes
4. monitoring → sanctions_monitor() — sanctions list updates
5. monitoring → set_alert(condition, channel="slack") — configure notifications
6. monitoring → check_alerts() — periodic check (or run on schedule)
```

---

## 9. External Data Sources

### OpenSanctions / yente

The single most important external source for investigations. Aggregates 325+ sanctions, PEP, and watchlist datasets into a unified FtM-native format.

**What you get:** Sanctioned entities, Politically Exposed Persons, crime-related entities, company registries from multiple jurisdictions.

**Setup:** Get an API key at [opensanctions.org](https://opensanctions.org). Set `OPENSANCTIONS_API_KEY` in `.env`.

**Self-hosted option:** Run your own yente instance for unlimited, private screening:
```bash
docker run -p 9090:8000 ghcr.io/opensanctions/yente:latest
# Set OPENSANCTIONS_HOST=http://localhost:9090 in .env
```

### OpenCorporates

200M+ company records from 145+ jurisdictions. Essential for corporate structure research.

**What you get:** Company name, jurisdiction, registration number, status, registered address, officers/directors.

**Setup:** Create an account at [opencorporates.com](https://opencorporates.com). Journalists and NGOs can apply for free enhanced access.

### ICIJ Offshore Leaks

810K+ offshore entities from Panama Papers, Paradise Papers, Pandora Papers, and other major leak investigations.

**What you get:** Offshore entities, intermediaries, officers, and their relationships.

**Setup:** No API key required. The database is publicly searchable.

### GLEIF

Global Legal Entity Identifier index. Provides verified corporate identity and ownership relationships via standardized 20-character LEI codes.

**What you get:** Verified legal entity identity, direct and ultimate parent relationships, subsidiary relationships.

**Setup:** No API key required. Fully open access (CC0 license).

---

## 10. Ethics and Governance

### The Five Pillars

All agent actions are evaluated against `VALUES.json`, which encodes journalism ethics as machine-readable governance rules:

| Pillar | Weight | Core Principle |
|--------|--------|----------------|
| Accuracy | 0.25 | Every claim traceable to original source material |
| Source Protection | 0.25 | Source identity never exposed without explicit consent |
| Public Interest | 0.20 | Investigation scope proportionate to public significance |
| Proportionality | 0.15 | Least intrusive method preferred |
| Transparency | 0.15 | Methodology documented and auditable |

### Consensus Gates

Certain actions require human editorial approval before proceeding. When a skill chip response has `requires_consensus=True`, the system pauses and asks for human review.

Actions that always require consensus:
- Publishing or sharing investigation findings
- Confirming or rejecting entity matches (cross-reference decisions)
- Writing AI-extracted entities back to Aleph collections
- Flagging an entity as suspicious
- Accessing data classified as human-source sensitive
- Pre-publication legal review

### The "Never Trust an LLM" Principle

Inspired by the NYT AI investigation methodology:
- AI-generated findings are always flagged with `source_chip` metadata
- No claim is published without traceable evidence from original documents
- The verification chip provides structured evidence chain tracing
- Confidence levels are explicitly stated for every finding
- The system distinguishes between "confirmed fact" and "AI inference"

---

## 11. API Reference

### Starting the API Server

```bash
# Development (with hot reload)
uvicorn emet.api:app --reload --port 8000

# Production
uvicorn emet.api:app --host 0.0.0.0 --port 8000 --workers 4
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/agent/message` | Send a message to the orchestrator |
| `GET` | `/api/agent/investigations` | List active investigations |
| `GET` | `/api/memory/search` | Search investigation memory |
| `GET` | `/api/config/skills` | List available skill chips |
| `GET` | `/api/config/values` | View current VALUES.json |

### Sending a Message

```bash
curl -X POST http://localhost:8000/api/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Search for Acme Holdings in all collections",
    "investigation_id": "inv-001",
    "user_id": "journalist-1"
  }'
```

The orchestrator classifies the message, routes it to the appropriate skill chip, and returns a structured response.

### Using the Python Client Directly

For scripting and notebooks, you can bypass the API and use skill chips directly:

```python
from emet.skills import get_chip
from emet.skills.base import SkillContext, SkillRequest

chip = get_chip("entity_search")
ctx = SkillContext(investigation_id="inv-001", user_id="me")
response = await chip.handle(
    SkillRequest(intent="search", parameters={"query": "Acme Holdings"}),
    ctx,
)
```

---

## 12. Docker Deployment

### Full Stack

```bash
docker-compose up -d
```

This starts:
- **emet** — The API server (port 8000)
- **PostgreSQL** (pgvector) — Database for investigation state, memory, entities
- **Redis** — Task queue for async operations

### Environment Variables for Docker

Set these in `.env` before running:

```bash
ALEPH_HOST=http://your-aleph-host:8080
ALEPH_API_KEY=your-key
ANTHROPIC_API_KEY=your-key    # Optional
DATABASE_URL=postgresql+asyncpg://ftm:ftm@db:5432/emet
REDIS_URL=redis://redis:6379/0
```

### Running Database Migrations

```bash
# Inside the container
docker-compose exec engine alembic upgrade head

# Or locally
alembic upgrade head
```

---

## 13. Troubleshooting

### "Connection refused" to Aleph

- Verify `ALEPH_HOST` is correct and the Aleph instance is running
- If using Docker, make sure both containers are on the same network
- Try `curl $ALEPH_HOST/api/2/collections` from the command line

### "401 Unauthorized" from Aleph

- Check that `ALEPH_API_KEY` is set correctly
- Verify the key hasn't expired
- Test with: `curl -H "Authorization: ApiKey YOUR_KEY" $ALEPH_HOST/api/2/collections`

### Skill chip import errors

- Make sure `followthemoney` is installed: `pip install followthemoney>=4.4`
- For NLP features: `pip install spacy && python -m spacy download en_core_web_sm`

### "No collection ID" errors

- Most chips need a collection context. Pass `collection_ids=["your-id"]` in the `SkillContext`
- Find your collection IDs: search Aleph's UI or use `AlephClient().list_collections()`

### Consensus gates blocking operations

- This is intentional — certain actions require human approval
- Check `response.requires_consensus` and `response.consensus_action` to see what's needed
- Editorial review is a feature, not a bug

### Rate limiting from external APIs

- OpenSanctions: 100 requests/minute (free tier)
- OpenCorporates: 200 requests/month (free tier) — apply for journalist access
- GLEIF: No rate limit
- ICIJ: Be polite — add delays between requests

### Database migration errors

```bash
# Reset and recreate
alembic downgrade base
alembic upgrade head
```

---

## Quick Reference Card

```
# Search Aleph
chip = get_chip("entity_search")
await chip.handle(SkillRequest(intent="search", parameters={"query": "..."}), ctx)

# Screen sanctions
chip = get_chip("cross_reference")
await chip.handle(SkillRequest(intent="screen_sanctions", parameters={"query": "..."}), ctx)

# Upload document
chip = get_chip("document_analysis")
await chip.handle(SkillRequest(intent="upload", parameters={"file_path": "...", "collection_id": "..."}), ctx)

# Extract entities from text
chip = get_chip("nlp_extraction")
await chip.handle(SkillRequest(intent="extract", parameters={"text": "..."}), ctx)

# Build network graph
chip = get_chip("network_analysis")
await chip.handle(SkillRequest(intent="build_graph", parameters={"collection_id": "..."}), ctx)

# Trace ownership
chip = get_chip("financial_investigation")
await chip.handle(SkillRequest(intent="trace_ownership", parameters={"entity_name": "..."}), ctx)

# Verify a claim
chip = get_chip("verification")
await chip.handle(SkillRequest(intent="fact_check", parameters={"claim": "...", "evidence": [...]}), ctx)
```
