#!/usr/bin/env python3
"""Audit small_scenario_v2 experiments (offline, read-only on raw data).

    python scripts/audit_small_scenario.py data/raw/small_v1/scn_...  [more folders]
    python scripts/audit_small_scenario.py --campaign data/campaigns/<campaign_id>

Writes data/audits/v_<auditor-sha12>/<experiment_id>.json (never modifies raw folders
or the collection-time audits in data/audits/) and prints
a one-line verdict per experiment. Exit code 1 if any experiment fails.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.audit import audit_experiment, auditor_version  # noqa: E402
from smartmall.paths import resolve  # noqa: E402

# Re-audits go to a per-auditor-version folder; data/audits/<exp>.json holds the
# collection-time audit written by the campaign runner and is never overwritten here.
AUDIT_ROOT = ROOT / "data" / "audits" / f"v_{auditor_version()[:12]}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folders", nargs="*", type=resolve)
    p.add_argument("--campaign", type=resolve, help="Campaign folder with manifest.json")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--out-dir", type=Path, default=AUDIT_ROOT,
                   help="Where to write audit JSON (default data/audits/v_<auditor-sha12>/; "
                        "use a temporary directory for smoke-test runs)")
    args = p.parse_args()
    folders = list(args.folders)
    if args.campaign:
        manifest = json.loads((args.campaign / "manifest.json").read_text(encoding="utf-8"))
        folders += [resolve(r["raw_relative_path"]) for r in manifest["runs"] if r.get("raw_relative_path")]
    if not folders:
        p.error("no experiment folders given")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for folder in folders:
        res = audit_experiment(folder)
        (args.out_dir / f"{res['experiment_id']}.json").write_text(
            json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
        verdict = "PASS" if res["passed"] else "FAIL"
        failures += not res["passed"]
        print(f"{verdict} {res['experiment_id']} {res['fault_type']} {res['target'] or '-'} "
              f"{res['params'] or ''} load={res['offered_mbps']}"
              + ("" if res["passed"] else f"  failed={res['failed_checks']}"))
        for w in res.get("warnings", []):
            print(f"    warning: {w}")
        if not args.quiet and not res["passed"]:
            for c in res["checks"]:
                if not c["pass"]:
                    print(f"    - {c['check']}: {c['detail']}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
