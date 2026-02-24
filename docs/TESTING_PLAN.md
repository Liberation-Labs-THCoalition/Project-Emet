# Emet Pre-Release Testing Plan

## Part 1: Live Cluster Integration Tests

Tests requiring real API access, network calls, and compute resources.  
Designed for automated execution on the research cluster with API keys configured.

---

### 1.1 External Data Source Integration Tests

Each test hits a real API, validates response shape, and confirms the FtM
converter produces a valid entity. Run with `pytest -m live` (all tagged
`@pytest.mark.live`).

**Test file:** `tests/live/test_live_federation.py`

#### OpenSanctions / Yente

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_yente_search_known_entity` | Search "Gaddafi" → results with score > 0.5 | ≥1 entity, schema=Person, has sanctions datasets |
| `test_yente_match_known_entity` | Match against known sanctioned company | Match response with results, score > 0.7 |
| `test_yente_empty_result` | Search gibberish string → empty results | `result_count == 0`, no crash |
| `test_yente_timeout_recovery` | Set 0.001s timeout, verify graceful failure | Returns `{"error": "timeout"}`, no exception |
| `test_yente_ftm_validity` | Full pipeline: search → convert → validate | All returned entities pass `_validate_ftm_entity` |

#### OpenCorporates

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_oc_search_known_company` | Search "Deutsche Bank" jurisdiction:de | ≥1 result, has company_number |
| `test_oc_officer_search` | Officer search for known directorship | Person entity with name, relationship hints |
| `test_oc_monthly_counter_integration` | Counter increments on real requests | `counter.remaining` decreases by 1 per call |
| `test_oc_rate_limit_respected` | Rapid burst doesn't produce 429 errors | All calls succeed under free-tier limits |

#### ICIJ Offshore Leaks

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_icij_search_known_leak` | Search known Panama Papers entity | Entity with sourceID containing "Panama" |
| `test_icij_relationships` | Fetch relationships for known node | Directorship/Ownership entities with valid schema |
| `test_icij_node_types` | Entity vs Officer vs Intermediary routing | Correct FtM schema per node type |

#### GLEIF

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_gleif_search_by_name` | Search "Apple Inc" | LEI entity with valid 20-char LEI code |
| `test_gleif_search_by_lei` | Direct LEI lookup | Exact match with full entity data |
| `test_gleif_relationships` | Parent/child corporate relationships | Ownership entities linking parent to child |

#### Companies House

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_ch_search_company` | Search "Tesco" | Company with number, status, address |
| `test_ch_get_officers` | Officers for known company number | ≥1 Person + Directorship pair |
| `test_ch_get_psc` | PSC (ownership) for known company | Ownership entities with control nature |
| `test_ch_ftm_roundtrip` | Full pipeline through converter | All entities pass validation |

#### SEC EDGAR

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_edgar_search_company` | Search "Apple" by ticker AAPL | Company with CIK, SIC code |
| `test_edgar_recent_filings` | Get 10-K filings for known CIK | Document entities with filing dates |
| `test_edgar_insider_transactions` | Get insider trading data | Transaction entities with dates and values |

#### GDELT

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_gdelt_keyword_search` | Search "corruption investigation" | Articles with URLs, dates, tones |
| `test_gdelt_ftm_conversion` | Articles → FtM Mention entities | Valid entities with provenance |
| `test_gdelt_person_extraction` | NER extracts people from articles | Person entities from article text |

#### Blockchain (Etherscan + Blockstream)

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_etherscan_known_address` | Query Vitalik's address balance | Non-zero balance, tx_count > 0 |
| `test_etherscan_rate_limit` | 5 calls/sec bucket respected | No 429 errors under TokenBucketLimiter |
| `test_blockstream_known_address` | Query known BTC address | Balance data, UTXO info |
| `test_tron_known_address` | Query known Tron address | Balance data with bandwidth info |

---

### 1.2 Federation End-to-End Tests

