
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import networkx as nx

from validate_topology import validate_topology


ROOT = Path(__file__).resolve().parents[1]


def get_positions(G):
    """Positionner les équipements selon la hiérarchie réseau."""

    distribution = sorted(
        n for n, d in G.nodes(data=True)
        if d.get("layer") == "distribution"
    )

    access = sorted(
        n for n, d in G.nodes(data=True)
        if d.get("layer") == "access"
    )

    pos = {}

    # Couche distribution
    for i, node in enumerate(distribution):
        x = (i - (len(distribution) - 1) / 2) * 3.5
        pos[node] = (x, 4)

    # Couche accès et équipements terminaux
    for i, node in enumerate(access):
        x = (i - (len(access) - 1) / 2) * 3.6
        pos[node] = (x, 2)

        hosts = sorted(
            n for n in G.neighbors(node)
            if G.nodes[n].get("type") == "host"
        )

        for j, host in enumerate(hosts):
            hx = x + (j - (len(hosts) - 1) / 2) * 1.7
            pos[host] = (hx, 0)

    # Équipements non couverts par la hiérarchie standard
    remaining = [n for n in G if n not in pos]

    for i, node in enumerate(remaining):
        x = (i - (len(remaining) - 1) / 2) * 2.2
        pos[node] = (x, -2)

    return pos


def visualize(topology_path):
    G = validate_topology(topology_path)
    pos = get_positions(G)

    bridges = list(nx.bridges(G))
    critical = {frozenset(edge) for edge in bridges}

    other_links = [
        edge for edge in G.edges()
        if frozenset(edge) not in critical
    ]

    distribution = [
        n for n, d in G.nodes(data=True)
        if d.get("layer") == "distribution"
    ]

    access = [
        n for n, d in G.nodes(data=True)
        if d.get("layer") == "access"
    ]

    hosts = [
        n for n, d in G.nodes(data=True)
        if d.get("type") == "host"
    ]

    fig, ax = plt.subplots(
        figsize=(max(12, len(access) * 3.2), 7)
    )

    # Liens non critiques
    nx.draw_networkx_edges(
        G, pos, edgelist=other_links,
        edge_color="#60A5FA", width=2.5, ax=ax
    )

    # Bridges : suppression = déconnexion du graphe
    nx.draw_networkx_edges(
        G, pos, edgelist=bridges,
        edge_color="#D97706", width=2.5, ax=ax
    )

    for nodes, color, size in [
        (distribution, "#1E3A8A", 950),
        (access, "#3B82F6", 950),
        (hosts, "#0D9488", 800),
    ]:
        nx.draw_networkx_nodes(
            G, pos, nodelist=nodes,
            node_color=color, node_size=size, ax=ax
        )

    # Étiquettes sous les équipements
    label_positions = {
        n: (x, y - 0.42)
        for n, (x, y) in pos.items()
    }

    nx.draw_networkx_labels(
        G, label_positions,
        font_size=8, font_weight="bold",
        font_color="#1F2937", ax=ax,
        bbox={
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.9,
            "pad": 0.2,
        }
    )

    legend = [
        Line2D([0], [0], color="#60A5FA", lw=3,
               label="Lien non critique"),
        Line2D([0], [0], color="#D97706", lw=3,
               label="Lien critique (bridge)"),
    ]

    ax.legend(handles=legend, loc="upper right")

    ax.set_title(
        f"SmartMall — {topology_path.stem.upper()} Topology\n"
        f"{G.number_of_nodes()} nodes | "
        f"{G.number_of_edges()} links | "
        f"{len(bridges)} bridges",
        fontsize=15,
        pad=20
    )

    ax.margins(0.15)
    ax.axis("off")

    output = ROOT / "docs" / f"topology_{topology_path.stem}.png"

    plt.savefig(
        output, dpi=220,
        bbox_inches="tight",
        facecolor="white"
    )
    plt.close()

    print(f"\nVisualization saved: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("topology", type=Path)
    args = parser.parse_args()

    visualize(args.topology)
