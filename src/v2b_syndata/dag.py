"""DAG topology + sampler registry.

Nodes are sampled in topological order. Each sampler reads the current
ScenarioContext and writes its output back to it (latents, a_user, a_fleet,
rendered, etc.).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import networkx as nx

from .types import ScenarioContext

# (node_name, list_of_parents)
NODE_TOPOLOGY: list[tuple[str, list[str]]] = [
    # Tier 1 roots — exogenous bundles
    ("C", []),
    ("W", []),
    ("A", []),
    ("S", []),
    ("O", []),
    ("T", []),
    ("U", []),
    ("F", []),
    ("X", []),
    # Tier 1.5 — per-entity instantiation
    ("A_user", ["U"]),
    ("A_fleet", ["F"]),
    # Tier 2 — latents
    ("L_flex", ["A", "S", "W", "O"]),
    ("L_inflex", ["A", "S", "O"]),
    ("f_arr", ["A_user"]),
    ("f_dwell", ["A_user"]),
    ("f_soc", ["A_user"]),
    # Tier 3 — renderers
    ("chargers.csv", ["X"]),
    ("grid_prices.csv", ["T"]),
    ("dr_events.csv", ["T", "W", "C", "building_load.csv"]),
    ("users.csv", ["A_user"]),
    ("cars.csv", ["A_fleet"]),
    ("building_load.csv", ["L_flex", "L_inflex"]),
    ("sessions.csv", ["f_arr", "f_dwell", "f_soc", "A_user", "A_fleet", "X", "building_load.csv"]),
]


def build_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    for node, _ in NODE_TOPOLOGY:
        g.add_node(node)
    for node, parents in NODE_TOPOLOGY:
        for p in parents:
            g.add_edge(p, node)
    if not nx.is_directed_acyclic_graph(g):
        cycle = nx.find_cycle(g)
        raise RuntimeError(f"DAG has a cycle: {cycle}")
    return g


def topological_order() -> list[str]:
    g = build_graph()
    # Stable order: lexical fallback for nodes at the same depth makes the
    # execution sequence deterministic across networkx versions.
    return list(nx.lexicographical_topological_sort(g))


SamplerFn = Callable[[ScenarioContext], Any]


class SamplerRegistry:
    """Maps node name → sampler function. Validates against DAG topology."""

    def __init__(self) -> None:
        self._fns: dict[str, SamplerFn] = {}

    def register(self, name: str, fn: SamplerFn) -> None:
        if name in self._fns:
            raise ValueError(f"sampler already registered for {name}")
        self._fns[name] = fn

    def get(self, name: str) -> SamplerFn:
        if name not in self._fns:
            raise KeyError(f"no sampler for {name}")
        return self._fns[name]

    def validate(self, graph: nx.DiGraph) -> None:
        missing = [n for n in graph.nodes if n not in self._fns]
        if missing:
            raise RuntimeError(f"nodes without samplers: {missing}")

    def run(self, ctx: ScenarioContext) -> ScenarioContext:
        graph = build_graph()
        self.validate(graph)
        for node in nx.lexicographical_topological_sort(graph):
            self._fns[node](ctx)
        return ctx
