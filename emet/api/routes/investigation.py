"""Investigation API — trigger and monitor investigations over HTTP.

Endpoints:
    POST /api/investigations        Start an investigation
    GET  /api/investigations/{id}   Get investigation status/results
    GET  /api/investigations        List recent investigations
    POST /api/investigations/{id}/export  Export scrubbed report

This is the bridge between external systems (adapters, CI/CD, cron)
and the InvestigationAgent. Investigations run asynchronously via
background tasks.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from emet.agent import InvestigationAgent, AgentConfig
from emet.agent.session import Session
from emet.agent.safety_harness import SafetyHarness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

# In-memory investigation store (production: replace with DB/Redis)
_investigations: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class InvestigationRequest(BaseModel):
    """Request to start a new investigation."""
    goal: str = Field(..., description="Investigation goal in natural language")
    max_turns: int = Field(15, ge=1, le=100, description="Max agent turns")
    llm_provider: str = Field("stub", description="LLM provider (stub, ollama, anthropic)")
    auto_sanctions: bool = Field(True, description="Auto-screen against sanctions")
    auto_news: bool = Field(True, description="Auto-check news")
    dry_run: bool = Field(False, description="Plan only, don't execute tools")


class InvestigationStatus(BaseModel):
    """Investigation status and results."""
    id: str
    goal: str
    status: str  # "running", "completed", "failed"
    started_at: str
    completed_at: Optional[str] = None
    turns: int = 0
    entity_count: int = 0
    finding_count: int = 0
    leads_open: int = 0
    leads_total: int = 0
    unique_tools: list[str] = []
    findings: list[dict[str, Any]] = []
    reasoning_trace: list[str] = []
    safety_audit: dict[str, Any] = {}
    error: Optional[str] = None


class InvestigationListItem(BaseModel):
    """Summary for investigation list."""
    id: str
    goal: str
    status: str
    started_at: str
    entity_count: int = 0
    finding_count: int = 0


class ExportResponse(BaseModel):
    """Scrubbed investigation export."""
    id: str
    goal: str
    report: dict[str, Any]
    pii_items_scrubbed: int = 0


# ---------------------------------------------------------------------------
# POST /api/investigations — start investigation
# ---------------------------------------------------------------------------

@router.post("", response_model=InvestigationStatus, status_code=202)
async def start_investigation(
    req: InvestigationRequest,
    background_tasks: BackgroundTasks,
) -> InvestigationStatus:
    """Start an asynchronous investigation.

    Returns immediately with status 202 and an investigation ID.
    Poll GET /api/investigations/{id} for results.
    """
    inv_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    _investigations[inv_id] = {
        "id": inv_id,
        "goal": req.goal,
        "status": "running",
        "started_at": now,
        "completed_at": None,
        "config": req.model_dump(),
        "session": None,
        "error": None,
    }

    background_tasks.add_task(_run_investigation, inv_id, req)

    return InvestigationStatus(
        id=inv_id,
        goal=req.goal,
        status="running",
        started_at=now,
    )


async def _run_investigation(inv_id: str, req: InvestigationRequest) -> None:
    """Background task that runs the actual investigation."""
    try:
        config = AgentConfig(
            max_turns=req.max_turns,
            llm_provider=req.llm_provider,
            auto_sanctions_screen=req.auto_sanctions,
            auto_news_check=req.auto_news,
            enable_safety=True,
            generate_graph=True,
        )

        agent = InvestigationAgent(config=config)
        session = await agent.investigate(req.goal)

        summary = session.summary()
        _investigations[inv_id].update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "session": session,
            "summary": summary,
        })

        logger.info(
            "Investigation %s completed: %d entities, %d findings",
            inv_id, summary["entity_count"], summary["finding_count"],
        )

    except Exception as exc:
        logger.exception("Investigation %s failed", inv_id)
        _investigations[inv_id].update({
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        })


# ---------------------------------------------------------------------------
# GET /api/investigations/{id} — get status/results
# ---------------------------------------------------------------------------

@router.get("/{inv_id}", response_model=InvestigationStatus)
async def get_investigation(inv_id: str) -> InvestigationStatus:
    """Get investigation status and results."""
    inv = _investigations.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Investigation {inv_id} not found")

    session: Session | None = inv.get("session")
    summary = inv.get("summary", {})

    findings = []
    reasoning = []
    safety_audit = {}

    if session is not None:
        findings = [
            {
                "source": f.source,
                "summary": f.summary,
                "confidence": f.confidence,
            }
            for f in session.findings
        ]
        reasoning = session.reasoning_trace
        safety_audit = getattr(session, "_safety_audit", {})

    return InvestigationStatus(
        id=inv_id,
        goal=inv["goal"],
        status=inv["status"],
        started_at=inv["started_at"],
        completed_at=inv.get("completed_at"),
        turns=summary.get("turns", 0),
        entity_count=summary.get("entity_count", 0),
        finding_count=summary.get("finding_count", 0),
        leads_open=summary.get("leads_open", 0),
        leads_total=summary.get("leads_total", 0),
        unique_tools=summary.get("unique_tools", []),
        findings=findings,
        reasoning_trace=reasoning,
        safety_audit=safety_audit,
        error=inv.get("error"),
    )


# ---------------------------------------------------------------------------
# GET /api/investigations — list recent
# ---------------------------------------------------------------------------

@router.get("", response_model=list[InvestigationListItem])
async def list_investigations(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status"),
) -> list[InvestigationListItem]:
    """List recent investigations."""
    items = sorted(
        _investigations.values(),
        key=lambda x: x["started_at"],
        reverse=True,
    )

    if status:
        items = [i for i in items if i["status"] == status]

    results = []
    for inv in items[:limit]:
        summary = inv.get("summary", {})
        results.append(InvestigationListItem(
            id=inv["id"],
            goal=inv["goal"],
            status=inv["status"],
            started_at=inv["started_at"],
            entity_count=summary.get("entity_count", 0),
            finding_count=summary.get("finding_count", 0),
        ))

    return results


# ---------------------------------------------------------------------------
# POST /api/investigations/{id}/export — scrubbed export
# ---------------------------------------------------------------------------

@router.post("/{inv_id}/export", response_model=ExportResponse)
async def export_investigation(inv_id: str) -> ExportResponse:
    """Export investigation with PII scrubbed for publication.

    This is the publication boundary — all PII is redacted from the
    exported data. Internal session data remains unmodified.
    """
    inv = _investigations.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Investigation {inv_id} not found")

    if inv["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Investigation {inv_id} is {inv['status']}, not completed",
        )

    session: Session = inv["session"]

    # Build raw report
    raw_report = {
        "goal": session.goal,
        "summary": inv.get("summary", {}),
        "findings": [
            {"source": f.source, "summary": f.summary, "confidence": f.confidence}
            for f in session.findings
        ],
        "entities": list(session.entities.values()),
        "reasoning": session.reasoning_trace,
    }

    # Publication boundary: scrub PII
    harness = SafetyHarness.from_defaults()
    scrubbed = harness.scrub_dict_for_publication(raw_report, "api_export")
    pub_audit = harness.audit_summary()
    pii_count = pub_audit.get("publication_scrubs", 0)

    return ExportResponse(
        id=inv_id,
        goal=session.goal,
        report=scrubbed,
        pii_items_scrubbed=pii_count,
    )
