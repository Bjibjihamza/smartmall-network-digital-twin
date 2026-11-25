
import argparse
import json
from pathlib import Path

import networkx as nx


def validate_topology(file_path: Path):
    with open(file_path, encoding="utf-8-sig") as f:
        topology = json.load(f)

    G = nx.Graph()

    # 1. Ajouter les équipements
    for node in topology["nodes"]:
        node_id = node["id"]

        if node_id in G:
            raise ValueError(f"Duplicate node: {node_id}")

        G.add_node(node_id, **node)

    # 2. Ajouter les liens
    link_ids = set()

    for link in topology["links"]:
        source = link["source"]
        target = link["target"]
        link_id = link["id"]

        if link_id in link_ids:
            raise ValueError(f"Duplicate link ID: {link_id}")
        link_ids.add(link_id)

        if source not in G or target not in G:
            raise ValueError(f"Unknown endpoint in {link_id}")

        if source == target:
            raise ValueError(f"Self-loop: {link_id}")

        if G.has_edge(source, target):
            raise ValueError(f"Duplicate connection: {link_id}")

        if link["bandwidth_mbps"] <= 0 or link["delay_ms"] < 0:
            raise ValueError(f"Invalid link parameters: {link_id}")

        G.add_edge(source, target, **link)

    # 3. Vérifications structurelles
    connected = nx.is_connected(G) if G else False
    cycles = nx.cycle_basis(G)
    bridges = list(nx.bridges(G))

    print(f"\n{'=' * 45}")
    print(f"Topology: {topology['topology_id']}")
    print(f"{'=' * 45}")
    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Links: {G.number_of_edges()}")
    print(f"Connected: {connected}")
    print(f"Cycles: {len(cycles)}")
    print(f"Bridges (critical links): {len(bridges)}")

    print("\nCritical links:")
    for source, target in bridges:
        print(f"  {source} <-> {target}")

    print("\nStructural validation: PASSED")

    return G


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("topology", type=Path)
    args = parser.parse_args()

    validate_topology(args.topology)
