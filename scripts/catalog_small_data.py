#!/usr/bin/env python3
"""Catalogue and checksum SMALL experimental evidence (offline, read-only on data).

    python scripts/catalog_small_data.py            # (re)write data/catalog/
    python scripts/catalog_small_data.py --verify   # compare data/ with data/catalog/SHA256SUMS

Writes:
  data/catalog/small_v1_inventory.csv  one row per raw folder: kind, protocol, role,
                                       campaign(s), status, scenario, in-dataset flag
  data/catalog/SHA256SUMS              sha256 of every file under data/raw, data/campaigns,
                                       data/audits and data/processed (paths relative to repo root)

Raw folders keep their repository-relative paths (`data/raw/small_v1/<exp>`), which manifests
and the dataset reference as `raw_relative_path`. Each path is looked up in the repository first
and then in the external archive (see `src/smartmall/paths.py`), so the catalogue and `--verify`
cover evidence wherever it is stored.
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.paths import resolve, search_roots  # noqa: E402

DATA = ROOT / "data"
RAW = resolve("data/raw/small_v1")
CATALOG = DATA / "catalog"
EVIDENCE_DIRS = ("raw", "campaigns", "audits", "processed")
DATASET_EXPERIMENTS = DATA / "processed" / "small_dataset_v2" / "experiments.csv"
FIELDS = ["folder", "kind", "protocol", "role", "campaigns", "status", "scenario", "load_mbps",
          "in_dataset", "files", "bytes"]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def campaign_membership():
    member = defaultdict(list)
    for manifest in sorted(resolve("data/campaigns").glob("*/manifest.json")):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for r in m.get("runs") or m.get("experiments") or []:
            if r.get("experiment_id"):
                member[r["experiment_id"]].append(m["campaign_id"])
    return member


def classify(folder, member, in_dataset):
    name = folder.name
    files = [p for p in folder.rglob("*") if p.is_file()]
    row = {"folder": f"data/raw/small_v1/{name}", "campaigns": ";".join(member.get(name, [])),
           "in_dataset": int(name in in_dataset), "files": len(files),
           "bytes": sum(p.stat().st_size for p in files), "scenario": "", "load_mbps": "", "status": ""}
    if name.startswith("scn_"):
        gt = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
        sc = gt["scenario"]
        row.update(kind="scenario_experiment", protocol=gt.get("protocol_version", ""), status=gt["status"],
                   scenario=f"{sc['fault_type']}:{sc['target'] or '-'}"
                   + (json.dumps(sc["params"], sort_keys=True) if sc["params"] else ""),
                   load_mbps=gt["traffic"]["offered_mbps"])
        camps = row["campaigns"]
        row["role"] = ("dataset" if row["in_dataset"] else
                       "pilot" if "_pilot_" in camps else "smoke_test" if not camps else "other")
    elif name.startswith("exp_"):
        gt = json.loads((folder / "incident.json").read_text(encoding="utf-8"))
        row.update(kind="link_failure_experiment", protocol="small_link_v1", status=gt.get("status", ""),
                   scenario=f"LINK_FAILURE:{gt['ground_truth'].get('fault_link_id', '')}", load_mbps=0)
        row["role"] = ("dataset" if row["in_dataset"] else
                       "failed_run" if gt.get("status") != "completed" else "historical_v1_development")
    elif name.startswith("receiver_verify_"):
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        row.update(kind="receiver_verification", protocol="stage_a", status=m["status"],
                   role="stage_a_verification" if m.get("acceptance") == "PASS" else "stage_a_failed_attempt")
    elif name.startswith("load_pilot_"):
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        row.update(kind="load_pilot", protocol="load_pilot_v1", status=m["status"], role="historical_pilot")
    elif name.startswith("design_probe_"):
        row.update(kind="design_probe", protocol="design_probe", status="completed", role="design_evidence")
    else:
        row.update(kind="unknown", protocol="", role="unclassified")
    return row


def evidence_files():
    """Map repository-relative path -> file, repository copy taking precedence over the archive."""
    found = {}
    for root in reversed(search_roots()):
        for sub in EVIDENCE_DIRS:
            for p in sorted((root / "data" / sub).rglob("*")):
                if p.is_file():
                    found[str(p.relative_to(root)).replace("\\", "/")] = p
    return dict(sorted(found.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="Verify the evidence (repository + archive) against data/catalog/SHA256SUMS")
    args = ap.parse_args()
    sums_path = CATALOG / "SHA256SUMS"
    if args.verify:
        expected = {}
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            digest, rel = line.split("  ", 1)
            expected[rel] = digest
        actual = evidence_files()
        print("searched: " + ", ".join(str(r) for r in search_roots()))
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(r for r in set(expected) & set(actual) if sha256(actual[r]) != expected[r])
        print(f"checked {len(expected)} catalogued files: missing={len(missing)} changed={len(changed)} "
              f"new(uncatalogued)={len(added)}")
        for label, items in (("MISSING", missing), ("CHANGED", changed), ("NEW", added)):
            for r in items[:20]:
                print(f"  {label} {r}")
        sys.exit(1 if missing or changed else 0)

    member = campaign_membership()
    in_dataset = set()
    if DATASET_EXPERIMENTS.is_file():
        with DATASET_EXPERIMENTS.open(newline="", encoding="utf-8") as h:
            in_dataset = {r["experiment_id"] for r in csv.DictReader(h)}
    rows = [classify(f, member, in_dataset) for f in sorted(RAW.iterdir()) if f.is_dir()]
    CATALOG.mkdir(parents=True, exist_ok=True)
    with (CATALOG / "small_v1_inventory.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    lines = [f"{sha256(p)}  {rel}" for rel, p in evidence_files().items()]
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Catalogued {len(rows)} raw folders; roles: {dict(Counter(r['role'] for r in rows))}")
    print(f"Checksummed {len(lines)} evidence files -> {sums_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
