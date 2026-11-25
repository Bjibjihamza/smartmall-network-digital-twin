#!/usr/bin/env python3
"""SmartMall Phase 2.12a — background UDP traffic pilot on SMALL, NO FAULT.

Run from SmartMall project root in Ubuntu WSL2:
    sudo apt install -y iperf3
    sudo /usr/bin/python3 scripts/legacy/pilot_small_background_traffic.py --dry-run
    sudo /usr/bin/python3 scripts/legacy/pilot_small_background_traffic.py

Dependencies: scripts/run_small_mininet.py, updated scripts/legacy/collect_small_with_ports.py,
                 Mininet, OVS, iperf3.

Purpose: verify background-traffic generator and actual network behavior BEFORE
combining variable traffic with faults. This does not create a GNN training dataset.
"""
import argparse
import csv
import itertools
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "topologies" / "small.json"
PROBE_FIELDS = [
    "experiment_id", "profile", "offered_mbps", "source_node_id", "target_node_id",
    "probe_start_utc", "probe_end_utc", "packets_sent", "packets_received",
    "loss_pct", "rtt_avg_ms", "reachable", "probe_status",
]
PORT_FIELDS = [
    "experiment_id", "profile", "offered_mbps", "link_id", "node_id",
    "peer_node_id", "interface_name", "start_time_utc", "end_time_utc",
    "duration_s", "admin_up_before", "admin_up_after", "operstate_after",
    "rx_bytes_delta", "tx_bytes_delta", "rx_packets_delta", "tx_packets_delta",
    "rx_errors_delta", "tx_errors_delta", "rx_dropped_delta", "tx_dropped_delta",
    "rx_plus_tx_mbps_proxy",
]
COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_errors",
            "tx_errors", "rx_dropped", "tx_dropped")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_iperf(data):
    """Extract observed UDP statistics, respecting receiver vs sender reporting."""
    end = data.get("end", {})
    receiver = end.get("sum_received")
    source = "sum_received" if receiver else ""
    if not receiver:
        summary = end.get("sum") or {}
        if summary and summary.get("sender") is False:
            receiver, source = summary, "sum(receiver)"
        elif summary:
            # iperf3 UDP often places the receiver's loss/jitter in 'sum'.
            receiver, source = summary, "sum(unverified_role)"
    if not receiver:
        return {"observed_mbps": None, "jitter_ms": None,
                "udp_loss_pct": None, "report_section": "unavailable"}
    bps = receiver.get("bits_per_second")
    return {
        "observed_mbps": round(float(bps) / 1e6, 3) if bps is not None else None,
        "jitter_ms": receiver.get("jitter_ms"),
        "udp_loss_pct": receiver.get("lost_percent"),
        "report_section": source,
    }


def take_port_sample(net, mapping, read_interface):
    stamp = utc_now()
    # A sample is a short sequential scan, not an instantaneous snapshot.
    data = {}
    for port in mapping:
        identifier = (port["link_id"], port["node_id"])
        data[identifier] = {**port, **read_interface(net, port["node_name"], port["interface_name"])}
    return stamp, data


def calculate_port_deltas(before, after, duration_s, exp_id, profile, offered):
    rows = []
    for key in before:
        a, b = before[key], after[key]
        values = {}
        for field in COUNTERS:
            diff = int(b[field]) - int(a[field])
            if diff < 0:
                raise RuntimeError(f"Counter reset/decreased: {profile}/{key}/{field}")
            values[field + "_delta"] = diff
        rows.append({
            "experiment_id": exp_id,
            "profile": profile,
            "offered_mbps": offered,
            "link_id": a["link_id"],
            "node_id": a["node_id"],
            "peer_node_id": a["peer_node_id"],
            "interface_name": a["interface_name"],
            "admin_up_before": a["admin_up"],
            "admin_up_after": b["admin_up"],
            "operstate_after": b["operstate"],
            "duration_s": round(duration_s, 3),
            "rx_plus_tx_mbps_proxy": round(
                (values["rx_bytes_delta"] + values["tx_bytes_delta"])
                * 8 / duration_s / 1e6, 5
            ),
            **values,
        })
    return rows


