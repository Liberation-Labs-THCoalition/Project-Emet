# Emet — Deployment Guide
### OCCRP Operations Team

Emet is an autonomous investigative intelligence framework. It runs entirely on your own hardware — no data leaves the machine, no cloud APIs are called, no telemetry is sent. This guide covers getting it running across three deployment tiers.

---

## Prerequisites

**All tiers**
- Docker Engine 24+ and Docker Compose v2 (`docker compose` not `docker-compose`)
- Git
- 100GB+ free disk for models (field), 200GB (server), 500GB (enterprise)
- Internet access on first run to pull models; air-gapped operation possible after that

**Check your Docker install:**
```bash
docker compose version
# Should return: Docker Compose version v2.x.x
```

---

## Deployment Tiers

### Field — Laptop / Mac Mini (24–32GB RAM)
Models: Qwen3 14B (reasoning) + Qwen3 8B (extraction)  
Model footprint: ~15GB on disk, ~20GB RAM when loaded  
Suitable for: field investigations, individual analyst workstations

```bash
docker compose -f docker-compose.yml -f docker-compose.field.yml up -d
```

### Server — Office Server (64GB+ RAM)
Models: Qwen3.5 27B (deep reasoning) + Qwen3 8B (extraction)  
Model footprint: ~23GB on disk, ~40GB RAM when loaded  
Suitable for: shared newsroom server, small team concurrent use

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d
```

### Enterprise — Newsroom Infrastructure (256GB+ RAM)
Models: Qwen3 235B MoE (142GB) + Qwen3.5 27B (17GB) + Qwen3 8B (6GB)  
Model footprint: ~165GB on disk, ~170GB RAM when all three are loaded  
Suitable for: organization-wide deployment, concurrent multi-investigator use  
Note: 512GB+ systems should increase `OLLAMA_NUM_PARALLEL` in the compose file for higher concurrency.

```bash
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d
```

---

## First Run

On first run, the `ollama-setup` container pulls models before Emet can process requests. **This happens automatically** — you do not need to do anything. Expected download times on a 1Gbps connection:

| Tier | Download size | Approximate time |
|------|--------------|------------------|
| Field | ~15GB | 5–10 minutes |
| Server | ~23GB | 10–20 minutes |
| Enterprise | ~165GB | 60–120 minutes |

**Wait for models before running investigations.** Monitor pull progress:
```bash
docker compose logs -f ollama-setup
```
The setup container exits with a "models ready" message when complete. After that, `ollama-setup` stays exited — this is expected.

Verify everything is up:
```bash
docker compose ps
# engine, db, redis, mcp, spiderfoot should be running
# ollama-setup should be exited (0) after first run
```

Check the API is responding:
```bash
curl http://localhost:8000/health
```

---

## Demo Delivery

**The demo is pre-configured for the field tier.** Start the stack with the field command above, wait for models to pull, then:

```bash
bash demo_occrp.sh
```

This runs three investigations:
1. Corporate ownership trace — shell company network, offshore jurisdictions, nominee directors
2. Sanctions screening — PEP status, hits against OpenSanctions, adverse media
3. Financial flow analysis — ICIJ Offshore Leaks cross-reference, circular ownership detection

Reports are written to `./investigations/`. Each session also produces a full audit log.

The server and enterprise tiers are available in the repo for your infrastructure team to evaluate independently.

---

## CLI Usage

Run investigations directly from the command line:

```bash
python -m emet.cli investigate "Trace ownership of Meridian Holdings Ltd" --llm ollama
```

Common options:
```bash
# Set reasoning depth (default: 8 turns)
python -m emet.cli investigate "..." --llm ollama --max-turns 12

# Save session to file
python -m emet.cli investigate "..." --llm ollama --save investigations/my_case.json

# Use stub LLM for testing (no model required)
python -m emet.cli investigate "..." --llm stub
```

Or via the running container:
```bash
docker compose exec engine python -m emet.cli investigate "..." --llm ollama
```

---

## API Access

FastAPI HTTP interface on port 8000.

**Interactive docs:** `http://localhost:8000/docs`

