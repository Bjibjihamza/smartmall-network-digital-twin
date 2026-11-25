#!/usr/bin/env python3
"""SmartMall Phase 2.5 — reproducible SMALL link-failure telemetry capture.

Run from the SmartMall project on Ubuntu/WSL2:
    sudo /usr/bin/python3 scripts/legacy/collect_small_experiment.py
    sudo /usr/bin/python3 scripts/legacy/collect_small_experiment.py --rounds 1

Requires scripts/run_small_mininet.py and topologies/small.json.
Each run writes an isolated folder containing:
    topology.json  : exact network specification
    telemetry.csv  : measured end-to-end probes ONLY (no ground-truth labels)
    incident.json  : injection metadata and time intervals (keep away from ML inputs)

This is a feasibility/pilot dataset, not yet a training-grade GNN dataset.
"""

import argparse
import sys
import csv
import itertools
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSBridge

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # repo src/ (script lives in scripts/legacy/)
from smartmall.emulation import SmartMallSmall
ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "topologies" / "small.json"
FIELDS = [
    "experiment_id", "snapshot_id", "probe_start_utc", "probe_end_utc",
    "source_node_id", "target_node_id", "packets_sent", "packets_received",
    "loss_pct", "rtt_avg_ms", "reachable",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def probe(net, mapping, source, target, packets):
    host_src = net.get(mapping[source])
    host_dst = net.get(mapping[target])
    start = utc_now()
    # Every packet is an independent opportunity for loss; -W bounds a missing reply.
    output = host_src.cmd(f"ping -n -c {packets} -W 1 {host_dst.IP()}")
    end = utc_now()

    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    stats_match = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
    rtt_match = re.search(
        r"rtt min/avg/max/(?:mdev|stddev) = [^/]+/([^/]+)/", output
    )
    if not loss_match or not stats_match:
        raise RuntimeError(f"Cannot parse ping response for {source}->{target}:\n{output}")

    sent, received = int(stats_match.group(1)), int(stats_match.group(2))
    loss = float(loss_match.group(1))
    return {
        "probe_start_utc": start,
        "probe_end_utc": end,
        "source_node_id": source,
        "target_node_id": target,
        "packets_sent": sent,
        "packets_received": received,
        "loss_pct": loss,
        "rtt_avg_ms": round(float(rtt_match.group(1)), 4) if rtt_match else "",
        "reachable": int(received > 0),
    }


def capture_snapshots(writer, net, mapping, pairs, rounds, packets,
                      experiment_id, metadata, phase, counter):
    for _ in range(rounds):
        counter += 1
        snapshot = f"window_{counter:03d}"
        started = utc_now()
        losses = []
        for source, target in pairs:
            measurement = probe(net, mapping, source, target, packets)
            writer.writerow({
                "experiment_id": experiment_id,
                "snapshot_id": snapshot,
                **measurement,
            })
            losses.append(measurement["loss_pct"])
        ended = utc_now()
        # The phase label remains ONLY in incident.json, never in telemetry.csv.
        metadata["ground_truth"]["snapshots"].append({
            "snapshot_id": snapshot,
            "phase": phase,
            "start_utc": started,
            "end_utc": ended,
        })
        print(f"  {snapshot}: {len(pairs)} probes, "
              f"{sum(loss > 0 for loss in losses)} with loss ({phase})", flush=True)
    return counter


def main():
    parser = argparse.ArgumentParser(
        description="Capture a controlled fault experiment from SmartMall SMALL"
    )
    parser.add_argument("--rounds", type=int, default=2,
                        help="Number of network snapshots per phase (default: 2)")
    parser.add_argument("--packets", type=int, default=2,
                        help="Packets per host-pair probe (default: 2)")
    parser.add_argument("--fault-link", default="L2",
                        help="Link ID to disable from small.json (default: L2)")
    args = parser.parse_args()
    if args.rounds < 1 or args.packets < 1:
        parser.error("--rounds and --packets must be positive")

    with SPEC_PATH.open(encoding="utf-8-sig") as stream:
        spec = json.load(stream)
    if spec.get("topology_id") != "small_v1":
        raise ValueError("This pilot requires small_v1")
    fault_link = next(
        (link for link in spec["links"] if link["id"] == args.fault_link), None
    )
    if fault_link is None:
        parser.error(f"Unknown fault-link ID: {args.fault_link}")

    experiment_id = (
        "exp_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:6]
    )
    output = ROOT / "data" / "raw" / "small_v1" / experiment_id
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(SPEC_PATH, output / "topology.json")

    topo = SmartMallSmall(spec=spec)
    mapping = topo.component_to_mininet
    hosts = sorted(node["id"] for node in spec["nodes"] if node["type"] == "host")
    pairs = list(itertools.combinations(hosts, 2))
    source = mapping[fault_link["source"]]
    target = mapping[fault_link["target"]]
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    metadata = {
        "experiment_id": experiment_id,
        "topology_id": spec["topology_id"],
        "started_at_utc": utc_now(),
        "status": "running",
        "protocol": {
            "rounds_per_phase": args.rounds,
            "packets_per_probe": args.packets,
            "probe_pairs": [[a, b] for a, b in pairs],
            "switch_mode": "OVSBridge (standalone)",
            "measurement_type": "end_to_end_icmp_only",
        },
        "ground_truth": {
            "fault_type": "LINK_FAILURE",
            "fault_link_id": fault_link["id"],
            "source_node_id": fault_link["source"],
            "target_node_id": fault_link["target"],
            "injected_at_utc": None,
            "restored_at_utc": None,
            "snapshots": [],
        },
    }
    link_is_down = False
    started = False
    counter = 0
    print(f"\nExperiment: {experiment_id}")
    print(f"Topology: {spec['topology_id']}; fault: {args.fault_link} "
          f"({fault_link['source']} <-> {fault_link['target']})")
    print(f"Output: {output}")
    print("Telemetry CSV excludes the fault label and phase.", flush=True)
    try:
        with (output / "telemetry.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            net.start()
            started = True
            print("\nWarm-up: baseline connectivity", flush=True)
            if net.pingAll() != 0:
                raise RuntimeError("Unhealthy network before the experiment")

            print("\nA — HEALTHY", flush=True)
            counter = capture_snapshots(writer, net, mapping, pairs, args.rounds,
                                        args.packets, experiment_id, metadata,
                                        "healthy", counter)
            file.flush()

            print(f"\n[INJECT] {args.fault_link}", flush=True)
            net.configLinkStatus(source, target, "down")
            link_is_down = True
            metadata["ground_truth"]["injected_at_utc"] = utc_now()
            time.sleep(0.5)
            print("\nB — FAILED", flush=True)
            counter = capture_snapshots(writer, net, mapping, pairs, args.rounds,
                                        args.packets, experiment_id, metadata,
                                        "failed", counter)
            file.flush()

            print(f"\n[RESTORE] {args.fault_link}", flush=True)
            net.configLinkStatus(source, target, "up")
            link_is_down = False
            metadata["ground_truth"]["restored_at_utc"] = utc_now()
            time.sleep(1.0)
            if net.pingAll() != 0:
                raise RuntimeError("Network did not fully recover")
            print("\nC — RECOVERED", flush=True)
            counter = capture_snapshots(writer, net, mapping, pairs, args.rounds,
                                        args.packets, experiment_id, metadata,
                                        "recovered", counter)
            file.flush()

        metadata["status"] = "completed"
        print(f"\nSUCCESS: {counter} snapshots x {len(pairs)} pairs = "
              f"{counter * len(pairs)} telemetry rows")
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        print(f"\nEXPERIMENT FAILED: {exc}", flush=True)
        raise
    finally:
        if link_is_down and started:
            try:
                net.configLinkStatus(source, target, "up")
            except Exception as exc:
                print(f"Warning: restoring failed link failed: {exc}", flush=True)
        if started:
            net.stop()
        metadata["finished_at_utc"] = utc_now()
        with (output / "incident.json").open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2, ensure_ascii=False)
            file.write("\n")
        print(f"Saved: {output / 'telemetry.csv'}")
        print(f"Saved: {output / 'incident.json'}")
        print(f"Saved: {output / 'topology.json'}")


if __name__ == "__main__":
    setLogLevel("warning")
    main()