def terminate(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def pilot(args):
    # Delay Mininet imports until after --dry-run, to allow environment checks.
    if not shutil.which("iperf3") and any(rate > 0 for rate in args.rates):
        raise RuntimeError("iperf3 missing in Ubuntu: sudo apt install -y iperf3")
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSBridge
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # repo src/ (script lives in scripts/legacy/)
    from smartmall.emulation import SmartMallSmall
    from collect_small_with_ports import map_interfaces, probe, read_interface

    if not callable(probe):
        raise RuntimeError("Update scripts/legacy/collect_small_with_ports.py before this pilot")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8-sig"))
    if spec.get("topology_id") != "small_v1":
        raise RuntimeError("This pilot requires topology small_v1")
    hosts = sorted(node["id"] for node in spec["nodes"] if node["type"] == "host")
    pairs = list(itertools.combinations(hosts, 2))
    topo = SmartMallSmall(spec=spec)
    names = topo.component_to_mininet
    src_id, dst_id = "PC-SHOP", "SRV-LOCAL"
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exp_id = f"load_pilot_{stamp}_{uuid.uuid4().hex[:6]}"
    folder = ROOT / "data" / "raw" / "small_v1" / exp_id
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(SPEC_PATH, folder / "topology.json")
    manifest = {
        "experiment_id": exp_id, "topology_id": spec["topology_id"],
        "status": "running", "started_at_utc": utc_now(),
        "scope": "NO FAULT; standalone background UDP traffic pilot; not GNN data",
        "flow": {"source_node_id": src_id, "target_node_id": dst_id, "protocol": "UDP/iperf3"},
        "parameters": {"offered_rates_mbps": args.rates,
                       "udp_duration_s": args.duration,
                       "icmp_packets_per_pair": args.packets},
        "profiles": [],
        "limitations": [
            "iperf3 -b is offered load, not guaranteed received throughput",
            "IPERF3 and ICMP share the same emulated network; port MB/s proxies include both directions",
            "Counter samples and six ICMP probes are sequential, not simultaneous",
            "No fault is injected. Compare observable load behavior only.",
            "Keep experiment IDs and timestamps out of ML features",
        ],
    }
    started = False
    server_proc = None
    client_proc = None
    setLogLevel("warning")
    print(f"Experiment: {exp_id}\nOutput: {folder}", flush=True)
    try:
        with (folder / "icmp_telemetry.csv").open("w", encoding="utf-8", newline="") as pf, \
             (folder / "port_deltas.csv").open("w", encoding="utf-8", newline="") as lf:
            p_writer = csv.DictWriter(pf, fieldnames=PROBE_FIELDS)
            l_writer = csv.DictWriter(lf, fieldnames=PORT_FIELDS)
            p_writer.writeheader()
            l_writer.writeheader()
            net.start()
            started = True
            print("Warm-up: baseline pingAll", flush=True)
            if net.pingAll() != 0:
                raise RuntimeError("Baseline pingAll has unexpected loss")
            mapping = map_interfaces(net, spec, names)
            if len(mapping) != 12:
                raise RuntimeError("Expected exactly 12 SMALL interfaces")
            sender, receiver = net.get(names[src_id]), net.get(names[dst_id])
            # Explicit single bridge path PC-SHOP -> SW-COM -> DSW-1 -> SW-ADM -> SRV-LOCAL.
            for index, offered in enumerate(args.rates):
                profile = f"udp_{offered}mbps" if offered else "idle"
                print(f"\nPROFILE {index + 1}/{len(args.rates)}: {profile}", flush=True)
                server_proc = None
                client_proc = None
                port = args.port + index
                if offered:
                    server_proc = receiver.popen(
                        ["iperf3", "-s", "-1", "-p", str(port)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    )
                    time.sleep(0.65)
                    if server_proc.poll() is not None:
                        _, err = server_proc.communicate()
                        raise RuntimeError(f"iperf3 server exited before client: {err.decode(errors='replace')}")
                    client_proc = sender.popen(
                        ["iperf3", "-c", receiver.IP(), "-u", "-b", f"{offered}M",
                         "-l", "1200", "-t", str(args.duration), "-p", str(port), "-J"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    time.sleep(1.0)
                    if client_proc.poll() is not None:
                        out, err = client_proc.communicate()
                        raise RuntimeError(
                            f"iperf3 client failed to start (rc={client_proc.returncode}): "
                            + (err or out).decode(errors="replace")[-1000:]
                        )
                before_time, before = take_port_sample(net, mapping, read_interface)
                start_t = time.monotonic()
                probes = []
                for left, right in pairs:
                    obs = probe(net, names, left, right, args.packets)
                    probes.append(obs)
                    if client_proc is not None and client_proc.poll() not in (None, 0):
                        raise RuntimeError("iperf3 client died while measuring ICMP")
                duration_s = time.monotonic() - start_t
                after_time, after = take_port_sample(net, mapping, read_interface)
                if duration_s <= 0:
                    raise RuntimeError("Nonpositive sampling duration")
                for obs in probes:
                    # The corrected probe() returns the probe_status field.
                    if "probe_status" not in obs:
                        raise RuntimeError("Outdated collect_small_with_ports.py: missing probe_status")
                    p_writer.writerow({"experiment_id": exp_id, "profile": profile,
                                       "offered_mbps": offered, **obs})
                for delta in calculate_port_deltas(before, after, duration_s,
                                                   exp_id, profile, offered):
                    delta["start_time_utc"] = before_time
                    delta["end_time_utc"] = after_time
                    l_writer.writerow(delta)
                unreachable = sum(int(x["reachable"]) == 0 for x in probes)
                usable_rtt = [float(x["rtt_avg_ms"]) for x in probes if x["rtt_avg_ms"] != ""]
                mean_rtt = round(sum(usable_rtt) / len(usable_rtt), 4) if usable_rtt else None
                iperf_stat = None
                if client_proc is not None:
                    try:
                        out, err = client_proc.communicate(timeout=max(10, args.duration + 12))
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("iperf3 client timed out")
                    if client_proc.returncode != 0:
                        raise RuntimeError(
                            f"iperf3 client exited {client_proc.returncode}: "
                            + (err or out).decode(errors="replace")[-1200:]
                        )
                    iperf_data = json.loads(out.decode("utf-8"))
                    if "error" in iperf_data:
                        raise RuntimeError(f"iperf3 error: {iperf_data['error']}")
                    iperf_stat = parse_iperf(iperf_data)
                    (folder / f"iperf3_{profile}.json").write_text(
                        json.dumps(iperf_data, indent=2) + "\n", encoding="utf-8")
                    # iperf3 report can contain sender-only stats. Do not infer a receiver rate.
                    if iperf_stat["report_section"] == "sum(unverified_role)":
                        print("  Note: iperf3 JSON role is unverified; inspect raw report", flush=True)
                    if iperf_stat["observed_mbps"] is None:
                        print("  Note: received throughput absent from iperf3 JSON", flush=True)
                    else:
                        print(f"  iperf3 observed {iperf_stat['observed_mbps']} Mb/s "
                              f"({iperf_stat['report_section']})", flush=True)
                if server_proc is not None:
                    try:
                        server_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("iperf3 server did not exit after one client")
                    if server_proc.returncode != 0:
                        raise RuntimeError(f"iperf3 server exited {server_proc.returncode}")
                server_proc = None
                client_proc = None
                data = {
                    "profile": profile, "offered_mbps": offered,
                    "probe_count": len(probes), "unreachable_probes": unreachable,
                    "mean_reachable_rtt_ms": mean_rtt,
                    "icmp_sample_duration_s": round(duration_s, 3),
                    "iperf3": iperf_stat,
                }
                manifest["profiles"].append(data)
                print(f"  ICMP: {len(probes)} pairs; unreachable={unreachable}; "
                      f"mean RTT={mean_rtt}ms; port deltas=12", flush=True)
                if unreachable > 0:
                    print("  WARNING: reachability changed with background traffic", flush=True)
                pf.flush()
                lf.flush()
                # Prevent lingering UDP sessions between profiles.
                time.sleep(0.3)
        manifest["status"] = "completed"
        print(f"\nSUCCESS: {len(args.rates)} traffic profiles collected (NO FAULT)", flush=True)
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        print(f"PILOT FAILED: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        terminate(client_proc)
        terminate(server_proc)
        if started:
            net.stop()
        manifest["finished_at_utc"] = utc_now()
        (folder / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved pilot output to: {folder}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rates", type=int, nargs="+", default=[0, 5, 40],
                        help="Offered UDP rates in Mb/s (0=idle, default: 0 5 40)")
    parser.add_argument("--duration", type=int, default=15,
                        help="iperf3 UDP duration per active profile in seconds")
    parser.add_argument("--packets", type=int, default=2,
                        help="ICMP packets per host pair, 6 pairs measured")
    parser.add_argument("--port", type=int, default=5201,
                        help="Base TCP control/UDP test port for iperf3")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.rates or any(rate < 0 or rate > 80 for rate in args.rates):
        parser.error("Rates must be between 0 and 80 Mb/s (SMALL access links 100 Mb/s)")
    if len(args.rates) != len(set(args.rates)):
        parser.error("Rates must be unique")
    if args.duration < 15 or args.duration > 90 or args.packets < 1 or args.packets > 5:
        parser.error("Use duration 15..90 seconds and packets 1..5")
    if args.port < 1024 or args.port + len(args.rates) > 65535:
        parser.error("Invalid iperf3 port range")
    print("SmartMall Phase 2.12a — UDP background load PILOT (NO FAULT)")
    print(f"SMALL: PC-SHOP -> SRV-LOCAL; offered Mb/s: {args.rates}")
    print(f"Duration per active profile: {args.duration}s; ICMP packets/pair: {args.packets}")
    print("NOTE: offered rate != measured received throughput; inspect iperf3 JSON")
    if args.dry_run:
        print("DRY RUN: no Mininet process, no files written")
        return
    pilot(args)


if __name__ == "__main__":
    main()
