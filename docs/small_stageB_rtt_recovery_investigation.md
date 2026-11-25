# Stage B — investigation of the 3 `rtt_recovered_close_to_healthy` audit failures

Campaign: `campaign_B_full_20261125T155024Z_bef001` (63 runs, seed 2026112501).
All 63 runs completed (rc = 0). The collection-time auditor (`src/smartmall/audit.py`, sha256
`d2186428…`, recorded in the manifest) marked **60/63 PASS**. Its verdicts are preserved unchanged in
`data/campaigns/campaign_B_full_20261125T155024Z_bef001/audits_at_collection/`.

## The three exceptions

| Experiment | Scenario | Old check (mean RTT, healthy → recovered) | Window with transient |
|---|---|---|---|
| `scn_20261125T155624Z_4b4a46` | LINK_FAILURE L6, 40 Mb/s, rep 1 | 7.293 → 9.546 ms | w09 (recovered): 5 pairs |
| `scn_20261125T161425Z_179750` | LINK_FAILURE L1, 40 Mb/s, rep 3 | 10.632 → 7.151 ms | w03 (**healthy**): 5 pairs |
| `scn_20261125T164533Z_46cc4d` | LINK_FAILURE L3, 40 Mb/s, rep 1 | 9.064 → 6.962 ms | w02 (**healthy**): 4 pairs |

A transient window is one where at least 2 pairs have an echo more than 10 ms above that pair's own
minimum RTT.

## Evidence (run `…4b4a46`, inspected per host pair)

- **Recovery**:
  - All 6 pairs were reachable at the first check, 1.03 s after restoration.
  - tc was restored to baseline, all 12 interfaces were admin-up with carrier, and no OVS bridge
    remained after the stop.
- **RTT per pair**:
  - In w07 and w08, every pair was back at its healthy level (≈4.2 ms same-switch, ≈8.3 ms cross-switch).
  - In w09, 5 of the 6 probes launched at the same instant (15:57:15.25) had min ≈8.3 ms but max
    35–40 ms (mdev ≈14 ms). In other words, **one of three echoes** was delayed by about 30 ms.
- **Not specific to L6**:
  - The affected pairs include PC-ADM~PC-SHOP and PC-SHOP~SRV-LOCAL, which never traverse L6.
  - The only unaffected pair, PC-ADM~SRV-LOCAL, is the only pair that does not traverse SW-COM. SW-COM
    carries the 40 Mb/s flow.
- **Traffic**:
  - The receiver got ≈40.0 Mb/s in every window, including w09, and destination NIC counters were
    consistent.
  - The alignment flags were normal.
- **Other repetitions**: the L6/40 runs rep 2 and rep 3 show no transient.

## Campaign-wide statistics (63 runs, 567 windows)

| Load | Healthy windows with transient | Failed | Recovered | Runs with ≥1 transient |
|---|---|---|---|---|
| 0 Mb/s | 0/63 | 1/63 | 0/63 | 1/21 |
| 5 Mb/s | 0/63 | 0/63 | 1/63 | 1/21 |
| 40 Mb/s | **4/63** | 0/63 | **4/63** | 6/21 |

- **Rates are equal in healthy and recovered windows at 40 Mb/s.** The transient is not linked to
  recovery. In two of the three exceptions it occurred **before** the fault was injected, which makes
  the healthy mean *higher* than the recovered mean.
- **No transient occurred in the FAILED windows at 40 Mb/s.** In 4 of the 6 link-failure scenarios,
  the failed link cuts the 40 Mb/s flow off from its destination. This is consistent with a
  load-related cause.
- **Healthy RTT by load**:
  - The median is unchanged: 8.33 / 8.29 / 8.29 ms at 0 / 5 / 40 Mb/s.
  - Only the tail grows: P95 9.23 / 8.99 / 10.78 ms, max 12.8 / 13.8 / 23.0 ms.
  - So 40 Mb/s on the 100 Mb/s links causes **occasional tail-latency transients, not sustained
    queueing**. This is consistent with Stage A: 0 datagram loss at 40 Mb/s.
- **Path delay**: the largest |Δ| between healthy and recovered, using the per-pair median of
  per-window minimum RTT, is **0.18 ms** over all 63 runs.
- **Probable mechanism** (not proven): momentary processing delay in the single-host emulation
  (kernel OVS datapath / softirq / veth scheduling on WSL2). We have no instrumentation that isolates
  this further, so it is reported as a limitation of the emulation platform.

### Addendum after Stage C (corrects an earlier statement)

Stage C (`campaign_C_full_20261125T165402Z_db0b5f`) shows the same transients **at idle as well**:

| Campaign | 0 Mb/s | 5 Mb/s | 40 Mb/s |
|---|---|---|---|
| B full | 1/189 windows | 1/189 | 7/189 |
| C full | 9/162 windows | 9/135 | 1/27 |

The C transients:

- **Occur in all families and all phases.** They hit every impairment family, and healthy, failed and
  recovered windows alike.
- **Are clustered in time.** Runs 1–3 (16:54–16:56 UTC) and runs 32–35 (17:20–17:23 UTC) account for
  most of them.

They are therefore **not caused by background traffic alone**. The better description is time-varying
noise on the emulation host, which background load appears to make more likely (as in B). The earlier
wording "occur only under background load" was based on Stage B alone and is withdrawn.

The conclusion for the audit is unchanged: transients are not a scenario effect. In Stage C one of them
caused the only FAIL (`scn_20261125T165402Z_8b34e1`). Its delay-isolation check used the same mean-RTT
statistic, so the path-delay statistic now applies to the delay checks as well (auditor
`993a4b44e694`).

## Conclusion

- **This is not a genuine recovery problem.** Connectivity, interface state, tc configuration,
  traffic and path delay are all restored in every run.
- **It is measurement variability under load**, in the form of rare single-window RTT transients.
- **The old criterion was mis-specified for its purpose.** It compared the mean RTT of all probes
  across three windows. A single transient window in either phase (healthy or recovered) moves that
  mean by more than 2 ms. So the check tested load jitter, not restoration of the path.

## Audit change (statistic, not threshold)

Auditor `v_08ab341b5a59` (sha256 `08ab341b5a59…`) changes the following:

1. **Gating check `rtt_recovered_path_delay`**: for each pair, the median over a phase's windows of
   the per-window *minimum* RTT must not differ by 2 ms or more between healthy and recovered. The
   **2 ms threshold is unchanged**. Using the minimum targets propagation and fixed delay. Using the
   median requires most windows to be normal: a persistent shift in 2 of 3 windows still fails (this
   is a regression test).
2. **Non-gating warning**: a mean RTT shift of 2 ms or more is still reported for every run.
3. **New output `rtt_transient_windows`**: lists transient windows for every run, so this jitter
   stays visible in all reports and in the dataset.
4. **Version tracking**: every audit records `auditor_sha256`. Re-audits are written to
   `data/audits/v_<sha12>/` and never overwrite collection-time audits.

New tests in `tests/test_audit.py`:

- `test_single_window_rtt_transient_is_warning_not_failure`
- `test_persistent_path_delay_shift_after_recovery_fails`

## Result

| Auditor | PASS | FAIL | Warnings |
|---|---:|---:|---:|
| collection-time `d2186428` | 60 | 3 (the runs above) | — |
| current `08ab341b5a59` | **63** | 0 | 3 (the same runs: mean-RTT shift) |

All three runs are kept in the dataset. Their transient windows are flagged in the audit output and are
not removed.
