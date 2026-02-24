"""WebSocket endpoint for live investigation progress.

Clients connect to /ws/investigations/{id} and receive real-time
updates as the investigation progresses: tool calls, findings,
leads discovered, and the final report.

Protocol (server → client JSON messages):
    {"type": "started", "goal": "...", "id": "..."}
    {"type": "turn", "turn": 3, "tool": "search_entities", "reasoning": "..."}
    {"type": "finding", "source": "...", "summary": "...", "confidence": 0.8}
    {"type": "lead", "description": "...", "priority": 0.9}
    {"type": "progress", "message": "..."}
    {"type": "completed", "summary": {...}}
    {"type": "error", "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from emet.agent import InvestigationAgent, AgentConfig
from emet.agent.session import Session, Finding, Lead

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Active WebSocket connections per investigation
_connections: dict[str, list[WebSocket]] = {}


async def _broadcast(inv_id: str, message: dict[str, Any]) -> None:
    """Send a message to all WebSocket clients watching an investigation."""
    connections = _connections.get(inv_id, [])
    dead: list[WebSocket] = []

    for ws in connections:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)

    # Clean up dead connections
    for ws in dead:
        connections.remove(ws)


@router.websocket("/ws/investigations/{inv_id}")
async def investigation_ws(websocket: WebSocket, inv_id: str) -> None:
    """WebSocket endpoint for live investigation updates.

    Connect to receive real-time progress for an investigation.
    Send {"action": "start", "goal": "..."} to begin a new investigation,
    or just connect to watch an already-running one.
    """
    await websocket.accept()

    # Register connection
    if inv_id not in _connections:
        _connections[inv_id] = []
    _connections[inv_id].append(websocket)

    try:
        while True:
            # Wait for client messages
            data = await websocket.receive_json()
            action = data.get("action", "")

            if action == "start":
                goal = data.get("goal", "")
                if not goal:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Missing 'goal' field",
                    })
                    continue

                # Run investigation with progress streaming
                asyncio.create_task(
                    _run_streaming_investigation(inv_id, goal, data)
                )

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected: %s", inv_id)
    except Exception as exc:
        logger.debug("WebSocket error: %s", exc)
    finally:
        # Unregister
        conns = _connections.get(inv_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            _connections.pop(inv_id, None)


async def _run_streaming_investigation(
    inv_id: str,
    goal: str,
    options: dict[str, Any],
) -> None:
    """Run an investigation and stream progress via WebSocket."""
    max_turns = options.get("max_turns", 15)
    llm_provider = options.get("llm_provider", "stub")
    demo = options.get("demo_mode", False) or llm_provider == "stub"

    await _broadcast(inv_id, {
        "type": "started",
        "id": inv_id,
        "goal": goal,
    })

    try:
        config = AgentConfig(
            max_turns=max_turns,
            llm_provider=llm_provider,
            enable_safety=True,
            generate_graph=True,
            demo_mode=demo,
        )

        agent = InvestigationAgent(config=config)

        # We can't easily hook into the agent loop mid-flight yet,
        # so we run the full investigation and stream the results
        # from the session afterward. For true streaming, the agent
        # loop would need callback hooks (future enhancement).
        session = await agent.investigate(goal)

        # Stream findings
        for finding in session.findings:
            await _broadcast(inv_id, {
                "type": "finding",
                "source": finding.source,
                "summary": finding.summary,
                "confidence": finding.confidence,
            })

        # Stream open leads
        for lead in session.get_open_leads():
            await _broadcast(inv_id, {
                "type": "lead",
                "description": lead.description,
                "priority": lead.priority,
            })

        # Stream tool history as turns
        for i, tool_call in enumerate(session.tool_history):
            await _broadcast(inv_id, {
                "type": "turn",
                "turn": i + 1,
                "tool": tool_call.get("tool", "unknown"),
                "reasoning": tool_call.get("reasoning", ""),
            })

        # Final summary
        summary = session.summary()
        await _broadcast(inv_id, {
            "type": "completed",
            "summary": summary,
            "report": session.report,
        })

    except Exception as exc:
        logger.exception("Streaming investigation failed: %s", inv_id)
        await _broadcast(inv_id, {
            "type": "error",
            "message": str(exc),
        })
