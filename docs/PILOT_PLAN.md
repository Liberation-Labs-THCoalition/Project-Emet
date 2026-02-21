# Emet — Pilot & Testing Roadmap

**Version:** 1.0 — February 2026
**Status:** Pre-pilot preparation
**Target partner:** OCCRP (primary), adaptable to other qualifying organizations

---

## Current State (What We Have)

| Component | Status | Notes |
|-----------|--------|-------|
| Core framework | ✅ Complete | 25K lines, 156 files, 15 skill chips |
| FtM data spine | ✅ Complete | Full FollowTheMoney schema support |
| Aleph client | ⚠️ Mock only | 23-entity test dataset, 66 integration tests passing |
| FastAPI server | ✅ Complete | 8 endpoints, OpenAPI docs |
| Cognition layer | ✅ Complete | EFE routing, orchestrator, keyword fallback |
| Ethics governance | ✅ Complete | VALUES.json, consensus gates |
| E2E tests | ✅ 51/51 passing | |
| Integration tests | ✅ 66/66 passing | All against mock Aleph |
| Documentation | ✅ Complete | README, ARCHITECTURE, USER_GUIDE (831 lines) |
| License | ✅ Complete | Source-Available v1.0, journalism carve-out |
| Live infrastructure | ❌ Not tested | No real Aleph, no real DB, no Docker deployment |
| LLM integration | ❌ Stub only | Skill chips use regex/pattern matching |
| Authentication | ❌ None | No user accounts, no API keys |
| Web UI | ❌ None | API-only, curl/notebook access |

---

## Gap Analysis: What Needs to Happen Before a Journalist Touches This

### Priority 1 — Must Have for Alpha (Weeks 1–4)

**Live Aleph Connection**
The entire value proposition depends on this. Replace mock transport with real httpx calls to an Aleph instance. OCCRP runs the largest public Aleph deployment (data.occrp.org) — if they're the partner, we may get API access or a staging instance.

Tasks:
- Configure real Aleph API base URL and authentication (API key)
- Test all AlephClient methods against a live instance
- Handle rate limiting, pagination, and timeout gracefully
- Validate FtM entity parsing against real (messy) Aleph data
- Write integration tests that run against a live Aleph sandbox

**PostgreSQL Database**
The memory layer, investigation state, and audit logs all need persistence.

Tasks:
- Stand up PostgreSQL (Docker Compose already defines it)
- Run Alembic migrations
- Test investigation state persistence across server restarts
- Verify audit trail captures all agent actions

**Docker Compose Stack**
The deployment target for any pilot partner.

Tasks:
- Test full `docker-compose up` from clean state
- Verify: API server, PostgreSQL, Redis (if needed), all healthy
- Document environment variables and secrets management
- Create `docker-compose.pilot.yml` with production-appropriate defaults
- Test on a fresh Linux VM (not just the dev machine)

**LLM Integration**
Skill chips currently return template/regex results. For a journalist to find this useful, the NLP extraction, story development, and verification chips need real language model backing.

Tasks:
- Integrate LLM provider (OpenAI API, Anthropic API, or local model)
- Configure API key management (env vars, not hardcoded)
- Update NLP extraction chip: real entity recognition, relationship extraction
- Update story development chip: real outline generation, narrative assistance
- Update verification chip: real source cross-referencing suggestions
- Add token usage tracking and cost monitoring
- Test with real investigative text (redacted OCCRP examples if available)

**Basic Authentication**
Journalists need individual accounts. Investigations contain sensitive material.

Tasks:
- API key-based auth for MVP (no OAuth yet)
- Per-user investigation isolation
- Rate limiting per API key
- Audit log ties actions to authenticated user

### Priority 2 — Must Have for Pilot (Weeks 5–8)

**Operational Security Review**
This is non-negotiable before real journalists use it with real sources.

Tasks:
- Threat model: who are the adversaries? (State actors, corporate targets, litigation opponents)
- Source protection audit: can any Emet output leak source identity?
- Data at rest: PostgreSQL encryption, investigation data isolation
- Data in transit: TLS everywhere, API key rotation
- Logging review: ensure logs don't capture source names or investigation details
- LLM provider review: what data goes to OpenAI/Anthropic? Can we use local models?
- Network isolation: Emet instance should not be reachable from public internet
- Document the security model for journalist review

**Notebook / CLI Interface**
Most investigative journalists are not going to curl an API. Before a web UI exists, Jupyter notebooks are the pragmatic interface.

Tasks:
- Create 3–5 investigation workflow notebooks:
  - "New Investigation: Search and Map an Entity Network"
  - "Shell Company Detection: Analyze a Corporate Structure"
  - "Financial Trail: Extract and Follow the Money"
  - "Pre-Publication: Verify Claims and Check for Defamation Risk"
  - "Monitoring: Set Up Alerts for Ongoing Investigations"
