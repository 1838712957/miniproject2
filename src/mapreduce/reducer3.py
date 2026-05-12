#!/usr/bin/env python3
"""Reducer for Output 3: Top 10 Most Active Devices.
Sums counts by device_id, then outputs the top 10 by event count.
Hadoop streaming: sort | python reducer3.py
Because Hadoop streaming sorts keys alphabetically, we do a two-pass approach:
  Pass 1 (this reducer): aggregate per device_id, emit device_id \t count
  Pass 2 (external): sort -nr -k2 | head -10
For EMR Hadoop streaming, we run a single-pass reducer that tracks everything
in memory (the device count set is bounded, ~200 devices, so it fits).
"""
import sys
from collections import defaultdict

def main():
    counts = defaultdict(int)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            key, count = line.rsplit('\t', 1)
            counts[key] += int(count)
        except ValueError:
            continue

    # Sort descending by count, take top 10
    top10 = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    for device, count in top10:
        print(f'{device}\t{count}')

if __name__ == '__main__':
    main()
