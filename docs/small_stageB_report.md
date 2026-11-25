# SMALL Stage B - link failures under background UDP load (full campaign)

- Campaigns: `campaign_B_full_20261125T155024Z_bef001`
- Runs planned/executed: 63; audited PASS: **63**; FAIL or not run: **0**
- Protocol: small_scenario_v2 (3 phases x 3 windows x 4 s; 6 concurrent ICMP probes/window, 3 echo requests each; 12 interfaces sampled before/after each window)
- Every experiment was re-audited with the current `src/smartmall/audit.py` for this report.

## 1. Inventory

| Scenario | Load Mb/s | Runs | PASS |
|---|---:|---:|---:|
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
| `NONE:-` | 0 | 3 | 3 |
| `NONE:-` | 5 | 3 | 3 |
| `NONE:-` | 40 | 3 | 3 |

## 2. Audit failures

None. Every executed run passed every audit check.

## 3. Connectivity signatures in FAILED windows (host-pair ICMP only)

Signature = set of host pairs unreachable in a FAILED window. `route_unreachable` probes (source had no usable local route: 0 packets sent, loss undefined) are counted separately from ICMP loss.

| Scenario | Runs | Distinct signatures across runs/windows | Unreachable pairs | ICMP-loss probes/run | Route-unreachable probes/run |
|---|---:|---:|---|---:|---:|
| `LINK_FAILURE:L1` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `LINK_FAILURE:L2` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 12 | 0 |
| `LINK_FAILURE:L3` | 9 | 1 | PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | 0 | 9 |
| `LINK_FAILURE:L4` | 9 | 1 | PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | 9 | 0 |
| `LINK_FAILURE:L5` | 9 | 1 | PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | 3 | 6 |
| `LINK_FAILURE:L6` | 9 | 1 | PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | 6 | 3 |
| `NONE:-` | 9 | 1 | (none) | 0 | 0 |

### Distinguishability from host-pair connectivity alone

| Signature (unreachable pairs) | Scenarios sharing it |
|---|---|
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `LINK_FAILURE:L1`, `LINK_FAILURE:L2` |
| (no pair unreachable) | `NONE:-` |
| PC-ADM~PC-SHOP, PC-ADM~POS, PC-ADM~SRV-LOCAL | `LINK_FAILURE:L3` |
| PC-ADM~PC-SHOP, PC-SHOP~POS, PC-SHOP~SRV-LOCAL | `LINK_FAILURE:L5` |
| PC-ADM~POS, PC-SHOP~POS, POS~SRV-LOCAL | `LINK_FAILURE:L6` |
| PC-ADM~SRV-LOCAL, PC-SHOP~SRV-LOCAL, POS~SRV-LOCAL | `LINK_FAILURE:L4` |

### Interface-state pattern in FAILED windows (admin_up/carrier per interface)

Shows which interfaces deviate from (admin_up=1, carrier=1). These states are produced directly by the injection mechanism and therefore *reveal* admin-down faults (leakage for ML).

| Scenario | Interfaces deviating (node:link admin/carrier) |
|---|---|
| `LINK_FAILURE:L1` | DSW-1:L1 0/0; SW-ADM:L1 0/0 |
| `LINK_FAILURE:L2` | DSW-1:L2 0/0; SW-COM:L2 0/0 |
| `LINK_FAILURE:L3` | PC-ADM:L3 0/0; SW-ADM:L3 0/0 |
| `LINK_FAILURE:L4` | SRV-LOCAL:L4 0/0; SW-ADM:L4 0/0 |
| `LINK_FAILURE:L5` | PC-SHOP:L5 0/0; SW-COM:L5 0/0 |
| `LINK_FAILURE:L6` | POS:L6 0/0; SW-COM:L6 0/0 |
| `NONE:-` | none (all admin-up with carrier) |

## 4. Background UDP flow PC-SHOP → SRV-LOCAL (receiver-side, per phase)

Receiver Mb/s = iperf3 server intervals allocated to windows (alignment-unreliable windows adjacent to transitions excluded). Dst NIC = SRV-LOCAL ingress counter rate (includes headers).

| Scenario | Load | Flow relation | Healthy rx Mb/s | FAILED rx Mb/s | FAILED dst NIC Mb/s | FAILED src NIC tx Mb/s | Sender aborted | Recovered rx Mb/s |
|---|---:|---|---|---|---|---|---|---|
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
| `NONE:-` | 5 | no_fault | 5.000 ± 0.001 | 5.000 ± 0.000 | 5.177 ± 0.001 | 5.176 ± 0.001 | 0/3 | 5.000 ± 0.001 |
| `NONE:-` | 40 | no_fault | 40.000 ± 0.001 | 39.998 ± 0.006 | 41.397 ± 0.004 | 41.400 ± 0.002 | 0/3 | 40.000 ± 0.011 |

## 5. RTT by background load (HEALTHY windows, all reachable probes)

Every host pair shares at least one link with the flow path in this tree, so the exact flow pair (PC-SHOP~SRV-LOCAL, same 4 links as the UDP flow) is reported separately.

| Load Mb/s | Probes | Mean RTT ms | Median | P95 | Max | PC-SHOP~SRV-LOCAL mean RTT ms |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 378 | 7.102 | 8.329 | 9.230 | 12.789 | 8.466 |
| 5 | 378 | 7.091 | 8.290 | 8.993 | 13.787 | 8.418 |
| 40 | 378 | 7.477 | 8.289 | 10.782 | 22.988 | 8.934 |

## 7. Recovery

- All PASS runs regained full 6-pair reachability; first full-reachability check at 0.99–1.05 s after restoration (check granularity ≈1 s, so this is an upper bound).
- tc configuration restored to baseline and all interfaces admin-up with carrier in every PASS run; no OVS bridges left after Mininet stop.

