#!/usr/bin/env python3
"""SmartMall Phase 2.6 — audit a Mininet experiment without dependencies.

Usage, from project root (Windows PowerShell, or Ubuntu/WSL):
    python scripts/legacy/audit_experiment.py
    python scripts/legacy/audit_experiment.py data/raw/small_v1/exp_20261125T130833Z_c13c88

By default selects the most recent experiment directory under data/raw/small_v1.
Checks recorded facts and reports an important limitation: different link faults
can have identical end-to-end ICMP symptoms. No ground-truth columns are added
to the measured telemetry. The source data are never modified.
"""

import argparse
import csv
import itertools
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "raw" / "small_v1"
FIELDS = {
    "experiment_id", "snapshot_id", "probe_start_utc", "probe_end_utc",
    "source_node_id", "target_node_id", "packets_sent", "packets_received",
    "loss_pct", "rtt_avg_ms", "reachable",
}
LABEL_FIELDS = {
    "phase", "fault_type", "fault_link_id", "ground_truth", "injected_at_utc",
    "restored_at_utc", "source_fault", "target_fault", "label",
}


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def components_without_edge(nodes, links, excluded_link):
    adjacency = {node: set() for node in nodes}
    for link in links:
        if link["id"] == excluded_link:
            continue
        a, b = link["source"], link["target"]
        adjacency[a].add(b)
        adjacency[b].add(a)
    components = {}
    for node in nodes:
        if node in components:
            continue
        group = len(set(components.values()))
        stack = [node]
        while stack:
            current = stack.pop()
            if current in components:
                continue
            components[current] = group
            stack.extend(adjacency[current] - components.keys())
    return components


def signature(nodes, links, pairs, link_id):
    c = components_without_edge(nodes, links, link_id)
    return tuple(c[a] != c[b] for a, b in pairs)


