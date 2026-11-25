# Operations reference

This is the definitive command list. Run every command from the **repository root**.

- **Windows** commands use the Conda environment `cenv` (PowerShell).
- **Linux** commands run in Ubuntu 22.04 on WSL2 at `/mnt/c/<…>/smartmall-network-digital-twin`.
  From PowerShell, wrap them as `wsl.exe -d Ubuntu-22.04 --cd <repo-in-wsl> -- <command>`.

Commands marked **[root]** start Mininet and need `sudo` in WSL. Nothing else needs root.

---

## 1. Environments

| Environment | Purpose | Requirements |
|---|---|---|
| Windows + Conda `cenv` (Python 3.12) | tests, audits, analysis, dataset, topology tools | stdlib only; `networkx` and `matplotlib` for the topology tools |
| Ubuntu 22.04 / WSL2 (`/usr/bin/python3` 3.10) | experiments | Mininet 2.3.0, Open vSwitch 2.17, iperf3 3.9, iproute2 (tc); passwordless sudo for experiments |

Check the environments (read-only):

```powershell
conda run -n cenv python -c "import sys, networkx, matplotlib; print(sys.version)"
```
```bash
python3 --version; mn --version; ovs-vsctl --version | head -1; iperf3 --version | head -1
sudo -n true && echo "sudo OK"; sudo -n ovs-vsctl list-br      # expect no bridges when idle
```

There is no package installation step. Scripts add `src/` to `sys.path` themselves.
`pip install -e .` is optional and not required.

### 1.1 Where the evidence lives

The repository keeps **results only**: code, configs, `data/processed/small_dataset_v2/`,
`data/catalog/` and the reports in `docs/`. The experimental evidence lives in an external archive with
the same relative layout:

| Archive path | Content |
|---|---|
| `<archive>/data/raw/small_v1/` | 204 raw experiment folders |
| `<archive>/data/campaigns/` | campaign configs, manifests (seeds, run order, source hashes), collection-time audits |
| `<archive>/data/audits/` | collection-time audits and the versioned re-audits `v_<sha12>/` |
| `<archive>/docs/history/` | v1-era reports of the legacy scripts |

`<archive>` is `$SMARTMALL_ARCHIVE` if set, otherwise the sibling folder `../smartmall-data-archive`.
Every command below accepts the usual repository-relative paths (`data/raw/...`, `data/campaigns/...`).
They are looked up in the repository first, then in the archive (`src/smartmall/paths.py`).
`data/raw/`, `data/campaigns/`, `data/audits/` and `docs/history/` are git-ignored, so new
collections land in the repository locally and never reach git.

**Archiving new collections**: move the new folders into the same paths under `<archive>`, then run
`scripts/catalog_small_data.py` to re-catalogue and `--verify` to check.

---

## 2. Recommended commands (official v2 workflow)

### 2.1 Automated tests (no Mininet, no root)

```powershell
conda run -n cenv python -m unittest discover -s tests
```
```bash
python3 -m unittest discover -s tests
```

### 2.2 Topology: validate, visualise, smoke-test

```powershell
conda run -n cenv python scripts/validate_topology.py topologies/small.json
conda run -n cenv python scripts/visualize_topology.py topologies/small.json   # overwrites docs/topology_small.png
```
```bash
sudo /usr/bin/python3 scripts/run_small_mininet.py           # [root] start SMALL, pingAll, stop
sudo /usr/bin/python3 scripts/run_small_mininet.py --cli     # [root] interactive Mininet CLI
```

### 2.3 Stage A: iperf3 receiver verification

```bash
sudo /usr/bin/python3 scripts/verify_small_iperf_receiver.py --dry-run
sudo /usr/bin/python3 scripts/verify_small_iperf_receiver.py            # [root] 5 and 40 Mb/s
python3 scripts/verify_small_iperf_receiver.py --reanalyze data/raw/small_v1/receiver_verify_<id>   # offline
```

### 2.4 Single experiment (pilot or smoke test)

