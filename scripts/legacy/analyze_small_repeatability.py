#!/usr/bin/env python3
"""SmartMall SMALL - evaluate repeatability across completed link-failure campaigns.

Run from the SmartMall project root (Windows Conda, stdlib only):
    python scripts/legacy/analyze_small_repeatability.py --campaigns \
        data/campaigns/campaign_20261125T134916Z_249a1c \
        data/campaigns/campaign_20261125T140815Z_f24de3

Reads original experiments without modifying them. Writes:
    docs/history/small_v1/small_repeatability_report.md
    docs/history/small_v1/small_repeatability_experiments.csv

This is descriptive data-quality analysis, NOT ML model evaluation.
"""
import argparse
import csv
import itertools
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHASES = ("healthy", "failed", "recovered")
COUNTERS = ("rx_bytes", "rx_packets", "tx_bytes", "tx_packets")


def read_json(path):
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value):
    return float(value) if value not in ("", None) else None


def iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def simple_stats(values):
    if not values:
        return (None, None)
    return (statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0)


def fmt(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def missing_host_pairs_after_link_fault(topology, link_id):
    vertices = {node["id"] for node in topology["nodes"]}
    adj = {v: set() for v in vertices}
    for link in topology["links"]:
        if link["id"] == link_id:
            continue
        a, b = link["source"], link["target"]
        adj[a].add(b)
        adj[b].add(a)
    hosts = sorted(n["id"] for n in topology["nodes"] if n["type"] == "host")
    missing = set()
    for src, dst in itertools.combinations(hosts, 2):
        visited = {src}
        pending = [src]
        while pending:
            for nxt in adj[pending.pop()]:
                if nxt not in visited:
                    visited.add(nxt)
                    pending.append(nxt)
        if dst not in visited:
            missing.add((src, dst))
    return missing


def analyze_experiment(exp, campaign, baseline_topology, errors, warnings):
    experiment_id = exp["experiment_id"]
    prefix = f"{campaign}/{experiment_id}"
    folder = ROOT / exp["raw_relative_path"]
    for name in ("topology.json", "incident.json", "telemetry.csv", "port_telemetry.csv"):
        if not (folder / name).is_file():
            errors.append(f"Missing {folder / name}")
            return None
    topology = read_json(folder / "topology.json")
    incident = read_json(folder / "incident.json")
    probes = read_csv(folder / "telemetry.csv")
    ports = read_csv(folder / "port_telemetry.csv")
    if topology != baseline_topology:
        errors.append(f"{prefix}: inconsistent topology")
    link = exp["fault_link_id"]
    if incident["ground_truth"]["fault_link_id"] != link:
        errors.append(f"{prefix}: mismatched ground truth")
    if incident["experiment_id"] != experiment_id or incident["status"] != "completed":
        errors.append(f"{prefix}: incident ID/status mismatch")
    if len(probes) != exp["icmp_rows"] or len(ports) != exp["port_rows"]:
        errors.append(f"{prefix}: record counts differ from campaign manifest")
    windows = {s["snapshot_id"]: s["phase"] for s in incident["ground_truth"]["snapshots"]}
    cnt = Counter(windows.values())
    if any(cnt[p] != incident["protocol"]["rounds_per_phase"] for p in PHASES):
        errors.append(f"{prefix}: incorrect number of windows by phase")
    expected_pairs = set(itertools.combinations(
        sorted(n["id"] for n in topology["nodes"] if n["type"] == "host"), 2
    ))
    expected_signature = missing_host_pairs_after_link_fault(topology, link)
    by_window = defaultdict(list)
    for p in probes:
        by_window[p["snapshot_id"]].append(p)
    failed_signatures = []
    failed_categories = []
    rtt = defaultdict(list)
    disrupted = defaultdict(int)
    loss = defaultdict(int)
    unroutable = defaultdict(int)

    for window, phase in windows.items():
        rows = by_window.get(window, [])
        if len(rows) != len(expected_pairs):
            errors.append(f"{prefix}/{window}: incorrect number of probes")
        got_pairs = [tuple(sorted((p["source_node_id"], p["target_node_id"]))) for p in rows]
        if set(got_pairs) != expected_pairs or len(set(got_pairs)) != len(rows):
            errors.append(f"{prefix}/{window}: probe-pair mismatch or duplicate")
        missed = set()
        for p in rows:
            if p.get("experiment_id") != experiment_id:
                errors.append(f"{prefix}/{window}: wrong experiment ID on ICMP row")
            status = p.get("probe_status", "icmp_stats")
            sent = int(p["packets_sent"])
            received = int(p["packets_received"])
            ping_loss = as_float(p.get("loss_pct"))
            reachable = p.get("reachable") == "1"
            if status == "route_unreachable":
                if sent != 0 or received != 0 or ping_loss is not None or reachable:
                    errors.append(f"{prefix}/{window}: route_unreachable wrongly encoded")
                unroutable[phase] += 1
            elif status == "icmp_stats":
                if sent < 1 or received > sent or ping_loss is None:
                    errors.append(f"{prefix}/{window}: invalid ICMP stats")
                if ping_loss is not None and ping_loss > 0:
                    loss[phase] += 1
            else:
                errors.append(f"{prefix}/{window}: unknown probe_status={status}")
            if not reachable:
                disrupted[phase] += 1
                missed.add(tuple(sorted((p["source_node_id"], p["target_node_id"]))))
            else:
                avg_rtt = as_float(p.get("rtt_avg_ms"))
                if avg_rtt is not None:
                    rtt[phase].append(avg_rtt)
        if phase == "failed":
            failed_signatures.append(frozenset(missed))
            failed_categories.append((sum(p.get("probe_status") == "route_unreachable" for p in rows),
                                      sum((as_float(p.get("loss_pct")) or 0) > 0 for p in rows)))
            if missed != expected_signature:
                errors.append(f"{prefix}/{window}: observed disconnected pairs differ from topology")
        elif missed:
            errors.append(f"{prefix}/{window}: healthy/recovered has disconnected pairs")

    if not failed_signatures or len(set(failed_signatures)) != 1:
        errors.append(f"{prefix}: unstable or missing failed signatures")
    if len(set(failed_categories)) != 1:
        errors.append(f"{prefix}: changes in route/loss category across failed windows")
    
    link_map = {v["id"]: v for v in topology["links"]}
    port_index = defaultdict(list)
    for p in ports:
        key = (p["snapshot_id"], p["sample_position"], p["link_id"], p["node_id"])
        port_index[key].append(p)
        if p.get("experiment_id") != experiment_id:
            errors.append(f"{prefix}: wrong experiment ID in port rows")
    byte_rate_by_phase = defaultdict(list)
    for window, phase in windows.items():
        for link_id, edge in link_map.items():
            # Count a single endpoint per link (source in topology.json), avoiding mirrored traffic double counting.
            src = edge["source"]
            before_rows = port_index.get((window, "before", link_id, src), [])
            after_rows = port_index.get((window, "after", link_id, src), [])
            target = "0" if phase == "failed" and link_id == link else "1"
            if len(before_rows) != 1 or len(after_rows) != 1:
                errors.append(f"{prefix}/{window}/{link_id}: missing/duplicate port samples at source")
                continue
            before, after = before_rows[0], after_rows[0]
            for endpoint in (edge["source"], edge["target"]):
                for position in ("before", "after"):
                    rows = port_index.get((window, position, link_id, endpoint), [])
                    if len(rows) != 1 or rows[0]["admin_up"] != target:
                        errors.append(f"{prefix}/{window}/{link_id}/{endpoint}: unexpected port state")
            for name in COUNTERS:
                b, a = int(before[name]), int(after[name])
                if a < b:
                    errors.append(f"{prefix}/{window}/{link_id}: {name} counter decreased")
            t0 = iso(before["sample_time_utc"])
            t1 = iso(after["sample_time_utc"])
            duration = (t1 - t0).total_seconds()
            if duration <= 0:
                errors.append(f"{prefix}/{window}/{link_id}: nonpositive sampling duration")
            else:
                delta_bytes = ((int(after["rx_bytes"]) - int(before["rx_bytes"]))
                               + (int(after["tx_bytes"]) - int(before["tx_bytes"])))
                byte_rate_by_phase[phase].append(delta_bytes * 8 / duration / 1_000_000)
    rtt_h, _ = simple_stats(rtt["healthy"])
    rtt_r, _ = simple_stats(rtt["recovered"])
    return {
        "campaign_id": campaign,
        "experiment_id": experiment_id,
        "link": link,
        "failed_disrupted": disrupted["failed"],
        "failed_loss": loss["failed"],
        "failed_route_unreachable": unroutable["failed"],
        "healthy_disrupted": disrupted["healthy"],
        "recovered_disrupted": disrupted["recovered"],
        "healthy_rtt_mean_ms": rtt_h,
        "recovered_rtt_mean_ms": rtt_r,
        "mean_link_endpoint_mbps_healthy": simple_stats(byte_rate_by_phase["healthy"])[0],
        "mean_link_endpoint_mbps_failed": simple_stats(byte_rate_by_phase["failed"])[0],
        "mean_link_endpoint_mbps_recovered": simple_stats(byte_rate_by_phase["recovered"])[0],
        "signature": tuple(sorted(failed_signatures[0])) if failed_signatures else (),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaigns", required=True, nargs="+", type=Path,
                        help="One or more completed campaign directories")
    args = parser.parse_args()
    errors, warnings = [], []
    all_rows = []
    seen_ids = set()
    topology = None
    sha = None
    for campaign in args.campaigns:
        folder = campaign.resolve()
        manifest = read_json(folder / "manifest.json")
        cid = manifest["campaign_id"]
        if manifest["status"] != "completed":
            errors.append(f"Campaign {cid} is not completed")
            continue
        if manifest.get("topology_id") != "small_v1":
            errors.append(f"{cid} is not small_v1")
            continue
        current_sha = manifest.get("source_sha256", {})
        if sha is None:
            sha = current_sha
        elif sha != current_sha:
            errors.append("Source checksums differ across campaigns: protocol/software confounding")
        for exp in manifest["experiments"]:
            if exp.get("status") != "PASS":
                errors.append(f"{cid}/{exp.get('experiment_id')}: not PASS")
                continue
            eid = exp["experiment_id"]
            if eid in seen_ids:
                errors.append(f"Repeated experiment ID: {eid}")
                continue
            seen_ids.add(eid)
            exp_folder = ROOT / exp["raw_relative_path"]
            if not (exp_folder / "topology.json").exists():
                errors.append(f"Missing topology for {eid}")
                continue
            this_topology = read_json(exp_folder / "topology.json")
            if topology is None:
                topology = this_topology
            row = analyze_experiment(exp, cid, topology, errors, warnings)
            if row:
                all_rows.append(row)
    if not all_rows:
        print("No valid experiments to analyze", file=sys.stderr)
        raise SystemExit(2)
    by_link = defaultdict(list)
    for row in all_rows:
        by_link[row["link"]].append(row)
    lines = [
        "# SmartMall SMALL — Repeatability analysis", "",
        f"- Campaigns evaluated: {len(args.campaigns)}",
        f"- Experiments analyzed: {len(all_rows)}",
        f"- Telemetry volume (expected from manifests): {len(all_rows)*36} ICMP, {len(all_rows)*144} port rows",
        "- Scope: administratively injected LINK_FAILURE on SMALL; descriptive repeatability, not GNN results", "",
        "## Fault signatures across independent experiments", "",
        "| Link | Experiments | Disruptions per experiment | ICMP-loss probes per experiment | Local-route failures per experiment | Identical disconnected-pair signatures |",
        "|---|---:|---|---|---|---|",
    ]
    for link in sorted(by_link):
        rows = by_link[link]
        d = sorted(set(r["failed_disrupted"] for r in rows))
        l = sorted(set(r["failed_loss"] for r in rows))
        u = sorted(set(r["failed_route_unreachable"] for r in rows))
        consistent = len({r["signature"] for r in rows}) == 1
        if not consistent:
            errors.append(f"{link}: fault signature differs across independent experiments")
        lines.append(f"| {link} | {len(rows)} | {', '.join(map(str,d))} | {', '.join(map(str,l))} | {', '.join(map(str,u))} | {'YES' if consistent else 'NO'} |")
    lines += ["", "## RTT descriptive statistics (reachable probes)", "",
              "| Link fault | Healthy mean RTT ms (across experiment means) | Recovered mean RTT ms (across experiment means) |",
              "|---|---|---|"]
    for link in sorted(by_link):
        rows = by_link[link]
        mh, sh = simple_stats([r["healthy_rtt_mean_ms"] for r in rows if r["healthy_rtt_mean_ms"] is not None])
        mr, sr = simple_stats([r["recovered_rtt_mean_ms"] for r in rows if r["recovered_rtt_mean_ms"] is not None])
        lines.append(f"| {link} | {fmt(mh)} ± {fmt(sh)} | {fmt(mr)} ± {fmt(sr)} |")
    lines += [
        "", "## Traffic-counter description", "",
        "The accompanying experiment CSV includes mean per-link throughput proxies computed from within-window delta(rx_bytes + tx_bytes) / duration at ONE endpoint of each link.",
        "They reflect short sequential ICMP probes, not controlled throughput or externally imposed traffic load.",
        "Do not infer bandwidth performance, quality of service, or production-like load from these values.",
        "", "## Quality result", "", f"**{'PASS' if not errors else 'CHECK REQUIRED'}**", "",
    ]
    if errors:
        lines += ["### Errors", ""] + [f"- {error}" for error in errors[:60]] + [""]
    if warnings:
        lines += ["### Warnings", ""] + [f"- {warning}" for warning in warnings[:40]] + [""]
    lines += [
        "## Scientific limits", "",
        "- All repetitions share the same topology, source code, fault mechanism, probe order and light ICMP traffic. Reproducibility here does not imply generalization.",
        "- admin_up is a direct consequence of the injected administrative link-down; do not report that feature as learned fault localization.",
        "- Phase and fault-link labels are used for auditing only; do not leak them into ML features.",
        "- Probe windows are sequential and counters are cumulative; only per-window differences are meaningful.",
        "- For future ML, split by independent experiments/campaigns, not by probe rows or snapshots.",
        "- To estimate realistic latency variability, repeat under distinct background traffic and larger probe samples.", "",
    ]
    docs = ROOT / "docs" / "history" / "small_v1"
    docs.mkdir(exist_ok=True, parents=True)
    report = docs / "small_repeatability_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    detail = docs / "small_repeatability_experiments.csv"
    cols = ["campaign_id", "experiment_id", "link", "failed_disrupted", "failed_loss", "failed_route_unreachable",
            "healthy_disrupted", "recovered_disrupted", "healthy_rtt_mean_ms", "recovered_rtt_mean_ms",
            "mean_link_endpoint_mbps_healthy", "mean_link_endpoint_mbps_failed", "mean_link_endpoint_mbps_recovered"]
    with detail.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for row in sorted(all_rows, key=lambda x: (x["link"], x["experiment_id"])):
            writer.writerow({c: fmt(row[c], 5) if isinstance(row[c], float) else row[c] for c in cols})
    print("\n".join(lines))
    print(f"\nReport: {report}")
    print(f"Experiment table: {detail}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
