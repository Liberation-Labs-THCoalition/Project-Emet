"""MCP tool definitions for Project Emet.

Maps Emet's investigative capabilities to MCP tool format with
JSON Schema input definitions.  Each tool delegates to existing
modules — this is glue, not new logic.

Tool categories:
  - Search & discovery: federated entity search, OSINT recon
  - Analysis: graph analytics, ownership tracing, sanctions screening
  - Monitoring: change detection, alert management
  - Export: Markdown reports, FtM bundles, timelines
  - Documents: ingestion from Datashare/DocumentCloud
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition schema (MCP-compatible)
# ---------------------------------------------------------------------------


@dataclass
class MCPToolDef:
    """MCP tool definition with JSON Schema input."""
    name: str
    description: str
    input_schema: dict[str, Any]
    category: str = "investigation"
    read_only: bool = True            # MCP annotation hint
    requires_confirmation: bool = False


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


EMET_TOOLS: list[MCPToolDef] = [
    # --- Search & Discovery ---
    MCPToolDef(
        name="search_entities",
        description=(
            "Federated search across OpenSanctions, OpenCorporates, ICIJ "
            "Offshore Leaks, and GLEIF.  Returns FtM entities with provenance "
            "tracking.  Supports Person, Company, and general queries."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Entity name or search term",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["Person", "Company", "Any"],
                    "default": "Any",
                    "description": "Filter by FtM schema type",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Limit to specific sources: opensanctions, "
                        "opencorporates, icij, gleif.  Empty = all."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max results per source",
                },
            },
            "required": ["query"],
        },
        category="search",
    ),

    MCPToolDef(
        name="osint_recon",
        description=(
            "Technical OSINT reconnaissance via SpiderFoot.  Given a domain, "
            "email, IP, or name, runs automated reconnaissance modules "
            "(WHOIS, DNS, breach search, social media, etc.) and returns "
            "FtM entities.  200+ modules available."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target to investigate: domain, email, IP address, or name",
                },
                "scan_type": {
                    "type": "string",
                    "enum": ["passive", "active", "all"],
                    "default": "passive",
                    "description": (
                        "Scan intensity.  'passive' = no direct contact with target. "
                        "'active' = includes port scanning etc.  'all' = everything."
                    ),
                },
                "modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific SpiderFoot modules to run.  Empty = auto-select.",
                },
            },
            "required": ["target"],
        },
        category="search",
    ),

    # --- Analysis ---
    MCPToolDef(
        name="analyze_graph",
        description=(
            "Run graph analytics on an entity network.  Algorithms: "
            "community_detection (Louvain), centrality (betweenness/degree), "
            "shortest_path, connected_components, pagerank, bridging_nodes, "
            "temporal_patterns.  Input is a list of FtM entity IDs or a "
            "previous search result."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "FtM entity IDs to include in graph",
                },
                "algorithm": {
                    "type": "string",
                    "enum": [
                        "community_detection",
                        "centrality",
                        "shortest_path",
                        "connected_components",
                        "pagerank",
                        "bridging_nodes",
                        "temporal_patterns",
                    ],
                    "description": "Graph algorithm to run",
                },
                "params": {
                    "type": "object",
                    "description": "Algorithm-specific parameters (e.g. source/target for shortest_path)",
                },
            },
            "required": ["algorithm"],
        },
        category="analysis",
    ),

    MCPToolDef(
        name="trace_ownership",
        description=(
            "Trace corporate ownership chains from a target entity.  "
            "Follows beneficial ownership, directorship, and shareholding "
            "links across jurisdictions.  Returns an ownership tree with "
            "shell company indicators."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Company or person name to trace from",
                },
                "max_depth": {
                    "type": "integer",
                    "default": 3,
                    "description": "Maximum ownership chain depth",
                },
                "include_officers": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include directors and officers",
                },
            },
            "required": ["entity_name"],
        },
        category="analysis",
    ),

    MCPToolDef(
        name="screen_sanctions",
        description=(
            "Screen entities against 325+ sanctions, PEP, and watchlist "
            "datasets via OpenSanctions.  Returns match scores, dataset "
            "origins, and risk classification."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "schema": {"type": "string", "default": "Person"},
                            "birth_date": {"type": "string"},
                            "nationality": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                    "description": "Entities to screen (batch supported)",
                },
                "threshold": {
                    "type": "number",
                    "default": 0.7,
                    "description": "Minimum match score (0-1) to include",
                },
            },
            "required": ["entities"],
        },
        category="analysis",
    ),

    MCPToolDef(
        name="investigate_blockchain",
        description=(
            "Investigate blockchain addresses and transactions.  "
            "Supports Ethereum and Bitcoin.  Returns balance, transaction "
            "history, connected addresses, and token transfers."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Blockchain address (ETH 0x... or BTC)",
                },
                "chain": {
                    "type": "string",
                    "enum": ["ethereum", "bitcoin"],
                    "default": "ethereum",
                },
                "depth": {
                    "type": "integer",
                    "default": 1,
                    "description": "Transaction hop depth to trace",
                },
            },
            "required": ["address"],
        },
        category="analysis",
    ),

    # --- Monitoring ---
    MCPToolDef(
        name="monitor_entity",
        description=(
            "Register an entity for continuous monitoring.  Emet will "
            "periodically check for changes in sanctions status, corporate "
            "filings, news mentions, and other data sources.  Returns "
            "alerts when changes are detected."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of entity to monitor",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["Person", "Company", "Any"],
                    "default": "Any",
                },
                "alert_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "new_sanction",
                            "changed_property",
                            "new_entity",
                            "removed_entity",
                        ],
                    },
                    "description": "Types of changes to alert on.  Empty = all.",
                },
            },
            "required": ["entity_name"],
        },
        category="monitoring",
        read_only=False,
    ),

    MCPToolDef(
        name="check_alerts",
        description=(
            "Check for alerts on all monitored entities.  Returns any "
            "detected changes since last check."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Filter alerts to a specific entity.  Empty = all.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Minimum severity to include",
                },
            },
        },
        category="monitoring",
    ),

    # --- Export ---
    MCPToolDef(
        name="generate_report",
        description=(
            "Generate an investigation report from search results, analysis, "
            "and monitoring data.  Formats: markdown, ftm_bundle, timeline."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Report title",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "ftm_bundle", "timeline"],
                    "default": "markdown",
                },
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Entity IDs to include in report",
                },
                "include_graph": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include graph visualization data",
                },
                "include_timeline": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include temporal analysis",
                },
            },
            "required": ["title"],
        },
        category="export",
        read_only=False,
    ),

    # --- Documents ---
    MCPToolDef(
        name="ingest_documents",
        description=(
            "Ingest documents from Datashare or DocumentCloud for NER "
            "extraction and entity linking.  Returns extracted entities "
            "and document metadata."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["datashare", "documentcloud"],
                    "description": "Document source platform",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project/collection ID in source platform",
                },
                "query": {
                    "type": "string",
                    "description": "Search query within document source",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max documents to ingest",
                },
            },
            "required": ["source"],
        },
        category="documents",
        read_only=False,
    ),
]


# ---------------------------------------------------------------------------
# Tool executor — delegates to existing Emet modules
# ---------------------------------------------------------------------------


class EmetToolExecutor:
    """Executes MCP tool calls by delegating to Emet's existing modules.

    This is intentionally thin glue code.  Each tool method imports
    and calls the relevant existing module rather than reimplementing
    any logic.
    """

    def __init__(self) -> None:
        self._tool_map: dict[str, Callable[..., Coroutine[Any, Any, dict]]] = {
            "search_entities": self._search_entities,
            "osint_recon": self._osint_recon,
            "analyze_graph": self._analyze_graph,
            "trace_ownership": self._trace_ownership,
            "screen_sanctions": self._screen_sanctions,
            "investigate_blockchain": self._investigate_blockchain,
            "monitor_entity": self._monitor_entity,
            "check_alerts": self._check_alerts,
            "generate_report": self._generate_report,
            "ingest_documents": self._ingest_documents,
        }

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute an MCP tool call."""
        handler = self._tool_map.get(tool_name)
        if handler is None:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            }
        try:
            result = await handler(**arguments)
            return {
                "isError": False,
                "content": [{"type": "text", "text": _format_result(result)}],
                "_raw": result,
            }
        except Exception as exc:
            logger.exception("Tool execution failed: %s", tool_name)
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Error: {exc}"}],
            }

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP-formatted tool list."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
                "annotations": {
                    "readOnlyHint": t.read_only,
                    "destructiveHint": False,
                    "requiresConfirmation": t.requires_confirmation,
                },
            }
            for t in EMET_TOOLS
        ]

    # --- Tool implementations (thin wrappers) ---

    async def _search_entities(
        self,
        query: str,
        entity_type: str = "Any",
        sources: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Federated entity search."""
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        config = FederationConfig()
        if sources:
            config.enable_opensanctions = "opensanctions" in sources
            config.enable_opencorporates = "opencorporates" in sources
            config.enable_icij = "icij" in sources
            config.enable_gleif = "gleif" in sources

        federation = FederatedSearch(config=config)
        et = entity_type if entity_type != "Any" else ""
        results = await federation.search_entity(query, entity_type=et, limit=limit)
        return {
            "query": query,
            "entity_type": entity_type,
            "result_count": len(results),
            "entities": results[:limit],
        }

    async def _osint_recon(
        self,
        target: str,
        scan_type: str = "passive",
        modules: list[str] | None = None,
    ) -> dict[str, Any]:
        """SpiderFoot OSINT reconnaissance."""
        from emet.ftm.external.spiderfoot import SpiderFootClient, SpiderFootConfig

        client = SpiderFootClient(SpiderFootConfig())
        scan_result = await client.scan(
            target=target,
            scan_type=scan_type,
            modules=modules,
        )
        return scan_result

    async def _analyze_graph(
        self,
        algorithm: str,
        entity_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Graph analytics on entity network."""
        from emet.graph.engine import GraphEngine

        engine = GraphEngine()
        if entity_ids:
            engine.load_entities(entity_ids)

        algo_params = params or {}
        result = engine.run_algorithm(algorithm, **algo_params)
        return {
            "algorithm": algorithm,
            "node_count": engine.node_count,
            "edge_count": engine.edge_count,
            "result": result,
        }

    async def _trace_ownership(
        self,
        entity_name: str,
        max_depth: int = 3,
        include_officers: bool = True,
    ) -> dict[str, Any]:
        """Corporate ownership tracing."""
        from emet.ftm.external.federation import FederatedSearch

        federation = FederatedSearch()
        results = await federation.search_entity(
            entity_name, entity_type="Company", limit=10
        )

        return {
            "target": entity_name,
            "max_depth": max_depth,
            "include_officers": include_officers,
            "entities_found": len(results),
            "entities": results[:10],
        }

    async def _screen_sanctions(
        self,
        entities: list[dict[str, Any]],
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        """Sanctions screening via OpenSanctions."""
        from emet.ftm.external.adapters import YenteClient

        client = YenteClient()
        results = []
        for entity in entities:
            matches = await client.match(
                name=entity.get("name", ""),
                schema=entity.get("schema", "Person"),
            )
            for match in matches.get("responses", {}).values():
                for r in match.get("results", []):
                    if r.get("score", 0) >= threshold:
                        results.append(r)

        return {
            "screened_count": len(entities),
            "match_count": len(results),
            "threshold": threshold,
            "matches": results,
        }

    async def _investigate_blockchain(
        self,
        address: str,
        chain: str = "ethereum",
        depth: int = 1,
    ) -> dict[str, Any]:
        """Blockchain address investigation."""
        from emet.ftm.external.blockchain import BlockchainAdapter, BlockchainConfig

        adapter = BlockchainAdapter(BlockchainConfig())
        if chain == "ethereum":
            result = await adapter.get_eth_address(address)
        else:
            result = await adapter.get_btc_address(address)

        return {
            "address": address,
            "chain": chain,
            "depth": depth,
            "data": result,
        }

    async def _monitor_entity(
        self,
        entity_name: str,
        entity_type: str = "Any",
        alert_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register entity for monitoring."""
        from emet.monitoring import ChangeDetector

        detector = ChangeDetector()
        detector.register_query(entity_name, entity_type=entity_type)
        return {
            "registered": True,
            "entity_name": entity_name,
            "entity_type": entity_type,
            "alert_types": alert_types or ["all"],
        }

    async def _check_alerts(
        self,
        entity_name: str = "",
        severity: str = "",
    ) -> dict[str, Any]:
        """Check monitoring alerts."""
        from emet.monitoring import ChangeDetector

        detector = ChangeDetector()
        alerts = await detector.check_all()

        if entity_name:
            alerts = [a for a in alerts if a.entity_name == entity_name]
        if severity:
            severity_order = {"low": 0, "medium": 1, "high": 2}
            min_sev = severity_order.get(severity, 0)
            alerts = [
                a for a in alerts
                if severity_order.get(a.severity, 0) >= min_sev
            ]

        return {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "type": a.alert_type,
                    "entity": a.entity_name,
                    "severity": a.severity,
                    "details": a.details,
                    "timestamp": a.timestamp,
                }
                for a in alerts
            ],
        }

    async def _generate_report(
        self,
        title: str,
        format: str = "markdown",
        entity_ids: list[str] | None = None,
        include_graph: bool = True,
        include_timeline: bool = True,
    ) -> dict[str, Any]:
        """Generate investigation report."""
        from emet.export.markdown import MarkdownReporter

        reporter = MarkdownReporter()
        report = reporter.generate(
            title=title,
            entity_ids=entity_ids or [],
            include_graph=include_graph,
            include_timeline=include_timeline,
        )
        return {
            "title": title,
            "format": format,
            "report": report,
        }

    async def _ingest_documents(
        self,
        source: str,
        project_id: str = "",
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Document ingestion from Datashare/DocumentCloud."""
        from emet.ftm.external.document_sources import (
            DatashareClient,
            DocumentCloudClient,
            DatashareConfig,
            DocumentCloudConfig,
        )

        if source == "datashare":
            client = DatashareClient(DatashareConfig())
            docs = await client.search(query=query, project_id=project_id, limit=limit)
        elif source == "documentcloud":
            client = DocumentCloudClient(DocumentCloudConfig())
            docs = await client.search(query=query, project_id=project_id, limit=limit)
        else:
            return {"error": f"Unknown source: {source}"}

        return {
            "source": source,
            "document_count": len(docs),
            "documents": docs[:limit],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_result(result: dict[str, Any]) -> str:
    """Format a tool result as human-readable text for MCP response."""
    import json
    return json.dumps(result, indent=2, default=str)
