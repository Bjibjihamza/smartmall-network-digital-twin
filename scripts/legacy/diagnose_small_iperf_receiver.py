#!/usr/bin/env python3
"""Inspect iperf3 sender/receiver JSON from an existing SmartMall receiver verification.

Offline/read-only: no Mininet, no iperf3, no modifications to the experiment.
Example (project root, Windows or WSL):
  python scripts/legacy/diagnose_small_iperf_receiver.py --folder data/raw/small_v1/receiver_verify_20261125T143400Z_8a5a05
"""
import argparse
import json
from pathlib import Path


def metric_rows(payload, prefix):
    end = payload.get('end') or {}
    rows = []
    for key in ('sum_received', 'sum', 'sum_sent'):
        obj = end.get(key)
        if isinstance(obj, dict):
            rows.append((f'{prefix}.end.{key}', obj))
    for i, stream in enumerate(end.get('streams') or []):
        if not isinstance(stream, dict):
            continue
        for key in ('udp', 'sender', 'receiver'):
            obj = stream.get(key)
            if isinstance(obj, dict):
                rows.append((f'{prefix}.end.streams[{i}].{key}', obj))
    return rows


def brief(row):
    location, obj = row
    wanted = ('sender', 'bytes', 'bits_per_second', 'packets', 'lost_packets',
              'lost_percent', 'jitter_ms', 'seconds')
    detail = ', '.join(f'{key}={obj[key]}' for key in wanted if key in obj)
    return f'  {location}: {detail or "(no standard UDP metric fields)"}'


def receiver_candidates(server_json):
    """Positive receiver-side UDP *candidates*; no fallback to client sender metrics."""
    out = []
    for location, obj in metric_rows(server_json, 'server'):
        # A positive rate from the receiving host, not explicitly tagged sender.
        bps = obj.get('bits_per_second')
        try:
            rate = float(bps)
        except (ValueError, TypeError):
            continue
        if rate > 0 and obj.get('sender') is not True and 'sum_sent' not in location and '.sender' not in location:
            out.append((location, rate / 1e6, obj))
    return out


def inspect(folder):
    if not folder.is_dir():
        raise SystemExit(f'Folder not found: {folder}')
    server_files = sorted(folder.glob('iperf3_server_*.json'))
    if not server_files:
        raise SystemExit('No iperf3_server_*.json files found; check the verification folder.')
    print(f'SmartMall — OFFLINE iperf3 receiver diagnostic\nFolder: {folder}\n')
    for sf in server_files:
        profile = sf.name[len('iperf3_server_'):-len('.json')]
        cf = folder / f'iperf3_client_{profile}.json'
        print(f'=== {profile} ===')
        server = json.loads(sf.read_text(encoding='utf-8'))
        print(f'  Server report: top-level keys={list(server)}; end keys={list((server.get("end") or {}).keys())}')
        if server.get('error'):
            print(f'  SERVER ERROR: {server["error"]}')
        for row in metric_rows(server, 'server'):
            print(brief(row))
        if cf.is_file():
            client = json.loads(cf.read_text(encoding='utf-8'))
            print(f'  Client report: top-level keys={list(client)}; end keys={list((client.get("end") or {}).keys())}')
            if client.get('error'):
                print(f'  CLIENT ERROR: {client["error"]}')
            for row in metric_rows(client, 'client'):
                print(brief(row))
            if isinstance(client.get('server_output_json'), dict):
                print('  Client contains server_output_json:')
                for row in metric_rows(client['server_output_json'], 'client.server_output_json'):
                    print(brief(row))
        else:
            print('  WARNING: client JSON not found')
        candidates = receiver_candidates(server)
        if candidates:
            for location, mbps, _ in candidates:
                print(f'  RECEIVER-SIDE POSITIVE CANDIDATE: {mbps:.4f} Mb/s from {location}')
            print('  RESULT: positive receiver-side data exists; original parser may have selected a zero summary first.')
        else:
            print('  RESULT: NO POSITIVE RECEIVER RATE found in the server end statistics.')
            print('  This does not by itself prove zero network traffic; investigate raw UDP counters and server/client JSON.')
        print()
    print('Read-only diagnostic finished. Do not mark the experiment PASS until the source of a positive receiver measurement is validated.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder', required=True, type=Path,
                   help='Existing receiver_verify_... folder')
    args = p.parse_args()
    inspect(args.folder)


if __name__ == '__main__':
    main()
