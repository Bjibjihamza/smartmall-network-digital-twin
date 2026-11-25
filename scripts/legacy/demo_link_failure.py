#!/usr/bin/env python3
"""SmartMall SMALL: controlled link-failure experiment (diagnostic smoke test).

Requires scripts/run_small_mininet.py and topologies/small.json.
Run on Ubuntu/WSL2:
    sudo /usr/bin/python3 scripts/legacy/demo_link_failure.py

This is a manual experiment, NOT a labeled ML dataset generator.
"""

import json
import re
import sys
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSBridge

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # repo src/ (script lives in scripts/legacy/)
from smartmall.emulation import SmartMallSmall
ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = ROOT / "topologies" / "small.json"
FAILED_LINK = ("DSW-1", "SW-COM")
SAMPLES = (
    ("PC-ADM", "POS", "Cross-zone: should FAIL during incident"),
    ("PC-ADM", "SRV-LOCAL", "Same ADM branch: should remain UP"),
    ("PC-SHOP", "POS", "Same COM branch: should remain UP"),
)


def ping_pair(net, names, source, target):
    hsrc = net.get(names[source])
    hdst = net.get(names[target])
    # -n avoids reverse DNS; -c/-W bound the wait during deliberate failure.
    output = hsrc.cmd(f"ping -n -c 2 -W 1 {hdst.IP()}")
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    if not match:
        raise RuntimeError(f"Unparseable ping output for {source} -> {target}:\n{output}")
    loss = float(match.group(1))
    rtt_match = re.search(r"rtt min/avg/max/(?:mdev|stddev) = [^/]+/([^/]+)/", output)
    rtt = float(rtt_match.group(1)) if rtt_match else None
    return loss, rtt


def observe(net, names, phase):
    print(f"\n{'-' * 70}\n{phase}\n{'-' * 70}")
    outcomes = {}
    for src, dst, reason in SAMPLES:
        loss, rtt = ping_pair(net, names, src, dst)
        metric = f"RTT avg {rtt:.2f} ms" if rtt is not None else "RTT not available"
        print(f"  {src:10s} -> {dst:10s}  loss={loss:5.1f}%  {metric}  | {reason}")
        outcomes[(src, dst)] = loss
    return outcomes


def main():
    with SPEC_FILE.open(encoding="utf-8-sig") as stream:
        spec = json.load(stream)
    assert spec.get("topology_id") == "small_v1", "Expected small_v1"
    assert any({x["source"], x["target"]} == set(FAILED_LINK) for x in spec["links"]), (
        "Injected failure target not found in topology JSON"
    )

    topo = SmartMallSmall(spec=spec)
    names = topo.component_to_mininet
    sw1, sw2 = (names[component] for component in FAILED_LINK)
    print(f"SmartMall scenario: {spec['topology_id']}")
    print(f"Ground truth (experiment operator only): link {FAILED_LINK[0]} <-> {FAILED_LINK[1]}")
    print(f"Emulated interface pair: {sw1} <-> {sw2}")

    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    link_disabled = False
    try:
        net.start()
        print("\nWarming up forwarding and ARP tables ...")
        initial_loss = net.pingAll()
        if initial_loss != 0:
            raise RuntimeError(f"Baseline is not healthy: pingAll loss={initial_loss}%")
        healthy_before = observe(net, names, "PHASE A — HEALTHY BEFORE FAILURE")

        print(f"\n[INJECT] Disabling {FAILED_LINK[0]} <-> {FAILED_LINK[1]}")
        net.configLinkStatus(sw1, sw2, "down")
        link_disabled = True
        time.sleep(0.5)
        during = observe(net, names, "PHASE B — LINK DOWN")

        print(f"\n[RESTORE] Re-enabling {FAILED_LINK[0]} <-> {FAILED_LINK[1]}")
        net.configLinkStatus(sw1, sw2, "up")
        link_disabled = False
        time.sleep(1)
        # A full ping sweep encourages recovery of stale forwarding entries.
        net.pingAll()
        healthy_after = observe(net, names, "PHASE C — RECOVERED")

        cross = ("PC-ADM", "POS")
        left = ("PC-ADM", "SRV-LOCAL")
        right = ("PC-SHOP", "POS")
        checks = {
            "initial cross-zone connectivity": healthy_before[cross] == 0,
            "cross-zone disruption during failure": during[cross] == 100,
            "ADM branch stays reachable": during[left] == 0,
            "COM branch stays reachable": during[right] == 0,
            "cross-zone connectivity recovered": healthy_after[cross] == 0,
        }
        print("\nEXPERIMENT CHECKS")
        for name, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not all(checks.values()):
            raise SystemExit("One or more checks failed. Review the output above.")
        print("\nSUCCESS: controlled failure, observed impact, and recovery verified.")
        print("Note: these are connectivity probes, not yet a training dataset.")
    finally:
        if link_disabled:
            try:
                net.configLinkStatus(sw1, sw2, "up")
            except Exception as exc:
                print(f"Warning: unable to restore link before teardown: {exc}")
        net.stop()


if __name__ == "__main__":
    setLogLevel("warning")
    main()
