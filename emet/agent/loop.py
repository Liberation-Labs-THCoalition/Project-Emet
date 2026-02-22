"""Agent loop — the investigate-reason-act cycle.

The core agentic runtime. Takes an investigation goal, iteratively
uses tools, accumulates findings, follows leads, and decides when
to stop.

Design:
  - Simple loop, not a DAG or planning framework
  - LLM decides next action from investigation context
  - One tool call per turn
  - Stops on budget exhaustion or LLM "conclude" signal
  - Falls back to heuristic routing if no LLM available

    agent = InvestigationAgent()
    result = await agent.investigate("Acme Corp corruption in Panama")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from emet.agent.session import Session, Finding, Lead
from emet.agent.safety_harness import SafetyHarness
from emet.mcp.tools import EmetToolExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Available tools the agent can call
# ---------------------------------------------------------------------------

AGENT_TOOLS = {
    "search_entities": {
        "description": "Search for entities (people, companies, sanctions) across multiple sources",
        "params": ["query", "entity_type", "sources"],
    },
    "osint_recon": {
        "description": "OSINT reconnaissance on a target (domain, email, IP)",
        "params": ["target", "scan_type"],
    },
    "analyze_graph": {
        "description": "Analyze network graph for hidden connections, brokers, communities",
        "params": ["entities", "analysis_type"],
    },
    "trace_ownership": {
        "description": "Trace corporate ownership chains",
        "params": ["entity_name", "max_depth"],
    },
    "screen_sanctions": {
        "description": "Screen entity against sanctions and PEP lists",
        "params": ["entity_name", "entity_type", "threshold"],
    },
    "investigate_blockchain": {
        "description": "Investigate blockchain address transactions and flows",
        "params": ["address", "chain"],
    },
    "monitor_entity": {
        "description": "Monitor real-time news for an entity via GDELT",
        "params": ["entity_name", "timespan"],
    },
    "generate_report": {
        "description": "Generate investigation report from accumulated findings",
        "params": ["title", "format"],
    },
    "conclude": {
        "description": "End the investigation and compile results",
        "params": [],
    },
}


# ---------------------------------------------------------------------------
# System prompt for LLM-powered decision making
# ---------------------------------------------------------------------------

INVESTIGATION_SYSTEM_PROMPT = """You are an investigative journalist's AI research assistant. Your job is to \
direct an investigation by choosing which tools to call next, based on the current state of evidence.

PRINCIPLES:
- Follow the money. Corporate ownership chains and financial flows reveal hidden connections.
- Verify through multiple sources. One data point is a hint; corroboration is evidence.
- Pursue the highest-value leads first. Sanctions hits and ownership anomalies outrank general searches.
- Know when to stop. Conclude when findings answer the goal or when remaining leads are low-priority.
- Never fabricate. If a tool returns no data, note the gap — don't invent results.

STRATEGY:
1. Broad entity search first to identify key players
2. Sanctions/PEP screening for flagged entities
3. Ownership tracing for corporate structures
4. OSINT for digital footprints when warranted
5. Blockchain investigation only when crypto addresses surface
6. Conclude and synthesize when the picture is clear

