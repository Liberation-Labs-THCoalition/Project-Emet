"""Emet Agent — the agentic investigation runtime.

This is the nervous system that wires cognition, skills, tools,
and the FtM data spine into an actual running investigator.

    from emet.agent import InvestigationAgent
    agent = InvestigationAgent()
    result = await agent.investigate("Acme Corp shell companies in Panama")

Safety harness wraps every tool call:

    from emet.agent import SafetyHarness
    harness = SafetyHarness.from_defaults()

Persistence:

    from emet.agent import save_session, load_session
    save_session(session, "investigations/acme.json")
"""

from emet.agent.loop import InvestigationAgent, AgentConfig
from emet.agent.session import Session, Finding
from emet.agent.safety_harness import SafetyHarness
from emet.agent.persistence import save_session, load_session

__all__ = [
    "InvestigationAgent",
    "AgentConfig",
    "Session",
    "Finding",
    "SafetyHarness",
    "save_session",
    "load_session",
]
