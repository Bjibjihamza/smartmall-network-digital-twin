# SmartMall Network Digital Twin — SMALL final validation report

Date: 2026-11-25. Topology: `small_v1`.

Every number in this report comes from raw experiments stored under `data/raw/small_v1/`. Nothing is
simulated, extrapolated or planned. No machine-learning model was trained, and no ML performance is
claimed.

Companion documents:
- `docs/small_receiver_verification_audit.md` (Stage A)
- `docs/small_stageB_report.md`, `docs/small_stageC_report.md`, `docs/small_stageD_report.md`
- `docs/small_all_scenarios_report.md` (B + C + D combined)
- `docs/small_stageB_rtt_recovery_investigation.md`
- `docs/SMALL_DATASET_CARD.md`
- `docs/SMALL_PROGRESS_LOG.md`

---

## 0. Status summary

| Stage | Status | Evidence |
|---|---|---|
| A — iperf3 receiver verification | **Validated** | 3 live runs × {5, 40} Mb/s, all PASS, 0 datagram loss; root cause documented; 13 regression tests |
| B — link failures under background load | **Validated** | 63/63 runs PASS (60/63 under the collection-time auditor; 3 exceptions investigated) |
| C — degradations (delay, loss, bandwidth/congestion) | **Validated** | 36/36 PASS (35/36 under the collection-time auditor; 1 exception investigated) |
| D — node failures (switch power-off, silent black hole, host power-off) | **Validated** | 48/48 PASS (48/48 under the collection-time auditor) |
| E — dataset quality and consistency | **Validated** | 165 experiments, 1,431 windows; 19/19 dataset checks PASS; leakage quantified |
| F — final validation and documentation | **Done** | this report |

---

## 1. Topology and experimental configuration

`topologies/small.json` was verified by unit tests (`tests/test_topology_telemetry.py`):

- **Nodes (7)**: 3 switches (DSW-1 distribution; SW-ADM and SW-COM access) and 4 hosts (PC-ADM,
  SRV-LOCAL, PC-SHOP, POS).
- **Links (6)**: L1 (DSW-1–SW-ADM) and L2 (DSW-1–SW-COM) at 1000 Mb/s; L3–L6 (host access) at
  100 Mb/s. Every link has 1 ms delay.
- **Structure**: a tree with no redundant path. The topology was not redesigned.

| Item | Setting |
|---|---|
| Emulator | Mininet 2.3.0, Open vSwitch 2.17.12 (`OVSBridge`, standalone L2 learning), Ubuntu 22.04 on WSL2 |
| Link shaping | `TCLink`: HTB rate plus a netem child with the 1 ms delay, on both ends of each link |
| Addressing | 10.42.0.11–14/24 (single L2 domain) |
| Traffic generator | iperf3 3.9 UDP, flow PC-SHOP → SRV-LOCAL (path L5 → L2 → L1 → L4), 1200 B datagrams, 0 / 5 / 40 Mb/s |
| Protocol `small_scenario_v2` | HEALTHY → FAILED → RECOVERED, 3 windows per phase, fixed 4 s windows |
| ICMP probing | 6 host pairs probed **concurrently** each window (3 echoes at 0.2 s, 2 s wait; 10 echoes at 0.1 s for loss scenarios) |
| Interface telemetry | 12 interfaces sampled before and after each window (counters, admin and carrier state, operstate) |
| Queue telemetry | tc qdisc/class sampled before and after each window |
| Flow segments | Segment 1 spans HEALTHY and FAILED, so traffic genuinely crosses the injection. Segment 2 covers RECOVERED |
| Legacy protocol `small_link_v1` | 18 pre-existing link-failure experiments: sequential probes, 2 echoes, 2 windows per phase, no traffic or tc telemetry |

---

## 2. Supported scenarios and implementation

