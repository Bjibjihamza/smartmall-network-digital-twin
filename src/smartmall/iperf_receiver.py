"""Receiver-side iperf3 UDP throughput extraction (Stage A fix).

Root cause of the earlier failure (iperf3 3.9, observed in
``data/raw/small_v1/receiver_verify_*``): the receiver-side (``iperf3 -s -J``)
end-of-test summary ``end.sum`` / ``end.streams[].udp`` reports
``bytes = 0`` and ``bits_per_second = 0`` while ``packets > 0``. The per-interval
receiver reports ``intervals[].sum`` contain the real received byte counts.
The previous parser accepted ``0`` as a valid rate, selected the zero summary
first and aborted the run.

Policy implemented here:

* Only a SERVER-side report (``start.accepted_connection`` present, not
  reverse mode) is accepted as receiver evidence. Client reports are parsed
  separately and are always labelled *sender* values.
* Throughput = total received bytes / total measured seconds over valid,
  non-omitted receiver intervals (byte-weighted, NOT a mean of interval rates).
* An end summary with ``bytes == 0`` but ``packets > 0`` is flagged as an
  inconsistent summary and never used as a rate.
* A report whose intervals all carry zero bytes is ``zero_received``: a real
  observation that nothing arrived, whose CAUSE (disconnection, sender
  failure, loss) must be established elsewhere. It is not packet loss.
"""

from __future__ import annotations

import math

STATUS_VERIFIED = "verified"
STATUS_ZERO = "zero_received"
STATUS_UNAVAILABLE = "unavailable"
STATUS_INVALID = "invalid"


