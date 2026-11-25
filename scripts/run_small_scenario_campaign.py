#!/usr/bin/env python3
"""Config-driven SMALL scenario campaign (protocol small_scenario_v2).

    python3 scripts/run_small_scenario_campaign.py configs/small_stageB_pilot.json --dry-run
    sudo /usr/bin/python3 scripts/run_small_scenario_campaign.py configs/small_stageB_pilot.json

Each run is an independent Mininet instantiation executed as a separate
process (scripts/run_small_scenario.py). Run order is shuffled with the
documented campaign seed; every run gets its own derived seed. Raw folders are
never overwritten; failed runs stay listed in the manifest as evidence.
Every completed run is audited (src/smartmall/audit.py).
"""
import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall import scenarios as S  # noqa: E402
from smartmall import topology as topo  # noqa: E402
from smartmall.audit import audit_experiment  # noqa: E402

RUNNER = ROOT / "scripts" / "run_small_scenario.py"
CAMPAIGN_ROOT = ROOT / "data" / "campaigns"
AUDIT_ROOT = ROOT / "data" / "audits"
EST_SECONDS_BASE = 22.0          # Mininet start/stop, pingAll, recovery check, settles
EST_KB_IDLE, EST_KB_LOAD = 110, 230


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expand_plan(config, spec):
    proto = config.get("protocol", {})
    runs = []
    for entry in config["scenarios"]:
        loads = entry.get("loads_mbps", config.get("loads_mbps", [0]))
        params = entry.get("params", {})
        scenario = S.validate_scenario(spec, entry["fault_type"], entry.get("target"), params)
        for load in loads:
            for rep in range(1, config.get("repeats", 1) + 1):
                runs.append({"scenario": scenario, "load_mbps": int(load), "repetition": rep,
                             "protocol": {**proto, **entry.get("protocol", {})}})
    rng = random.Random(config["seed"])
    rng.shuffle(runs)
    for index, run in enumerate(runs, 1):
        run["order"] = index
        run["run_seed"] = rng.randrange(1, 2 ** 31)
    return runs


def estimate(run):
    p = run["protocol"]
    rounds, window = p.get("rounds", 3), p.get("window_s", 4.0)
    secs = EST_SECONDS_BASE + 3 * rounds * (window + 0.1)
    if run["load_mbps"] > 0:
        secs += 3 * p.get("warmup_s", 2.0) + 8
    kb = EST_KB_LOAD if run["load_mbps"] > 0 else EST_KB_IDLE
    return secs, kb