| Family | Mechanism (`scripts/run_small_scenario.py`, `src/smartmall/scenarios.py`) | Targets run | Verified by |
|---|---|---|---|
| `NONE` | No injection (control) | — | all-reachable signature |
| `LINK_FAILURE` | `configLinkStatus(down)`: **both** link ends administratively down | L1–L6 | admin_up = 0 on both ends; expected signature; recovery |
| `LINK_DELAY` | `TCIntf.config` on both ends: netem delay = 1 ms + added (each direction) | L5 +20 and +5 ms; L2 +20 ms | tc readback in every window; RTT path-delay shift |
| `LINK_LOSS` | `TCIntf.config` on both ends: netem random loss | L5, L2 at 5 % | tc readback; ICMP and UDP receiver loss |
| `LINK_BANDWIDTH` | `TCIntf.config` on both ends: HTB rate cap, netem queue limit 100 packets | L5 at 10 Mb/s | tc readback; receiver rate; qdisc drops; RTT |
| `NODE_FAILURE` (switch) | Power-off emulation: all of the switch's own interfaces admin-down; neighbours stay admin-up and lose carrier | DSW-1, SW-ADM, SW-COM | admin and carrier pattern; signature |
| `NODE_FAILURE` (host) | Power-off emulation: the host interface admin-down; the switch port loses carrier | all 4 hosts | as above |
| `SWITCH_BLACKHOLE` | Silent data-plane failure: OVS `fail-mode secure` and all flows deleted; every interface stays UP with carrier | DSW-1, SW-ADM, SW-COM | fail_mode and flow_count readback (0 flows during, NORMAL flow after); signature |

**Safety and cleanup**, checked in every run:
- **Mechanism verified**: the mechanism's effect is read back right after injection and right after
  restoration (`injector_effect_verified_and_reverted`).
- **tc restored**: the full tc configuration of all 12 interfaces is compared with the baseline taken
  at start.
- **Interfaces restored**: all interfaces are admin-up with carrier after restoration.
- **Clean shutdown**: no OVS bridge remains after `net.stop()`.
- **Recovery**: full 6-pair reachability is confirmed before the RECOVERED phase. It was reached
  0.99–1.06 s after restoration in all 147 runs. The check granularity is about 1 s, so this is an
  upper bound.

**Ground truth.** It lives only in `incident.json`:
- the scenario, its parameters and its mechanism
- injection and restoration times, taken when the mechanism is applied
- the phase of each window
- the expected effects
- the relation between the fault and the flow

The telemetry CSVs contain no label column. Every audit verifies this.

---

## 3. Campaign inventory and experiment counts

### Validated campaigns (in the dataset)

| Campaign | Config / seed | Runs | Families |
|---|---|---:|---|
| `campaign_20261125T134916Z_249a1c` and `campaign_20261125T140815Z_f24de3` (v1, pre-existing) | — | 18 | LINK_FAILURE L1–L6 × 3, idle |
| `campaign_B_full_20261125T155024Z_bef001` | `configs/small_stageB_full.json` / 2026112501 | 63 | LINK_FAILURE L1–L6 × {0, 5, 40} Mb/s × 3 = 54; NONE × {0, 5, 40} × 3 = 9 |
| `campaign_C_full_20261125T165402Z_db0b5f` | `configs/small_stageC_full.json` / 2026112503 | 36 | DELAY 15, LOSS 12, BANDWIDTH 9 |
| `campaign_D_full_20261125T173105Z_35c196` | `configs/small_stageD_full.json` / 2026112505 | 48 | NODE_FAILURE (switch) 18, NODE_FAILURE (host) 12, SWITCH_BLACKHOLE 18 |
| **Total in dataset** | | **165** | |

### Experiment counts by scenario family (dataset)

| Family | Experiments | Active-fault windows |
|---|---:|---:|
| LINK_FAILURE | 72 (54 v2 + 18 v1) | 198 |
| LINK_DELAY | 15 | 45 |
| LINK_LOSS | 12 | 36 |
| LINK_BANDWIDTH | 9 | 27 |
| NODE_FAILURE | 30 | 90 |
| SWITCH_BLACKHOLE | 18 | 54 |
| NONE (controls) | 9 | 0 (all windows are no-fault) |
| **All** | **165** | **450 fault windows, of 1,431** |

