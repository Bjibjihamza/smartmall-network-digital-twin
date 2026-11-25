#!/usr/bin/env python3
"""SmartMall SMALL: analyse descriptive des signatures de connectivite d'une campagne.

Usage (PowerShell, racine du projet):
    python scripts/legacy/analyze_small_campaign.py --campaign data/campaigns/campaign_20261125T134916Z_249a1c

Aucun paquet Mininet n'est necessaire. stdlib uniquement.
Lit les resultats RAW en lecture seule. Utilise la verite terrain UNIQUEMENT
pour l'audit descriptif; ne cree aucun dataset d'entrainement ML.
"""

import argparse
import csv
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_json(path):
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pair_label(pair):
    return " <-> ".join(pair)


def connectivity_without_link(spec, failed_link):
    """Expected host-pair disconnections based strictly on graph connectivity."""
    adjacency = defaultdict(set)
    for node in spec["nodes"]:
        adjacency[node["id"]]
    for link in spec["links"]:
        if link["id"] == failed_link:
            continue
        a, b = link["source"], link["target"]
        adjacency[a].add(b)
        adjacency[b].add(a)
    hosts = sorted(n["id"] for n in spec["nodes"] if n["type"] == "host")
    result = set()
    for source, target in itertools.combinations(hosts, 2):
        visited = {source}
        pending = [source]
        while pending:
            for neighbor in adjacency[pending.pop()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        if target not in visited:
            result.add((source, target))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True, help="Folder containing manifest.json")
    args = parser.parse_args()
    folder = args.campaign.resolve()
    manifest = read_json(folder / "manifest.json")
    if manifest.get("status") != "completed":
        parser.error("The campaign is not marked completed. Do not treat incomplete campaigns as validated.")
    if manifest.get("topology_id") != "small_v1":
        parser.error("This script analyzes SMALL v1 only.")
    experiments = manifest.get("experiments", [])
    if not experiments:
        parser.error("No experiments found in manifest.json")

    problems = []
    per_link = defaultdict(list)
    total_icmp = 0
    total_ports = 0
    all_pairs = None
    topology = None
    detail = []
    for experiment in experiments:
        if experiment.get("status") != "PASS":
            problems.append(f"Experiment {experiment.get('experiment_id')} status != PASS")
            continue
        exp_folder = ROOT / experiment["raw_relative_path"]
        spec = read_json(exp_folder / "topology.json")
        incident = read_json(exp_folder / "incident.json")
        probes = read_csv(exp_folder / "telemetry.csv")
        port_rows = read_csv(exp_folder / "port_telemetry.csv")
        link_id = incident["ground_truth"]["fault_link_id"]
        exp_id = experiment["experiment_id"]
        if incident["experiment_id"] != exp_id or incident.get("status") != "completed":
            problems.append(f"Experiment metadata inconsistent for {exp_id}")
        if link_id != experiment["fault_link_id"]:
            problems.append(f"Fault label inconsistent for {exp_id}")
        if topology is None:
            topology = spec
            hosts = sorted(n["id"] for n in spec["nodes"] if n["type"] == "host")
            all_pairs = set(itertools.combinations(hosts, 2))
        elif spec != topology:
            problems.append(f"Topology different in experiment {exp_id}")

        total_icmp += len(probes)
        total_ports += len(port_rows)
        if len(probes) != experiment.get("icmp_rows") or len(port_rows) != experiment.get("port_rows"):
            problems.append(f"CSV row counts do not match manifest for {exp_id}")
        windows = {
            s["snapshot_id"]: s["phase"]
            for s in incident["ground_truth"]["snapshots"]
        }
        failed_windows = sorted(w for w, phase in windows.items() if phase == "failed")
        if not failed_windows:
            problems.append(f"No failed windows in {exp_id}")
            continue
        by_window = defaultdict(list)
        for row in probes:
            by_window[row["snapshot_id"]].append(row)
            if windows.get(row["snapshot_id"]) not in ("healthy", "failed", "recovered"):
                problems.append(f"Unexpected snapshot ID {row['snapshot_id']} in {exp_id}")
        for window, phase in windows.items():
            rows = by_window.get(window, [])
            observed_pairs = [tuple(sorted((r["source_node_id"], r["target_node_id"]))) for r in rows]
            if len(rows) != len(all_pairs) or set(observed_pairs) != all_pairs or len(set(observed_pairs)) != len(rows):
                problems.append(f"Missing/duplicated directed host pairs: {exp_id}/{window}")
            if phase != "failed" and any(r["reachable"] != "1" for r in rows):
                problems.append(f"Non-failure window has disconnected pairs: {exp_id}/{window}")

        graph_expectation = connectivity_without_link(spec, link_id)
        failed_signatures = []
        for window in failed_windows:
            rows = by_window.get(window, [])
            disconnected = {
                tuple(sorted((r["source_node_id"], r["target_node_id"])))
                for r in rows if r["reachable"] == "0"
            }
            lost = sum(r.get("loss_pct", "") not in ("", None) and float(r["loss_pct"]) > 0 for r in rows)
            route = sum(r.get("probe_status") == "route_unreachable" for r in rows)
            failed_signatures.append(disconnected)
            if disconnected != graph_expectation:
                problems.append(
                    f"Graph/probes mismatch {exp_id}/{window}: "
                    f"observed={[pair_label(x) for x in sorted(disconnected)]}, "
                    f"expected={[pair_label(x) for x in sorted(graph_expectation)]}"
                )
            if route and not all(
                r.get("loss_pct", "") in ("", None) and r.get("packets_sent") == "0"
                for r in rows if r.get("probe_status") == "route_unreachable"
            ):
                problems.append(f"Unreachable-route semantics inconsistent for {exp_id}/{window}")
            detail.append({
                "experiment_id": exp_id,
                "fault_link": link_id,
                "snapshot_id": window,
                "disrupted_pairs": len(disconnected),
                "icmp_loss_probes": lost,
                "route_unreachable_probes": route,
                "signature": " | ".join(pair_label(p) for p in sorted(disconnected)),
            })
        if any(s != failed_signatures[0] for s in failed_signatures[1:]):
            problems.append(f"Inconsistent signatures across failed windows for {exp_id}")
        per_link[link_id].append(failed_signatures[0])

    canonical = {}
    for link, signatures in per_link.items():
        if any(s != signatures[0] for s in signatures[1:]):
            problems.append(f"Inconsistent signatures across experiments for link {link}")
        canonical[link] = frozenset(signatures[0])

    equivalent = defaultdict(list)
    for link, signature in canonical.items():
        equivalent[signature].append(link)
    non_unique = [sorted(v) for v in equivalent.values() if len(v) > 1]

    ordered_links = sorted(canonical, key=lambda x: (int(x[1:]) if x[1:].isdigit() else 999999, x))
    cid = manifest["campaign_id"]
    lines = [
        "# SmartMall — Analyse des signatures de pannes SMALL", "",
        f"- Campagne : `{cid}`", "- Topologie : `small_v1`",
        f"- Experiences validees dans le manifest : {len(experiments)}",
        f"- Enregistrements : {total_icmp} ICMP, {total_ports} ports", "",
        "## Signatures observees (fenetres de panne)", "",
        "| Lien coupe | Paires d'hotes injoignables | Signature |",
        "|---|---:|---|",
    ]
    for link in ordered_links:
        s = canonical[link]
        lines.append(f"| {link} | {len(s)} | {' ; '.join(pair_label(p) for p in sorted(s))} |")
    lines.extend(["", "## Identifiabilite avec la connectivite seule", ""])
    lines.append(f"- Signatures distinctes : **{len(equivalent)} sur {len(canonical)} liens evalues**.")
    if non_unique:
        for group in non_unique:
            lines.append(f"- Liens indiscernables : **{', '.join(group)}**.")
    else:
        lines.append("- Aucune paire de liens indiscernable dans cette campagne.")
    lines.extend([
        "", "## Qualite descriptive", "",
        f"**{'PASS' if not problems else 'CHECK REQUIRED'}**", "",
    ])
    if problems:
        lines.extend(["### Anomalies"] + [f"- {x}" for x in problems] + [""])
    lines.extend([
        "## Limites scientifiques", "",
        "- Les signatures sont construites ici a partir des fenetres `failed` du ground truth **pour l'analyse de collecte uniquement**.",
        "- Les metadonnees de phase, `fault_link_id`, IDs d'experience et horodatages ne doivent pas etre des features ML.",
        "- L'etat administratif `admin_up` expose directement l'injection et n'est pas une preuve de localisation GNN realiste.",
        "- Les 6 sondes de chaque fenetre sont sequentielles et non simultanees.",
        "- Une seule repetition par lien ne permet pas d'estimer robustement des performances de generalisation.",
        "- En cas de nouveaux mecanismes de panne, verifier de nouveau l'identifiabilite.", "",
    ])

    output_dir = ROOT / "docs" / "history" / "small_v1"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_md = output_dir / f"analysis_{cid}.md"
    output_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Report: {output_md}")

    output_csv = output_dir / f"signatures_{cid}.csv"
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "experiment_id", "fault_link", "snapshot_id", "disrupted_pairs",
            "icmp_loss_probes", "route_unreachable_probes", "signature",
        ])
        writer.writeheader()
        writer.writerows(detail)
    print(f"Signature table: {output_csv}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
