#!/usr/bin/env python3
"""SmartMall Phase 2.12c — independently verify iperf3 UDP receiver goodput on SMALL.

This is a short, separate verification run with NO injected fault. It does NOT
modify earlier load_pilot / receiver_verify folders or LINK_FAILURE datasets.

From the SmartMall project root in Ubuntu / WSL2:
    sudo /usr/bin/python3 scripts/verify_small_iperf_receiver.py --dry-run
    sudo /usr/bin/python3 scripts/verify_small_iperf_receiver.py
    # Offline re-analysis of an existing folder (no Mininet, read-only):
    python3 scripts/verify_small_iperf_receiver.py --reanalyze data/raw/small_v1/receiver_verify_...

Receiver evidence = iperf3 SERVER (-s -J) per-interval byte counts, aggregated as
total bytes / total measured seconds (src/smartmall/iperf_receiver.py).
iperf3 3.9 reports end.sum.bytes=0 on the receiver; that summary is never used
as a rate. Client values are recorded as SENDER values only. The receiving
host's NIC rx_bytes delta is an independent (overhead-inclusive) cross-check.
"""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "topologies" / "small.json"
sys.path.insert(0, str(ROOT / "src"))

from smartmall.iperf_receiver import (  # noqa: E402
    STATUS_VERIFIED, receiver_interval_rows, receiver_udp_stats, sender_udp_stats,
)

# Acceptance thresholds for an UNCONGESTED verification path (100 Mb/s access links).
MAX_RATE_DEVIATION = 0.05      # |receiver - offered| / offered
MAX_LOSS_PCT = 1.0
UDP_OVERHEAD_BYTES = 8 + 20 + 14   # UDP + IPv4 + Ethernet header per datagram


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def evaluate_profile(offered, server_json, client_json, nic_rx_bytes=None, nic_seconds=None,
                     blksize=1200):
    """Pure evaluation of one profile; returns (record, list_of_failures)."""
    rec = receiver_udp_stats(server_json)
    snd = sender_udp_stats(client_json) if client_json is not None else {"status": "absent"}
    failures = []
    if rec["status"] != STATUS_VERIFIED:
        failures.append(f"receiver status {rec['status']}: {rec['reason']}")
    else:
        dev = abs(rec["receiver_mbps"] - offered) / offered
        if dev > MAX_RATE_DEVIATION:
            failures.append(f"receiver {rec['receiver_mbps']} Mb/s deviates {dev:.1%} from offered")
        if rec["loss_pct"] is None:
            failures.append("receiver loss unavailable")
        elif rec["loss_pct"] > MAX_LOSS_PCT:
            failures.append(f"receiver loss {rec['loss_pct']}% > {MAX_LOSS_PCT}%")
    # Server copy embedded in the client report must agree with the standalone server JSON.
    embedded = (client_json or {}).get("server_output_json")
    embedded_check = "absent"
    if isinstance(embedded, dict):
        emb = receiver_udp_stats(embedded)
        embedded_check = "match" if emb.get("received_bytes") == rec.get("received_bytes") else "mismatch"
        if embedded_check == "mismatch":
            failures.append("server JSON and client --get-server-output disagree")
    nic = None
    if nic_rx_bytes is not None and nic_seconds and rec.get("received_packets") is not None:
        expected_wire = rec["received_bytes"] + rec["received_packets"] * UDP_OVERHEAD_BYTES
        nic = {
            "nic_rx_bytes_delta": nic_rx_bytes,
            "nic_window_s": round(nic_seconds, 3),
            "nic_rx_mbps": round(nic_rx_bytes * 8 / nic_seconds / 1e6, 4),
            "expected_wire_bytes_from_receiver": expected_wire,
            # NIC window encloses the whole test, so it must carry at least the payload+headers.
            "nic_covers_receiver_bytes": nic_rx_bytes >= expected_wire,
        }
        if not nic["nic_covers_receiver_bytes"]:
            failures.append("receiver NIC counted fewer bytes than iperf3 reports received")
    record = {
        "offered_mbps": offered,
        "receiver": rec,
        "sender": snd,
        "embedded_server_output_check": embedded_check,
        "nic_cross_check": nic,
        "acceptance": "PASS" if not failures else "FAIL",
        "failures": failures,
    }
    return record, failures