You respond with ONLY a single JSON object representing the next action. No explanations outside the JSON."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    """Agent configuration."""
    max_turns: int = 15            # Budget per investigation
    min_confidence: float = 0.3    # Minimum to pursue a lead
    auto_sanctions_screen: bool = True  # Always screen found entities
    auto_news_check: bool = True   # Always check GDELT for targets
    llm_provider: str = "stub"     # LLM backend (stub, ollama, anthropic)
    verbose: bool = True           # Log reasoning
    # Safety
    enable_safety: bool = True     # Enable full safety harness
    enable_pii_redaction: bool = True   # Scrub PII from outputs
    enable_shield: bool = True     # Budget/rate/circuit breaker
    # Persistence
    persist_path: str = ""         # Auto-save session to this path
    # Visualization
    generate_graph: bool = True    # Generate Cytoscape graph at conclusion


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class InvestigationAgent:
    """The agentic investigator.

    Takes a goal, iteratively uses tools, and accumulates findings
    into a coherent investigation session.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig()
        self._executor = EmetToolExecutor()
        # Safety harness
        if self._config.enable_safety:
            self._harness = SafetyHarness.from_defaults()
        else:
            self._harness = SafetyHarness.disabled()
        # LLM client — created once, reused across turns
        self._llm_client: Any = None  # Lazy-initialized
        self._cost_tracker: Any = None

    async def investigate(self, goal: str) -> Session:
        """Run an investigation from a natural-language goal.

        Returns the completed Session with all findings, entities,
        leads, and reasoning trace.
        """
        session = Session(goal=goal)
        session.record_reasoning(f"Starting investigation: {goal}")

        # Phase 1: Initial search
        await self._initial_search(session)

        # Phase 2: Iterative investigation loop
        while session.turn_count < self._config.max_turns:
            session.turn_count += 1

            action = await self._decide_next_action(session)

            if action["tool"] == "conclude":
                session.record_reasoning("Concluding investigation.")
                break

            session.record_reasoning(
                f"Turn {session.turn_count}: {action['reasoning']}"
            )

            # --- Safety: pre-check ---
            verdict = self._harness.pre_check(
                tool=action["tool"],
                args=action.get("args", {}),
            )
            if verdict.blocked:
                session.record_reasoning(
                    f"BLOCKED by safety harness: {verdict.reason}"
                )
                # Mark lead as dead end if it was lead-following
                lead_id = action.get("lead_id")
                if lead_id:
                    session.resolve_lead(lead_id, "blocked")
                continue

            result = await self._execute_action(session, action)

            await self._process_result(session, action, result)

            # Check if we've exhausted leads
            if not session.get_open_leads() and session.turn_count >= 3:
                session.record_reasoning(
                    "No open leads remaining. Concluding."
                )
                break

        # Phase 3: Generate report
        await self._generate_report(session)

        # Phase 4: Generate investigation graph
        if self._config.generate_graph:
            self._generate_investigation_graph(session)

        # Phase 5: Persist session
        if self._config.persist_path:
            from emet.agent.persistence import save_session
            save_session(session, self._config.persist_path)

        # Attach safety audit to session
        session._safety_audit = self._harness.audit_summary()

        return session

    async def _initial_search(self, session: Session) -> None:
        """Phase 1: Cast the net — search entities, check news."""
        goal = session.goal

        # Entity search
        session.record_reasoning(f"Initial entity search for: {goal}")
        try:
            result = await self._executor.execute(
                "search_entities",
                {"query": goal, "entity_type": "Any", "limit": 20},
            )
            session.record_tool_use("search_entities", {"query": goal}, result)

            entities = result.get("entities", [])
            if entities:
                finding = Finding(
                    source="search_entities",
                    summary=f"Found {len(entities)} entities matching '{goal}'",
                    entities=entities,
                    confidence=0.7,
                )
                session.add_finding(finding)

                # Generate leads from found entities
                for entity in entities[:5]:
                    props = entity.get("properties", {})
                    names = props.get("name", [])
                    schema = entity.get("schema", "")
                    if names:
                        name = names[0]
                        # Sanctions screening lead
                        if self._config.auto_sanctions_screen:
                            session.add_lead(Lead(
                                description=f"Screen {name} against sanctions",
                                priority=0.8,
                                source_finding=finding.id,
                                query=name,
                                tool="screen_sanctions",
                            ))
                        # Ownership tracing for companies
                        if schema in ("Company", "Organization", "LegalEntity"):
                            session.add_lead(Lead(
                                description=f"Trace ownership of {name}",
                                priority=0.7,
                                source_finding=finding.id,
                                query=name,
                                tool="trace_ownership",
                            ))

        except Exception as exc:
            session.record_reasoning(f"Initial search failed: {exc}")

        # News monitoring
        if self._config.auto_news_check:
            try:
                result = await self._executor.execute(
                    "monitor_entity",
                    {"entity_name": goal, "timespan": "7d"},
                )
                session.record_tool_use("monitor_entity", {"entity_name": goal}, result)

                articles = result.get("article_count", 0)
                if articles:
                    session.add_finding(Finding(
                        source="monitor_entity",
                        summary=f"Found {articles} recent news articles about '{goal}'",
                        confidence=0.5,
                        raw_data=result,
                    ))
            except Exception as exc:
                session.record_reasoning(f"News check failed: {exc}")

    async def _decide_next_action(
        self, session: Session
    ) -> dict[str, Any]:
        """Decide what to do next.

        Uses LLM if available, falls back to lead-following heuristic.
        """
        # Try LLM decision
        action = await self._llm_decide(session)
        if action:
            return action

        # Heuristic fallback: follow highest-priority open lead
        return self._heuristic_decide(session)

    def _get_llm_client(self) -> Any:
        """Get or create the cached LLM client.

        Returns None if the provider is unavailable (e.g. no API key).
        The client is created once and reused for the duration of the
        investigation, maintaining cost tracking across turns.
        """
        if self._llm_client is not None:
            return self._llm_client

        try:
            from emet.cognition.llm_factory import create_llm_client_sync
            from emet.cognition.model_router import CostTracker

            self._cost_tracker = CostTracker()
            self._llm_client = create_llm_client_sync(
                provider=self._config.llm_provider,
                cost_tracker=self._cost_tracker,
            )
            return self._llm_client
        except Exception as exc:
            logger.debug("Cannot create LLM client: %s", exc)
            return None

    async def _llm_decide(self, session: Session) -> dict[str, Any] | None:
        """Ask the LLM what to do next.

        Uses the investigation context and available tools to prompt the
        LLM for a structured JSON action. Returns None if the LLM is
        unavailable or the response can't be parsed, triggering heuristic
        fallback.
        """
        client = self._get_llm_client()
        if client is None:
            return None

        context = session.context_for_llm()
        tools_desc = "\n".join(
            f"  - {name}: {info['description']}"
            f"\n    Parameters: {', '.join(info['params'])}"
            for name, info in AGENT_TOOLS.items()
        )

        system = INVESTIGATION_SYSTEM_PROMPT

        prompt = f"""{context}

AVAILABLE TOOLS:
{tools_desc}

Based on the investigation state above, decide the SINGLE next action.
Respond with ONLY a JSON object — no markdown, no commentary:
{{"tool": "<tool_name>", "args": {{<relevant_params>}}, "reasoning": "<one sentence why>"}}

Rules:
- Pick the tool that fills the biggest gap in your current knowledge
- If you have open leads, consider following the highest-priority one
- If findings are sufficient to answer the goal, use "conclude"
- Don't repeat the same tool call with the same arguments
- Each tool call costs budget — be efficient"""

        try:
            response = await client.complete(
                prompt,
                system=system,
                max_tokens=300,
                temperature=0.2,  # Low temp for structured decisions
                tier="balanced",
            )
            text = response.text.strip()

            # Parse JSON from response (handles preamble/markdown fences)
            if "```" in text:
                # Strip markdown code fences
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            if "{" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                action = json.loads(json_str)

                # Validate tool name
                tool = action.get("tool", "")
                if tool not in AGENT_TOOLS:
                    logger.debug("LLM suggested unknown tool %r", tool)
                    return None

                # Ensure args is a dict
                if not isinstance(action.get("args"), dict):
                    action["args"] = {}

                logger.info(
                    "LLM decision (turn %d): %s — %s",
                    session.turn_count,
                    action["tool"],
                    action.get("reasoning", "")[:80],
                )
                return action

        except Exception as exc:
            logger.debug("LLM decision failed: %s", exc)

        return None

    def _heuristic_decide(self, session: Session) -> dict[str, Any]:
        """Fallback: follow the highest-priority open lead."""
        leads = session.get_open_leads()

        if not leads:
            return {"tool": "conclude", "args": {}, "reasoning": "No leads remaining"}

        lead = leads[0]
        lead.status = "investigating"

        args: dict[str, Any] = {}
        if lead.tool == "screen_sanctions":
            args = {"entity_name": lead.query, "entity_type": "Any", "threshold": 0.6}
        elif lead.tool == "trace_ownership":
            args = {"entity_name": lead.query, "max_depth": 3}
        elif lead.tool == "osint_recon":
            args = {"target": lead.query, "scan_type": "passive"}
        elif lead.tool == "search_entities":
            args = {"query": lead.query, "entity_type": "Any"}
        elif lead.tool == "investigate_blockchain":
            args = {"address": lead.query, "chain": "ethereum"}
        elif lead.tool == "monitor_entity":
            args = {"entity_name": lead.query, "timespan": "24h"}
        else:
            args = {"query": lead.query}

        return {
            "tool": lead.tool or "search_entities",
            "args": args,
            "reasoning": f"Following lead: {lead.description}",
            "lead_id": lead.id,
        }

    async def _execute_action(
        self,
        session: Session,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call with safety observation (audit-only)."""
        tool = action["tool"]
        args = action.get("args", {})

        try:
            result = await self._executor.execute(tool, args)

            # Safety: report success to circuit breaker
            self._harness.report_tool_success(tool)

            # Safety: observe result (audit-only, no scrubbing)
            # PII and security observations are logged but data is untouched
            result_text = json.dumps(result, default=str)
            if len(result_text) > 10:
                self._harness.post_check(result_text, tool=tool)

            session.record_tool_use(tool, args, result)
            return result
        except Exception as exc:
            # Safety: report failure to circuit breaker
            self._harness.report_tool_failure(tool)

            error = {"error": str(exc), "tool": tool}
            session.record_tool_use(tool, args, error)
            session.record_reasoning(f"Tool {tool} failed: {exc}")
            # Mark lead as dead end if it was a lead-following action
            lead_id = action.get("lead_id")
            if lead_id:
                session.resolve_lead(lead_id, "dead_end")
            return error

    async def _process_result(
        self,
        session: Session,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Process tool result into findings and new leads."""
        tool = action["tool"]
        lead_id = action.get("lead_id")

        if "error" in result:
            return

        # Extract entities from result
        entities = result.get("entities", [])
        result_count = result.get("result_count", len(entities))

        if entities or result_count:
            finding = Finding(
                source=tool,
                summary=_build_finding_summary(tool, action, result),
                entities=entities,
                confidence=_estimate_confidence(result),
                raw_data={k: v for k, v in result.items() if k != "entities"},
            )
            session.add_finding(finding)

            # Generate new leads from results
            self._extract_leads(session, finding, result)

        # Resolve the lead that triggered this action
        if lead_id:
            session.resolve_lead(lead_id, "resolved")

    def _extract_leads(
        self,
        session: Session,
        finding: Finding,
        result: dict[str, Any],
    ) -> None:
        """Extract new investigative leads from a finding."""
        for entity in finding.entities[:3]:
            props = entity.get("properties", {})
            schema = entity.get("schema", "")
            names = props.get("name", [])
            if not names:
                continue
            name = names[0]

            # Don't create duplicate leads
            existing_queries = {l.query.lower() for l in session.leads}
            if name.lower() in existing_queries:
                continue

            # Companies → trace ownership
            if schema in ("Company", "Organization", "LegalEntity"):
                session.add_lead(Lead(
                    description=f"Trace ownership of {name}",
                    priority=0.6,
                    source_finding=finding.id,
                    query=name,
                    tool="trace_ownership",
                ))

            # Crypto addresses → investigate blockchain
            crypto_keys = props.get("publicKey", [])
            for addr in crypto_keys[:1]:
                session.add_lead(Lead(
                    description=f"Investigate crypto address {addr[:20]}...",
                    priority=0.5,
                    source_finding=finding.id,
                    query=addr,
                    tool="investigate_blockchain",
                ))

        # Sanctions matches → high priority
        matches = result.get("matches", [])
        for match in matches[:3]:
            match_name = match.get("name", match.get("entity_name", ""))
            if match_name:
                session.add_lead(Lead(
                    description=f"SANCTIONS HIT: {match_name}",
                    priority=0.95,
                    source_finding=finding.id,
                    query=match_name,
                    tool="search_entities",
                ))

    async def _generate_report(self, session: Session) -> None:
        """Generate final investigation report.

        This is a publication boundary — PII is scrubbed from the
        report output before it's attached to the session.

        When an LLM is available, it synthesizes findings into a
        coherent narrative. Otherwise falls back to the template-based
        generate_report tool.
        """
        try:
            # Try LLM-powered synthesis first
            synthesized = await self._llm_synthesize_report(session)
            if synthesized:
                result = {
                    "report": synthesized,
                    "format": "markdown",
                    "source": "llm_synthesis",
                }
            else:
                # Fallback: template-based report from tool
                entity_summaries = []
                for eid, entity in list(session.entities.items())[:50]:
                    names = entity.get("properties", {}).get("name", [])
                    schema = entity.get("schema", "")
                    entity_summaries.append(f"[{schema}] {names[0] if names else eid}")

                result = await self._executor.execute(
                    "generate_report",
                    {
                        "title": f"Investigation: {session.goal}",
                        "format": "markdown",
                        "entities": list(session.entities.values())[:50],
                    },
                )

            # Publication boundary: scrub PII from report output
            if self._config.enable_pii_redaction:
                result = self._harness.scrub_dict_for_publication(result, "report")

            session.record_tool_use("generate_report", {"title": session.goal}, result)
            session.record_reasoning("Report generated (PII scrubbed for publication).")

            # Record cost summary if LLM was used
            if self._cost_tracker:
                cost_info = self._cost_tracker.summary()
                session.record_reasoning(
                    f"LLM cost: ${cost_info['cumulative']:.4f} "
                    f"({cost_info['call_count']} calls, "
                    f"${cost_info['remaining']:.4f} budget remaining)"
                )

        except Exception as exc:
            session.record_reasoning(f"Report generation failed: {exc}")

    async def _llm_synthesize_report(self, session: Session) -> str | None:
        """Use the LLM to synthesize findings into a narrative report.

        Returns the markdown report text, or None if LLM unavailable.
        """
        client = self._get_llm_client()
        if client is None:
            return None

        # Don't use LLM synthesis for stub provider — it produces canned text
        try:
            from emet.cognition.llm_base import LLMProvider
            if hasattr(client, 'provider') and client.provider == LLMProvider.STUB:
                return None
        except Exception:
            pass

        # Build synthesis prompt from session data
        findings_text = "\n".join(
            f"- [{f.source}] (confidence: {f.confidence:.0%}) {f.summary}"
            for f in session.findings
        )

        entities_text = "\n".join(
            f"- [{entity.get('schema', '?')}] "
            f"{entity.get('properties', {}).get('name', [eid])[0] if entity.get('properties', {}).get('name') else eid}"
            for eid, entity in list(session.entities.items())[:30]
        )

        open_leads = session.get_open_leads()
        leads_text = "\n".join(
            f"- [{l.priority:.0%}] {l.description}"
            for l in open_leads[:10]
        ) if open_leads else "None — all leads resolved."

        prompt = f"""Synthesize the following investigation findings into a clear, structured report.

INVESTIGATION GOAL: {session.goal}

FINDINGS ({session.finding_count}):
{findings_text or "No findings."}

KEY ENTITIES ({session.entity_count}):
{entities_text or "No entities identified."}

OPEN LEADS:
{leads_text}

INVESTIGATION STATS:
- Turns used: {session.turn_count}
- Tools used: {', '.join(set(t['tool'] for t in session.tool_history))}

Write a markdown report with these sections:
## Summary
A 2-3 sentence executive summary of what was found.

## Key Findings
The most important discoveries, with confidence levels.

## Entity Network
Who/what was identified and how they connect.

## Open Questions
What remains unresolved — leads not yet pursued.

## Methodology
Brief note on tools and sources used.

Be factual. Only report what the findings support. Flag low-confidence items explicitly."""

        try:
            response = await client.complete(
                prompt,
                system="You are a report writer for investigative journalists. Write clear, factual, well-structured reports. Never fabricate details beyond what the findings state.",
                max_tokens=2048,
                temperature=0.3,
                tier="balanced",
            )
            report = response.text.strip()
            if len(report) > 100:  # Sanity check
                logger.info(
                    "LLM synthesized report: %d chars, %d input tokens, %d output tokens",
                    len(report), response.input_tokens, response.output_tokens,
                )
                return report
        except Exception as exc:
            logger.debug("LLM report synthesis failed: %s", exc)

        return None

    def _generate_investigation_graph(self, session: Session) -> None:
        """Build a relationship graph from investigation findings.

        Uses emet.graph to create a NetworkX graph of all entities and
        their relationships discovered during the investigation.
        """
        try:
            from emet.graph.engine import GraphEngine

            # Collect all entities across findings
            all_entities = list(session.entities.values())
            if not all_entities:
                session.record_reasoning("Graph: no entities to graph")
                return

            engine = GraphEngine()
            graph_result = engine.build_from_entities(all_entities)

            session._investigation_graph = graph_result
            session.record_reasoning(
                f"Graph: {graph_result.stats.nodes_loaded} nodes, "
                f"{graph_result.stats.edges_loaded} edges"
            )

        except Exception as exc:
            session.record_reasoning(f"Graph generation failed: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_finding_summary(
    tool: str, action: dict[str, Any], result: dict[str, Any]
) -> str:
    """Build a human-readable summary of a tool result."""
    args = action.get("args", {})

    if tool == "search_entities":
        count = result.get("result_count", 0)
        return f"Entity search found {count} results for '{args.get('query', '?')}'"
    elif tool == "screen_sanctions":
        matches = len(result.get("matches", []))
        return f"Sanctions screening: {matches} matches for '{args.get('entity_name', '?')}'"
    elif tool == "trace_ownership":
        depth = result.get("max_depth_reached", 0)
        return f"Ownership trace reached depth {depth} for '{args.get('entity_name', '?')}'"
    elif tool == "osint_recon":
        return f"OSINT recon on '{args.get('target', '?')}'"
    elif tool == "monitor_entity":
        articles = result.get("article_count", 0)
        return f"Found {articles} news articles about '{args.get('entity_name', '?')}'"
    elif tool == "investigate_blockchain":
        txs = len(result.get("transactions", []))
        return f"Blockchain: {txs} transactions for {args.get('address', '?')[:20]}"
    elif tool == "analyze_graph":
        return f"Graph analysis: {result.get('analysis_type', 'network')}"
    else:
        return f"{tool}: completed"


def _estimate_confidence(result: dict[str, Any]) -> float:
    """Rough confidence estimate from result quality."""
    if result.get("matches"):
        return 0.85
    if result.get("result_count", 0) > 0:
        return 0.7
    if result.get("entities"):
        return 0.6
    return 0.4
