#!/usr/bin/env python3
"""SmartMall SMALL — one scenario experiment (protocol small_scenario_v2).

HEALTHY -> FAILED (fault/impairment active) -> RECOVERED, fixed-duration windows,
optional background UDP flow PC-SHOP -> SRV-LOCAL that genuinely spans the injection.

Ubuntu / WSL2, project root:
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_FAILURE --target L2 --load-mbps 5 --dry-run
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_FAILURE --target L2 --load-mbps 5
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_DELAY --target L5 --added-delay-ms 20
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_BANDWIDTH --target L5 --bw-mbps 10 --queue-pkts 100 --load-mbps 40
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type NODE_FAILURE --target SW-COM
    sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type SWITCH_BLACKHOLE --target DSW-1

Output: data/raw/small_v1/<experiment_id>/ (new folder; never overwrites)
  icmp_probes.csv        concurrent ICMP probes per window          (telemetry, no labels)
  port_samples.csv       cumulative interface counters/states       (telemetry, no labels)
  port_window_deltas.csv per-window counter deltas (derived from port_samples.csv)
  tc_samples.csv         qdisc counters + configured tc params      (configured params = leakage!)
  receiver_intervals.csv iperf3 server per-interval receiver data   (telemetry)
  traffic/               raw iperf3 client/server JSON per flow segment
  incident.json          GROUND TRUTH: scenario, phases, timings, expectations, status
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "topologies" / "small.json"
RAW_ROOT = ROOT / "data" / "raw" / "small_v1"
sys.path.insert(0, str(ROOT / "src"))

from smartmall import scenarios as S  # noqa: E402
from smartmall import telemetry as T  # noqa: E402
from smartmall import topology as topo  # noqa: E402
from smartmall.iperf_receiver import receiver_interval_rows, receiver_udp_stats, sender_udp_stats  # noqa: E402

FLOW_SOURCE, FLOW_TARGET = "PC-SHOP", "SRV-LOCAL"
PAYLOAD = 1200
ICMP_FIELDS = ["experiment_id", "window_id", "source_node_id", "target_node_id",
               "probe_start_utc", "probe_end_utc", "packets_sent", "packets_received",
               "loss_pct", "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms",
               "icmp_errors", "reachable", "probe_status"]
PORT_FIELDS = ["experiment_id", "window_id", "sample_position", "sample_time_utc",
               "sample_unix", "link_id", "node_id", "peer_node_id", "interface_name",
               "admin_up", "carrier", "operstate"] + list(T.COUNTERS)
DELTA_FIELDS = ["experiment_id", "window_id", "link_id", "node_id", "peer_node_id",
                "interface_name", "duration_s", "admin_up_before", "admin_up_after",
                "carrier_before", "carrier_after", "operstate_after"] + \
               [c + "_delta" for c in T.COUNTERS] + ["counter_reset", "rx_mbps", "tx_mbps"]
TC_FIELDS = ["experiment_id", "window_id", "sample_position", "sample_unix", "link_id",
             "node_id", "interface_name", "cfg_rate_mbps", "cfg_delay_ms", "cfg_loss_pct",
             "cfg_limit_pkts", "htb_sent_pkts", "htb_dropped", "htb_overlimits",
             "netem_sent_pkts", "netem_dropped", "netem_backlog_pkts"]
RX_FIELDS = ["experiment_id", "segment_id", "interval_index", "rel_start_s", "rel_end_s",
             "abs_start_unix", "abs_end_unix", "seconds", "bytes", "packets",
             "lost_packets", "jitter_ms", "omitted"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    files = [SPEC_PATH, Path(__file__)]
    files += sorted((ROOT / "src" / "smartmall").glob("*.py"))
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in files}


# --------------------------------------------------------------------------- Mininet layer
class Lab:
    """Mininet SMALL instance with interface map, sampling and fault primitives."""

    def __init__(self, spec):
        from mininet.link import TCLink
        from mininet.net import Mininet
        from mininet.node import OVSBridge
        from smartmall.emulation import SmartMallSmall, map_interfaces
        self.spec = spec
        self.links = topo.links_by_id(spec)
        self.topo = SmartMallSmall(spec=spec)
        self.names = self.topo.component_to_mininet
        self.net = Mininet(topo=self.topo, controller=None, switch=OVSBridge, link=TCLink)
        self._map_interfaces = map_interfaces
        self.port_map = []
        self.intf_obj = {}

    def start(self):
        self.net.start()
        self.port_map = self._map_interfaces(self.net, self.spec, self.names)
        if len(self.port_map) != 2 * len(self.spec["links"]):
            raise RuntimeError("Interface map incomplete")
        for link in self.net.links:
            for intf in (link.intf1, link.intf2):
                self.intf_obj[intf.name] = intf

    def stop(self):
        self.net.stop()

    def node(self, component_id):
        return self.net.get(self.names[component_id])

    # ---------------- sampling
    def read_ports(self):
        """All 12 interfaces; one `ip -j -s link` per namespace (switches share root ns)."""
        by_node = {}
        for port in self.port_map:
            by_node.setdefault(port["node_name"], []).append(port)
        rows = {}
        root_cache = None
        for node_name, ports in by_node.items():
            node = self.net.get(node_name)
            is_switch = node_name.startswith("s")
            if is_switch and root_cache is not None:
                data, stamp = root_cache
            else:
                stamp = time.time()
                data = {e["ifname"]: e for e in json.loads(node.cmd("ip -j -s link show"))}
                if is_switch:
                    root_cache = (data, stamp)
            for port in ports:
                entry = data.get(port["interface_name"])
                if entry is None:
                    raise RuntimeError(f"Interface {port['interface_name']} not found")
                stats = entry.get("stats64") or entry.get("stats")
                flags = entry.get("flags", [])
                rows[port["interface_name"]] = {
                    "sample_unix": stamp,
                    "admin_up": int("UP" in flags),
                    "carrier": int("NO-CARRIER" not in flags and "UP" in flags),
                    "operstate": entry.get("operstate", "UNKNOWN"),
                    "rx_bytes": stats["rx"]["bytes"], "rx_packets": stats["rx"]["packets"],
                    "rx_errors": stats["rx"]["errors"], "rx_dropped": stats["rx"]["dropped"],
                    "tx_bytes": stats["tx"]["bytes"], "tx_packets": stats["tx"]["packets"],
                    "tx_errors": stats["tx"]["errors"], "tx_dropped": stats["tx"]["dropped"],
                }
        return rows

    def read_tc(self):
        out = {}
        for port in self.port_map:
            node = self.net.get(port["node_name"])
            name = port["interface_name"]
            q = T.parse_tc_qdisc(node.cmd(f"tc -s qdisc show dev {name}"))
            rate = T.parse_tc_class_rate_mbps(node.cmd(f"tc class show dev {name}"))
            htb = next((x for x in q if x["kind"] == "htb"), {})
            netem = next((x for x in q if x["kind"] == "netem"), {})
            out[name] = {
                "sample_unix": time.time(), "cfg_rate_mbps": rate,
                "cfg_delay_ms": netem.get("delay_ms"), "cfg_loss_pct": netem.get("loss_pct"),
                "cfg_limit_pkts": netem.get("limit"),
                "htb_sent_pkts": htb.get("sent_pkts"), "htb_dropped": htb.get("dropped"),
                "htb_overlimits": htb.get("overlimits"),
                "netem_sent_pkts": netem.get("sent_pkts"), "netem_dropped": netem.get("dropped"),
                "netem_backlog_pkts": netem.get("backlog_pkts"),
            }
        return out

    def tc_config_signature(self):
        tc = self.read_tc()
        return {k: (v["cfg_rate_mbps"], v["cfg_delay_ms"], v["cfg_loss_pct"], v["cfg_limit_pkts"])
                for k, v in tc.items()}

    def link_interfaces(self, link_id):
        return [p for p in self.port_map if p["link_id"] == link_id]

    def concurrent_probes(self, pairs, packets, interval, wait):
        procs = []
        for src, dst in pairs:
            h_src, h_dst = self.node(src), self.node(dst)
            start = time.time()
            proc = h_src.popen(["ping", "-n", "-c", str(packets), "-i", str(interval),
                                "-W", str(wait), h_dst.IP()],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            procs.append((src, dst, start, proc))
        results = []
        for src, dst, start, proc in procs:
            try:
                out, _ = proc.communicate(timeout=packets * interval + wait + 10)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
            end = time.time()
            parsed = T.parse_ping(out.decode(errors="replace"))
            results.append({"source_node_id": src, "target_node_id": dst,
                            "probe_start_utc": iso(start), "probe_end_utc": iso(end), **parsed})
        return results


# --------------------------------------------------------------------------- fault injectors
class Injector:
    """Applies and reverts one validated scenario; returns verification evidence."""

    def __init__(self, lab, scenario):
        self.lab = lab
        self.sc = scenario
        self.active = False
        self.evidence = {}

    def _link_ends(self):
        link = self.lab.links[self.sc["target"]]
        return self.lab.names[link["source"]], self.lab.names[link["target"]], link

    def _config_link(self, link, **kw):
        for port in self.lab.link_interfaces(link["id"]):
            self.lab.intf_obj[port["interface_name"]].config(**kw)

    def _baseline_kwargs(self, link):
        return {"bw": float(link["bandwidth_mbps"]), "delay": f"{float(link['delay_ms']):g}ms"}

    def inject(self):
        ft, target, p = self.sc["fault_type"], self.sc["target"], self.sc["params"]
        if ft == "NONE":
            pass
        elif ft == "LINK_FAILURE":
            a, b, _ = self._link_ends()
            self.lab.net.configLinkStatus(a, b, "down")
        elif ft in ("LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH"):
            _, _, link = self._link_ends()
            kw = self._baseline_kwargs(link)
            if ft == "LINK_DELAY":
                kw["delay"] = f"{float(link['delay_ms']) + p['added_delay_ms']:g}ms"
            elif ft == "LINK_LOSS":
                kw["loss"] = p["loss_pct"]
            else:
                kw["bw"] = p["bw_mbps"]
                kw["max_queue_size"] = p["queue_pkts"]
            self._config_link(link, **kw)
        elif ft == "NODE_FAILURE":
            for port in self.lab.port_map:
                if port["node_id"] == target:
                    self.lab.intf_obj[port["interface_name"]].ifconfig("down")
        elif ft == "SWITCH_BLACKHOLE":
            br = self.lab.names[target]
            self.lab.net.get(br).cmd(f"ovs-vsctl set-fail-mode {br} secure")
            self.lab.net.get(br).cmd(f"ovs-ofctl del-flows {br}")
        self.active = ft != "NONE"
        self.applied_unix = time.time()          # mechanism applied (before verification)
        self.evidence["after_inject"] = self.verify_state()

    def restore(self):
        ft, target = self.sc["fault_type"], self.sc["target"]
        if ft == "LINK_FAILURE":
            a, b, _ = self._link_ends()
            self.lab.net.configLinkStatus(a, b, "up")
        elif ft in ("LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH"):
            _, _, link = self._link_ends()
            self._config_link(link, **self._baseline_kwargs(link))
        elif ft == "NODE_FAILURE":
            for port in self.lab.port_map:
                if port["node_id"] == target:
                    self.lab.intf_obj[port["interface_name"]].ifconfig("up")
        elif ft == "SWITCH_BLACKHOLE":
            br = self.lab.names[target]
            self.lab.net.get(br).cmd(f"ovs-vsctl set-fail-mode {br} standalone")
        self.active = False
        self.reverted_unix = time.time()
        self.evidence["after_restore"] = self.verify_state()

    def verify_state(self):
        """Direct evidence that the mechanism is (not) in effect."""
        ft, target = self.sc["fault_type"], self.sc["target"]
        ev = {"time_utc": utc_now()}
        if ft in ("LINK_FAILURE", "LINK_DELAY", "LINK_LOSS", "LINK_BANDWIDTH"):
            names = [p["interface_name"] for p in self.lab.link_interfaces(target)]
        elif ft in ("NODE_FAILURE", "SWITCH_BLACKHOLE"):
            names = [p["interface_name"] for p in self.lab.port_map
                     if target in (p["node_id"], p["peer_node_id"])]
        else:
            names = []
        if names:
            ports = self.lab.read_ports()
            tc = self.lab.read_tc()
            ev["interfaces"] = {n: {"admin_up": ports[n]["admin_up"], "carrier": ports[n]["carrier"],
                                    "operstate": ports[n]["operstate"],
                                    "rate_mbps": tc[n]["cfg_rate_mbps"],
                                    "delay_ms": tc[n]["cfg_delay_ms"],
                                    "loss_pct": tc[n]["cfg_loss_pct"],
                                    "limit_pkts": tc[n]["cfg_limit_pkts"]} for n in names}
        if ft == "SWITCH_BLACKHOLE":
            br = self.lab.names[target]
            sw = self.lab.net.get(br)
            ev["fail_mode"] = sw.cmd(f"ovs-vsctl get-fail-mode {br}").strip()
            flows = [l for l in sw.cmd(f"ovs-ofctl dump-flows {br}").splitlines()
                     if "actions=" in l]
            ev["flow_count"] = len(flows)
        return ev


# --------------------------------------------------------------------------- traffic
class FlowSegment:
    def __init__(self, lab, seg_id, rate_mbps, duration_s, port, out_dir):
        self.lab, self.seg_id, self.rate, self.duration = lab, seg_id, rate_mbps, duration_s
        self.port, self.out_dir = port, out_dir
        self.server = self.client = None
        self.meta = {"segment_id": seg_id, "offered_mbps": rate_mbps, "duration_s": duration_s,
                     "port": port}

    def start(self):
        snd, rcv = self.lab.node(FLOW_SOURCE), self.lab.node(FLOW_TARGET)
        self.server = rcv.popen(["iperf3", "-s", "-1", "-J", "-i", "0.5", "-p", str(self.port)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.4)
        if self.server.poll() is not None:
            raise RuntimeError(f"iperf3 server for {self.seg_id} exited early")
        stat = f"/sys/class/net/{rcv.defaultIntf().name}/statistics/rx_packets"
        rx0 = int(rcv.cmd(f"cat {stat}").strip() or 0)
        self.meta["client_launch_unix"] = time.time()
        self.client = snd.popen(["iperf3", "-c", rcv.IP(), "-u", "-b", f"{self.rate}M",
                                 "-l", str(PAYLOAD), "-t", str(self.duration), "-i", "0.5",
                                 "-p", str(self.port), "-J", "--connect-timeout", "2000"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Measure the alignment base: first burst of datagrams at the receiver NIC.
        # (iperf3 JSON only carries integer-second timestamps.)
        threshold = 15          # > TCP control-channel handshake packets
        deadline = time.time() + 3.0
        while time.time() < deadline:
            now_rx = int(rcv.cmd(f"cat {stat}").strip() or 0)
            if now_rx - rx0 >= threshold:
                self.meta["first_data_unix"] = time.time()
                break
        self.meta["alignment_probe"] = {"method": "receiver NIC rx_packets polling",
                                        "threshold_packets": threshold,
                                        "detected": "first_data_unix" in self.meta}

    def client_alive(self):
        return self.client is not None and self.client.poll() is None

    def finish(self):
        meta = self.meta
        try:
            cout, cerr = self.client.communicate(timeout=self.duration + 30)
        except subprocess.TimeoutExpired:
            self.client.kill()
            cout, cerr = self.client.communicate()
            meta["client_killed"] = True
        meta["client_exit_unix"] = meta.get("client_exit_unix") or time.time()
        meta["client_rc"] = self.client.returncode
        try:
            sout, serr = self.server.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.server.kill()
            sout, serr = self.server.communicate()
            meta["server_killed"] = True
        meta["server_rc"] = self.server.returncode
        client_json, server_json = self._json(cout), self._json(sout)
        (self.out_dir / f"iperf3_client_{self.seg_id}.json").write_text(
            json.dumps(client_json if client_json is not None else
                       {"unparsed_stdout": cout.decode(errors="replace")[-4000:]}, indent=1) + "\n",
            encoding="utf-8")
        (self.out_dir / f"iperf3_server_{self.seg_id}.json").write_text(
            json.dumps(server_json if server_json is not None else
                       {"unparsed_stdout": sout.decode(errors="replace")[-4000:]}, indent=1) + "\n",
            encoding="utf-8")
        meta["client_stderr_tail"] = cerr.decode(errors="replace")[-300:]
        meta["client_error"] = (client_json or {}).get("error")
        meta["server_error"] = (server_json or {}).get("error")
        meta["sender"] = sender_udp_stats(client_json) if client_json else {"status": "unavailable"}
        clean = {k: v for k, v in (server_json or {}).items() if k != "error"}
        rec = receiver_udp_stats(clean) if server_json else {"status": "unavailable"}
        meta["receiver"] = {k: rec.get(k) for k in ("status", "reason", "receiver_mbps",
                                                     "received_packets", "lost_packets",
                                                     "loss_pct", "measured_seconds", "warnings")}
        rows = receiver_interval_rows(clean) if server_json else []
        # Align server-relative times: server test start ~= first data arrival at the NIC
        # (minus the polling granularity, ~10 ms per namespace command).
        base = meta.get("first_data_unix") or meta["client_launch_unix"]
        meta["alignment_base_unix"] = base
        meta["alignment"] = ("first_data_unix (NIC polling, ~0.01-0.03 s granularity)"
                             if "first_data_unix" in meta else
                             "client_launch_unix fallback (+0.1-0.2 s setup uncertainty)")
        for row in rows:
            row["abs_start_unix"] = base + row["rel_start_s"] if row["rel_start_s"] is not None else None
            row["abs_end_unix"] = base + row["rel_end_s"] if row["rel_end_s"] is not None else None
        return rows

    @staticmethod
    def _json(raw):
        try:
            return json.loads(raw.decode("utf-8")) if raw.strip() else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def kill(self):
        for proc in (self.client, self.server):
            if proc is not None and proc.poll() is None:
                proc.kill()


# --------------------------------------------------------------------------- experiment
class Experiment:
    def __init__(self, args, spec, scenario):
        self.args, self.spec, self.sc = args, spec, scenario
        self.exp_id = ("scn_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                       + "_" + uuid.uuid4().hex[:6])
        self.folder = Path(args.raw_root) / self.exp_id
        self.pairs = topo.host_pairs(spec)
        self.window_counter = 0
        self.receiver_rows = []
        self.windows = []

    def run(self):
        args = self.args
        self.folder.mkdir(parents=True, exist_ok=False)
        (self.folder / "traffic").mkdir()
        (self.folder / "topology.json").write_bytes(SPEC_PATH.read_bytes())
        gt = {
            "experiment_id": self.exp_id, "protocol_version": S.PROTOCOL_VERSION,
            "topology_id": self.spec["topology_id"], "campaign_id": args.campaign_id,
            "repetition": args.repetition, "seed": args.seed, "status": "running",
            "started_at_utc": utc_now(),
            "scenario": self.sc,
            "expected": S.expected_effects(self.spec, self.sc),
            "traffic": {"offered_mbps": args.load_mbps, "flow_source": FLOW_SOURCE,
                        "flow_target": FLOW_TARGET, "payload_bytes": PAYLOAD,
                        "flow_relation": S.flow_affected(self.spec, self.sc, FLOW_SOURCE, FLOW_TARGET),
                        "segments": []},
            "protocol": {"rounds_per_phase": args.rounds, "window_s": args.window_s,
                         "icmp_packets": args.packets, "icmp_interval_s": args.ping_interval,
                         "icmp_wait_s": args.ping_wait, "probe_pairs": [list(p) for p in self.pairs],
                         "probe_mode": "concurrent (all pairs launched together each window)",
                         "switch_mode": "OVSBridge standalone", "warmup_s": args.warmup_s,
                         "settle_s": args.settle_s},
            "injected_at_utc": None, "restored_at_utc": None, "recovery": None,
            "injector_evidence": {}, "cleanup": {}, "windows": [],
            "source_sha256": source_hashes(),
            "tool_versions": {"iperf3": subprocess.run(["iperf3", "--version"], capture_output=True,
                                                       text=True).stdout.splitlines()[0],
                              "python": sys.version.split()[0]},
            "leakage_notes": [
                "admin_up/carrier/operstate directly reveal admin-down mechanisms (LINK_FAILURE, NODE_FAILURE)",
                "tc_samples cfg_* columns are CONFIGURATION, i.e. ground truth for impairments; never model inputs",
                "window_id order encodes phase order; experiment_id/timestamps are identifiers, not features",
            ],
        }
        self.gt = gt
        print(f"Experiment {self.exp_id}: {self.sc['fault_type']} {self.sc['target'] or ''} "
              f"{self.sc['params'] or ''} load={args.load_mbps} Mb/s", flush=True)
        lab = Lab(self.spec)
        injector = Injector(lab, self.sc)
        segment = None
        started = False
        files = {}
        try:
            files = self._open_files()
            lab.start()
            started = True
            self.baseline_tc = lab.tc_config_signature()
            if lab.net.pingAll() != 0:
                raise RuntimeError("Baseline pingAll not fully connected")
            port_base = 5500 + (args.seed % 200) * 2

            # ---- segment 1: spans HEALTHY + FAILED
            if args.load_mbps > 0:
                # Generous: sampling overhead lengthens windows; coverage is audited afterwards.
                dur = int(round(args.warmup_s + 2 * args.rounds * (args.window_s + 1.0)
                                + args.settle_s + 4))
                segment = FlowSegment(lab, "seg1", args.load_mbps, dur, port_base, self.folder / "traffic")
                segment.start()
                time.sleep(args.warmup_s)
            self._phase(lab, files, "healthy", segment)
            t_inj = time.time()
            injector.inject()
            gt["injected_at_utc"] = iso(injector.applied_unix)
            gt["injected_at_unix"] = round(injector.applied_unix, 4)
            gt["inject_call_started_unix"] = round(t_inj, 4)
            gt["injector_evidence"]["after_inject"] = injector.evidence["after_inject"]
            time.sleep(args.settle_s)
            self._phase(lab, files, "failed", segment)
            injector.restore()
            gt["restored_at_utc"] = iso(injector.reverted_unix)
            gt["restored_at_unix"] = round(injector.reverted_unix, 4)
            gt["injector_evidence"]["after_restore"] = injector.evidence["after_restore"]
            if segment is not None:
                self._close_segment(segment, files)
                segment = None
            gt["recovery"] = self._await_recovery(lab)
            if not gt["recovery"]["all_pairs_reachable"]:
                raise RuntimeError("Network did not recover within the recovery timeout")

            # ---- segment 2: RECOVERED
            if args.load_mbps > 0:
                dur = int(round(args.warmup_s + args.rounds * (args.window_s + 1.0) + 3))
                segment = FlowSegment(lab, "seg2", args.load_mbps, dur, port_base + 1,
                                      self.folder / "traffic")
                segment.start()
                time.sleep(args.warmup_s)
            self._phase(lab, files, "recovered", segment)
            if segment is not None:
                self._close_segment(segment, files)
                segment = None
            gt["cleanup"]["tc_restored_to_baseline"] = lab.tc_config_signature() == self.baseline_tc
            ports = lab.read_ports()
            gt["cleanup"]["all_ports_admin_up_with_carrier"] = all(
                v["admin_up"] == 1 and v["carrier"] == 1 for v in ports.values())
            if not gt["cleanup"]["tc_restored_to_baseline"]:
                raise RuntimeError("tc configuration not restored to baseline")
            if not gt["cleanup"]["all_ports_admin_up_with_carrier"]:
                raise RuntimeError("Some interfaces not restored")
            gt["status"] = "completed"
        except Exception as exc:
            gt["status"] = "failed"
            gt["error"] = f"{type(exc).__name__}: {exc}"
            print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr, flush=True)
            raise
        finally:
            if segment is not None:
                segment.kill()
            if injector.active and started:
                try:
                    injector.restore()
                    gt["cleanup"]["emergency_restore"] = True
                except Exception as exc:  # pragma: no cover
                    gt["cleanup"]["emergency_restore_error"] = str(exc)
            for handle in files.values():
                handle.close()
            if started:
                lab.stop()
            gt["cleanup"]["ovs_bridges_after_stop"] = subprocess.run(
                ["ovs-vsctl", "list-br"], capture_output=True, text=True).stdout.split()
            gt["windows"] = self.windows
            gt["finished_at_utc"] = utc_now()
            (self.folder / "incident.json").write_text(
                json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Saved: {self.folder} [{gt['status']}]", flush=True)
        return self.folder

    # ---------------- helpers
    def _open_files(self):
        spec = {"icmp": ("icmp_probes.csv", ICMP_FIELDS), "port": ("port_samples.csv", PORT_FIELDS),
                "delta": ("port_window_deltas.csv", DELTA_FIELDS), "tc": ("tc_samples.csv", TC_FIELDS),
                "rx": ("receiver_intervals.csv", RX_FIELDS)}
        handles, self.writers = {}, {}
        for key, (name, fields) in spec.items():
            handles[key] = (self.folder / name).open("w", newline="", encoding="utf-8")
            self.writers[key] = csv.DictWriter(handles[key], fieldnames=fields)
            self.writers[key].writeheader()
        return handles

    def _close_segment(self, segment, files):
        rows = segment.finish()
        for row in rows:
            self.writers["rx"].writerow({"experiment_id": self.exp_id, "segment_id": segment.seg_id,
                                         **{k: row.get(k) for k in RX_FIELDS if k in row}})
        files["rx"].flush()
        self.receiver_rows += [dict(r, segment_id=segment.seg_id) for r in rows]
        self.gt["traffic"]["segments"].append(segment.meta)
        print(f"  flow {segment.seg_id}: client rc={segment.meta['client_rc']} "
              f"receiver={segment.meta['receiver']['status']} "
              f"{segment.meta['receiver'].get('receiver_mbps')} Mb/s "
              f"lost={segment.meta['receiver'].get('lost_packets')}", flush=True)

    def _phase(self, lab, files, phase, segment):
        for _ in range(self.args.rounds):
            self.window_counter += 1
            wid = f"w{self.window_counter:02d}"
            t0 = time.time()
            ports_before = lab.read_ports()
            tc_before = lab.read_tc()
            probes = lab.concurrent_probes(self.pairs, self.args.packets, self.args.ping_interval,
                                           self.args.ping_wait)
            remaining = self.args.window_s - (time.time() - t0)
            if remaining > 0:
                time.sleep(remaining)
            ports_after = lab.read_ports()
            tc_after = lab.read_tc()
            t1 = time.time()
            for probe in probes:
                self.writers["icmp"].writerow({"experiment_id": self.exp_id, "window_id": wid, **probe})
            for pos, snapshot, tcs in (("before", ports_before, tc_before), ("after", ports_after, tc_after)):
                for port in lab.port_map:
                    v = snapshot[port["interface_name"]]
                    self.writers["port"].writerow({
                        "experiment_id": self.exp_id, "window_id": wid, "sample_position": pos,
                        "sample_time_utc": iso(v["sample_unix"]), "sample_unix": round(v["sample_unix"], 4),
                        "link_id": port["link_id"], "node_id": port["node_id"],
                        "peer_node_id": port["peer_node_id"], "interface_name": port["interface_name"],
                        **{k: v[k] for k in ("admin_up", "carrier", "operstate") + T.COUNTERS}})
                    t = tcs[port["interface_name"]]
                    self.writers["tc"].writerow({
                        "experiment_id": self.exp_id, "window_id": wid, "sample_position": pos,
                        "sample_unix": round(t["sample_unix"], 4), "link_id": port["link_id"],
                        "node_id": port["node_id"], "interface_name": port["interface_name"],
                        **{k: t[k] for k in TC_FIELDS[7:]}})
            for port in lab.port_map:
                b, a = ports_before[port["interface_name"]], ports_after[port["interface_name"]]
                dur = a["sample_unix"] - b["sample_unix"]
                self.writers["delta"].writerow({
                    "experiment_id": self.exp_id, "window_id": wid, "link_id": port["link_id"],
                    "node_id": port["node_id"], "peer_node_id": port["peer_node_id"],
                    "interface_name": port["interface_name"], "duration_s": round(dur, 4),
                    "admin_up_before": b["admin_up"], "admin_up_after": a["admin_up"],
                    "carrier_before": b["carrier"], "carrier_after": a["carrier"],
                    "operstate_after": a["operstate"], **T.counter_deltas(b, a, dur)})
            for handle in files.values():
                handle.flush()
            flow_state = None
            if segment is not None:
                flow_state = {"segment_id": segment.seg_id, "client_alive_at_window_end": segment.client_alive()}
            self.windows.append({"window_id": wid, "phase": phase, "start_unix": round(t0, 4),
                                 "end_unix": round(t1, 4), "start_utc": iso(t0), "end_utc": iso(t1),
                                 "flow": flow_state})
            unreach = sum(1 for p in probes if p["reachable"] == 0)
            route = sum(1 for p in probes if p["probe_status"] == "route_unreachable")
            rtts = [p["rtt_avg_ms"] for p in probes if p["rtt_avg_ms"] != ""]
            mean_rtt = round(sum(rtts) / len(rtts), 2) if rtts else None
            print(f"  {wid} {phase:9s} unreachable={unreach} route_unreachable={route} "
                  f"mean_rtt={mean_rtt} ms dur={t1 - t0:.2f}s"
                  + (f" flow_alive={flow_state['client_alive_at_window_end']}" if flow_state else ""),
                  flush=True)

    def _await_recovery(self, lab):
        t_restore = time.time()
        for attempt in range(1, 11):
            time.sleep(self.args.settle_s)
            probes = lab.concurrent_probes(self.pairs, 1, 0.2, 1)
            ok = all(p["reachable"] == 1 for p in probes)
            if ok:
                return {"all_pairs_reachable": True, "attempts": attempt,
                        "seconds_after_restore": round(time.time() - t_restore, 3)}
        return {"all_pairs_reachable": False, "attempts": 10,
                "seconds_after_restore": round(time.time() - t_restore, 3)}


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fault-type", required=True, choices=sorted(S.FAULT_FAMILIES))
    p.add_argument("--target", default=None, help="Link ID or node ID")
    p.add_argument("--added-delay-ms", type=float, default=None)
    p.add_argument("--loss-pct", type=float, default=None)
    p.add_argument("--bw-mbps", type=float, default=None)
    p.add_argument("--queue-pkts", type=int, default=None)
    p.add_argument("--load-mbps", type=int, default=0, choices=range(0, 81), metavar="0..80")
    p.add_argument("--rounds", type=int, default=3, help="Windows per phase (default 3)")
    p.add_argument("--window-s", type=float, default=4.0, help="Window duration (default 4 s)")
    p.add_argument("--packets", type=int, default=3, help="ICMP requests per probe (default 3)")
    p.add_argument("--ping-interval", type=float, default=0.2)
    p.add_argument("--ping-wait", type=float, default=2.0)
    p.add_argument("--warmup-s", type=float, default=2.0)
    p.add_argument("--settle-s", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=0, help="Recorded for lineage; sets iperf3 port block")
    p.add_argument("--campaign-id", default=None)
    p.add_argument("--repetition", type=int, default=None)
    p.add_argument("--raw-root", default=str(RAW_ROOT),
                   help="Output root for the experiment folder (default data/raw/small_v1; "
                        "use a temporary directory for smoke tests)")
    p.add_argument("--dry-run", action="store_true")
    return p


def scenario_from_args(spec, args):
    params = {}
    if args.added_delay_ms is not None:
        params["added_delay_ms"] = args.added_delay_ms
    if args.loss_pct is not None:
        params["loss_pct"] = args.loss_pct
    if args.bw_mbps is not None:
        params["bw_mbps"] = args.bw_mbps
    if args.queue_pkts is not None:
        params["queue_pkts"] = args.queue_pkts
    return S.validate_scenario(spec, args.fault_type, args.target, params)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10 or not 2.5 <= args.window_s <= 30 or not 1 <= args.packets <= 20:
        parser.error("rounds 1..10, window-s 2.5..30, packets 1..20")
    if args.packets * args.ping_interval + args.ping_wait + 0.5 > args.window_s:
        parser.error("ICMP probe duration would exceed the window")
    spec = topo.load_spec(SPEC_PATH)
    try:
        scenario = scenario_from_args(spec, args)
    except ValueError as exc:
        parser.error(str(exc))
    plan = {"scenario": scenario, "load_mbps": args.load_mbps,
            "expected": S.expected_effects(spec, scenario),
            "flow_relation": S.flow_affected(spec, scenario, FLOW_SOURCE, FLOW_TARGET),
            "windows": 3 * args.rounds,
            "approx_duration_s": round(25 + 3 * args.rounds * args.window_s + 3 * args.warmup_s, 1)}
    print(json.dumps(plan, indent=1))
    if args.dry_run:
        print("DRY RUN: no Mininet, no files")
        return
    from mininet.log import setLogLevel
    setLogLevel("error")
    Experiment(args, spec, scenario).run()


if __name__ == "__main__":
    main()
