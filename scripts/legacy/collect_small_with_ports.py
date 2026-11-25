#!/usr/bin/env python3
"""SmartMall Phase 2.7 — SMALL link-failure experiment with port telemetry.

Ubuntu / WSL2 usage (from the project root):
    sudo /usr/bin/python3 scripts/legacy/collect_small_with_ports.py
    sudo /usr/bin/python3 scripts/legacy/collect_small_with_ports.py --fault-link L1 --rounds 2

Requires:
    scripts/run_small_mininet.py
    topologies/small.json
    Ubuntu packages mininet, openvswitch-switch and iproute2

Each run creates a NEW folder in data/raw/small_v1/ with:
    topology.json          : immutable topology specification
    telemetry.csv          : timestamped ICMP observations (no fault labels)
    port_telemetry.csv     : pre/post samples of each interface (no fault labels)
    incident.json          : operator-only ground truth and phase intervals

IMPORTANT RESEARCH LIMITATION:
The experiment uses configLinkStatus(), which ADMINISTRATIVELY disables
interfaces. Consequently admin_up can trivially reveal the injected location.
This is a control experiment to verify observability, NOT a fair benchmark of
fault localization under realistic physical link loss. Use independent fault
mechanisms, more telemetry, multiple scenarios and leakage controls later.
"""

import argparse
import csv
import itertools
import json
import re
import shutil
import sys
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
ICMP_FIELDS = [
    "experiment_id", "snapshot_id", "probe_start_utc", "probe_end_utc",
    "source_node_id", "target_node_id", "packets_sent", "packets_received",
    "loss_pct", "rtt_avg_ms", "reachable", "probe_status",
]
PORT_FIELDS = [
    "experiment_id", "snapshot_id", "sample_position", "sample_time_utc",
    "link_id", "node_id", "peer_node_id", "interface_name",
    "admin_up", "operstate", "rx_bytes", "rx_packets", "rx_errors",
    "rx_dropped", "tx_bytes", "tx_packets", "tx_errors", "tx_dropped",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_interface(net, node_name, interface_name):
    """Read Linux kernel interface flags and counters in the proper namespace."""
    node = net.get(node_name)
    output = node.cmd(f"ip -j -s link show dev {interface_name}")
    try:
        rows = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not read interface {node_name}/{interface_name} with iproute2: "
            f"{output.strip()}"
        ) from exc
    if len(rows) != 1:
        raise RuntimeError(f"Unexpected interface data for {node_name}/{interface_name}: {output}")

    entry = rows[0]
    statistics = entry.get("stats64") or entry.get("stats")
    if not statistics or "rx" not in statistics or "tx" not in statistics:
        raise RuntimeError(f"Missing interface counters for {node_name}/{interface_name}")

    flags = entry.get("flags", [])
    rx = statistics["rx"]
    tx = statistics["tx"]
    return {
        "admin_up": int("UP" in flags),
        "operstate": entry.get("operstate", "UNKNOWN"),
        "rx_bytes": rx.get("bytes", ""),
        "rx_packets": rx.get("packets", ""),
        "rx_errors": rx.get("errors", ""),
        "rx_dropped": rx.get("dropped", ""),
        "tx_bytes": tx.get("bytes", ""),
        "tx_packets": tx.get("packets", ""),
        "tx_errors": tx.get("errors", ""),
        "tx_dropped": tx.get("dropped", ""),
    }


def map_interfaces(net, spec, names):
    """Find each JSON link's TWO actual Mininet interfaces by endpoints."""
    mapping = []
    for link_spec in spec["links"]:
        source_id = link_spec["source"]
        target_id = link_spec["target"]
        source_mn = names[source_id]
        target_mn = names[target_id]
        matching = [
            link for link in net.links
            if {link.intf1.node.name, link.intf2.node.name} == {source_mn, target_mn}
        ]
        if len(matching) != 1:
            raise RuntimeError(
                f"Expected one Mininet link for {link_spec['id']} "
                f"({source_mn}-{target_mn}), found {len(matching)}"
            )
        link = matching[0]
        for interface in (link.intf1, link.intf2):
            node_name = interface.node.name
            if node_name == source_mn:
                node_id, peer_id = source_id, target_id
            else:
                node_id, peer_id = target_id, source_id
            mapping.append({
                "link_id": link_spec["id"],
                "node_id": node_id,
                "peer_node_id": peer_id,
                "node_name": node_name,
                "interface_name": interface.name,
            })
    return mapping


