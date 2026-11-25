#!/usr/bin/env python3
"""Build + quality-audit the consolidated SMALL dataset (Stage E). Offline, read-only on raw data.

    python scripts/build_small_dataset.py --v2-campaigns data/campaigns/campaign_B_full_* ... \
        --v1-campaigns data/campaigns/campaign_20261125T134916Z_249a1c data/campaigns/campaign_20261125T140815Z_f24de3 \
        --out data/processed/small_dataset_v2 --report docs/SMALL_DATASET_CARD.md

Only experiments whose audit PASSES enter the feature/label tables; every
excluded run is listed with its reason in build_manifest.json.
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall import dataset as D  # noqa: E402
from smartmall import topology as topo  # noqa: E402
from smartmall.paths import resolve  # noqa: E402
from smartmall.audit import LABEL_COLUMNS, audit_experiment  # noqa: E402


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect(args):
    exps, pair, intf, flow, labels, excluded = [], [], [], [], [], []
    for c in args.v2_campaigns:
        m = json.loads((c / "manifest.json").read_text(encoding="utf-8"))
        for r in m["runs"]:
            path = resolve(r["raw_relative_path"]) if r.get("raw_relative_path") else None
            if path is None or not (path / "incident.json").is_file():
                excluded.append({"campaign_id": m["campaign_id"], "experiment_id": r.get("experiment_id"),
                                 "reason": "run did not produce an experiment folder"})
                continue
            a = audit_experiment(path)
            if not a["passed"]:
                excluded.append({"campaign_id": m["campaign_id"], "experiment_id": a["experiment_id"],
                                 "reason": f"audit FAIL: {a['failed_checks']}"})
                continue
            e, p, i, f, lab = D.convert_v2(path, m["campaign_id"], a)
            exps.append(e); pair += p; intf += i; flow += f; labels += lab
    for c in args.v1_campaigns:
        m = json.loads((c / "manifest.json").read_text(encoding="utf-8"))
        reps = Counter()
        for r in m["experiments"]:
            if r["status"] != "PASS":
                excluded.append({"campaign_id": m["campaign_id"], "experiment_id": r["experiment_id"],
                                 "reason": f"v1 campaign status {r['status']}"})
                continue
            reps[r["fault_link_id"]] += 1
            e, p, i, f, lab = D.convert_v1(resolve(r["raw_relative_path"]), m["campaign_id"],
                                           f"{m['campaign_id'][-6:]}#{reps[r['fault_link_id']]}")
            exps.append(e); pair += p; intf += i; flow += f; labels += lab
    return exps, pair, intf, flow, labels, excluded


def quality(spec, exps, pair, intf, flow, labels):
    q = {"checks": [], "stats": {}}

    def check(name, ok, detail=""):
        q["checks"].append({"check": name, "pass": bool(ok), "detail": detail})

    links = topo.links_by_id(spec)
    nodes = set(topo.node_types(spec))
    ids = [e["experiment_id"] for e in exps]
    check("unique_experiment_ids", len(ids) == len(set(ids)), str([k for k, v in Counter(ids).items() if v > 1]))
    for name, rows in (("pair_window", pair), ("interface_window", intf), ("flow_window", flow)):
        cols = set(rows[0]) if rows else set()
        check(f"no_label_columns:{name}", not cols & (LABEL_COLUMNS | set(D.LABEL_FIELDS[2:])),
              str(sorted(cols & (LABEL_COLUMNS | set(D.LABEL_FIELDS[2:])))))
    keys = [(r["experiment_id"], r["window_id"]) for r in labels]
    check("unique_label_keys", len(keys) == len(set(keys)))
    kset = set(keys)
    per = lambda rows: Counter((r["experiment_id"], r["window_id"]) for r in rows)  # noqa: E731
    pc, ic, fc = per(pair), per(intf), per(flow)
    check("pair_rows_per_window_6", all(pc[k] == 6 for k in kset) and set(pc) == kset)
    check("interface_rows_per_window_12", all(ic[k] == 12 for k in kset) and set(ic) == kset)
    check("flow_rows_per_window_1", all(fc[k] == 1 for k in kset) and set(fc) == kset)
    check("experiments_referenced_consistently",
          {k[0] for k in kset} == set(ids), "label experiments == experiment table")
    # topology mapping
    bad = [r for r in intf if r["link_id"] not in links
           or {r["node_id"], r["peer_node_id"]} != {links[r["link_id"]]["source"], links[r["link_id"]]["target"]}]
    check("interface_topology_mapping", not bad, f"{len(bad)} rows")
    hosts = set(topo.hosts(spec))
    check("pair_nodes_are_hosts", all(r["source_node_id"] in hosts and r["target_node_id"] in hosts for r in pair))
    # ICMP semantics
    sem_bad = 0
    for r in pair:
        if r["probe_status"] == "route_unreachable":
            sem_bad += not (str(r["packets_sent"]) == "0" and r["loss_pct"] in ("", None) and str(r["reachable"]) == "0")
        else:
            lp = _f(r["loss_pct"])
            sem_bad += lp is None or not 0 <= lp <= 100
            if str(r["reachable"]) == "1":
                sem_bad += (_f(r["rtt_avg_ms"]) or 0) <= 0
    check("icmp_route_unreachable_vs_loss_semantics", sem_bad == 0, f"{sem_bad} violations")
    # counters
    resets = sum(int(r["counter_reset"] or 0) for r in intf)
    neg = sum(1 for r in intf for c in ("rx_mbps", "tx_mbps", "rx_pps", "tx_pps", "qdisc_drops_delta")
              if _f(r[c]) is not None and _f(r[c]) < 0)
    check("no_counter_resets", resets == 0, f"{resets}")
    check("no_negative_rates_or_deltas", neg == 0, f"{neg}")
    # timing
    by_exp = defaultdict(list)
    for r in labels:
        by_exp[r["experiment_id"]].append(r)
    t_bad = 0
    durs = defaultdict(list)
    proto = {e["experiment_id"]: e["protocol_version"] for e in exps}
    for e, rows in by_exp.items():
        rows.sort(key=lambda r: r["window_start_unix"])
        for i, r in enumerate(rows):
            d = r["window_end_unix"] - r["window_start_unix"]
            durs[proto[e]].append(d)
            t_bad += d <= 0
            if i and rows[i - 1]["window_end_unix"] > r["window_start_unix"]:
                t_bad += 1
    check("window_timestamps_monotonic_non_overlapping", t_bad == 0, f"{t_bad}")
    q["stats"]["window_duration_s"] = {p: {"n": len(v), "min": round(min(v), 3), "mean": round(statistics.mean(v), 3),
                                           "max": round(max(v), 3)} for p, v in durs.items()}
    # labels
    l_bad = 0
    for r in labels:
        if r["phase"] != "failed":
            l_bad += r["fault_active"] != 0 or r["fault_family"] != "NONE"
        if r["fault_active"]:
            l_bad += r["fault_target"] not in set(links) | nodes
    check("labels_consistent_with_phase_and_topology", l_bad == 0, f"{l_bad}")
    # flow semantics: receiver-only metrics, offered is a condition
    check("flow_table_receiver_metrics_only",
          not any(k.startswith("sender_mbps") or k == "sent_mbps" for k in (flow[0] if flow else {})))
    # missing values
    miss = {}
    for name, rows in (("pair_window", pair), ("interface_window", intf), ("flow_window", flow)):
        for col in rows[0]:
            for pv in sorted({proto[r["experiment_id"]] for r in rows}):
                sub = [r for r in rows if proto[r["experiment_id"]] == pv]
                n = sum(1 for r in sub if r[col] in ("", None))
                if n:
                    miss[f"{name}.{col}[{pv}]"] = round(n / len(sub), 4)
    q["stats"]["missing_fraction"] = miss
    # splits
    folds = defaultdict(set)
    for e in exps:
        folds[e["experiment_id"]].add(e["split_fold"])
    check("each_experiment_in_exactly_one_fold", all(len(v) == 1 for v in folds.values()))
    strata = defaultdict(set)
    for e in exps:
        strata[(e["protocol_version"], e["scenario_key"])].add(e["split_fold"])
    incomplete = {f"{k[0]}:{k[1]}": sorted(v) for k, v in strata.items() if len(v) < 3}
    check("strata_cover_all_folds", not incomplete, json.dumps(incomplete)[:400])
    # class balance
    q["stats"]["windows_by_family"] = dict(Counter(r["fault_family"] for r in labels))
    q["stats"]["windows_by_target_active"] = dict(Counter(r["fault_target"] for r in labels if r["fault_active"]))
    q["stats"]["experiments_by_family_protocol"] = dict(Counter(f"{e['fault_family']}[{e['protocol_version']}]" for e in exps))
    q["stats"]["experiments_by_fold"] = dict(Counter(e["split_fold"] for e in exps))
    # leakage quantification
    lab = {(r["experiment_id"], r["window_id"]): r for r in labels}
    any_down = defaultdict(int)
    for r in intf:
        if str(r["admin_up"]) == "0" or str(r["carrier"]) == "0":
            any_down[(r["experiment_id"], r["window_id"])] = 1
    tp = sum(1 for k, r in lab.items() if any_down[k] and r["fault_active"])
    fp = sum(1 for k, r in lab.items() if any_down[k] and not r["fault_active"])
    adm = [k for k, r in lab.items() if r["fault_active"] and r["fault_family"] in ("LINK_FAILURE", "NODE_FAILURE")]
    q["stats"]["leakage_interface_state"] = {
        "rule": "fault_active := any interface admin_up==0 or carrier==0",
        "true_positives": tp, "false_positives": fp,
        "admin_mechanism_fault_windows": len(adm),
        "recall_on_admin_mechanism_faults": round(sum(any_down[k] for k in adm) / len(adm), 4) if adm else None,
        "interpretation": "Near-perfect detection from interface state alone = mechanism leakage, not learned diagnosis"}
    # localisation leakage: is the target the unique admin-down/carrier-down component?
    loc_hits = loc_n = 0
    for k in adm:
        r = lab[k]
        down = {(x["link_id"], x["node_id"]) for x in intf if (x["experiment_id"], x["window_id"]) == k
                and (str(x["admin_up"]) == "0" or str(x["carrier"]) == "0")}
        if r["target_kind"] == "link":
            guess = {l for l, _ in down}
            loc_hits += guess == {r["fault_target"]}
        else:
            admin_nodes = {x["node_id"] for x in intf if (x["experiment_id"], x["window_id"]) == k
                           and str(x["admin_up"]) == "0"}
            loc_hits += admin_nodes == {r["fault_target"]}
        loc_n += 1
    q["stats"]["leakage_localization_from_admin_state"] = {
        "windows": loc_n, "exact_target_recovered": loc_hits,
        "rule": "link faults: set of links with a down interface; node faults: nodes with admin-down interfaces"}
    order = Counter((r["window_id"][-2:], r["phase"]) for r in labels if proto[r["experiment_id"]] == "small_scenario_v2")
    q["stats"]["leakage_window_id_vs_phase_v2"] = {f"{w}->{p}": n for (w, p), n in sorted(order.items())}
    q["passed"] = all(c["pass"] for c in q["checks"])
    return q


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-campaigns", nargs="*", type=resolve, default=[])
    ap.add_argument("--v1-campaigns", nargs="*", type=resolve, default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()
    spec = topo.load_spec(ROOT / "topologies" / "small.json")
    exps, pair, intf, flow, labels, excluded = collect(args)
    D.assign_folds(exps)
    args.out.mkdir(parents=True, exist_ok=True)
    D.write_csv(args.out / "experiments.csv", D.EXP_FIELDS, sorted(exps, key=lambda e: e["experiment_id"]))
    D.write_csv(args.out / "pair_window.csv", D.PAIR_FIELDS, pair)
    D.write_csv(args.out / "interface_window.csv", D.INTF_FIELDS, intf)
    D.write_csv(args.out / "flow_window.csv", D.FLOW_FIELDS, flow)
    D.write_csv(args.out / "labels_window.csv", D.LABEL_FIELDS, labels)
    D.write_csv(args.out / "feature_dictionary.csv",
                ["table", "column", "unit", "leakage_class", "model_input", "description"],
                [dict(zip(["table", "column", "unit", "leakage_class", "model_input", "description"], d))
                 for d in D.FEATURE_DICTIONARY] +
                [{"table": "labels_window", "column": c, "unit": "", "leakage_class": "identifier",
                  "model_input": "no", "description": "Join key"} for c in D.LABEL_FIELDS[:2]] +
                [{"table": "labels_window", "column": c, "unit": "", "leakage_class": "ground_truth",
                  "model_input": "no", "description": "Ground truth / label (never a feature)"} for c in D.LABEL_FIELDS[2:]] +
                [{"table": "experiments", "column": c, "unit": "", "leakage_class":
                  "identifier" if c in ("experiment_id", "campaign_id", "raw_relative_path", "run_seed") else
                  "split" if c == "split_fold" else "ground_truth" if c in ("scenario_key", "fault_family", "fault_target")
                  else "condition", "model_input": "no", "description": "Experiment-level metadata"} for c in D.EXP_FIELDS])
    (args.out / "graph_schema.json").write_text(json.dumps(D.graph_schema(spec), indent=2) + "\n", encoding="utf-8")
    q = quality(spec, exps, pair, intf, flow, labels)
    (args.out / "quality_report.json").write_text(json.dumps(q, indent=2) + "\n", encoding="utf-8")
    manifest = {"built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "v2_campaigns": [c.name for c in args.v2_campaigns], "v1_campaigns": [c.name for c in args.v1_campaigns],
                "experiments": len(exps), "windows": len(labels), "excluded": excluded,
                "source_sha256": {p: D.sha256(ROOT / p) for p in (
                    "scripts/build_small_dataset.py", "src/smartmall/dataset.py", "src/smartmall/audit.py",
                    "src/smartmall/graph_loader.py", "topologies/small.json")},
                "quality_passed": q["passed"]}
    (args.out / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Dataset: {len(exps)} experiments, {len(labels)} windows, {len(pair)} pair rows, "
          f"{len(intf)} interface rows; excluded {len(excluded)}; quality {'PASS' if q['passed'] else 'FAIL'}")
    for c in q["checks"]:
        if not c["pass"]:
            print(f"  FAIL {c['check']}: {c['detail']}")
    if args.report:
        write_card(args, exps, labels, q, excluded)
    sys.exit(0 if q["passed"] else 1)


def write_card(args, exps, labels, q, excluded):
    s = q["stats"]
    L = ["# SMALL dataset card (`" + args.out.name + "`)", "",
         f"Generated by `scripts/build_small_dataset.py` from raw experiments (read-only). "
         f"Location: `{args.out.as_posix()}`.", "",
         "## Contents", "",
         f"- Experiments: **{len(exps)}** ({', '.join(f'{k}: {v}' for k, v in sorted(s['experiments_by_family_protocol'].items()))})",
         f"- Windows (graph snapshots): **{len(labels)}**",
         f"- Excluded runs: **{len(excluded)}** (listed in `build_manifest.json` with reasons)", "",
         "| File | Grain | Role |", "|---|---|---|",
         "| `experiments.csv` | experiment | identifiers, conditions, scenario (ground truth), split fold |",
         "| `pair_window.csv` | experiment × window × host pair | ICMP features |",
         "| `interface_window.csv` | experiment × window × interface | counter-delta, state and queue features |",
         "| `flow_window.csv` | experiment × window | background-flow receiver features |",
         "| `labels_window.csv` | experiment × window | **ground truth only** |",
         "| `feature_dictionary.csv` | column | unit, leakage class, allowed as model input |",
         "| `graph_schema.json` | topology | node/edge index, feature sources, label tasks |",
         "| `quality_report.json` | dataset | all checks below + statistics |", "",
         "## Quality checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    for c in q["checks"]:
        L.append(f"| {c['check']} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail'][:120]} |")
    L += ["", "## Class balance (windows)", "", "| Fault family | Windows |", "|---|---:|"]
    for k, v in sorted(s["windows_by_family"].items()):
        L.append(f"| {k} | {v} |")
    L += ["", "Active-fault windows by target: " + ", ".join(f"{k}={v}" for k, v in sorted(s["windows_by_target_active"].items())),
          "", f"Experiments per fold: {dict(sorted(s['experiments_by_fold'].items()))}", "",
          "## Window durations", "", "| Protocol | n | min s | mean s | max s |", "|---|---:|---:|---:|---:|"]
    for p, d in s["window_duration_s"].items():
        L.append(f"| {p} | {d['n']} | {d['min']} | {d['mean']} | {d['max']} |")
    L += ["", "## Leakage review (quantified)", "",
          f"- **Interface state** ({s['leakage_interface_state']['rule']}): true positives "
          f"{s['leakage_interface_state']['true_positives']}, false positives {s['leakage_interface_state']['false_positives']}, "
          f"recall on admin-mechanism faults {s['leakage_interface_state']['recall_on_admin_mechanism_faults']}. "
          "`admin_up`, `carrier`, `oper_up` are classified `mechanism_revealing` and excluded from default model inputs.",
          f"- **Localisation from admin state**: exact target recovered in "
          f"{s['leakage_localization_from_admin_state']['exact_target_recovered']}/"
          f"{s['leakage_localization_from_admin_state']['windows']} admin-mechanism fault windows. Any localisation "
          "result using these columns measures the injection mechanism, not realistic diagnosis.",
          "- **window_id** deterministically encodes the phase in v2 (`w01–w03` healthy, `w04–w06` failed, `w07–w09` "
          "recovered): " + ", ".join(f"{k}: {v}" for k, v in list(s["leakage_window_id_vs_phase_v2"].items())[:9]) +
          ". It is an identifier, never a feature.",
          "- `experiment_id`, `campaign_id`, timestamps, `run_seed` and `raw_relative_path` are identifiers; "
          "`scenario_key`, `fault_*`, `param_*`, `phase`, `expected_unreachable_pairs` are ground truth.",
          "- `offered_mbps` is an experimental *condition* (constant per run); use only if the deployment "
          "would know the load profile.",
          "- `tc_samples.csv` configured parameters (`cfg_*`) exist only in raw data and are never exported.",
          "", "## Splitting policy", "",
          "- Unit = independent experiment. Folds 1–3 = leave-one-repetition-out within each "
          "(protocol, scenario, load) stratum; every stratum appears in every fold.",
          "- Never split windows or rows of one experiment across train/test.",
          "- v1 (`small_link_v1`: sequential probes, 2 packets, no traffic/tc telemetry, variable window length) and "
          "v2 rows differ in protocol; train/test on mixed protocols only with protocol as an explicit covariate.", "",
          "## Missing values (fraction, by protocol; expected where noted)", "",
          "Expected: `loss_pct` empty for route_unreachable; `rtt_*` empty when no reply; flow/qdisc columns empty "
          "for v1 and idle runs; receiver values empty outside flow segments.", "", "| Column[protocol] | Missing |", "|---|---:|"]
    for k, v in sorted(s["missing_fraction"].items()):
        L.append(f"| {k} | {v} |")
    args.report.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
