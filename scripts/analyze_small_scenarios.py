#!/usr/bin/env python3
"""Descriptive analysis of small_scenario_v2 campaigns -> Markdown report.

    python scripts/analyze_small_scenarios.py --campaigns data/campaigns/campaign_B_full_* \
        --title "Stage B ..." --out docs/small_stageB_report.md

Re-audits every experiment with the current auditor (raw data is read-only),
then reports inventory, connectivity signatures and their distinguishability,
traffic behaviour by cause, RTT by load, observed vs configured effects,
recovery and audit outcomes. Descriptive statistics only; no ML claims.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.audit import audit_experiment  # noqa: E402
from smartmall.paths import resolve  # noqa: E402


def fmt(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.3f}"
    return f"{statistics.mean(values):.3f} ± {statistics.stdev(values):.3f}"


def label(sc):
    p = sc["params"]
    extra = ",".join(f"{k}={v:g}" for k, v in p.items()) if p else ""
    return f"{sc['fault_type']}:{sc['target'] or '-'}" + (f"[{extra}]" if extra else "")


def load_runs(campaigns):
    runs = []
    for c in campaigns:
        manifest = json.loads((c / "manifest.json").read_text(encoding="utf-8"))
        for r in manifest["runs"]:
            entry = {"campaign_id": manifest["campaign_id"], **r}
            if r.get("raw_relative_path") and (resolve(r["raw_relative_path"]) / "incident.json").is_file():
                folder = resolve(r["raw_relative_path"])
                entry["gt"] = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
                entry["audit"] = audit_experiment(folder)
                with (folder / "icmp_probes.csv").open(newline="", encoding="utf-8") as h:
                    entry["icmp"] = list(csv.DictReader(h))
                with (folder / "port_window_deltas.csv").open(newline="", encoding="utf-8") as h:
                    entry["deltas"] = list(csv.DictReader(h))
            runs.append(entry)
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaigns", nargs="+", type=resolve, required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    runs = load_runs(args.campaigns)
    ok_runs = [r for r in runs if r.get("audit") and r["audit"]["passed"]]
    L = [f"# {args.title}", ""]
    L.append(f"- Campaigns: {', '.join('`' + c.name + '`' for c in args.campaigns)}")
    L.append(f"- Runs planned/executed: {len(runs)}; audited PASS: **{len(ok_runs)}**; "
             f"FAIL or not run: **{len(runs) - len(ok_runs)}**")
    L.append("- Protocol: small_scenario_v2 (3 phases x 3 windows x 4 s; 6 concurrent ICMP probes/window, "
             "3 echo requests each; 12 interfaces sampled before/after each window)")
    L.append("- Every experiment was re-audited with the current `src/smartmall/audit.py` for this report.")
    L.append("")

    # ---------------- inventory
    L += ["## 1. Inventory", "", "| Scenario | Load Mb/s | Runs | PASS |", "|---|---:|---:|---:|"]
    inv = defaultdict(lambda: [0, 0])
    for r in runs:
        sc = r["gt"]["scenario"] if r.get("gt") else {"fault_type": r["fault_type"], "target": r["target"],
                                                       "params": r["params"]}
        key = (label(sc), r["load_mbps"])
        inv[key][0] += 1
        inv[key][1] += int(bool(r.get("audit") and r["audit"]["passed"]))
    for (lab, load), (n, p) in sorted(inv.items()):
        L.append(f"| `{lab}` | {load} | {n} | {p} |")
    L.append("")

    # ---------------- audit failures
    bad = [r for r in runs if not (r.get("audit") and r["audit"]["passed"])]
    L += ["## 2. Audit failures", ""]
    if not bad:
        L.append("None. Every executed run passed every audit check.")
    for r in bad:
        fc = r["audit"]["failed_checks"] if r.get("audit") else ["run did not complete"]
        L.append(f"- `{r.get('experiment_id')}` {r['fault_type']} {r['target']} load={r['load_mbps']}: {fc}")
        if r.get("audit"):
            for c in r["audit"]["checks"]:
                if not c["pass"]:
                    L.append(f"  - {c['check']}: {c['detail'][:300]}")
    L.append("")

    # ---------------- signatures
    L += ["## 3. Connectivity signatures in FAILED windows (host-pair ICMP only)", "",
          "Signature = set of host pairs unreachable in a FAILED window. `route_unreachable` probes (source had "
          "no usable local route: 0 packets sent, loss undefined) are counted separately from ICMP loss.", "",
          "| Scenario | Runs | Distinct signatures across runs/windows | Unreachable pairs | ICMP-loss probes/run | Route-unreachable probes/run |",
          "|---|---:|---:|---|---:|---:|"]
    sig_by_scn = defaultdict(list)
    counts_by_scn = defaultdict(list)
    for r in ok_runs:
        wp = {w["window_id"]: w["phase"] for w in r["gt"]["windows"]}
        lab = label(r["gt"]["scenario"])
        loss = route = 0
        for wid in sorted(wp):
            if wp[wid] != "failed":
                continue
            rows = [x for x in r["icmp"] if x["window_id"] == wid]
            sig = tuple(sorted(f"{x['source_node_id']}~{x['target_node_id']}" for x in rows if x["reachable"] == "0"))
            sig_by_scn[lab].append(sig)
            loss += sum(1 for x in rows if x["probe_status"] == "icmp_stats" and x["reachable"] == "0")
            route += sum(1 for x in rows if x["probe_status"] == "route_unreachable")
        counts_by_scn[lab].append((loss, route))
    for lab in sorted(sig_by_scn):
        sigs = Counter(sig_by_scn[lab])
        top = sigs.most_common(1)[0][0]
        losses = sorted({c[0] for c in counts_by_scn[lab]})
        routes = sorted({c[1] for c in counts_by_scn[lab]})
        L.append(f"| `{lab}` | {len(counts_by_scn[lab])} | {len(sigs)} | {', '.join(top) or '(none)'} | "
                 f"{'/'.join(map(str, losses))} | {'/'.join(map(str, routes))} |")
    L.append("")
    # distinguishability
    groups = defaultdict(list)
    for lab, sigs in sig_by_scn.items():
        dominant = Counter(sigs).most_common(1)[0][0]
        groups[dominant].append(lab)
    L += ["### Distinguishability from host-pair connectivity alone", "",
          "| Signature (unreachable pairs) | Scenarios sharing it |", "|---|---|"]
    for sig, labs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        L.append(f"| {', '.join(sig) or '(no pair unreachable)'} | {', '.join('`' + x + '`' for x in sorted(labs))} |")
    L.append("")
    # interface-state patterns
    L += ["### Interface-state pattern in FAILED windows (admin_up/carrier per interface)", "",
          "Shows which interfaces deviate from (admin_up=1, carrier=1). These states are produced directly by "
          "the injection mechanism and therefore *reveal* admin-down faults (leakage for ML).", "",
          "| Scenario | Interfaces deviating (node:link admin/carrier) |", "|---|---|"]
    seen = {}
    for r in ok_runs:
        lab = label(r["gt"]["scenario"])
        if lab in seen:
            continue
        wp = {w["window_id"]: w["phase"] for w in r["gt"]["windows"]}
        wid = next(w for w, p in sorted(wp.items()) if p == "failed")
        dev = sorted(f"{d['node_id']}:{d['link_id']} {d['admin_up_after']}/{d['carrier_after']}"
                     for d in r["deltas"] if d["window_id"] == wid
                     and (d["admin_up_after"], d["carrier_after"]) != ("1", "1"))
        seen[lab] = dev
    for lab in sorted(seen):
        L.append(f"| `{lab}` | {'; '.join(seen[lab]) or 'none (all admin-up with carrier)'} |")
    L.append("")

    # ---------------- traffic
    loaded = [r for r in ok_runs if r["load_mbps"] > 0]
    if loaded:
        L += ["## 4. Background UDP flow PC-SHOP → SRV-LOCAL (receiver-side, per phase)", "",
              "Receiver Mb/s = iperf3 server intervals allocated to windows (alignment-unreliable windows "
              "adjacent to transitions excluded). Dst NIC = SRV-LOCAL ingress counter rate (includes headers).", "",
              "| Scenario | Load | Flow relation | Healthy rx Mb/s | FAILED rx Mb/s | FAILED dst NIC Mb/s | FAILED src NIC tx Mb/s | Sender aborted | Recovered rx Mb/s |",
              "|---|---:|---|---|---|---|---|---|---|"]
        agg = defaultdict(lambda: defaultdict(list))
        for r in loaded:
            key = (label(r["gt"]["scenario"]), r["load_mbps"])
            rel = r["gt"]["traffic"]["flow_relation"]["relation"]
            agg[key]["relation"].append(rel)
            seg1 = next((s for s in r["gt"]["traffic"]["segments"] if s["segment_id"] == "seg1"), {})
            agg[key]["aborted"].append(seg1.get("client_rc") not in (0, None))
            for t in r["audit"]["traffic_windows"]:
                if not t["receiver_alignment_reliable"]:
                    continue
                agg[key][f"rx_{t['phase']}"].append(t["receiver_mbps"])
                if t["phase"] == "failed":
                    agg[key]["dst"].append(t["dst_nic_rx_mbps"])
                    agg[key]["src"].append(t["src_nic_tx_mbps"])
        for (lab, load), a in sorted(agg.items()):
            ab = Counter(a["aborted"])
            L.append(f"| `{lab}` | {load} | {Counter(a['relation']).most_common(1)[0][0]} | "
                     f"{mean_sd(a['rx_healthy'])} | {mean_sd(a['rx_failed'])} | {mean_sd(a['dst'])} | "
                     f"{mean_sd(a['src'])} | {ab.get(True, 0)}/{len(a['aborted'])} | {mean_sd(a['rx_recovered'])} |")
        L.append("")

    # ---------------- RTT by load (healthy windows, all pairs reachable)
    L += ["## 5. RTT by background load (HEALTHY windows, all reachable probes)", "",
          "Every host pair shares at least one link with the flow path in this tree, so the exact flow "
          "pair (PC-SHOP~SRV-LOCAL, same 4 links as the UDP flow) is reported separately.", "",
          "| Load Mb/s | Probes | Mean RTT ms | Median | P95 | Max | PC-SHOP~SRV-LOCAL mean RTT ms |",
          "|---:|---:|---:|---:|---:|---:|---:|"]
    by_load = defaultdict(list)
    by_load_path = defaultdict(list)
    for r in ok_runs:
        wp = {w["window_id"]: w["phase"] for w in r["gt"]["windows"]}
        for x in r["icmp"]:
            if wp[x["window_id"]] == "healthy" and x["rtt_avg_ms"]:
                v = float(x["rtt_avg_ms"])
                by_load[r["load_mbps"]].append(v)
                if {x["source_node_id"], x["target_node_id"]} == {"PC-SHOP", "SRV-LOCAL"}:
                    by_load_path[r["load_mbps"]].append(v)
    for load in sorted(by_load):
        v = sorted(by_load[load])
        p95 = v[int(0.95 * (len(v) - 1))]
        L.append(f"| {load} | {len(v)} | {statistics.mean(v):.3f} | {statistics.median(v):.3f} | {p95:.3f} | "
                 f"{max(v):.3f} | {fmt(statistics.mean(by_load_path[load]) if by_load_path[load] else None)} |")
    L.append("")

    # ---------------- effects
    eff_rows = []
    for r in ok_runs + [r for r in runs if r.get("audit") and not r["audit"]["passed"]]:
        for c in r["audit"]["checks"]:
            if c["check"].startswith("effect_"):
                eff_rows.append((label(r["gt"]["scenario"]), r["load_mbps"], r.get("repetition"),
                                 c["check"], c["pass"], c["detail"]))
    if eff_rows:
        L += ["## 6. Configured vs observed effects", "",
              "| Scenario | Load | Rep | Check | Result | Observation |", "|---|---:|---:|---|---|---|"]
        for row in sorted(eff_rows):
            L.append(f"| `{row[0]}` | {row[1]} | {row[2]} | {row[3]} | {'PASS' if row[4] else 'FAIL'} | {row[5]} |")
        L.append("")

    # ---------------- recovery
    rec = [r["gt"]["recovery"]["seconds_after_restore"] for r in ok_runs if r["gt"].get("recovery")]
    if rec:
        L += ["## 7. Recovery", "",
              f"- All PASS runs regained full 6-pair reachability; first full-reachability check at "
              f"{min(rec):.2f}–{max(rec):.2f} s after restoration (check granularity ≈1 s, so this is an upper bound).",
              f"- tc configuration restored to baseline and all interfaces admin-up with carrier in every PASS run; "
              f"no OVS bridges left after Mininet stop.", ""]
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(ok_runs)}/{len(runs)} PASS)")


if __name__ == "__main__":
    main()