Key endpoints:
```
POST /investigate          Start an investigation
GET  /investigations       List saved investigations
GET  /investigations/{id}  Retrieve a session
WS   /ws/investigate       WebSocket streaming (real-time turn output)
```

Example:
```bash
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"goal": "Screen Viktor Renko against OpenSanctions", "llm": "ollama"}'
```

---

## MCP Integration

The MCP server runs on port 9400 and exposes 9+ investigative tools to Claude Desktop and other MCP clients (entity lookup, sanctions screening, corporate registry search, graph analysis, report generation).

**For Claude Desktop**, add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "emet-investigative": {
      "url": "http://localhost:9400"
    }
  }
}
```

**For stdio transport** (local process, see `mcp-config.example.json`):
```json
{
  "mcpServers": {
    "emet-investigative": {
      "command": "python",
      "args": ["-m", "emet.mcp.server", "--transport", "stdio"],
      "env": {
        "SPIDERFOOT_HOST": "http://localhost:5001",
        "LLM_PROVIDER": "ollama"
      }
    }
  }
}
```

Once connected, Claude Desktop can invoke Emet tools directly from the chat interface.

---

## Security

**Data handling:**
- All LLM inference runs locally via Ollama. No data is sent to cloud APIs.
- The Anthropic API key field is explicitly set to empty in all local-mode compose files.
- PostgreSQL and Redis are local containers. Investigation data does not leave the host.
- SpiderFoot (OSINT sidecar) is self-hosted — it queries public OSINT sources, not third-party data brokers.

**Audit trail:**
- Every tool call, LLM exchange, and reasoning step is logged in gzip JSONL format.
- Logs are SHA-256 verified. Suitable for evidentiary use.
- Session logs are available per-investigation under the session directory.

**PII scrubbing:**
- PII scrubbing is enforced at all publication boundaries: CLI export, API response, PDF, and MCP adapter.
- The safety harness runs in two modes: `investigate` (audit-only) and `publish` (enforcing). Publication actions require human approval via Consensus Gates.

**Network exposure:**
- Default compose files bind only to localhost. If deploying on a shared server, configure a reverse proxy with TLS and authentication before exposing any port externally.
- Ports in use: 8000 (API), 9400 (MCP), 11434 (Ollama internal), 5432 (Postgres internal), 6379 (Redis internal), 5001 (SpiderFoot internal).

---

## Troubleshooting

**Ollama not responding**
```bash
docker compose logs ollama
# If container is restarting, check available RAM — Ollama may be OOM
docker stats ollama
```
If the host is low on memory, reduce model load by switching to a lower tier compose file.

**Model not found**
```bash
docker compose logs ollama-setup
# If it exited non-zero, re-run the pull manually:
docker compose exec ollama ollama pull qwen3:14b
docker compose exec ollama ollama pull qwen3:8b
```

**Out of memory / container killed**
- Field tier requires at least 24GB host RAM with models loaded. Close other applications.
- Server tier requires at least 64GB. The `ollama` service has a 48GB memory reservation — if the host cannot satisfy it, the container will not start.
- Enterprise tier: the 235B MoE model requires ~142GB. On 256GB hosts, ensure OS and services together leave 200GB+ available to Ollama.
- Check: `docker compose ps` and `docker compose logs engine` for OOM signals.

**Investigations directory missing**
```bash
mkdir -p investigations
# The demo script writes output here; it will error if the directory doesn't exist.
```

**Database connection errors on startup**
The engine waits for Postgres to be healthy before starting. If you see repeated connection errors, check:
```bash
docker compose logs db
docker compose ps db
```
A slow disk can delay Postgres initialization past the healthcheck timeout. If needed: `docker compose restart engine`.

---

## Contact

For deployment questions and evaluation support:  
thomas@liberationlabs.tech
