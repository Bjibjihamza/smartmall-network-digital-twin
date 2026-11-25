"""Scenario (fault / impairment) specifications for SMALL — pure Python.

A scenario is ground truth. Nothing produced here may be written into
telemetry files; it belongs to incident.json only.
"""

from __future__ import annotations

from . import topology as topo

PROTOCOL_VERSION = "small_scenario_v2"

FAULT_FAMILIES = {
    "NONE": {
        "category": "control",
        "target_kind": None,
        "mechanism": "no injection (healthy control experiment)",
    },
    "LINK_FAILURE": {
        "category": "failure",
        "target_kind": "link",
        "mechanism": "Mininet configLinkStatus(down): BOTH link endpoints administratively down",
    },
    "LINK_DELAY": {
        "category": "degradation",
        "target_kind": "link",
        "mechanism": "TCIntf.config on BOTH endpoints: netem delay = baseline + added_delay_ms (each direction)",
    },
    "LINK_LOSS": {
        "category": "degradation",
        "target_kind": "link",
        "mechanism": "TCIntf.config on BOTH endpoints: netem random loss loss_pct (each direction)",
    },
    "LINK_BANDWIDTH": {
        "category": "degradation",
        "target_kind": "link",
        "mechanism": "TCIntf.config on BOTH endpoints: HTB rate bw_mbps, netem limit queue_pkts",
    },
    "NODE_FAILURE": {
        "category": "failure",
        "target_kind": "node",
        "mechanism": ("power-off emulation: the node's OWN interfaces administratively down; "
                      "peers stay admin-up and observe carrier loss"),
    },
    "SWITCH_BLACKHOLE": {
        "category": "failure",
        "target_kind": "switch",
        "mechanism": ("silent data-plane failure: OVS fail-mode secure + all flows deleted; "
                      "interfaces remain UP with carrier"),
    },
}

DEFAULT_QUEUE_PKTS = 1000      # Mininet / netem default limit when max_queue_size is unset


def validate_scenario(spec, fault_type, target=None, params=None):
    """Validate and normalise a scenario. Returns a dict; raises ValueError."""
    params = dict(params or {})
    if fault_type not in FAULT_FAMILIES:
        raise ValueError(f"Unknown fault type {fault_type!r}")
    family = FAULT_FAMILIES[fault_type]
    kind = family["target_kind"]
    links = topo.links_by_id(spec)
    types = topo.node_types(spec)
    if kind is None:
        if target not in (None, "", "NONE"):
            raise ValueError("NONE scenarios take no target")
        target = None
    elif kind == "link":
        if target not in links:
            raise ValueError(f"{fault_type} needs a link target, got {target!r}")
    elif kind == "node":
        if target not in types:
            raise ValueError(f"{fault_type} needs a node target, got {target!r}")
    elif kind == "switch":
        if types.get(target) != "switch":
            raise ValueError(f"{fault_type} needs a switch target, got {target!r}")

    if fault_type == "LINK_DELAY":
        added = float(params.get("added_delay_ms", 0))
        if not 0 < added <= 500:
            raise ValueError("added_delay_ms must be in (0, 500]")
        params = {"added_delay_ms": added}
    elif fault_type == "LINK_LOSS":
        loss = float(params.get("loss_pct", 0))
        if not 0 < loss < 100:
            raise ValueError("loss_pct must be in (0, 100)")
        params = {"loss_pct": loss}
    elif fault_type == "LINK_BANDWIDTH":
        bw = float(params.get("bw_mbps", 0))
        base = float(links[target]["bandwidth_mbps"])
        if not 0 < bw < base:
            raise ValueError(f"bw_mbps must be in (0, {base:g}) for {target}")
        queue = int(params.get("queue_pkts", DEFAULT_QUEUE_PKTS))
        if not 10 <= queue <= 10000:
            raise ValueError("queue_pkts must be in [10, 10000]")
        params = {"bw_mbps": bw, "queue_pkts": queue}
    elif params:
        raise ValueError(f"{fault_type} takes no parameters")
    return {"fault_type": fault_type, "target": target, "params": params,
            "category": family["category"], "mechanism": family["mechanism"]}


def expected_effects(spec, scenario):
    """Ground-truth expectations used ONLY by audits (never as features)."""
    ft, target = scenario["fault_type"], scenario["target"]
    failed_links, failed_nodes = [], []
    if ft == "LINK_FAILURE":
        failed_links = [target]
    elif ft in ("NODE_FAILURE", "SWITCH_BLACKHOLE"):
        failed_nodes = [target]
    disrupted = sorted(topo.disrupted_pairs(spec, failed_links, failed_nodes))
    if ft in ("LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH"):
        affected_links = [target]
    elif ft == "LINK_FAILURE":
        affected_links = [target]
    elif ft in ("NODE_FAILURE", "SWITCH_BLACKHOLE"):
        affected_links = topo.incident_links(spec, target)
    else:
        affected_links = []
    pairs_through = sorted(
        (a, b) for a, b in topo.host_pairs(spec)
        if set(topo.path_links(spec, a, b) or []) & set(affected_links)
    ) if ft in ("LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH") else []
    return {
        "disrupted_pairs_failed_phase": [list(p) for p in disrupted],
        "affected_links": affected_links,
        "impaired_pairs": [list(p) for p in pairs_through],
    }


def flow_affected(spec, scenario, flow_source, flow_target):
    """How the injected scenario relates to the background flow path (ground truth)."""
    path = topo.path_links(spec, flow_source, flow_target) or []
    effects = expected_effects(spec, scenario)
    ft = scenario["fault_type"]
    if ft == "NONE":
        return {"flow_path_links": path, "relation": "no_fault"}
    if [flow_source, flow_target] in effects["disrupted_pairs_failed_phase"] or \
            [flow_target, flow_source] in effects["disrupted_pairs_failed_phase"]:
        relation = "flow_disconnected"
    elif set(path) & set(effects["affected_links"]):
        relation = "flow_impaired" if scenario["category"] == "degradation" else "flow_on_failed_path"
    else:
        relation = "flow_not_on_fault_path"
    endpoint_isolated = None
    if relation == "flow_disconnected":
        # Which endpoint loses its own attachment? Determines iperf3 client behaviour.
        src_link = path[0] if path else None
        dst_link = path[-1] if path else None
        if ft == "LINK_FAILURE":
            endpoint_isolated = ("source" if scenario["target"] == src_link else
                                 "destination" if scenario["target"] == dst_link else "none")
        elif ft in ("NODE_FAILURE",):
            endpoint_isolated = ("source" if scenario["target"] == flow_source else
                                 "destination" if scenario["target"] == flow_target else "none")
        else:
            endpoint_isolated = "none"
    return {"flow_path_links": path, "relation": relation, "endpoint_isolated": endpoint_isolated}
