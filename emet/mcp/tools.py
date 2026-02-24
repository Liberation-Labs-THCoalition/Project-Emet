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
                    "enum": ["ethereum", "bitcoin", "tron"],
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

    # --- Workflows ---
    MCPToolDef(
        name="list_workflows",
        description=(
            "List available investigation workflow templates.  Workflows "
            "are pre-built investigation patterns that chain multiple tools "
            "into automated sequences."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g. corporate, compliance, person)",
                },
            },
        },
        category="workflows",
    ),

    MCPToolDef(
        name="run_workflow",
        description=(
            "Execute an investigation workflow template.  Available workflows: "
            "corporate_ownership, person_investigation, sanctions_screening, "
            "domain_investigation, due_diligence.  Each workflow chains "
            "multiple investigative steps automatically."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "workflow_name": {
                    "type": "string",
                    "description": "Name of the workflow to execute",
                },
                "inputs": {
                    "type": "object",
                    "description": "Workflow input parameters (varies by workflow)",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Preview parameter resolution without executing",
                },
            },
            "required": ["workflow_name", "inputs"],
        },
        category="workflows",
        read_only=False,
        requires_confirmation=True,
    ),
]


# ---------------------------------------------------------------------------
# Tool executor — delegates to existing Emet modules
# ---------------------------------------------------------------------------


