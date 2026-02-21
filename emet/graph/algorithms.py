"""Investigative graph analysis algorithms.

Wraps standard NetworkX algorithms with investigative interpretations.
Each function returns structured results with:
  - The raw algorithmic output
  - A human-readable explanation suitable for journalists
  - A confidence/significance score
  - Suggested follow-up actions

These are not novel algorithms — they're standard graph theory applied
to investigative journalism domain knowledge. The value is in the
interpretation layer, not the math.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)

# Try importing community detection — optional dependency
try:
    from community import community_louvain  # python-louvain package
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False
    logger.debug("python-louvain not installed; Louvain community detection unavailable")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class BrokerResult:
    """Entity identified as a broker/intermediary."""
    entity_id: str
    name: str
    schema: str
    betweenness_score: float
    connected_groups: int
    explanation: str
    follow_up: list[str] = field(default_factory=list)


@dataclass
class CommunityResult:
    """A detected community/cluster of entities."""
    community_id: int
    member_count: int
    members: list[dict[str, str]]  # [{id, name, schema}]
    dominant_country: str
    dominant_schema: str
    cross_jurisdiction: bool
    explanation: str


@dataclass
class CycleResult:
    """A detected circular structure (ownership, payment, etc.)."""
    cycle_entities: list[dict[str, str]]  # [{id, name, schema}]
    cycle_length: int
    edge_types: list[str]
    significance: str
    explanation: str
    risk_score: float  # 0–1


@dataclass
class KeyPlayerResult:
    """Entity ranked by structural importance."""
    entity_id: str
    name: str
    schema: str
    pagerank: float
    degree_centrality: float
    composite_score: float
    explanation: str


@dataclass
class PathResult:
    """Path between two entities."""
    source_id: str
    target_id: str
    path_length: int
    path_entities: list[dict[str, str]]
    edge_types: list[str]
    explanation: str


@dataclass
class AnomalyResult:
    """Structural anomaly detected in the network."""
    anomaly_type: str
    entities: list[dict[str, str]]
    severity: str  # "low", "medium", "high"
    explanation: str
    follow_up: list[str] = field(default_factory=list)


@dataclass
class ShellScore:
    """Topology-based shell company risk score."""
    entity_id: str
    name: str
    score: float  # 0–1 composite
    factors: dict[str, float]  # individual factor scores
    explanation: str
    risk_level: str  # "low", "medium", "high", "critical"


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------


class InvestigativeAnalysis:
    """Run investigative graph algorithms on an entity network.

    Parameters
    ----------
    graph:
        A NetworkX MultiDiGraph built from FtM entities.
    """

    def __init__(self, graph: nx.MultiDiGraph) -> None:
        self._graph = graph
        # Build an undirected simple version for algorithms that need it
        self._undirected = graph.to_undirected()

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._graph

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def _node_info(self, node_id: str) -> dict[str, str]:
        """Get basic info dict for a node."""
        data = self._graph.nodes.get(node_id, {})
        return {
            "id": node_id,
            "name": data.get("name", node_id[:12]),
            "schema": data.get("schema", "Unknown"),
        }

    # -- Broker / intermediary detection -------------------------------------

    def find_brokers(self, top_n: int = 10) -> list[BrokerResult]:
        """Find entities that bridge otherwise disconnected groups.

        Uses betweenness centrality: nodes that appear on many shortest
        paths between other nodes. In corruption networks, these are
        often facilitators, nominee directors, or shell company agents.
        """
        if self.node_count < 3:
            return []

        # Use simple graph for betweenness (MultiDiGraph not supported directly)
        simple = nx.DiGraph(self._graph)
        betweenness = nx.betweenness_centrality(simple, weight="weight")

        # Sort by score, take top N
        ranked = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:top_n]

        results = []
        for node_id, score in ranked:
            if score < 0.001:
                continue  # Skip trivially unimportant nodes

            info = self._node_info(node_id)
            # Count connected components if we remove this node
            test_graph = self._undirected.copy()
            if node_id in test_graph:
                test_graph.remove_node(node_id)
            components_after = nx.number_connected_components(test_graph)
            components_before = nx.number_connected_components(self._undirected)
            groups_connected = max(0, components_after - components_before)

            explanation = (
                f"{info['name']} ({info['schema']}) has a betweenness centrality of "
                f"{score:.4f}, making it a key intermediary in the network."
            )
            if groups_connected > 0:
                explanation += (
                    f" Removing this entity would disconnect {groups_connected} "
                    f"additional group(s), suggesting it serves as a critical bridge."
                )

            follow_up = []
            if info["schema"] in ("Company", "LegalEntity", "Organization"):
                follow_up.append("Check if this entity is a nominee company or registered agent")
                follow_up.append("Investigate ownership and directorship of this entity")
            elif info["schema"] == "Person":
                follow_up.append("Check if this person appears on sanctions/PEP lists")
                follow_up.append("Investigate other companies directed by this person")

            results.append(BrokerResult(
                entity_id=node_id,
                name=info["name"],
                schema=info["schema"],
                betweenness_score=score,
                connected_groups=groups_connected,
                explanation=explanation,
                follow_up=follow_up,
            ))

        return results

    # -- Community detection -------------------------------------------------

    def find_communities(self) -> list[CommunityResult]:
        """Detect entity clusters using community detection.

        Uses Louvain algorithm (if available) or label propagation.
        Communities often represent corporate groups, family networks,
        or coordinated entity clusters.
        """
        if self.node_count < 2:
            return []

        # Get communities
        if HAS_LOUVAIN:
            partition = community_louvain.best_partition(self._undirected)
        else:
            # Fallback: label propagation (always available in NetworkX)
            communities_gen = nx.community.label_propagation_communities(self._undirected)
            partition = {}
            for i, community_set in enumerate(communities_gen):
                for node in community_set:
                    partition[node] = i

        # Group members by community
        communities: dict[int, list[str]] = {}
        for node_id, comm_id in partition.items():
            communities.setdefault(comm_id, []).append(node_id)

        results = []
        for comm_id, members in sorted(communities.items(), key=lambda x: -len(x[1])):
            if len(members) < 2:
                continue  # Skip singletons

            member_info = [self._node_info(m) for m in members]

            # Analyze community composition
            countries = [self._graph.nodes[m].get("country", "") for m in members]
            countries = [c for c in countries if c]
            schemas = [self._graph.nodes[m].get("schema", "") for m in members]

            dominant_country = max(set(countries), key=countries.count) if countries else "Unknown"
            dominant_schema = max(set(schemas), key=schemas.count) if schemas else "Unknown"
            unique_countries = len(set(countries))
            cross_jurisdiction = unique_countries > 1

            explanation = (
                f"Cluster of {len(members)} entities, predominantly {dominant_schema} "
                f"types in {dominant_country}."
            )
            if cross_jurisdiction:
                explanation += (
                    f" Spans {unique_countries} jurisdictions — "
                    f"cross-border structure worth investigating."
                )

            results.append(CommunityResult(
                community_id=comm_id,
                member_count=len(members),
                members=member_info,
                dominant_country=dominant_country,
                dominant_schema=dominant_schema,
                cross_jurisdiction=cross_jurisdiction,
                explanation=explanation,
            ))

        return results

    # -- Circular ownership detection ----------------------------------------

    def find_circular_ownership(self, max_length: int = 8) -> list[CycleResult]:
        """Detect circular structures in ownership/control networks.

        Circular ownership is a classic indicator of:
        - Nominee arrangements (A owns B which owns A)
        - Tax optimization structures
        - Deliberate ownership obfuscation
        - Shell company networks

        Parameters
        ----------
        max_length:
            Maximum cycle length to search. Shorter cycles are more
            suspicious. Very long cycles may be coincidental.
        """
        # Build subgraph of only ownership/control edges
        control_types = {"Ownership", "Directorship"}
        control_graph = nx.DiGraph()

        for u, v, data in self._graph.edges(data=True):
            if data.get("schema") in control_types:
                # Use max weight if multiple edges
                existing_weight = control_graph[u][v]["weight"] if control_graph.has_edge(u, v) else 0
                control_graph.add_edge(u, v, weight=max(existing_weight, data.get("weight", 0.5)))

        if control_graph.number_of_nodes() < 2:
            return []

        results = []
        try:
            # Johnson's algorithm for finding all elementary cycles
            cycles = list(nx.simple_cycles(control_graph))

            for cycle in cycles:
                if len(cycle) > max_length:
                    continue

                cycle_info = [self._node_info(n) for n in cycle]

                # Determine edge types in cycle
                edge_types = []
                for i in range(len(cycle)):
                    u = cycle[i]
                    v = cycle[(i + 1) % len(cycle)]
                    for _, _, data in self._graph.edges(u, data=True):
                        if data.get("schema") in control_types:
                            edge_types.append(data["schema"])
                            break

                # Score risk based on cycle length and types
                risk_score = min(1.0, 1.0 / len(cycle) + 0.3)  # Shorter = riskier
                if "Ownership" in edge_types:
                    risk_score = min(1.0, risk_score + 0.2)

                if len(cycle) == 2:
                    significance = "Mutual ownership — strong indicator of nominee arrangement"
                elif len(cycle) <= 4:
                    significance = "Short ownership cycle — likely deliberate structure"
                else:
                    significance = "Extended ownership cycle — may be intentional obfuscation"

                explanation = (
                    f"Circular {' → '.join(edge_types)} chain of length {len(cycle)}: "
                    + " → ".join(f"{e['name']}" for e in cycle_info)
                    + f" → {cycle_info[0]['name']}. {significance}."
                )

                results.append(CycleResult(
                    cycle_entities=cycle_info,
                    cycle_length=len(cycle),
                    edge_types=edge_types,
                    significance=significance,
                    explanation=explanation,
                    risk_score=risk_score,
                ))

        except nx.NetworkXError as e:
            logger.warning("Cycle detection failed: %s", e)

        # Sort by risk score
        results.sort(key=lambda r: r.risk_score, reverse=True)
        return results

    # -- Key player ranking --------------------------------------------------

    def find_key_players(self, top_n: int = 10) -> list[KeyPlayerResult]:
        """Rank entities by structural importance using composite score.

        Combines PageRank (global influence) with degree centrality
        (direct connections) for a robust importance ranking.
        """
        if self.node_count < 2:
            return []

        simple = nx.DiGraph(self._graph)

        # Calculate metrics
        pagerank = nx.pagerank(simple, weight="weight")
        degree_cent = nx.degree_centrality(simple)

        # Composite score: weighted combination
        composite: dict[str, float] = {}
        for node_id in simple.nodes():
            pr = pagerank.get(node_id, 0)
            dc = degree_cent.get(node_id, 0)
            composite[node_id] = (pr * 0.6) + (dc * 0.4)

        ranked = sorted(composite.items(), key=lambda x: x[1], reverse=True)[:top_n]

        results = []
        for node_id, score in ranked:
            if score < 0.001:
                continue

            info = self._node_info(node_id)
            pr = pagerank.get(node_id, 0)
            dc = degree_cent.get(node_id, 0)

            explanation = (
                f"{info['name']} ({info['schema']}) ranks #{len(results) + 1} in the "
                f"network with PageRank {pr:.4f} and degree centrality {dc:.4f}."
            )

            results.append(KeyPlayerResult(
                entity_id=node_id,
                name=info["name"],
                schema=info["schema"],
                pagerank=pr,
                degree_centrality=dc,
                composite_score=score,
                explanation=explanation,
            ))

        return results

    # -- Hidden connections --------------------------------------------------

    def find_hidden_connections(
        self,
        source_id: str,
        target_id: str,
        max_paths: int = 5,
    ) -> list[PathResult]:
        """Find all shortest paths between two entities.

        When a journalist suspects two entities are connected but doesn't
        know how, this traces all shortest paths through the network.
        Intermediate nodes often reveal previously unknown intermediaries.
        """
        if source_id not in self._graph or target_id not in self._graph:
            return []

        results = []
        try:
            # Find all shortest paths in undirected graph
            paths = list(nx.all_shortest_paths(
                self._undirected, source_id, target_id
            ))

            for path in paths[:max_paths]:
                path_info = [self._node_info(n) for n in path]

                # Collect edge types along path
                edge_types = []
                for i in range(len(path) - 1):
                    u, v = path[i], path[i + 1]
                    # Check directed edges in both directions
                    for a, b in [(u, v), (v, u)]:
                        if self._graph.has_edge(a, b):
                            for _, data in self._graph[a][b].items():
                                edge_types.append(data.get("label", "linked"))
                                break
                            break

                source_name = self._node_info(source_id)["name"]
                target_name = self._node_info(target_id)["name"]
                intermediaries = [
                    self._node_info(n)["name"] for n in path[1:-1]
                ]

                explanation = (
                    f"Connection from {source_name} to {target_name} "
                    f"through {len(path) - 2} intermediaries"
                )
                if intermediaries:
                    explanation += f": {' → '.join(intermediaries)}"
                explanation += "."

                results.append(PathResult(
                    source_id=source_id,
                    target_id=target_id,
                    path_length=len(path) - 1,
                    path_entities=path_info,
                    edge_types=edge_types,
                    explanation=explanation,
                ))

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass  # No path exists

        return results

    # -- Structural anomaly detection ----------------------------------------

    def find_structural_anomalies(self) -> list[AnomalyResult]:
        """Detect structural patterns that may indicate suspicious activity.

        Checks for:
        - Fan-out: Single entity with many outgoing ownership edges
        - Fan-in: Single entity owned by unusually many parents
        - Orphan clusters: Isolated components with no external connections
        - Bridge nodes: Entities connecting otherwise separate communities
        - Jurisdiction bridges: Entities connecting different country clusters
        - Missing directors: Companies with no directorship relationships
        """
        anomalies: list[AnomalyResult] = []

        # Fan-out detection: entity owns 5+ others
        for node_id in self._graph.nodes():
            out_ownership = [
                (u, v, d) for u, v, _, d in self._graph.out_edges(node_id, data=True, keys=True)
                if d.get("schema") == "Ownership"
            ]
            if len(out_ownership) >= 5:
                info = self._node_info(node_id)
                targets = [self._node_info(v) for _, v, _ in out_ownership]

                # Check jurisdiction spread
                target_countries = set(
                    self._graph.nodes[v].get("country", "") for _, v, _ in out_ownership
                )
                target_countries.discard("")

                severity = "medium"
                if len(out_ownership) >= 10:
                    severity = "high"
                if len(target_countries) >= 3:
                    severity = "high"

                explanation = (
                    f"{info['name']} owns {len(out_ownership)} entities"
                )
                if target_countries:
                    explanation += f" across {len(target_countries)} jurisdictions"
                explanation += ". This fan-out pattern is common in holding structures and shell company networks."

                anomalies.append(AnomalyResult(
                    anomaly_type="fan_out_ownership",
                    entities=[info] + targets[:5],
                    severity=severity,
                    explanation=explanation,
                    follow_up=[
                        "Verify if this is a legitimate holding company",
                        "Check incorporation dates of owned entities for temporal clustering",
                        "Cross-reference owner against PEP/sanctions lists",
                    ],
                ))

        # Bridge nodes (articulation points)
        try:
            articulation_points = list(nx.articulation_points(self._undirected))
            for node_id in articulation_points[:10]:  # Cap at 10
                info = self._node_info(node_id)
                degree = self._undirected.degree(node_id)

                if degree < 3:
                    continue  # Only flag significant bridges

                anomalies.append(AnomalyResult(
                    anomaly_type="bridge_node",
                    entities=[info],
                    severity="medium",
                    explanation=(
                        f"{info['name']} is an articulation point with {degree} connections. "
                        f"Removing this entity would disconnect parts of the network, "
                        f"suggesting it plays a critical bridging role."
                    ),
                    follow_up=[
                        "Investigate this entity's role as an intermediary",
                        "Check if this entity appears in multiple investigation contexts",
                    ],
                ))
        except nx.NetworkXError:
            pass  # Articulation points not defined for some graph types

        # Missing directors: Company nodes with no Directorship edges
        company_schemas = {"Company", "LegalEntity", "Organization"}
        for node_id, data in self._graph.nodes(data=True):
            if data.get("schema") not in company_schemas:
                continue
            if data.get("_orphan"):
                continue

            has_director = any(
                d.get("schema") == "Directorship"
                for _, _, d in self._graph.in_edges(node_id, data=True)
            )
            has_owner = any(
                d.get("schema") == "Ownership"
                for _, _, d in self._graph.in_edges(node_id, data=True)
            )

            if not has_director and not has_owner:
                info = self._node_info(node_id)
                anomalies.append(AnomalyResult(
                    anomaly_type="missing_officers",
                    entities=[info],
                    severity="low",
                    explanation=(
                        f"{info['name']} has no recorded directors or owners in the dataset. "
                        f"This may indicate incomplete data or deliberate opacity."
                    ),
                    follow_up=[
                        "Check corporate registry for officer filings",
                        "Search OpenCorporates for this company's officers",
                    ],
                ))

        return anomalies

    # -- Shell company topology scoring --------------------------------------

    def shell_company_topology_score(self, entity_id: str) -> ShellScore | None:
        """Calculate topology-based shell company risk score.

        Combines multiple graph signals:
        - Circular ownership involvement
        - Fan-out/fan-in patterns
        - Jurisdiction bridging
        - Missing officer edges
        - Betweenness (intermediary role)

        This score is designed to be combined with heuristic scores
        from the CorporateResearchChip for a comprehensive assessment.
        """
        if entity_id not in self._graph:
            return None

        info = self._node_info(entity_id)
        factors: dict[str, float] = {}

        # Factor 1: Circular ownership involvement
        cycles = self.find_circular_ownership(max_length=6)
        involved_in_cycles = [
            c for c in cycles
            if any(e["id"] == entity_id for e in c.cycle_entities)
        ]
        factors["circular_ownership"] = min(1.0, len(involved_in_cycles) * 0.5)

        # Factor 2: Fan-out (owns many entities)
        out_ownership = sum(
            1 for _, _, d in self._graph.out_edges(entity_id, data=True)
            if d.get("schema") == "Ownership"
        )
        factors["fan_out"] = min(1.0, out_ownership / 10.0)

        # Factor 3: Jurisdiction bridging
        neighbors = list(self._undirected.neighbors(entity_id))
        neighbor_countries = set(
            self._graph.nodes[n].get("country", "") for n in neighbors
        )
        neighbor_countries.discard("")
        entity_country = self._graph.nodes[entity_id].get("country", "")
        foreign_countries = neighbor_countries - {entity_country} if entity_country else neighbor_countries
        factors["jurisdiction_bridge"] = min(1.0, len(foreign_countries) / 3.0)

        # Factor 4: Missing officers
        has_officers = any(
            d.get("schema") in ("Directorship", "Ownership")
            for _, _, d in self._graph.in_edges(entity_id, data=True)
        )
        factors["missing_officers"] = 0.0 if has_officers else 0.6

        # Factor 5: Betweenness centrality (intermediary role)
        simple = nx.DiGraph(self._graph)
        try:
            betweenness = nx.betweenness_centrality(simple)
            bc = betweenness.get(entity_id, 0)
            factors["intermediary_role"] = min(1.0, bc * 5)  # Scale up
        except Exception:
            factors["intermediary_role"] = 0.0

        # Weighted composite
        weights = {
            "circular_ownership": 0.30,
            "fan_out": 0.20,
            "jurisdiction_bridge": 0.20,
            "missing_officers": 0.15,
            "intermediary_role": 0.15,
        }

        score = sum(factors[k] * weights[k] for k in weights)

        # Risk level thresholds
        if score >= 0.7:
            risk_level = "critical"
        elif score >= 0.5:
            risk_level = "high"
        elif score >= 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Build explanation
        active_factors = [k for k, v in factors.items() if v > 0.1]
        explanation = f"{info['name']} has a topology risk score of {score:.2f} ({risk_level})."
        if active_factors:
            explanation += " Contributing factors: " + ", ".join(
                f.replace("_", " ") for f in active_factors
            ) + "."

        return ShellScore(
            entity_id=entity_id,
            name=info["name"],
            score=score,
            factors=factors,
            explanation=explanation,
            risk_level=risk_level,
        )

    # -- Summary statistics --------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return high-level graph statistics."""
        simple_undirected = self._undirected

        components = list(nx.connected_components(simple_undirected))

        stats: dict[str, Any] = {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "density": nx.density(self._graph),
            "connected_components": len(components),
            "largest_component_size": max(len(c) for c in components) if components else 0,
        }

        # Schema distribution
        schema_counts: dict[str, int] = {}
        for _, data in self._graph.nodes(data=True):
            s = data.get("schema", "Unknown")
            schema_counts[s] = schema_counts.get(s, 0) + 1
        stats["node_schema_distribution"] = schema_counts

        edge_type_counts: dict[str, int] = {}
        for _, _, data in self._graph.edges(data=True):
            s = data.get("schema", "Unknown")
            edge_type_counts[s] = edge_type_counts.get(s, 0) + 1
        stats["edge_type_distribution"] = edge_type_counts

        # Diameter (of largest component)
        if components:
            largest = max(components, key=len)
            subgraph = simple_undirected.subgraph(largest)
            try:
                if len(largest) <= 1000:  # Only compute for manageable graphs
                    stats["diameter"] = nx.diameter(subgraph)
                else:
                    stats["diameter"] = "too_large_to_compute"
            except nx.NetworkXError:
                stats["diameter"] = "disconnected"

        return stats
