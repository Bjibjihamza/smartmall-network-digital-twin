#!/usr/bin/env python3
"""Run the validated SmartMall SMALL JSON topology in Mininet (Ubuntu/WSL2).

Usage:
    sudo /usr/bin/python3 scripts/run_small_mininet.py
    sudo /usr/bin/python3 scripts/run_small_mininet.py --cli

This is an initial connectivity proof, not a complete mall LAN configuration.
"""

import argparse
import json
import sys
from pathlib import Path

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.log import setLogLevel

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_FILE = ROOT / "topologies" / "small.json"
sys.path.insert(0, str(ROOT / "src"))

from smartmall.emulation import SmartMallSmall  # noqa: E402,F401  (re-exported for compatibility)


def main():
    parser = argparse.ArgumentParser(description="Emulate SmartMall SMALL with Mininet")
    parser.add_argument("--cli", action="store_true", help="Open interactive Mininet CLI after pingall")
    args = parser.parse_args()

    with TOPOLOGY_FILE.open("r", encoding="utf-8-sig") as f:
        spec = json.load(f)

    topo = SmartMallSmall(spec=spec)
    print(f"\nSmartMall topology: {spec['topology_id']}")
    print("\nMininet component mapping:")
    for original, mapped in topo.component_to_mininet.items():
        address = topo.host_addresses.get(original)
        suffix = f"  {address[1]}" if address else ""
        print(f"  {original:16s} -> {mapped}{suffix}")

    # OVSBridge is in standalone mode; the SMALL topology is loop-free.
    net = Mininet(topo=topo, controller=None, switch=OVSBridge, link=TCLink)
    try:
        net.start()
        print("\n*** Testing host-to-host reachability")
        loss = net.pingAll()
        print(f"\n*** Ping loss: {loss:.1f}%")
        if args.cli:
            print("*** Interactive Mininet CLI (type 'exit' to stop)")
            CLI(net)
        elif loss != 0:
            raise SystemExit("Ping test failed: inspect the Mininet output above.")
    finally:
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    main()
