# SMALL - all scenario families (Stages B, C, D)

- Campaigns: `campaign_B_full_20261125T155024Z_bef001`, `campaign_C_full_20261125T165402Z_db0b5f`, `campaign_D_full_20261125T173105Z_35c196`
- Runs planned/executed: 147; audited PASS: **147**; FAIL or not run: **0**
- Protocol: small_scenario_v2 (3 phases x 3 windows x 4 s; 6 concurrent ICMP probes/window, 3 echo requests each; 12 interfaces sampled before/after each window)
- Every experiment was re-audited with the current `src/smartmall/audit.py` for this report.

## 1. Inventory

| Scenario | Load Mb/s | Runs | PASS |
|---|---:|---:|---:|
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 0 | 3 | 3 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 5 | 3 | 3 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 3 | 3 |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 3 | 3 |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 3 | 3 |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 3 | 3 |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 3 | 3 |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 3 | 3 |
| `LINK_FAILURE:L1` | 0 | 3 | 3 |
| `LINK_FAILURE:L1` | 5 | 3 | 3 |
| `LINK_FAILURE:L1` | 40 | 3 | 3 |
| `LINK_FAILURE:L2` | 0 | 3 | 3 |
| `LINK_FAILURE:L2` | 5 | 3 | 3 |
| `LINK_FAILURE:L2` | 40 | 3 | 3 |
| `LINK_FAILURE:L3` | 0 | 3 | 3 |
| `LINK_FAILURE:L3` | 5 | 3 | 3 |
| `LINK_FAILURE:L3` | 40 | 3 | 3 |
| `LINK_FAILURE:L4` | 0 | 3 | 3 |
| `LINK_FAILURE:L4` | 5 | 3 | 3 |
| `LINK_FAILURE:L4` | 40 | 3 | 3 |
| `LINK_FAILURE:L5` | 0 | 3 | 3 |
| `LINK_FAILURE:L5` | 5 | 3 | 3 |
| `LINK_FAILURE:L5` | 40 | 3 | 3 |
| `LINK_FAILURE:L6` | 0 | 3 | 3 |
| `LINK_FAILURE:L6` | 5 | 3 | 3 |
| `LINK_FAILURE:L6` | 40 | 3 | 3 |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 3 | 3 |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 3 | 3 |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 3 | 3 |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 3 | 3 |
| `NODE_FAILURE:DSW-1` | 0 | 3 | 3 |
| `NODE_FAILURE:DSW-1` | 5 | 3 | 3 |
| `NODE_FAILURE:PC-ADM` | 5 | 3 | 3 |
| `NODE_FAILURE:PC-SHOP` | 5 | 3 | 3 |
| `NODE_FAILURE:POS` | 5 | 3 | 3 |
| `NODE_FAILURE:SRV-LOCAL` | 5 | 3 | 3 |
| `NODE_FAILURE:SW-ADM` | 0 | 3 | 3 |
| `NODE_FAILURE:SW-ADM` | 5 | 3 | 3 |
| `NODE_FAILURE:SW-COM` | 0 | 3 | 3 |
| `NODE_FAILURE:SW-COM` | 5 | 3 | 3 |
| `NONE:-` | 0 | 3 | 3 |
| `NONE:-` | 5 | 3 | 3 |
| `NONE:-` | 40 | 3 | 3 |
| `SWITCH_BLACKHOLE:DSW-1` | 0 | 3 | 3 |
| `SWITCH_BLACKHOLE:DSW-1` | 5 | 3 | 3 |
| `SWITCH_BLACKHOLE:SW-ADM` | 0 | 3 | 3 |
| `SWITCH_BLACKHOLE:SW-ADM` | 5 | 3 | 3 |
| `SWITCH_BLACKHOLE:SW-COM` | 0 | 3 | 3 |
| `SWITCH_BLACKHOLE:SW-COM` | 5 | 3 | 3 |

## 2. Audit failures

None. Every executed run passed every audit check.

## 3. Connectivity signatures in FAILED windows (host-pair ICMP only)

Signature = set of host pairs unreachable in a FAILED window. `route_unreachable` probes (source had no usable local route: 0 packets sent, loss undefined) are counted separately from ICMP loss.