```bash
python3 scripts/run_small_scenario.py --fault-type LINK_FAILURE --target L2 --load-mbps 5 --dry-run
# [root] smoke test written OUTSIDE the evidence tree:
sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_FAILURE --target L5 --load-mbps 5 --raw-root /tmp/smartmall_smoke
python3 scripts/audit_small_scenario.py --out-dir /tmp/smartmall_smoke_audit /tmp/smartmall_smoke/scn_*
```

Fault types and their parameters are listed below. See `--help` for timing options: `--rounds`,
`--window-s`, `--packets`, `--ping-interval`, `--ping-wait`, `--warmup-s`, `--settle-s`.

| Fault type | Target | Parameters |
|---|---|---|
| `NONE` | — | — |
| `LINK_FAILURE` | `L1`–`L6` | — |
| `LINK_DELAY` | link | `--added-delay-ms` |
| `LINK_LOSS` | link | `--loss-pct` |
| `LINK_BANDWIDTH` | link | `--bw-mbps`, `--queue-pkts` |
| `NODE_FAILURE` | switch or host | — |
| `SWITCH_BLACKHOLE` | switch | — |

Without `--raw-root`, the experiment folder is created in `data/raw/small_v1/`, which is the
evidence tree. Use that only for runs intended as evidence.

### 2.5 Campaign from configuration

```bash
python3 scripts/run_small_scenario_campaign.py configs/small_stageB_pilot.json --dry-run   # plan, time and disk estimate
sudo /usr/bin/python3 scripts/run_small_scenario_campaign.py configs/small_stageB_pilot.json   # [root]
```

Each campaign:

- writes `data/campaigns/<campaign_id>/` (config snapshot, manifest with seed and source hashes,
  `summary.csv`, `audits_at_collection/`);
- runs every experiment as a separate process and audits it;
- exits with code 1 if any run fails its audit, without stopping the campaign (use `--stop-on-fail`
  to stop).

| Config | Runs | Measured duration |
|---|---:|---|
| `configs/small_stageB_pilot.json` | 6 | ~5 min |
| `configs/small_stageB_full.json` | 63 | 56 min |
| `configs/small_stageC_pilot.json` | 5 | ~5 min |
| `configs/small_stageC_full.json` | 36 | 31 min |
| `configs/small_stageD_pilot.json` | 4 | ~4 min |
| `configs/small_stageD_full.json` | 48 | 43 min |

### 2.6 Audit existing experiments (offline, read-only on raw data)

```powershell
conda run -n cenv python scripts/audit_small_scenario.py data/raw/small_v1/scn_<id>
conda run -n cenv python scripts/audit_small_scenario.py --quiet --campaign data/campaigns/campaign_D_full_20261125T173105Z_35c196
```

Results are written to `data/audits/v_<auditor-sha12>/`. Collection-time audits are never
overwritten. The exit code is 1 if any experiment fails.

### 2.7 Build and validate the dataset

```powershell
conda run -n cenv python scripts/build_small_dataset.py `
  --v2-campaigns data/campaigns/campaign_B_full_20261125T155024Z_bef001 data/campaigns/campaign_C_full_20261125T165402Z_db0b5f data/campaigns/campaign_D_full_20261125T173105Z_35c196 `
  --v1-campaigns data/campaigns/campaign_20261125T134916Z_249a1c data/campaigns/campaign_20261125T140815Z_f24de3 `
  --out data/processed/small_dataset_v2 --report docs/SMALL_DATASET_CARD.md
