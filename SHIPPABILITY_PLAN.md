# Emet Shippability Plan

**Created:** 2026-02-24
**Goal:** Make Emet demo-ready and shippable to early users/buyers
**Status tracking:** ✅ done | 🔧 in progress | ⬜ not started

---

## Context (for post-compaction)

This plan follows a multi-session pre-release audit that found:
- 8 of 12 MCP tools crashed on real invocation (fixed: commit 0c66c00)
- 2 of 12 tools had FederatedResult type mismatches (fixed: commit c4a34cc)
- All 12 tools now execute without crashes (10 OK, 2 graceful soft errors)
- ICIJ API returns 404 (endpoint moved to reconciliation API in Jan 2025)
- End-to-end investigation produces empty results — first-use experience broken
- Session object doesn't expose generated report (AttributeError)
- Test mocks don't match real interfaces (hid all the above bugs)
- 13K lines of dead code (25% of codebase)
- .env.example missing 5+ data source configs

Key files modified in prior sessions:
- emet/mcp/tools.py — all 12 tool handlers
- emet/ftm/external/federation.py — Companies House kwarg fix
- emet/ftm/external/blockchain.py — Etherscan V2 upgrade
- emet/monitoring/__init__.py — ChangeDetector federation fix
- tests/test_mcp_server.py — FederatedResult mock fixes

---

## Tier 1: Blocks a Demo / First-Use

### 1.1 ✅ Fix first-use experience (demo mode) (DONE)
**Problem:** `emet investigate "..." --llm stub` returns 0 entities, 0 findings.
Without API keys, all federated sources fail (401/404). New user gets empty report.

**Fix approach:**
- Add a synthetic/demo data source to federation that returns realistic FtM entities
  when no real sources return data (or when a `--demo` flag is passed)
- OR: Ship a bundled demo dataset (JSONL of ~50 FtM entities) that the stub LLM
  mode loads automatically so the investigation pipeline has data to work with
- The demo should show: entity search → sanctions screen → ownership trace →
  graph analysis → report generation — all with plausible data
- CLI output should look impressive on first run

**Files likely touched:**
- emet/agent/loop.py (demo data injection)
- emet/cli.py (--demo flag or auto-detect)
- emet/data/demo_entities.json (new: bundled demo data)

### 1.2 ✅ Fix ICIJ Offshore Leaks adapter (DONE)
**Problem:** ICIJ moved from `/api/v1/search` to a reconciliation API in Jan 2025.
Current adapter returns 404 on every query. ICIJ is keyless/free — should just work.

**Fix approach:**
- Update emet/ftm/external/icij.py to use the new reconciliation endpoint
- New API: POST to `https://offshoreleaks.icij.org/api/v1/reconcile`
  with `{"queries": {"q0": {"query": "search term", "type": ["Entity"]}}}` 
- Verify with live request, update FtM converter for new response shape
- Add graceful fallback if reconciliation API also changes

**Files likely touched:**
- emet/ftm/external/icij.py (or wherever ICIJ adapter lives)
- tests/ (update ICIJ mocks)

### 1.3 ✅ Attach report to Session object (DONE)
**Problem:** Agent generates report internally but never stores it on Session.
`session.report` → AttributeError. CLI works around this via tool_history.

**Fix approach:**
- Add `report: str | None = None` field to Session dataclass
- In agent loop `_generate_report()`, store result on `session.report`
- Verify CLI `_save_report()` and `_print_session_results()` use it

**Files likely touched:**
- emet/agent/session.py (add report field)
- emet/agent/loop.py (store report on session)

---

## Tier 2: Undermines Credibility in Evaluation

### 2.1 ✅ Smoke-test MCP server end-to-end (DONE)
**Problem:** Tools work via execute_raw() but we haven't verified JSON-RPC works.
`emet serve --transport stdio` hasn't been tested with actual MCP messages.

**Fix approach:**
- Write a script that starts the MCP server, sends JSON-RPC tool calls, verifies responses
- Test at least: tools/list, search_entities, analyze_graph, generate_report
- Fix any serialization or transport issues found

**Files likely touched:**
- emet/mcp/server.py
- tests/test_mcp_integration.py (new or existing)

### 2.2 ✅ Smoke-test HTTP API end-to-end (DONE)
**Problem:** `emet serve --http` hasn't been verified to start and accept requests.

**Fix approach:**
- Start server, hit health endpoint, POST an investigation, verify response
- Test WebSocket streaming if claimed in README

**Files likely touched:**
- emet/api/ (server startup)
- tests/test_api_integration.py

### 2.3 ⬜ Fix test mock fidelity
**Problem:** Mocks return wrong types (list vs FederatedResult), use wrong kwargs.
Tests pass but don't catch real bugs. A technical evaluator will notice.

**Fix approach:**
- Systematic pass over tests/test_mcp_server.py
- For each mocked function: verify mock return type matches real function
- For each tool test: verify args match tool's actual signature
- Add a "mock fidelity" test that imports real classes and asserts mock shapes match

**Files likely touched:**
- tests/test_mcp_server.py
- tests/conftest.py (shared fixtures)

---

## Tier 3: Professional Polish

### 3.1 ⬜ Complete .env.example
**Problem:** Missing Etherscan, GLEIF, GDELT, SpiderFoot, DocumentCloud entries.

**Fix:** Add all env vars with descriptions. Group by category.

### 3.2 ⬜ Quarantine dead code
**Problem:** 13K lines never imported. Makes codebase look unfocused.

**Fix approach:**
- Move to `_future/` or `emet/_incubator/` directory
- Keep tests but mark as `@pytest.mark.incubator`
- Dead modules: discord adapter, email adapter, old skills, BDI,
  plugins system, multitenancy, EFE tuning

### 3.3 ⬜ CLI entry point reinstall
**Problem:** `emet` command not found after pip install -e .

**Fix:** Verify pyproject.toml entry points, document reinstall step.

---

## Execution Order

1. **1.3** — Session.report (smallest, unblocks other work)
2. **1.2** — ICIJ adapter (gets a real data source working keyless)
3. **1.1** — Demo mode (biggest impact, needs 1.3 done first)
4. **2.1** — MCP smoke test
5. **2.2** — HTTP API smoke test
6. **2.3** — Mock fidelity
7. **3.1** — .env.example
8. **3.2** — Dead code quarantine
9. **3.3** — CLI entry point