| Scenario | Runs | Distinct signatures across runs/windows | Unreachable pairs | ICMP-loss probes/run | Route-unreachable probes/run |
|---|---:|---:|---|---:|---:|
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 9 | 1 | (none) | 0 | 0 |
| `LINK_DELAY:L2[added_delay_ms=20]` | 6 | 1 | (none) | 0 | 0 |
| `LINK_DELAY:L5[added_delay_ms=20]` | 6 | 1 | (none) | 0 | 0 |
| `LINK_DELAY:L5[added_delay_ms=5]` | 3 | 1 | (none) | 0 | 0 |
| `LINK_FAILURE:L1` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `LINK_FAILURE:L2` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `LINK_FAILURE:L3` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | 0 | 9 |
| `LINK_FAILURE:L4` | 9 | 1 | PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 9 | 0 |
| `LINK_FAILURE:L5` | 9 | 1 | PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | 3 | 6 |
| `LINK_FAILURE:L6` | 9 | 1 | PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | 6 | 3 |
| `LINK_LOSS:L2[loss_pct=5]` | 6 | 1 | (none) | 0 | 0 |
| `LINK_LOSS:L5[loss_pct=5]` | 6 | 1 | (none) | 0 | 0 |
| `NODE_FAILURE:DSW-1` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `NODE_FAILURE:PC-ADM` | 3 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | 0 | 9 |
| `NODE_FAILURE:PC-SHOP` | 3 | 1 | PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | 3 | 6 |
| `NODE_FAILURE:POS` | 3 | 1 | PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | 6 | 3 |
| `NODE_FAILURE:SRV-LOCAL` | 3 | 1 | PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 9 | 0 |
| `NODE_FAILURE:SW-ADM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `NODE_FAILURE:SW-COM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `NONE:-` | 9 | 1 | (none) | 0 | 0 |
| `SWITCH_BLACKHOLE:DSW-1` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `SWITCH_BLACKHOLE:SW-ADM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `SWITCH_BLACKHOLE:SW-COM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |

### Distinguishability from host-pair connectivity alone

| Signature (unreachable pairs) | Scenarios sharing it |
|---|---|
| (no pair unreachable) | `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]`, `LINK_DELAY:L2[added_delay_ms=20]`, `LINK_DELAY:L5[added_delay_ms=20]`, `LINK_DELAY:L5[added_delay_ms=5]`, `LINK_LOSS:L2[loss_pct=5]`, `LINK_LOSS:L5[loss_pct=5]`, `NONE:-` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `LINK_FAILURE:L1`, `LINK_FAILURE:L2`, `NODE_FAILURE:DSW-1`, `SWITCH_BLACKHOLE:DSW-1` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | `LINK_FAILURE:L3`, `NODE_FAILURE:PC-ADM` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:SW-ADM`, `SWITCH_BLACKHOLE:SW-ADM` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:SW-COM`, `SWITCH_BLACKHOLE:SW-COM` |
| PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | `LINK_FAILURE:L5`, `NODE_FAILURE:PC-SHOP` |
| PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | `LINK_FAILURE:L6`, `NODE_FAILURE:POS` |
| PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `LINK_FAILURE:L4`, `NODE_FAILURE:SRV-LOCAL` |

### Interface-state pattern in FAILED windows (admin_up/carrier per interface)

Shows which interfaces deviate from (admin_up=1, carrier=1). These states are produced directly by the injection mechanism and therefore *reveal* admin-down faults (leakage for ML).

| Scenario | Interfaces deviating (node:link admin/carrier) |
|---|---|
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | none (all admin-up with carrier) |
| `LINK_DELAY:L2[added_delay_ms=20]` | none (all admin-up with carrier) |
| `LINK_DELAY:L5[added_delay_ms=20]` | none (all admin-up with carrier) |
| `LINK_DELAY:L5[added_delay_ms=5]` | none (all admin-up with carrier) |
| `LINK_FAILURE:L1` | DSW-1:L1 0/0; SW-ADM:L1 0/0 |
| `LINK_FAILURE:L2` | DSW-1:L2 0/0; SW-COM:L2 0/0 |
| `LINK_FAILURE:L3` | PC-ADM:L3 0/0; SW-ADM:L3 0/0 |
| `LINK_FAILURE:L4` | SRV-LOCAL:L4 0/0; SW-ADM:L4 0/0 |
| `LINK_FAILURE:L5` | PC-SHOP:L5 0/0; SW-COM:L5 0/0 |
| `LINK_FAILURE:L6` | POS:L6 0/0; SW-COM:L6 0/0 |
| `LINK_LOSS:L2[loss_pct=5]` | none (all admin-up with carrier) |
| `LINK_LOSS:L5[loss_pct=5]` | none (all admin-up with carrier) |
| `NODE_FAILURE:DSW-1` | DSW-1:L1 0/0; DSW-1:L2 0/0; SW-ADM:L1 1/0; SW-COM:L2 1/0 |
| `NODE_FAILURE:PC-ADM` | PC-ADM:L3 0/0; SW-ADM:L3 1/0 |
| `NODE_FAILURE:PC-SHOP` | PC-SHOP:L5 0/0; SW-COM:L5 1/0 |
| `NODE_FAILURE:POS` | POS:L6 0/0; SW-COM:L6 1/0 |
| `NODE_FAILURE:SRV-LOCAL` | SRV-LOCAL:L4 0/0; SW-ADM:L4 1/0 |
| `NODE_FAILURE:SW-ADM` | DSW-1:L1 1/0; PC-ADM:L3 1/0; SRV-LOCAL:L4 1/0; SW-ADM:L1 0/0; SW-ADM:L3 0/0; SW-ADM:L4 0/0 |
| `NODE_FAILURE:SW-COM` | DSW-1:L2 1/0; PC-SHOP:L5 1/0; POS:L6 1/0; SW-COM:L2 0/0; SW-COM:L5 0/0; SW-COM:L6 0/0 |
| `NONE:-` | none (all admin-up with carrier) |
| `SWITCH_BLACKHOLE:DSW-1` | none (all admin-up with carrier) |
| `SWITCH_BLACKHOLE:SW-ADM` | none (all admin-up with carrier) |
| `SWITCH_BLACKHOLE:SW-COM` | none (all admin-up with carrier) |

