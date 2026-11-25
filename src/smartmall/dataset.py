"""Consolidated SMALL dataset: window-level telemetry tables + separate ground truth.

Design rules (Stage E):
* Feature tables (pair_window, interface_window, flow_window) never contain labels.
* labels_window.csv holds ground truth only; experiments.csv holds identifiers and
  experimental conditions; feature_dictionary.csv classifies EVERY column.
* The primary split unit is the independent experiment. Folds are assigned by
  repetition within each scenario stratum (leave-one-repetition-out), so no
  window of an experiment can appear in two folds.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from . import topology as topo
from .telemetry import counter_deltas

PAIR_FIELDS = ["experiment_id", "window_id", "source_node_id", "target_node_id", "packets_sent",
               "packets_received", "loss_pct", "rtt_avg_ms", "rtt_mdev_ms", "reachable",
               "route_unreachable", "probe_status"]
INTF_FIELDS = ["experiment_id", "window_id", "link_id", "node_id", "peer_node_id", "duration_s",
               "rx_mbps", "tx_mbps", "rx_pps", "tx_pps", "rx_errors_delta", "tx_errors_delta",
               "rx_dropped_delta", "tx_dropped_delta", "counter_reset", "admin_up", "carrier",
               "oper_up", "qdisc_drops_delta", "qdisc_backlog_pkts", "qdisc_overlimits_delta"]
FLOW_FIELDS = ["experiment_id", "window_id", "offered_mbps", "flow_active_fraction", "receiver_mbps",
               "receiver_lost_packets", "receiver_alignment_reliable", "sender_alive_at_window_end"]
LABEL_FIELDS = ["experiment_id", "window_id", "phase", "fault_active", "fault_family", "fault_category",
                "fault_target", "target_kind", "param_added_delay_ms", "param_loss_pct",
                "param_bw_mbps", "param_queue_pkts", "window_start_unix", "window_end_unix",
                "expected_unreachable_pairs"]
EXP_FIELDS = ["experiment_id", "protocol_version", "campaign_id", "scenario_key", "fault_family",
              "fault_target", "offered_mbps", "repetition", "run_seed", "audit", "n_windows",
              "window_s_nominal", "probe_mode", "split_fold", "raw_relative_path"]

FEATURE_DICTIONARY = [
    # table, column, unit, leakage_class, model_input, description
    ("pair_window", "experiment_id", "", "identifier", "no", "Experiment identifier; grouping/split key only"),
    ("pair_window", "window_id", "", "identifier", "no", "Window ID; ordinal encodes phase order in a run"),
    ("pair_window", "source_node_id", "", "graph_key", "key", "Probe source host"),
    ("pair_window", "target_node_id", "", "graph_key", "key", "Probe target host"),
    ("pair_window", "packets_sent", "packets", "observation", "yes", "ICMP echo requests transmitted (0 if route_unreachable)"),
    ("pair_window", "packets_received", "packets", "observation", "yes", "ICMP echo replies received"),
    ("pair_window", "loss_pct", "%", "observation", "yes", "ICMP loss; EMPTY when no packet was sent (never 100%)"),
    ("pair_window", "rtt_avg_ms", "ms", "observation", "yes", "Mean RTT of received replies; empty if none"),
    ("pair_window", "rtt_mdev_ms", "ms", "observation", "yes", "RTT mean deviation (v2 only)"),
    ("pair_window", "reachable", "0/1", "observation", "yes", "At least one reply received"),
    ("pair_window", "route_unreachable", "0/1", "observation", "yes", "Source kernel refused to send (local route/interface down)"),
    ("pair_window", "probe_status", "", "observation", "yes", "icmp_stats | route_unreachable"),
    ("interface_window", "experiment_id", "", "identifier", "no", "Experiment identifier"),
    ("interface_window", "window_id", "", "identifier", "no", "Window ID"),
    ("interface_window", "link_id", "", "graph_key", "key", "Topology link (edge key)"),
    ("interface_window", "node_id", "", "graph_key", "key", "Node owning the interface"),
    ("interface_window", "peer_node_id", "", "graph_key", "key", "Node at the other end of the link"),
    ("interface_window", "duration_s", "s", "observation", "yes", "Counter-delta interval for this interface"),
    ("interface_window", "rx_mbps", "Mb/s", "observation", "yes", "Ingress byte rate incl. headers"),
    ("interface_window", "tx_mbps", "Mb/s", "observation", "yes", "Egress byte rate incl. headers"),
    ("interface_window", "rx_pps", "pkt/s", "observation", "yes", "Ingress packet rate"),
    ("interface_window", "tx_pps", "pkt/s", "observation", "yes", "Egress packet rate"),
    ("interface_window", "rx_errors_delta", "packets", "observation", "yes", "Kernel rx error counter delta"),
    ("interface_window", "tx_errors_delta", "packets", "observation", "yes", "Kernel tx error counter delta"),
    ("interface_window", "rx_dropped_delta", "packets", "observation", "yes", "Kernel rx drop counter delta"),
    ("interface_window", "tx_dropped_delta", "packets", "observation", "yes", "Kernel tx drop counter delta"),
    ("interface_window", "counter_reset", "0/1", "quality_flag", "no", "Counter decreased within window (deltas blanked)"),
    ("interface_window", "admin_up", "0/1", "mechanism_revealing", "restricted",
     "Administrative state AFTER window. Directly set by LINK_FAILURE/NODE_FAILURE injection: reveals the fault location"),
    ("interface_window", "carrier", "0/1", "mechanism_revealing", "restricted",
     "Carrier (no NO-CARRIER flag). Peer-side carrier loss reveals NODE_FAILURE neighbours; v1 rows derive it from operstate"),
    ("interface_window", "oper_up", "0/1", "mechanism_revealing", "restricted", "operstate == UP after window"),
    ("interface_window", "qdisc_drops_delta", "packets", "observation", "yes",
     "Queue (netem leaf) drops in window. Includes netem random loss for LINK_LOSS (v2 only)"),
    ("interface_window", "qdisc_backlog_pkts", "packets", "observation", "yes", "Queue backlog at window end (v2 only)"),
    ("interface_window", "qdisc_overlimits_delta", "events", "observation", "yes", "HTB overlimit events (rate-cap pressure; v2 only)"),
    ("flow_window", "experiment_id", "", "identifier", "no", "Experiment identifier"),
    ("flow_window", "window_id", "", "identifier", "no", "Window ID"),
    ("flow_window", "offered_mbps", "Mb/s", "condition", "conditional",
     "Configured UDP offered load (experimental condition, not a fault label; constant per run)"),
    ("flow_window", "flow_active_fraction", "0..1", "observation", "yes", "Fraction of window with a live sender process"),
    ("flow_window", "receiver_mbps", "Mb/s", "observation", "yes", "iperf3 receiver goodput allocated to window"),
    ("flow_window", "receiver_lost_packets", "packets", "observation", "caution",
     "iperf3 sequence-gap losses; after a disconnection they are attributed when traffic RESUMES, not when lost"),
    ("flow_window", "receiver_alignment_reliable", "0/1", "quality_flag", "no",
     "0 if a transition lies within one receiver interval (0.5 s) of the window boundary"),
    ("flow_window", "sender_alive_at_window_end", "0/1", "observation", "caution",
     "iperf3 client process alive; it aborts when its own interface is down"),
]
LABEL_DICTIONARY = [(c, "ground_truth") for c in LABEL_FIELDS[2:]]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenario_key(fault, target, params, load):
    p = ",".join(f"{k}={v:g}" for k, v in sorted(params.items())) if params else ""
    return f"{fault}|{target or '-'}|{p}|load={load}"


# ------------------------------------------------------------------ v2 (small_scenario_v2)
def convert_v2(folder, campaign_id, audit):
    folder = Path(folder)
    gt = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
    spec = json.loads((folder / "topology.json").read_text(encoding="utf-8-sig"))
    exp_id = gt["experiment_id"]
    sc = gt["scenario"]
    pair = []
    for r in read_rows(folder / "icmp_probes.csv"):
        pair.append({k: r.get(k, "") for k in PAIR_FIELDS if k in r} |
                    {"route_unreachable": int(r["probe_status"] == "route_unreachable")})
    tc = defaultdict(dict)
    for r in read_rows(folder / "tc_samples.csv"):
        tc[(r["window_id"], r["interface_name"])][r["sample_position"]] = r
    intf = []
    for r in read_rows(folder / "port_window_deltas.csv"):
        dur = _f(r["duration_s"]) or 0
        t = tc.get((r["window_id"], r["interface_name"]), {})
        b, a = t.get("before", {}), t.get("after", {})
        col = "netem_dropped" if a.get("netem_dropped", "") != "" else "htb_dropped"

        def d(key):
            x, y = _f(b.get(key)), _f(a.get(key))
            return int(y - x) if None not in (x, y) and y >= x else ""
        intf.append({
            "experiment_id": exp_id, "window_id": r["window_id"], "link_id": r["link_id"],
            "node_id": r["node_id"], "peer_node_id": r["peer_node_id"], "duration_s": r["duration_s"],
            "rx_mbps": r["rx_mbps"], "tx_mbps": r["tx_mbps"],
            "rx_pps": round(int(r["rx_packets_delta"]) / dur, 3) if r["rx_packets_delta"] != "" and dur else "",
            "tx_pps": round(int(r["tx_packets_delta"]) / dur, 3) if r["tx_packets_delta"] != "" and dur else "",
            "rx_errors_delta": r["rx_errors_delta"], "tx_errors_delta": r["tx_errors_delta"],
            "rx_dropped_delta": r["rx_dropped_delta"], "tx_dropped_delta": r["tx_dropped_delta"],
            "counter_reset": r["counter_reset"], "admin_up": r["admin_up_after"],
            "carrier": r["carrier_after"], "oper_up": int(r["operstate_after"] == "UP"),
            "qdisc_drops_delta": d(col), "qdisc_backlog_pkts": a.get("netem_backlog_pkts", ""),
            "qdisc_overlimits_delta": d("htb_overlimits")})
    flow = []
    span = {w["window_id"]: w["end_unix"] - w["start_unix"] for w in gt["windows"]}
    for t in audit["traffic_windows"]:
        flow.append({"experiment_id": exp_id, "window_id": t["window_id"],
                     "offered_mbps": gt["traffic"]["offered_mbps"],
                     "flow_active_fraction": round(t["flow_active_s"] / span[t["window_id"]], 4)
                     if gt["traffic"]["offered_mbps"] else 0,
                     "receiver_mbps": "" if t["receiver_mbps"] is None else t["receiver_mbps"],
                     "receiver_lost_packets": "" if t["receiver_lost_packets"] is None else t["receiver_lost_packets"],
                     "receiver_alignment_reliable": t["receiver_alignment_reliable"],
                     "sender_alive_at_window_end": "" if t["client_alive_at_window_end"] is None
                     else int(t["client_alive_at_window_end"])})
    kind = {"LINK_FAILURE": "link", "LINK_DELAY": "link", "LINK_LOSS": "link", "LINK_BANDWIDTH": "link",
            "NODE_FAILURE": topo.node_types(spec).get(sc["target"] or "", ""), "SWITCH_BLACKHOLE": "switch",
            "NONE": ""}[sc["fault_type"]]
    labels = []
    n_unreach = len(gt["expected"]["disrupted_pairs_failed_phase"])
    for w in gt["windows"]:
        active = int(w["phase"] == "failed" and sc["fault_type"] != "NONE")
        p = sc["params"]
        labels.append({"experiment_id": exp_id, "window_id": w["window_id"], "phase": w["phase"],
                       "fault_active": active,
                       "fault_family": sc["fault_type"] if active else "NONE",
                       "fault_category": sc["category"] if active else "none",
                       "fault_target": sc["target"] if active else "",
                       "target_kind": kind if active else "",
                       "param_added_delay_ms": p.get("added_delay_ms", "") if active else "",
                       "param_loss_pct": p.get("loss_pct", "") if active else "",
                       "param_bw_mbps": p.get("bw_mbps", "") if active else "",
                       "param_queue_pkts": p.get("queue_pkts", "") if active else "",
                       "window_start_unix": w["start_unix"], "window_end_unix": w["end_unix"],
                       "expected_unreachable_pairs": n_unreach if active else 0})
    exp = {"experiment_id": exp_id, "protocol_version": gt["protocol_version"], "campaign_id": campaign_id,
           "scenario_key": scenario_key(sc["fault_type"], sc["target"], sc["params"], gt["traffic"]["offered_mbps"]),
           "fault_family": sc["fault_type"], "fault_target": sc["target"] or "",
           "offered_mbps": gt["traffic"]["offered_mbps"], "repetition": gt.get("repetition") or "",
           "run_seed": gt.get("seed", ""), "audit": "PASS" if audit["passed"] else "FAIL",
           "n_windows": len(gt["windows"]), "window_s_nominal": gt["protocol"]["window_s"],
           "probe_mode": "concurrent", "raw_relative_path": f"data/raw/small_v1/{exp_id}"}
    return exp, pair, intf, flow, labels


# ------------------------------------------------------------------ v1 (legacy link-failure runs)
def convert_v1(folder, campaign_id, repetition):
    folder = Path(folder)
    gt = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
    exp_id = gt["experiment_id"]
    g = gt["ground_truth"]
    pair = []
    for r in read_rows(folder / "telemetry.csv"):
        wid = r["snapshot_id"]
        pair.append({"experiment_id": exp_id, "window_id": wid, "source_node_id": r["source_node_id"],
                     "target_node_id": r["target_node_id"], "packets_sent": r["packets_sent"],
                     "packets_received": r["packets_received"], "loss_pct": r["loss_pct"],
                     "rtt_avg_ms": r["rtt_avg_ms"], "rtt_mdev_ms": "", "reachable": r["reachable"],
                     "route_unreachable": int(r["probe_status"] == "route_unreachable"),
                     "probe_status": r["probe_status"]})
    samples = defaultdict(dict)
    for r in read_rows(folder / "port_telemetry.csv"):
        samples[(r["snapshot_id"], r["interface_name"])][r["sample_position"]] = r
    from datetime import datetime
    intf = []
    for (wid, name), s in sorted(samples.items()):
        b, a = s["before"], s["after"]
        dur = (datetime.fromisoformat(a["sample_time_utc"]) - datetime.fromisoformat(b["sample_time_utc"])).total_seconds()
        dl = counter_deltas(b, a, dur)
        intf.append({"experiment_id": exp_id, "window_id": wid, "link_id": a["link_id"], "node_id": a["node_id"],
                     "peer_node_id": a["peer_node_id"], "duration_s": round(dur, 4),
                     "rx_mbps": dl["rx_mbps"], "tx_mbps": dl["tx_mbps"],
                     "rx_pps": round(dl["rx_packets_delta"] / dur, 3) if dl["rx_packets_delta"] != "" else "",
                     "tx_pps": round(dl["tx_packets_delta"] / dur, 3) if dl["tx_packets_delta"] != "" else "",
                     "rx_errors_delta": dl["rx_errors_delta"], "tx_errors_delta": dl["tx_errors_delta"],
                     "rx_dropped_delta": dl["rx_dropped_delta"], "tx_dropped_delta": dl["tx_dropped_delta"],
                     "counter_reset": dl["counter_reset"], "admin_up": a["admin_up"],
                     "carrier": int(a["operstate"] == "UP"), "oper_up": int(a["operstate"] == "UP"),
                     "qdisc_drops_delta": "", "qdisc_backlog_pkts": "", "qdisc_overlimits_delta": ""})
    labels = []
    for s in g["snapshots"]:
        active = int(s["phase"] == "failed")
        start = datetime.fromisoformat(s["start_utc"]).timestamp()
        end = datetime.fromisoformat(s["end_utc"]).timestamp()
        labels.append({"experiment_id": exp_id, "window_id": s["snapshot_id"], "phase": s["phase"],
                       "fault_active": active, "fault_family": "LINK_FAILURE" if active else "NONE",
                       "fault_category": "failure" if active else "none",
                       "fault_target": g["fault_link_id"] if active else "", "target_kind": "link" if active else "",
                       "param_added_delay_ms": "", "param_loss_pct": "", "param_bw_mbps": "", "param_queue_pkts": "",
                       "window_start_unix": round(start, 4), "window_end_unix": round(end, 4),
                       "expected_unreachable_pairs": len(topo.disrupted_pairs(
                           json.loads((folder / "topology.json").read_text(encoding="utf-8-sig")),
                           failed_links=[g["fault_link_id"]])) if active else 0})
    flow = [{"experiment_id": exp_id, "window_id": s["snapshot_id"], "offered_mbps": 0,
             "flow_active_fraction": 0, "receiver_mbps": "", "receiver_lost_packets": "",
             "receiver_alignment_reliable": "", "sender_alive_at_window_end": ""} for s in g["snapshots"]]
    exp = {"experiment_id": exp_id, "protocol_version": "small_link_v1", "campaign_id": campaign_id,
           "scenario_key": scenario_key("LINK_FAILURE", g["fault_link_id"], {}, 0),
           "fault_family": "LINK_FAILURE", "fault_target": g["fault_link_id"], "offered_mbps": 0,
           "repetition": repetition, "run_seed": "", "audit": "PASS(v1 campaign audit)",
           "n_windows": len(g["snapshots"]), "window_s_nominal": "", "probe_mode": "sequential",
           "raw_relative_path": f"data/raw/small_v1/{exp_id}"}
    return exp, pair, intf, flow, labels


def assign_folds(experiments, n_folds=3):
    """Leave-one-repetition-out: within each (protocol, scenario) stratum, the k-th
    independent run (ordered by repetition, then id) goes to fold ((k-1) mod n)+1."""
    strata = defaultdict(list)
    for e in experiments:
        strata[(e["protocol_version"], e["scenario_key"])].append(e)
    for members in strata.values():
        members.sort(key=lambda e: (str(e["repetition"]), e["experiment_id"]))
        for k, e in enumerate(members):
            e["split_fold"] = k % n_folds + 1
    return experiments


def write_csv(path, fields, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def graph_schema(spec):
    nodes = [n["id"] for n in spec["nodes"]]
    return {
        "topology_id": spec["topology_id"],
        "nodes": [{"index": i, "node_id": n["id"], "type": n["type"],
                   "attrs": {k: v for k, v in n.items() if k not in ("id", "type")}}
                  for i, n in enumerate(spec["nodes"])],
        "edges": [{"index": i, "link_id": l["id"], "source": l["source"], "target": l["target"],
                   "source_index": nodes.index(l["source"]), "target_index": nodes.index(l["target"]),
                   "static_attrs": {"bandwidth_mbps": l["bandwidth_mbps"], "delay_ms": l["delay_ms"]}}
                  for i, l in enumerate(spec["links"])],
        "sample_unit": "(experiment_id, window_id) -> one graph snapshot",
        "edge_features_from": "interface_window (two directed interface rows per link: node_id->peer)",
        "pair_features_from": "pair_window (host-pair end-to-end probes; candidate hyper-edges / path features)",
        "flow_features_from": "flow_window (single background flow PC-SHOP->SRV-LOCAL)",
        "default_excluded_columns": [d[1] for d in FEATURE_DICTIONARY if d[4] in ("no", "restricted")],
        "label_tasks": {
            "detection": "labels_window.fault_active (window-level binary)",
            "family": "labels_window.fault_family",
            "localization": "labels_window.fault_target (link or node ID) for fault_active==1",
        },
    }
