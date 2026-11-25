"""Dataset builder / graph loader tests on committed raw data (v1 + B pilot)."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.paths import resolve  # noqa: E402
from smartmall import dataset as D  # noqa: E402
from smartmall.graph_loader import load_snapshots  # noqa: E402

PILOT = resolve("data/campaigns/campaign_B_pilot_20261125T154421Z_b12ae9")
V1 = [resolve("data/campaigns/campaign_20261125T134916Z_249a1c"),
      resolve("data/campaigns/campaign_20261125T140815Z_f24de3")]


def rows(path):
    with path.open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


@unittest.skipUnless(PILOT.is_dir() and all(p.is_dir() for p in V1), "committed campaigns missing")
class DatasetBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()) / "ds"
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_small_dataset.py"),
                               "--v2-campaigns", str(PILOT), "--v1-campaigns", *map(str, V1),
                               "--out", str(cls.tmp)], capture_output=True, text=True)
        cls.log = proc.stdout + proc.stderr
        cls.q = json.loads((cls.tmp / "quality_report.json").read_text(encoding="utf-8"))

    def test_counts(self):
        exps = rows(self.tmp / "experiments.csv")
        self.assertEqual(len(exps), 24)                       # 18 v1 + 6 pilot
        self.assertEqual(Counter(e["protocol_version"] for e in exps),
                         {"small_link_v1": 18, "small_scenario_v2": 6})

    def test_checks_except_fold_coverage_pass(self):
        failing = {c["check"] for c in self.q["checks"] if not c["pass"]}
        # pilot has one repetition per stratum, so only fold coverage may fail
        self.assertLessEqual(failing, {"strata_cover_all_folds"}, self.log)

    def test_feature_tables_have_no_labels(self):
        for name in ("pair_window.csv", "interface_window.csv", "flow_window.csv"):
            header = next(csv.reader((self.tmp / name).open(encoding="utf-8")))
            self.assertFalse(set(header) & set(D.LABEL_FIELDS[2:]), name)

    def test_every_column_classified(self):
        dic = {(r["table"], r["column"]) for r in rows(self.tmp / "feature_dictionary.csv")}
        for name in ("pair_window", "interface_window", "flow_window", "labels_window", "experiments"):
            header = next(csv.reader((self.tmp / f"{name}.csv").open(encoding="utf-8")))
            for col in header:
                self.assertIn((name, col), dic)

    def test_v1_folds_leave_one_repetition_out(self):
        exps = [e for e in rows(self.tmp / "experiments.csv") if e["protocol_version"] == "small_link_v1"]
        per = {}
        for e in exps:
            per.setdefault(e["scenario_key"], []).append(e["split_fold"])
        for key, folds in per.items():
            self.assertEqual(sorted(folds), ["1", "2", "3"], key)

    def test_interface_state_leakage_quantified(self):
        leak = self.q["stats"]["leakage_interface_state"]
        self.assertEqual(leak["false_positives"], 0)
        self.assertEqual(leak["recall_on_admin_mechanism_faults"], 1.0)

    def test_graph_snapshots(self):
        snaps = list(load_snapshots(self.tmp, with_labels=True))
        self.assertEqual(len(snaps), len(rows(self.tmp / "labels_window.csv")))
        s = snaps[0]
        self.assertEqual(len(s["node_ids"]), 7)
        self.assertEqual(len(s["edge_index"][0]), 6)
        self.assertEqual(len(s["x_edge"][0]), len(s["edge_feature_names"]))
        self.assertNotIn("src_end.admin_up", s["edge_feature_names"])
        self.assertIn("phase", s["label"])
        r = list(load_snapshots(self.tmp, include_restricted=True))[0]
        self.assertIn("src_end.admin_up", r["edge_feature_names"])


if __name__ == "__main__":
    unittest.main()
