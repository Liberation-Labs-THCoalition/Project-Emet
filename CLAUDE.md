# CLAUDE.md — Project Emet

## What Is Emet

Emet is an autonomous investigative intelligence framework for anti-corruption journalism. It traces corporate ownership, screens sanctions lists, analyzes blockchain flows, and synthesizes findings into auditable, publication-safe reports. The name means "truth" in Hebrew.

Emet is built for transparency organizations and investigative newsrooms. The cameras point UP the power hierarchy — never down at sources, whistleblowers, or vulnerable populations.

## Architecture

The system takes a natural-language investigation goal and runs a multi-step agent loop:

```
Goal → Initial Search → [LLM Decide → Execute → Process] x N → Report → Export
```

- **Agent loop** (`InvestigationAgent`): Turn-based LLM reasoning with heuristic fallback. One tool call per turn, budget-capped, with full audit trail.
- **FTM data spine**: All entities use the FollowTheMoney data model. Federated search fans out to 7 sources (OpenSanctions, OpenCorporates, ICIJ, GLEIF, Companies House, SEC EDGAR, Aleph).
- **Graph engine**: NetworkX-based with 7 investigative algorithms (community detection, centrality, brokers, shortest path, connected components, PageRank, temporal patterns). Multi-format export (GEXF, D3, Cytoscape, CSV).
- **MCP server**: Exposes 9+ tools via Model Context Protocol for Claude Desktop and other MCP clients.
- **Safety harness**: Two-mode (investigate=audit-only, publish=enforcing). PII scrubbing at all exit points.
- **LLM abstraction**: Anthropic Claude, Ollama (local), Stub (testing). Cascading fallback, tiered routing, per-session cost tracking.

Four interfaces: CLI, HTTP API (FastAPI), WebSocket streaming, MCP (stdio/SSE).

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `emet/agent/` | Core agent loop, session state, safety harness, audit, persistence |
| `emet/ftm/` | FTM data spine, Aleph client, federated search, blockchain (ETH/BTC/Tron) |
| `emet/graph/` | Graph analytics engine, 7 algorithms, FTM-to-NetworkX loader, exporters |
| `emet/export/` | Markdown, PDF, FTM bundle, and timeline report generation |
| `emet/workflows/` | Predefined investigation templates (corporate ownership, sanctions, etc.) |
| `emet/mcp/` | MCP server, tool executor, resource providers |
| `emet/security/` | Intent Capsules, Security Shield, Behavior Monitor |
| `emet/cognition/` | LLM clients (Anthropic, Ollama, Stub), factory, model router |
| `emet/api/` | FastAPI HTTP + WebSocket interfaces |
| `emet/monitoring/` | Change detection, snapshot diffing, sanctions alerts |
| `emet/skills/` | 15 specialized investigation skill chips |
| `skills/` | Investigation skill documentation (SKILL.md files) |

## Running Tests

```bash
# Full unit + integration suite (1,650 tests, ~3 minutes)
python -m pytest tests/ -q --ignore=tests/live

# Live integration tests (requires API keys)
python -m pytest -m live tests/live/ -v

# Key individual modules
python -m pytest tests/test_agent.py              # Agent loop
python -m pytest tests/test_security_pii.py        # PII scrubbing
python -m pytest tests/test_mcp_server.py          # MCP server
python -m pytest tests/test_graph.py               # Graph analytics
python -m pytest tests/test_federation.py          # Federated search
python -m pytest tests/test_e2e_pipeline.py        # End-to-end pipeline
python -m pytest tests/test_export.py              # Export pipeline
```

No external services needed for unit tests — all use stubs and mocks.

## Quick Start

```bash
pip install -e ".[dev]"
cp .env.example .env
# Stub mode (no API keys): emet investigate "Trace ownership of Acme" --llm stub
# Demo mode: emet investigate "Meridian Holdings" --llm stub --demo
# With LLM: export ANTHROPIC_API_KEY=sk-ant-... && emet investigate "Acme" --llm anthropic
```

## Team Context

Emet is a Coalition project (Liberation Labs / THCoalition). Built on Project Kintsugi (self-repairing agentic harness). Infrastructure layers (governance, security, memory, BDI, plugins) transfer from Kintsugi; investigative layers (agent loop, MCP tools, FTM spine, data sources) are Emet-specific.

Designed for: investigative journalists, newsrooms, press freedom organizations, anti-corruption NGOs, academic journalism programs.

## Ethics

- Cameras point UP — investigate power, never surveil the vulnerable
- Source protection is non-negotiable (weighted 0.25 in VALUES.json)
- PII scrubbing enforced at every publication boundary (CLI export, API response, PDF, adapter)
- Forensic audit trail: every tool call, LLM exchange, and reasoning step logged (gzip JSONL, SHA-256 verified)
- AI findings always flagged as requiring human verification
- Never fabricate evidence, impersonate sources, or publish without human review
- Consensus Gates require human approval for publication actions
- Prohibited uses: surveillance of journalists, press suppression, targeting whistleblowers, mass surveillance
