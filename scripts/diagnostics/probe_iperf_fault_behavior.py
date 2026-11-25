#!/usr/bin/env python3
"""Stage B design probe: how does a continuous iperf3 UDP flow behave across a link fault?

NO dataset output: prints observations and stores a small JSON evidence file under
data/raw/small_v1/design_probe_<id>/ (new folder, never overwrites).

    sudo /usr/bin/python3 scripts/diagnostics/probe_iperf_fault_behavior.py --links L1 L5 L4
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.iperf_receiver import receiver_udp_stats  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--links", nargs="+", default=["L1", "L5", "L4"])
    p.add_argument("--rate", type=int, default=5)
    args = p.parse_args()
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSBridge
    from smartmall.emulation import SmartMallSmall
    setLogLevel("error")
    spec = json.loads((ROOT / "topologies" / "small.json").read_text(encoding="utf-8-sig"))
    links = {l["id"]: l for l in spec["links"]}
    out_dir = ROOT / "data" / "raw" / "small_v1" / (
        "design_probe_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6])
    out_dir.mkdir(parents=True, exist_ok=False)
    evidence = {"purpose": "continuous iperf3 UDP flow across a link fault (design probe)", "runs": []}
    for link_id in args.links:
        topo = SmartMallSmall(spec=spec)
        names = topo.component_to_mininet
        net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
        net.start()
        try:
            snd, rcv = net.get(names["PC-SHOP"]), net.get(names["SRV-LOCAL"])
            a, b = names[links[link_id]["source"]], names[links[link_id]["target"]]
            srv = rcv.popen(["iperf3", "-s", "-1", "-J", "-p", "5401"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.5)
            t0 = time.time()
            cli = snd.popen(["iperf3", "-c", rcv.IP(), "-u", "-b", f"{args.rate}M", "-l", "1200",
                             "-t", "12", "-p", "5401", "-J", "--connect-timeout", "2000"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(3)
            net.configLinkStatus(a, b, "down")
            t_down = time.time() - t0
            time.sleep(4)
            alive_during_fault = cli.poll() is None
            net.configLinkStatus(a, b, "up")
            t_up = time.time() - t0
            try:
                cout, cerr = cli.communicate(timeout=25)
            except subprocess.TimeoutExpired:
                cli.kill()
                cout, cerr = cli.communicate()
            try:
                sout, serr = srv.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                srv.kill()
                sout, serr = srv.communicate()
            run = {"link": link_id, "fault_at_s": round(t_down, 2), "restore_at_s": round(t_up, 2),
                   "client_alive_during_fault": alive_during_fault, "client_rc": cli.returncode,
                   "server_rc": srv.returncode}
            try:
                cj = json.loads(cout.decode() or "{}")
                run["client_error"] = cj.get("error")
            except json.JSONDecodeError:
                run["client_raw"] = (cout + cerr).decode(errors="replace")[-400:]
            try:
                sj = json.loads(sout.decode() or "{}")
                run["server_error"] = sj.get("error")
                stats = receiver_udp_stats({k: v for k, v in sj.items() if k != "error"})
                run["receiver_status"] = stats["status"]
                run["receiver_lost_packets"] = stats["lost_packets"]
                run["receiver_received_packets"] = stats["received_packets"]
                run["per_interval_bytes"] = [int(i["sum"]["bytes"]) for i in sj.get("intervals", [])]
            except json.JSONDecodeError:
                run["server_raw"] = (sout + serr).decode(errors="replace")[-400:]
            print(json.dumps(run), flush=True)
            evidence["runs"].append(run)
        finally:
            net.stop()
    (out_dir / "design_probe.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {out_dir}")


if __name__ == "__main__":
    main()
