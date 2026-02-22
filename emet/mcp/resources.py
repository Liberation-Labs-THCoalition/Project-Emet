"""MCP resource endpoints for investigation state.

Exposes investigation context as MCP resources that AI agents can
read to understand the current state of an investigation.

Resources:
  - investigation://state       — Current investigation summary
  - investigation://entities    — Entity inventory with provenance
  - investigation://graph       — Graph structure (Cytoscape JSON)
  - investigation://alerts      — Active monitoring alerts
  - investigation://config      — Emet configuration (non-sensitive)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resource definitions
# ---------------------------------------------------------------------------


@dataclass
class MCPResource:
    """MCP resource definition."""
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"


EMET_RESOURCES: list[MCPResource] = [
    MCPResource(
        uri="investigation://state",
        name="Investigation State",
        description=(
            "Current investigation summary: active queries, entity count, "
            "monitoring status, last activity timestamp."
        ),
    ),
    MCPResource(
        uri="investigation://entities",
        name="Entity Inventory",
        description=(
            "All entities discovered in the current investigation session, "
            "with FtM schema, provenance, and relationship counts."
        ),
    ),
    MCPResource(
        uri="investigation://graph",
        name="Entity Graph",
        description="Entity relationship graph in Cytoscape JSON format.",
    ),
    MCPResource(
        uri="investigation://alerts",
        name="Monitoring Alerts",
        description="Active alerts from change detection monitoring.",
    ),
    MCPResource(
        uri="investigation://config",
        name="Emet Configuration",
        description="Current Emet configuration (non-sensitive fields only).",
    ),
]


# ---------------------------------------------------------------------------
# Investigation session state
# ---------------------------------------------------------------------------


@dataclass
class InvestigationSession:
    """Tracks state within an MCP session.

    Inspired by mcp-memory-service's memory ontology — observations
    (entities found), decisions (investigative choices), and patterns
    (detected relationships) are tracked with timestamps for the
    forgetting/consolidation pattern.
    """
    session_id: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    entities: list[dict[str, Any]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def record_query(self, tool_name: str, arguments: dict, result_count: int) -> None:
        """Record a tool call for session history."""
        entry = {
            "tool": tool_name,
            "arguments": arguments,
            "result_count": result_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.tool_calls.append(entry)
        self.queries.append(entry)

    def add_entities(self, entities: list[dict[str, Any]]) -> None:
        """Add discovered entities to session inventory."""
        existing_ids = {e.get("id") for e in self.entities}
        for entity in entities:
            if entity.get("id") not in existing_ids:
                self.entities.append(entity)
                existing_ids.add(entity.get("id"))

    def add_alerts(self, alerts: list[dict[str, Any]]) -> None:
        """Add monitoring alerts to session."""
        self.alerts.extend(alerts)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def query_count(self) -> int:
        return len(self.queries)

    def summary(self) -> dict[str, Any]:
        """Generate session summary."""
        schema_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for entity in self.entities:
            schema = entity.get("schema", "Unknown")
            schema_counts[schema] = schema_counts.get(schema, 0) + 1
            source = entity.get("_provenance", {}).get("source", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1

        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "entity_count": self.entity_count,
            "query_count": self.query_count,
            "alert_count": len(self.alerts),
            "entities_by_schema": schema_counts,
            "entities_by_source": source_counts,
            "recent_queries": self.queries[-5:],
        }


# ---------------------------------------------------------------------------
# Resource provider
# ---------------------------------------------------------------------------


class EmetResourceProvider:
    """Serves MCP resources from investigation session state."""

    def __init__(self) -> None:
        self.session = InvestigationSession()
        self._resource_handlers: dict[str, Any] = {
            "investigation://state": self._get_state,
            "investigation://entities": self._get_entities,
            "investigation://graph": self._get_graph,
            "investigation://alerts": self._get_alerts,
            "investigation://config": self._get_config,
        }

    def list_resources(self) -> list[dict[str, Any]]:
        """Return MCP-formatted resource list."""
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mime_type,
            }
            for r in EMET_RESOURCES
        ]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI."""
        handler = self._resource_handlers.get(uri)
        if handler is None:
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": f"Unknown resource: {uri}",
                }],
            }

        data = await handler()
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(data, indent=2, default=str),
            }],
        }

    # --- Resource handlers ---

    async def _get_state(self) -> dict[str, Any]:
        return self.session.summary()

    async def _get_entities(self) -> dict[str, Any]:
        return {
            "count": self.session.entity_count,
            "entities": self.session.entities,
        }

    async def _get_graph(self) -> dict[str, Any]:
        """Build Cytoscape JSON from session entities."""
        nodes = []
        edges = []
        for entity in self.session.entities:
            nodes.append({
                "data": {
                    "id": entity.get("id", ""),
                    "label": _entity_label(entity),
                    "schema": entity.get("schema", "Thing"),
                    "source": entity.get("_provenance", {}).get("source", ""),
                },
            })

        return {
            "elements": {
                "nodes": nodes,
                "edges": edges,
            },
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    async def _get_alerts(self) -> dict[str, Any]:
        return {
            "count": len(self.session.alerts),
            "alerts": self.session.alerts,
        }

    async def _get_config(self) -> dict[str, Any]:
        """Non-sensitive configuration."""
        try:
            from emet.config.settings import settings
            return {
                "deployment_tier": settings.DEPLOYMENT_TIER,
                "llm_provider": settings.LLM_PROVIDER,
                "llm_fallback_enabled": settings.LLM_FALLBACK_ENABLED,
                "embedding_mode": settings.EMBEDDING_MODE,
            }
        except Exception:
            return {"status": "configuration unavailable"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity_label(entity: dict[str, Any]) -> str:
    """Extract a display label from an FtM entity."""
    props = entity.get("properties", {})
    names = props.get("name", [])
    if isinstance(names, list) and names:
        return names[0]
    if isinstance(names, str):
        return names
    return entity.get("id", "unknown")