def sample_interfaces(writer, net, port_map, experiment_id, snapshot_id, position):
    """Read all ports at a snapshot boundary; return per-link admin states."""
    link_states = {}
    for port in port_map:
        measured_at = utc_now()
        values = read_interface(net, port["node_name"], port["interface_name"])
        writer.writerow({
            "experiment_id": experiment_id,
            "snapshot_id": snapshot_id,
            "sample_position": position,
            "sample_time_utc": measured_at,
            "link_id": port["link_id"],
            "node_id": port["node_id"],
            "peer_node_id": port["peer_node_id"],
            "interface_name": port["interface_name"],
            **values,
        })
        link_states.setdefault(port["link_id"], []).append(values["admin_up"])
    return link_states


def probe(net, names, source, target, packets):
    hsrc = net.get(names[source])
    hdst = net.get(names[target])
    start = utc_now()
    output = hsrc.cmd(f"ping -n -c {packets} -W 1 {hdst.IP()}")
    end = utc_now()

    # If the source's only interface is disabled, Linux fails locally *before*
    # transmitting any ICMP request. This is NOT 100% packet loss: zero packets
    # were sent, so loss_pct is undefined and must remain empty in the CSV.
    # This occurs, for example, when L3 isolates host PC-ADM.
    local_route_errors = (
        "Network is unreachable", "Network is down", "No route to host",
    )
    if any(message in output for message in local_route_errors) and not re.search(
        r"\d+ packets transmitted, \d+ (?:packets )?received", output
    ):
        return {
            "probe_start_utc": start,
            "probe_end_utc": end,
            "source_node_id": source,
            "target_node_id": target,
            "packets_sent": 0,
            "packets_received": 0,
            "loss_pct": "",
            "rtt_avg_ms": "",
            "reachable": 0,
            "probe_status": "route_unreachable",
        }

    counts = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    rtt_match = re.search(r"rtt min/avg/max/(?:mdev|stddev) = [^/]+/([^/]+)/", output)
    if not counts or not loss_match:
        raise RuntimeError(f"Failed parsing {source}->{target} ping:\n{output}")
    received = int(counts.group(2))
    return {
        "probe_start_utc": start,
        "probe_end_utc": end,
        "source_node_id": source,
        "target_node_id": target,
        "packets_sent": int(counts.group(1)),
        "packets_received": received,
        "loss_pct": float(loss_match.group(1)),
        "rtt_avg_ms": round(float(rtt_match.group(1)), 4) if rtt_match else "",
        "reachable": int(received > 0),
        "probe_status": "icmp_stats",
    }