def newest_experiment():
    if not DATA_ROOT.exists():
        raise FileNotFoundError(f"No experiment directory: {DATA_ROOT}")
    candidates = [p for p in DATA_ROOT.iterdir() if p.is_dir() and
                  (p / "telemetry.csv").exists() and
                  (p / "incident.json").exists() and
                  (p / "topology.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No complete experiment folder inside {DATA_ROOT}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def audit(folder):
    errors, warnings = [], []
    with (folder / "topology.json").open(encoding="utf-8-sig") as f:
        topo = json.load(f)
    with (folder / "incident.json").open(encoding="utf-8-sig") as f:
        incident = json.load(f)
    with (folder / "telemetry.csv").open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        rows = list(reader)

    missing_columns = FIELDS - columns
    if missing_columns:
        errors.append(f"Missing measurement fields: {sorted(missing_columns)}")
    leaked_fields = columns & LABEL_FIELDS
    if leaked_fields:
        errors.append(f"Ground-truth fields in telemetry CSV: {sorted(leaked_fields)}")
    if not rows:
        errors.append("Empty telemetry CSV")

    nodes = {n["id"] for n in topo["nodes"]}
    hosts = {n["id"] for n in topo["nodes"] if n["type"] == "host"}
    links = topo["links"]
    link_ids = {edge["id"] for edge in links}
    if len(link_ids) != len(links):
        errors.append("Duplicate link IDs in topology")
    if len(nodes) != len(topo["nodes"]):
        errors.append("Duplicate node IDs in topology")
    if any(edge["source"] not in nodes or edge["target"] not in nodes for edge in links):
        errors.append("Link refers to missing node")

    eid = incident.get("experiment_id")
    if topo.get("topology_id") != incident.get("topology_id"):
        errors.append("Topology IDs do not match")
    if incident.get("status") != "completed":
        errors.append(f"Experiment status is {incident.get('status')!r}, not completed")

    ground_truth = incident["ground_truth"]
    fault_id = ground_truth.get("fault_link_id")
    if fault_id not in link_ids:
        errors.append(f"Injected fault link {fault_id!r} missing from topology")
    injected = timestamp(ground_truth["injected_at_utc"])
    restored = timestamp(ground_truth["restored_at_utc"])
    if restored <= injected:
        errors.append("Restoration timestamp precedes injection")
    snapshots = ground_truth.get("snapshots", [])
    snapshot_by_id = {s["snapshot_id"]: s for s in snapshots}
    if len(snapshot_by_id) != len(snapshots):
        errors.append("Duplicate snapshot IDs in incident.json")
    pairs = [tuple(p) for p in incident["protocol"]["probe_pairs"]]
    canonical_pairs = {tuple(sorted(p)) for p in pairs}
    if len(canonical_pairs) != len(pairs):
        errors.append("Duplicate probe pairs in protocol")
    if any(a not in hosts or b not in hosts or a == b for a, b in pairs):
        errors.append("Invalid host pair(s) in protocol")

    observed = defaultdict(list)
    keys = set()
    for index, row in enumerate(rows, start=2):
        sid = row.get("snapshot_id", "")
        if sid not in snapshot_by_id:
            errors.append(f"CSV row {index}: unknown snapshot {sid}")
            continue
        if row.get("experiment_id") != eid:
            errors.append(f"CSV row {index}: experiment_id mismatch")
        a, b = row["source_node_id"], row["target_node_id"]
        pair = tuple(sorted((a, b)))
        if pair not in canonical_pairs:
            errors.append(f"CSV row {index}: unexpected probe pair {a}->{b}")
        key = (sid, pair)
        if key in keys:
            errors.append(f"CSV row {index}: repeated pair {pair} within {sid}")
        keys.add(key)
        try:
            sent = int(row["packets_sent"])
            received = int(row["packets_received"])
            loss = float(row["loss_pct"])
            reachable = int(row["reachable"])
            start, end = timestamp(row["probe_start_utc"]), timestamp(row["probe_end_utc"])
            sw = snapshot_by_id[sid]
            sw_start, sw_end = timestamp(sw["start_utc"]), timestamp(sw["end_utc"])
            if not (sw_start <= start <= end <= sw_end):
                errors.append(f"CSV row {index}: probe outside snapshot time range")
            if not (sent > 0 and 0 <= received <= sent and reachable == int(received > 0)):
                errors.append(f"CSV row {index}: invalid packet counts or reachability")
            if abs(loss - 100 * (sent - received) / sent) > 0.15:
                errors.append(f"CSV row {index}: packet loss inconsistent with counts")
            rtt = row["rtt_avg_ms"].strip()
            if received == 0 and rtt:
                errors.append(f"CSV row {index}: RTT must be blank without replies")
            if received > 0 and (not rtt or float(rtt) < 0):
                errors.append(f"CSV row {index}: invalid or missing RTT")
            observed[sid].append((pair, loss))
        except (ValueError, KeyError) as exc:
            errors.append(f"CSV row {index}: invalid measurement: {exc}")

    phase_order = []
    for item in snapshots:
        sid = item["snapshot_id"]
        phase = item["phase"]
        start, end = timestamp(item["start_utc"]), timestamp(item["end_utc"])
        phase_order.append(phase)
        measured_pairs = {pair for pair, _ in observed[sid]}
        if measured_pairs != canonical_pairs:
            errors.append(f"{sid}: missing or unexpected pairs")
        if phase == "healthy" and end > injected:
            errors.append(f"{sid}: healthy snapshot overlaps injection")
        if phase == "failed" and not (injected <= start <= end <= restored):
            errors.append(f"{sid}: failed snapshot outside incident interval")
        if phase == "recovered" and start < restored:
            errors.append(f"{sid}: recovery snapshot begins before restoration")
        if phase not in {"healthy", "failed", "recovered"}:
            warnings.append(f"{sid}: unknown phase {phase}")
    if phase_order != sorted(phase_order, key={"healthy": 0, "failed": 1, "recovered": 2}.get):
        errors.append("Snapshot phases are not chronologically ordered")

    grouped = defaultdict(list)
    for item in snapshots:
        grouped[item["phase"]].extend(loss for _, loss in observed[item["snapshot_id"]])
    if not {"healthy", "failed", "recovered"}.issubset(grouped):
        warnings.append("Not all three experiment phases were recorded")
    if len(pairs) > 1:
        warnings.append("Host-pair probes are sequential, not simultaneous network snapshots")
    if incident["protocol"].get("packets_per_probe", 0) <= 2:
        warnings.append("Only 2 ICMP packets per probe: too sparse for stable packet-loss estimates")
    warnings.append("End-to-end ICMP only: no interface/port/link counters; fault localization remains ambiguous")
    warnings.append("Keep experiment_id, absolute timestamps, and labels OUT of model features")

    equivalent = []
    expected_failed_pairs = []
    actual_failed_pairs = []
    if fault_id in link_ids and not (set(pairs) - set(itertools.combinations(sorted(hosts), 2))):
        expected_sig = signature(nodes, links, pairs, fault_id)
        expected_failed_pairs = [pairs[i] for i, down in enumerate(expected_sig) if down]
        equivalent = [l["id"] for l in links if signature(nodes, links, pairs, l["id"]) == expected_sig]
        if len(equivalent) > 1:
            warnings.append("Identical host-pair outage signatures for these link faults: " + ", ".join(equivalent))
        for item in snapshots:
            if item["phase"] == "failed":
                actual_failed_pairs.extend(pair for pair, loss in observed[item["snapshot_id"]] if loss >= 99.9)
        failed_rounds = sum(s["phase"] == "failed" for s in snapshots)
        if Counter(actual_failed_pairs) != Counter({tuple(sorted(p)): failed_rounds for p in expected_failed_pairs}):
            warnings.append("Observed outage pattern differs from the topology-only partition expectation")

    lines = [
        "# SmartMall — Experiment Quality Audit", "",
        f"- Experiment: `{eid}`",
        f"- Topology: `{topo['topology_id']}` ({len(nodes)} nodes, {len(links)} links)",
        f"- Injected fault: `{fault_id}` ({ground_truth['fault_type']})",
        f"- Dataset: {len(rows)} telemetry records, {len(snapshots)} windows, {len(pairs)} probe pairs", "",
        "## Observed packet loss by experimental phase", "",
        "| Phase | Probes | Probes with loss | 100% loss |",
        "|---|---:|---:|---:|",
    ]
    for phase in ("healthy", "failed", "recovered"):
        values = grouped.get(phase, [])
        lines.append(f"| {phase} | {len(values)} | {sum(x > 0 for x in values)} | {sum(x >= 99.9 for x in values)} |")
    if expected_failed_pairs:
        lines += ["", "## Expected disconnected host pairs (graph analysis)", ""]
        lines += [f"- `{a}` ↔ `{b}`" for a, b in expected_failed_pairs]
    if equivalent:
        lines += ["", "## Link-fault identifiability from these probes", "",
                  "Indistinguishable link failures based on end-to-end reachability alone: " + ", ".join(f"`{x}`" for x in equivalent) + "."]
    lines += ["", "## Data integrity", "", "**PASS**" if not errors else "**FAIL**", ""]
    if errors:
        lines += ["### Errors", ""] + [f"- {x}" for x in errors] + [""]
    if warnings:
        lines += ["### Scientific limitations and warnings", ""] + [f"- {x}" for x in warnings] + [""]
    lines += ["Raw experiment files were not changed.", ""]

    print("\n".join(lines))
    out = ROOT / "docs" / "history" / "small_v1" / f"audit_{eid}.md"
    out.parent.mkdir(exist_ok=True, parents=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Audit saved: {out}")
    return not errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", nargs="?", type=Path, help="Experiment folder; default: latest SMALL run")
    args = p.parse_args()
    try:
        folder = args.folder or newest_experiment()
        if not folder.is_dir():
            raise NotADirectoryError(folder)
        sys.exit(0 if audit(folder) else 1)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"AUDIT ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