There are 981 no-fault windows: the healthy and recovered windows of every run, plus all windows of
the controls.

### Supporting and historical runs (kept as evidence, not in the dataset)

| Folder(s) | Purpose | Outcome |
|---|---|---|
| `receiver_verify_…143400Z`, `…144728Z`, `…144957Z` | Original Stage A attempts | FAILED (zero-summary bug); re-analysed read-only and valid under the fix |
| `receiver_verify_…152455Z`, `…152524Z`, `…152547Z` | Stage A verification | 3/3 PASS |
| `load_pilot_…142531Z_591715` | Pre-existing load pilot (client-side only) | receiver unverified, superseded by Stage A |
| `design_probe_…152755Z_1a0cdb` | iperf3 behaviour across faults | design evidence |
| `campaign_B_pilot_…153741Z`, `…154421Z` (and smoke run `scn_…153343Z`, outside any campaign) | Stage B pilots | 12/12 + 1/1 PASS; pilot 1 predates the alignment and timestamp fixes |
| `campaign_C_pilot_…164805Z` | Stage C pilot | 5/5 PASS |
| `campaign_D_pilot_…172703Z` | Stage D pilot | 4/4 PASS |
| 9 other `exp_*` folders (including the failed `exp_…133614Z_119124`) and 3 early v1 campaigns | Pre-existing v1 development runs | preserved unchanged |

Evidence under `data/` totals about 40.7 MB of files (raw 31.7 MB); the processed dataset is 2.7 MB.

---

## 4. Validation methods and results

### 4.1 Per-experiment audit (`src/smartmall/audit.py`)

Each audit applies more than 25 checks:

- **Schema and identifiers**: schema; no label columns; consistent experiment IDs.
- **Windows and timing**:
  - window count and phase order
  - window durations (4.06–4.12 s observed)
  - windows do not overlap
  - injection and restoration fall between phases
- **Mechanism**: the injector effect is verified and reverted.
- **ICMP**:
  - semantics: `route_unreachable` means 0 packets sent and undefined loss, never 100 %
  - the connectivity signature matches the topology-derived expectation
- **Ports**:
  - sample and delta counts
  - no counter resets
  - interface states match the mechanism
- **tc**: the configuration matches the phase on all 12 interfaces in every window.
- **Traffic**:
  - flow segments are present
  - the flow overlaps every window
  - receiver and NIC rates match the offered load in healthy and recovered windows
  - zero-traffic windows during the fault are explained by their cause
- **Effects and recovery**: family-specific effect checks; path delay is recovered.

Auditor versions:

| Auditor (sha256 prefix) | Used at collection for | Change |
|---|---|---|
| `d2186428f0a0` | B full | initial |
| `d6ee06ed281f` | C full | recovery uses the path-delay statistic; transient report; idle-bandwidth check; drop accounting |
| `993a4b44e694` | D full; **current, used to re-audit everything** | delay-effect checks use the path-delay statistic |

- **Collection-time verdicts** are preserved in each campaign's `audits_at_collection/`.
- **Re-audits** are in `data/audits/v_993a4b44e694/`.
- **The collector did not change between campaigns.** `scripts/run_small_scenario.py` has the same
  sha256 `8ea2f29ae394…` in all three full campaigns.

### 4.2 Audit outcomes

| Campaign | Collection-time PASS | Current-auditor PASS | Warnings (non-gating) |
|---|---:|---:|---:|
| B full | 60/63 | 63/63 | 3 |
| C full | 35/36 | 36/36 | 1 |
| D full | 48/48 | 48/48 | 2 |
| B, C and D pilots (re-audited) | 21/21 | 21/21 | — |

**The 4 collection-time exceptions:** 3 in B (L6/40 rep 1, L1/40 rep 3, L3/40 rep 1) and 1 in C
(DELAY L5 +20 ms at idle, rep 2).

