"""Regression tests for receiver-side iperf3 UDP extraction (Stage A).

Run from the project root:  python -m unittest discover -s tests -v
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartmall.paths import resolve  # noqa: E402

from smartmall.iperf_receiver import (  # noqa: E402
    STATUS_INVALID, STATUS_UNAVAILABLE, STATUS_VERIFIED, STATUS_ZERO,
    receiver_interval_rows, receiver_udp_stats, sender_udp_stats,
)

HISTORICAL = (resolve("data/raw/small_v1/receiver_verify_20261125T144957Z_737f8b")
              / "iperf3_server_udp_5mbps.json")


def interval(start, seconds, nbytes, packets, lost=0, jitter=0.05, **extra):
    rec = {"start": start, "end": start + seconds, "seconds": seconds, "bytes": nbytes,
           "bits_per_second": nbytes * 8 / seconds, "jitter_ms": jitter,
           "lost_packets": lost, "packets": packets,
           "lost_percent": 100 * lost / (packets + lost) if packets + lost else 0,
           "omitted": False, "sender": False}
    rec.update(extra)
    return {"streams": [dict(rec, socket=5)], "sum": rec}


def server_report(intervals, end_bytes=0, end_packets=None, end_lost=0):
    if end_packets is None:
        end_packets = sum(i["sum"]["packets"] for i in intervals) + end_lost
    return {
        "start": {"accepted_connection": {"host": "10.42.0.13", "port": 1},
                  "timestamp": {"timesecs": 1_000_000},
                  "test_start": {"protocol": "UDP", "blksize": 1000, "reverse": 0}},
        "intervals": intervals,
        "end": {"sum": {"bytes": end_bytes, "bits_per_second": 0, "packets": end_packets,
                        "lost_packets": end_lost, "jitter_ms": 0.04, "sender": False}},
    }


class ZeroEndSummaryTests(unittest.TestCase):
    def test_zero_final_summary_uses_valid_intervals(self):
        rep = server_report([interval(0, 1.0, 625_000, 625), interval(1.0, 1.0, 625_000, 625)])
        out = receiver_udp_stats(rep)
        self.assertEqual(out["status"], STATUS_VERIFIED)
        self.assertAlmostEqual(out["receiver_mbps"], 5.0, places=3)  # 625 kB/s
        self.assertEqual(out["received_packets"], 1250)
        self.assertTrue(any("bytes=0" in w for w in out["warnings"]))

    def test_historical_iperf39_report_regression(self):
        if not HISTORICAL.is_file():
            self.skipTest("historical raw file not present")
        out = receiver_udp_stats(json.loads(HISTORICAL.read_text(encoding="utf-8")))
        self.assertEqual(out["status"], STATUS_VERIFIED)
        self.assertEqual(out["received_bytes"], 5_000_400)
        self.assertEqual(out["received_packets"], 4167)
        self.assertEqual(out["lost_packets"], 0)
        self.assertAlmostEqual(out["receiver_mbps"], 4.968, delta=0.01)

    def test_byte_weighted_not_mean_of_rates(self):
        # 1 s at 10 Mb/s then a 0.1 s tail at 1 Mb/s:
        # unweighted mean = 5.5 Mb/s ; byte-weighted = 10.1 Mb / 1.1 s = 9.18 Mb/s
        rep = server_report([interval(0, 1.0, 1_250_000, 1250), interval(1.0, 0.1, 12_500, 12)])
        out = receiver_udp_stats(rep, blksize=1000)
        self.assertAlmostEqual(out["receiver_mbps"], (1_262_500 * 8 / 1.1) / 1e6, places=3)
        self.assertNotAlmostEqual(out["receiver_mbps"], 5.5, places=1)

    def test_loss_and_jitter_from_receiver(self):
        rep = server_report([interval(0, 1.0, 900_000, 900, lost=100)], end_lost=100)
        out = receiver_udp_stats(rep)
        self.assertEqual(out["lost_packets"], 100)
        self.assertAlmostEqual(out["loss_pct"], 10.0)
        self.assertEqual(out["jitter_ms"], 0.04)


class MissingAndMalformedTests(unittest.TestCase):
    def test_all_intervals_zero_bytes_is_zero_received_not_loss(self):
        rep = server_report([interval(0, 1.0, 0, 0), interval(1.0, 1.0, 0, 0)], end_packets=0)
        out = receiver_udp_stats(rep)
        self.assertEqual(out["status"], STATUS_ZERO)
        self.assertIsNone(out["receiver_mbps"])
        self.assertIsNone(out["loss_pct"])

    def test_missing_intervals(self):
        rep = server_report([])
        self.assertEqual(receiver_udp_stats(rep)["status"], STATUS_UNAVAILABLE)
        del rep["intervals"]
        self.assertEqual(receiver_udp_stats(rep)["status"], STATUS_UNAVAILABLE)

    def test_malformed_inputs(self):
        for bad in (None, [], "text", 42):
            self.assertEqual(receiver_udp_stats(bad)["status"], STATUS_INVALID)
        rep = server_report([{"sum": {"seconds": "x", "bytes": None}}, {"nothing": 1}],
                            end_packets=0)
        out = receiver_udp_stats(rep)
        self.assertEqual(out["status"], STATUS_UNAVAILABLE)
        self.assertEqual(out["rejected_intervals"], 2)

    def test_nan_and_negative_values_rejected(self):
        rep = server_report([interval(0, 1.0, 1000, 1), interval(1.0, 1.0, 1000, 1)])
        rep["intervals"][0]["sum"]["bytes"] = float("nan")
        rep["intervals"][1]["sum"]["seconds"] = -1
        self.assertEqual(receiver_udp_stats(rep)["status"], STATUS_UNAVAILABLE)

    def test_error_report(self):
        rep = server_report([interval(0, 1.0, 1000, 1)])
        rep["error"] = "unable to receive"
        self.assertEqual(receiver_udp_stats(rep)["status"], STATUS_INVALID)


class RoleTests(unittest.TestCase):
    def test_client_report_is_never_receiver_evidence(self):
        rep = server_report([interval(0, 1.0, 625_000, 625)])
        client = copy.deepcopy(rep)
        client["start"].pop("accepted_connection")
        client["start"]["connecting_to"] = {"host": "10.42.0.12", "port": 5201}
        self.assertEqual(receiver_udp_stats(client)["status"], STATUS_INVALID)
        client["end"]["sum"].update(bytes=625_000, bits_per_second=5e6, sender=True)
        snd = sender_udp_stats(client)
        self.assertEqual(snd["status"], "sender_only")
        self.assertEqual(snd["sent_mbps"], 5.0)

    def test_sender_flagged_intervals_rejected(self):
        rep = server_report([interval(0, 1.0, 625_000, 625, sender=True)])
        out = receiver_udp_stats(rep)
        self.assertEqual(out["status"], STATUS_UNAVAILABLE)

    def test_reverse_mode_rejected(self):
        rep = server_report([interval(0, 1.0, 625_000, 625)])
        rep["start"]["test_start"]["reverse"] = 1
        self.assertEqual(receiver_udp_stats(rep)["status"], STATUS_INVALID)

    def test_interval_rows_absolute_time(self):
        rep = server_report([interval(0, 1.0, 1000, 1), interval(1.0, 1.0, 2000, 2)])
        rows = receiver_interval_rows(rep)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["abs_start_unix"], 1_000_001.0)
        self.assertEqual(rows[1]["bytes"], 2000)


if __name__ == "__main__":
    unittest.main()