- Each notebook: narrative walkthrough, working code cells, markdown explanations
- Package as JupyterHub deployment or VS Code dev container

**Error Handling and Graceful Degradation**
Real Aleph data is messy. Real networks are unreliable. Real journalists don't read stack traces.

Tasks:
- Human-readable error messages for all failure modes
- Graceful degradation when Aleph is unreachable
- Graceful degradation when LLM provider is down
- Retry logic with exponential backoff for external APIs
- Investigation state preservation on crash

### Priority 3 — Should Have for Beta (Weeks 9–16)

**Web UI**
A proper browser-based interface for non-technical journalists.

Tasks:
- Investigation dashboard: active investigations, recent activity
- Entity search and network visualization (graph view)
- Skill chip invocation through UI forms
- Investigation timeline view
- Export: PDF reports, FtM entity bundles, structured data
- Framework: React or similar (lightweight, auditable)

**Multi-User Collaboration**
Real investigations are team efforts.

Tasks:
- Shared investigations with role-based access
- Investigation-level permissions (owner, editor, viewer)
- Activity feed per investigation
- Consensus gate UI for editorial review actions

**External Data Source Integration**
Live connections beyond Aleph.

Tasks:
- OpenSanctions / yente: live entity matching
- OpenCorporates: real company lookups
- ICIJ Offshore Leaks: live search
- GLEIF: LEI resolution
- Test each adapter against real APIs

**Monitoring and Observability**
For a production deployment someone else is relying on.

Tasks:
- OpenTelemetry traces (already stubbed in kintsugi_engine)
- Health check dashboard
- Alert on: API errors > threshold, Aleph unreachable, LLM cost spike
- Usage metrics: investigations created, skill chips invoked, entities processed

---

## Pilot Structure

### Phase 0: Pre-Pilot (4 weeks)
**Goal:** Live infrastructure working end-to-end with real Aleph data.

- Complete Priority 1 tasks
- Deploy to a secure staging environment
- Run the full integration test suite against live Aleph
- Internal testing: run 2–3 synthetic investigations through the complete pipeline
- Document known limitations and workarounds

**Exit criteria:**
- [ ] Live Aleph search returns real entities
- [ ] Entity expansion builds real network graphs
- [ ] NLP extraction works on real investigation text
- [ ] Shell company detection produces meaningful results on real corporate structures
- [ ] Investigation state persists across server restarts
- [ ] Docker Compose stack deploys cleanly on a fresh VM
- [ ] Security review complete, no source-leaking pathways identified

### Phase 1: Alpha — Closed Internal (2 weeks)
**Goal:** Validate with 1–2 OCCRP technologists or data journalists.

- Participants: OCCRP tech team members who already know Aleph internals
- Method: Pair programming / guided sessions, not unsupervised use
- Focus: Does Emet surface connections that Aleph alone doesn't? Is the skill chip model intuitive? What breaks?
- Feedback: Daily standups or async Slack channel
- Scope: Use on non-sensitive, already-published investigations (so no source protection risk during testing)

**What we're testing:**
- Aleph integration reliability
- Skill chip usefulness (which chips do they actually use?)
- Routing accuracy (does the orchestrator pick the right chip?)
- Performance (acceptable response times?)
- Data quality (do FtM entities parse correctly from real Aleph data?)

**What we're NOT testing yet:**
- Security under adversarial conditions
- Multi-user collaboration
- Non-technical journalist usability

**Exit criteria:**
- [ ] At least one real investigation workflow completed end-to-end
- [ ] Critical bugs identified and fixed
- [ ] Skill chip priority list from testers (what to improve first)
- [ ] Performance benchmarks established
- [ ] Go/no-go decision for pilot

### Phase 2: Pilot — Supervised Use (4 weeks)
**Goal:** 3–5 OCCRP journalists use Emet on real (active or recent) investigations.

- Participants: Investigative journalists, not just technologists
- Method: Jupyter notebooks + API access, with dedicated support channel
- Focus: Does Emet make investigations faster or surface things journalists would have missed?
- Feedback: Weekly check-ins, structured feedback form, open Slack channel
- Scope: Real investigations, but with operational security measures in place

**Structure:**
- Week 1: Onboarding. Walk each journalist through their first investigation using Emet. Stay on call.
- Week 2–3: Independent use with support. Journalists use Emet on their own, flag issues async.
- Week 4: Retrospective. What worked, what didn't, what do they actually need?

