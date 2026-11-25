"""Mininet-specific SMALL emulation helpers (imported ONLY on Ubuntu/WSL2 with Mininet).

Moved verbatim from scripts/run_small_mininet.py (SmartMallSmall) and the legacy
v1 collector scripts/legacy/collect_small_with_ports.py (read_interface,
map_interfaces), so that the official v2 pipeline no longer imports a legacy
script. Never import this module from offline tools or unit tests that must run
without Mininet.
"""

import json

from mininet.topo import Topo


class SmartMallSmall(Topo):
    """Translate component IDs to Mininet-safe switch and host names."""

    def build(self, spec):
        self.component_to_mininet = {}
        self.host_addresses = {}
        host_index = 0
        switch_index = 0

        if spec.get("family") != "small":
            raise ValueError("This first runner only supports the SMALL topology.")

        for component in spec["nodes"]:
            component_id = component["id"]
            if component_id in self.component_to_mininet:
                raise ValueError(f"Duplicate component ID: {component_id}")

            if component["type"] == "switch":
                switch_index += 1
                node_name = f"s{switch_index}"
                self.addSwitch(node_name)
            elif component["type"] == "host":
                host_index += 1
                node_name = f"h{host_index}"
                ip_address = f"10.42.0.{10 + host_index}/24"
                self.addHost(node_name, ip=ip_address)
                self.host_addresses[component_id] = (node_name, ip_address)
            else:
                raise ValueError(f"Unsupported node type: {component['type']}")

            self.component_to_mininet[component_id] = node_name

        seen_links = set()
        for link in spec["links"]:
            source = link["source"]
            target = link["target"]
            if source not in self.component_to_mininet or target not in self.component_to_mininet:
                raise ValueError(f"Unknown endpoint in {link['id']}")
            if source == target:
                raise ValueError(f"Self-loop in {link['id']}")
            pair = frozenset((source, target))
            if pair in seen_links:
                raise ValueError(f"Parallel link in {link['id']}; not supported by this runner")
            seen_links.add(pair)

            self.addLink(
                self.component_to_mininet[source],
                self.component_to_mininet[target],
                bw=float(link["bandwidth_mbps"]),
                delay=f"{float(link['delay_ms']):g}ms",
            )


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
