"""Topology helpers (pure Python, no Mininet): reachability under faults, paths."""

from __future__ import annotations

import itertools
import json
from pathlib import Path


def load_spec(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def node_types(spec):
    return {n["id"]: n["type"] for n in spec["nodes"]}


def hosts(spec):
    return sorted(n["id"] for n in spec["nodes"] if n["type"] == "host")


def switches(spec):
    return sorted(n["id"] for n in spec["nodes"] if n["type"] == "switch")


def host_pairs(spec):
    """Canonical probe pairs: unordered, lexicographically sorted (source < target)."""
    return list(itertools.combinations(hosts(spec), 2))


def links_by_id(spec):
    return {link["id"]: link for link in spec["links"]}


def incident_links(spec, node_id):
    return sorted(l["id"] for l in spec["links"] if node_id in (l["source"], l["target"]))


def _components(spec, failed_links=(), failed_nodes=()):
    failed_links = set(failed_links)
    failed_nodes = set(failed_nodes)
    parent = {n["id"]: n["id"] for n in spec["nodes"] if n["id"] not in failed_nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in spec["links"]:
        if link["id"] in failed_links:
            continue
        a, b = link["source"], link["target"]
        if a in failed_nodes or b in failed_nodes:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return {node: find(node) for node in parent}


def reachable_pairs(spec, failed_links=(), failed_nodes=()):
    """Set of host pairs (sorted tuples) with a working path."""
    comp = _components(spec, failed_links, failed_nodes)
    out = set()
    for a, b in host_pairs(spec):
        if a in comp and b in comp and comp[a] == comp[b]:
            out.add((a, b))
    return out


def disrupted_pairs(spec, failed_links=(), failed_nodes=()):
    return set(host_pairs(spec)) - reachable_pairs(spec, failed_links, failed_nodes)


def path_links(spec, source, target):
    """Link IDs on the unique (tree) path between two nodes, in order; None if no path."""
    adjacency = {}
    for link in spec["links"]:
        adjacency.setdefault(link["source"], []).append((link["target"], link["id"]))
        adjacency.setdefault(link["target"], []).append((link["source"], link["id"]))
    stack = [(source, [])]
    seen = {source}
    while stack:
        node, path = stack.pop()
        if node == target:
            return path
        for neighbour, link_id in adjacency.get(node, []):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append((neighbour, path + [link_id]))
    return None


def is_tree(spec):
    nodes = [n["id"] for n in spec["nodes"]]
    comp = _components(spec)
    return len(spec["links"]) == len(nodes) - 1 and len(set(comp.values())) == 1