- **What they share**: each was caused by a **single 4 s window** in which one echo of several pairs
  was delayed by 30–55 ms while the minimum RTT stayed normal. In 3 of the 4, the transient was in a
  **HEALTHY** window, before any fault.
- **Why the checks failed**: they used the mean RTT over all probes, so a single transient window
  dominated the comparison.
- **The statistic that replaced it**: the per-pair median over windows of the per-window minimum RTT,
  i.e. the path delay. The thresholds are unchanged (2 ms; ±max(2 ms, 20 %) for delay). Two regression
  tests confirm that a persistent shift still fails.
- **Path delay recovered everywhere**: the largest healthy→recovered change over all 147 v2 runs is
  0.18 ms.

The full investigation is in `docs/small_stageB_rtt_recovery_investigation.md`.

### 4.3 Automated tests

Run with `python -m unittest discover -s tests` (stdlib only; passes in cenv on Windows and in WSL
Python 3.10). **48 tests, all PASS.**

| File | Tests | Covers |
|---|---:|---|
| `tests/test_iperf_receiver.py` | 13 | zero end summaries (synthetic and the real 3.9 report), byte weighting, loss and jitter, all-zero intervals, missing or malformed data, NaN and negative values, error and client/reverse roles, sender-flagged intervals |
| `tests/test_topology_telemetry.py` | 15 | topology, signatures, paths; ping parsing with real fixtures (ok / total loss / local route failure); counter resets; window allocation; tc parsing |
| `tests/test_audit.py` | 13 | genuine runs pass; tamper detection for label leak, counter reset, wrong signature, route_unreachable-with-loss, missing rows, failed status, mistimed injection; transient → warning; persistent shift → fail; delay isolation (2 tests) |
| `tests/test_dataset.py` | 7 | dataset counts, checks, no labels in features, every column classified, leave-one-repetition-out folds, leakage quantification, graph snapshots |

### 4.4 Dataset audit (Stage E)

All 19 checks in `quality_report.json` PASS:

- unique IDs and keys; no label columns in feature tables
- 6 pair rows, 12 interface rows and 1 flow row per window
- topology mapping
- ICMP route-vs-loss semantics (0 violations)
- 0 counter resets; 0 negative rates
- monotonic, non-overlapping windows
- labels consistent with phase and topology
- receiver-only flow metrics
- each experiment in exactly one fold, and every stratum in every fold

---

## 5. Measurement analysis

### 5.1 Receiver-side throughput (Stage A)

| Offered | Receiver Mb/s (3 runs) | Datagrams lost | Receiver NIC Mb/s |
|---|---|---:|---|
| 5 Mb/s | 4.973 / 4.974 / 4.974 | 0 / 5208 each | 5.06–5.07 |
| 40 Mb/s | 39.780 / 39.794 / 39.739 | 0 / 41,664 each | 40.47–40.53 |

- **Why the receiver reads about 0.5 % low**: its measurement window (10.05 s) is longer than the
  sender's 10.00 s. This is not loss.
- **NIC rate**: the NIC rate exceeds goodput by the 42 B per datagram of header overhead.

### 5.2 ICMP and RTT

- **Healthy RTT**: about 4.2 ms for same-switch pairs (2 links) and about 8.3 ms for cross pairs
  (4 links). This matches 1 ms netem per link end in each direction.
- **Effect of 40 Mb/s on the 100 Mb/s links (healthy windows)**:
  - The median is unchanged: 8.33 / 8.29 / 8.29 ms at 0 / 5 / 40 Mb/s.
  - Only the tail grows: P95 9.2 → 10.8 ms, max 12.8 → 23.0 ms.
  - Datagram loss is 0.
  - **So 40 Mb/s causes no congestion on these links**, only occasional tail transients.
- **Rare RTT transients** (≥2 pairs with an echo >10 ms above baseline): 0.5 % of idle windows in B
  and 3.7 % of 40 Mb/s windows; up to about 6 % in C at any load. They are clustered in time and
  appear in every phase. They are attributed to timing noise on the emulation host, which background
  load makes more likely but does not cause. This is a platform limitation.
