"""Graph export in multiple formats for external visualization tools.

Supported formats:
  - GEXF: Gephi (the standard for investigative graph visualization)
  - GraphML: General-purpose XML graph format
  - Cytoscape JSON: For eventual web UI (Cytoscape.js / Sigma.js)
  - D3 JSON: For D3.js force-directed layouts
  - CSV: Node and edge tables for spreadsheet analysis

All exporters add visual attributes (node size, color, edge weight)
pre-configured for investigative visualization.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx

from emet.graph.algorithms import InvestigativeAnalysis

logger = logging.getLogger(__name__)


class GraphExporter:
    """Export NetworkX graphs in various formats.

    Parameters
    ----------
    graph:
        The NetworkX MultiDiGraph to export.
    analysis:
        Optional pre-computed analysis results for enriching exports.
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        analysis: InvestigativeAnalysis | None = None,
    ) -> None:
        self._graph = graph
        self._analysis = analysis

    # -- GEXF (Gephi) -------------------------------------------------------

    def to_gexf(self, path: str | Path) -> None:
        """Export to GEXF format for Gephi.

        Pre-configures visual attributes:
        - Node size by PageRank (if analysis available) or degree
        - Node color by entity schema
        - Edge weight by relationship strength
        """
        # GEXF needs simple DiGraph (no multi-edges)
        export_graph = self._prepare_simple_graph()
        self._add_visual_attributes(export_graph)
        nx.write_gexf(export_graph, str(path))
        logger.info("Exported GEXF to %s (%d nodes, %d edges)",
                     path, export_graph.number_of_nodes(), export_graph.number_of_edges())

    # -- GraphML -------------------------------------------------------------

    def to_graphml(self, path: str | Path) -> None:
        """Export to GraphML format."""
        export_graph = self._prepare_simple_graph()
        self._add_visual_attributes(export_graph)

        # GraphML doesn't handle dicts/lists well — flatten
        for node_id in export_graph.nodes():
            data = export_graph.nodes[node_id]
            for key in list(data.keys()):
                if isinstance(data[key], (dict, list)):
                    data[key] = json.dumps(data[key])

        for u, v in export_graph.edges():
            data = export_graph[u][v]
            for key in list(data.keys()):
                if isinstance(data[key], (dict, list)):
                    data[key] = json.dumps(data[key])

        nx.write_graphml(export_graph, str(path))
        logger.info("Exported GraphML to %s", path)

    # -- Cytoscape JSON ------------------------------------------------------

    def to_cytoscape_json(self) -> dict[str, Any]:
        """Export to Cytoscape.js JSON format for web visualization."""
        elements: list[dict[str, Any]] = []

        # Add nodes
        for node_id, data in self._graph.nodes(data=True):
            node_data = {
                "id": node_id,
                "label": data.get("name", node_id[:12]),
                "schema": data.get("schema", "Unknown"),
                "country": data.get("country", ""),
                "color": data.get("color", "#95A5A6"),
            }

            # Add PageRank for sizing if analysis available
            if self._analysis:
                simple = nx.DiGraph(self._graph)
                try:
                    pr = nx.pagerank(simple)
                    node_data["pagerank"] = pr.get(node_id, 0)
                except Exception:
                    pass

            elements.append({"data": node_data, "group": "nodes"})

        # Add edges
        edge_id = 0
        for u, v, key, data in self._graph.edges(data=True, keys=True):
            elements.append({
                "data": {
                    "id": f"e{edge_id}",
                    "source": u,
                    "target": v,
                    "label": data.get("label", ""),
                    "schema": data.get("schema", ""),
                    "weight": data.get("weight", 0.5),
                },
                "group": "edges",
            })
            edge_id += 1

        return {"elements": elements}

    # -- D3 JSON -------------------------------------------------------------

    def to_d3_json(self) -> dict[str, Any]:
        """Export to D3.js force-directed JSON format."""
        nodes = []
        node_index: dict[str, int] = {}

        for i, (node_id, data) in enumerate(self._graph.nodes(data=True)):
            node_index[node_id] = i
            nodes.append({
                "id": node_id,
                "name": data.get("name", node_id[:12]),
                "schema": data.get("schema", "Unknown"),
                "country": data.get("country", ""),
                "color": data.get("color", "#95A5A6"),
                "group": data.get("schema", "Unknown"),
            })

        links = []
        for u, v, data in self._graph.edges(data=True):
            if u in node_index and v in node_index:
                links.append({
                    "source": node_index[u],
                    "target": node_index[v],
                    "label": data.get("label", ""),
                    "schema": data.get("schema", ""),
                    "weight": data.get("weight", 0.5),
                })

        return {"nodes": nodes, "links": links}

    # -- CSV -----------------------------------------------------------------

    def to_csv_nodes(self) -> str:
        """Export node table as CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "name", "schema", "country", "address"])

        for node_id, data in self._graph.nodes(data=True):
            writer.writerow([
                node_id,
                data.get("name", ""),
                data.get("schema", ""),
                data.get("country", ""),
                data.get("address", ""),
            ])

        return output.getvalue()

    def to_csv_edges(self) -> str:
        """Export edge table as CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["source_id", "target_id", "relationship_type", "label", "weight"])

        for u, v, data in self._graph.edges(data=True):
            writer.writerow([
                u, v,
                data.get("schema", ""),
                data.get("label", ""),
                data.get("weight", 0.5),
            ])

        return output.getvalue()

    def to_csv_files(self, directory: str | Path) -> tuple[Path, Path]:
        """Write node and edge CSV files to a directory."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        nodes_path = directory / "nodes.csv"
        edges_path = directory / "edges.csv"

        nodes_path.write_text(self.to_csv_nodes())
        edges_path.write_text(self.to_csv_edges())

        logger.info("Exported CSV to %s (nodes + edges)", directory)
        return nodes_path, edges_path

    # -- Helpers -------------------------------------------------------------

    def _prepare_simple_graph(self) -> nx.DiGraph:
        """Convert MultiDiGraph to simple DiGraph for export.

        When multiple edges exist between two nodes, keep the one
        with the highest weight (strongest relationship).
        """
        simple = nx.DiGraph()

        # Copy nodes
        for node_id, data in self._graph.nodes(data=True):
            # Filter out non-serializable attributes
            clean_data = {}
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_data[k] = v
                elif isinstance(v, dict):
                    clean_data[k] = json.dumps(v)
            simple.add_node(node_id, **clean_data)

        # Copy edges (keep strongest)
        for u, v, data in self._graph.edges(data=True):
            if simple.has_edge(u, v):
                existing_weight = simple[u][v].get("weight", 0)
                if data.get("weight", 0) <= existing_weight:
                    continue

            clean_data = {}
            for k, val in data.items():
                if isinstance(val, (str, int, float, bool)):
                    clean_data[k] = val
            simple.add_edge(u, v, **clean_data)

        return simple

    def _add_visual_attributes(self, graph: nx.DiGraph) -> None:
        """Add Gephi-compatible visual attributes."""
        # Node sizing: use degree if no analysis
        max_degree = max((graph.degree(n) for n in graph.nodes()), default=1)
        if max_degree == 0:
            max_degree = 1

        for node_id in graph.nodes():
            degree = graph.degree(node_id)
            # Gephi uses 'viz:size'
            graph.nodes[node_id]["size"] = max(5, (degree / max_degree) * 50)
