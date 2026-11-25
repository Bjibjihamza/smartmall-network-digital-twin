import json
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "topologies" / "small.json"

with open(path, encoding="utf-8-sig") as f:
    topology = json.load(f)

G = nx.Graph()

for node in topology["nodes"]:
    G.add_node(node["id"], **node)

for link in topology["links"]:
    G.add_edge(
        link["source"],
        link["target"],
        **link
    )

expected_nodes = {node["id"] for node in topology["nodes"]}

print("Topology:", topology["topology_id"])
print("Nodes:", G.number_of_nodes())
print("Links:", G.number_of_edges())
print("Valid endpoints:", set(G.nodes) == expected_nodes)
print("Connected:", nx.is_connected(G))
print("Has cycles:", len(nx.cycle_basis(G)) > 0)
print("Is tree:", nx.is_tree(G))