**Test file:** `tests/live/test_live_e2e_federation.py`

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_federated_search_all_sources` | Fan out "Deutsche Bank" to all sources | Results from ≥3 sources, dedup merges AG/no-suffix variants |
| `test_federated_search_timeout_handling` | One source deliberately slow | Other sources return results, slow source logged as timeout |
| `test_federated_search_one_source_down` | Disable one API key | Remaining sources return results, error dict has failure |
| `test_federated_cache_hit` | Same query twice | Second call has cache_hits > 0, faster wall time |
| `test_federated_dedup_cross_source` | Entity appears in OpenSanctions + GLEIF | Dedup merges to 1 entity, provenance lists both sources |
| `test_federated_queried_at` | Any search | `result.queried_at` is valid ISO 8601 within last 60s |

---

### 1.3 Full Investigation Pipeline Tests

**Test file:** `tests/live/test_live_investigation.py`

These are the crown jewels — full agent loop with real tools.

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_investigation_known_sanctioned_entity` | Investigate "Viktor Bout" | Finds sanctions hits, news articles, produces report |
| `test_investigation_shell_company_network` | Investigate known ICIJ entity | Follows ownership leads, builds graph, finds circular structures |
| `test_investigation_clean_entity` | Investigate "Microsoft Corporation" | No sanctions hits, clean entity, report says "no adverse findings" |
| `test_investigation_nonexistent_entity` | Investigate "Xyzzy Fake Corp 99999" | Graceful conclusion within 3 turns, empty report |
| `test_investigation_report_pii_scrubbed` | Run in publish mode | No SSNs, credit cards, emails in output report |
| `test_investigation_graph_generation` | Check Cytoscape output | Valid JSON graph with nodes + edges matching entity count |
| `test_investigation_concurrent_real` | Two investigations simultaneously | No entity cross-contamination, both complete |
| `test_investigation_resume` | Save session, load, continue | Session state restored, investigation resumes correctly |

---

### 1.4 LLM Integration Tests

**Test file:** `tests/live/test_live_llm.py`

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_ollama_decision_making` | LLM picks appropriate next tool | Returns valid JSON action with tool + args |
| `test_ollama_report_synthesis` | LLM generates investigation summary | Coherent markdown report referencing findings |
| `test_anthropic_fallback` | Ollama unavailable, falls back to Anthropic | Investigation completes on cloud provider |
| `test_llm_decision_respects_budget` | Turn 14 of 15 → LLM should conclude | Action is "conclude", not another search |
| `test_llm_handles_empty_context` | No findings yet, LLM still picks tool | Valid search action, not an error |

---

### 1.5 Infrastructure Tests

**Test file:** `tests/live/test_live_infra.py`

| Test | What it validates | Expected |
|------|-------------------|----------|
| `test_http_api_investigation_lifecycle` | POST /investigate → poll → GET result | 201 → running → completed with report |
| `test_websocket_streaming` | Connect WS, start investigation | Receives progress events, final report |
| `test_mcp_server_tool_listing` | JSON-RPC initialize → tools/list | All 12+ tools listed with schemas |
| `test_mcp_server_tool_call` | JSON-RPC tools/call search_entities | Valid FtM entities returned |

---

### 1.6 Cluster Test Runner Configuration

```yaml
# tests/live/conftest.py configuration
# Requires .env with:
#   OPENSANCTIONS_API_URL=https://api.opensanctions.org
#   OPENCORPORATES_API_KEY=...
#   COMPANIES_HOUSE_API_KEY=...
#   ETHERSCAN_API_KEY=...
#   ANTHROPIC_API_KEY=... (for fallback tests)
#   OLLAMA_BASE_URL=http://localhost:11434

markers:
  live: "requires real API access"
  live_slow: "live test >30s"
  live_llm: "requires LLM (Ollama or Anthropic)"
  live_blockchain: "requires blockchain API keys"

# Run: pytest -m live --timeout=120
# Run fast only: pytest -m "live and not live_slow"
# Run LLM tests: pytest -m live_llm
```

---

## Part 2: Architectural Improvements for Coverage

Current: **26% overall** (17,225 lines, 12,768 uncovered).

Target: **60%+** with strategic effort on high-value modules.

---

### 2.1 Coverage Heat Map

```
CRITICAL PATH (agent loop → tools → federation → report)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
agent/session.py          ██████████ 100%  ✓ done
agent/persistence.py      █████████▍  94%  ✓ done
export/timeline.py        █████████▉  99%  ✓ done
export/ftm_bundle.py      █████████▋  97%  ✓ done
export/markdown.py        ████████▊   88%  ✓ done
security/monitor.py       █████████   91%  ✓ done
rate_limit.py             ████████▋   87%  ✓ done
agent/loop.py             ████████▎   83%  → 90% (LLM decision path)
agent/safety_harness.py   ████████▏   82%  → 90% (publication mode paths)
security/shield.py        ████████▍   84%  ✓ good enough
converters.py             ███████▊    78%  ✓ done
security/pii.py           ███████▍    74%  ✓ done
gdelt.py                  ███████▏    72%  ✓ good enough
ftm_loader.py             █████▌      55%  → 75%
companies_house.py        █████       51%  → 70% (needs mock HTTP)
graph/engine.py           ████▌       46%  → 70%
edgar.py                  ████▍       44%  → 65%
monitoring/__init__.py    ████▍       44%  → 60%
blockchain.py             ████        41%  → 60%
federation.py             ████        41%  → 65%
mcp/tools.py              ███▋        37%  → 65%

