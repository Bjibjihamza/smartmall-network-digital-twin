#!/usr/bin/env python3
"""SmartMall Phase 2.9a: reproducible multi-LINK campaign for SMALL v1.

Usage in Ubuntu/WSL2 from project root:
    sudo /usr/bin/python3 scripts/legacy/run_small_link_campaign.py --dry-run
    sudo /usr/bin/python3 scripts/legacy/run_small_link_campaign.py
    sudo /usr/bin/python3 scripts/legacy/run_small_link_campaign.py --links L1 L2 --repeats 2

Reuses the validated single-incident collector; it NEVER overwrites raw runs.
Each link failure is a separate, clean Mininet experiment with healthy,
failed and recovered observations. This covers LINK_FAILURE only — the
next scientific stage is node faults, degradations, and service failures.

IMPORTANT: configLinkStatus() is administrative-down, directly observable
via admin_up. These observations validate the laboratory and data pipeline,
NOT a fair benchmark of GNN fault localization. Labels and phases remain
in incident.json and campaign metadata, outside telemetry CSV files.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "topologies" / "small.json"
COLLECTOR = ROOT / "scripts" / "legacy" / "collect_small_with_ports.py"
AUDITOR = ROOT / "scripts" / "legacy" / "audit_port_experiment.py"
RAW_ROOT = ROOT / "data" / "raw" / "small_v1"
CAMPAIGN_ROOT = ROOT / "data" / "campaigns"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def csv_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        forbidden = {"phase", "fault_type", "fault_link_id", "label", "ground_truth"}
        if forbidden & columns:
            raise ValueError(f"Label leakage in {path.name}: {sorted(forbidden & columns)}")
        return list(reader)


def check_result(folder, expected_link, spec, rounds):
    """Structural checks + basic observable healthy/failure/recovery checks."""
    required = ["topology.json", "incident.json", "telemetry.csv", "port_telemetry.csv"]
    missing = [name for name in required if not (folder / name).is_file()]
    if missing:
        raise ValueError(f"Missing files in {folder.name}: {missing}")

    metadata = json.loads((folder / "incident.json").read_text(encoding="utf-8-sig"))
    truth = metadata["ground_truth"]
    if metadata.get("status") != "completed" or truth.get("fault_link_id") != expected_link:
        raise ValueError(f"Unexpected incident status or fault target for {folder.name}")
    if metadata.get("topology_id") != spec["topology_id"]:
        raise ValueError("Topology ID mismatch")
    if json.loads((folder / "topology.json").read_text(encoding="utf-8-sig")) != spec:
        raise ValueError("Saved topology does not match the current specification")

    probes = csv_rows(folder / "telemetry.csv")
    ports = csv_rows(folder / "port_telemetry.csv")
    snapshots = truth["snapshots"]
    phase_by_snapshot = {s["snapshot_id"]: s["phase"] for s in snapshots}
    host_count = sum(n["type"] == "host" for n in spec["nodes"])
    pair_count = host_count * (host_count - 1) // 2
    expected_windows = 3 * rounds
    expected_probes = expected_windows * pair_count
    expected_ports = expected_windows * len(spec["links"]) * 2 * 2
    if len(snapshots) != expected_windows or len(probes) != expected_probes or len(ports) != expected_ports:
        raise ValueError(f"Wrong record counts for {folder.name}: windows={len(snapshots)}, "
                         f"icmp={len(probes)}, ports={len(ports)}")

    counts = {p: {"total": 0, "loss": 0, "route_unreachable": 0, "disrupted": 0}
              for p in ("healthy", "failed", "recovered")}
    for r in probes:
        if r.get("experiment_id") != metadata["experiment_id"]:
            raise ValueError("ICMP experiment ID mismatch")
        phase = phase_by_snapshot.get(r["snapshot_id"])
        if phase not in counts:
            raise ValueError("Unexpected snapshot/phase")
        status = r.get("probe_status", "icmp_stats")  # supports older successful runs
        sent, received, reachable = int(r["packets_sent"]), int(r["packets_received"]), int(r["reachable"])
        if status == "route_unreachable":
            if sent != 0 or received != 0 or r["loss_pct"] != "" or reachable != 0:
                raise ValueError(f"Invalid local-route-failure record: {r}")
            counts[phase]["route_unreachable"] += 1
        elif status == "icmp_stats":
            if sent < 1 or not 0 <= received <= sent or r["loss_pct"] == "":
                raise ValueError(f"Invalid ICMP packet counts/loss: {r}")
            loss = float(r["loss_pct"])
            if not 0 <= loss <= 100 or abs(loss - 100 * (sent - received) / sent) > 0.15:
                raise ValueError(f"Inconsistent ICMP loss: {r}")
            counts[phase]["loss"] += (loss > 0)
        else:
            raise ValueError(f"Unrecognized probe_status: {status}")
        if reachable != int(received > 0):
            raise ValueError(f"Inconsistent reachable and packets_received: {r}")
        counts[phase]["disrupted"] += (reachable == 0)

    down_by_phase = {p: {"target": 0, "other": 0} for p in counts}
    for r in ports:
        if r.get("experiment_id") != metadata["experiment_id"]:
            raise ValueError("Port experiment ID mismatch")
        phase = phase_by_snapshot.get(r["snapshot_id"])
        if phase not in down_by_phase:
            raise ValueError("Unexpected port snapshot/phase")
        if r["admin_up"] == "0":
            category = "target" if r["link_id"] == expected_link else "other"
            down_by_phase[phase][category] += 1

    if (counts["healthy"]["disrupted"] or counts["recovered"]["disrupted"]
            or not counts["failed"]["disrupted"]):
        raise ValueError(f"Incorrect connectivity observations in {folder.name}: {counts}")
    if (down_by_phase["healthy"]["target"] or down_by_phase["recovered"]["target"]
            or down_by_phase["failed"]["target"] != rounds * 2 * 2
            or any(x["other"] for x in down_by_phase.values())):
        raise ValueError(f"Incorrect administrative port state in {folder.name}: {down_by_phase}")

    return {
        "experiment_id": metadata["experiment_id"],
        "fault_type": "LINK_FAILURE",
        "fault_link_id": expected_link,
        "status": "PASS",
        "windows": len(snapshots),
        "icmp_rows": len(probes),
        "port_rows": len(ports),
        "failed_probes_with_loss": counts["failed"]["loss"],
        "failed_probes_route_unreachable": counts["failed"]["route_unreachable"],
        "failed_probes_disrupted": counts["failed"]["disrupted"],
        "fault_port_down_samples": down_by_phase["failed"]["target"],
        "raw_relative_path": str(folder.relative_to(ROOT)).replace("\\", "/"),
    }


def write_summary(path, records):
    fields = [
        "experiment_id", "fault_type", "fault_link_id", "status", "windows",
        "icmp_rows", "port_rows", "failed_probes_with_loss",
        "failed_probes_route_unreachable", "failed_probes_disrupted",
        "fault_port_down_samples", "raw_relative_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", nargs="+", default=None, metavar="LINK_ID",
                        help="Subset of small.json link IDs; default: all links")
    parser.add_argument("--repeats", type=int, default=1, help="Independent runs per link (default: 1)")
    parser.add_argument("--rounds", type=int, default=2, help="Windows per phase (default: 2)")
    parser.add_argument("--packets", type=int, default=2, help="ICMP requests per pair (default: 2)")
    parser.add_argument("--seed", type=int, default=42, help="Randomized run order seed (default: 42)")
    parser.add_argument("--dry-run", action="store_true", help="Display plan only; does not start Mininet")
    parser.add_argument("--audit", action="store_true", help="Run existing port audit on each experiment")
    args = parser.parse_args()

    for name in ("repeats", "rounds", "packets"):
        if getattr(args, name) < 1:
            parser.error(f"--{name} must be >= 1")
    if not TOPOLOGY.is_file() or not COLLECTOR.is_file():
        parser.error("Missing topologies/small.json or scripts/legacy/collect_small_with_ports.py")
    if args.audit and not AUDITOR.is_file():
        parser.error("--audit requires scripts/legacy/audit_port_experiment.py")

    spec = json.loads(TOPOLOGY.read_text(encoding="utf-8-sig"))
    if spec.get("topology_id") != "small_v1":
        parser.error("This campaign requires small_v1")
    known = [link["id"] for link in spec["links"]]
    selected = args.links or known
    if len(selected) != len(set(selected)) or any(link not in known for link in selected):
        parser.error(f"Links must be distinct valid IDs: {', '.join(known)}")
    plan = [link for link in selected for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(plan)

    print(f"\nSmartMall / Phase 2.9a — controlled link-failure campaign")
    print(f"Topology: {spec['topology_id']} | Seed: {args.seed}")
    print(f"Run order ({len(plan)} independent experiments): {', '.join(plan)}")
    print("Each run: 3 phases x {0} windows, {1} ICMP packets per host pair".format(args.rounds, args.packets))
    print("SCIENTIFIC LIMIT: administrative port-down directly exposes the fault target.")
    if args.dry_run:
        print("DRY RUN: no network created and no files written.")
        return
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Run from Ubuntu/WSL2 with sudo /usr/bin/python3 (not Windows Conda)")

    campaign_id = "campaign_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    destination = CAMPAIGN_ROOT / campaign_id
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {
        "campaign_id": campaign_id,
        "topology_id": spec["topology_id"],
        "started_at_utc": now(),
        "status": "running",
        "parameters": {"links": selected, "repeats": args.repeats, "rounds": args.rounds,
                       "packets": args.packets, "seed": args.seed, "order": plan},
        "source_sha256": {"topology_json": file_hash(TOPOLOGY), "collector_py": file_hash(COLLECTOR)},
        "scope": "LINK_FAILURE only — administratively disabled links",
        "scientific_limitations": [
            "This campaign validates collection and incident diversity, not realistic GNN localization.",
            "Port admin_up directly reveals the artificially disabled interface.",
            "Host-pair probes are sequential; each uses few ICMP packets.",
            "Raw experiment_id, timestamps and physical component IDs are metadata, not ML features.",
            "Do not split snapshots of an experiment across train and test.",
        ],
        "experiments": [],
    }
    write_json(destination / "manifest.json", manifest)
    records = []

    try:
        for number, fault_link in enumerate(plan, 1):
            print(f"\n{'=' * 62}\nRUN {number}/{len(plan)}: {fault_link}\n{'=' * 62}", flush=True)
            before = {p.name for p in RAW_ROOT.glob("exp_*") if p.is_dir()}
            cmd = [sys.executable, str(COLLECTOR), "--fault-link", fault_link,
                   "--rounds", str(args.rounds), "--packets", str(args.packets)]
            subprocess.run(cmd, cwd=ROOT, check=True)
            after = {p.name for p in RAW_ROOT.glob("exp_*") if p.is_dir()}
            new_dirs = after - before
            if len(new_dirs) != 1:
                raise RuntimeError(f"Expected exactly one new experiment, found {len(new_dirs)}: {new_dirs}")
            folder = RAW_ROOT / new_dirs.pop()
            record = check_result(folder, fault_link, spec, args.rounds)
            if args.audit:
                subprocess.run([sys.executable, str(AUDITOR), "--experiment", str(folder)],
                               cwd=ROOT, check=True)
            records.append(record)
            manifest["experiments"].append(record)
            write_json(destination / "manifest.json", manifest)
            write_summary(destination / "summary.csv", records)
            print(f"\nVALIDATED: {record['experiment_id']} / {fault_link}", flush=True)
        manifest["status"] = "completed"
        print(f"\nSUCCESS: {len(records)} independent LINK_FAILURE experiments completed.")
        print(f"Totals: {sum(r['icmp_rows'] for r in records)} ICMP rows; "
              f"{sum(r['port_rows'] for r in records)} port rows")
    except (Exception, KeyboardInterrupt) as exc:
        manifest["status"] = "incomplete"
        manifest["error"] = str(exc)
        print(f"\nCAMPAIGN INCOMPLETE: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        manifest["finished_at_utc"] = now()
        write_json(destination / "manifest.json", manifest)
        write_summary(destination / "summary.csv", records)
        print(f"Campaign manifest: {destination / 'manifest.json'}", flush=True)
        print(f"Campaign summary : {destination / 'summary.csv'}", flush=True)


if __name__ == "__main__":
    main()