- **Selection effect**: during an L1 or L2 failure, the mean RTT of the *reachable* pairs drops to
  about 4.2 ms because only same-switch pairs remain. This is not an improvement.

### 5.3 Background flow under failures (Stage B)

| Fault relation to flow | Example | FAILED receiver Mb/s | Destination NIC | Sender |
|---|---|---|---|---|
| Flow path cut mid-path or at the receiver | L1, L2, L4 | 0.000 | about 0.001 Mb/s (control chatter) | **keeps sending** 5.18 / 41.4 Mb/s on L5; traffic is discarded at the cut without appearing in any interface drop counter |
| Sender's own link down | L5 | 0.000 | about 0.001 | **aborts** (`Network is unreachable`) 3/3 at both loads; a new flow segment restarts after recovery |
| Not on the flow path | L3, L6 | 5.000 / 40.000 | 5.18 / 41.40 | unaffected |
| Control | NONE | 5.000 / 39.998 | 5.18 / 41.40 | unaffected |

- **Recovered phase**: receiver throughput was 5.000 and 40.000 ± 0.02 Mb/s in every case.
- **Lost-packet counts during cuts are not real-time loss**: iperf3 reports the outage's sequence gap
  as "lost" packets **when traffic resumes**. Per-window `receiver_lost_packets` during a
  disconnection is therefore not a loss measurement. It is flagged `caution` in the feature
  dictionary.

### 5.4 Degradations (Stage C): configured vs observed

| Scenario | Runs | Observed (range over runs) | Consistent with configuration |
|---|---:|---|---|
| DELAY L5 +20 ms (0 and 5 Mb/s) | 6 | path-delay increase on impaired pairs +39.98 … +40.14 ms (expected +40) | yes; other pairs max shift ≤0.13 ms |
| DELAY L2 +20 ms (0 and 5 Mb/s) | 6 | +40.00 … +40.12 ms | yes; other pairs ≤0.07 ms |
| DELAY L5 +5 ms (idle) | 3 | +10.02 … +10.11 ms (expected +10) | yes |
| LOSS L5 5 % | 6 | UDP receiver loss 4.74–4.96 % (one traversal); ICMP impaired-pair loss 8.9–16.7 % per run, pooled 11.5 % (expected about 9.75 % round trip; binomial, +1.4 SD); other pairs 0 % | yes |
| LOSS L2 5 % | 6 | UDP receiver loss 4.73–4.94 %; ICMP 7.5–10.8 % per run, pooled 9.2 %; other pairs 0 % | yes |
| BANDWIDTH L5 10 Mb/s, idle | 3 | no RTT shift (≤0.07 ms), 0 drops | yes: **a cap is unobservable without traffic** |
| BANDWIDTH L5 10 Mb/s, 5 Mb/s offered | 3 | receiver 4.999–5.000 Mb/s, 0 drops | yes: the limit is present but not binding |
| BANDWIDTH L5 10 Mb/s, **40 Mb/s offered** | 3 | receiver **9.59–9.77 Mb/s**; qdisc drops **37,882–38,094** ≈ receiver-lost **38,612–38,948**; impaired-pair RTT 7.0–7.7 → **104.6–105.3 ms** (a full 100-packet queue at 10 Mb/s takes 99.4 ms); ICMP loss 7–19 % | yes: **congestion is demonstrated by measurements, not inferred from configured rates** |

- **Bandwidth limitation versus congestion**: a limitation alone (offered < cap) produces no loss and
  about +1 ms of serialisation delay. Traffic-induced congestion (offered > cap) produces a capped
  receiver rate, queue drops that equal receiver losses, and queueing delay at the full-queue bound.
- **Controls**: the 40 Mb/s controls on uncapped 100 Mb/s links (Stage B, NONE) show none of these
  effects.

### 5.5 Interface telemetry

Per-window deltas show the following:

- **Healthy load**: 5.18 / 41.40 Mb/s on every interface along L5 → L2 → L1 → L4 (UDP payload plus
  IP and Ethernet headers).
