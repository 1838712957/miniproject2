"""
Step 0: Local ground-truth generator.
Produces the three MapReduce outputs + Ray abnormal-device list using pandas.
Results saved to outputs/ as the reference for later cloud-run validation.
"""
import csv
import json
import time
import os
from collections import defaultdict

DATASET = os.path.join(os.path.dirname(__file__), '..', 'Comp3006J MiniProject 2 Dataset.csv')
OUTPUTS = os.path.join(os.path.dirname(__file__), '..', 'outputs')


def read_data(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['value'] = float(row['value']) if row['value'] else 0.0
            row['battery_level'] = int(row['battery_level'])
            rows.append(row)
    return rows


# ---- Output 1: Event Count by Sensor Type ----
def output1_event_count_by_sensor(rows):
    counts = defaultdict(int)
    for r in rows:
        counts[r['sensor_type']] += 1
    result = sorted(counts.items())
    return result


# ---- Output 2: Warning/Error Count by Building ----
def output2_warning_error_by_building(rows):
    counts = defaultdict(int)
    for r in rows:
        if r['status'] in ('WARNING', 'ERROR'):
            counts[r['building']] += 1
    result = sorted(counts.items())
    return result


# ---- Output 3: Top 10 Most Active Devices ----
def output3_top10_devices(rows):
    counts = defaultdict(int)
    for r in rows:
        counts[r['device_id']] += 1
    top10 = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return top10


# ---- Ray logic (same algorithm, executed locally for ground truth) ----
def abnormal_detection(rows):
    """Simulates Ray parallel detection. Returns list of (device_id, building, reason)."""
    from collections import defaultdict

    # Group by device
    device_groups = defaultdict(list)
    for r in rows:
        device_groups[r['device_id']].append(r)

    abnormal = []
    for device_id, events in device_groups.items():
        building = events[0]['building']
        reasons = []

        # Check battery < 20 (any single record is enough)
        if any(e['battery_level'] < 20 for e in events):
            reasons.append('low battery')

        # Check >= 3 ERROR records
        error_count = sum(1 for e in events if e['status'] == 'ERROR')
        if error_count >= 3:
            reasons.append('repeated errors')

        # Check >= 3 records with temperature > 32
        high_temp_count = sum(
            1 for e in events
            if e['sensor_type'] == 'temperature' and e['value'] > 32
        )
        if high_temp_count >= 3:
            reasons.append('repeated high temperature')

        if reasons:
            for reason in reasons:
                abnormal.append((device_id, building, reason))

    return sorted(abnormal, key=lambda x: x[0])


def main():
    os.makedirs(OUTPUTS, exist_ok=True)

    print('Reading dataset...')
    t0 = time.time()
    rows = read_data(DATASET)
    print(f'  Loaded {len(rows)} rows ({time.time() - t0:.2f}s)')

    # Output 1
    print('\n[Output 1] Event Count by Sensor Type')
    t0 = time.time()
    o1 = output1_event_count_by_sensor(rows)
    print(f'  Completed in {time.time() - t0:.2f}s')
    for sensor, count in o1:
        print(f'    {sensor}: {count}')
    with open(os.path.join(OUTPUTS, 'output1_sensor_count.json'), 'w') as f:
        json.dump(dict(o1), f, indent=2)

    # Output 2
    print('\n[Output 2] Warning/Error Count by Building')
    t0 = time.time()
    o2 = output2_warning_error_by_building(rows)
    print(f'  Completed in {time.time() - t0:.2f}s')
    for building, count in o2:
        print(f'    {building}: {count}')
    with open(os.path.join(OUTPUTS, 'output2_warning_error.json'), 'w') as f:
        json.dump(dict(o2), f, indent=2)

    # Output 3
    print('\n[Output 3] Top 10 Most Active Devices')
    t0 = time.time()
    o3 = output3_top10_devices(rows)
    print(f'  Completed in {time.time() - t0:.2f}s')
    for device, count in o3:
        print(f'    {device}: {count}')
    with open(os.path.join(OUTPUTS, 'output3_top10_devices.json'), 'w') as f:
        json.dump(dict(o3), f, indent=2)

    # Abnormal detection (Ray logic, sequential for ground truth)
    print('\n[Ray Logic] Abnormal Device Detection')
    t0 = time.time()
    abnormal = abnormal_detection(rows)
    print(f'  Completed in {time.time() - t0:.2f}s')
    print(f'  Found {len(abnormal)} abnormal device entries:')
    for device, building, reason in abnormal[:20]:
        print(f'    {device},{building},{reason}')
    if len(abnormal) > 20:
        print(f'    ... and {len(abnormal) - 20} more')
    with open(os.path.join(OUTPUTS, 'abnormal_devices.json'), 'w') as f:
        json.dump([{'device_id': d, 'building': b, 'reason': r}
                    for d, b, r in abnormal], f, indent=2)

    print(f'\nAll outputs saved to outputs/')
    # Save runtime summary
    with open(os.path.join(OUTPUTS, 'runtime_local.json'), 'w') as f:
        json.dump({
            'environment': 'local Windows 11, Python 3.10, sequential pandas',
            'total_rows': len(rows),
        }, f, indent=2)


if __name__ == '__main__':
    main()
