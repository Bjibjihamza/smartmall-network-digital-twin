"""Auditor regression tests on a real committed experiment and tampered copies.

The auditor must PASS the genuine run and FAIL when typical data defects
are introduced (label leakage, counter reset, wrong signature, missing rows).
"""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.paths import resolve  # noqa: E402
from smartmall.audit import audit_experiment  # noqa: E402

# Stage B pilot run: LINK_FAILURE L5 at 5 Mb/s (sender access link; client aborts)
GENUINE = resolve("data/raw/small_v1/scn_20261125T154614Z_d7cbfa")


def rewrite_csv(path, mutate):
    with path.open(newline="", encoding="utf-8") as h:
        reader = csv.DictReader(h)
        fields = list(reader.fieldnames)
        rows = list(reader)
    fields, rows = mutate(fields, rows)
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


@unittest.skipUnless(GENUINE.is_dir(), "genuine pilot experiment not present")
class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.exp = self.tmp / GENUINE.name
        shutil.copytree(GENUINE, self.exp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def failed(self):
        res = audit_experiment(self.exp)
        return res["passed"], set(res.get("failed_checks", []))

    def test_genuine_passes(self):
        ok, failed = self.failed()
        self.assertTrue(ok, failed)

    def test_label_column_leak_detected(self):
        rewrite_csv(self.exp / "icmp_probes.csv",
                    lambda f, r: (f + ["phase"], [dict(x, phase="failed") for x in r]))
        ok, failed = self.failed()
        self.assertFalse(ok)
        self.assertIn("no_label_columns:icmp_probes.csv", failed)

    def test_counter_reset_detected(self):
        def mutate(f, rows):
            rows[40]["counter_reset"] = "1"
            return f, rows
        rewrite_csv(self.exp / "port_window_deltas.csv", mutate)
        ok, failed = self.failed()
        self.assertIn("no_counter_resets", failed)

    def test_wrong_signature_detected(self):
        def mutate(f, rows):
            for r in rows:   # pretend PC-ADM<->POS was unreachable in a healthy window
                if r["window_id"] == "w01" and r["source_node_id"] == "PC-ADM" and r["target_node_id"] == "POS":
                    r.update(packets_received="0", loss_pct="100.0", reachable="0", rtt_avg_ms="")
            return f, rows
        rewrite_csv(self.exp / "icmp_probes.csv", mutate)
        ok, failed = self.failed()
        self.assertIn("connectivity_signature_matches_expectation", failed)

    def test_route_unreachable_with_loss_is_invalid(self):
        def mutate(f, rows):
            for r in rows:
                if r["probe_status"] == "route_unreachable":
                    r["loss_pct"] = "100.0"   # the exact confusion the protocol forbids
                    break
            return f, rows
        rewrite_csv(self.exp / "icmp_probes.csv", mutate)
        ok, failed = self.failed()
        self.assertIn("icmp_status_semantics", failed)

    def test_missing_rows_detected(self):
        rewrite_csv(self.exp / "port_samples.csv", lambda f, r: (f, r[:-3]))
        ok, failed = self.failed()
        self.assertIn("port_sample_count", failed)

    def test_failed_status_detected(self):
        gt = json.loads((self.exp / "incident.json").read_text(encoding="utf-8"))
        gt["status"] = "failed"
        (self.exp / "incident.json").write_text(json.dumps(gt), encoding="utf-8")
        ok, failed = self.failed()
        self.assertFalse(ok)
        self.assertIn("status_completed", failed)

    def _set_rtt(self, windows, pairs, **values):
        def mutate(f, rows):
            for r in rows:
                if r["window_id"] in windows and (r["source_node_id"], r["target_node_id"]) in pairs:
                    r.update({k: str(v) for k, v in values.items()})
            return f, rows
        rewrite_csv(self.exp / "icmp_probes.csv", mutate)

    def test_single_window_rtt_transient_is_warning_not_failure(self):
        # One recovered window with a delayed echo on every reachable pair (min RTT unchanged)
        pairs = {("PC-ADM", "POS"), ("PC-ADM", "SRV-LOCAL"), ("POS", "SRV-LOCAL")}
        self._set_rtt({"w09"}, pairs, rtt_avg_ms=40.0, rtt_max_ms=110.0)
        res = audit_experiment(self.exp)
        self.assertTrue(res["passed"], res.get("failed_checks"))
        self.assertTrue(any("mean RTT shift" in w for w in res["warnings"]))
        self.assertTrue(res["observed_effects"]["rtt_transient_windows"])

    def test_persistent_path_delay_shift_after_recovery_fails(self):
        # Two of three recovered windows with +5 ms on the minimum RTT: path not restored
        pairs = {("PC-ADM", "POS")}
        self._set_rtt({"w08", "w09"}, pairs, rtt_min_ms=13.3, rtt_avg_ms=13.4, rtt_max_ms=13.5)
        ok, failed = self.failed()
        self.assertIn("rtt_recovered_path_delay", failed)

    def test_injection_time_outside_phase_gap_detected(self):
        gt = json.loads((self.exp / "incident.json").read_text(encoding="utf-8"))
        gt["injected_at_utc"] = gt["windows"][0]["start_utc"]
        (self.exp / "incident.json").write_text(json.dumps(gt), encoding="utf-8")
        ok, failed = self.failed()
        self.assertIn("injection_between_phases", failed)


DELAY_RUN = resolve("data/raw/small_v1/scn_20261125T164805Z_d5a4ee")  # C pilot: +20 ms on L5


@unittest.skipUnless(DELAY_RUN.is_dir(), "Stage C pilot delay run not present")
class DelayEffectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.exp = self.tmp / DELAY_RUN.name
        shutil.copytree(DELAY_RUN, self.exp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _set(self, windows, pair, **values):
        def mutate(f, rows):
            for r in rows:
                if r["window_id"] in windows and (r["source_node_id"], r["target_node_id"]) == pair:
                    r.update({k: str(v) for k, v in values.items()})
            return f, rows
        rewrite_csv(self.exp / "icmp_probes.csv", mutate)

    def test_genuine_delay_run_passes(self):
        res = audit_experiment(self.exp)
        self.assertTrue(res["passed"], res.get("failed_checks"))
        self.assertAlmostEqual(res["observed_effects"]["rtt_impaired_increase_ms"], 40.0, delta=2.0)

    def test_transient_on_unimpaired_pair_does_not_break_isolation(self):
        # one healthy window: one echo of an unimpaired pair delayed by 55 ms (min unchanged)
        self._set({"w03"}, ("PC-ADM", "POS"), rtt_avg_ms=26.5, rtt_max_ms=63.0)
        res = audit_experiment(self.exp)
        self.assertTrue(res["passed"], res.get("failed_checks"))

    def test_delay_leaking_to_unimpaired_pair_fails_isolation(self):
        # every FAILED window of an unimpaired pair carries +20 ms on the minimum RTT
        self._set({"w04", "w05", "w06"}, ("PC-ADM", "POS"), rtt_min_ms=28.3, rtt_avg_ms=28.4, rtt_max_ms=28.5)
        res = audit_experiment(self.exp)
        self.assertIn("effect_delay_isolated_to_impaired_pairs", res["failed_checks"])


if __name__ == "__main__":
    unittest.main()
