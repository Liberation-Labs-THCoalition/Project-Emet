# Emet Upgrade Notes — Claude Code Architecture Insights

**Date:** 2026-04-02
**Author:** CC (Coalition Code)
**Source:** Claude Code source analysis (512K lines, 18 sections analyzed)

---

## Applicable Patterns

### 1. Coordinator Mode → Investigation Orchestration

**Current:** Single-agent investigation with sequential tool calls.
**Upgrade:** Multi-agent parallel investigation using Coordinator Mode:

```
Coordinator (Emet Core):
  → Spawn entity-search worker: "Search OpenSanctions, ICIJ, SEC EDGAR for Meridian Holdings"
  → Spawn blockchain worker: "Trace Ethereum transactions from wallet 0x..."
  → Spawn osint worker: "Domain and social footprint for key individuals"
  → SYNTHESIS: Coordinator reads all findings, identifies connections
  → Spawn graph-analysis worker: "Run community detection on the combined entity graph"
  → Spawn report worker: "Generate publication-safe report with PII scrubbing"
```

**Benefit:** 3-5x faster investigations through parallel fan-out.
Coordinator catches connections workers miss by synthesizing across domains.

### 2. Skill System → Investigation Workflows as Skills

**Current:** Predefined investigation workflows (corporate ownership, sanctions sweep, etc.)
**Upgrade:** Convert workflows to Claude Code skill format:

```markdown
---
name: corporate-ownership-trace
description: Multi-hop beneficial ownership investigation
when-to-use: Tracing shell companies, offshore structures
tools: [search_entities, trace_ownership, analyze_graph, generate_report]
effort: high
effort-levels:
  - low: Single-hop, top-level only
  - medium: Multi-hop, key jurisdictions
  - high: Exhaustive, all jurisdictions + blockchain
---

# Corporate Ownership Trace

Trace beneficial ownership of the target entity through corporate structures...
```

### 3. Hook System → Forensic Audit Enhancement

**Current:** Forensic audit archive captures tool calls and LLM exchanges.
**Upgrade:** Use Claude Code hook events for richer capture:

| Hook | Emet Use |
|------|----------|
| PreToolUse | Log intended tool call with reasoning |
| PostToolUse | Log result + capture artifacts |
| PostToolUseFailure | Log failure + retry strategy |
| SubagentStart | Log investigation branch initiated |
| SubagentStop | Log investigation branch findings |
| FileChanged | Track evidence file modifications |
| SessionEnd | Generate investigation session summary |

### 4. autoDream → Investigation Memory

**Current:** Cross-session memory via file-based recall.
**Upgrade:** Apply autoDream 4-phase pattern to investigation memory:

1. **Orient** — Review prior investigation sessions, active targets
2. **Gather** — Check for new sanctions entries, corporate filings, news
3. **Consolidate** — Update entity knowledge graph with new findings
4. **Prune** — Remove superseded leads, update confidence scores

This makes Emet a **persistent investigator** that accumulates intelligence
across sessions rather than starting fresh each time.

### 5. Agent Definition → Emet as a Custom Agent

Define Emet as a proper Claude Code custom agent:

```markdown
---
name: emet
description: Autonomous investigative intelligence agent
when-to-use: Corporate investigations, sanctions screening, ownership tracing
tools: [Bash, Read, Write, Grep, WebSearch, WebFetch]
model: opus
effort: high
memory: project
permissionMode: default
maxTurns: 50
hooks:
  SessionStart:
    - command: python3 load_active_investigations.py
  Stop:
    - command: python3 archive_session.py
mcpServers: [emet-tools]
---
```

### 6. Dangerous Patterns → Investigation Safety

**Current:** PII scrubbing at publication boundary.
**Upgrade:** Apply the dangerous patterns concept to investigation actions:

- **Auto-allow:** Read-only searches, graph analysis, report generation
- **Require approval:** External API calls (sanctions APIs have rate limits and legal implications)
- **Hard deny:** Direct contact with investigation targets, unauthorized data sharing

### 7. Narrator Pattern → Plain Language Reports

**Current:** LLM-synthesized or template-based reports.
**Upgrade:** Apply Sovereign's narrator pattern for reports accessible to
non-investigators (journalists, community members, board members).

"We traced Meridian Holdings through three offshore jurisdictions.
The ownership chain goes: Meridian → a Cayman Islands shell company →
a trust in Jersey → a beneficial owner who also sits on the board of
a sanctioned entity. Think of it like nesting dolls — each layer is
designed to make the real owner harder to find."

---

## Implementation Priority

1. **Coordinator Mode for parallel investigation** — highest impact on speed
2. **Investigation skills as markdown** — formalizes and shares workflows
3. **Hook-based forensic audit** — richer evidence capture
4. **autoDream for persistent intelligence** — accumulates across sessions
5. **Narrator for accessible reports** — broadens audience

---

*"The name Emet (אמת) is Hebrew for truth." — And truth deserves the best tools.*