- **Admin-down interfaces**: zero counters.
- **Link and node failures**: neighbours of admin-down interfaces show `carrier = 0`
  (`LOWERLAYERDOWN` / `DOWN`).
- **Black holes**: all interfaces stay UP with carrier. Frames usually still arrive at the dead
  switch's own ports and are discarded internally. Mean own-port rx was 132 / 85 / 81 pkt/s for
  DSW-1 / SW-COM / SW-ADM.
- **SW-ADM exception**: 28 % of SW-ADM's own-port windows had rx = 0, because the hosts behind it are
  mostly idle. This is why its "silent interface" signature is unstable (section 6).
- **Kernel counters miss data-plane drops**: `tx_dropped` and `rx_dropped` were 0 in all 17,172
  interface-window rows. OVS-internal and black-hole discards are invisible to kernel interface
  counters; only qdisc counters see shaping drops.

---

## 6. Fault-signature distinguishability and known ambiguities

The analysis covers all 16 v2 *failure* scenarios, using FAILED windows. It is descriptive, not a
classifier.

| Observables used | Distinct signatures | Ambiguous groups remaining |
|---|---:|---|
| Host-pair reachability only | 7 | {L1, L2, DSW-1 power-off, DSW-1 black hole}; {L3, PC-ADM}; {L4, SRV-LOCAL}; {L5, PC-SHOP}; {L6, POS}; {SW-ADM power-off, SW-ADM black hole}; {SW-COM power-off, SW-COM black hole} |
| + `probe_status` (route_unreachable vs loss) | 7 | no gain: members of each group share the same pattern |
| + interfaces with zero traffic (rx = tx = 0 pps) | 13 | access link L3–L6 ≡ failure of its attached host. The SW-ADM black hole produced 2 signatures, so it is not fully stable |
| + `admin_up` / `carrier` (restricted) | 16 | none, **but this separation is produced by the injection mechanism** |

Further points:
- **Degradations** (delay, loss, non-binding or idle bandwidth caps) never change reachability, so they
  share the all-reachable signature with NONE. They are separable only through RTT, loss, throughput
  and queue observations.
- **Repeatability**: every scenario showed **exactly one signature across all its windows, loads and
  repetitions** at the reachability level.
- **Switch power-off vs access-link failure**: when an access switch powers off, its hosts keep an
  admin-up NIC without carrier. They still *transmit* probes (loss), whereas an access-link failure
  produces `route_unreachable`. This difference is observable without restricted columns.
- **Reproduced from v1**: L1 and L2 remain indistinguishable by reachability, as found earlier.

---

## 7. Reproducibility

```powershell
# Windows (cenv): unit tests, audits, analysis, dataset
conda run -n cenv python -m unittest discover -s tests
conda run -n cenv python scripts/audit_small_scenario.py --campaign data/campaigns/campaign_B_full_20261125T155024Z_bef001
conda run -n cenv python scripts/build_small_dataset.py --v2-campaigns <B_full> <C_full> <D_full> --v1-campaigns data/campaigns/campaign_20261125T134916Z_249a1c data/campaigns/campaign_20261125T140815Z_f24de3 --out data/processed/small_dataset_v2 --report docs/SMALL_DATASET_CARD.md
```

```bash
# Ubuntu WSL2, project root: experiments (dry run first; each campaign writes NEW folders)
python3 scripts/run_small_scenario_campaign.py configs/small_stageB_full.json --dry-run
sudo /usr/bin/python3 scripts/run_small_scenario_campaign.py configs/small_stageB_full.json
sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_BANDWIDTH --target L5 --bw-mbps 10 --queue-pkts 100 --load-mbps 40
sudo /usr/bin/python3 scripts/verify_small_iperf_receiver.py            # Stage A
```

- **Seeds**: each campaign seed shuffles the run order and derives a per-run seed. Both are recorded
  in each manifest.
- **Provenance**: manifests record SHA-256 hashes of the runner, auditor, library modules, config
  and topology. Each `incident.json` records the hashes of the code that produced it.
