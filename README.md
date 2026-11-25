# SmartMall Network Digital Twin

A Mininet-based digital twin of a shopping-mall LAN for research on **graph-based network fault
detection, localization and simulation**.

The twin emulates the mall topology. It injects controlled faults and degradations while
background traffic runs, collects ICMP, interface, queue and receiver-side traffic telemetry, audits
every experiment, and exports graph-ready datasets in which the ground truth is kept separate from
the features.

## Objectives and scope

- Emulate SMALL, MEDIUM and LARGE mall topologies (`topologies/*.json`).
- Inject faults with verified mechanisms and verified restoration:
  - link failure
  - link delay, loss and bandwidth limitation, including congestion
  - switch and host power-off
  - silent switch data-plane failure (black hole)
- Produce reproducible, audited, leakage-reviewed datasets for later GNN work.

**Status**:

- SMALL is complete and validated. See [`docs/SMALL_FINAL_VALIDATION.md`](docs/SMALL_FINAL_VALIDATION.md).
- MEDIUM and LARGE topologies are defined but have not been emulated yet.
- No ML model is trained in this repository yet.

## Repository layout

```
src/smartmall/            reusable library (stdlib only, no Mininet), except emulation.py
  iperf_receiver.py       receiver-side iperf3 UDP extraction (Stage A fix)
  topology.py             reachability, paths, expected fault signatures
  telemetry.py            ping/tc parsing, counter deltas, receiver-window allocation
  scenarios.py            fault families, validation, ground-truth expectations
  audit.py                per-experiment auditor (versioned by its SHA-256)
  dataset.py              consolidated dataset, folds, feature dictionary
  graph_loader.py         per-window graph snapshots (pure Python)
  emulation.py            Mininet topology builder and interface helpers (WSL/Mininet only)
scripts/                  official command-line entry points (see docs/OPERATIONS.md)
  diagnostics/            supported one-off diagnostic tools
  legacy/                 frozen v1 scripts that produced the historical evidence
configs/                  campaign configurations (seeded)
topologies/               small.json, medium.json, large.json
tests/                    unittest suite and real tool-output fixtures
data/                     processed dataset and evidence catalogue (raw evidence: external archive, see data/README.md)
docs/                     reports, dataset card, operations reference, history/
models/, notebooks/       reserved for the ML and exploration phases
```

## Requirements

| Use | Environment |
|---|---|
| Tests, audits, analysis, dataset build | Python ≥ 3.10, **standard library only** (Windows Conda `cenv` or WSL `python3`) |
| Topology validation and figures | plus `networkx` and `matplotlib` (available in `cenv`) |
| Experiments | Ubuntu 22.04 (WSL2) with Mininet 2.3.0, Open vSwitch 2.17, iperf3 3.9, iproute2; `sudo` |

No installation step is required: the scripts locate `src/` themselves. Audits, reports, the
dataset rebuild and most tests read the raw evidence from the external archive
(`../smartmall-data-archive`, or set `SMARTMALL_ARCHIVE`). Environment checks are in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md#1-environments).

## Quick start

```powershell
# Windows (cenv): run the test suite and verify the evidence integrity
conda run -n cenv python -m unittest discover -s tests
conda run -n cenv python scripts/catalog_small_data.py --verify
conda run -n cenv python scripts/validate_topology.py topologies/small.json
```
```bash
# Ubuntu WSL2, repository root
sudo /usr/bin/python3 scripts/run_small_mininet.py                                     # smoke test
python3 scripts/run_small_scenario_campaign.py configs/small_stageB_pilot.json --dry-run
sudo /usr/bin/python3 scripts/run_small_scenario.py --fault-type LINK_FAILURE --target L5 --load-mbps 5 --raw-root /tmp/smartmall_smoke
```

## SMALL experimental workflow

1. **Configure**: write a campaign config in `configs/` (scenarios × loads × repetitions, seed).
2. **Dry run**: `scripts/run_small_scenario_campaign.py <config> --dry-run` prints the run order and
   the time and disk estimates.
3. **Run** (root): each experiment runs HEALTHY → FAILED → RECOVERED in 4 s windows, with concurrent
   ICMP probes, interface and tc samples, and an iperf3 flow spanning the injection. Ground truth goes
   only to `incident.json`.
4. **Audit**: every run is audited at collection time. Re-audit with `scripts/audit_small_scenario.py`.
5. **Analyse**: run `scripts/analyze_small_scenarios.py` to produce the Markdown report.
6. **Dataset**: run `scripts/build_small_dataset.py` to produce the feature tables, the separate
   labels, the leakage-classified dictionary, experiment-level folds and the quality report.

## Validated results

| Artefact | Location |
|---|---|
| Final SMALL validation report | [`docs/SMALL_FINAL_VALIDATION.md`](docs/SMALL_FINAL_VALIDATION.md) |
| Validated dataset (165 experiments, 1,431 windows) | `data/processed/small_dataset_v2/`, described in [`docs/SMALL_DATASET_CARD.md`](docs/SMALL_DATASET_CARD.md) |
| Stage reports | [`docs/README.md`](docs/README.md) |
| Raw evidence (external archive) and integrity catalogue | `../smartmall-data-archive/` or `$SMARTMALL_ARCHIVE`; `data/catalog/` ([`data/README.md`](data/README.md)) |

## Tests and audits

```powershell
conda run -n cenv python -m unittest discover -s tests                     # 55 tests, no root
conda run -n cenv python scripts/audit_small_scenario.py --quiet --campaign data/campaigns/campaign_B_full_20261125T155024Z_bef001
```

## Roadmap

- [x] **SMALL** (7 nodes, 6 links): Stages A–F complete (receiver verification; link failures under
  load; degradations; node failures; dataset; final validation).
- [ ] **MEDIUM**: generalise the topology builder, flow endpoints and per-window row counts; choose a
  probe-selection policy; enable STP if the topology has loops. See section 12 of the final report.
- [ ] **LARGE**: the same, plus a runtime budget estimated with the campaign dry run.
- [ ] Data Engineering and GNN phase, on top of `src/smartmall/graph_loader.py`.