## 4. Background UDP flow PC-SHOP → SRV-LOCAL (receiver-side, per phase)

Receiver Mb/s = iperf3 server intervals allocated to windows (alignment-unreliable windows adjacent to transitions excluded). Dst NIC = SRV-LOCAL ingress counter rate (includes headers).

| Scenario | Load | Flow relation | Healthy rx Mb/s | FAILED rx Mb/s | FAILED dst NIC Mb/s | FAILED src NIC tx Mb/s | Sender aborted | Recovered rx Mb/s |
|---|---:|---|---|---|---|---|---|---|
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 5 | flow_impaired | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.182 ± 0.014 | 5.182 ± 0.013 | 0/3 | 5.000 ± 0.001 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | flow_impaired | 40.005 ± 0.012 | 9.587 ± 0.049 | 9.932 ± 0.053 | 9.932 ± 0.054 | 0/3 | 39.997 ± 0.008 |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | flow_impaired | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.177 ± 0.002 | 5.176 ± 0.002 | 0/3 | 5.000 ± 0.004 |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | flow_impaired | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.177 ± 0.001 | 5.173 ± 0.009 | 0/3 | 5.000 ± 0.001 |
| `LINK_FAILURE:L1` | 5 | flow_disconnected | 5.001 ± 0.003 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `LINK_FAILURE:L1` | 40 | flow_disconnected | 39.987 ± 0.031 | 0.000 ± 0.000 | 0.001 ± 0.000 | 41.451 ± 0.117 | 0/3 | 40.000 ± 0.001 |
| `LINK_FAILURE:L2` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.183 ± 0.015 | 0/3 | 5.000 ± 0.001 |
| `LINK_FAILURE:L2` | 40 | flow_disconnected | 39.996 ± 0.119 | 0.000 ± 0.000 | 0.001 ± 0.000 | 41.442 ± 0.108 | 0/3 | 40.000 ± 0.001 |
| `LINK_FAILURE:L3` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.176 ± 0.001 | 5.176 ± 0.002 | 0/3 | 5.000 ± 0.001 |
| `LINK_FAILURE:L3` | 40 | flow_not_on_fault_path | 40.000 ± 0.002 | 39.999 ± 0.007 | 41.400 ± 0.009 | 41.399 ± 0.007 | 0/3 | 40.005 ± 0.021 |
| `LINK_FAILURE:L4` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.002 |
| `LINK_FAILURE:L4` | 40 | flow_disconnected | 40.000 ± 0.009 | 0.000 ± 0.000 | 0.000 ± 0.000 | 41.446 ± 0.116 | 0/3 | 40.000 ± 0.009 |
| `LINK_FAILURE:L5` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 3/3 | 5.000 ± 0.002 |
| `LINK_FAILURE:L5` | 40 | flow_disconnected | 40.000 ± 0.004 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 3/3 | 40.001 ± 0.016 |
| `LINK_FAILURE:L6` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.176 ± 0.001 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `LINK_FAILURE:L6` | 40 | flow_not_on_fault_path | 39.985 ± 0.035 | 40.000 ± 0.001 | 41.399 ± 0.004 | 41.401 ± 0.004 | 0/3 | 40.000 ± 0.001 |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | flow_impaired | 5.000 ± 0.002 | 4.748 ± 0.021 | 4.917 ± 0.025 | 5.180 ± 0.003 | 0/3 | 5.000 ± 0.001 |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | flow_impaired | 5.000 ± 0.001 | 4.739 ± 0.017 | 4.911 ± 0.018 | 4.911 ± 0.020 | 0/3 | 5.000 ± 0.002 |
| `NODE_FAILURE:DSW-1` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:PC-ADM` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.176 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.003 |
| `NODE_FAILURE:PC-SHOP` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 3/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:POS` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.175 ± 0.001 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SRV-LOCAL` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SW-ADM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.180 ± 0.010 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SW-COM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 0/3 | 5.000 ± 0.001 |
| `NONE:-` | 5 | no_fault | 5.000 ± 0.001 | 5.000 ± 0.000 | 5.177 ± 0.001 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NONE:-` | 40 | no_fault | 40.000 ± 0.001 | 39.998 ± 0.006 | 41.397 ± 0.004 | 41.400 ± 0.002 | 0/3 | 40.000 ± 0.011 |
| `SWITCH_BLACKHOLE:DSW-1` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `SWITCH_BLACKHOLE:SW-ADM` | 5 | flow_disconnected | 5.000 ± 0.005 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.181 ± 0.011 | 0/3 | 5.000 ± 0.001 |
| `SWITCH_BLACKHOLE:SW-COM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.181 ± 0.011 | 0/3 | 5.000 ± 0.001 |

## 5. RTT by background load (HEALTHY windows, all reachable probes)

Every host pair shares at least one link with the flow path in this tree, so the exact flow pair (PC-SHOP~SRV-LOCAL, same 4 links as the UDP flow) is reported separately.

| Load Mb/s | Probes | Mean RTT ms | Median | P95 | Max | PC-SHOP~SRV-LOCAL mean RTT ms |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1026 | 7.252 | 8.329 | 9.503 | 26.517 | 8.629 |
| 5 | 1188 | 7.134 | 8.301 | 9.133 | 20.406 | 8.501 |
| 40 | 432 | 7.457 | 8.290 | 10.782 | 22.988 | 8.953 |

## 6. Configured vs observed effects

| Scenario | Load | Rep | Check | Result | Observation |
|---|---:|---:|---|---|---|
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 0 | 1 | effect_bw_idle_unobservable | PASS | no load: impaired-pair max |path-delay shift| 0.042 ms, drops=0 (a capacity cap is not observable without traffic) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 0 | 2 | effect_bw_idle_unobservable | PASS | no load: impaired-pair max |path-delay shift| 0.074 ms, drops=0 (a capacity cap is not observable without traffic) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 0 | 3 | effect_bw_idle_unobservable | PASS | no load: impaired-pair max |path-delay shift| 0.045 ms, drops=0 (a capacity cap is not observable without traffic) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 5 | 1 | effect_bw_not_binding | PASS | receiver 4.9999 Mb/s at offered 5 < cap 10.0; drops=0 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 5 | 2 | effect_bw_not_binding | PASS | receiver 4.9998 Mb/s at offered 5 < cap 10.0; drops=0 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 5 | 3 | effect_bw_not_binding | PASS | receiver 4.9993 Mb/s at offered 5 < cap 10.0; drops=0 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 1 | effect_bw_throughput_capped | PASS | receiver 9.7351 Mb/s <= cap 10.0 Mb/s (offered 40) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 1 | effect_congestion_drops_observed | PASS | qdisc drops=38014, receiver lost=38612 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 2 | effect_bw_throughput_capped | PASS | receiver 9.7739 Mb/s <= cap 10.0 Mb/s (offered 40) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 2 | effect_congestion_drops_observed | PASS | qdisc drops=38094, receiver lost=38777 |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 3 | effect_bw_throughput_capped | PASS | receiver 9.5871 Mb/s <= cap 10.0 Mb/s (offered 40) |
| `LINK_BANDWIDTH:L5[bw_mbps=10,queue_pkts=100]` | 40 | 3 | effect_congestion_drops_observed | PASS | qdisc drops=37882, receiver lost=38948 |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 1 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.07 ms (mean RTT 4.165 -> 4.294 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 1 | effect_delay_rtt_increase | PASS | path-delay increase +40.122 ms (mean-RTT +40.198) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 2 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.011 ms (mean RTT 4.186 -> 4.266 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 2 | effect_delay_rtt_increase | PASS | path-delay increase +40.072 ms (mean-RTT +40.158) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 3 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.028 ms (mean RTT 4.364 -> 4.194 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 0 | 3 | effect_delay_rtt_increase | PASS | path-delay increase +40.043 ms (mean-RTT +39.739) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 1 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.031 ms (mean RTT 5.196 -> 4.455 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 1 | effect_delay_rtt_increase | PASS | path-delay increase +40.063 ms (mean-RTT +39.017) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 2 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.037 ms (mean RTT 4.226 -> 4.263 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 2 | effect_delay_rtt_increase | PASS | path-delay increase +40.02 ms (mean-RTT +38.996) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 3 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.025 ms (mean RTT 4.188 -> 4.168 ms) |
| `LINK_DELAY:L2[added_delay_ms=20]` | 5 | 3 | effect_delay_rtt_increase | PASS | path-delay increase +39.998 ms (mean-RTT +39.996) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 1 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.043 ms (mean RTT 6.966 -> 6.988 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 1 | effect_delay_rtt_increase | PASS | path-delay increase +40.034 ms (mean-RTT +40.228) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 2 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.126 ms (mean RTT 10.522 -> 7.931 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 2 | effect_delay_rtt_increase | PASS | path-delay increase +40.121 ms (mean-RTT +38.151) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 3 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.119 ms (mean RTT 7.784 -> 8.215 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 0 | 3 | effect_delay_rtt_increase | PASS | path-delay increase +40.143 ms (mean-RTT +39.874) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 1 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.028 ms (mean RTT 7.116 -> 7.405 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 1 | effect_delay_rtt_increase | PASS | path-delay increase +40.033 ms (mean-RTT +39.934) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 2 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.031 ms (mean RTT 6.9 -> 6.955 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 2 | effect_delay_rtt_increase | PASS | path-delay increase +39.996 ms (mean-RTT +40.007) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 3 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.047 ms (mean RTT 7.708 -> 7.072 ms) |
| `LINK_DELAY:L5[added_delay_ms=20]` | 5 | 3 | effect_delay_rtt_increase | PASS | path-delay increase +39.982 ms (mean-RTT +39.395) vs configured round-trip +40.0 ms |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 1 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.163 ms (mean RTT 7.957 -> 7.438 ms) |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 1 | effect_delay_rtt_increase | PASS | path-delay increase +10.109 ms (mean-RTT +10.05) vs configured round-trip +10.0 ms |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 2 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.046 ms (mean RTT 7.21 -> 7.001 ms) |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 2 | effect_delay_rtt_increase | PASS | path-delay increase +10.097 ms (mean-RTT +9.713) vs configured round-trip +10.0 ms |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 3 | effect_delay_isolated_to_impaired_pairs | PASS | other pairs max |path-delay shift| 0.058 ms (mean RTT 7.006 -> 7.024 ms) |
| `LINK_DELAY:L5[added_delay_ms=5]` | 0 | 3 | effect_delay_rtt_increase | PASS | path-delay increase +10.019 ms (mean-RTT +9.678) vs configured round-trip +10.0 ms |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 1 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 7.5% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 1 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 2 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 8.33% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 2 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 3 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 8.33% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 0 | 3 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 1 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 10.83% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 1 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 1 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.84% vs configured 5.0% (one traversal) |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 2 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 10.83% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 2 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 2 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.725% vs configured 5.0% (one traversal) |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 3 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 9.17% (configured 5.0%/direction) |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 3 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L2[loss_pct=5]` | 5 | 3 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.94% vs configured 5.0% (one traversal) |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 1 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 16.67% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 1 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 2 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 12.22% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 2 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 3 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 11.11% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 0 | 3 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 1 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 8.89% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 1 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 1 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.964% vs configured 5.0% (one traversal) |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 2 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 8.89% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 2 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 2 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.824% vs configured 5.0% (one traversal) |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 3 | effect_loss_icmp_observed | PASS | impaired-pair ICMP loss 11.11% (configured 5.0%/direction) |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 3 | effect_loss_isolated | PASS | other pairs ICMP loss 0.0% |
| `LINK_LOSS:L5[loss_pct=5]` | 5 | 3 | effect_loss_receiver_udp | PASS | UDP receiver loss 4.743% vs configured 5.0% (one traversal) |

## 7. Recovery

- All PASS runs regained full 6-pair reachability; first full-reachability check at 0.99–1.05 s after restoration (check granularity ≈1 s, so this is an upper bound).
- tc configuration restored to baseline and all interfaces admin-up with carrier in every PASS run; no OVS bridges left after Mininet stop.