- **Expected duration**: B 56 min, C 31 min, D 43 min. Each campaign prints a dry-run estimate.

---

## 8. Dataset schema and labelling policy

The dataset is in `data/processed/small_dataset_v2/`; see `docs/SMALL_DATASET_CARD.md` for details.

- **Grain**: one graph snapshot per (experiment, window). There are 1,431 snapshots.
- **Feature tables**:
  - `pair_window.csv`: 8,586 rows, host-pair ICMP
  - `interface_window.csv`: 17,172 rows, directed interface deltas, states and queue counters
  - `flow_window.csv`: receiver goodput, alignment flag, sender liveness
- **Labels**: `labels_window.csv` only. It holds phase, `fault_active`, family, category, target,
  target kind, parameters and window times.
- **Experiment metadata**: `experiments.csv` holds scenario, condition, seed, audit and fold.
- **Feature dictionary**: every column has a leakage class (`observation`, `mechanism_revealing`,
  `identifier`, `condition`, `quality_flag`, `ground_truth`, `split`) and a `model_input` decision.
  The test suite enforces that all columns are classified.
- **Leakage controls**:
  - **Interface state reveals the fault.** Detecting faults from "any interface admin_up = 0 or
    carrier = 0" yields 0 false positives and recall 1.0 on admin-mechanism faults. Localisation from
    admin state recovers the exact target in every admin-mechanism fault window.
    `admin_up`, `carrier` and `oper_up` are therefore `restricted` and excluded from the default
    graph features (`src/smartmall/graph_loader.py`; `include_restricted=True` must be requested
    explicitly).
  - **`window_id` determines the phase** (w01–03 healthy, w04–06 failed, w07–09 recovered). It is an
    identifier, as are `experiment_id`, timestamps, seed and paths.
  - **`offered_mbps`** is an experimental condition, constant per run.
  - **Configured tc parameters** (`cfg_*`) stay in raw data only.
- **Splits**: leave-one-repetition-out with 3 folds, using the independent experiment as the unit.
  Every (protocol, scenario, load) stratum appears in every fold, giving 55 / 55 / 55 experiments.
  No experiment's windows are split.
- **Graph interface**: `graph_schema.json` (7 nodes, 6 edges, feature sources, label tasks: detection,
  family, localisation). `load_snapshots()` yields edge features (2 × 8 directed-end features per
  link), node features (6 probe and throughput aggregates) and masks. It is pure Python with no GNN
  dependency.

---

## 9. Implemented vs not validated vs unsupported

### Implemented and validated

- Receiver-side iperf3 UDP verification, with the 3.9 zero-summary root cause fixed.
- Link failures L1–L6 under 0, 5 and 40 Mb/s, plus no-fault controls.
- Delay, loss and bandwidth-cap impairments, with measured effects. Congestion is demonstrated (40
  offered → 10 Mb/s cap) and distinguished from non-binding limitation.
- Switch power-off for all 3 switches, host power-off for all 4 hosts, and a silent switch black hole
  for all 3 switches.
- Cleanup, recovery, tc and interface restoration, verified every run.
- Consolidated dataset with leakage classification and experiment-level splits.

### Implemented but not fully validated

- `graph_loader.load_snapshots()`: tested for shape, feature exclusion and labels only. No GNN
  framework integration has been exercised.
- Per-window receiver allocation in windows adjacent to transitions (`receiver_alignment_reliable = 0`).
  The values are kept but should not be interpreted. NIC counters are the reliable per-window
  measure.
- The legacy v1 experiments use a different protocol. They are included and labelled, but mixing them
  with v2 data has not been evaluated.

### Not supported in SMALL (by design or not tested)

- Rerouting and redundancy: the tree has no alternative path, so failover can't be studied.
- Physical-layer realism: link and node failures are emulated by administrative interface state.
  There is no real carrier loss, CRC errors or flapping.
- Multiple simultaneous faults, intermittent or flapping faults, gradual degradations, jitter
  impairments, service or application failures, ARP/MAC-table faults.
