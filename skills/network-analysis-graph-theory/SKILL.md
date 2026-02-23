---
name: network-analysis-graph-theory
description: "Emet-aware network analysis for investigative intelligence. Maps graph theory concepts to Emet's 7 built-in algorithms, FtM entity graph construction, and multi-format export. Use this skill when interpreting graph analysis results, choosing algorithms for specific investigative questions, or extending Emet's graph capabilities."
---

# Network Analysis for Emet Investigations

## Overview
Emet includes a purpose-built graph analytics engine (`emet/graph/`) that converts FtM entities into NetworkX graphs and runs 7 investigative algorithms. This skill covers when and how to use each algorithm, how to interpret results, and how to extend the engine.

**Do not write raw NetworkX code for standard analysis.** Use Emet's `analyze_graph` tool or `GraphAnalyzer` class directly — they handle FtM conversion, edge weighting, node caps, and result formatting.

## Emet's Graph Pipeline

```
FtM Entities → ftm_loader.py → NetworkX MultiDiGraph → algorithms.py → results
                                                          ↓
                                                     exporters.py → GEXF/D3/Cytoscape/CSV
```

### FtM → Graph Conversion (`ftm_loader.py`)
- 11 FtM relationship schemas automatically mapped to edges
- Ownership, directorship, membership, family, association, etc.
- Weighted edges (ownership percentages, confidence scores)
- 50,000 node cap with warnings
- Entity properties preserved as node attributes

### Available Algorithms

#### 1. Community Detection (`community_detection`)
**What:** Louvain algorithm partitions the network into densely-connected clusters.
**Investigative use:** Reveal distinct groups — corporate clusters, family networks, geographic hubs.
**Interpret:** Communities sharing members with sanctioned entities warrant deeper investigation. Small communities with high internal density may indicate coordinated structures.
**Params:** None required.

#### 2. Centrality Analysis (`centrality`)
**What:** Betweenness + degree centrality for all nodes.
**Investigative use:** Find the most connected entities (degree) and the most critical intermediaries (betweenness).
**Interpret:** High betweenness + low degree = hidden broker. High degree = obvious hub. Entities ranking high on both are key targets.
**Params:** None required.

#### 3. Broker Detection (`bridging_nodes`)
**What:** Identifies nodes that connect otherwise-separate communities.
**Investigative use:** Find nominees, intermediaries, and gatekeepers in ownership networks.
**Interpret:** Brokers between a legitimate company cluster and an offshore cluster are high-priority targets for beneficial ownership investigation.
**Params:** None required.

#### 4. Shortest Path (`shortest_path`)
**What:** Find the minimum-hop connection between two specific entities.
**Investigative use:** "How is the sanctioned person connected to this company?"
**Interpret:** Each hop in the path is a relationship to document. Shorter paths = stronger connection for reporting.
**Params:** `{source: "entity_id_1", target: "entity_id_2"}` (required)

#### 5. Connected Components (`connected_components`)
**What:** Find isolated subnetworks with no connections between them.
**Investigative use:** Determine if entities are in the same network at all. Separate components = no known connection.
**Interpret:** Multiple small components in what should be a single corporate group may indicate hidden ownership layers.
**Params:** None required.

#### 6. PageRank (`pagerank`)
**What:** Google-style importance ranking weighted by incoming connections.
**Investigative use:** Weight-aware influence ranking — entities pointed to by many important entities rank highest.
**Interpret:** High PageRank in ownership networks = entity that many others depend on. In financial networks = entity receiving flows from important sources.
**Params:** None required.

#### 7. Temporal Patterns (`temporal_patterns`)
**What:** Track network evolution over time using entity/relationship timestamps.
**Investigative use:** When did this network form? Did structure change around key events (sanctions designation, regulatory action)?
**Interpret:** Rapid restructuring after a sanctions designation is a strong indicator of evasion. Simultaneous entity creation across jurisdictions suggests coordinated setup.
**Params:** None required.

### Standalone Scoring

#### Shell Company Topology Score
Available via `GraphAnalyzer.shell_company_topology_score(entity_id)`:
- Analyzes structural features: high intermediary count, minimal economic substance, nominee patterns
- Returns 0-1 score with contributing factor breakdown
- Not available through `analyze_graph` tool — call directly from code

## Recommended Analysis Sequences

### Standard Network Investigation
```
1. community_detection → understand overall structure
2. centrality → identify key players within each community
3. bridging_nodes → find intermediaries between communities
4. shortest_path → document specific connections of interest
```

### Sanctions Evasion Network
```
1. community_detection → find clusters around designated entities
2. bridging_nodes → find who connects sanctioned cluster to clean companies
3. shell_company_topology_score → score suspicious entities
4. temporal_patterns → did network restructure after designation?
```

### Corporate Ownership Analysis
```
1. connected_components → are all subsidiaries in one network?
2. community_detection → find ownership clusters
3. centrality → find controlling entities
4. bridging_nodes → find nominee directors connecting clusters
```

## Export Formats

Graph results can be exported through `emet/graph/exporters.py`:

| Format | Tool | Best For |
|--------|------|----------|
| GEXF | `to_gexf("file.gexf")` | Gephi visualization (interactive, presentation-quality) |
| GraphML | `to_graphml("file.graphml")` | Academic tools, yEd |
| D3 JSON | `to_d3_json()` | Web dashboards, interactive browser visualization |
| Cytoscape JSON | `to_cytoscape_json()` | Cytoscape desktop (biological/network science) |
| CSV | `to_csv_files("./output/")` | Spreadsheet analysis, data sharing |

## Extending the Graph Engine

When Emet's built-in algorithms don't cover a specific need:

1. **Add to `algorithms.py`** — not as standalone scripts. This preserves the FtM→graph pipeline.
2. **Follow the pattern:** Each algorithm is a method on `GraphAnalyzer` that returns a typed result dataclass.
3. **Use the existing graph:** `self._graph` is a NetworkX MultiDiGraph with FtM properties on nodes/edges.
4. **Register in tools.py:** Add the algorithm name to the `analyze_graph` tool's algorithm enum.

### Pattern for New Algorithm
```python
@dataclass
class NewResult:
    """Result from new_algorithm."""
    findings: list[dict]

class GraphAnalyzer:
    def find_new_thing(self, **params) -> NewResult:
        """Docstring explaining investigative purpose."""
        # Use self._graph (NetworkX MultiDiGraph)
        # Return typed result
```

## Interpreting Results for Reports

When writing investigation reports based on graph analysis:

- **Community detection:** "The network contains N distinct clusters. Cluster A includes [sanctioned entity] alongside [company names], suggesting..."
- **Centrality:** "[Entity] is the most connected node (degree N) and ranks highest in betweenness centrality, indicating it serves as a critical intermediary..."
- **Brokers:** "[Nominee Director] bridges the legitimate UK operations and the offshore BVI structure, appearing in N% of shortest paths between the two clusters..."
- **Shell scores:** "[Company] scores 0.85 on shell company topology indicators due to [factors], warranting beneficial ownership investigation..."

Always cite the algorithm used and the specific metrics. Graph findings are structural evidence — they show *patterns* that warrant investigation, not proof of wrongdoing.
