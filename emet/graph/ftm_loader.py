"""FtM Entity → NetworkX graph conversion.

FtM's data model is already graph-native: entities are nodes, and
relationship entities (Ownership, Directorship, Payment, etc.) are edges
with their own properties. This module converts between the two
representations.

The critical insight is that FtM "relationship" schemas are entities
themselves, not simple edges. An Ownership entity has its own ID,
dates, percentage, etc. We preserve this metadata on edges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FtM relationship schema → edge semantics
# ---------------------------------------------------------------------------

# Maps FtM relationship schemas to their source/target property names
# and a human-readable label for the edge.
RELATIONSHIP_SCHEMAS: dict[str, dict[str, str]] = {
    "Ownership": {"source": "owner", "target": "asset", "label": "owns"},
    "Directorship": {"source": "director", "target": "organization", "label": "directs"},
    "Membership": {"source": "member", "target": "organization", "label": "member_of"},
    "Employment": {"source": "employee", "target": "employer", "label": "employed_by"},
    "Family": {"source": "person", "target": "relative", "label": "related_to"},
    "Associate": {"source": "person", "target": "associate", "label": "associated_with"},
    "Payment": {"source": "payer", "target": "beneficiary", "label": "paid"},
    "Debt": {"source": "debtor", "target": "creditor", "label": "owes"},
    "Representation": {"source": "agent", "target": "client", "label": "represents"},
    "Succession": {"source": "predecessor", "target": "successor", "label": "succeeded_by"},
    "UnknownLink": {"source": "subject", "target": "object", "label": "linked_to"},
}

# Node schemas — everything that isn't a relationship
# Grouped by investigative category for visualization
NODE_SCHEMA_COLORS: dict[str, str] = {
    # People
    "Person": "#4A90D9",
    "LegalEntity": "#E74C3C",
    "Company": "#E74C3C",
    "Organization": "#E67E22",
    "PublicBody": "#9B59B6",
    # Assets
    "RealEstate": "#2ECC71",
    "Vehicle": "#1ABC9C",
    "Vessel": "#1ABC9C",
    "Airplane": "#1ABC9C",
    # Financial
    "BankAccount": "#F1C40F",
    "CryptoWallet": "#F39C12",
    "Security": "#F1C40F",
    # Documents
    "Document": "#95A5A6",
    "Email": "#95A5A6",
    # Location
    "Address": "#BDC3C7",
}

# Edge weight by relationship type — higher = stronger investigative signal
EDGE_WEIGHTS: dict[str, float] = {
    "Ownership": 1.0,       # Strongest signal — direct control
    "Directorship": 0.9,    # Direct influence
    "Payment": 0.8,         # Financial connection
    "Debt": 0.7,            # Financial obligation
    "Employment": 0.6,      # Organizational tie
    "Representation": 0.6,  # Legal/agent relationship
    "Family": 0.5,          # Personal connection
    "Membership": 0.4,      # Loose organizational tie
    "Associate": 0.3,       # Weakest documented link
    "Succession": 0.3,      # Temporal relationship
    "UnknownLink": 0.2,     # Unknown relationship type
}


# ---------------------------------------------------------------------------
# Graph loader
# ---------------------------------------------------------------------------


@dataclass
class LoadStats:
    """Statistics from a graph loading operation."""

    nodes_loaded: int = 0
    edges_loaded: int = 0
    relationship_entities: int = 0
    orphan_references: int = 0
    schema_counts: dict[str, int] = field(default_factory=dict)
    edge_type_counts: dict[str, int] = field(default_factory=dict)
    skipped_entities: int = 0


class FtMGraphLoader:
    """Convert FtM entity collections into NetworkX graphs.

    Parameters
    ----------
    max_nodes:
        Safety cap on graph size. Prevents memory issues on huge
        collections. Default 50,000 is sufficient for most investigations.
    include_orphan_nodes:
        Whether to create placeholder nodes for entity IDs referenced
        in relationships but not present in the entity list. Default True
        because Aleph collections often have partial data.
    """

    def __init__(
        self,
        max_nodes: int = 50_000,
        include_orphan_nodes: bool = True,
    ) -> None:
        self._max_nodes = max_nodes
        self._include_orphan_nodes = include_orphan_nodes

    def load(self, entities: list[dict[str, Any]]) -> tuple[nx.MultiDiGraph, LoadStats]:
        """Convert a list of FtM entity dicts to a NetworkX graph.

        Parameters
        ----------
        entities:
            List of FtM entity dicts, each with at minimum ``id``,
            ``schema``, and ``properties`` keys.

        Returns
        -------
        Tuple of (graph, load_stats).
        """
        graph = nx.MultiDiGraph()
        stats = LoadStats()

        # Two passes: first collect nodes, then add edges
        node_entities: list[dict[str, Any]] = []
        edge_entities: list[dict[str, Any]] = []

        for entity in entities:
            schema = entity.get("schema", "")
            if schema in RELATIONSHIP_SCHEMAS:
                edge_entities.append(entity)
                stats.relationship_entities += 1
            else:
                node_entities.append(entity)

        # Pass 1: Add nodes
        for entity in node_entities:
            if graph.number_of_nodes() >= self._max_nodes:
                stats.skipped_entities += len(node_entities) - stats.nodes_loaded
                logger.warning(
                    "Node cap reached (%d). Skipping remaining entities.",
                    self._max_nodes,
                )
                break

            self._add_node(graph, entity, stats)

        # Track which node IDs we have
        known_nodes = set(graph.nodes())

        # Pass 2: Add edges from relationship entities
        for entity in edge_entities:
            self._add_edges_from_relationship(graph, entity, known_nodes, stats)

        return graph, stats

    def _add_node(
        self,
        graph: nx.MultiDiGraph,
        entity: dict[str, Any],
        stats: LoadStats,
    ) -> None:
        """Add a single FtM entity as a graph node."""
        eid = entity.get("id", "")
        if not eid:
            stats.skipped_entities += 1
            return

        schema = entity.get("schema", "Thing")
        props = entity.get("properties", {})

        # Extract key properties for node attributes
        names = props.get("name", [])
        name = names[0] if names else eid[:12]

        countries = props.get("country", props.get("jurisdiction", []))
        country = countries[0] if countries else ""

        # Dates for temporal analysis
        dates = {}
        for date_prop in ("incorporationDate", "startDate", "date", "createdAt"):
            vals = props.get(date_prop, [])
            if vals:
                dates[date_prop] = vals[0]

        addresses = props.get("address", props.get("registeredAddress", []))
        address = addresses[0] if addresses else ""

        graph.add_node(
            eid,
            schema=schema,
            name=name,
            country=country,
            address=address,
            dates=dates,
            color=NODE_SCHEMA_COLORS.get(schema, "#95A5A6"),
            properties=props,  # Full FtM properties preserved
            _provenance=entity.get("_provenance", {}),
        )

        stats.nodes_loaded += 1
        stats.schema_counts[schema] = stats.schema_counts.get(schema, 0) + 1

    def _add_edges_from_relationship(
        self,
        graph: nx.MultiDiGraph,
        entity: dict[str, Any],
        known_nodes: set[str],
        stats: LoadStats,
    ) -> None:
        """Add edges from a FtM relationship entity."""
        schema = entity.get("schema", "")
        edge_def = RELATIONSHIP_SCHEMAS.get(schema)
        if not edge_def:
            stats.skipped_entities += 1
            return

        props = entity.get("properties", {})
        sources = props.get(edge_def["source"], [])
        targets = props.get(edge_def["target"], [])

        if not sources or not targets:
            stats.skipped_entities += 1
            return

        # Extract edge metadata
        weight = EDGE_WEIGHTS.get(schema, 0.2)
        dates = {}
        for date_prop in ("startDate", "endDate", "date"):
            vals = props.get(date_prop, [])
            if vals:
                dates[date_prop] = vals[0]

        # Ownership-specific: percentage
        share_pcts = props.get("percentage", props.get("sharesCount", []))
        share_pct = share_pcts[0] if share_pcts else ""

        for source_id in sources:
            for target_id in targets:
                # Create orphan placeholder nodes if needed
                if source_id not in known_nodes:
                    if self._include_orphan_nodes:
                        graph.add_node(
                            source_id,
                            schema="Unknown",
                            name=source_id[:12],
                            country="",
                            address="",
                            dates={},
                            color="#CCCCCC",
                            properties={},
                            _orphan=True,
                        )
                        known_nodes.add(source_id)
                        stats.orphan_references += 1
                    else:
                        continue

                if target_id not in known_nodes:
                    if self._include_orphan_nodes:
                        graph.add_node(
                            target_id,
                            schema="Unknown",
                            name=target_id[:12],
                            country="",
                            address="",
                            dates={},
                            color="#CCCCCC",
                            properties={},
                            _orphan=True,
                        )
                        known_nodes.add(target_id)
                        stats.orphan_references += 1
                    else:
                        continue

                graph.add_edge(
                    source_id,
                    target_id,
                    key=entity.get("id", ""),
                    schema=schema,
                    label=edge_def["label"],
                    weight=weight,
                    dates=dates,
                    share_pct=share_pct,
                    properties=props,
                    entity_id=entity.get("id", ""),
                )

                stats.edges_loaded += 1
                stats.edge_type_counts[schema] = (
                    stats.edge_type_counts.get(schema, 0) + 1
                )
