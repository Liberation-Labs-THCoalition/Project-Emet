"""Graph Analytics Engine — high-level orchestrator.

Provides the primary API for building graphs from various sources
(FtM entity lists, Aleph collections, federated search results)
and running investigative analysis.

Usage::

    engine = GraphEngine()

    # Build from a list of FtM entities
    result = engine.build_from_entities(entities)

    # Run analysis
    brokers = result.analysis.find_brokers(top_n=5)
    communities = result.analysis.find_communities()
    cycles = result.analysis.find_circular_ownership()

    # Export
    result.exporter.to_gexf("output/network.gexf")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from emet.graph.algorithms import InvestigativeAnalysis
from emet.graph.exporters import GraphExporter
from emet.graph.ftm_loader import FtMGraphLoader, LoadStats

logger = logging.getLogger(__name__)


@dataclass
class GraphResult:
    """Result of a graph build operation.

    Contains the graph, analysis engine, exporter, and load stats
    all wired together and ready to use.
    """

    graph: nx.MultiDiGraph
    analysis: InvestigativeAnalysis
    exporter: GraphExporter
    stats: LoadStats

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def summary(self) -> dict[str, Any]:
        """Combined summary of graph stats and load stats."""
        analysis_summary = self.analysis.summary()
        return {
            **analysis_summary,
            "load_stats": {
                "nodes_loaded": self.stats.nodes_loaded,
                "edges_loaded": self.stats.edges_loaded,
                "relationship_entities": self.stats.relationship_entities,
                "orphan_references": self.stats.orphan_references,
                "skipped_entities": self.stats.skipped_entities,
                "schema_counts": self.stats.schema_counts,
                "edge_type_counts": self.stats.edge_type_counts,
            },
        }


class GraphEngine:
    """Build and analyze entity relationship graphs.

    Parameters
    ----------
    max_nodes:
        Safety cap on graph size. Default 50,000.
    include_orphan_nodes:
        Create placeholder nodes for unresolved entity references.
    """

    def __init__(
        self,
        max_nodes: int = 50_000,
        include_orphan_nodes: bool = True,
    ) -> None:
        self._loader = FtMGraphLoader(
            max_nodes=max_nodes,
            include_orphan_nodes=include_orphan_nodes,
        )

    def build_from_entities(self, entities: list[dict[str, Any]]) -> GraphResult:
        """Build a graph from a list of FtM entity dicts.

        This is the primary entry point. Entities can come from Aleph,
        federated search, or any other source that produces FtM dicts.
        """
        graph, stats = self._loader.load(entities)
        analysis = InvestigativeAnalysis(graph)
        exporter = GraphExporter(graph, analysis)

        logger.info(
            "Graph built: %d nodes, %d edges (%d relationship entities processed, "
            "%d orphan references)",
            stats.nodes_loaded, stats.edges_loaded,
            stats.relationship_entities, stats.orphan_references,
        )

        return GraphResult(
            graph=graph,
            analysis=analysis,
            exporter=exporter,
            stats=stats,
        )

    async def build_from_aleph(
        self,
        collection_id: str,
        aleph_host: str = "",
        aleph_api_key: str = "",
    ) -> GraphResult:
        """Build a graph from an Aleph collection.

        Streams entities from the Aleph API and constructs the graph
        incrementally.
        """
        from emet.ftm.aleph_client import AlephClient

        client = AlephClient(host=aleph_host, api_key=aleph_api_key)

        entities: list[dict[str, Any]] = []
        async for entity in client.stream_entities(collection_id):
            entities.append(entity)

        logger.info(
            "Streamed %d entities from Aleph collection %s",
            len(entities), collection_id,
        )

        return self.build_from_entities(entities)

    async def build_from_federation(
        self,
        query: str,
        entity_type: str = "",
        jurisdictions: list[str] | None = None,
    ) -> GraphResult:
        """Build a graph from federated search results.

        Runs a query across all configured external data sources and
        builds a graph from the merged results.
        """
        from emet.ftm.external.federation import FederatedSearch

        federation = FederatedSearch()
        results = await federation.search_entity(
            name=query,
            entity_type=entity_type,
            jurisdictions=jurisdictions or [],
        )

        entities = results.get("entities", [])
        logger.info(
            "Federated search for %r returned %d entities from %d sources",
            query, len(entities), len(results.get("sources_queried", [])),
        )

        return self.build_from_entities(entities)

    # -- Convenience: full investigation workflow ----------------------------

    async def investigate_entity(
        self,
        entity_name: str,
        export_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Run a full investigative analysis on an entity.

        This is the "wow" function for demos — give it a name, get back
        a complete network analysis.

        1. Federated search across all data sources
        2. Build entity network graph
        3. Run all investigative algorithms
        4. Export results
        5. Return structured findings

        Parameters
        ----------
        entity_name:
            The name to investigate (person, company, etc.)
        export_dir:
            Optional directory for graph exports (GEXF, CSV).
        """
        result = await self.build_from_federation(entity_name)

        findings: dict[str, Any] = {
            "query": entity_name,
            "graph_summary": result.summary(),
        }

        # Only run analysis if graph has enough data
        if result.node_count >= 2:
            findings["key_players"] = [
                {
                    "name": kp.name,
                    "schema": kp.schema,
                    "composite_score": kp.composite_score,
                    "explanation": kp.explanation,
                }
                for kp in result.analysis.find_key_players(top_n=10)
            ]

            findings["brokers"] = [
                {
                    "name": b.name,
                    "schema": b.schema,
                    "betweenness": b.betweenness_score,
                    "explanation": b.explanation,
                    "follow_up": b.follow_up,
                }
                for b in result.analysis.find_brokers(top_n=5)
            ]

            findings["communities"] = [
                {
                    "id": c.community_id,
                    "size": c.member_count,
                    "cross_jurisdiction": c.cross_jurisdiction,
                    "explanation": c.explanation,
                }
                for c in result.analysis.find_communities()
            ]

            findings["circular_ownership"] = [
                {
                    "length": c.cycle_length,
                    "entities": [e["name"] for e in c.cycle_entities],
                    "risk_score": c.risk_score,
                    "explanation": c.explanation,
                }
                for c in result.analysis.find_circular_ownership()
            ]

            findings["anomalies"] = [
                {
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "explanation": a.explanation,
                    "follow_up": a.follow_up,
                }
                for a in result.analysis.find_structural_anomalies()
            ]
        else:
            findings["note"] = (
                f"Only {result.node_count} node(s) found — insufficient for "
                f"network analysis. Try enriching with additional data sources."
            )

        # Export if directory provided
        if export_dir:
            export_path = Path(export_dir)
            export_path.mkdir(parents=True, exist_ok=True)
            try:
                result.exporter.to_gexf(export_path / "network.gexf")
                result.exporter.to_csv_files(export_path)
                d3_data = result.exporter.to_d3_json()
                (export_path / "network_d3.json").write_text(
                    __import__("json").dumps(d3_data, indent=2)
                )
                findings["exports"] = {
                    "gexf": str(export_path / "network.gexf"),
                    "nodes_csv": str(export_path / "nodes.csv"),
                    "edges_csv": str(export_path / "edges.csv"),
                    "d3_json": str(export_path / "network_d3.json"),
                }
            except Exception as e:
                logger.warning("Export failed: %s", e)
                findings["export_error"] = str(e)

        return findings
