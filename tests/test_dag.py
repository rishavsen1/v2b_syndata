"""DAG topology tests."""
from __future__ import annotations

import networkx as nx

from v2b_syndata.dag import build_graph, topological_order
from v2b_syndata.runner import build_registry


def test_dag_is_acyclic():
    g = build_graph()
    assert nx.is_directed_acyclic_graph(g)


def test_topo_order_includes_all_nodes():
    g = build_graph()
    order = topological_order()
    assert set(order) == set(g.nodes)


def test_topo_order_respects_parents():
    g = build_graph()
    order = topological_order()
    pos = {n: i for i, n in enumerate(order)}
    for u, v in g.edges:
        assert pos[u] < pos[v], f"{u} -> {v} violated by topo sort"


def test_every_node_has_registered_sampler():
    reg = build_registry()
    g = build_graph()
    reg.validate(g)


def test_a_user_parents_include_u():
    g = build_graph()
    assert "U" in list(g.predecessors("A_user"))
