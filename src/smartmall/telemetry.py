"""Telemetry parsing and derivation helpers (pure Python, no Mininet)."""

from __future__ import annotations

import re

COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
            "rx_errors", "tx_errors", "rx_dropped", "tx_dropped")

LOCAL_ROUTE_ERRORS = ("Network is unreachable", "Network is down", "No route to host")
_COUNTS = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
_LOSS = re.compile(r"(\d+(?:\.\d+)?)% packet loss")
_RTT = re.compile(r"rtt min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")
_SEND_ERR = re.compile(r"\+(\d+) errors")


def parse_ping(output):
    """Parse iputils ping output.

    probe_status:
      * ``icmp_stats``        ICMP requests were transmitted; loss_pct is defined.
      * ``route_unreachable`` the kernel refused to send (local interface/route down):
                              packets_sent = 0 and loss_pct is UNDEFINED (empty), never 100 %.
      * ``parse_error``       unrecognised output (kept for auditing, never silently dropped).
    """
    counts = _COUNTS.search(output or "")
    if any(msg in (output or "") for msg in LOCAL_ROUTE_ERRORS) and (
            counts is None or int(counts.group(1)) == 0):
        return {"packets_sent": 0, "packets_received": 0, "loss_pct": "",
                "rtt_min_ms": "", "rtt_avg_ms": "", "rtt_max_ms": "", "rtt_mdev_ms": "",
                "icmp_errors": "", "reachable": 0, "probe_status": "route_unreachable"}
    loss = _LOSS.search(output or "")
    if counts is None or loss is None:
        return {"packets_sent": "", "packets_received": "", "loss_pct": "",
                "rtt_min_ms": "", "rtt_avg_ms": "", "rtt_max_ms": "", "rtt_mdev_ms": "",
                "icmp_errors": "", "reachable": "", "probe_status": "parse_error"}
    sent, received = int(counts.group(1)), int(counts.group(2))
    rtt = _RTT.search(output)
    errs = _SEND_ERR.search(output)
    out = {"packets_sent": sent, "packets_received": received,
           "loss_pct": float(loss.group(1)),
           "rtt_min_ms": "", "rtt_avg_ms": "", "rtt_max_ms": "", "rtt_mdev_ms": "",
           "icmp_errors": int(errs.group(1)) if errs else 0,
           "reachable": int(received > 0), "probe_status": "icmp_stats"}
    if rtt and received > 0:
        out.update(rtt_min_ms=float(rtt.group(1)), rtt_avg_ms=float(rtt.group(2)),
                   rtt_max_ms=float(rtt.group(3)), rtt_mdev_ms=float(rtt.group(4)))
    return out


def counter_deltas(before, after, duration_s):
    """Per-window counter deltas. A decrease is flagged as a reset, never clipped silently."""
    out = {}
    reset = False
    for field in COUNTERS:
        try:
            diff = int(after[field]) - int(before[field])
        except (KeyError, TypeError, ValueError):
            out[field + "_delta"] = ""
            continue
        if diff < 0:
            reset = True
            out[field + "_delta"] = ""
        else:
            out[field + "_delta"] = diff
    out["counter_reset"] = int(reset)
    if not reset and duration_s and duration_s > 0 and out["rx_bytes_delta"] != "" \
            and out["tx_bytes_delta"] != "":
        out["rx_mbps"] = round(out["rx_bytes_delta"] * 8 / duration_s / 1e6, 5)
        out["tx_mbps"] = round(out["tx_bytes_delta"] * 8 / duration_s / 1e6, 5)
    else:
        out["rx_mbps"] = ""
        out["tx_mbps"] = ""
    return out


def window_receiver_bytes(intervals, window_start, window_end):
    """Allocate receiver interval bytes/packets to a window, proportionally to overlap.

    ``intervals``: dicts with abs_start/abs_end (same clock as the window) and
    bytes/packets/lost_packets. Returns covered seconds plus allocated totals.
    """
    covered = 0.0
    nbytes = packets = lost = 0.0
    for row in intervals:
        start, end = row.get("abs_start"), row.get("abs_end")
        if start is None or end is None or end <= start:
            continue
        overlap = min(end, window_end) - max(start, window_start)
        if overlap <= 0:
            continue
        frac = overlap / (end - start)
        covered += overlap
        nbytes += frac * (row.get("bytes") or 0)
        packets += frac * (row.get("packets") or 0)
        lost += frac * (row.get("lost_packets") or 0)
    span = window_end - window_start
    return {
        "covered_s": round(covered, 4),
        "coverage_fraction": round(covered / span, 4) if span > 0 else 0.0,
        "bytes": round(nbytes, 1),
        "packets": round(packets, 2),
        "lost_packets": round(lost, 2),
        "mbps": round(nbytes * 8 / covered / 1e6, 4) if covered > 0 else None,
    }


_QDISC_HEAD = re.compile(r"^qdisc (\S+) (\S+): (?:root|parent (\S+))")
_SENT = re.compile(r"Sent (\d+) bytes (\d+) pkt \(dropped (\d+), overlimits (\d+) requeues (\d+)\)")
_BACKLOG = re.compile(r"backlog (\S+?)b? (\d+)p")
_DELAY = re.compile(r"delay ([\d.]+)(us|ms|s)\b")
_LOSSP = re.compile(r"loss ([\d.]+)%")
_RATE = re.compile(r"rate ([\d.]+)([KMG]?)bit")
_LIMIT = re.compile(r"limit (\d+)")


def _to_ms(value, unit):
    value = float(value)
    return value / 1000 if unit == "us" else value * 1000 if unit == "s" else value


def _to_bytes(text):
    m = re.match(r"([\d.]+)([KMG]?)", text)
    if not m:
        return 0
    mult = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
    return int(float(m.group(1)) * mult)


def parse_tc_qdisc(output):
    """Parse ``tc -s qdisc show dev X`` into qdisc dicts (kind, params, counters)."""
    qdiscs = []
    current = None
    for line in (output or "").splitlines():
        head = _QDISC_HEAD.match(line.strip())
        if head:
            current = {"kind": head.group(1), "handle": head.group(2),
                       "parent": head.group(3) or "root",
                       "delay_ms": None, "loss_pct": None, "limit": None,
                       "sent_bytes": None, "sent_pkts": None, "dropped": None,
                       "overlimits": None, "backlog_bytes": None, "backlog_pkts": None}
            d = _DELAY.search(line)
            if d:
                current["delay_ms"] = _to_ms(d.group(1), d.group(2))
            lp = _LOSSP.search(line)
            if lp:
                current["loss_pct"] = float(lp.group(1))
            lim = _LIMIT.search(line)
            if lim:
                current["limit"] = int(lim.group(1))
            qdiscs.append(current)
            continue
        if current is None:
            continue
        s = _SENT.search(line)
        if s:
            current.update(sent_bytes=int(s.group(1)), sent_pkts=int(s.group(2)),
                           dropped=int(s.group(3)), overlimits=int(s.group(4)))
        b = _BACKLOG.search(line)
        if b:
            current.update(backlog_bytes=_to_bytes(b.group(1)), backlog_pkts=int(b.group(2)))
    return qdiscs


def parse_tc_class_rate_mbps(output):
    """Configured HTB class rate (Mbit/s) from ``tc class show dev X``; None if absent."""
    m = _RATE.search(output or "")
    if not m:
        return None
    mult = {"": 1e-6, "K": 1e-3, "M": 1.0, "G": 1e3}[m.group(2)]
    return round(float(m.group(1)) * mult, 6)
