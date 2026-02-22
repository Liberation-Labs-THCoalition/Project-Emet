"""Investigation persistence — save and load sessions.

Investigations can be saved mid-flight and resumed later, or
archived for audit and review.

    from emet.agent.persistence import save_session, load_session

    save_session(session, "investigations/acme-2026.json")
    session = load_session("investigations/acme-2026.json")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from emet.agent.session import Session, Finding, Lead

logger = logging.getLogger(__name__)


def save_session(session: Session, path: str | Path) -> Path:
    """Serialize a session to JSON.

    Saves everything: findings, leads, entities, tool history,
    reasoning trace. Can be loaded back with load_session().
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": 1,
        "session_id": session.id,
        "goal": session.goal,
        "started_at": session.started_at,
        "turn_count": session.turn_count,
        "findings": [
            {
                "id": f.id,
                "source": f.source,
                "summary": f.summary,
                "entities": f.entities,
                "relationships": f.relationships,
                "confidence": f.confidence,
                "timestamp": f.timestamp,
                "raw_data": f.raw_data,
            }
            for f in session.findings
        ],
        "leads": [
            {
                "id": l.id,
                "description": l.description,
                "priority": l.priority,
                "source_finding": l.source_finding,
                "query": l.query,
                "tool": l.tool,
                "status": l.status,
                "timestamp": l.timestamp,
            }
            for l in session.leads
        ],
        "entities": session.entities,
        "tool_history": session.tool_history,
        "reasoning_trace": session.reasoning_trace,
    }

    with open(path, "w") as fp:
        json.dump(data, fp, indent=2, default=str)

    logger.info("Session %s saved to %s", session.id, path)
    return path


def load_session(path: str | Path) -> Session:
    """Load a session from JSON.

    Returns a fully-hydrated Session that can be resumed or inspected.
    """
    path = Path(path)
    with open(path) as fp:
        data = json.load(fp)

    session = Session(
        goal=data["goal"],
        session_id=data.get("session_id", ""),
    )
    session.started_at = data.get("started_at", session.started_at)
    session.turn_count = data.get("turn_count", 0)

    # Restore findings
    for fd in data.get("findings", []):
        finding = Finding(
            id=fd.get("id", ""),
            source=fd.get("source", ""),
            summary=fd.get("summary", ""),
            entities=fd.get("entities", []),
            relationships=fd.get("relationships", []),
            confidence=fd.get("confidence", 0.0),
            timestamp=fd.get("timestamp", ""),
            raw_data=fd.get("raw_data", {}),
        )
        session.findings.append(finding)
        # Re-index entities
        for entity in finding.entities:
            eid = entity.get("id", "")
            if eid:
                session.entities[eid] = entity

    # Restore leads
    for ld in data.get("leads", []):
        session.leads.append(Lead(
            id=ld.get("id", ""),
            description=ld.get("description", ""),
            priority=ld.get("priority", 0.5),
            source_finding=ld.get("source_finding", ""),
            query=ld.get("query", ""),
            tool=ld.get("tool", ""),
            status=ld.get("status", "open"),
            timestamp=ld.get("timestamp", ""),
        ))

    # Restore entities (may include ones not in findings)
    for eid, entity in data.get("entities", {}).items():
        if eid not in session.entities:
            session.entities[eid] = entity

    session.tool_history = data.get("tool_history", [])
    session.reasoning_trace = data.get("reasoning_trace", [])

    logger.info("Session %s loaded from %s", session.id, path)
    return session


def list_sessions(directory: str | Path = "investigations") -> list[dict[str, Any]]:
    """List saved investigation sessions in a directory."""
    directory = Path(directory)
    if not directory.exists():
        return []

    sessions = []
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path) as fp:
                data = json.load(fp)
            sessions.append({
                "path": str(path),
                "session_id": data.get("session_id", ""),
                "goal": data.get("goal", ""),
                "started_at": data.get("started_at", ""),
                "turns": data.get("turn_count", 0),
                "entities": len(data.get("entities", {})),
                "findings": len(data.get("findings", [])),
            })
        except Exception:
            continue

    return sessions