DEAD WEIGHT (0% — should either test or delete)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
adapters/  (all)          ░░░░░░░░░░   0%  ~2,600 lines
api/routes/ (all)         ░░░░░░░░░░   0%  ~1,100 lines
skills/  (all)            ░░░░░░░░░░   0%  ~1,200 lines
workflows/ (all)          ░░░░░░░░░░   0%  ~  350 lines
ftm/aleph_client.py       ░░░░░░░░░░   0%  ~  144 lines
ftm/data_spine.py         ░░░░░░░░░░   0%  ~  207 lines
external/augmentation.py  ░░░░░░░░░░   0%  ~  151 lines
external/document_src.py  ░░░░░░░░░░   0%  ~  148 lines
external/entity_res.py    ░░░░░░░░░░   0%  ~  184 lines
external/semantic.py      ░░░░░░░░░░   0%  ~  174 lines
external/spiderfoot.py    ░░░░░░░░░░   0%  ~  164 lines
external/transcription.py ░░░░░░░░░░   0%  ~  188 lines
graph/visualizer.py       ░░░░░░░░░░   0%  ~   47 lines

INHERITED/KINTSUGI (test if keeping, delete if not)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
bdi/                      ██            20%  ~  500 lines
calibration/              ███▍          34%  ~  800 lines
cognition/                ██▌           25%  ~  900 lines
memory/                   ███▌          35%  ~  500 lines
multitenancy/             ███           30%  ~  650 lines
plugins/                  ██▌           25%  ~  850 lines
tuning/                   ███           30%  ~  630 lines
```

---

### 2.2 Strategy: Three Tiers of Effort

#### Tier A: High-ROI Unit Tests (offline, no APIs)
**Goal:** +15-20% coverage. ~2-3 sessions of work.

These modules have well-defined inputs/outputs and can be tested with
mocks. Highest value per line of test code.

| Module | Current | Target | Approach |
|--------|---------|--------|----------|
| `mcp/tools.py` (912 lines) | 37% | 65% | Mock executor, test each tool handler's arg parsing + response shaping |
| `graph/algorithms.py` (751 lines) | 26% | 60% | Build small NetworkX graphs, test each algorithm directly |
| `graph/engine.py` (72 lines) | 46% | 80% | Test load/analyze/export cycle with fixture graph |
| `graph/ftm_loader.py` (101 lines) | 55% | 80% | Feed FtM entity dicts, verify graph structure |
| `graph/exporters.py` (113 lines) | 20% | 70% | Test each format (GEXF, GraphML, CSV, D3, Cytoscape) |
| `federation.py` fan-out (683 lines) | 41% | 65% | Mock individual source clients, test parallel fan-out + dedup |
| `agent/loop.py` LLM path (839 lines) | 83% | 92% | Mock LLM responses, test decision parsing + edge cases |
| `export/pdf.py` (426 lines) | 15% | 50% | Generate PDF, verify it's valid (pypdf read), check sections exist |

**Implementation pattern for MCP tools:**
```python
class TestMCPToolHandlers:
    """Test each MCP tool handler with mock executor."""

    def setup_method(self):
        self.executor = MockExecutor()  # Returns canned responses
        self.tools = MCPToolRegistry(self.executor)

    async def test_search_entities_handler(self):
        result = await self.tools.handle("search_entities", {"query": "test"})
        assert "entities" in result

    async def test_screen_sanctions_handler(self):
        result = await self.tools.handle("screen_sanctions", {"entities": ["Test Corp"]})
        assert "matches" in result
