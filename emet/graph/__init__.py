"""Emet Graph Analytics Engine.

Builds NetworkX graphs from FtM entities and runs investigative
algorithms to surface hidden connections, central actors, circular
ownership, and structural anomalies.

Usage::

    from emet.graph import GraphEngine, InvestigativeAnalysis

    engine = GraphEngine()
    graph = engine.build_from_entities(ftm_entities)

    analysis = InvestigativeAnalysis(graph)
    brokers = analysis.find_brokers(top_n=10)
    communities = analysis.find_communities()
    cycles = analysis.find_circular_ownership()
"""

from emet.graph.engine import GraphEngine
from emet.graph.algorithms import InvestigativeAnalysis
from emet.graph.ftm_loader import FtMGraphLoader
from emet.graph.exporters import GraphExporter

__all__ = [
    "GraphEngine",
    "InvestigativeAnalysis",
    "FtMGraphLoader",
    "GraphExporter",
]