def _num(value):
    """Finite non-negative float, else None (bool is rejected)."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out < 0:
        return None
    return out


def _result(status, reason, **extra):
    base = {
        "status": status,
        "reason": reason,
        "receiver_mbps": None,
        "received_bytes": None,
        "received_packets": None,
        "lost_packets": None,
        "loss_pct": None,
        "jitter_ms": None,
        "measured_seconds": None,
        "valid_intervals": 0,
        "rejected_intervals": 0,
        "source": None,
        "warnings": [],
    }
    base.update(extra)
    return base


def report_role(report):
    """Return 'server', 'client' or 'unknown' from an iperf3 JSON report."""
    start = report.get("start") if isinstance(report, dict) else None
    if not isinstance(start, dict):
        return "unknown"
    if "accepted_connection" in start:
        return "server"
    if "connecting_to" in start:
        return "client"
    return "unknown"


def _interval_record(interval):
    """Pick the receiver-side aggregate of one interval (sum, else 1 stream)."""
    if not isinstance(interval, dict):
        return None
    record = interval.get("sum")
    if isinstance(record, dict):
        return record
    streams = interval.get("streams")
    if isinstance(streams, list) and len(streams) == 1 and isinstance(streams[0], dict):
        return streams[0]
    return None


def receiver_udp_stats(server_report, blksize=None):
    """Extract verified receiver-side UDP statistics from ``iperf3 -s -J`` output.

    Returns a dict with ``status`` in {verified, zero_received, unavailable,
    invalid}. Only ``verified`` carries a positive ``receiver_mbps``.
    """
    if not isinstance(server_report, dict):
        return _result(STATUS_INVALID, "report is not a JSON object")
    if server_report.get("error"):
        return _result(STATUS_INVALID, f"iperf3 error: {server_report['error']}")
    role = report_role(server_report)
    if role != "server":
        return _result(STATUS_INVALID,
                       f"report role is '{role}', receiver evidence requires a server report")
    test_start = (server_report.get("start") or {}).get("test_start") or {}
    if test_start.get("reverse"):
        return _result(STATUS_INVALID, "reverse-mode test: server is the sender")
    if str(test_start.get("protocol", "UDP")).upper() != "UDP":
        return _result(STATUS_INVALID, "not a UDP test")
    if blksize is None:
        blksize = _num(test_start.get("blksize"))

    intervals = server_report.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        return _result(STATUS_UNAVAILABLE, "no receiver intervals in server report")

    warnings = []
    total_bytes = 0.0
    total_seconds = 0.0
    packets = 0.0
    lost = 0.0
    jitters = []
    valid = 0
    rejected = 0
    packets_complete = True
    lost_complete = True
    last_end = None
    for index, interval in enumerate(intervals):
        rec = _interval_record(interval)
        if rec is None:
            rejected += 1
            warnings.append(f"interval {index}: no sum/stream record")
            continue
        if rec.get("sender") is True:
            rejected += 1
            warnings.append(f"interval {index}: flagged sender=True")
            continue
        if rec.get("omitted") is True:
            rejected += 1
            continue
        seconds = _num(rec.get("seconds"))
        nbytes = _num(rec.get("bytes"))
        if seconds is None or seconds <= 0 or nbytes is None:
            rejected += 1
            warnings.append(f"interval {index}: missing/invalid seconds or bytes")
            continue
        start = _num(rec.get("start"))
        if start is not None and last_end is not None and abs(start - last_end) > 0.05:
            warnings.append(f"interval {index}: gap of {start - last_end:.3f}s before interval")
        end = _num(rec.get("end"))
        last_end = end if end is not None else last_end
        valid += 1
        total_bytes += nbytes
        total_seconds += seconds
        pk = _num(rec.get("packets"))
        if pk is None:
            packets_complete = False
        else:
            packets += pk
        lp = _num(rec.get("lost_packets"))
        if lp is None:
            lost_complete = False
        else:
            lost += lp
        jt = _num(rec.get("jitter_ms"))
        if jt is not None and nbytes > 0:
            jitters.append(jt)

    if valid == 0:
        return _result(STATUS_UNAVAILABLE, "no valid receiver intervals",
                       rejected_intervals=rejected, warnings=warnings)

    # Cross-check against the end summary, without ever using a zero summary as a rate.
    end_sum = (server_report.get("end") or {}).get("sum")
    end_packets = end_lost = None
    if isinstance(end_sum, dict):
        end_bytes = _num(end_sum.get("bytes"))
        end_packets = _num(end_sum.get("packets"))
        end_lost = _num(end_sum.get("lost_packets"))
        if end_bytes == 0 and (end_packets or 0) > 0:
            warnings.append(
                "end.sum reports bytes=0 with packets>0 (inconsistent receiver summary; "
                "interval data used)")
        elif end_bytes and total_bytes and abs(end_bytes - total_bytes) / total_bytes > 0.01:
            warnings.append(
                f"end.sum bytes {end_bytes:.0f} differs from interval total {total_bytes:.0f}")
        if end_packets is not None and packets_complete and end_lost is not None:
            # iperf3 end 'packets' counts expected datagrams (received + lost).
            expected_received = end_packets - end_lost
            if abs(expected_received - packets) > max(2, 0.01 * max(packets, 1)):
                warnings.append(
                    f"interval packets {packets:.0f} vs end.sum packets-lost "
                    f"{expected_received:.0f}")
    if blksize and packets_complete and packets > 0:
        if abs(packets * blksize - total_bytes) > blksize:
            warnings.append("received bytes != packets x blksize")

    received_packets = int(packets) if packets_complete else None
    lost_packets = int(lost) if lost_complete else None
    if lost_packets is None and end_lost is not None:
        lost_packets = int(end_lost)
    loss_pct = None
    if received_packets is not None and lost_packets is not None and \
            received_packets + lost_packets > 0:
        loss_pct = round(100.0 * lost_packets / (received_packets + lost_packets), 4)
    jitter = None
    end_jitter = _num(end_sum.get("jitter_ms")) if isinstance(end_sum, dict) else None
    if end_jitter is not None and total_bytes > 0:
        jitter = round(end_jitter, 4)
    elif jitters:
        jitter = round(jitters[-1], 4)

    common = dict(
        received_bytes=int(total_bytes),
        received_packets=received_packets,
        lost_packets=lost_packets,
        loss_pct=loss_pct,
        jitter_ms=jitter,
        measured_seconds=round(total_seconds, 6),
        valid_intervals=valid,
        rejected_intervals=rejected,
        source="server intervals[].sum (byte-weighted)",
        warnings=warnings,
    )
    if total_bytes <= 0:
        return _result(STATUS_ZERO,
                       "receiver intervals present but no bytes received", **common)
    mbps = total_bytes * 8.0 / total_seconds / 1e6
    return _result(STATUS_VERIFIED, "ok", receiver_mbps=round(mbps, 4), **common)


def receiver_interval_rows(server_report):
    """Per-interval receiver rows with absolute UNIX times, for window alignment."""
    if report_role(server_report) != "server":
        return []
    start_secs = _num(((server_report.get("start") or {}).get("timestamp") or {}).get("timesecs"))
    rows = []
    for index, interval in enumerate(server_report.get("intervals") or []):
        rec = _interval_record(interval)
        if rec is None or rec.get("sender") is True:
            continue
        rel_start = _num(rec.get("start"))
        rel_end = _num(rec.get("end"))
        rows.append({
            "interval_index": index,
            "rel_start_s": rel_start,
            "rel_end_s": rel_end,
            "abs_start_unix": (start_secs + rel_start) if None not in (start_secs, rel_start) else None,
            "abs_end_unix": (start_secs + rel_end) if None not in (start_secs, rel_end) else None,
            "seconds": _num(rec.get("seconds")),
            "bytes": _num(rec.get("bytes")),
            "packets": _num(rec.get("packets")),
            "lost_packets": _num(rec.get("lost_packets")),
            "jitter_ms": _num(rec.get("jitter_ms")),
            "omitted": bool(rec.get("omitted", False)),
        })
    return rows


def sender_udp_stats(client_report):
    """Sender-side (client) statistics. These are NEVER receiver evidence."""
    if not isinstance(client_report, dict):
        return {"status": STATUS_INVALID, "reason": "report is not a JSON object"}
    if client_report.get("error"):
        return {"status": STATUS_INVALID, "reason": f"iperf3 error: {client_report['error']}"}
    if report_role(client_report) != "client":
        return {"status": STATUS_INVALID, "reason": "not a client report"}
    end_sum = (client_report.get("end") or {}).get("sum")
    if not isinstance(end_sum, dict):
        return {"status": STATUS_UNAVAILABLE, "reason": "no end.sum in client report"}
    bps = _num(end_sum.get("bits_per_second"))
    return {
        "status": "sender_only",
        "reason": "client-side values describe what was SENT, not received",
        "sent_mbps": round(bps / 1e6, 4) if bps is not None else None,
        "sent_bytes": _num(end_sum.get("bytes")),
        "sent_packets": _num(end_sum.get("packets")),
        "sender_flag": end_sum.get("sender", "absent"),
    }
