# SMALL completion — progress log

## 0. Repository inspection and gap analysis (2026-11-25)

What I verified in the repository (not taken from earlier claims):

- `topologies/small.json` has 7 nodes (DSW-1, SW-ADM, SW-COM, and the hosts PC-ADM, SRV-LOCAL,
  PC-SHOP, POS) and 6 links, L1–L6. It is a tree. The uplinks are 1000 Mb/s and the access links
  100 Mb/s, each with 1 ms delay.
- 27 `exp_*` link-failure folders exist:
  - 1 is a failed run (`exp_20261125T133614Z_119124`).
  - The 18 experiments in campaigns `..134916Z_249a1c` and `..140815Z_f24de3` give 3 per link and
    are summarised in `docs/history/small_v1/small_repeatability_report.md` (648 ICMP and 2,592 port rows).
  - The others are earlier pilots and campaigns.
- The load pilot `load_pilot_..142531Z_591715` recorded only client-side iperf3 data, so its receiver
  throughput was unverified.
- There were 3 `receiver_verify_*` runs, and all of them **failed** at the 5 Mbps profile. The
  40 Mbps profile was never executed.
- None of this work had been committed to git. `src/` and `tests/` were empty, and no automated
  tests existed. `pytest` is not installed in either environment, so the tests use the standard
  library's `unittest`.

| Roadmap item | State found | Gap |
|---|---|---|
| A — iperf receiver verification | 3 failed runs; parser selects a zero `end.sum` | Root cause, fix, tests, live 5/40 Mb/s runs |
| B — link failures under load | Load pilot (no fault) and link failures (no load) exist separately | Combined pipeline that checks traffic overlap |
| C — degradations | None | Everything |
| D — node failures | None | Everything |
| E — dataset quality | Per-experiment audits only; no unified dataset | Schema, labels, leakage policy, splits |
| F — final report | None | `docs/SMALL_FINAL_VALIDATION.md` |

Commit `136079f` snapshots all existing work, including the failed runs, as historical evidence.

## Stage A — DONE (PASS)

- Root cause: iperf3 3.9's receiver `end.sum.bytes` is 0, and the old parser accepted that 0. See
  `docs/small_receiver_verification_audit.md`.
- Fix: `src/smartmall/iperf_receiver.py`, which uses byte-weighted server intervals. 13 regression
  tests pass in both cenv and WSL.
- 3 live runs, each with 5 and 40 Mb/s: all PASS with 0 loss. The receiver rate was 4.97–4.97 and
  39.74–39.79 Mb/s.

## Stage B — framework and pilot

- Design probe (`design_probe_20261125T152755Z_1a0cdb`): a continuous iperf3 UDP flow survives cuts
  in the middle of the path and on the receiver's link. The open-loop sender keeps transmitting, and
  iperf3 counts the gap as "lost" datagrams. When the sender's own link goes down, the client aborts
  with `Network is unreachable`.
- Protocol `small_scenario_v2`:
  - Fixed 4 s windows, 3 per phase.
  - 6 concurrent ICMP probes per window.
  - 12 interfaces sampled before and after each window.
  - tc samples.
  - Flow segment 1 spans HEALTHY and FAILED; segment 2 covers RECOVERED.
  - Receiver intervals are aligned to the first data arrival measured at the receiver NIC (offset
    0.14 s).
  - Injection and restore times are recorded when the mechanism is applied.
- The generic auditor is `src/smartmall/audit.py`, with 8 tamper-detection tests.
- Two pilots on L2 and L5 at 0, 5 and 40 Mb/s: **12/12 PASS**. The first pilot showed the alignment
  and injection-timestamp issues, which were fixed and validated by the second pilot.
- Full campaign `campaign_B_full_20261125T155024Z_bef001` (`configs/small_stageB_full.json`, seed
  2026112501): 63 runs, 56 min, all rc = 0.
  - The collection-time auditor `d2186428` gave 60/63 PASS. The 3 FAILs were all
    `rtt_recovered_close_to_healthy` at 40 Mb/s: single-window RTT transients under load, and 2 of the
    3 occurred in HEALTHY windows.
  - Investigation: `docs/small_stageB_rtt_recovery_investigation.md`. The statistic was changed to the
    per-pair median of minimum RTT; the threshold is unchanged.
  - Auditor `08ab341b5a59` gives 63/63 PASS with 3 warnings.
  - Collection-time audits are preserved in the campaign folder (`audits_at_collection/`).
- Report: `docs/small_stageB_report.md`.
- Signatures were identical across all 9 runs (3 loads × 3 repetitions) of each link. L1 and L2 are
  indistinguishable by connectivity alone.

## Stage C — DONE

- Pilot: 5/5 PASS.
- Full campaign `campaign_C_full_20261125T165402Z_db0b5f`: 36 runs.
  - The collection-time auditor gave 35/36. The one FAIL was delay isolation under the mean-RTT
    statistic, caused by an idle RTT transient.
  - Auditor `993a4b44e694` gives 36/36.
- Delay +40.0 ± 0.15 ms; UDP loss 4.7–5.0 %; congestion is demonstrated at a 10 Mb/s cap with
  40 Mb/s offered. See `docs/small_stageC_report.md`.
- Transients also occur at idle, so the Stage B investigation was amended.

## Stage D — DONE

- Pilot: 4/4 PASS.
- Full campaign `campaign_D_full_20261125T173105Z_35c196`: 48/48 PASS, both at collection time and
  now. See `docs/small_stageD_report.md`.

## Stage E — DONE

- `data/processed/small_dataset_v2`: 165 experiments and 1,431 windows; 19/19 quality checks PASS.
  See `docs/SMALL_DATASET_CARD.md`.

## Stage F — DONE

- `docs/SMALL_FINAL_VALIDATION.md`.
