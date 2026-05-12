"""
Task 3: Ray-based Abnormal Device Detection.
Uses @ray.remote to process the dataset in parallel in two phases:
  Phase 1: Each Ray task aggregates per-device stats from its chunk.
  Phase 2: Merge partial stats across chunks, then apply detection rules.

This ensures cross-chunk correctness (a device's ERROR records may span
multiple chunks, and we need the global count to reach >= 3).

Usage (local Ray):
    python abnormal_detection.py

Usage (EC2):
    python abnormal_detection.py --s3-input s3://bucket/dataset/iot_logs.csv
"""
import argparse
import csv
import io
import os
import time
from collections import defaultdict

import ray


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------
def _parse_row(row):
    parsed = {}
    for k, v in row.items():
        if k == 'value':
            parsed[k] = float(v) if v else 0.0
        elif k == 'battery_level':
            parsed[k] = int(v)
        else:
            parsed[k] = v
    return parsed


def load_from_local(path):
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [_parse_row(row) for row in reader]


def load_from_s3(s3_uri):
    import boto3
    bucket, key = s3_uri.replace('s3://', '').split('/', 1)
    s3 = boto3.client('s3')
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    return [_parse_row(row) for row in reader]


# ---------------------------------------------------------------------------
# Phase 1: Ray remote task — aggregate per-device stats from a chunk
# ---------------------------------------------------------------------------
@ray.remote
def aggregate_chunk(chunk_rows):
    """
    Process one chunk. Returns a dict:
        device_id -> {building, error_count, high_temp_count, min_battery}
    """
    stats = {}
    for r in chunk_rows:
        did = r['device_id']
        if did not in stats:
            stats[did] = {
                'building': r['building'],
                'error_count': 0,
                'high_temp_count': 0,
                'min_battery': r['battery_level'],
            }
        s = stats[did]
        s['min_battery'] = min(s['min_battery'], r['battery_level'])
        if r['status'] == 'ERROR':
            s['error_count'] += 1
        if r['sensor_type'] == 'temperature' and r['value'] > 32:
            s['high_temp_count'] += 1
    return stats


# ---------------------------------------------------------------------------
# Phase 2: Merge partial stats and apply detection rules
# ---------------------------------------------------------------------------
def merge_and_detect(partial_stats_list):
    """Combine partial stats from all chunks and return abnormal devices."""
    merged = {}
    for partial in partial_stats_list:
        for did, s in partial.items():
            if did not in merged:
                merged[did] = dict(s)  # copy
            else:
                m = merged[did]
                m['error_count'] += s['error_count']
                m['high_temp_count'] += s['high_temp_count']
                m['min_battery'] = min(m['min_battery'], s['min_battery'])

    results = []
    for did, s in sorted(merged.items()):
        if s['min_battery'] < 20:
            results.append((did, s['building'], 'low battery'))
        if s['error_count'] >= 3:
            results.append((did, s['building'], 'repeated errors'))
        if s['high_temp_count'] >= 3:
            results.append((did, s['building'], 'repeated high temperature'))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='Ray Abnormal Device Detection')
    parser.add_argument('--s3-input', default=None,
                        help='S3 URI for input dataset')
    parser.add_argument('--chunk-size', type=int, default=5000,
                        help='Rows per chunk for parallel processing')
    parser.add_argument('--local-input', default=None,
                        help='Local path to dataset CSV')
    parser.add_argument('--output', default=None,
                        help='Output file path (default: outputs/abnormal_devices_ray.txt)')
    args = parser.parse_args()

    # Load data
    if args.s3_input:
        print(f'Loading from S3: {args.s3_input}')
        rows = load_from_s3(args.s3_input)
    elif args.local_input:
        print(f'Loading from local: {args.local_input}')
        rows = load_from_local(args.local_input)
    else:
        default_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'Comp3006J MiniProject 2 Dataset.csv'
        )
        print(f'Loading from default: {default_path}')
        rows = load_from_local(default_path)

    print(f'Loaded {len(rows)} rows')

    # Init Ray
    ray.init(ignore_reinit_error=True)
    print(f'Ray resources: CPU={int(ray.cluster_resources().get("CPU", 0))}')

    # Split into chunks
    chunks = [
        rows[i:i + args.chunk_size]
        for i in range(0, len(rows), args.chunk_size)
    ]
    print(f'Split into {len(chunks)} chunks of ~{args.chunk_size} rows')

    # Phase 1: parallel aggregation
    t0 = time.time()
    futures = [aggregate_chunk.remote(chunk) for chunk in chunks]
    partial_stats = ray.get(futures)
    phase1_time = time.time() - t0
    print(f'Phase 1 (parallel aggregation): {phase1_time:.2f}s')

    # Phase 2: merge + detect (local, fast)
    t0 = time.time()
    abnormal = merge_and_detect(partial_stats)
    phase2_time = time.time() - t0
    print(f'Phase 2 (merge & detect): {phase2_time:.4f}s')

    total_time = phase1_time + phase2_time
    print(f'\nAbnormal devices detected: {len(abnormal)}')
    for device_id, building, reason in abnormal:
        print(f'{device_id},{building},{reason}')

    # Save output
    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'outputs',
            'abnormal_devices_ray.txt'
        )
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('device_id,building,reason\n')
        for device_id, building, reason in abnormal:
            f.write(f'{device_id},{building},{reason}\n')
    print(f'\nOutput saved to {output_path}')

    # Save runtime info
    import json
    runtime_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'outputs', 'runtime_ray.json'
    )
    with open(runtime_path, 'w') as f:
        json.dump({
            'environment': 'Ray on EC2' if args.s3_input else 'Ray local',
            'total_rows': len(rows),
            'num_chunks': len(chunks),
            'chunk_size': args.chunk_size,
            'phase1_parallel_s': round(phase1_time, 2),
            'phase2_merge_s': round(phase2_time, 4),
            'total_time_s': round(total_time, 2),
            'ray_cpu': int(ray.cluster_resources().get('CPU', 0)),
        }, f, indent=2)

    ray.shutdown()


if __name__ == '__main__':
    main()