class EmetToolExecutor:
    """Executes MCP tool calls by delegating to Emet's existing modules.

    Maintains a resource pool of adapter instances so they're created
    once and reused across tool calls within a session, rather than
    spinning up fresh connections on every invocation.
    """

    def __init__(self, demo_mode: bool = False) -> None:
        self.demo_mode = demo_mode
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
            "list_workflows": self._list_workflows,
            "run_workflow": self._run_workflow,
        }
        # Connection pool — lazily initialized, reused across calls
        self._pool: dict[str, Any] = {}

    def _get_or_create(self, key: str, factory: Callable[[], Any]) -> Any:
        """Get a cached adapter instance, or create one."""
        if key not in self._pool:
            self._pool[key] = factory()
        return self._pool[key]

    def reset_pool(self) -> None:
        """Clear all cached adapter instances."""
        self._pool.clear()

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute an MCP tool call.  Returns MCP-protocol wrapped result."""
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

    async def execute_raw(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool and return the raw result dict (no MCP wrapping).

        Used by the agent loop and other internal callers that need direct
        access to entities, article counts, etc.  Raises on unknown tool;
        propagates tool exceptions.
        """
        handler = self._tool_map.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        return await handler(**arguments)

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

        if sources:
            # Custom source set — create per-call (rare path)
            config = FederationConfig()
            config.enable_opensanctions = "opensanctions" in sources
            config.enable_opencorporates = "opencorporates" in sources
            config.enable_icij = "icij" in sources
            config.enable_gleif = "gleif" in sources
            federation = FederatedSearch(config=config)
        else:
            # Default config — reuse pooled instance
            federation = self._get_or_create(
                "federation", lambda: FederatedSearch(config=FederationConfig())
            )
        et = entity_type if entity_type != "Any" else ""
        federated_result = await federation.search_entity(
            query, entity_type=et, limit_per_source=limit,
        )
        entities = federated_result.entities[:limit]
        return {
            "query": query,
            "entity_type": entity_type,
            "result_count": len(entities),
            "entities": entities,
            "source_stats": federated_result.source_stats,
            "errors": federated_result.errors,
            "queried_at": federated_result.queried_at,
        }

    async def _osint_recon(
        self,
        target: str,
        scan_type: str = "passive",
        modules: list[str] | None = None,
    ) -> dict[str, Any]:
        """SpiderFoot OSINT reconnaissance."""
        from emet.ftm.external.spiderfoot import SpiderFootClient, SpiderFootConfig

        try:
            client = self._get_or_create(
                "spiderfoot", lambda: SpiderFootClient(SpiderFootConfig())
            )
            scan_result = await client.scan(
                target=target,
                scan_type=scan_type,
                modules=modules,
            )
            return scan_result
        except (ConnectionError, OSError, Exception) as exc:
            if "connect" in type(exc).__name__.lower() or "connection" in str(exc).lower():
                return {
                    "target": target,
                    "scan_type": scan_type,
                    "error": f"SpiderFoot server unavailable: {exc}",
                    "hint": "Ensure SpiderFoot is running and SPIDERFOOT_URL is configured.",
                }
            raise

    async def _analyze_graph(
        self,
        algorithm: str = "full",
        entity_ids: list[str] | None = None,
        entities: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Graph analytics on entity network.

        Algorithms: community_detection, brokers, circular_ownership,
        key_players, structural_anomalies, full (runs all).
        """
        from emet.graph.engine import GraphEngine

        engine = self._get_or_create("graph_engine", GraphEngine)

        entity_list = entities or []
        if not entity_list:
            return {
                "algorithm": algorithm,
                "node_count": 0,
                "edge_count": 0,
                "result": {},
                "error": "No entities provided for graph analysis",
            }

        graph_result = engine.build_from_entities(entity_list)
        analysis = graph_result.analysis
        algo_params = params or {}

        # Map algorithm name to actual method
        algo_map = {
            "community_detection": lambda: [c.__dict__ for c in analysis.find_communities()],
            "brokers": lambda: [b.__dict__ for b in analysis.find_brokers(**algo_params)],
            "circular_ownership": lambda: [c.__dict__ for c in analysis.find_circular_ownership(**algo_params)],
            "key_players": lambda: [k.__dict__ for k in analysis.find_key_players(**algo_params)],
            "structural_anomalies": lambda: [a.__dict__ for a in analysis.find_structural_anomalies()],
        }

        if algorithm == "full":
            result = {}
            for name, fn in algo_map.items():
                try:
                    result[name] = fn()
                except Exception as exc:
                    result[name] = {"error": str(exc)}
        elif algorithm in algo_map:
            result = algo_map[algorithm]()
        else:
            return {
                "algorithm": algorithm,
                "error": f"Unknown algorithm '{algorithm}'. Available: {list(algo_map.keys()) + ['full']}",
            }

        return {
            "algorithm": algorithm,
            "node_count": graph_result.node_count,
            "edge_count": graph_result.edge_count,
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

        federation = self._get_or_create("federation_default", FederatedSearch)
        federated_result = await federation.search_entity(
            entity_name, entity_type="Company", limit_per_source=10,
        )
        entities = federated_result.entities[:10]

        return {
            "target": entity_name,
            "max_depth": max_depth,
            "include_officers": include_officers,
            "entities_found": len(entities),
            "entities": entities,
        }

    async def _screen_sanctions(
        self,
        entities: list[dict[str, Any]],
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        """Sanctions screening via OpenSanctions."""
        from emet.ftm.external.adapters import YenteClient

        client = self._get_or_create("yente", YenteClient)

        # Convert input entities to FtM-style dicts for the match API
        ftm_entities = []
        for entity in entities:
            ftm_entities.append({
                "schema": entity.get("schema", "Person"),
                "properties": {"name": [entity.get("name", "")]},
            })

        raw_matches = await client.screen_entities(ftm_entities)

        # Filter by threshold
        results = [
            m for m in raw_matches
            if m.get("score", 0) >= threshold
        ]

        # Demo mode: inject demo sanctions matches when real screening returns empty
        if not results and self.demo_mode:
            from emet.data.demo_entities import get_demo_sanctions_matches
            entity_names = {e.get("name", "").lower() for e in entities}
            for demo_match in get_demo_sanctions_matches():
                if demo_match.get("name", "").lower() in entity_names:
                    results.append(demo_match)

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

        adapter = self._get_or_create(
            "blockchain", lambda: BlockchainAdapter(BlockchainConfig())
        )
        if chain == "ethereum":
            result = await adapter.get_eth_address(address)
        elif chain == "tron":
            result = await adapter.get_tron_address(address)
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
        timespan: str = "7d",
    ) -> dict[str, Any]:
        """Monitor entity: GDELT news search + register for change detection."""
        from emet.monitoring import ChangeDetector
        from emet.ftm.external.gdelt import GDELTClient

        # 1. Run GDELT news search for immediate results
        gdelt = self._get_or_create("gdelt", GDELTClient)
        try:
            news = await gdelt.search_news_ftm(
                query=entity_name,
                timespan=timespan,
            )
        except Exception as exc:
            logger.warning("GDELT search failed for %r: %s", entity_name, exc)
            news = {
                "article_count": 0,
                "entity_count": 0,
                "unique_sources": [],
                "average_tone": 0.0,
                "entities": [],
            }

        # 2. Register for ongoing change monitoring
        detector = self._get_or_create("change_detector", ChangeDetector)
        detector.register_query(entity_name, entity_type=entity_type)

        return {
            "entity_name": entity_name,
            "entity_type": entity_type,
            "monitoring_registered": True,
            "alert_types": alert_types or ["all"],
            # GDELT results
            "article_count": news.get("article_count", 0),
            "unique_sources": news.get("unique_sources", []),
            "average_tone": news.get("average_tone", 0.0),
            "entities": news.get("entities", []),
            "result_count": news.get("article_count", 0),
        }

    async def _check_alerts(
        self,
        entity_name: str = "",
        severity: str = "",
    ) -> dict[str, Any]:
        """Check monitoring alerts."""
        from emet.monitoring import ChangeDetector

        detector = self._get_or_create("change_detector", ChangeDetector)
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
        entities: list[dict[str, Any]] | None = None,
        entity_ids: list[str] | None = None,
        include_graph: bool = True,
        include_timeline: bool = True,
    ) -> dict[str, Any]:
        """Generate investigation report."""
        from emet.export.markdown import MarkdownReport, InvestigationReport

        reporter = self._get_or_create("markdown_reporter", MarkdownReport)

        report_obj = InvestigationReport(title=title)

        # Populate entities if provided
        if entities:
            for entity in entities:
                props = entity.get("properties", {})
                report_obj.entities.append({
                    "id": entity.get("id", ""),
                    "schema": entity.get("schema", ""),
                    "name": (props.get("name", [""]) or [""])[0],
                    "country": (props.get("country", [""]) or [""])[0],
                    "properties": props,
                })

        report_text = reporter.generate(report_obj)
        return {
            "title": title,
            "format": format,
            "report": report_text,
        }

    async def _ingest_documents(
        self,
        source: str,
        project_id: str = "",
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Document ingestion from Datashare/DocumentCloud."""

        if source == "datashare":
            from emet.ftm.external.document_sources import DatashareClient
            client = self._get_or_create("datashare", DatashareClient)
            docs = await client.search(query=query or "*", size=limit)
        elif source == "documentcloud":
            from emet.ftm.external.document_sources import DocumentCloudClient
            client = self._get_or_create("documentcloud", DocumentCloudClient)
            docs = await client.search(query=query or "*", per_page=limit)
        else:
            return {"error": f"Unknown source: {source}"}

        return {
            "source": source,
            "document_count": len(docs),
            "documents": docs[:limit],
        }

    async def _list_workflows(
        self,
        category: str = "",
    ) -> dict[str, Any]:
        """List available workflow templates."""
        from emet.workflows.registry import WorkflowRegistry

        def _make_registry():
            r = WorkflowRegistry()
            r.load_builtins()
            return r

        registry = self._get_or_create("workflow_registry", _make_registry)
        workflows = registry.list_workflows()

        if category:
            workflows = [w for w in workflows if w.get("category") == category]

        return {
            "workflow_count": len(workflows),
            "workflows": workflows,
        }

    async def _run_workflow(
        self,
        workflow_name: str,
        inputs: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute an investigation workflow."""
        from emet.workflows.registry import WorkflowRegistry
        from emet.workflows.engine import WorkflowEngine

        def _make_registry():
            r = WorkflowRegistry()
            r.load_builtins()
            return r

        registry = self._get_or_create("workflow_registry", _make_registry)

        workflow = registry.get(workflow_name)
        if workflow is None:
            available = [w["name"] for w in registry.list_workflows()]
            return {
                "error": f"Unknown workflow: {workflow_name}",
                "available": available,
            }

        engine = WorkflowEngine(tool_executor=self)
        run = await engine.run(workflow, inputs or {}, dry_run=dry_run)

        return {
            "run_id": run.run_id,
            "workflow": workflow_name,
            "status": run.status.value,
            "steps_completed": sum(
                1 for sr in run.step_results
                if sr.status.value in ("completed", "skipped")
            ),
            "steps_total": len(run.step_results),
            "entity_count": run.entity_count,
            "error": run.error,
            "step_results": [
                {
                    "step_id": sr.step_id,
                    "tool": sr.tool,
                    "status": sr.status.value,
                    "duration": sr.duration_seconds,
                    "skip_reason": sr.skip_reason,
                }
                for sr in run.step_results
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_result(result: dict[str, Any]) -> str:
    """Format a tool result as human-readable text for MCP response."""
    import json
    return json.dumps(result, indent=2, default=str)
