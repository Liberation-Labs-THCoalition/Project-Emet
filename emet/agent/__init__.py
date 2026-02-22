"""Emet Agent — the agentic investigation runtime.

This is the nervous system that wires cognition, skills, tools,
and the FtM data spine into an actual running investigator.

    from emet.agent import InvestigationAgent
    agent = InvestigationAgent()
    result = await agent.investigate("Acme Corp shell companies in Panama")
"""

from emet.agent.loop import InvestigationAgent, AgentConfig
from emet.agent.session import Session, Finding

__all__ = ["InvestigationAgent", "AgentConfig", "Session", "Finding"]
