# SMALL Stage D - node failures (switch power-off, silent black hole, host power-off), full campaign

- Campaigns: `campaign_D_full_20261125T173105Z_35c196`
- Runs planned/executed: 48; audited PASS: **48**; FAIL or not run: **0**
- Protocol: small_scenario_v2 (3 phases x 3 windows x 4 s; 6 concurrent ICMP probes/window, 3 echo requests each; 12 interfaces sampled before/after each window)
- Every experiment was re-audited with the current `src/smartmall/audit.py` for this report.

## 1. Inventory

| Scenario | Load Mb/s | Runs | PASS |
|---|---:|---:|---:|
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
| `NODE_FAILURE:DSW-1` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `NODE_FAILURE:PC-ADM` | 3 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | 0 | 9 |
| `NODE_FAILURE:PC-SHOP` | 3 | 1 | PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | 3 | 6 |
| `NODE_FAILURE:POS` | 3 | 1 | PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | 6 | 3 |
| `NODE_FAILURE:SRV-LOCAL` | 3 | 1 | PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 9 | 0 |
| `NODE_FAILURE:SW-ADM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `NODE_FAILURE:SW-COM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `SWITCH_BLACKHOLE:DSW-1` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `SWITCH_BLACKHOLE:SW-ADM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |
| `SWITCH_BLACKHOLE:SW-COM` | 6 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 15 | 0 |

### Distinguishability from host-pair connectivity alone

| Signature (unreachable pairs) | Scenarios sharing it |
|---|---|
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:SW-ADM`, `SWITCH_BLACKHOLE:SW-ADM` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:SW-COM`, `SWITCH_BLACKHOLE:SW-COM` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:DSW-1`, `SWITCH_BLACKHOLE:DSW-1` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | `NODE_FAILURE:PC-ADM` |
| PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | `NODE_FAILURE:PC-SHOP` |
| PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | `NODE_FAILURE:POS` |
| PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `NODE_FAILURE:SRV-LOCAL` |

### Interface-state pattern in FAILED windows (admin_up/carrier per interface)

Shows which interfaces deviate from (admin_up=1, carrier=1). These states are produced directly by the injection mechanism and therefore *reveal* admin-down faults (leakage for ML).

| Scenario | Interfaces deviating (node:link admin/carrier) |
|---|---|
| `NODE_FAILURE:DSW-1` | DSW-1:L1 0/0; DSW-1:L2 0/0; SW-ADM:L1 1/0; SW-COM:L2 1/0 |
| `NODE_FAILURE:PC-ADM` | PC-ADM:L3 0/0; SW-ADM:L3 1/0 |
| `NODE_FAILURE:PC-SHOP` | PC-SHOP:L5 0/0; SW-COM:L5 1/0 |
| `NODE_FAILURE:POS` | POS:L6 0/0; SW-COM:L6 1/0 |
| `NODE_FAILURE:SRV-LOCAL` | SRV-LOCAL:L4 0/0; SW-ADM:L4 1/0 |
| `NODE_FAILURE:SW-ADM` | DSW-1:L1 1/0; PC-ADM:L3 1/0; SRV-LOCAL:L4 1/0; SW-ADM:L1 0/0; SW-ADM:L3 0/0; SW-ADM:L4 0/0 |
| `NODE_FAILURE:SW-COM` | DSW-1:L2 1/0; PC-SHOP:L5 1/0; POS:L6 1/0; SW-COM:L2 0/0; SW-COM:L5 0/0; SW-COM:L6 0/0 |
| `SWITCH_BLACKHOLE:DSW-1` | none (all admin-up with carrier) |
| `SWITCH_BLACKHOLE:SW-ADM` | none (all admin-up with carrier) |
| `SWITCH_BLACKHOLE:SW-COM` | none (all admin-up with carrier) |

## 4. Background UDP flow PC-SHOP → SRV-LOCAL (receiver-side, per phase)

Receiver Mb/s = iperf3 server intervals allocated to windows (alignment-unreliable windows adjacent to transitions excluded). Dst NIC = SRV-LOCAL ingress counter rate (includes headers).

| Scenario | Load | Flow relation | Healthy rx Mb/s | FAILED rx Mb/s | FAILED dst NIC Mb/s | FAILED src NIC tx Mb/s | Sender aborted | Recovered rx Mb/s |
|---|---:|---|---|---|---|---|---|---|
| `NODE_FAILURE:DSW-1` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:PC-ADM` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.176 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.003 |
| `NODE_FAILURE:PC-SHOP` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 3/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:POS` | 5 | flow_not_on_fault_path | 5.000 ± 0.001 | 5.000 ± 0.001 | 5.175 ± 0.001 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SRV-LOCAL` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SW-ADM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.180 ± 0.010 | 0/3 | 5.000 ± 0.001 |
| `NODE_FAILURE:SW-COM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 0.000 ± 0.000 | 0/3 | 5.000 ± 0.001 |
| `SWITCH_BLACKHOLE:DSW-1` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.177 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `SWITCH_BLACKHOLE:SW-ADM` | 5 | flow_disconnected | 5.000 ± 0.005 | 0.000 ± 0.000 | 0.000 ± 0.000 | 5.181 ± 0.011 | 0/3 | 5.000 ± 0.001 |
| `SWITCH_BLACKHOLE:SW-COM` | 5 | flow_disconnected | 5.000 ± 0.001 | 0.000 ± 0.000 | 0.001 ± 0.000 | 5.181 ± 0.011 | 0/3 | 5.000 ± 0.001 |

## 5. RTT by background load (HEALTHY windows, all reachable probes)

Every host pair shares at least one link with the flow path in this tree, so the exact flow pair (PC-SHOP~SRV-LOCAL, same 4 links as the UDP flow) is reported separately.

| Load Mb/s | Probes | Mean RTT ms | Median | P95 | Max | PC-SHOP~SRV-LOCAL mean RTT ms |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 324 | 7.375 | 8.333 | 9.859 | 20.853 | 8.601 |
| 5 | 540 | 7.110 | 8.309 | 8.961 | 20.406 | 8.527 |

## 7. Recovery

- All PASS runs regained full 6-pair reachability; first full-reachability check at 1.00–1.03 s after restoration (check granularity ≈1 s, so this is an upper bound).
- tc configuration restored to baseline and all interfaces admin-up with carrier in every PASS run; no OVS bridges left after Mininet stop.

