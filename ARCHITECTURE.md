# Emet — Architecture

## Overview

Emet is an autonomous investigative intelligence agent built on the [**Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness architecture, adapted for the **FollowTheMoney (FtM) data ecosystem** and OCCRP's Aleph investigative platform.

The system takes a natural-language investigation goal, reasons autonomously about which tools to call, executes them through a safety harness, and synthesizes findings into auditable, publication-safe reports.

```
┌─────────────────────────────────────────────────────────────────────┐
│                              EMET                                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Interfaces                                                      │ │
│  │  CLI  │  HTTP API (FastAPI)  │  WebSocket  │  MCP               │ │
│  └──────────────────────┬──────────────────────────────────────────┘ │
│                         │                                             │
│  ┌──────────────────────▼──────────────────────────────────────────┐ │
│  │  Investigation Bridge (adapter → agent loop)                     │ │
│  └──────────────────────┬──────────────────────────────────────────┘ │
│                         │                                             │
│  ┌──────────────────────▼──────────────────────────────────────────┐ │
│  │  Agent Loop (InvestigationAgent)                                  │ │
│  │                                                                   │ │
│  │  ┌─────────────┐  ┌────────────────┐  ┌──────────────────────┐  │ │
│  │  │ LLM Decision │  │ Tool Executor  │  │ Session State        │  │ │
│  │  │              │  │ (MCP Tools)    │  │                      │  │ │
│  │  │ System       │  │                │  │ Entities (FtM)       │  │ │
│  │  │  prompt +    │  │ search_entities│  │ Findings + conf.     │  │ │
│  │  │  context →   │  │ screen_sanction│  │ Leads + priority     │  │ │
│  │  │  JSON action │  │ trace_ownership│  │ Tool history         │  │ │
│  │  │              │  │ osint_recon    │  │ Reasoning trace      │  │ │
│  │  │ Heuristic    │  │ invest_blockch.│  │ Graph state          │  │ │
│  │  │  fallback    │  │ monitor_entity │  │ Cost tracker         │  │ │
│  │  │  when LLM    │  │ analyze_graph  │  │                      │  │ │
│  │  │  unavailable │  │ generate_report│  │ Persistence (save/   │  │ │
│  │  │              │  │ conclude       │  │  load/resume)        │  │ │
│  │  └──────────────┘  └────────────────┘  └──────────────────────┘  │ │
│  └──────────────────────┬──────────────────────────────────────────┘ │
│                         │                                             │
│  ┌──────────────────────▼──────────────────────────────────────────┐ │
│  │  Safety Harness (two-mode)                                       │ │
│  │  Investigate: audit-only (log all, block nothing)                │ │
│  │  Publish:     enforcing (PII scrub, redact, sanitize)           │ │
│  │                                                                   │ │
│  │  Pre-execution checks │ Circuit breaker │ Cost caps │ Audit log  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  LLM Abstraction Layer                                           │ │
│  │  Anthropic Claude → Ollama (local) → Stub (test)                │ │
│  │  Tiered routing: fast / balanced / powerful                      │ │
│  │  Per-session cost tracking + budget caps                         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Kintsugi Infrastructure (transferred from Project-Kintsugi)    │ │
│  │  Governance (VALUES.json, Consensus Gates, OTel, Bloom)         │ │
│  │  Security (Intent Capsules, Shield, Monitor, Sandbox)           │ │
│  │  Memory (CMA 3-stage pipeline, investigation context)           │ │
│  │  BDI (Beliefs=evidence, Desires=hypotheses, Intentions=leads)   │ │
│  │  Plugins (SDK, loader, registry) │ Multitenancy (per-session)   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Data Layer                                                       │ │
│  │  FtM Data Spine │ Aleph Client │ Federated Search               │ │
│  │  Blockchain (ETH/BTC) │ Document Sources │ Graph Analytics      │ │
│  │  Export (Markdown, FtM bundle, Timeline) │ Monitoring │ Workflow │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Agent Loop

The central nervous system. `InvestigationAgent` (783 lines) runs a turn-based loop:

```
Goal → Initial Search → [LLM Decide → Execute → Process Result] × N → Report → Export
```

### Decision Chain

Each turn, the agent decides what to do next:

1. **LLM decision** (`_llm_decide`): Sends accumulated context (findings, entities, open leads, tool history) plus a system prompt to the LLM. The LLM responds with a single JSON action (`{"tool": "...", "args": {...}, "reasoning": "..."}`). Temperature 0.2 for structured output, balanced tier, max 300 tokens.

2. **Heuristic fallback** (`_heuristic_decide`): If the LLM is unavailable, returns non-JSON, or suggests an unknown tool, the agent falls back to a deterministic strategy: follow the highest-priority open lead, mapping lead types to appropriate tools.

3. **Conclude**: When the LLM judges the investigation complete, or no open leads remain, the agent generates a report and exits.

### System Prompt

The LLM receives an investigation-specific system prompt encoding:
- Principles: follow the money, verify through multiple sources, pursue highest-value leads, know when to stop, never fabricate
- Strategy ordering: entity search → sanctions → ownership → OSINT → blockchain → conclude
- Output constraint: respond with ONLY a single JSON action object

### Report Synthesis

The agent attempts LLM-synthesized reports first (`_llm_synthesize_report`), falling back to template-based generation. LLM reports include: executive summary, key findings with confidence levels, entity network map, open questions, and methodology notes. All reports pass through PII scrubbing at the publication boundary.

### Agent Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `max_turns` | 15 | Turn budget per investigation |
| `min_confidence` | 0.3 | Minimum confidence to pursue a lead |
| `auto_sanctions_screen` | true | Always screen discovered entities |
| `auto_news_check` | true | Always monitor GDELT for targets |
| `llm_provider` | stub | LLM backend (stub, ollama, anthropic) |
| `enable_safety` | true | Enable safety harness |
| `generate_graph` | true | Build network graph from findings |
| `persist_path` | "" | Auto-save session to path |

---

## Safety Harness

Two-mode design separating investigation from publication:

### Investigate Mode (audit-only)
During the investigation, the harness **logs** everything but **blocks** nothing (except true safety violations). The AI needs to see complete data — names, addresses, financial records — to make connections. Premature redaction would cripple the investigation.

### Publish Mode (enforcing)
At publication boundaries — when findings leave the system via CLI export, API response, adapter message, or report generation — the harness activates:
- PII detection and scrubbing (names, addresses, phone numbers, SSNs, financial identifiers)
- Sensitive data redaction
- Output sanitization
- Publication audit logging

### Safety Infrastructure

| Component | Source | Function |
|-----------|--------|----------|
| Pre-execution checks | Safety harness | Validate tool + args before execution |
| Circuit breaker | Safety harness | Halt after N consecutive failures or budget exceeded |
| Cost tracking | LLM factory | Per-session token/cost accumulation with hard caps |
| PII scrubbing | Safety harness | Regex + heuristic detection at publication boundaries |
| Audit trail | Safety harness | Every check, observation, block recorded |
| Kintsugi Shield | Security layer | Intent Capsule validation |
| Kintsugi Monitor | Security layer | Post-execution anomaly detection |
| Consensus Gates | Governance | Human approval for publication actions |

---

## Interfaces

### CLI (`emet/cli.py`)

Five commands: `investigate`, `search`, `workflow`, `serve`, `status`.

Investigation modes: standard (autonomous), interactive (approve each tool call), dry-run (plan without executing), resume (reload saved session).

### HTTP API (`emet/api/`)

FastAPI application factory (`create_app()`) with:
- `POST /api/investigations` — Create and run investigation (async, returns 202)
- `GET /api/investigations/{id}` — Poll investigation status
- `GET /api/investigations` — List all investigations
- `POST /api/investigations/{id}/export` — Export report (JSON/Markdown)
- `POST /api/agent/message` — Send message to agent
- `GET /api/agent/temporal` — Temporal event queries
- `GET /api/config/values` — Read VALUES.json
- `PUT /api/config/values` — Update ethics constitution
- `GET /api/health` — Health check

### WebSocket (`emet/api/websocket.py`)

`WS /ws/investigations/{id}` — Real-time streaming of investigation events:
- `tool_start`: Tool about to execute
- `tool_result`: Tool completed with results
- `finding`: New finding discovered
- `report`: Report generated
- `complete`: Investigation finished
- `error`: Error occurred

### MCP Server (`emet/mcp/`)

Model Context Protocol server for Claude Desktop and other MCP-compatible clients. Exposes all 9 investigation tools plus 3 resource providers. Transport: stdio or SSE.

### Adapter Bridge (planned: `_future/adapters/`)

Slack, Discord, and webchat adapters are planned but not yet wired into the active codebase. The bridge architecture is designed — platform-specific messages translate into investigation goals, results stream back as formatted messages. Code exists in `_future/adapters/` pending integration.

---

## LLM Abstraction Layer

Provider-agnostic LLM interface with cascading fallback:

| Module | Provider | Usage |
|--------|----------|-------|
| `llm_anthropic.py` | Anthropic Claude | Cloud, most capable |
| `llm_ollama.py` | Local Ollama | Local, no API key needed |
| `llm_stub.py` | Canned responses | Testing, offline |
| `llm_factory.py` | Factory + `FallbackLLMClient` | Cascade on failure |

### Client Interface (`LLMClient` ABC)

- `complete(prompt, system, max_tokens, temperature, tier)` → `LLMResponse`
- `classify_intent(text)` → `LLMResponse`
- `generate_content(prompt, context)` → `LLMResponse`
- `extract_entities(text)` → `LLMResponse`

### Tiered Model Routing

| Tier | Ollama | Anthropic | Use Case |
|------|--------|-----------|----------|
| fast | llama3.2:3b | haiku | Quick classification |
| balanced | mistral:7b | sonnet | Investigation decisions |
| powerful | llama3.1:70b | opus | Complex synthesis |

### Agent Loop Integration

The agent loop creates a single LLM client at first use (lazy initialization), caches it for the session lifetime, and tracks costs via `CostTracker`. The factory accepts an explicit `provider` parameter that overrides the global setting, allowing per-investigation provider selection.

---

## MCP Tools

9 investigation tools exposed via MCP protocol and used by the agent loop:

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `search_entities` | Cross-source entity search | query, entity_type, sources, limit |
| `screen_sanctions` | Sanctions/PEP screening | entity_name, entity_type, threshold |
| `trace_ownership` | Corporate ownership chains | entity_name, max_depth |
| `osint_recon` | OSINT reconnaissance | target, scan_type |
| `investigate_blockchain` | Blockchain analysis | address, chain (ethereum/bitcoin/tron) |
| `monitor_entity` | GDELT news monitoring | entity_name, timespan |
| `analyze_graph` | Network analysis | entities, analysis_type |
| `generate_report` | Report generation | title, format |
| `conclude` | End investigation | (none) |

`EmetToolExecutor` routes tool calls to the appropriate subsystem (federation, graph engine, export pipeline, etc.). Two interfaces:
- `execute()`: MCP protocol wrapper (returns `{isError, content, _raw}`) — used by MCP server
- `execute_raw()`: Direct result dict — used by agent loop, CLI, and workflow engine

---

## Data Layer

### FtM Data Spine (`ftm/`)

Central integration layer using the [FollowTheMoney](https://followthemoney.tech/) data model:
- `data_spine.py`: FtM entity factory with validated creation (Person, Company, Ownership, Directorship, Payment)
- `aleph_client.py`: Async Aleph REST API client (search, CRUD, cross-reference, ingest, streaming)

### Federated Search (`ftm/external/federation.py`)

Parallel async fan-out across 7 data sources:
- OpenSanctions / yente (sanctions, PEP)
- OpenCorporates (corporate registries)
- ICIJ Offshore Leaks (offshore entities)
- GLEIF (Legal Entity Identifiers)
- UK Companies House (600M+ records, officers, PSC/beneficial ownership)
- SEC EDGAR (US filings, 13D/13G beneficial ownership, insider trading)

With deduplication, per-source rate limiting (token bucket + monthly counter), response caching, and graceful degradation on partial source failure.

### Blockchain (`ftm/external/blockchain.py`)

Three-chain support via `BlockchainAdapter`:
- `EtherscanClient`: ETH address validation, balance, transactions, counterparty analysis, FtM conversion
- `BlockstreamClient`: BTC address validation, balance, transactions
- `TronscanClient`: TRX balance, transactions, TRC-20 token transfers (USDT tracking for sanctions evasion)
- `detect_chain()`: Auto-detect ETH (0x...), BTC (bc1.../1.../3...), or Tron (T...) addresses

### Graph Analytics (`graph/`)

NetworkX-based investigative analysis:
- `ftm_loader.py`: FtM entities → NetworkX MultiDiGraph (11 relationship schemas, weighted edges, 50K node cap)
- `algorithms.py`: 7 algorithms — find_brokers, find_communities, find_circular_ownership, find_key_players, find_hidden_connections, find_structural_anomalies, shell_company_topology_score
- `exporters.py`: GEXF (Gephi), GraphML, Cytoscape JSON, D3 JSON, CSV
- `engine.py`: Orchestrator (build from entities/Aleph/federation → analysis → export)

### Export (`export/`)

- `markdown.py`: Structured report with executive summary, entity inventory, network findings
- `pdf.py`: Branded PDF reports (navy/gold default, configurable colors/logo). Reportlab-based.
- `ftm_bundle.py`: JSONL/zip for Aleph re-import (round-trip investigation → export → Aleph)
- `timeline.py`: Temporal event extraction, burst detection, coincidence detection

### Monitoring (`monitoring/`)

Change detection for ongoing investigations:
- `ChangeDetector`: Register queries, scheduled checks against federated search, snapshot management
- `SnapshotDiffer`: Compare entity snapshots for new entities, property changes, new sanctions, removals
- `ChangeAlert`: Structured alerts with type, severity, provenance

### Workflows (`workflows/`)

Predefined multi-step investigation templates:
- `schema.py`: Workflow definition (steps, conditions, parameters)
- `registry.py`: Discovery and registration of built-in and custom workflows
- `engine.py`: Execution engine with step sequencing and result collection

### Document Sources (`ftm/external/document_sources.py`)

Adapters for established document processing tools:
- `DatashareClient`: ICIJ Datashare (search, NER, FtM conversion)
- `DocumentCloudClient`: MuckRock/IRE DocumentCloud (search, text extraction, FtM conversion)

---

## Kintsugi Infrastructure

These modules transfer verbatim from [Project-Kintsugi](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) — they are intentionally domain-agnostic:

| Module | Function |
|--------|----------|
| `kintsugi_engine/` | Shadow verification, self-repair, resilience |
| `governance/` | VALUES.json, Consensus Gates, OTel audit, Bloom accountability |
| `security/` | Intent Capsules, Security Shield, Behavior Monitor, Sandbox |
| `memory/` | CMA 3-stage pipeline (working, episodic, semantic) |
| `bdi/` | Beliefs-Desires-Intentions (evidence, hypotheses, leads) |
| `plugins/` | Plugin SDK, loader, registry |
| `multitenancy/` | Per-investigation isolation |

### Ethics Governance (adapted)

VALUES.json implements the Five Pillars of Journalism:
1. Accuracy (0.25) — Every claim traceable to source material
2. Source Protection (0.25) — Source identity never exposed without consent
3. Public Interest (0.20) — Scope proportionate to significance
4. Proportionality (0.15) — Least intrusive method preferred
5. Transparency (0.15) — Methodology documented and auditable

Consensus Gates require human approval for: publishing findings, confirming entity matches, accessing sensitive data, flagging entities.

---

## Skill Chips (Legacy Layer)

15 specialized agents from the original architecture, accessible via `get_chip()` and `SkillRequest`:

| Category | Chips |
|----------|-------|
| Investigation | entity_search, cross_reference, document_analysis, nlp_extraction, network_analysis, data_quality |
| Specialized | financial_investigation, government_accountability, environmental_investigation, labor_investigation, corporate_research |
| Monitoring | monitoring |
| Publication | verification, story_development |
| Resources | resources |

These are now secondary to the agent loop + MCP tools architecture, but remain available for direct Python API access and specialized domain workflows.

---

## Codebase Stats

| Metric | Value |
|--------|-------|
| Source files | 179 Python modules |
| Source lines | ~50,000 |
| Tests | 1,811 unit + 44 live |
| Packages | 23 |
| Commits | 40 |
| MCP tools | 9 |
| API routes | 19 |
| Interfaces | 4 (CLI, HTTP, WebSocket, MCP) |