**Metrics:**
- Time-to-insight: How long to map a corporate network vs. manual Aleph?
- Coverage: Did Emet surface entities/connections the journalist hadn't found?
- Trust: Did journalists trust Emet's outputs enough to act on them?
- Chip usage: Which skill chips got used? Which got ignored?
- Error rate: How often did Emet produce incorrect or misleading results?
- NPS-style: "Would you use this again on your next investigation?"

**Exit criteria:**
- [ ] At least 3 journalists completed real investigation workflows
- [ ] Measurable improvement in at least one metric (time, coverage, or connections found)
- [ ] No source protection incidents
- [ ] Prioritized feature request list
- [ ] Go/no-go decision for beta

### Phase 3: Beta — Broader Access (8+ weeks)
**Goal:** Open to all qualifying OCCRP journalists + 2–3 additional partner organizations.

- Participants: 15–30 journalists across multiple organizations
- Method: Web UI (if ready) + notebooks + API
- Focus: Scale, stability, cross-organization use patterns
- Feedback: In-app feedback mechanism, monthly retrospectives
- Scope: Full production use with real investigations

**Additional requirements for beta:**
- Web UI minimum viable version
- Multi-user investigation support
- Automated deployment (CI/CD pipeline)
- Monitoring and alerting
- User documentation (not just developer docs)
- Incident response plan

---

## Resource Requirements

### Infrastructure
- **Staging server:** 4 vCPU, 16GB RAM, 100GB SSD (Emet + PostgreSQL + Aleph sandbox)
- **Production server:** 8 vCPU, 32GB RAM, 200GB SSD (for pilot/beta)
- **LLM API budget:** ~$200–500/month during pilot (depends on usage volume and model choice)
- **Domain + TLS:** For API endpoint

### People
- **Lead developer:** Full-time through pilot, part-time through beta
- **OCCRP liaison:** 1 person who bridges between Emet development and editorial needs
- **Security reviewer:** Part-time or contract, especially pre-pilot
- **Pilot journalists:** 3–5 for pilot, 15–30 for beta

### Timeline (Optimistic)
| Phase | Duration | Dates (if starting March 2026) |
|-------|----------|-------------------------------|
| Pre-pilot | 4 weeks | March 1 – March 28 |
| Alpha | 2 weeks | March 29 – April 11 |
| Pilot | 4 weeks | April 12 – May 9 |
| Beta prep | 4 weeks | May 10 – June 6 |
| Beta | 8+ weeks | June 7 – August 1+ |

### Timeline (Realistic)
Add 50% buffer to every phase. Things will break. Aleph's API will surprise us. Journalists will want features we didn't anticipate. The realistic first beta is late Q3 2026.

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Aleph API changes or access revoked | Critical | Low | Maintain mock fallback, abstract API layer |
| LLM produces hallucinated entities/connections | High | Medium | Consensus gates, mandatory human verification, clear "AI-generated" labeling |
| Source identity leaked through logs or LLM API | Critical | Low | Security audit, local model option, log scrubbing |
| Journalists don't find it useful | High | Medium | Early alpha feedback, iterate before pilot |
| Performance too slow for interactive use | Medium | Medium | Async processing, caching, benchmark early |
| OCCRP partnership doesn't materialize | High | Unknown | Identify backup partners: ICIJ, Bellingcat, GIJN member orgs |
| Skill chips don't work on real (messy) data | High | High | Budget significant time for data quality handling |
| Single developer dependency | High | High | Document everything, keep code clean, plan for contributors |

---

## What to Send Your Contact

Don't send the pilot plan. Send three things:

1. **The README** — it speaks for itself. Source-available, 15 skill chips, FtM-native, ethics-governed. Link: https://github.com/Liberation-Labs-THCoalition/Project-FtM

2. **A one-paragraph pitch:**

   > Emet is an investigative journalism framework built on FollowTheMoney and designed to work with Aleph. It gives journalists 15 specialized AI skill chips — shell company detection, financial trail analysis, network mapping, NLP extraction, source verification, story development — orchestrated by an ethics-governed agent that enforces editorial standards before any output reaches the journalist. It's source-available (free for newsrooms, licensed for commercial use) and the code is public for security auditing. We're looking for a pilot partner to test it against real investigations. OCCRP built the infrastructure Emet runs on — you're the natural first home for it.

3. **A specific ask:**

   > Would anyone on the OCCRP data/tech team be willing to spend 30 minutes looking at the repo and telling us if this is worth testing? We're not asking for a commitment — just an informed opinion from someone who knows Aleph.

That's it. Don't oversell. Let the code do the talking. If they look at the repo and see 25,000 lines of working Python with 117 passing tests and a license that specifically protects their journalists, the conversation will happen naturally.
