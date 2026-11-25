#!/usr/bin/env python3
"""Audit a SmartMall Mininet ICMP + port-telemetry pilot experiment.

Run from the project root on Windows (Conda) or Ubuntu (stdlib only):
    python scripts/legacy/audit_port_experiment.py
    python3 scripts/legacy/audit_port_experiment.py --experiment data/raw/small_v1/exp_...

Produces docs/history/small_v1/audit_ports_<experiment_id>.md and does not modify raw data.
This is an integrity/observability audit, NOT GNN fault-localization validation.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
REQUIRED = ("topology.json", "incident.json", "telemetry.csv", "port_telemetry.csv")
COUNTERS = ("rx_bytes", "rx_packets", "rx_errors", "rx_dropped",
            "tx_bytes", "tx_packets", "tx_errors", "tx_dropped")
FORBIDDEN_FEATURE_COLS = {"phase", "fault_type", "fault_link_id", "fault_node_id", "ground_truth", "label"}


def iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def find_experiment(explicit):
    if explicit:
        directory = Path(explicit).resolve()
    else:
        candidates = [p for p in RAW.glob("*/exp_*")
                      if p.is_dir() and all((p / f).exists() for f in REQUIRED)]
        if not candidates:
            raise FileNotFoundError("No complete experiment containing port_telemetry.csv under data/raw")
        directory = sorted(candidates, key=lambda p: p.name)[-1]
    for name in REQUIRED:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"Missing {name} in {directory}")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=None, help="Path to the experiment directory")
    args = parser.parse_args()
    directory = find_experiment(args.experiment)
    topology = json.loads((directory / "topology.json").read_text(encoding="utf-8-sig"))
    incident = json.loads((directory / "incident.json").read_text(encoding="utf-8-sig"))
    ports = read_csv(directory / "port_telemetry.csv")
    probes = read_csv(directory / "telemetry.csv")
    links = {x["id"]: {x["source"], x["target"]} for x in topology["links"]}
    snapshot_phase = {x["snapshot_id"]: x["phase"] for x in incident["ground_truth"]["snapshots"]}
    snapshot_bounds = {
        x["snapshot_id"]: (iso(x["start_utc"]), iso(x["end_utc"]))
        for x in incident["ground_truth"]["snapshots"]
    }
    exp_id = incident["experiment_id"]
    fault = incident["ground_truth"]["fault_link_id"]
    errors = []
    warnings = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(bool(ports) and bool(probes), "Empty ICMP or port CSV")
    check(fault in links, f"Fault link {fault} is missing from topology")
    check(incident["topology_id"] == topology["topology_id"], "Topology ID mismatch")
    check(incident["status"] == "completed", "Experiment not marked completed")
    for name, rows in (("ports", ports), ("icmp", probes)):
        check(all(row.get("experiment_id") == exp_id for row in rows), f"{name}: experiment ID mismatch")
        bad_columns = FORBIDDEN_FEATURE_COLS.intersection(rows[0].keys()) if rows else set()
        check(not bad_columns, f"{name}: label/phase columns leaked into observations: {sorted(bad_columns)}")
        check(all(row.get("snapshot_id") in snapshot_phase for row in rows), f"{name}: unknown snapshot ID")

    actual_pairs = len(incident["protocol"]["probe_pairs"])
    expected_probes = len(snapshot_phase) * actual_pairs
    expected_ports = len(snapshot_phase) * 2 * len(links) * 2
    check(len(probes) == expected_probes, f"ICMP rows {len(probes)} != expected {expected_probes}")
    check(len(ports) == expected_ports, f"Port rows {len(ports)} != expected {expected_ports}")

    group = defaultdict(list)
    seen = set()
    state_by_phase_link = defaultdict(list)
    delta_errors = []
    for row in ports:
        window = row["snapshot_id"]
        key = (window, row["sample_position"], row["link_id"], row["node_id"])
        check(key not in seen, f"Duplicate port sample: {key}")
        seen.add(key)
        check(row["sample_position"] in ("before", "after"), f"Bad sample position: {key}")
        check(row["link_id"] in links, f"Unknown link ID: {key}")
        if row["link_id"] in links:
            check(row["node_id"] in links[row["link_id"]], f"Wrong node-link mapping: {key}")
            check(row["peer_node_id"] in links[row["link_id"]] - {row["node_id"]},
                  f"Wrong peer-link mapping: {key}")
        check(row["admin_up"] in ("0", "1"), f"Invalid admin_up value: {key}")
        try:
            sample_time = iso(row["sample_time_utc"])
            start, end = snapshot_bounds[window]
            check((start - timedelta(seconds=1)) <= sample_time <= (end + timedelta(seconds=1)),
                  f"Sample timestamp outside window: {key}")
        except (ValueError, KeyError) as exc:
            errors.append(f"Timestamp parse error {key}: {exc}")
        group[(window, row["sample_position"], row["link_id"])].append(row)
        state_by_phase_link[(snapshot_phase.get(window, "unknown"), row["link_id"])].append(row["admin_up"])

    for window in snapshot_phase:
        for position in ("before", "after"):
            for link_id, endpoints in links.items():
                records = group.get((window, position, link_id), [])
                check(len(records) == 2 and {x["node_id"] for x in records} == endpoints,
                      f"Expected exactly two interfaces of link {link_id} at {window}/{position}")
                if len(records) == 2:
                    expected_up = "0" if link_id == fault and snapshot_phase[window] == "failed" else "1"
                    for row in records:
                        check(row["admin_up"] == expected_up,
                              f"Unexpected admin state at {window}/{position}/{link_id}/{row['node_id']}")

    for window in snapshot_phase:
        for link_id in links:
            before = {r["node_id"]: r for r in group.get((window, "before", link_id), [])}
            after = {r["node_id"]: r for r in group.get((window, "after", link_id), [])}
            for node in before.keys() & after.keys():
                for counter in COUNTERS:
                    try:
                        a = int(after[node][counter])
                        b = int(before[node][counter])
                        if a < b:
                            delta_errors.append(f"Counter decreased at {window}/{link_id}/{node}/{counter}: {b} -> {a}")
                    except (ValueError, TypeError, KeyError):
                        warnings.append(f"Missing/non-numeric counter {window}/{link_id}/{node}/{counter}")

    icmp_by_phase = defaultdict(lambda: {"total": 0, "loss": 0, "full_loss": 0,
                                        "route_unreachable": 0, "disrupted": 0})
    for row in probes:
        phase = snapshot_phase.get(row["snapshot_id"], "unknown")
        stat = icmp_by_phase[phase]
        stat["total"] += 1
        try:
            sent, received = int(row["packets_sent"]), int(row["packets_received"])
            reachable = int(row["reachable"])
            status = row.get("probe_status", "icmp_stats")
            if status == "route_unreachable":
                if sent != 0 or received != 0 or row["loss_pct"] != "" or reachable != 0:
                    raise ValueError("route-unreachable record must have sent=0, received=0, empty loss, reachable=0")
                stat["route_unreachable"] += 1
            elif status == "icmp_stats":
                loss = float(row["loss_pct"])
                if sent < 1 or not 0 <= received <= sent or not 0 <= loss <= 100:
                    raise ValueError("invalid ICMP counters or loss")
                if abs(loss - 100 * (sent - received) / sent) > 0.15:
                    raise ValueError("loss inconsistent with transmitted/received packets")
                stat["loss"] += loss > 0
                stat["full_loss"] += loss == 100
            else:
                raise ValueError(f"unknown probe_status={status}")
            if reachable != int(received > 0):
                raise ValueError("reachable inconsistent with received packets")
            stat["disrupted"] += reachable == 0
        except (ValueError, TypeError) as exc:
            errors.append(f"Invalid ICMP sample in {row['snapshot_id']}: {exc}")
    check(not delta_errors, "Some port counters decreased within the same snapshot; see report")
    if not warnings:
        warnings.append("None")

    lines = [
        "# SmartMall — Port Telemetry Quality Audit", "",
        f"- Experiment: `{exp_id}`", f"- Topology: `{topology['topology_id']}`",
        f"- Injected link (ground truth, audit only): `{fault}`",
        f"- Observations: **{len(probes)} ICMP rows**, **{len(ports)} port rows**", 
        f"- Expected ports: {len(links)} links × 2 endpoints × 2 samples × {len(snapshot_phase)} windows = **{expected_ports}**", "",
        "## ICMP measurements by phase", "",
        "| Phase | Probes | With ICMP loss | 100% ICMP loss | Route unreachable | Not reachable |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for phase in ("healthy", "failed", "recovered"):
        s = icmp_by_phase[phase]
        lines.append(f"| {phase} | {s['total']} | {s['loss']} | {s['full_loss']} | "
                     f"{s['route_unreachable']} | {s['disrupted']} |")
    lines += ["", "## Observed port admin state", "",
              "| Phase | Fault-link samples up/down | Other-link samples down |", "|---|---|---:|"]
    for phase in ("healthy", "failed", "recovered"):
        fault_states = state_by_phase_link.get((phase, fault), [])
        up = sum(x == "1" for x in fault_states)
        down = sum(x == "0" for x in fault_states)
        other_down = sum(x == "0" for (ph, link), states in state_by_phase_link.items()
                         if ph == phase and link != fault for x in states)
        lines.append(f"| {phase} | {up} up / {down} down | {other_down} |")
    lines += ["", "## Data integrity", "", f"**{'PASS' if not errors else 'FAIL'}**", ""]
    if errors:
        lines += ["### Errors", ""] + [f"- {msg}" for msg in errors[:35]] + [""]
        if len(errors) > 35:
            lines.append(f"- ... and {len(errors) - 35} more errors")
    if delta_errors:
        lines += ["### Port counter decreases", ""] + [f"- {msg}" for msg in delta_errors[:20]] + [""]
    lines += [
        "## Scientific cautions", "",
        "- Administrative port-down is a **direct proxy for the injected link**. Treat this as an observability/control experiment, not a realistic GNN localization benchmark.",
        "- A locally unreachable route is recorded with 0 packets transmitted and blank loss_pct; it is NOT equivalent to 100% ICMP packet loss.",
        "- The six host-pair probes are sequential (not a simultaneous network snapshot); each probe uses only two ICMP packets.",
        "- Counter columns are cumulative; compute within-window deltas, not raw totals, for traffic analysis. Handle wrap/reset and sampling duration.",
        "- `experiment_id`, `snapshot_id`, `sample_time_utc`, `interface_name`, and absolute node/link identities require leakage/generalization review before ML.",
        "- Do not use `incident.json` labels or phases as model inputs. This audit intentionally joins ground truth only to verify the experiment.",
        "- This single SMALL fault scenario is insufficient to train/evaluate a generalizable GNN.", "",
        "## Parser warnings", "",
    ]
    lines += [f"- {msg}" for msg in warnings[:25]] + [""]
    output = ROOT / "docs" / "history" / "small_v1" / f"audit_ports_{exp_id}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:len(lines) - (len(warnings[:25]) + 1)]))
    print(f"\nReport saved: {output}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
