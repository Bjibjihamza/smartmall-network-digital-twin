
import json
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / "topologies" / "small.json", encoding="utf-8-sig") as f:
    topology = json.load(f)

G = nx.Graph()

for node in topology["nodes"]:
    G.add_node(node["id"], **node)

for link in topology["links"]:
    G.add_edge(link["source"], link["target"], **link)

# Positions représentant la hiérarchie du réseau
pos = {
    "DSW-1": (0, 3),
    "SW-ADM": (-2, 2),
    "SW-COM": (2, 2),
    "PC-ADM": (-3, 0.5),
    "SRV-LOCAL": (-1, 0.5),
    "PC-SHOP": (1, 0.5),
    "POS": (3, 0.5),
}

switches = [
    n for n, data in G.nodes(data=True)
    if data["type"] == "switch"
]
hosts = [
    n for n, data in G.nodes(data=True)
    if data["type"] == "host"
]

fig, ax = plt.subplots(figsize=(11, 6))

nx.draw_networkx_edges(G, pos, ax=ax, width=2, edge_color="#94A3B8")

nx.draw_networkx_nodes(
    G, pos, nodelist=switches,
    node_color="#2563EB", node_size=2800, ax=ax
)

nx.draw_networkx_nodes(
    G, pos, nodelist=hosts,
    node_color="#0D9488", node_size=2500, ax=ax
)

nx.draw_networkx_labels(
    G, pos, font_size=9,
    font_weight="bold", font_color="white", ax=ax
)

ax.set_title("SmartMall — SMALL Network Topology", fontsize=16, pad=20)
ax.axis("off")

output = ROOT / "docs" / "topology_small.png"
plt.tight_layout()
plt.savefig(output, dpi=200, bbox_inches="tight")
plt.close()

print(f"Topology visualization saved: {output}")