- Multiple competing flows, TCP traffic, bursty or realistic mall traffic mixes.
- Impairment on uplink L1, loss rates other than 5 %, and caps other than 10 Mb/s.

---

## 10. Scientific findings

1. Under iperf3 3.9, receiver goodput can only be recovered from the server's per-interval reports;
   its end summary reports zero bytes.
2. Link-failure connectivity signatures are fully deterministic across loads and repetitions. L1 and
   L2 remain indistinguishable by reachability, extending the v1 finding.
3. Host failures are observationally equivalent to the failure of their access link, except in
   restricted interface state. Access-switch power-off and black hole are equivalent in reachability
   but separable by interface traffic silence.
4. A silent data-plane failure (black hole) leaves every interface UP with carrier. It is the
   realistic case where interface-state features are useless.
5. 40 Mb/s on 100 Mb/s access links causes no loss and no median RTT change. Congestion appears only
   with an actual 10 Mb/s bottleneck, where queueing delay reaches the theoretical 99 ms queue bound
   and drops equal receiver losses.
6. A bandwidth cap is unobservable without load, and a non-binding cap is nearly unobservable
   (+1 ms serialisation).
7. Open-loop UDP senders keep sending into a cut path, and these discards are invisible to kernel
   interface drop counters. iperf3 attributes outage losses only when traffic resumes.
8. The emulation platform produces rare, time-clustered RTT transients at every load. Any RTT-based
   check or feature must use robust statistics.

---

## 11. Limitations and open research challenges

- **Single host, single topology, single protocol**: high repeatability here does not imply
  generalisation.
- **Mechanism leakage**: administrative fault mechanisms make interface-state features trivially
  diagnostic. Realistic localisation must be evaluated without restricted columns, and on black holes
  and degradations.
- **Small classes**: 9 windows per host-failure target; 27 for bandwidth. The class balance is
  dominated by no-fault windows (981 of 1,431).
- **Short windows**: 4 s windows with 3-echo probes limit loss resolution. ICMP loss estimates per
  run are noisy (±3 %), and UDP receiver loss is the precise measure.
- **Time alignment**: the receiver-interval offset was measured (0.135–0.162 s) but alignment carries
  ±0.03 s granularity plus 0.5 s interval smearing near transitions.
- **Unresolved host noise**: the cause of the RTT transients has not been isolated.
- **Open challenge**: separating the ambiguity groups of section 6 without leakage needs either
  richer observability (per-switch counters, flow tables, LLDP-like neighbour state) or active
  probing designs.

---

## 12. Readiness for MEDIUM and LARGE

**Recommendation: SMALL is ready, and MEDIUM can proceed.** The pipeline (collector, injectors,
traffic, auditors, analysis, dataset builder) is validated end to end on 147 v2 experiments with no
open audit failures. It is configuration-driven and reproducible.

Before or while scaling, address the following:

1. **Generalise the topology-specific parts**:
   - `run_small_mininet.SmartMallSmall` rejects any family other than `small`.
   - IP assignment assumes fewer than about 240 hosts.
   - The flow endpoints (PC-SHOP → SRV-LOCAL) are fixed constants.
   - `map_interfaces` assumes no parallel links.
   - The dataset/auditor check of 6 pair rows and 12 interface rows per window must become
     topology-derived.
2. **Probe scaling**: all-pairs concurrent ICMP grows as O(n²) in hosts. MEDIUM and LARGE need a
   probe-selection policy (for example a sampled or monitoring-host subset) and a re-validated window
   length.
3. **Redundant paths**: if MEDIUM or LARGE contain loops, standalone `OVSBridge` needs STP (or a
   controller). Failover then becomes an observable behaviour to validate, and the tree-based
   expected-signature logic in `topology.py` (union-find reachability) remains valid only for
   reachability, not paths.
4. **Runtime budget**: about 50 s per experiment on SMALL. Estimate larger topologies with the
   campaign dry run before running them.
5. **Re-run Stage A** on the new topology before trusting any throughput measurement.