def capture_phase(icmp_writer, port_writer, net, names, port_map, pairs,
                  experiment_id, metadata, phase, rounds, packets, window_counter,
                  fault_link_id):
    for _ in range(rounds):
        window_counter += 1
        snapshot_id = f"window_{window_counter:03d}"
        started = utc_now()
        sample_interfaces(port_writer, net, port_map, experiment_id, snapshot_id, "before")
        disrupted = 0
        route_unreachable = 0
        losses = 0
        for source, target in pairs:
            observation = probe(net, names, source, target, packets)
            icmp_writer.writerow({
                "experiment_id": experiment_id,
                "snapshot_id": snapshot_id,
                **observation,
            })
            disrupted += int(observation["reachable"] == 0)
            route_unreachable += int(observation["probe_status"] == "route_unreachable")
            if observation["loss_pct"] != "":
                losses += int(observation["loss_pct"] > 0)
        end_states = sample_interfaces(
            port_writer, net, port_map, experiment_id, snapshot_id, "after"
        )
        ended = utc_now()
        metadata["ground_truth"]["snapshots"].append({
            "snapshot_id": snapshot_id,
            "phase": phase,
            "start_utc": started,
            "end_utc": ended,
        })
        status = end_states[fault_link_id]
        print(
            f"  {snapshot_id}: {len(pairs)} connectivity probes, "
            f"{losses} with ICMP packet loss, "
            f"{route_unreachable} locally unroutable, {disrupted} unreachable; "
            f"fault-target port admin_up={status}",
            flush=True,
        )
    return window_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-link", default="L2", help="ID of a link in small.json")
    parser.add_argument("--rounds", type=int, default=2, help="Windows per phase")
    parser.add_argument("--packets", type=int, default=2, help="ICMP requests per probe")
    args = parser.parse_args()
    if args.rounds < 1 or args.packets < 1:
        parser.error("--rounds and --packets must be positive")

    with SPEC_PATH.open(encoding="utf-8-sig") as file:
        spec = json.load(file)
    if spec.get("topology_id") != "small_v1":
        raise ValueError("This first port collector supports small_v1 only")
    chosen_link = next((l for l in spec["links"] if l["id"] == args.fault_link), None)
    if not chosen_link:
        parser.error(f"Unknown fault link {args.fault_link!r}")

    experiment_id = (
        "exp_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:6]
    )
    folder = ROOT / "data" / "raw" / "small_v1" / experiment_id
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(SPEC_PATH, folder / "topology.json")

    topo = SmartMallSmall(spec=spec)
    names = topo.component_to_mininet
    hosts = sorted(node["id"] for node in spec["nodes"] if node["type"] == "host")
    pairs = list(itertools.combinations(hosts, 2))
    left, right = names[chosen_link["source"]], names[chosen_link["target"]]
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    metadata = {
        "experiment_id": experiment_id,
        "topology_id": spec["topology_id"],
        "started_at_utc": utc_now(),
        "status": "running",
        "protocol": {
            "rounds_per_phase": args.rounds,
            "packets_per_probe": args.packets,
            "probe_pairs": [[s, t] for s, t in pairs],
            "switch_mode": "OVSBridge (standalone)",
            "measurement_type": "icmp_and_linux_interface_telemetry",
            "port_sampling": "before_and_after_each_probe_window",
            "port_admin_state_caveat": (
                "configLinkStatus administratively disables ports: admin_up is "
                "a direct controlled-fault indicator; not a production diagnosis benchmark"
            ),
        },
        "ground_truth": {
            "fault_type": "LINK_FAILURE",
            "fault_link_id": args.fault_link,
            "source_node_id": chosen_link["source"],
            "target_node_id": chosen_link["target"],
            "injected_at_utc": None,
            "restored_at_utc": None,
            "snapshots": [],
        },
    }
    started = False
    link_disabled = False
    window_counter = 0
    print(f"\nExperiment: {experiment_id}")
    print(f"Topology: {spec['topology_id']}; injected link: {args.fault_link}")
    print(f"Output: {folder}")
    print("Labels and phase are stored ONLY in incident.json", flush=True)

    try:
        with (folder / "telemetry.csv").open("w", newline="", encoding="utf-8") as icmp_file, \
             (folder / "port_telemetry.csv").open("w", newline="", encoding="utf-8") as port_file:
            icmp_writer = csv.DictWriter(icmp_file, fieldnames=ICMP_FIELDS)
            port_writer = csv.DictWriter(port_file, fieldnames=PORT_FIELDS)
            icmp_writer.writeheader()
            port_writer.writeheader()

            net.start()
            started = True
            port_map = map_interfaces(net, spec, names)
            print(f"Mapped {len(port_map)} interfaces over {len(spec['links'])} links")
            print("Warm-up: testing baseline connectivity", flush=True)
            if net.pingAll() != 0:
                raise RuntimeError("Network baseline is not fully connected")

            print("\nA — HEALTHY")
            window_counter = capture_phase(
                icmp_writer, port_writer, net, names, port_map, pairs,
                experiment_id, metadata, "healthy", args.rounds, args.packets,
                window_counter, args.fault_link,
            )

            print(f"\n[INJECT] disabling {args.fault_link}", flush=True)
            net.configLinkStatus(left, right, "down")
            link_disabled = True
            metadata["ground_truth"]["injected_at_utc"] = utc_now()
            time.sleep(0.5)
            print("\nB — FAILED")
            window_counter = capture_phase(
                icmp_writer, port_writer, net, names, port_map, pairs,
                experiment_id, metadata, "failed", args.rounds, args.packets,
                window_counter, args.fault_link,
            )

            print(f"\n[RESTORE] enabling {args.fault_link}", flush=True)
            net.configLinkStatus(left, right, "up")
            link_disabled = False
            metadata["ground_truth"]["restored_at_utc"] = utc_now()
            time.sleep(1)
            if net.pingAll() != 0:
                raise RuntimeError("Network did not recover fully")
            print("\nC — RECOVERED")
            window_counter = capture_phase(
                icmp_writer, port_writer, net, names, port_map, pairs,
                experiment_id, metadata, "recovered", args.rounds, args.packets,
                window_counter, args.fault_link,
            )

        metadata["status"] = "completed"
        total_port_records = window_counter * len(spec["links"]) * 2 * 2
        print(
            f"\nSUCCESS: {window_counter * len(pairs)} ICMP records, "
            f"{total_port_records} port records (two endpoints x before/after)"
        )
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        if link_disabled and started:
            try:
                net.configLinkStatus(left, right, "up")
            except Exception as exc:
                print(f"Warning: cannot restore link: {exc}", file=sys.stderr)
        if started:
            net.stop()
        metadata["finished_at_utc"] = utc_now()
        with (folder / "incident.json").open("w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
            file.write("\n")
        print(f"Saved experiment data to: {folder}", flush=True)


if __name__ == "__main__":
    setLogLevel("warning")
    main()
