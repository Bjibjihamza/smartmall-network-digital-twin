"""Unit tests for topology reachability and telemetry parsing (real tool fixtures)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smartmall import telemetry as T  # noqa: E402
from smartmall import topology as topo  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SPEC = topo.load_spec(ROOT / "topologies" / "small.json")


def fixture(name):
    return (FIX / f"{name}.txt").read_text(encoding="utf-8")


class TopologyTests(unittest.TestCase):
    def test_small_is_expected_tree(self):
        self.assertTrue(topo.is_tree(SPEC))
        self.assertEqual(len(SPEC["nodes"]), 7)
        self.assertEqual(sorted(topo.links_by_id(SPEC)), ["L1", "L2", "L3", "L4", "L5", "L6"])
        self.assertEqual(topo.hosts(SPEC), ["PC-ADM", "PC-SHOP", "POS", "SRV-LOCAL"])
        self.assertEqual(len(topo.host_pairs(SPEC)), 6)

    def test_link_failure_signatures_match_repeatability_report(self):
        counts = {lid: len(topo.disrupted_pairs(SPEC, failed_links=[lid]))
                  for lid in topo.links_by_id(SPEC)}
        # docs/history/small_v1/small_repeatability_report.md: L1/L2 -> 4 pairs/window, L3..L6 -> 3 pairs/window
        self.assertEqual(counts, {"L1": 4, "L2": 4, "L3": 3, "L4": 3, "L5": 3, "L6": 3})
        self.assertEqual(topo.disrupted_pairs(SPEC, failed_links=["L1"]),
                         topo.disrupted_pairs(SPEC, failed_links=["L2"]))

    def test_node_failure_signatures(self):
        dsw = topo.disrupted_pairs(SPEC, failed_nodes=["DSW-1"])
        self.assertEqual(dsw, topo.disrupted_pairs(SPEC, failed_links=["L1"]))
        self.assertEqual(len(topo.disrupted_pairs(SPEC, failed_nodes=["SW-ADM"])), 5)
        self.assertEqual(topo.disrupted_pairs(SPEC, failed_nodes=["PC-ADM"]),
                         topo.disrupted_pairs(SPEC, failed_links=["L3"]))

    def test_flow_path(self):
        self.assertEqual(topo.path_links(SPEC, "PC-SHOP", "SRV-LOCAL"), ["L5", "L2", "L1", "L4"])
        self.assertEqual(topo.incident_links(SPEC, "SW-COM"), ["L2", "L5", "L6"])


class PingTests(unittest.TestCase):
    def test_ok(self):
        out = T.parse_ping(fixture("ping_ok"))
        self.assertEqual(out["probe_status"], "icmp_stats")
        self.assertEqual((out["packets_sent"], out["packets_received"]), (3, 3))
        self.assertEqual(out["loss_pct"], 0.0)
        self.assertAlmostEqual(out["rtt_avg_ms"], 4.272)
        self.assertEqual(out["reachable"], 1)

    def test_total_loss_is_loss(self):
        out = T.parse_ping(fixture("ping_total_loss"))
        self.assertEqual(out["probe_status"], "icmp_stats")
        self.assertEqual(out["loss_pct"], 100.0)
        self.assertEqual(out["rtt_avg_ms"], "")
        self.assertEqual(out["reachable"], 0)

    def test_local_route_failure_is_not_packet_loss(self):
        out = T.parse_ping(fixture("ping_local_down"))
        self.assertEqual(out["probe_status"], "route_unreachable")
        self.assertEqual(out["packets_sent"], 0)
        self.assertEqual(out["loss_pct"], "")

    def test_garbage(self):
        self.assertEqual(T.parse_ping("")["probe_status"], "parse_error")
        self.assertEqual(T.parse_ping(None)["probe_status"], "parse_error")


class CounterTests(unittest.TestCase):
    def test_deltas_and_rate(self):
        before = dict.fromkeys(T.COUNTERS, 100)
        after = dict(before, rx_bytes=100 + 1_250_000, tx_bytes=100)
        out = T.counter_deltas(before, after, 1.0)
        self.assertEqual(out["rx_bytes_delta"], 1_250_000)
        self.assertEqual(out["rx_mbps"], 10.0)
        self.assertEqual(out["counter_reset"], 0)

    def test_reset_detected_not_clipped(self):
        before = dict.fromkeys(T.COUNTERS, 100)
        after = dict(before, rx_bytes=5)
        out = T.counter_deltas(before, after, 1.0)
        self.assertEqual(out["counter_reset"], 1)
        self.assertEqual(out["rx_bytes_delta"], "")
        self.assertEqual(out["rx_mbps"], "")


class WindowAllocationTests(unittest.TestCase):
    def test_partial_overlap(self):
        iv = [{"abs_start": 0, "abs_end": 1, "bytes": 1000, "packets": 10, "lost_packets": 0},
              {"abs_start": 1, "abs_end": 2, "bytes": 2000, "packets": 20, "lost_packets": 2}]
        out = T.window_receiver_bytes(iv, 0.5, 2.0)
        self.assertEqual(out["bytes"], 2500)
        self.assertEqual(out["covered_s"], 1.5)
        self.assertEqual(out["coverage_fraction"], 1.0)
        self.assertEqual(out["lost_packets"], 2)

    def test_no_overlap(self):
        out = T.window_receiver_bytes([{"abs_start": 0, "abs_end": 1, "bytes": 9}], 5, 6)
        self.assertEqual(out["coverage_fraction"], 0.0)
        self.assertIsNone(out["mbps"])


class TcTests(unittest.TestCase):
    def test_baseline(self):
        q = T.parse_tc_qdisc(fixture("tc_qdisc_baseline"))
        self.assertEqual([x["kind"] for x in q], ["htb", "netem"])
        self.assertEqual(q[1]["delay_ms"], 1.0)
        self.assertEqual(q[1]["limit"], 1000)
        self.assertEqual(q[0]["sent_pkts"], 12)
        self.assertEqual(T.parse_tc_class_rate_mbps(fixture("tc_class_baseline")), 100.0)

    def test_bandwidth_and_queue(self):
        q = T.parse_tc_qdisc(fixture("tc_qdisc_bw10"))
        self.assertEqual(q[1]["limit"], 100)
        self.assertEqual(T.parse_tc_class_rate_mbps(fixture("tc_class_bw10")), 10.0)

    def test_delay_loss(self):
        q = T.parse_tc_qdisc(fixture("tc_qdisc_delay_loss"))
        self.assertEqual(q[1]["delay_ms"], 21.0)
        self.assertEqual(q[1]["loss_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