```

- To check reproducibility without touching the validated dataset, use `--out data/interim/rebuild_check`
  and omit `--report`.
- The 19 quality checks are printed, and they are also stored in `quality_report.json`.
- The exit code is 1 if any check fails.

### 2.8 Reproduce the SMALL reports

```powershell
conda run -n cenv python scripts/analyze_small_scenarios.py --campaigns data/campaigns/campaign_B_full_20261125T155024Z_bef001 --title "SMALL Stage B - link failures under background UDP load (full campaign)" --out docs/small_stageB_report.md
conda run -n cenv python scripts/analyze_small_scenarios.py --campaigns data/campaigns/campaign_C_full_20261125T165402Z_db0b5f --title "SMALL Stage C - degradations (delay, loss, bandwidth/congestion), full campaign" --out docs/small_stageC_report.md
conda run -n cenv python scripts/analyze_small_scenarios.py --campaigns data/campaigns/campaign_D_full_20261125T173105Z_35c196 --title "SMALL Stage D - node failures (switch power-off, silent black hole, host power-off), full campaign" --out docs/small_stageD_report.md
```

For the combined report, pass all three campaign folders and write to
`docs/small_all_scenarios_report.md`. `docs/SMALL_FINAL_VALIDATION.md` is written by hand from
these reports.

### 2.9 Data catalogue and integrity

```powershell
conda run -n cenv python scripts/catalog_small_data.py --verify   # check repository + archive against data/catalog/SHA256SUMS
conda run -n cenv python scripts/catalog_small_data.py            # re-catalogue AFTER adding new evidence
```

### 2.10 Clean-up after an interrupted experiment

```bash
sudo -n ovs-vsctl list-br          # should print nothing
sudo mn -c                         # [root] only if bridges or stale namespaces remain
```

---

## 3. Diagnostic utilities (`scripts/diagnostics/`)

These are supported but are not part of the experimental workflow.

| Script | Use |
|---|---|
| `scripts/diagnostics/capture_small_tool_fixtures.py` | **[root]** Regenerates `tests/fixtures/*.txt` (real ping, tc and ip outputs) after a tool upgrade |
| `scripts/diagnostics/probe_iperf_fault_behavior.py` | **[root]** Re-checks how an iperf3 UDP flow behaves across link faults; writes `data/raw/small_v1/design_probe_<id>/` |

---

## 4. Legacy commands (`scripts/legacy/`): historical, not maintained

These scripts produced the **v1** evidence: the 18 legacy link-failure experiments in the dataset,
the earlier development runs, the load pilot and the failed Stage A attempts.

- They are kept so that this evidence remains explainable and reproducible.
- Their logic is frozen. They were only re-pathed when moved, and their outputs now go to
  `docs/history/small_v1/`.
- Do not use them for new work.

| Legacy script | Produced | Superseded by |
|---|---|---|
| `scripts/legacy/collect_small_experiment.py`, `scripts/legacy/collect_small_with_ports.py` | v1 experiments `exp_*` | `scripts/run_small_scenario.py` |
| `scripts/legacy/run_small_link_campaign.py` | v1 campaigns `campaign_2026…` | `scripts/run_small_scenario_campaign.py` |
| `scripts/legacy/audit_experiment.py`, `scripts/legacy/audit_port_experiment.py` | `docs/history/small_v1/audit_*.md` | `scripts/audit_small_scenario.py` |
| `scripts/legacy/analyze_small_campaign.py`, `scripts/legacy/analyze_small_repeatability.py` | v1 signature and repeatability reports | `scripts/analyze_small_scenarios.py` |
| `scripts/legacy/pilot_small_background_traffic.py`, `scripts/legacy/audit_small_load_pilot.py` | `load_pilot_*` (client-side only) | Stage A plus v2 traffic segments |
| `scripts/legacy/diagnose_small_iperf_receiver.py` | read-only Stage A diagnosis | `scripts/verify_small_iperf_receiver.py --reanalyze` |
| `scripts/legacy/demo_link_failure.py` | manual demo (**starts Mininet immediately; it has no `--help`**) | `scripts/run_small_scenario.py` |

All of them require `sudo` in WSL except the analysis and audit scripts. They run with
`sudo /usr/bin/python3 scripts/legacy/<name>.py`.

---

## 5. Safety rules

- Never edit anything under `data/raw`, `data/campaigns` or `data/audits/*` (in the repository or the
  archive): new runs always create new folders. Raw folder paths are referenced by manifests and by
  the dataset. Move a folder only to the same relative path in the archive, and re-verify the catalogue.
- Do not modify `src/smartmall/*.py` or `scripts/run_small_scenario*.py` while a campaign is running.
  Manifests record the source hashes at campaign start.
- Changing `src/smartmall/audit.py` creates a new auditor version: re-audit into a new
  `data/audits/v_<sha12>/` folder and keep the old ones.
- Smoke tests go to `--raw-root /tmp/…` and `--out-dir /tmp/…`.
