"""Emet HTTP API — FastAPI application factory.

Creates the FastAPI app with all investigation and management routes.
This is the HTTP interface to Emet; the MCP interface is separate
(emet.mcp.server).

Usage:
    from emet.api.app import create_app
    app = create_app()

    # Or from CLI:
    emet serve --http --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from emet import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup/shutdown hooks."""
    logger.info("Emet API starting (version %s)", __version__)
    yield
    logger.info("Emet API shutting down")


def create_app(
    cors_origins: list[str] | None = None,
    include_docs: bool = True,
) -> FastAPI:
    """Create the FastAPI application with all routes.

    Args:
        cors_origins: Allowed CORS origins. Defaults to ["*"] for development.
        include_docs: Whether to include /docs and /redoc. Default True.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Emet",
        description="Investigative journalism agent — REST API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if include_docs else None,
        redoc_url="/redoc" if include_docs else None,
    )

    # CORS
    origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Register routes ---
    from emet.api.routes.health import router as health_router
    app.include_router(health_router)

    from emet.api.routes.investigation import router as investigation_router
    app.include_router(investigation_router)

    # WebSocket for live investigation streaming
    from emet.api.routes.ws_investigation import router as ws_router
    app.include_router(ws_router)

    # Config routes (settings, capabilities)
    try:
        from emet.api.routes.config import router as config_router
        app.include_router(config_router)
    except Exception:
        logger.debug("Config routes not available")

    # Memory routes (temporal memory)
    try:
        from emet.api.routes.memory import router as memory_router
        app.include_router(memory_router)
    except Exception:
        logger.debug("Memory routes not available")

    # Agent routes (legacy chat endpoint)
    try:
        from emet.api.routes.agent import router as agent_router
        app.include_router(agent_router)
    except Exception:
        logger.debug("Agent routes not available (DB required)")

    logger.info(
        "Emet API created with %d routes",
        len(app.routes),
    )

    return app