def write_intervals_csv(path, profile, server_json):
    rows = receiver_interval_rows(server_json)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["profile", "interval_index", "rel_start_s", "rel_end_s", "abs_start_unix",
                  "abs_end_unix", "seconds", "bytes", "packets", "lost_packets",
                  "jitter_ms", "omitted"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({"profile": profile, **row})


def stop_process(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def run(args):
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSBridge
    from smartmall.emulation import SmartMallSmall, read_interface

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8-sig"))
    if spec.get("topology_id") != "small_v1":
        raise RuntimeError("Expected SMALL topology 'small_v1'")

    topo = SmartMallSmall(spec=spec)
    sender_name = topo.component_to_mininet["PC-SHOP"]
    receiver_name = topo.component_to_mininet["SRV-LOCAL"]
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    expid = ("receiver_verify_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
             + "_" + uuid.uuid4().hex[:6])
    output = ROOT / "data" / "raw" / "small_v1" / expid
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(SPEC_PATH, output / "topology.json")
    manifest = {
        "experiment_id": expid,
        "topology_id": "small_v1",
        "status": "running",
        "started_at_utc": utc_now(),
        "purpose": "Independent UDP receiver-goodput verification (NO FAULT)",
        "source": "PC-SHOP",
        "destination": "SRV-LOCAL",
        "path_links": ["L5", "L2", "L1", "L4"],
        "duration_s": args.duration,
        "rates_offered_mbps": args.rates,
        "datagram_payload_bytes": 1200,
        "iperf3_version": subprocess.run(["iperf3", "--version"], capture_output=True,
                                         text=True).stdout.splitlines()[0],
        "parser": "src/smartmall/iperf_receiver.py receiver_udp_stats (byte-weighted intervals)",
        "parser_sha256": hashlib.sha256(
            (ROOT / "src" / "smartmall" / "iperf_receiver.py").read_bytes()).hexdigest(),
        "acceptance_criteria": {
            "receiver_status": STATUS_VERIFIED,
            "max_rate_deviation": MAX_RATE_DEVIATION,
            "max_loss_pct": MAX_LOSS_PCT,
            "nic_rx_must_cover_receiver_bytes": True,
            "embedded_server_output_must_match": True,
        },
        "profiles": [],
        "limitations": [
            "Fresh standalone tests, not a retroactive receiver measurement of the earlier load pilot",
            "No network fault injected; no claim of congestion or causal RTT change",
            "Receiver-side iperf3 UDP goodput excludes UDP/IP/Ethernet headers; NIC counters include them",
        ],
    }

    started = False
    client_proc = None
    server_proc = None
    setLogLevel("warning")
    print(f"Verification: {expid}\nOutput: {output}", flush=True)
    try:
        net.start()
        started = True
        if net.pingAll() != 0:
            raise RuntimeError("Baseline connectivity failed")
        sender = net.get(sender_name)
        receiver = net.get(receiver_name)
        rx_intf = receiver.defaultIntf().name
        all_failures = []
        for i, offered in enumerate(args.rates):
            name = f"udp_{offered}mbps"
            port = args.port + i
            print(f"\nPROFILE {i+1}/{len(args.rates)}: offered {offered} Mb/s", flush=True)
            server_proc = receiver.popen(
                ["iperf3", "-s", "-1", "-J", "-p", str(port)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            if server_proc.poll() is not None:
                out, err = server_proc.communicate()
                raise RuntimeError(f"iperf3 server could not start: "
                                   f"{(err or out).decode(errors='replace')[-1200:]}")
            nic_before = read_interface(net, receiver_name, rx_intf)
            t0 = time.monotonic()
            client_proc = sender.popen(
                ["iperf3", "-c", receiver.IP(), "-u", "-b", f"{offered}M",
                 "-l", "1200", "-t", str(args.duration), "-p", str(port),
                 "-J", "--get-server-output", "--connect-timeout", "3000"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            client_out, client_err = client_proc.communicate(timeout=args.duration + 25)
            if client_proc.returncode != 0:
                raise RuntimeError(f"iperf3 client failed (rc={client_proc.returncode}): "
                                   f"{(client_err or client_out).decode(errors='replace')[-1500:]}")
            server_out, server_err = server_proc.communicate(timeout=15)
            nic_after = read_interface(net, receiver_name, rx_intf)
            nic_seconds = time.monotonic() - t0
            client_json = json.loads(client_out.decode("utf-8"))
            (output / f"iperf3_client_{name}.json").write_text(
                json.dumps(client_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if server_proc.returncode != 0:
                raise RuntimeError(f"iperf3 server failed (rc={server_proc.returncode}): "
                                   f"{(server_err or server_out).decode(errors='replace')[-1500:]}")
            server_json = json.loads(server_out.decode("utf-8"))
            (output / f"iperf3_server_{name}.json").write_text(
                json.dumps(server_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            write_intervals_csv(output / f"receiver_intervals_{name}.csv", name, server_json)
            record, failures = evaluate_profile(
                offered, server_json, client_json,
                nic_rx_bytes=int(nic_after["rx_bytes"]) - int(nic_before["rx_bytes"]),
                nic_seconds=nic_seconds)
            manifest["profiles"].append({"profile": name, **record})
            all_failures += [f"{name}: {f}" for f in failures]
            r = record["receiver"]
            print(f"  Receiver ({r['status']}): {r['receiver_mbps']} Mb/s over "
                  f"{r['measured_seconds']} s; packets={r['received_packets']} "
                  f"lost={r['lost_packets']} ({r['loss_pct']}%); jitter={r['jitter_ms']} ms",
                  flush=True)
            print(f"  Sender (not receiver evidence): {record['sender'].get('sent_mbps')} Mb/s",
                  flush=True)
            print(f"  NIC rx cross-check: {record['nic_cross_check']}", flush=True)
            print(f"  Acceptance: {record['acceptance']} {failures or ''}", flush=True)
            client_proc = None
            server_proc = None
        manifest["status"] = "completed" if not all_failures else "completed_with_failures"
        manifest["acceptance"] = "PASS" if not all_failures else "FAIL"
        print(f"\nRESULT: {manifest['acceptance']} for {len(args.rates)} profiles", flush=True)
        if all_failures:
            raise RuntimeError("; ".join(all_failures))
    except Exception as exc:
        if manifest["status"] == "running":
            manifest["status"] = "failed"
        manifest["error"] = str(exc)
        print(f"VERIFICATION FAILED: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        stop_process(client_proc)
        stop_process(server_proc)
        if started:
            net.stop()
        manifest["finished_at_utc"] = utc_now()
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved verification data: {output}", flush=True)
    return output


def reanalyze(folder):
    """Read-only re-analysis of an existing folder with the corrected parser."""
    results = []
    for server_file in sorted(folder.glob("iperf3_server_*.json")):
        profile = server_file.stem[len("iperf3_server_"):]
        offered = float(profile.split("_")[1].replace("mbps", ""))
        client_file = folder / f"iperf3_client_{profile}.json"
        client = json.loads(client_file.read_text(encoding="utf-8")) if client_file.is_file() else None
        record, _ = evaluate_profile(offered, json.loads(server_file.read_text(encoding="utf-8")),
                                     client)
        results.append({"folder": folder.name, "profile": profile, **record})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rates", nargs="+", type=int, default=[5, 40],
                        help="UDP offered rates in Mb/s (default 5 40)")
    parser.add_argument("--duration", type=int, default=10,
                        help="Duration in seconds per UDP profile (default 10)")
    parser.add_argument("--port", type=int, default=5301, help="Base port (default 5301)")
    parser.add_argument("--reanalyze", type=Path, nargs="+", default=None,
                        help="Offline: re-evaluate existing receiver_verify folders (read-only)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.reanalyze:
        for folder in args.reanalyze:
            for res in reanalyze(folder):
                r = res["receiver"]
                print(json.dumps({"folder": res["folder"], "profile": res["profile"],
                                  "status": r["status"], "receiver_mbps": r["receiver_mbps"],
                                  "received_packets": r["received_packets"],
                                  "loss_pct": r["loss_pct"], "jitter_ms": r["jitter_ms"],
                                  "sender_mbps": res["sender"].get("sent_mbps"),
                                  "acceptance": res["acceptance"], "warnings": r["warnings"]}))
        return
    if not args.rates or any(v <= 0 or v > 80 for v in args.rates):
        parser.error("Use distinct UDP rates in 1..80 Mb/s")
    if len(args.rates) != len(set(args.rates)):
        parser.error("Rates must be distinct")
    if args.duration < 5 or args.duration > 30:
        parser.error("Duration must be between 5 and 30 seconds")
    if args.port < 1024 or args.port + len(args.rates) > 65535:
        parser.error("Invalid port range")
    print("SmartMall Phase 2.12c — iperf3 SERVER-SIDE receiver verification (NO FAULT)")
    print(f"SMALL: PC-SHOP -> SRV-LOCAL; rates={args.rates}; duration={args.duration}s")
    if args.dry_run:
        print("DRY RUN: no Mininet and no output files")
        return
    if not shutil.which("iperf3"):
        raise RuntimeError("iperf3 not installed in Ubuntu. Run: sudo apt install -y iperf3")
    run(args)


if __name__ == "__main__":
    main()
