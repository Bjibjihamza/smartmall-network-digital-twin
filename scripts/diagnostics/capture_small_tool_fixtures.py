#!/usr/bin/env python3
"""Capture real tool outputs (ping, tc, ip, ovs) from SMALL as unit-test fixtures.

    sudo /usr/bin/python3 scripts/diagnostics/capture_small_tool_fixtures.py
Regenerates the parser fixtures used by tests/test_topology_telemetry.py. Writes tests/fixtures/*.txt (overwrites fixtures only; never touches data/).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "src"))


def main():
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSBridge
    from smartmall.emulation import SmartMallSmall
    setLogLevel("error")
    FIX.mkdir(parents=True, exist_ok=True)
    spec = json.loads((ROOT / "topologies" / "small.json").read_text(encoding="utf-8-sig"))
    topo = SmartMallSmall(spec=spec)
    n = topo.component_to_mininet
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    net.start()
    try:
        adm, srv, shop = net.get(n["PC-ADM"]), net.get(n["SRV-LOCAL"]), net.get(n["PC-SHOP"])
        net.pingAll()
        out = {}
        out["ping_ok"] = adm.cmd(f"ping -n -c 3 -i 0.2 -W 2 {srv.IP()}")
        intf = shop.defaultIntf()
        out["tc_qdisc_baseline"] = shop.cmd(f"tc -s qdisc show dev {intf}")
        out["tc_class_baseline"] = shop.cmd(f"tc class show dev {intf}")
        intf.config(bw=10, delay="1ms", max_queue_size=100)
        out["tc_qdisc_bw10"] = shop.cmd(f"tc -s qdisc show dev {intf}")
        out["tc_class_bw10"] = shop.cmd(f"tc class show dev {intf}")
        intf.config(bw=100, delay="21ms", loss=5)
        out["tc_qdisc_delay_loss"] = shop.cmd(f"tc -s qdisc show dev {intf}")
        intf.config(bw=100, delay="1ms")
        # Peer switch interface becomes unreachable target: total loss through a dead path.
        net.configLinkStatus(n["DSW-1"], n["SW-ADM"], "down")
        time.sleep(0.5)
        out["ping_total_loss"] = shop.cmd(f"ping -n -c 3 -i 0.2 -W 2 {srv.IP()}")
        net.configLinkStatus(n["DSW-1"], n["SW-ADM"], "up")
        net.configLinkStatus(n["SW-COM"], n["PC-SHOP"], "down")
        time.sleep(0.5)
        out["ping_local_down"] = shop.cmd(f"ping -n -c 3 -i 0.2 -W 2 {srv.IP()}")
        out["ip_link_down"] = shop.cmd(f"ip -j -s link show dev {intf}")
        net.configLinkStatus(n["SW-COM"], n["PC-SHOP"], "up")
        # host-side-only admin down: peer switch port loses carrier
        intf.ifconfig("down")
        time.sleep(0.5)
        sw = net.get(n["SW-COM"])
        peer = [l for l in net.links if shop in (l.intf1.node, l.intf2.node)][0]
        peer_intf = peer.intf1 if peer.intf1.node is sw else peer.intf2
        out["ip_link_peer_nocarrier"] = sw.cmd(f"ip -j -s link show dev {peer_intf}")
        intf.ifconfig("up")
        for name, text in out.items():
            (FIX / f"{name}.txt").write_text(text, encoding="utf-8")
            print(f"--- {name}\n{text.strip()[:900]}")
    finally:
        net.stop()


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    main()
