# SMALL — Stage A: iperf3 UDP receiver verification audit

Scope: background UDP flow PC-SHOP → SRV-LOCAL (path L5 → L2 → L1 → L4), no injected fault.
Tool: iperf3 3.9 (Ubuntu 22.04 / WSL2), 1200-byte datagrams, 10 s per profile.

## Root cause of the earlier failures

The three historical runs `receiver_verify_20261125T143400Z_8a5a05`, `..._144728Z_9d7e8e`, and
`..._144957Z_737f8b` all aborted with `Receiver got zero UDP throughput for udp_5mbps`. The 40 Mbps
profile never ran.

- In iperf3 3.9, the receiver (server, `-s -J`) end summary `end.sum` and `end.streams[0].udp` report
  `bytes = 0` and `bits_per_second = 0`, while `packets = 4167` and `sender = false`.
- The server's 9 `intervals[].sum` records add up to **5,000,400 bytes = 4167 × 1200 B**. That is
  consistent with the end packet count and with the client's sent bytes.
- The old `parse_server_udp()` used a `positive_number()` check that accepts `0`, so it chose the zero
  `end.sum` first and then raised an error.
- No fix had been applied before this work. The only earlier change was a read-only diagnostic
  (`scripts/legacy/diagnose_small_iperf_receiver.py`).

## Fix

`src/smartmall/iperf_receiver.py`:

- Only a **server** report counts as receiver evidence: `start.accepted_connection` must be present
  and the run must not be in reverse mode. Intervals flagged `sender=True` are rejected.
- Throughput is calculated as **Σ bytes / Σ seconds over valid, non-omitted receiver intervals**. It
  is weighted by bytes, not an average of the interval rates.
- When `end.sum` has `bytes=0` but `packets>0`, it is flagged and never used as a rate.
- Packet counts are checked three ways: interval packets against `end.packets − end.lost`, and bytes
  against packets × blksize.
- Loss is calculated as lost / (received + lost) from the receiver. Jitter comes from the receiver.
- The possible statuses are `verified`, `zero_received` (nothing arrived; the cause must be
  established elsewhere, and this is **not** counted as loss), `unavailable` and `invalid`.
- Client values are reported as `sender_only`, never as receiver throughput.

`scripts/verify_small_iperf_receiver.py` adds:

- Explicit acceptance criteria:
  - status `verified`
  - |receiver − offered| / offered ≤ 5 %
  - loss ≤ 1 %
- A check that the server output embedded by the client (`--get-server-output`) matches the
  standalone server JSON.
- An independent NIC cross-check: the `rx_bytes` delta on SRV-LOCAL must be at least
  payload + (8 + 20 + 14) B × received packets.
- A per-interval CSV with absolute timestamps.
- An offline `--reanalyze` mode, which never modifies existing folders.

Regression tests: `tests/test_iperf_receiver.py` (13 tests). They cover zero-valued final summaries,
the real historical 3.9 report, byte weighting compared with a mean of rates, loss and jitter, all-zero
intervals, missing intervals, malformed values, NaN and negative values, error reports, client and
reverse roles, sender-flagged intervals, and interval timestamps.

## Results

### Historical runs re-analysed offline (raw files unchanged)

| Run | Profile | Receiver Mb/s | Received pkts | Loss % | Acceptance |
|---|---|---:|---:|---:|---|
| 143400Z_8a5a05 | 5 Mb/s | 4.9665 | 4167 | 0.0 | PASS |
| 144728Z_9d7e8e | 5 Mb/s | 4.9687 | 4167 | 0.0 | PASS |
| 144957Z_737f8b | 5 Mb/s | 4.9684 | 4167 | 0.0 | PASS |

### New live verifications (3 independent Mininet instantiations)

| Run | Profile | Receiver Mb/s | Bytes | Pkts | Lost | Jitter ms | Rx window s | Sender Mb/s (not evidence) | NIC rx Mb/s | Embedded server copy | Acceptance |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 152455Z_a3813a | 5 | 4.9727 | 6,249,600 | 5208 | 0 | 0.042 | 10.054 | 4.9996 | 5.064 | match | PASS |
| 152455Z_a3813a | 40 | 39.7802 | 49,996,800 | 41664 | 0 | 0.084 | 10.055 | 39.9964 | 40.512 | match | PASS |
| 152524Z_6cac92 | 5 | 4.9742 | 6,249,600 | 5208 | 0 | 0.035 | 10.051 | 4.9996 | 5.070 | match | PASS |
| 152524Z_6cac92 | 40 | 39.7936 | 49,996,800 | 41664 | 0 | 0.099 | 10.051 | 39.9970 | 40.534 | match | PASS |
| 152547Z_b5ee78 | 5 | 4.9743 | 6,249,600 | 5208 | 0 | 0.032 | 10.051 | 4.9996 | 5.069 | match | PASS |
| 152547Z_b5ee78 | 40 | 39.7390 | 49,996,800 | 41664 | 0 | 0.088 | 10.065 | 39.9971 | 40.473 | match | PASS |

Each run's only warning is the known `end.sum bytes=0` inconsistency.

## Interpretation

- Every datagram sent was received: 5208 and 41,664 datagrams, with 0 lost.
- The receiver rate is about 0.5 % below the offered rate. This is because the receiver's measurement
  window (≈10.05 s, including a final partial interval) is longer than the sender's 10.00 s. It is not
  loss.
- The NIC ingress rate is higher than the goodput by the expected header overhead
  (1242 / 1200 ≈ 1.035, less the window effect).
- 40 Mb/s on the 100 Mb/s access links caused **no loss and no evidence of congestion**. This
  verification makes no claim of congestion.

**Stage A acceptance: PASS.** Both active profiles were verified from real receiver-side measurements
in 3 independent runs.

Raw evidence:
`data/raw/small_v1/receiver_verify_20261125T1524*`, `..._152524Z_6cac92`, `..._152547Z_b5ee78`.
Each folder holds the server and client JSON, `receiver_intervals_*.csv`, and `manifest.json`, which
records the parser SHA-256.
