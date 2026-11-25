"""Pure-Python conversion of the SMALL dataset into per-window graph snapshots.

No torch / PyG dependency: returns plain dicts with node/edge feature matrices
(lists) in the index order of graph_schema.json, ready to be wrapped by a GNN
framework in the Data Engineering phase. Labels are returned separately and
only on request.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

EDGE_FEATURES = ["rx_mbps", "tx_mbps", "rx_pps", "tx_pps", "rx_dropped_delta", "tx_dropped_delta",
                 "qdisc_drops_delta", "qdisc_backlog_pkts"]
RESTRICTED_EDGE_FEATURES = ["admin_up", "carrier", "oper_up"]
NODE_FEATURES = ["probe_reachable_fraction", "probe_route_unreachable_fraction",
                 "probe_mean_rtt_ms", "probe_loss_pct", "total_rx_mbps", "total_tx_mbps"]


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def load_snapshots(dataset_dir, include_restricted=False, with_labels=False, experiments=None):
    """Yield one graph snapshot per (experiment_id, window_id).

    Edge features: for each undirected link, the two directed interface rows
    concatenated in (source-end, target-end) order -> 2 x len(EDGE_FEATURES).
    Node features: probe statistics over pairs involving the node (hosts) and
    total interface throughput (all nodes). Missing values are encoded 0.0 with a
    companion mask in ``edge_mask`` / ``node_mask``.
    """
    d = Path(dataset_dir)
    schema = json.loads((d / "graph_schema.json").read_text(encoding="utf-8"))
    node_ids = [n["node_id"] for n in schema["nodes"]]
    edges = schema["edges"]
    edge_cols = EDGE_FEATURES + (RESTRICTED_EDGE_FEATURES if include_restricted else [])
    intf = defaultdict(dict)
    for r in _rows(d / "interface_window.csv"):
        if experiments and r["experiment_id"] not in experiments:
            continue
        intf[(r["experiment_id"], r["window_id"])][(r["link_id"], r["node_id"])] = r
    pairs = defaultdict(list)
    for r in _rows(d / "pair_window.csv"):
        if experiments and r["experiment_id"] not in experiments:
            continue
        pairs[(r["experiment_id"], r["window_id"])].append(r)
    labels = {}
    if with_labels:
        labels = {(r["experiment_id"], r["window_id"]): r for r in _rows(d / "labels_window.csv")}
    for key in sorted(intf):
        x_edge, m_edge = [], []
        for e in edges:
            vec, mask = [], []
            for end in (e["source"], e["target"]):
                row = intf[key].get((e["link_id"], end), {})
                for c in edge_cols:
                    v = row.get(c, "")
                    vec.append(_f(v))
                    mask.append(int(v not in ("", None)))
            x_edge.append(vec)
            m_edge.append(mask)
        x_node, m_node = [], []
        for n in node_ids:
            involved = [p for p in pairs[key] if n in (p["source_node_id"], p["target_node_id"])]
            rtts = [_f(p["rtt_avg_ms"]) for p in involved if p["rtt_avg_ms"] not in ("", None)]
            losses = [_f(p["loss_pct"]) for p in involved if p["loss_pct"] not in ("", None)]
            own = [r for (link, node), r in intf[key].items() if node == n]
            vec = [
                sum(int(p["reachable"] == "1") for p in involved) / len(involved) if involved else 0.0,
                sum(int(p["route_unreachable"] == "1") for p in involved) / len(involved) if involved else 0.0,
                sum(rtts) / len(rtts) if rtts else 0.0,
                sum(losses) / len(losses) if losses else 0.0,
                sum(_f(r["rx_mbps"]) for r in own),
                sum(_f(r["tx_mbps"]) for r in own),
            ]
            mask = [int(bool(involved)), int(bool(involved)), int(bool(rtts)), int(bool(losses)),
                    int(bool(own)), int(bool(own))]
            x_node.append(vec)
            m_node.append(mask)
        snap = {"experiment_id": key[0], "window_id": key[1], "node_ids": node_ids,
                "edge_index": [[e["source_index"] for e in edges], [e["target_index"] for e in edges]],
                "link_ids": [e["link_id"] for e in edges],
                "x_node": x_node, "node_mask": m_node, "node_feature_names": NODE_FEATURES,
                "x_edge": x_edge, "edge_mask": m_edge,
                "edge_feature_names": [f"{end}.{c}" for end in ("src_end", "dst_end") for c in edge_cols]}
        if with_labels:
            snap["label"] = labels.get(key)
        yield snap
