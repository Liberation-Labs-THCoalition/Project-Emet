"""Investigation session — tracks state across agent turns.

An investigation session accumulates:
  - FtM entities discovered
  - Relationships found
  - Leads to follow
  - Tools used and their results
  - The narrative thread of reasoning

This is the working memory of an investigation.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """A single investigative finding."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    source: str = ""           # Which tool/step produced this
    summary: str = ""          # Human-readable summary
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0    # 0-1
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lead:
    """An investigative lead to follow up."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    priority: float = 0.5      # 0-1, higher = more urgent
    source_finding: str = ""   # Finding ID that generated this lead
    query: str = ""            # Suggested query to follow up
    tool: str = ""             # Suggested tool to use
    status: str = "open"       # open, investigating, resolved, dead_end
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Session:
    """Investigation session — the working memory of an agent run.

    Tracks everything discovered during an investigation and provides
    the accumulated context for the agent's next decision.
    """

    def __init__(self, goal: str, session_id: str = "") -> None:
        self.id = session_id or uuid.uuid4().hex[:12]
        self.goal = goal
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.findings: list[Finding] = []
        self.leads: list[Lead] = []
        self.entities: dict[str, dict[str, Any]] = {}  # id → entity
        self.tool_history: list[dict[str, Any]] = []
        self.reasoning_trace: list[str] = []
        self.turn_count: int = 0
        # Set by agent loop after investigation
        self._investigation_graph: Any = None
        self._safety_audit: dict[str, Any] = {}

    def add_finding(self, finding: Finding) -> None:
        """Record a finding and index its entities."""
        self.findings.append(finding)
        for entity in finding.entities:
            eid = entity.get("id", "")
            if eid:
                if eid in self.entities:
                    # Merge properties
                    existing = self.entities[eid]
                    for k, v in entity.get("properties", {}).items():
                        existing_vals = existing.get("properties", {}).get(k, [])
                        new_vals = [x for x in v if x not in existing_vals]
                        if new_vals:
                            existing.setdefault("properties", {}).setdefault(k, []).extend(new_vals)
                else:
                    self.entities[eid] = entity

    def add_lead(self, lead: Lead) -> None:
        """Add an investigative lead to follow."""
        self.leads.append(lead)
        logger.info("New lead [%s]: %s", lead.priority, lead.description)

    def get_open_leads(self) -> list[Lead]:
        """Get leads sorted by priority (highest first)."""
        return sorted(
            [l for l in self.leads if l.status == "open"],
            key=lambda l: l.priority,
            reverse=True,
        )

    def resolve_lead(self, lead_id: str, status: str = "resolved") -> None:
        """Mark a lead as resolved or dead end."""
        for lead in self.leads:
            if lead.id == lead_id:
                lead.status = status
                return

    def record_tool_use(
        self, tool: str, args: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Record a tool invocation."""
        self.tool_history.append({
            "tool": tool,
            "args": args,
            "result_summary": _summarize_result(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_reasoning(self, thought: str) -> None:
        """Record a reasoning step."""
        self.reasoning_trace.append(thought)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def context_for_llm(self, max_chars: int = 4000) -> str:
        """Build context string for LLM decision-making.

        Summarizes the investigation state so the LLM can decide
        what to do next.
        """
        parts = [
            f"INVESTIGATION GOAL: {self.goal}",
            f"TURN: {self.turn_count}",
            f"ENTITIES FOUND: {self.entity_count}",
            f"FINDINGS: {self.finding_count}",
        ]

        # Recent findings
        if self.findings:
            parts.append("\nRECENT FINDINGS:")
            for f in self.findings[-5:]:
                parts.append(f"  - [{f.source}] {f.summary}")

        # Open leads
        open_leads = self.get_open_leads()
        if open_leads:
            parts.append(f"\nOPEN LEADS ({len(open_leads)}):")
            for l in open_leads[:5]:
                parts.append(f"  - [{l.priority:.1f}] {l.description}")
                if l.tool:
                    parts.append(f"    Suggested: {l.tool}({l.query})")

        # Key entities
        if self.entities:
            parts.append(f"\nKEY ENTITIES ({len(self.entities)}):")
            # Show most-referenced entities
            for eid, entity in list(self.entities.items())[:10]:
                schema = entity.get("schema", "?")
                names = entity.get("properties", {}).get("name", [])
                name = names[0] if names else eid[:12]
                parts.append(f"  - [{schema}] {name}")

        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars - 20] + "\n... (truncated)"
        return text

    def summary(self) -> dict[str, Any]:
        """Machine-readable investigation summary."""
        return {
            "session_id": self.id,
            "goal": self.goal,
            "started_at": self.started_at,
            "turns": self.turn_count,
            "entity_count": self.entity_count,
            "finding_count": self.finding_count,
            "leads_open": len(self.get_open_leads()),
            "leads_total": len(self.leads),
            "tools_used": len(self.tool_history),
            "unique_tools": list({t["tool"] for t in self.tool_history}),
        }


def _summarize_result(result: dict[str, Any]) -> str:
    """Create a brief summary of a tool result."""
    if "result_count" in result:
        return f"{result['result_count']} results"
    if "entity_count" in result:
        return f"{result['entity_count']} entities"
    if "article_count" in result:
        return f"{result['article_count']} articles"
    if "error" in result:
        return f"error: {result['error']}"
    return f"{len(result)} keys"
