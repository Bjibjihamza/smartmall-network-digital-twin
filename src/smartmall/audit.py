"""Audit of one small_scenario_v2 experiment folder (pure Python, no Mininet).

The audit compares raw telemetry with ground truth (incident.json). Ground
truth is used here ONLY to verify the laboratory, never to build features.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from . import topology as topo
from .telemetry import window_receiver_bytes

LABEL_COLUMNS = {"phase", "fault_type", "fault_link_id", "fault_target", "label",
                 "ground_truth", "scenario", "category"}
EXPECTED_COLUMNS = {
    "icmp_probes.csv": ["experiment_id", "window_id", "source_node_id", "target_node_id",
                        "probe_start_utc", "probe_end_utc", "packets_sent", "packets_received",
                        "loss_pct", "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms",
                        "icmp_errors", "reachable", "probe_status"],
    "port_samples.csv": None, "port_window_deltas.csv": None, "tc_samples.csv": None,
    "receiver_intervals.csv": None,
}
UDP_WIRE_FACTOR = (1200 + 8 + 20 + 14) / 1200.0
RATE_TOL = 0.10          # healthy-window receiver rate tolerance vs offered
NIC_TOL = 0.10           # NIC vs receiver x wire-factor tolerance


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Checks:
    def __init__(self):
        self.items = []

    def add(self, name, ok, detail=""):
        self.items.append({"check": name, "pass": bool(ok), "detail": detail})
        return ok

    @property
    def passed(self):
        return all(item["pass"] for item in self.items)

    def failures(self):
        return [i for i in self.items if not i["pass"]]


def auditor_version():
    import hashlib
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def audit_experiment(folder):
    folder = Path(folder)
    checks = Checks()
    gt = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
    spec = json.loads((folder / "topology.json").read_text(encoding="utf-8-sig"))
    sc = gt["scenario"]
    ft = sc["fault_type"]
    proto = gt["protocol"]
    rounds = proto["rounds_per_phase"]
    window_s = proto["window_s"]
    pairs = [tuple(p) for p in proto["probe_pairs"]]
    n_ports = 2 * len(spec["links"])
    result = {"experiment_id": gt["experiment_id"], "fault_type": ft, "target": sc["target"],
              "params": sc["params"], "offered_mbps": gt["traffic"]["offered_mbps"],
              "campaign_id": gt.get("campaign_id"), "repetition": gt.get("repetition"),
              "auditor_sha256": auditor_version()}

    checks.add("status_completed", gt["status"] == "completed", gt.get("error", ""))

    # ---------------- schema / leakage
    tables = {}
    for name, expected in EXPECTED_COLUMNS.items():
        path = folder / name
        if not checks.add(f"file_present:{name}", path.is_file()):
            continue
        cols, rows = read_csv(path)
        tables[name] = rows
        checks.add(f"no_label_columns:{name}", not (set(cols) & LABEL_COLUMNS),
                   str(sorted(set(cols) & LABEL_COLUMNS)))
        if expected is not None:
            checks.add(f"schema:{name}", cols == expected, f"got {cols}")
        ids = {r["experiment_id"] for r in rows}
        checks.add(f"experiment_id_consistent:{name}", ids <= {gt["experiment_id"]}, str(ids))
    if gt["status"] != "completed" or len(tables) < len(EXPECTED_COLUMNS):
        result.update(passed=False, checks=checks.items,
                      failed_checks=[c["check"] for c in checks.failures()] or ["incomplete_experiment"])
        return result

    # ---------------- windows & timing
    windows = gt["windows"]
    phases = [w["phase"] for w in windows]
    checks.add("window_count", len(windows) == 3 * rounds, f"{len(windows)}")
    checks.add("phase_order", phases == ["healthy"] * rounds + ["failed"] * rounds + ["recovered"] * rounds,
               str(phases))
    durations = [w["end_unix"] - w["start_unix"] for w in windows]
    checks.add("window_durations", all(window_s - 0.05 <= d <= window_s + 1.5 for d in durations),
               f"min={min(durations):.3f} max={max(durations):.3f}")
    checks.add("windows_non_overlapping",
               all(windows[i]["end_unix"] <= windows[i + 1]["start_unix"] for i in range(len(windows) - 1)))
    wid_phase = {w["window_id"]: w["phase"] for w in windows}
    wins = {w["window_id"]: w for w in windows}
    last_h = windows[rounds - 1]["end_utc"]
    first_f = windows[rounds]["start_utc"]
    last_f = windows[2 * rounds - 1]["end_utc"]
    first_r = windows[2 * rounds]["start_utc"]
    checks.add("injection_between_phases", last_h <= (gt["injected_at_utc"] or "") <= first_f,
               f"{gt['injected_at_utc']}")
    checks.add("restoration_between_phases", last_f <= (gt["restored_at_utc"] or "") <= first_r,
               f"{gt['restored_at_utc']}")
    rec = gt.get("recovery") or {}
    checks.add("recovery_verified", rec.get("all_pairs_reachable") is True, str(rec))
    cleanup = gt.get("cleanup", {})
    checks.add("cleanup_tc_restored", cleanup.get("tc_restored_to_baseline") is True)
    checks.add("cleanup_ports_up", cleanup.get("all_ports_admin_up_with_carrier") is True)
    checks.add("cleanup_no_ovs_bridges", cleanup.get("ovs_bridges_after_stop") == [],
               str(cleanup.get("ovs_bridges_after_stop")))
    checks.add("no_emergency_restore", not cleanup.get("emergency_restore"))

    inj_ok, inj_detail = _check_injector(gt, spec)
    checks.add("injector_effect_verified_and_reverted", inj_ok, inj_detail)

    # ---------------- ICMP
    icmp = tables["icmp_probes.csv"]
    checks.add("icmp_row_count", len(icmp) == len(windows) * len(pairs), f"{len(icmp)}")
    by_window = {}
    status_ok = True
    for r in icmp:
        by_window.setdefault(r["window_id"], []).append(r)
        if r["probe_status"] == "route_unreachable":
            status_ok &= r["packets_sent"] == "0" and r["loss_pct"] == "" and r["reachable"] == "0"
        elif r["probe_status"] == "icmp_stats":
            status_ok &= r["loss_pct"] != "" and int(r["packets_sent"]) > 0
        else:
            status_ok = False
    checks.add("icmp_status_semantics", status_ok,
               "route_unreachable => 0 sent & undefined loss; icmp_stats => defined loss")
    expected_disrupted = {tuple(p) for p in gt["expected"]["disrupted_pairs_failed_phase"]}
    observed = {}
    sig_ok = True
    for wid, rows in by_window.items():
        dis = {(r["source_node_id"], r["target_node_id"]) for r in rows if r["reachable"] == "0"}
        observed[wid] = sorted(dis)
        exp = expected_disrupted if wid_phase[wid] == "failed" else set()
        if ft in ("LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH", "NONE"):
            exp = set()
        congested = (ft == "LINK_BANDWIDTH" and
                     gt["traffic"]["offered_mbps"] > sc["params"].get("bw_mbps", 1e9))
        if (ft == "LINK_LOSS" or congested) and wid_phase[wid] == "failed":
            # Random loss or tail-drop can discard all echoes of an impaired pair; judged
            # by observed_effects instead. Pairs NOT through the target must stay reachable.
            impaired = {tuple(p) for p in gt["expected"]["impaired_pairs"]}
            if dis - impaired:
                sig_ok = False
            continue
        if dis != exp:
            sig_ok = False
    checks.add("connectivity_signature_matches_expectation", sig_ok,
               json.dumps({k: v for k, v in observed.items() if v}))
    result["observed_disrupted_pairs"] = observed

    # ---------------- ports
    samples = tables["port_samples.csv"]
    deltas = tables["port_window_deltas.csv"]
    checks.add("port_sample_count", len(samples) == len(windows) * n_ports * 2, f"{len(samples)}")
    checks.add("port_delta_count", len(deltas) == len(windows) * n_ports, f"{len(deltas)}")
    checks.add("no_counter_resets", all(r["counter_reset"] == "0" for r in deltas))
    ok_dur = all(window_s - 0.2 <= float(r["duration_s"]) <= window_s + 1.6 for r in deltas)
    checks.add("delta_durations", ok_dur)
    state_ok, state_detail = _check_port_states(ft, sc["target"], spec, deltas, wid_phase)
    checks.add("interface_states_match_mechanism", state_ok, state_detail)

    # ---------------- tc configuration
    tc_ok, tc_detail = _check_tc(ft, sc, spec, tables["tc_samples.csv"], wid_phase)
    checks.add("tc_configuration_matches_phase", tc_ok, tc_detail)

    # ---------------- traffic
    traffic = _traffic_windows(gt, tables["receiver_intervals.csv"], deltas, windows)
    result["traffic_windows"] = traffic
    if gt["traffic"]["offered_mbps"] > 0:
        _check_traffic(checks, gt, traffic, windows, rounds)

    # ---------------- family-specific observed effects
    effects = observed_effects(gt, spec, icmp, deltas, tables["tc_samples.csv"], traffic, wid_phase)
    result["observed_effects"] = effects
    for name, ok, detail in effects.get("checks", []):
        checks.add(name, ok, detail)

    result.update(passed=checks.passed, checks=checks.items,
                  failed_checks=[c["check"] for c in checks.failures()],
                  warnings=effects.get("warnings", []))
    return result


def _check_injector(gt, spec):
    """Direct mechanism evidence recorded right after inject() and restore()."""
    sc, ft = gt["scenario"], gt["scenario"]["fault_type"]
    ev = gt.get("injector_evidence") or {}
    if ft == "NONE":
        return True, "no injection"
    inj, rst = ev.get("after_inject", {}), ev.get("after_restore", {})
    problems = []
    links = topo.links_by_id(spec)
    if ft in ("LINK_FAILURE", "LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH"):
        link = links[sc["target"]]
        for when, data, active in (("inject", inj, True), ("restore", rst, False)):
            intfs = data.get("interfaces", {})
            if len(intfs) != 2:
                problems.append(f"{when}: expected 2 interfaces, got {len(intfs)}")
            for name, v in intfs.items():
                exp_admin = 0 if (active and ft == "LINK_FAILURE") else 1
                if v["admin_up"] != exp_admin:
                    problems.append(f"{when}:{name} admin_up={v['admin_up']}")
                exp_delay = float(link["delay_ms"]) + (sc["params"].get("added_delay_ms", 0) if active else 0)
                exp_loss = sc["params"].get("loss_pct") if active else None
                exp_rate = sc["params"].get("bw_mbps", link["bandwidth_mbps"]) if active else link["bandwidth_mbps"]
                if v["delay_ms"] != exp_delay or v["loss_pct"] != exp_loss or float(v["rate_mbps"]) != float(exp_rate):
                    problems.append(f"{when}:{name} tc={v['rate_mbps']},{v['delay_ms']},{v['loss_pct']}")
    elif ft == "NODE_FAILURE":
        # evidence covers the node's own interfaces AND their peers (2 per incident link)
        seen = list(inj.get("interfaces", {}).values())
        if len(seen) != 2 * len(topo.incident_links(spec, sc["target"])):
            problems.append(f"expected {2 * len(topo.incident_links(spec, sc['target']))} interfaces, got {len(seen)}")
        down = sum(1 for v in seen if v["admin_up"] == 0)
        if down != len(topo.incident_links(spec, sc["target"])):
            problems.append(f"admin-down interfaces after inject: {down}")
        if any(v["admin_up"] != 1 for v in rst.get("interfaces", {}).values()):
            problems.append("interfaces still admin-down after restore")
    elif ft == "SWITCH_BLACKHOLE":
        if inj.get("fail_mode") != "secure" or inj.get("flow_count") != 0:
            problems.append(f"inject: fail_mode={inj.get('fail_mode')} flows={inj.get('flow_count')}")
        if rst.get("fail_mode") != "standalone":
            problems.append(f"restore: fail_mode={rst.get('fail_mode')}")
        if any(v["admin_up"] != 1 or v["carrier"] != 1 for v in inj.get("interfaces", {}).values()):
            problems.append("blackhole must keep interfaces up with carrier")
    return not problems, "; ".join(problems)


def _check_port_states(ft, target, spec, deltas, wid_phase):
    bad = []
    for r in deltas:
        phase = wid_phase[r["window_id"]]
        admin, carrier = r["admin_up_after"], r["carrier_after"]
        exp_admin, exp_carrier = "1", "1"
        if phase == "failed":
            if ft == "LINK_FAILURE" and r["link_id"] == target:
                exp_admin, exp_carrier = "0", "0"
            elif ft == "NODE_FAILURE" and r["node_id"] == target:
                exp_admin, exp_carrier = "0", "0"
            elif ft == "NODE_FAILURE" and r["peer_node_id"] == target:
                exp_admin, exp_carrier = "1", "0"
        if (admin, carrier) != (exp_admin, exp_carrier):
            bad.append(f"{r['window_id']}/{r['interface_name']}: {admin},{carrier} != {exp_admin},{exp_carrier}")
    return not bad, "; ".join(bad[:6])


def _check_tc(ft, sc, spec, tc_rows, wid_phase):
    links = topo.links_by_id(spec)
    bad = []
    for r in tc_rows:
        link = links[r["link_id"]]
        phase = wid_phase[r["window_id"]]
        rate, delay = _f(r["cfg_rate_mbps"]), _f(r["cfg_delay_ms"])
        loss, limit = _f(r["cfg_loss_pct"]), _f(r["cfg_limit_pkts"])
        exp = {"rate": float(link["bandwidth_mbps"]), "delay": float(link["delay_ms"]),
               "loss": None, "limit": 1000.0}
        if phase == "failed" and r["link_id"] == sc["target"]:
            p = sc["params"]
            if ft == "LINK_DELAY":
                exp["delay"] = float(link["delay_ms"]) + p["added_delay_ms"]
            elif ft == "LINK_LOSS":
                exp["loss"] = p["loss_pct"]
            elif ft == "LINK_BANDWIDTH":
                exp["rate"], exp["limit"] = p["bw_mbps"], float(p["queue_pkts"])
        got = {"rate": rate, "delay": delay, "loss": loss, "limit": limit}
        for key, value in exp.items():
            g = got[key]
            if value is None:
                if g not in (None, 0.0):
                    bad.append(f"{r['window_id']}/{r['interface_name']} {key}={g}")
            elif g is None or abs(g - value) > 1e-6 * max(1, value):
                bad.append(f"{r['window_id']}/{r['interface_name']} {key}={g} != {value}")
    return not bad, "; ".join(bad[:6])


def _traffic_windows(gt, rx_rows, deltas, windows):
    """Per-window traffic observations + cause annotation (audit-side, uses ground truth)."""
    offered = gt["traffic"]["offered_mbps"]
    segs = {s["segment_id"]: s for s in gt["traffic"]["segments"]}
    intervals = {}
    for r in rx_rows:
        intervals.setdefault(r["segment_id"], []).append({
            "abs_start": _f(r["abs_start_unix"]), "abs_end": _f(r["abs_end_unix"]),
            "bytes": _f(r["bytes"]) or 0, "packets": _f(r["packets"]) or 0,
            "lost_packets": _f(r["lost_packets"]) or 0})
    # Transitions near which per-window receiver allocation is alignment-sensitive.
    transitions = [gt.get("injected_at_unix"), gt.get("restored_at_unix")]
    for seg in segs.values():
        if seg.get("client_rc") not in (0, None):
            transitions.append(seg.get("client_exit_unix"))
    transitions = [t for t in transitions if t is not None]
    precise = all("first_data_unix" in s for s in segs.values()) if segs else False
    # Receiver intervals are 0.5 s long and allocated assuming a uniform rate, so any
    # transition within one interval of a window boundary smears that window's value.
    margin = 0.5 if precise else 0.65
    nic = {(r["window_id"]): r for r in deltas
           if r["node_id"] == gt["traffic"]["flow_target"]}
    src_nic = {(r["window_id"]): r for r in deltas
               if r["node_id"] == gt["traffic"]["flow_source"]}
    out = []
    for w in windows:
        row = {"window_id": w["window_id"], "phase": w["phase"], "offered_mbps": offered,
               "segment_id": None, "flow_active_s": 0.0, "receiver_mbps": None,
               "receiver_lost_packets": None, "receiver_packets": None, "receiver_coverage": 0.0,
               "dst_nic_rx_mbps": _f(nic[w["window_id"]]["rx_mbps"]) if w["window_id"] in nic else None,
               "src_nic_tx_mbps": _f(src_nic[w["window_id"]]["tx_mbps"]) if w["window_id"] in src_nic else None,
               "client_alive_at_window_end": None,
               "receiver_alignment_reliable": int(not any(
                   w["start_unix"] - margin < t < w["end_unix"] + margin for t in transitions))}
        if offered > 0 and w.get("flow"):
            sid = w["flow"]["segment_id"]
            seg = segs.get(sid, {})
            row["segment_id"] = sid
            row["client_alive_at_window_end"] = w["flow"]["client_alive_at_window_end"]
            launch = seg.get("client_launch_unix")
            if launch is not None:
                end = min(launch + seg["duration_s"], seg.get("client_exit_unix") or 1e18)
                row["flow_active_s"] = round(max(0.0, min(w["end_unix"], end) - max(w["start_unix"], launch)), 3)
            alloc = window_receiver_bytes(intervals.get(sid, []), w["start_unix"], w["end_unix"])
            row["receiver_mbps"] = alloc["mbps"]
            row["receiver_lost_packets"] = alloc["lost_packets"]
            row["receiver_packets"] = alloc["packets"]
            row["receiver_coverage"] = alloc["coverage_fraction"]
        out.append(row)
    return out


def _check_traffic(checks, gt, traffic, windows, rounds):
    offered = gt["traffic"]["offered_mbps"]
    relation = gt["traffic"]["flow_relation"]["relation"]
    segs = {s["segment_id"]: s for s in gt["traffic"]["segments"]}
    checks.add("traffic_segments_present", set(segs) == {"seg1", "seg2"}, str(sorted(segs)))
    # Background flow must OVERLAP every measurement window (except where aborted by fault).
    cover_bad = []
    for t in traffic:
        w = next(x for x in windows if x["window_id"] == t["window_id"])
        span = w["end_unix"] - w["start_unix"]
        aborted = t["client_alive_at_window_end"] is False and t["phase"] == "failed"
        if t["flow_active_s"] < 0.95 * span and not aborted:
            cover_bad.append(f"{t['window_id']} active {t['flow_active_s']}s/{span:.2f}s")
        if t["receiver_coverage"] < 0.95:
            cover_bad.append(f"{t['window_id']} receiver interval coverage {t['receiver_coverage']}")
    checks.add("traffic_overlaps_windows", not cover_bad, "; ".join(cover_bad))
    # Healthy and recovered windows: receiver-side rate close to offered, NIC consistent.
    bad = []
    skipped = []
    for t in traffic:
        if t["phase"] == "failed":
            continue
        r = t["receiver_mbps"]
        if not t["receiver_alignment_reliable"]:
            skipped.append(t["window_id"])      # NIC check below still applies
        elif r is None or abs(r - offered) / offered > RATE_TOL:
            bad.append(f"{t['window_id']} receiver {r}")
        n = t["dst_nic_rx_mbps"]
        if n is None or abs(n - offered * UDP_WIRE_FACTOR) / (offered * UDP_WIRE_FACTOR) > NIC_TOL:
            bad.append(f"{t['window_id']} dst NIC {n}")
    if len(skipped) > 2:
        bad.append(f"too many alignment-unreliable windows: {skipped}")
    checks.add("traffic_healthy_recovered_rates", not bad,
               "; ".join(bad) + (f" (receiver check skipped near transitions: {skipped})" if skipped else ""))
    # Failed windows: interpret absence of receiver traffic by its CAUSE.
    failed = [t for t in traffic if t["phase"] == "failed"]
    detail = []
    ok = True
    for t in failed:
        n = t["dst_nic_rx_mbps"] or 0.0
        if relation == "flow_disconnected":
            cause = "disconnection"
            ok &= n < 0.05 * offered            # nothing of the flow reaches the destination NIC
        elif relation in ("flow_not_on_fault_path",):
            cause = "unaffected"
            ok &= abs(n - offered * UDP_WIRE_FACTOR) / (offered * UDP_WIRE_FACTOR) <= NIC_TOL
        else:
            cause = relation                      # degradation: judged by observed_effects
        t["failed_window_cause"] = cause
        detail.append(f"{t['window_id']}:{cause} nic={n}")
    seg1 = segs.get("seg1", {})
    stderr = (seg1.get("client_stderr_tail") or "")
    endpoint = gt["traffic"]["flow_relation"].get("endpoint_isolated")
    if relation == "flow_disconnected" and endpoint == "source":
        ok &= seg1.get("client_rc") not in (0, None) and any(
            msg in stderr.lower() for msg in ("network is unreachable", "network is down"))
        detail.append(f"sender aborted rc={seg1.get('client_rc')} ({stderr.strip()})")
    checks.add("traffic_failed_phase_explained", ok, "; ".join(detail))


def observed_effects(gt, spec, icmp, deltas, tc_rows, traffic, wid_phase):
    """Measured effects by family + acceptance checks (configured vs observed)."""
    ft, sc = gt["scenario"]["fault_type"], gt["scenario"]
    impaired = {tuple(p) for p in gt["expected"]["impaired_pairs"]}

    def rtts(phase, pair_filter):
        vals = [_f(r["rtt_avg_ms"]) for r in icmp if wid_phase[r["window_id"]] == phase
                and pair_filter((r["source_node_id"], r["target_node_id"])) and r["rtt_avg_ms"] != ""]
        return vals

    def icmp_loss(phase, pair_filter):
        sent = recv = 0
        for r in icmp:
            if wid_phase[r["window_id"]] == phase and pair_filter((r["source_node_id"], r["target_node_id"])) \
                    and r["probe_status"] == "icmp_stats":
                sent += int(r["packets_sent"])
                recv += int(r["packets_received"])
        return sent, recv

    out = {"checks": []}
    imp = lambda p: p in impaired           # noqa: E731
    non = lambda p: p not in impaired       # noqa: E731
    for phase in ("healthy", "failed", "recovered"):
        a = rtts(phase, imp)
        b = rtts(phase, non)
        out[f"rtt_impaired_{phase}_ms"] = round(statistics.mean(a), 3) if a else None
        out[f"rtt_other_{phase}_ms"] = round(statistics.mean(b), 3) if b else None
        s, rcv = icmp_loss(phase, imp)
        out[f"icmp_impaired_{phase}"] = {"sent": s, "received": rcv,
                                         "loss_pct": round(100 * (s - rcv) / s, 2) if s else None}
        s, rcv = icmp_loss(phase, non)
        out[f"icmp_other_{phase}"] = {"sent": s, "received": rcv,
                                      "loss_pct": round(100 * (s - rcv) / s, 2) if s else None}
    failed_t = [t for t in traffic if t["phase"] == "failed"]
    rx = [t["receiver_mbps"] for t in failed_t if t["receiver_mbps"] is not None]
    out["receiver_failed_mean_mbps"] = round(statistics.mean(rx), 4) if rx else None
    # tc queue drops on the target link during FAILED windows (observed counters)
    # The HTB root's 'dropped' already aggregates its netem leaf's drops, so count the
    # leaf (netem) only, falling back to HTB when no netem qdisc is present.
    drops = 0
    if sc["target"] in topo.links_by_id(spec):
        before = {}
        for r in tc_rows:
            if wid_phase[r["window_id"]] == "failed" and r["link_id"] == sc["target"]:
                col = "netem_dropped" if r["netem_dropped"] != "" else "htb_dropped"
                if r[col] == "":
                    continue
                key = (r["window_id"], r["interface_name"])
                if r["sample_position"] == "before":
                    before[key] = int(r[col])
                elif key in before:
                    drops += int(r[col]) - before[key]
    out["target_qdisc_drops_failed"] = drops

    offered = gt["traffic"]["offered_mbps"]
    rel = gt["traffic"]["flow_relation"]["relation"]
    # Path delay per pair and phase: median over the phase's windows of the per-window MINIMUM
    # RTT. Tracks propagation + configured netem delay; robust to one transient window. Used for
    # delay and recovery checks (auditor d2186428 used mean RTT for recovery, d2186428 and 08ab341b for the delay checks; see
    # docs/small_stageB_rtt_recovery_investigation.md). Mean RTT stays reported, and stays the
    # statistic for congestion, where queueing delay IS the effect.
    pair_keys = sorted({(r["source_node_id"], r["target_node_id"]) for r in icmp})

    def med_min(phase, pair):
        vals = [_f(r["rtt_min_ms"]) for r in icmp if wid_phase[r["window_id"]] == phase
                and (r["source_node_id"], r["target_node_id"]) == pair and r.get("rtt_min_ms")]
        return statistics.median(vals) if vals else None

    def path_shift(phase_a, phase_b, pairs):
        out_s = {}
        for pair in pairs:
            a, b = med_min(phase_a, pair), med_min(phase_b, pair)
            out_s["~".join(pair)] = None if None in (a, b) else round(b - a, 3)
        return out_s

    if ft == "LINK_DELAY":
        added = sc["params"]["added_delay_ms"]
        exp = 2 * added
        imp_shift = path_shift("healthy", "failed", [p for p in pair_keys if p in impaired])
        oth_shift = path_shift("healthy", "failed", [p for p in pair_keys if p not in impaired])
        vals = [v for v in imp_shift.values() if v is not None]
        delta = round(statistics.mean(vals), 3) if vals and len(vals) == len(imp_shift) else None
        out["rtt_impaired_increase_ms"] = delta
        out["rtt_impaired_path_delay_shift_ms"] = imp_shift
        out["rtt_other_path_delay_shift_ms"] = oth_shift
        h, f = out["rtt_impaired_healthy_ms"], out["rtt_impaired_failed_ms"]
        out["rtt_impaired_mean_increase_ms"] = round(f - h, 3) if None not in (h, f) else None
        out["rtt_expected_increase_ms"] = exp
        out["checks"].append(("effect_delay_rtt_increase",
                              delta is not None and abs(delta - exp) <= max(2.0, 0.2 * exp),
                              f"path-delay increase +{delta} ms (mean-RTT +{out['rtt_impaired_mean_increase_ms']}) "
                              f"vs configured round-trip +{exp} ms"))
        worst = max((abs(v) for v in oth_shift.values() if v is not None), default=None)
        out["checks"].append(("effect_delay_isolated_to_impaired_pairs",
                              worst is not None and None not in oth_shift.values() and worst < 2.0,
                              f"other pairs max |path-delay shift| {worst} ms (mean RTT "
                              f"{out['rtt_other_healthy_ms']} -> {out['rtt_other_failed_ms']} ms)"))
    elif ft == "LINK_LOSS":
        loss = sc["params"]["loss_pct"]
        fi = out["icmp_impaired_failed"]
        out["checks"].append(("effect_loss_icmp_observed", (fi["loss_pct"] or 0) > 0,
                              f"impaired-pair ICMP loss {fi['loss_pct']}% (configured {loss}%/direction)"))
        oth = out["icmp_other_failed"]
        out["checks"].append(("effect_loss_isolated", (oth["loss_pct"] or 0) == 0,
                              f"other pairs ICMP loss {oth['loss_pct']}%"))
        if offered > 0 and rel == "flow_impaired":
            lost = sum(t["receiver_lost_packets"] or 0 for t in failed_t)
            pk = sum(t["receiver_packets"] or 0 for t in failed_t)
            pct = 100 * lost / (pk + lost) if pk + lost else None
            out["receiver_loss_failed_pct"] = round(pct, 3) if pct is not None else None
            out["checks"].append(("effect_loss_receiver_udp",
                                  pct is not None and 0.5 * loss <= pct <= 1.5 * loss,
                                  f"UDP receiver loss {out['receiver_loss_failed_pct']}% vs configured {loss}% (one traversal)"))
    elif ft == "LINK_BANDWIDTH":
        bw = sc["params"]["bw_mbps"]
        if offered == 0:
            sh = path_shift("healthy", "failed", [p for p in pair_keys if p in impaired])
            worst = max((abs(v) for v in sh.values() if v is not None), default=None)
            out["checks"].append(("effect_bw_idle_unobservable",
                                  worst is not None and worst < 2.0 and drops == 0,
                                  f"no load: impaired-pair max |path-delay shift| {worst} ms, drops={drops} "
                                  "(a capacity cap is not observable without traffic)"))
        if offered > 0 and rel == "flow_impaired":
            r = out["receiver_failed_mean_mbps"]
            lost = sum(t["receiver_lost_packets"] or 0 for t in failed_t)
            if offered > bw:
                out["congestion_evidence"] = {
                    "receiver_mbps": r, "receiver_lost_packets": round(lost, 1),
                    "qdisc_drops": drops,
                    "rtt_impaired_increase_ms": (round(out["rtt_impaired_failed_ms"] - out["rtt_impaired_healthy_ms"], 3)
                                                 if None not in (out["rtt_impaired_failed_ms"], out["rtt_impaired_healthy_ms"]) else None)}
                out["checks"].append(("effect_bw_throughput_capped",
                                      r is not None and r <= bw * 1.05,
                                      f"receiver {r} Mb/s <= cap {bw} Mb/s (offered {offered})"))
                out["checks"].append(("effect_congestion_drops_observed", drops > 0 and lost > 0,
                                      f"qdisc drops={drops}, receiver lost={lost:.0f}"))
            else:
                out["checks"].append(("effect_bw_not_binding",
                                      r is not None and abs(r - offered) / offered <= RATE_TOL and drops == 0,
                                      f"receiver {r} Mb/s at offered {offered} < cap {bw}; drops={drops}"))
    # Recovery of path-level delay (all families), same statistic, threshold 2 ms unchanged.
    shifts = path_shift("healthy", "recovered", pair_keys)
    out["rtt_recovered_path_delay_shift_ms"] = shifts
    worst = max((abs(v) for v in shifts.values() if v is not None), default=None)
    out["checks"].append(("rtt_recovered_path_delay",
                          worst is not None and None not in shifts.values() and worst < 2.0,
                          f"max |median(min RTT) recovered - healthy| over pairs = {worst} ms"))
    # Non-gating: mean RTT shift (sensitive to load-induced single-window transients).
    h, rcv = out["rtt_other_healthy_ms"], out["rtt_other_recovered_ms"]
    if None not in (h, rcv) and abs(rcv - h) >= 2.0:
        out.setdefault("warnings", []).append(
            f"mean RTT shift healthy->recovered {h} -> {rcv} ms (>= 2 ms); path-delay check governs "
            "recovery, transient jitter reported separately")
    out["rtt_transient_windows"] = _rtt_transients(icmp, wid_phase)
    return out


def _rtt_transients(icmp, wid_phase, excess_ms=10.0, min_pairs=2):
    """Windows where >= min_pairs pairs had an echo > excess_ms above the pair's own minimum."""
    # Baseline per (pair, phase): an intended impairment (e.g. +40 ms delay) shifts the whole
    # FAILED phase and must not be reported as a transient.
    base = {}
    for r in icmp:
        if r.get("rtt_min_ms"):
            k = (r["source_node_id"], r["target_node_id"], wid_phase[r["window_id"]])
            base[k] = min(base.get(k, 1e9), float(r["rtt_min_ms"]))
    out = []
    for wid in sorted(wid_phase):
        n = sum(1 for r in icmp if r["window_id"] == wid and r.get("rtt_max_ms")
                and float(r["rtt_max_ms"]) > base[(r["source_node_id"], r["target_node_id"],
                                                   wid_phase[wid])] + excess_ms)
        if n >= min_pairs:
            out.append({"window_id": wid, "phase": wid_phase[wid], "pairs": n})
    return out