```

**Implementation pattern for graph algorithms:**
```python
class TestGraphAlgorithms:
    """Test investigative graph algorithms on small fixture graphs."""

    def _shell_company_graph(self):
        """3-node chain: Person → Company A → Company B (offshore)."""
        G = nx.DiGraph()
        G.add_edge("person1", "company_a", relationship="director")
        G.add_edge("company_a", "company_b", relationship="shareholder")
        # ... node attributes
        return G

    def test_broker_detection(self):
        G = self._hub_graph()  # Node with high betweenness
        brokers = find_brokers(G)
        assert "hub_node" in [b["id"] for b in brokers]

    def test_circular_ownership_detection(self):
        G = self._circular_graph()  # A→B→C→A
        cycles = detect_circular_ownership(G)
        assert len(cycles) >= 1
```

#### Tier B: Integration Test Scaffolding (mock HTTP)
**Goal:** +8-12% coverage. ~2 sessions of work.

These modules make HTTP calls. Test them with `respx` or `aioresponses`
to mock HTTP without network access.

| Module | Current | Target | Approach |
|--------|---------|--------|----------|
| `ftm/external/adapters.py` | 32% | 60% | Mock HTTP responses per source |
| `ftm/external/blockchain.py` | 41% | 60% | Mock Etherscan/Blockstream JSON responses |
| `ftm/external/companies_house.py` | 51% | 70% | Mock CH API responses |
| `ftm/external/edgar.py` | 44% | 65% | Mock EDGAR EFTS responses |
| `api/routes/*.py` | 0% | 40% | FastAPI TestClient, mock agent |
| `mcp/server.py` | 17% | 50% | Mock JSON-RPC requests |

**Implementation pattern:**
```python
@pytest.fixture
def mock_http(respx_mock):
    respx_mock.get("https://api.company-information.service.gov.uk/search/companies").respond(
        json={"items": [{"company_name": "Tesco", "company_number": "00445790"}]}
    )
    return respx_mock

async def test_ch_search(mock_http):
    client = CompaniesHouseClient(config)
    result = await client.search("Tesco")
    assert result["entities"][0]["properties"]["name"][0] == "Tesco"
```

#### Tier C: Delete-or-Defer Decision
**Goal:** Remove ~4,000 lines of dead 0% code, instantly raising coverage.

These modules are either Kintsugi heritage not wired into the agent loop,
or features not yet connected. Each needs a decision.

| Module | Lines | Decision Criteria |
|--------|-------|-------------------|
| `skills/` (all) | 1,200 | **DELETE** — superseded by MCP tools. Skill chips are from the old Kintsugi orchestrator. No code references them in the agent loop. |
| `workflows/` (all) | 350 | **DEFER** — workflow engine is built but not wired to agent loop yet. Keep code, exclude from coverage. |
| `ftm/aleph_client.py` | 144 | **KEEP** — will be needed for OCCRP pilot. Add basic mock tests. |
| `ftm/data_spine.py` | 207 | **EVALUATE** — is this used? If only by old skill chips, delete. |
| `ftm/external/augmentation.py` | 151 | **DEFER** — blockchain augmentation, keep for later sprint. |
| `ftm/external/document_sources.py` | 148 | **DEFER** — Datashare/DocumentCloud adapters, keep for later. |
| `ftm/external/entity_resolution.py` | 184 | **DEFER** — Splink integration, keep for later sprint. |
| `ftm/external/semantic_search.py` | 174 | **DEFER** — ChromaDB RAG, keep for later sprint. |
| `ftm/external/spiderfoot.py` | 164 | **DEFER** — SpiderFoot OSINT adapter, keep for later sprint. |
| `ftm/external/transcription.py` | 188 | **DEFER** — faster-whisper, keep for later sprint. |
| `graph/visualizer.py` | 47 | **DEFER** — Cytoscape HTML viewer, keep. |
| `adapters/email/` | 1,100 | **DEFER** — email adapter not MVP. Keep but exclude from coverage. |
| `adapters/discord/` | 524 | **DEFER** — Discord bot not MVP. Keep but exclude. |
| `adapters/slack/` | 554 | **KEEP** — Slack is a deployment target. Add mock tests. |
| `adapters/webchat/` | 480 | **KEEP** — webchat is the demo UI. Add TestClient tests. |

**If we delete `skills/` alone**, total lines drop from 17,225 to ~16,025, 
and coverage jumps from 26% to ~28% for free.

**If we also exclude `adapters/email/` and `adapters/discord/` from 
coverage** (via `[tool.pytest.ini_options] --cov-config`), we drop another
~1,600 measured lines, pushing to ~31%.

---

### 2.3 Coverage Exclusion Configuration

Add to `pyproject.toml`:

```toml
[tool.coverage.run]
omit = [
    "emet/skills/*",          # Deprecated skill chips (replaced by MCP tools)
    "emet/adapters/email/*",  # Not MVP
    "emet/adapters/discord/*",# Not MVP  
    "emet/workflows/*",       # Not yet wired to agent loop
    "emet/ftm/external/augmentation.py",    # Future sprint
    "emet/ftm/external/document_sources.py",# Future sprint
    "emet/ftm/external/entity_resolution.py",# Future sprint
    "emet/ftm/external/semantic_search.py", # Future sprint
    "emet/ftm/external/spiderfoot.py",      # Future sprint
    "emet/ftm/external/transcription.py",   # Future sprint
]
```

**Effect:** Measured codebase drops from ~17,225 to ~12,800 lines.
Current tested lines (~4,450) against 12,800 = **~35% immediately**.
After Tier A work: **~55-60%**.
After Tier B work: **~65-70%**.

---

### 2.4 Recommended Execution Order

```
Session 1: Tier C decisions + coverage config
  - Delete emet/skills/ (or move to emet/_deprecated/)
  - Configure coverage exclusions
  - Verify coverage baseline jumps to ~35%
  
Session 2: Tier A — Graph algorithms + engine
  - 8-10 tests for algorithms.py (brokers, communities, cycles, shell scoring)
  - 3-4 tests for engine.py (load → analyze → export)
  - 3-4 tests for exporters.py (each format)
  - 2-3 tests for ftm_loader.py
  - Expected: graph/ goes from 30% → 65%

Session 3: Tier A — MCP tools + server
  - Mock executor with canned responses
  - Test each of 12+ tool handlers
  - Test MCP server JSON-RPC protocol
  - Expected: mcp/ goes from 30% → 60%

Session 4: Tier A — Agent loop LLM path + PDF export
  - Mock LLM returning various JSON actions
  - Test decision parsing edge cases (malformed JSON, fenced blocks)
  - Test PDF generation + validation
  - Expected: agent/loop 83%→92%, export/pdf 15%→50%

Session 5: Tier B — Mock HTTP for external adapters
  - Install respx/aioresponses
  - Mock responses for CH, EDGAR, adapters
  - Expected: external adapters 40%→60%

Session 6: Tier B — API routes + adapter tests
  - FastAPI TestClient for all routes
  - Mock Slack/webchat adapter tests
  - Expected: api/ 0%→40%, adapters/ 0%→30%
```

**After all 6 sessions: estimated 65-70% coverage on measured codebase.**

---

### 2.5 Test Infrastructure Additions

```
tests/
├── conftest.py              # Shared fixtures (mock executor, sample entities)
├── live/
│   ├── conftest.py          # Live test config, API key loading, markers
│   ├── test_live_federation.py
│   ├── test_live_investigation.py
│   ├── test_live_llm.py
│   └── test_live_infra.py
├── fixtures/
│   ├── sample_entities.json  # Realistic FtM entity fixtures
│   ├── sample_graph.json     # Pre-built graph for algorithm tests
│   ├── ch_responses/         # Canned Companies House API responses
│   ├── edgar_responses/      # Canned EDGAR API responses
│   └── etherscan_responses/  # Canned blockchain API responses
├── test_agent.py
├── test_federation.py
├── test_ftm_roundtrip.py
├── test_graph_algorithms.py   # NEW: Tier A
├── test_mcp_tools.py          # NEW: Tier A
├── test_api_routes.py         # NEW: Tier B
└── ...
```

---

### 2.6 CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -m "not live" --cov=emet --cov-fail-under=55
      
  live-tests:
    runs-on: self-hosted  # Research cluster
    if: github.ref == 'refs/heads/main'
    env:
      OPENSANCTIONS_API_URL: ${{ secrets.OPENSANCTIONS_API_URL }}
      OPENCORPORATES_API_KEY: ${{ secrets.OC_API_KEY }}
      # ... other keys
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/live/ -m live --timeout=120
```