def runner_cmd(run, campaign_id):
    sc, p = run["scenario"], run["protocol"]
    cmd = [sys.executable, str(RUNNER), "--fault-type", sc["fault_type"],
           "--load-mbps", str(run["load_mbps"]), "--seed", str(run["run_seed"]),
           "--campaign-id", campaign_id, "--repetition", str(run["repetition"])]
    if sc["target"]:
        cmd += ["--target", sc["target"]]
    flag = {"added_delay_ms": "--added-delay-ms", "loss_pct": "--loss-pct",
            "bw_mbps": "--bw-mbps", "queue_pkts": "--queue-pkts"}
    for key, value in sc["params"].items():
        cmd += [flag[key], str(value)]
    opt = {"rounds": "--rounds", "window_s": "--window-s", "packets": "--packets",
           "ping_interval": "--ping-interval", "ping_wait": "--ping-wait",
           "warmup_s": "--warmup-s", "settle_s": "--settle-s"}
    for key, value in p.items():
        cmd += [opt[key], str(value)]
    return cmd


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stop-on-fail", action="store_true")
    args = ap.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    spec = topo.load_spec(ROOT / "topologies" / "small.json")
    runs = expand_plan(config, spec)
    total_s = sum(estimate(r)[0] for r in runs)
    total_kb = sum(estimate(r)[1] for r in runs)
    print(f"Campaign '{config['campaign_name']}': {len(runs)} runs, seed={config['seed']}")
    print(f"Estimated duration ~{total_s / 60:.1f} min, raw disk ~{total_kb / 1024:.1f} MB")
    for r in runs:
        sc = r["scenario"]
        print(f"  #{r['order']:03d} {sc['fault_type']:16s} {sc['target'] or '-':9s} "
              f"{json.dumps(sc['params']) if sc['params'] else '':40s} load={r['load_mbps']:>2} rep={r['repetition']}")
    if args.dry_run:
        print("DRY RUN: nothing executed")
        return

    campaign_id = (f"campaign_{config['campaign_name']}_"
                   + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6])
    folder = CAMPAIGN_ROOT / campaign_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    manifest = {"campaign_id": campaign_id, "protocol_version": S.PROTOCOL_VERSION,
                "config_file": str(args.config).replace("\\", "/"), "config_sha256": sha256(args.config),
                "seed": config["seed"], "started_at_utc": now(), "status": "running",
                "planned_runs": len(runs),
                "estimate": {"minutes": round(total_s / 60, 1), "raw_mb": round(total_kb / 1024, 1)},
                "source_sha256": {p: sha256(ROOT / p) for p in (
                    "scripts/run_small_scenario.py", "scripts/run_small_scenario_campaign.py",
                    "src/smartmall/audit.py", "src/smartmall/scenarios.py",
                    "src/smartmall/telemetry.py", "src/smartmall/topology.py",
                    "src/smartmall/iperf_receiver.py", "topologies/small.json")},
                "runs": []}
    write = lambda: (folder / "manifest.json").write_text(  # noqa: E731
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    for r in runs:
        sc = r["scenario"]
        cmd = runner_cmd(r, campaign_id)
        print(f"\n[{r['order']}/{len(runs)}] {sc['fault_type']} {sc['target'] or ''} "
              f"{sc['params'] or ''} load={r['load_mbps']} rep={r['repetition']}", flush=True)
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        log = proc.stdout + proc.stderr
        saved = [l for l in log.splitlines() if l.startswith("Saved: ")]
        raw = Path(saved[-1].split("Saved: ", 1)[1].split(" [")[0]) if saved else None
        record = {"order": r["order"], "fault_type": sc["fault_type"], "target": sc["target"],
                  "params": sc["params"], "load_mbps": r["load_mbps"], "repetition": r["repetition"],
                  "run_seed": r["run_seed"], "returncode": proc.returncode,
                  "elapsed_s": round(time.time() - t0, 1),
                  "experiment_id": raw.name if raw else None,
                  "raw_relative_path": str(raw.relative_to(ROOT)).replace("\\", "/") if raw else None}
        if raw is not None:
            (raw / "runner_log.txt").write_text(log, encoding="utf-8")
        if proc.returncode == 0 and raw is not None:
            res = audit_experiment(raw)
            for target in (AUDIT_ROOT / f"{res['experiment_id']}.json",
                           folder / "audits_at_collection" / f"{res['experiment_id']}.json"):
                target.parent.mkdir(exist_ok=True)
                target.write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
            record["audit"] = "PASS" if res["passed"] else "FAIL"
            record["failed_checks"] = res.get("failed_checks", [])
        else:
            record["audit"] = "NOT_RUN"
            record["error_tail"] = log[-800:]
        manifest["runs"].append(record)
        write()
        print(f"  -> rc={proc.returncode} audit={record['audit']} {record.get('failed_checks') or ''} "
              f"({record['elapsed_s']} s) {record['experiment_id']}", flush=True)
        leftover = subprocess.run(["ovs-vsctl", "list-br"], capture_output=True, text=True).stdout.split()
        if leftover:
            subprocess.run(["mn", "-c"], capture_output=True)
            record["post_run_cleanup"] = f"mn -c removed {leftover}"
            write()
        if args.stop_on_fail and record["audit"] != "PASS":
            print("Stopping on failure", flush=True)
            break
    passed = sum(1 for x in manifest["runs"] if x["audit"] == "PASS")
    manifest["finished_at_utc"] = now()
    manifest["elapsed_min"] = round((time.time() - t_start) / 60, 1)
    manifest["passed_runs"] = passed
    manifest["status"] = "completed" if passed == len(runs) == len(manifest["runs"]) else "completed_with_failures"
    write()
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["order", "experiment_id", "fault_type", "target", "params", "load_mbps",
                  "repetition", "run_seed", "returncode", "audit", "failed_checks", "elapsed_s",
                  "raw_relative_path"]
        w = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for x in manifest["runs"]:
            w.writerow({**x, "params": json.dumps(x["params"]), "failed_checks": ";".join(x.get("failed_checks", []))})
    print(f"\nCampaign {campaign_id}: {passed}/{len(runs)} PASS in {manifest['elapsed_min']} min")
    print(f"Manifest: {folder / 'manifest.json'}")
    sys.exit(0 if manifest["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
