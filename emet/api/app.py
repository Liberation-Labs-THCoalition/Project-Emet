"""Emet — FastAPI application factory.

Usage:
    uvicorn emet.api.app:create_app --factory --reload --port 8000

Or for production:
    uvicorn emet.api.app:app --host 0.0.0.0 --port 8000 --workers 4
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from emet import __version__

logger = logging.getLogger("emet.api")


class InvestigationRequest(BaseModel):
    chip: str
    intent: str
    parameters: dict[str, Any] = {}
    investigation_id: str = "default"
    user_id: str = "anonymous"
    collection_ids: list[str] = []
    hypothesis: str = ""


class RouteRequest(BaseModel):
    message: str


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Emet",
        description="Investigative journalism agentic framework",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow local dev frontends
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import and mount route modules
    from emet.api.routes.health import router as health_router
    app.include_router(health_router)

    # Only mount DB-dependent routes if we can import them
    try:
        from emet.api.routes.agent import router as agent_router
        app.include_router(agent_router)
    except Exception as e:
        logger.warning("Agent routes not loaded (missing DB?): %s", e)

    try:
        from emet.api.routes.config import router as config_router
        app.include_router(config_router)
    except Exception as e:
        logger.warning("Config routes not loaded: %s", e)

    try:
        from emet.api.routes.memory import router as memory_router
        app.include_router(memory_router)
    except Exception as e:
        logger.warning("Memory routes not loaded: %s", e)

    # Skill chip listing endpoint (always available)
    @app.get("/api/skills")
    async def list_skills():
        """List all registered investigation skill chips."""
        from emet.skills import list_chips
        return {"skills": list_chips()}

    # Investigation endpoint (direct skill chip access)
    @app.post("/api/investigate")
    async def investigate(req: InvestigationRequest):
        """Execute a skill chip directly."""
        from emet.skills import get_chip
        from emet.skills.base import SkillContext, SkillRequest

        try:
            chip = get_chip(req.chip)
        except KeyError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(e))

        ctx = SkillContext(
            investigation_id=req.investigation_id,
            user_id=req.user_id,
            collection_ids=req.collection_ids,
            hypothesis=req.hypothesis,
        )
        skill_req = SkillRequest(intent=req.intent, parameters=req.parameters)
        response = await chip.handle(skill_req, ctx)

        return {
            "success": response.success,
            "content": response.content,
            "data": response.data,
            "produced_entities": response.produced_entities,
            "suggestions": response.suggestions,
            "requires_consensus": response.requires_consensus,
            "consensus_action": response.consensus_action,
            "result_confidence": response.result_confidence,
        }

    # Orchestrator routing endpoint
    @app.post("/api/route")
    async def route_message(req: RouteRequest):
        """Classify a message and return routing decision."""
        from emet.cognition.orchestrator import Orchestrator
        orch = Orchestrator()
        decision = await orch.classify_request(req.message)
        return {
            "skill_domain": decision.skill_domain,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "model_tier": decision.model_tier.value,
        }

    @app.on_event("startup")
    async def startup():
        logger.info("Emet v%s starting up", __version__)

    return app


# Default app instance for `uvicorn emet.api.app:app`
app = create_app()
