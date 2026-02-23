# Emet

**AI-Powered Investigative Intelligence**

An autonomous investigation agent that traces corporate ownership, screens sanctions lists, analyzes blockchain flows, and synthesizes findings into auditable, publication-safe reports. Built on the [FollowTheMoney](https://followthemoney.tech/) data ecosystem and the [Kintsugi](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) self-repairing harness.

The name "Emet" (אמת) is Hebrew for "truth." In Jewish folklore, it is the word inscribed on the forehead of the Golem — a guardian animated to protect its community. The first letter, Aleph (א), is also the name of [OCCRP's investigative data platform](https://github.com/alephdata/aleph) — the foundation Emet is designed to work with.

## What It Does

Give Emet a goal in plain language, and it runs a multi-step investigation autonomously:

```bash
emet investigate "Trace beneficial ownership of Meridian Holdings through offshore jurisdictions"
```

An LLM reasons about what to do next. The agent searches entity databases, screens sanctions and PEP lists, traces corporate ownership chains, monitors global news, investigates blockchain transactions, and synthesizes everything into a structured report — with PII scrubbed at publication boundaries and a full audit trail.

**Core investigation tools:**

| Tool | What It Does |
|------|-------------|
| `search_entities` | Cross-source entity search (Aleph, OpenSanctions, OpenCorporates, ICIJ, GLEIF, UK Companies House, SEC EDGAR) |
| `screen_sanctions` | OFAC, EU, UN consolidated sanctions and PEP screening with fuzzy matching |
| `trace_ownership` | Multi-hop beneficial ownership through offshore corporate structures |
| `osint_recon` | Domain, email, IP, and social footprint reconnaissance |
| `investigate_blockchain` | Ethereum, Bitcoin, and Tron transaction flow analysis and wallet clustering |
| `monitor_entity` | GDELT-powered real-time entity monitoring across global news |
| `analyze_graph` | Community detection, broker identification, circular ownership, shell scoring |
| `generate_report` | LLM-synthesized or template-based investigation reports |

**Additional platform capabilities:**
- Federated search across 7 sources with parallel async fan-out, deduplication, rate limiting, and caching
- Graph analytics engine (NetworkX): 7 investigative algorithms with multi-format export (Gephi, D3, Cytoscape)
- Document ingestion from Datashare (ICIJ) and DocumentCloud (MuckRock/IRE)
- Temporal pattern detection: burst analysis, coincidence detection across entity timelines
- PDF report generation with navy/gold branding (configurable) and PII scrubbing at publication boundary
- FtM bundle export (JSONL/zip) for round-trip Aleph re-import
- Change detection and monitoring: snapshot diffing, sanctions alerts, property change tracking
- Predefined investigation workflows (corporate ownership, sanctions sweep, financial investigation)

## Quick Start

```bash
# Install
git clone https://github.com/Liberation-Labs-THCoalition/Project-Emet.git
cd Project-Emet
pip install -e ".[dev]"
cp .env.example .env

# Run an investigation (stub mode — no API keys needed)
emet investigate "Trace ownership of Acme Holdings" --llm stub

# With an LLM for autonomous decision-making
export ANTHROPIC_API_KEY=sk-ant-...
emet investigate "Trace ownership of Acme Holdings" --llm anthropic

# Interactive mode — approve each tool call
emet --llm anthropic investigate "Acme Holdings" --interactive

# Dry run — show the investigation plan without executing
emet --llm anthropic investigate "Acme Holdings" --dry-run

# Start the HTTP API
emet serve --http --port 8000

# Start the MCP server (for Claude Desktop, etc.)
emet serve --transport stdio
```

## Interfaces

Emet is accessible through five interfaces, all backed by the same agent loop:

| Interface | Command / URL | Use Case |
|-----------|--------------|----------|
| **CLI** | `emet investigate "..."` | Direct investigations, scripting |
| **HTTP API** | `emet serve --http` | Web integration, dashboards |
| **WebSocket** | `ws://host/ws/investigations/{id}` | Real-time streaming updates |
| **MCP** | `emet serve --transport stdio` | Claude Desktop, MCP-compatible clients |
| **Slack / Discord** | Bot adapters | Team-based investigations in chat |

### HTTP API

```bash
# Start server
emet serve --http --port 8000

# Create investigation
curl -X POST localhost:8000/api/investigations \
  -H 'Content-Type: application/json' \
  -d '{"goal": "XYZ Holdings ownership", "llm_provider": "anthropic"}'

# Check status
curl localhost:8000/api/investigations/{id}

# Export report
curl -X POST localhost:8000/api/investigations/{id}/export \
  -H 'Content-Type: application/json' \
  -d '{"format": "json"}'
```

API docs available at `http://localhost:8000/docs` when the server is running.

### WebSocket Streaming

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/investigations/{id}");
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.type: "tool_start", "tool_result", "finding", "report", "complete", "error"
  console.log(`[${msg.type}] ${msg.data}`);
};
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                           EMET                               │
│                                                               │
│  Interfaces:  CLI  │  HTTP API  │  WebSocket  │  MCP  │  Chat │
│       ↓            ↓             ↓              ↓         ↓    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Investigation Bridge (unified adapter → agent loop)   │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                     │
│  ┌───────────────────────▼────────────────────────────────┐   │
│  │               Agent Loop (InvestigationAgent)           │   │
│  │  LLM decision → tool execution → result processing     │   │
│  │  Heuristic fallback when LLM unavailable                │   │
│  │  Turn budget, lead tracking, cost tracking              │   │
│  └───┬──────────────┬──────────────────┬──────────────────┘   │
│      │              │                  │                       │
│  ┌───▼──────┐  ┌────▼──────────┐  ┌───▼───────────────────┐  │
│  │  Safety   │  │  Session      │  │  Tool Executor        │  │
│  │  Harness  │  │  State        │  │  (MCP Tools)          │  │
│  │           │  │               │  │                       │  │
│  │ Pre-check │  │ Entities      │  │ search_entities       │  │
│  │ Circuit   │  │ Findings      │  │ screen_sanctions      │  │
│  │  breaker  │  │ Leads         │  │ trace_ownership       │  │
│  │ PII scrub │  │ Reasoning     │  │ osint_recon           │  │
│  │ Audit log │  │ Tool history  │  │ investigate_blockchain│  │
│  │ Cost cap  │  │ Graph state   │  │ monitor_entity        │  │
│  └───────────┘  └───────────────┘  │ analyze_graph         │  │
│                                     │ generate_report       │  │
│  ┌──────────────────────────────┐  └───────────────────────┘  │
│  │  LLM Abstraction Layer       │                              │
│  │  Anthropic → Ollama → Stub   │                              │
│  │  Tiered routing, cost track  │                              │
│  └──────────────────────────────┘                              │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Kintsugi Infrastructure (from Project-Kintsugi)         │ │
│  │  Governance │ Security │ Memory │ BDI │ Plugins │ Multi-T │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Data Layer                                               │ │
│  │  FtM Spine │ Aleph │ Federation │ Blockchain │ Graph     │ │
│  │  Export │ Monitoring │ Document Sources │ Workflows       │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full technical documentation.

## Safety & Ethics

Emet separates investigation from publication with an explicit, auditable boundary:

- **Investigate mode** (audit-only): All data flows freely between tools so the AI can reason over complete information. Every operation is logged.
- **Publish mode** (enforcing): PII is scrubbed, sensitive data is redacted, and every output is sanitized before leaving the system.

**Defense in depth:**
- Pre-execution safety checks validate every tool call
- Circuit breakers halt runaway loops
- Per-session cost tracking enforces hard budget caps
- PII detection and scrubbing at every exit point (CLI, API, adapters)
- Full audit trail with reasoning trace, tool history, and cost records
- Cascading LLM fallback — degrades from cloud AI to local models to heuristics, never crashes

**Journalism ethics governance** via [VALUES.json](VALUES.json):

1. **Accuracy** (0.25) — Every claim traceable to source material
2. **Source Protection** (0.25) — Source identity never exposed without consent
3. **Public Interest** (0.20) — Investigation scope proportionate to significance
4. **Proportionality** (0.15) — Least intrusive method preferred
5. **Transparency** (0.15) — Methodology documented and auditable

AI-generated findings are always flagged and require human verification. The system never fabricates evidence, impersonates sources, or publishes without human review.

## Configuration

```bash
# ─── LLM (required for autonomous mode) ──────────
LLM_PROVIDER=stub                  # stub | ollama | anthropic
ANTHROPIC_API_KEY=sk-ant-...       # For Anthropic Claude
OLLAMA_HOST=http://localhost:11434 # For local Ollama
LLM_FALLBACK_ENABLED=true          # Cascade: Ollama → Anthropic → Stub

# ─── Aleph (for live data) ───────────────────────
ALEPH_HOST=http://localhost:8080
ALEPH_API_KEY=your-api-key

# ─── External data sources (optional) ────────────
OPENSANCTIONS_API_KEY=your-key     # Sanctions & PEP screening
OPENCORPORATES_TOKEN=your-token    # Corporate registry lookups
ETHERSCAN_API_KEY=your-key         # Ethereum blockchain (free tier)
# Tron/Tronscan: no key needed     # Tron blockchain (USDT-TRC20 tracking)

# ─── Infrastructure ──────────────────────────────
DATABASE_URL=postgresql://ftm:ftm@localhost:5432/emet
REDIS_URL=redis://localhost:6379/0
```

No external services required for development — all tools return structured mock data when API keys are absent, and the test suite runs entirely on stubs.

## Testing

```bash
# Full suite (2,328 tests, ~10 seconds)
python -m pytest tests/ -q

# Key test modules
python -m pytest tests/test_agent_loop.py           # Agent loop + session
python -m pytest tests/test_agent_llm_wiring.py     # LLM decision + synthesis
python -m pytest tests/test_safety_harness.py        # Safety checks + PII
python -m pytest tests/test_mcp_tools.py             # MCP tool execution
python -m pytest tests/test_http_api.py              # HTTP API routes
python -m pytest tests/test_adapters.py              # Slack/Discord/WebSocket
python -m pytest tests/test_e2e_investigation.py     # End-to-end pipeline
python -m pytest tests/test_graph.py                 # Graph analytics
python -m pytest tests/test_federation.py            # Federated search
python -m pytest tests/test_export.py                # Export pipeline
python -m pytest tests/test_workflows.py             # Predefined workflows
```

No external services required — all tests use stubs, mocks, and synthetic datasets.

## Project Structure

```
Project-Emet/
├── emet/
│   ├── agent/                  # Autonomous investigation engine
│   │   ├── loop.py             # InvestigationAgent: LLM decisions, tool execution
│   │   ├── session.py          # Investigation state: entities, findings, leads
│   │   ├── safety_harness.py   # Two-mode safety: audit-only vs enforcing
│   │   └── persistence.py      # Session save/load for resume
│   ├── mcp/                    # Model Context Protocol server
│   │   ├── server.py           # MCP server (stdio/SSE)
│   │   ├── tools.py            # 12 MCP tools + EmetToolExecutor
│   │   └── resources.py        # MCP resource providers
│   ├── api/                    # HTTP API
│   │   ├── app.py              # FastAPI factory
│   │   ├── websocket.py        # WebSocket streaming
│   │   └── routes/             # REST endpoints (investigations, agent, config, health)
│   ├── adapters/               # Chat platform integrations
│   │   ├── investigation_bridge.py  # Unified adapter → agent loop bridge
│   │   ├── slack/              # Slack bot (OAuth, events, interactions)
│   │   ├── discord/            # Discord bot (cogs, embeds, permissions)
│   │   └── webchat/            # Embeddable web widget
│   ├── cognition/              # LLM abstraction + routing
│   │   ├── llm_base.py         # LLMClient ABC, LLMResponse dataclass
│   │   ├── llm_anthropic.py    # Anthropic Claude client
│   │   ├── llm_ollama.py       # Local Ollama client
│   │   ├── llm_stub.py         # Canned-response client (testing)
│   │   ├── llm_factory.py      # Provider factory + cascading fallback
│   │   ├── efe.py              # EFE active inference calculator
│   │   ├── orchestrator.py     # Domain routing
│   │   └── model_router.py     # Tier-to-model mapping
│   ├── ftm/                    # FollowTheMoney integration
│   │   ├── data_spine.py       # FtM entity factory + domain classification
│   │   ├── aleph_client.py     # Async Aleph REST API client
│   │   └── external/           # Federated data sources
│   │       ├── adapters.py     # Yente, OpenCorporates, ICIJ, GLEIF
│   │       ├── companies_house.py # UK Companies House API
│   │       ├── converters.py   # Source → FtM entity converters
│   │       ├── edgar.py        # SEC EDGAR (US filings, beneficial ownership)
│   │       ├── federation.py   # Parallel async fan-out search (7 sources)
│   │       ├── rate_limit.py   # Token bucket, monthly counter, cache
│   │       ├── blockchain.py   # Etherscan (ETH) + Blockstream (BTC) + Tronscan (TRX)
│   │       └── document_sources.py  # Datashare + DocumentCloud
│   ├── graph/                  # Network analysis engine
│   │   ├── algorithms.py       # 7 investigative algorithms
│   │   ├── ftm_loader.py       # FtM → NetworkX graph conversion
│   │   ├── exporters.py        # GEXF, GraphML, CSV, D3, Cytoscape
│   │   └── engine.py           # GraphEngine orchestrator
│   ├── export/                 # Investigation output
│   │   ├── markdown.py         # Markdown report generator
│   │   ├── ftm_bundle.py       # FtM JSONL/zip for Aleph re-import
│   │   └── timeline.py         # Temporal events + pattern detection
│   ├── monitoring/             # Change detection + alerts
│   ├── workflows/              # Predefined investigation workflows
│   │   ├── schema.py           # Workflow definition schema
│   │   ├── registry.py         # Workflow discovery + registration
│   │   └── engine.py           # Workflow execution engine
│   ├── skills/                 # Investigation skill chips (15 agents)
│   │   ├── llm_integration.py  # SkillLLMHelper + methodology prompts
│   │   ├── investigation/      # Core investigation agents (6)
│   │   ├── specialized/        # Domain-specific agents (5)
│   │   ├── publication/        # Verification + story development (2)
│   │   └── resources/          # Training and reference (1)
│   ├── governance/             # Consensus gates, OTel, Bloom
│   ├── security/               # Intent Capsules, Shield, Monitor
│   ├── memory/                 # CMA pipeline
│   ├── bdi/                    # Beliefs-Desires-Intentions
│   ├── kintsugi_engine/        # Self-repairing core
│   ├── plugins/                # Plugin SDK
│   ├── multitenancy/           # Per-investigation isolation
│   ├── config/                 # Settings
│   └── cli.py                  # CLI entry point
├── tests/                      # 2,328 tests
├── docs/                       # USER_GUIDE, COMPETITIVE_ROADMAP, PILOT_PLAN
├── VALUES.json                 # Journalism ethics constitution
├── ARCHITECTURE.md             # Technical architecture
└── pyproject.toml              # Package config
```

## Provenance

Emet's core infrastructure is derived from [**Project-Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi), a domain-agnostic self-repairing agentic harness. The governance, security, memory, BDI, and plugin layers transfer directly — they are intentionally domain-agnostic. The investigative layers (agent loop, MCP tools, safety harness, data sources, FtM spine) are new.

Built on:
- [**Project-Kintsugi**](https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi) — Self-repairing agentic harness
- [**FollowTheMoney**](https://followthemoney.tech/) — OCCRP's data model for organized crime investigations
- [**Aleph**](https://github.com/alephdata/aleph) — OCCRP's investigative data platform
- [**OpenSanctions / yente**](https://www.opensanctions.org/) — 325+ sanctions and PEP lists
- [**OpenCorporates**](https://opencorporates.com/) — 200M+ companies from 145+ jurisdictions
- [**ICIJ Offshore Leaks**](https://offshoreleaks.icij.org/) — 810K+ offshore entities
- [**GLEIF**](https://www.gleif.org/) — Global Legal Entity Identifier index
- [**UK Companies House**](https://developer.company-information.service.gov.uk/) — 600M+ records, officer/PSC data
- [**SEC EDGAR**](https://www.sec.gov/edgar/) — US securities filings, beneficial ownership disclosures
- [**GDELT**](https://www.gdeltproject.org/) — Real-time global news monitoring (250M+ articles)
- [**Tronscan**](https://tronscan.org/) — Tron blockchain explorer (USDT-TRC20 transfer tracking)

## License

**Emet Source-Available License v1.0** — See [LICENSE](LICENSE) for full terms.

Emet is **source-available, not open source**. The code is public for transparency, security auditing, and trust — but usage rights depend on who you are and what you're doing:

- **Investigative journalists, newsrooms, press freedom orgs, anti-corruption NGOs, and academic journalism programs** → Free. No cost, no catch. This is who Emet was built for.
- **Everyone else** (compliance, KYC/AML, due diligence, corporate intelligence, litigation support) → Commercial license required. Contact humboldtnomad@gmail.com.
- **Nobody, under any license** → may use Emet for surveillance of journalists, press suppression, targeting whistleblowers, mass surveillance, or circumventing press freedom protections. These restrictions are non-negotiable.

For commercial licensing inquiries: **humboldtnomad@gmail.com**
