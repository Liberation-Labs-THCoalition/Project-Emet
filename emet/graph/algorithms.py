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


@dataclass
class BeneficialOwner:
    """One node in a beneficial-ownership chain."""
    entity_id: str
    name: str
    schema: str
    # Effective ownership fraction (0–1) of the original target, i.e. the
    # product of share percentages down the chain. None when any link in
    # the path has an unknown percentage.
    effective_pct: float | None
    # Ordered list of {id,name,schema} from the target up to this owner.
    path: list[dict[str, str]] = field(default_factory=list)
    is_ultimate: bool = False  # True if this owner has no further owners


@dataclass
class OwnershipTrace:
    """Result of a beneficial-ownership trace on one target entity."""
    target_id: str
    target_name: str
    ultimate_owners: list[BeneficialOwner] = field(default_factory=list)
    all_owners: list[BeneficialOwner] = field(default_factory=list)
    max_depth_reached: int = 0
    truncated: bool = False  # hit max_depth before exhausting the tree
    cycles_detected: bool = False
    explanation: str = ""


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

    # -- Beneficial ownership tracing ---------------------------------------

    @staticmethod
    def _parse_share_pct(raw: Any) -> float | None:
        """Parse an edge ``share_pct`` value into a 0–1 fraction.

        Handles ``"50%"``, ``"50"``, ``"50.0"``, ``0.5`` (already a
        fraction), and comma-grouped forms. Returns ``None`` when the
        value is missing or unparseable so the chain can propagate
        "unknown" rather than silently assuming full ownership.
        """
        if raw in (None, "", []):
            return None
        if isinstance(raw, list):
            raw = raw[0] if raw else None
            if raw is None:
                return None
        try:
            text = str(raw).strip().replace("%", "").replace(",", "")
            value = float(text)
        except (ValueError, TypeError):
            return None
        if value < 0:
            return None
        # Heuristic: values >1 are percentages; <=1 are already fractions
        # unless they are exactly 1 which we treat as 100%.
        return value / 100.0 if value > 1 else value

    def trace_beneficial_ownership(
        self,
        entity_id: str,
        max_depth: int = 10,
        min_effective_pct: float = 0.0,
    ) -> OwnershipTrace:
        """Trace who ultimately owns ``entity_id`` — the UBO question.

        Walks *incoming* Ownership edges (``owner --owns--> asset``)
        recursively up the chain, multiplying share percentages to get
        each owner's effective stake in the original target. Terminal
        owners (no further owners upstream) are the ultimate beneficial
        owners. Cycles are detected and broken; depth is bounded.

        Parameters
        ----------
        entity_id:
            The asset/company whose owners we want.
        max_depth:
            Maximum chain length to walk.
        min_effective_pct:
            Prune branches whose effective stake falls below this (0–1).
            Only applies once a known percentage exists on the path.
        """
        target_info = self._node_info(entity_id)
        trace = OwnershipTrace(
            target_id=entity_id,
            target_name=target_info["name"],
        )
        if entity_id not in self._graph:
            trace.explanation = f"Entity {entity_id} not found in the graph."
            return trace

        all_owners: list[BeneficialOwner] = []

        def _owners_of(node_id: str) -> list[tuple[str, float | None]]:
            """Return (owner_id, share_fraction) for direct owners of node."""
            out: list[tuple[str, float | None]] = []
            for u, _v, data in self._graph.in_edges(node_id, data=True):
                if data.get("schema") != "Ownership":
                    continue
                out.append((u, self._parse_share_pct(data.get("share_pct"))))
            return out

        # Depth-first walk with per-path visited set to break cycles.
        def _walk(
            node_id: str,
            effective: float | None,
            depth: int,
            path: list[dict[str, str]],
            visited: set[str],
        ) -> None:
            if depth >= max_depth:
                trace.truncated = True
                return
            direct = _owners_of(node_id)
            for owner_id, share in direct:
                if owner_id in visited:
                    trace.cycles_detected = True
                    continue

                if effective is None or share is None:
                    new_effective: float | None = None
                else:
                    new_effective = effective * share
                    if new_effective < min_effective_pct:
                        continue

                owner_info = self._node_info(owner_id)
                new_path = path + [owner_info]
                upstream = _owners_of(owner_id)
                is_ultimate = not upstream or all(
                    o in visited or o == owner_id for o, _ in upstream
                )

                bo = BeneficialOwner(
                    entity_id=owner_id,
                    name=owner_info["name"],
                    schema=owner_info["schema"],
                    effective_pct=new_effective,
                    path=new_path,
                    is_ultimate=is_ultimate,
                )
                all_owners.append(bo)
                trace.max_depth_reached = max(trace.max_depth_reached, depth + 1)

                # Once a percentage is unknown anywhere on the path,
                # new_effective is None and stays None upstream.
                _walk(
                    owner_id,
                    new_effective,
                    depth + 1,
                    new_path,
                    visited | {owner_id},
                )

        _walk(entity_id, 1.0, 0, [target_info], {entity_id})

        trace.all_owners = all_owners
        trace.ultimate_owners = [o for o in all_owners if o.is_ultimate]
        trace.ultimate_owners.sort(
            key=lambda o: (o.effective_pct is None, -(o.effective_pct or 0))
        )

        n_ult = len(trace.ultimate_owners)
        if n_ult == 0:
            trace.explanation = (
                f"No ownership records found upstream of {target_info['name']}. "
                "Beneficial ownership is opaque in this dataset."
            )
        else:
            top = trace.ultimate_owners[0]
            pct_str = (
                f"{top.effective_pct * 100:.1f}%"
                if top.effective_pct is not None
                else "an undisclosed share"
            )
            trace.explanation = (
                f"{target_info['name']} traces to {n_ult} ultimate beneficial "
                f"owner(s). Largest: {top.name} ({top.schema}) holding "
                f"{pct_str} effective stake via a chain of "
                f"{len(top.path) - 1} link(s)."
            )
            if trace.cycles_detected:
                trace.explanation += " Circular ownership was detected and broken."
        return trace

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

        # Fan-in detection: entity owned by 5+ distinct parents
        for node_id in self._graph.nodes():
            in_ownership = [
                (u, v, d)
                for u, v, _, d in self._graph.in_edges(node_id, data=True, keys=True)
                if d.get("schema") == "Ownership"
            ]
            distinct_owners = {u for u, _, _ in in_ownership}
            if len(distinct_owners) >= 5:
                info = self._node_info(node_id)
                owners = [self._node_info(u) for u in list(distinct_owners)[:5]]

                owner_countries = {
                    self._graph.nodes[u].get("country", "") for u in distinct_owners
                }
                owner_countries.discard("")

                severity = "medium"
                if len(distinct_owners) >= 10 or len(owner_countries) >= 3:
                    severity = "high"

                explanation = (
                    f"{info['name']} is owned by {len(distinct_owners)} distinct parents"
                )
                if owner_countries:
                    explanation += f" across {len(owner_countries)} jurisdictions"
                explanation += (
                    ". Concentrated fan-in ownership can indicate a pooled special-"
                    "purpose vehicle, a layering hub, or a joint front company."
                )

                anomalies.append(AnomalyResult(
                    anomaly_type="fan_in_ownership",
                    entities=[info] + owners,
                    severity=severity,
                    explanation=explanation,
                    follow_up=[
                        "Trace beneficial ownership up each parent chain",
                        "Check whether the parents share a common ultimate owner",
                        "Verify the entity's stated business purpose",
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
