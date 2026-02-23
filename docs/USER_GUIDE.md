# Emet — User Guide

A practical guide to setting up and running investigations with Emet.

---

## Table of Contents

1. [What Is Emet?](#1-what-is-emet)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Your First Investigation](#4-your-first-investigation)
5. [CLI Reference](#5-cli-reference)
6. [HTTP API](#6-http-api)
7. [WebSocket Streaming](#7-websocket-streaming)
8. [MCP Server](#8-mcp-server)
9. [Slack & Discord](#9-slack--discord)
10. [LLM Providers](#10-llm-providers)
11. [Investigation Tools](#11-investigation-tools)
12. [Safety & Publication Boundaries](#12-safety--publication-boundaries)
13. [Sessions: Save, Resume, Export](#13-sessions-save-resume-export)
14. [Workflows](#14-workflows)
15. [Graph Analytics](#15-graph-analytics)
16. [Change Monitoring](#16-change-monitoring)
17. [Direct Python API](#17-direct-python-api)
18. [External Data Sources](#18-external-data-sources)
19. [Docker Deployment](#19-docker-deployment)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. What Is Emet?

Emet is an AI-powered investigative intelligence platform. You give it a goal in plain language — "Trace the beneficial ownership of Meridian Holdings through offshore jurisdictions" — and it runs a multi-step investigation autonomously.

An LLM reasons about what to do next based on what it has already found. The system searches entity databases, screens sanctions and PEP lists, traces corporate ownership chains, investigates blockchain transactions, monitors global news, and synthesizes findings into a structured, evidence-backed report.

**What it is:** An autonomous investigative agent with a safety harness, audit trail, and publication boundary.

**What it is not:** An unsupervised publisher. Every investigation has a human in the loop. Every report passes through PII scrubbing before leaving the system. The system never fabricates evidence.

---

## 2. Installation

### Prerequisites

- Python 3.11 or later
- 4 GB RAM minimum (8 GB recommended)
- No external services required for development — everything runs on stubs

### Install

```bash
git clone https://github.com/Liberation-Labs-THCoalition/Project-Emet.git
cd Project-Emet
pip install -e ".[dev]"
cp .env.example .env
```

### Verify

```bash
emet status
```

You should see all modules reporting `✓`.

---

## 3. Configuration

Edit `.env` with the credentials for the services you'll use. Nothing is strictly required — Emet runs in stub mode without any API keys.

```bash
# ─── LLM (for autonomous investigation) ──────────
LLM_PROVIDER=stub                  # stub | ollama | anthropic
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic Claude
OLLAMA_HOST=http://localhost:11434 # Local Ollama
LLM_FALLBACK_ENABLED=true          # Cascade through providers on failure

# ─── Aleph (for live data) ───────────────────────
ALEPH_HOST=http://localhost:8080
ALEPH_API_KEY=your-api-key

# ─── External data sources (optional) ────────────
OPENSANCTIONS_API_KEY=your-key     # Sanctions & PEP screening
OPENCORPORATES_TOKEN=your-token    # Corporate registry lookups
ETHERSCAN_API_KEY=your-key         # Ethereum blockchain (free tier)
COMPANIES_HOUSE_API_KEY=your-key   # UK Companies House (free at developer portal)
# SEC EDGAR: no key needed         # US filings (User-Agent header only)
# Tronscan: no key needed          # Tron blockchain / USDT-TRC20

# ─── Infrastructure (defaults work with Docker) ──
DATABASE_URL=postgresql://ftm:ftm@localhost:5432/emet
REDIS_URL=redis://localhost:6379/0
```

### Getting API Keys

| Service | How to Get a Key | Free Tier |
|---------|-----------------|-----------|
| Anthropic | [console.anthropic.com](https://console.anthropic.com) | Pay-per-token |
| OpenSanctions | [opensanctions.org](https://opensanctions.org) | Yes (rate limited; journalist access available) |
| OpenCorporates | [opencorporates.com](https://opencorporates.com) | Yes (200 req/month; journalist access available) |
| GLEIF | No key needed | Unlimited |
| Etherscan | [etherscan.io](https://etherscan.io) | Yes (5 req/sec) |
| Aleph | Your Aleph instance → Settings → API Key | Depends on instance |

---

## 4. Your First Investigation

### Stub Mode (no API keys needed)

```bash
emet investigate "Trace ownership of Acme Holdings"
```

This runs with the stub LLM and mock data sources. Tools return realistic structured data, the agent follows its heuristic decision chain, and you get a complete investigation report. Good for understanding the workflow.

### With an LLM

```bash
export ANTHROPIC_API_KEY=sk-ant-...
emet --llm anthropic investigate "Trace beneficial ownership of Meridian Holdings through offshore jurisdictions"
```

Now the LLM reasons about each step: which tool to call, what to do with the results, when to stop.

### What Happens

1. **Initial search**: The agent searches for the target entity across data sources.
2. **Sanctions screening**: Discovered entities are automatically screened against global sanctions/PEP lists.
3. **Lead generation**: Search results produce leads — ownership chains to trace, entities to investigate further, addresses to analyze.
4. **Autonomous loop**: Each turn, the LLM examines accumulated evidence and decides the next action. The safety harness validates every tool call.
5. **Report synthesis**: When the investigation is complete, the LLM synthesizes all findings into a narrative report with an executive summary, key findings, entity network, open questions, and methodology notes.
6. **Publication boundary**: PII is scrubbed from the report before it's shown to you.

### Output

```
🔍 Starting investigation: Trace ownership of Acme Holdings
   Max turns: 15 | LLM: anthropic

============================================================
INVESTIGATION COMPLETE — Trace ownership of Acme Holdings
============================================================
  Turns:    8
  Entities: 12
  Findings: 5
  Leads:    2 open / 7 total
  Tools:    search_entities, screen_sanctions, trace_ownership, monitor_entity

FINDINGS:
  [search_entities] Found 3 entities matching "Acme Holdings" across sources
  [screen_sanctions] Acme Holdings Ltd director matches PEP list (score: 0.87)
  [trace_ownership] Ownership chain: Acme Holdings → Sunrise BVI → Apex Nominee Ltd
  ...

REASONING TRACE:
  → Initial search for "Acme Holdings"
  → Sanctions hit on director — escalating ownership tracing
  → Tracing multi-hop ownership through BVI structure
  → ...
```

---

## 5. CLI Reference

### `emet investigate`

Run a full investigation.

```bash
emet investigate "investigation goal" [options]

Options:
  --llm PROVIDER       LLM provider: stub, ollama, anthropic (default: stub)
  --max-turns N        Maximum agent turns (default: 15)
  --no-sanctions       Skip automatic sanctions screening
  --no-news            Skip automatic GDELT news monitoring
  --output FILE        Save report to file (JSON, PII-scrubbed)
  --save PATH          Auto-save session to path (for resume)
  --resume PATH        Resume from a saved session file
  --dry-run            Show investigation plan without executing tools
  --interactive        Pause before each tool call for approval
  -v, --verbose        Verbose output with debug logging
```

### `emet search`

Quick entity search (does not start an investigation).

```bash
emet search "John Smith" --type Person --source opensanctions --limit 10
```

### `emet workflow`

Run a predefined investigation workflow.

```bash
emet workflow corporate_ownership --target "Acme Corp"
emet workflow sanctions_sweep --target "Viktor Petrov"
emet workflow corporate_ownership --target "Acme Corp" --dry-run
```

### `emet serve`

Start a server.

```bash
# HTTP API (FastAPI with auto-generated docs at /docs)
emet serve --http --port 8000

# MCP server (for Claude Desktop)
emet serve --transport stdio
```

### `emet status`

Show system status — loaded modules, skill chips, workflows, LLM configuration.

---

## 6. HTTP API

Start the server:

```bash
emet serve --http --port 8000
```

API documentation is auto-generated at `http://localhost:8000/docs`.

### Create an Investigation

```bash
curl -X POST localhost:8000/api/investigations \
  -H 'Content-Type: application/json' \
  -d '{
    "goal": "Trace ownership of Meridian Holdings",
    "llm_provider": "anthropic",
    "max_turns": 15
  }'
```

Returns `202 Accepted` with an investigation ID. The investigation runs asynchronously.

### Check Status

```bash
curl localhost:8000/api/investigations/{id}
```

Returns current status (running/complete/failed), turn count, findings, entities, and open leads.

### List Investigations

```bash
curl localhost:8000/api/investigations
```

### Export Report

```bash
# JSON export (default)
curl -X POST localhost:8000/api/investigations/{id}/export

# PDF export (branded, navy/gold)
curl -X POST "localhost:8000/api/investigations/{id}/export?format=pdf" \
  --output investigation.pdf
```

Reports are PII-scrubbed at the publication boundary before export. CLI also supports PDF:

```bash
emet investigate "Trace ownership of Acme" --output report.pdf
```

### Other Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/agent/message` | Send message to agent |
| GET | `/api/agent/temporal` | Temporal event queries |
| GET | `/api/config/values` | Read ethics constitution |
| PUT | `/api/config/values` | Update ethics constitution |
| GET | `/api/memory/search` | Search investigation memory |
| POST | `/api/memory/store` | Store to investigation memory |

---

## 7. WebSocket Streaming

Connect to a running investigation for real-time updates:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/investigations/{id}");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch (msg.type) {
    case "tool_start":
      console.log(`Executing: ${msg.data.tool}`);
      break;
    case "tool_result":
      console.log(`Result: ${msg.data.summary}`);
      break;
    case "finding":
      console.log(`Finding: ${msg.data.summary}`);
      break;
    case "report":
      console.log(`Report ready`);
      break;
    case "complete":
      console.log(`Investigation complete`);
      ws.close();
      break;
    case "error":
      console.error(`Error: ${msg.data.message}`);
      break;
  }
};
```

---

## 8. MCP Server

Emet exposes its tools via the [Model Context Protocol](https://modelcontextprotocol.io/), making it usable from Claude Desktop and other MCP-compatible clients.

```bash
emet serve --transport stdio
```

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "emet": {
      "command": "emet",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

Once connected, Claude can call Emet's investigation tools directly during conversations.

---

## 9. Slack & Discord

### Slack

Emet includes a full Slack adapter with OAuth, event handling, and interaction support. The adapter uses the Investigation Bridge to connect Slack messages to the agent loop.

### Discord

Emet includes a Discord adapter with cogs, embeds, and permission management.

Both adapters stream investigation updates back as formatted messages (Slack blocks / Discord embeds) as the investigation progresses.

See `emet/adapters/slack/` and `emet/adapters/discord/` for configuration.

---

## 10. LLM Providers

Emet supports three LLM providers, with cascading fallback:

| Provider | When to Use | Requires |
|----------|------------|----------|
| **anthropic** | Best autonomous decisions, report synthesis | `ANTHROPIC_API_KEY` |
| **ollama** | Local, no data leaves your machine | Ollama running locally |
| **stub** | Testing, development, no API keys | Nothing |

### Selecting a Provider

```bash
# Per-investigation via CLI
emet --llm anthropic investigate "..."

# Per-investigation via HTTP API
curl -X POST localhost:8000/api/investigations \
  -d '{"goal": "...", "llm_provider": "anthropic"}'

# Global default via .env
LLM_PROVIDER=anthropic
```

### Fallback Chain

When `LLM_FALLBACK_ENABLED=true`, if the configured provider fails, Emet tries the next one: Ollama → Anthropic → Stub. The stub provider always returns a non-JSON response, which triggers the heuristic decision fallback — so investigations always complete.

### Cost Tracking

Every LLM call is tracked: tokens in, tokens out, cost. The agent's cost tracker accumulates across the investigation and is included in the session summary and safety audit.

---

## 11. Investigation Tools

These are the tools the agent can call during an investigation:

### `search_entities`
Search for entities across all connected data sources. Returns FtM-formatted entities with provenance.

### `screen_sanctions`
Screen an entity against OFAC, EU, UN consolidated sanctions lists and PEP databases. Returns match scores with fuzzy matching.

### `trace_ownership`
Trace corporate ownership chains through multi-hop offshore structures. Follows beneficial ownership links across jurisdictions.

### `osint_recon`
Open-source intelligence reconnaissance on a target. Scans domains, email addresses, IP addresses, and social footprints.

### `investigate_blockchain`
Analyze Ethereum, Bitcoin, or Tron blockchain activity for an address. Returns transaction history, counterparties, and flow patterns. Tron support includes USDT-TRC20 transfer tracking (the dominant chain for sanctions evasion due to low fees). Auto-detects chain from address format.

### `monitor_entity`
Monitor an entity across global news via GDELT. Returns recent media mentions and sentiment.

### `analyze_graph`
Run network analysis on accumulated entities: community detection, broker identification, circular ownership detection, shell company scoring.

### `generate_report`
Generate an investigation report from accumulated findings. LLM-synthesized when available, template-based as fallback.

---

## 12. Safety & Publication Boundaries

### Two-Mode Safety Harness

During investigation, the harness operates in **audit-only** mode — it logs all activity but allows tools to see complete, unredacted data. This is essential because an analyst needs to see that "John Smith at 123 Main St" appears in both a sanctions filing and a corporate registry to make the connection.

At **publication boundaries** — when data leaves the system via CLI export, API response, adapter message, or report — the harness switches to **enforcing** mode:

- PII is detected and scrubbed (names, addresses, phone numbers, SSNs, financial identifiers)
- Sensitive data is redacted
- All publications are logged in the audit trail

### What Gets Checked

Every tool call passes through pre-execution safety checks:
- Is the tool recognized?
- Are the arguments valid?
- Has the circuit breaker tripped (too many consecutive failures)?
- Is the session within its cost budget?

### Audit Trail

Every investigation maintains a full audit trail: reasoning trace (why each decision was made), tool history (what was called with what args and what came back), safety checks (observations, blocks, PII detections), and cost tracking.

### Interactive Mode

For maximum human control, use interactive mode:

```bash
emet --llm anthropic investigate "..." --interactive
```

You'll approve each tool call before it executes. Options at each step: approve (y), skip (s), quit (q).

---

## 13. Sessions: Save, Resume, Export

### Save an Investigation

```bash
emet --llm anthropic investigate "Acme Holdings" --save ./sessions/acme.json
```

The session file contains: goal, all entities, findings, leads, reasoning trace, tool history, graph state, and safety audit.

### Resume

```bash
emet investigate --resume ./sessions/acme.json
```

Displays the saved investigation state (findings, entities, open leads).

### Export Report

```bash
emet --llm anthropic investigate "Acme Holdings" --output report.json
```

The exported report is PII-scrubbed at the publication boundary. The raw session file (via `--save`) preserves unredacted data for continued investigation.

---

## 14. Workflows

Predefined multi-step investigation templates:

```bash
# List available workflows
emet workflow --help

# Run a workflow
emet workflow corporate_ownership --target "Acme Corp"

# Preview without executing
emet workflow corporate_ownership --target "Acme Corp" --dry-run

# Pass extra parameters
emet workflow sanctions_sweep --target "Viktor Petrov" --params '{"jurisdictions": ["RU", "CY"]}'
```

Workflows define a fixed sequence of tool calls with conditions and parameters. They're useful for standardized compliance checks and repeatable investigation patterns.

---

## 15. Graph Analytics

The agent automatically builds a network graph during investigations. You can also use the graph engine directly:

```python
from emet.graph.engine import GraphEngine

engine = GraphEngine()
result = engine.build_from_entities(entities)

# Who are the intermediaries?
brokers = result.analysis.find_brokers(top_n=5)

# Circular ownership?
cycles = result.analysis.find_circular_ownership(max_length=6)

# Shell company scoring
score = result.analysis.shell_company_topology_score("entity-id")

# Export for visualization
result.exporter.to_gexf("network.gexf")     # Gephi
result.exporter.to_d3_json()                  # D3.js
result.exporter.to_cytoscape_json()           # Cytoscape
result.exporter.to_csv_files("./output/")     # Spreadsheets
```

---

## 16. Change Monitoring

Monitor registered queries for changes over time:

```python
from emet.monitoring import ChangeDetector

detector = ChangeDetector(storage_dir=".emet_monitoring")

# Register queries to watch
detector.register_query("Viktor Petrov", entity_type="Person")
detector.register_query("Sunrise Holdings", entity_type="Company")

# Check for changes (compares to previous snapshot)
alerts = await detector.check_all()

for alert in alerts:
    print(alert.summary)
    # "⚠️ NEW SANCTION: Viktor Petrov listed in opensanctions"
    # "New entity: Sunrise Holdings Ltd (Company) found in opencorporates"
```

Alert types: `new_sanction` (high), `new_entity` (medium), `changed_property` (low), `removed_entity` (low).

---

## 17. Direct Python API

For programmatic access beyond the CLI and HTTP API:

### Run an Investigation

```python
import asyncio
from emet.agent import InvestigationAgent, AgentConfig

config = AgentConfig(
    max_turns=15,
    llm_provider="anthropic",
    auto_sanctions_screen=True,
)

agent = InvestigationAgent(config=config)
session = asyncio.run(agent.investigate("Trace ownership of Acme Holdings"))

# Access results
print(session.summary())
for finding in session.findings:
    print(f"[{finding.source}] {finding.summary} (confidence: {finding.confidence})")
```

### Execute Individual Tools

```python
from emet.mcp.tools import EmetToolExecutor

executor = EmetToolExecutor()
result = await executor.execute("search_entities", {
    "query": "Acme Holdings",
    "entity_type": "Company",
    "limit": 20,
})
```

### Skill Chips (Legacy API)

The original skill chip API is still available for direct access to specialized domains:

```python
from emet.skills import get_chip
from emet.skills.base import SkillContext, SkillRequest

ctx = SkillContext(investigation_id="inv-001", user_id="analyst-1")
chip = get_chip("entity_search")
response = await chip.handle(
    SkillRequest(intent="search", parameters={"query": "Acme Holdings"}),
    ctx,
)
```

---

## 18. External Data Sources

| Source | Data | Free Tier | Key Required |
|--------|------|-----------|-------------|
| **OpenSanctions / yente** | 325+ sanctions & PEP lists | Yes (rate limited) | Yes |
| **OpenCorporates** | 200M+ companies, 145+ jurisdictions | 200 req/month | Yes |
| **ICIJ Offshore Leaks** | 810K+ offshore entities | Unlimited | No |
| **GLEIF** | Global Legal Entity Identifiers | Unlimited | No |
| **UK Companies House** | 600M+ UK company records, officers, PSC | Unlimited | Yes (free) |
| **SEC EDGAR** | US securities filings, beneficial ownership | Unlimited | No |
| **Etherscan** | Ethereum blockchain | 5 req/sec | Yes |
| **Blockstream** | Bitcoin blockchain | Unlimited | No |
| **Tronscan** | Tron blockchain (USDT-TRC20 tracking) | Unlimited | No |
| **GDELT** | Global news monitoring | Unlimited | No |
| **Aleph** | OCCRP investigative data platform | Depends on instance | Yes |
| **Datashare** | ICIJ document processing | Self-hosted | No |
| **DocumentCloud** | MuckRock/IRE public documents | Yes | No |

All sources are optional. When a source is unavailable, the agent skips it gracefully and works with what's available.

---

## 19. Docker Deployment

```bash
# Full stack (Emet + PostgreSQL + Redis)
docker-compose up -d

# With local Aleph
# Set ALEPH_HOST to the Aleph container name in .env
docker-compose up -d

# HTTP API mode
docker-compose exec emet emet serve --http --port 8000
```

---

## 20. Troubleshooting

### "No LLM client available"
The configured LLM provider can't be reached. Check your API key, or run with `--llm stub` for testing.

### Investigation ends after 1 turn
In stub mode, the LLM returns a non-JSON response, so the heuristic fallback runs. If there are no leads to follow after the initial search, the agent concludes immediately. Use `--llm anthropic` for real autonomous decision-making.

### "Circuit breaker tripped"
Too many consecutive tool failures. This is the safety harness protecting against runaway loops. Check your data source connectivity.

### PII appears in output
If PII appears in a CLI report or API response, file a bug. The publication boundary should catch all PII at exit points. Note that `--save` session files deliberately preserve unredacted data for investigation continuity — that's by design.

### Tests failing
```bash
python -m pytest tests/ -q
```
All 2,328 tests should pass with no external services. If failures occur, check that you've installed dev dependencies: `pip install -e ".[dev]"`

---

## Quick Reference

```bash
# Investigate
emet investigate "goal"                    # Stub mode
emet --llm anthropic investigate "goal"    # With LLM
emet --llm anthropic investigate "goal" -i # Interactive
emet --llm anthropic investigate "goal" --dry-run  # Plan only

# Search
emet search "John Smith" --type Person

# Workflow
emet workflow corporate_ownership --target "Acme Corp"

# Serve
emet serve --http --port 8000              # HTTP API
emet serve --transport stdio               # MCP server

# Status
emet status
```
