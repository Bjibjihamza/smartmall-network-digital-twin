# `data/`: SmartMall results and evidence catalogue

The repository keeps **results only**:

| Path | Content | Written by |
|---|---|---|
| `processed/small_dataset_v2/` | **Validated SMALL dataset**: 165 experiments, 1,431 windows. See `docs/SMALL_DATASET_CARD.md` | `scripts/build_small_dataset.py` |
| `catalog/small_v1_inventory.csv` | Role of every raw experiment folder (dataset, pilot, smoke test, failed run…) | `scripts/catalog_small_data.py` |
| `catalog/SHA256SUMS` | SHA-256 of every evidence file (raw, campaigns, audits, processed) | `scripts/catalog_small_data.py` |

## Experimental evidence (external archive)

The raw measurements and their provenance are kept **outside git** in an archive with the same
relative layout. Its location is `$SMARTMALL_ARCHIVE`, otherwise the sibling folder `../smartmall-data-archive`.

| Archive path | Content | Mutable? |
|---|---|---|
| `data/raw/small_v1/<experiment>/` | Raw measurements, one folder per experiment (telemetry CSVs, iperf3 JSON, `incident.json` ground truth, `topology.json`, `runner_log.txt`). 1,925 files, about 37 MB | **never** |
| `data/campaigns/<campaign_id>/` | `config.json`, `manifest.json` (seed, run order, per-run seed, source SHA-256, collection-time verdicts), `summary.csv`, `audits_at_collection/` (**original** verdicts, including the original FAILs) | never |
| `data/audits/` | Collection-time audits and versioned re-audits `v_<auditor-sha12>/` | new folder per auditor version |
| `docs/history/` | v1-era reports of the legacy scripts | never |

All scripts and tests accept repository-relative paths such as `data/raw/small_v1/<exp>` and look
them up in the repository first, then in the archive (`src/smartmall/paths.py`). Check that the
archive is complete and unchanged with:

```powershell
conda run -n cenv python scripts/catalog_small_data.py --verify
```

`data/raw/`, `data/campaigns/` and `data/audits/` are git-ignored. New collections are written there
locally. Move them to the same paths in the archive, then re-run `scripts/catalog_small_data.py`.

## Experiment roles (`catalog/small_v1_inventory.csv`)

| Role | Count | Meaning |
|---|---:|---|
| `dataset` | 165 | 147 v2 runs (campaigns B, C, D full) + 18 v1 link-failure runs. They make up the validated dataset |
| `pilot` | 21 | Stage B, C and D pilot campaigns (single repetition; B pilot 1 predates the alignment fix) |
| `smoke_test` | 1 | First v2 smoke run (`scn_20261125T153343Z_19d369`), outside any campaign |
| `historical_v1_development` | 8 | Early v1 link-failure runs from before the repeatability campaigns |
| `failed_run` | 1 | `exp_20261125T133614Z_119124` (v1 run that failed, kept as evidence) |
| `stage_a_verification` / `stage_a_failed_attempt` | 3 / 3 | iperf3 receiver verification (Stage A) |
| `historical_pilot` | 1 | Pre-existing background-load pilot (client-side iperf3 only) |
| `design_evidence` | 1 | Probe of iperf3 behaviour across link faults |

## Notes

- **Pilot audits were overwritten early on**: for the B pilot campaigns, the collection-time files in
  `data/audits/` were overwritten by re-audits before audit versioning existed. Their collection-time
  verdicts are in each campaign's `manifest.json`. All later campaigns also keep `audits_at_collection/`.
- **Transient outputs**: use `data/interim/` (git-ignored) or a temporary directory, for example
  `--raw-root /tmp/smoke` for `scripts/run_small_scenario.py`.
- **Line endings**: `.gitattributes` keeps `data/**` byte-exact (`-text`).
