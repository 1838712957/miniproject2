"""
Step 4: Validation script.
Compares EMR MapReduce outputs against local ground truth,
and verifies Ray abnormal detection results.
"""
import json
import os
import sys

OUTPUTS = os.path.join(os.path.dirname(__file__), '..', 'outputs')


def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def load_emr_output(path):
    """Load tab-separated EMR output file into a dict."""
    result = {}
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit('\t', 1)
            if len(parts) == 2:
                result[parts[0]] = int(parts[1])
    return result


def validate_output1(emr_path=None):
    """Compare sensor type counts."""
    print('\n=== Validating Output 1: Event Count by Sensor Type ===')
    ground = load_json(os.path.join(OUTPUTS, 'output1_sensor_count.json'))

    if emr_path:
        emr = load_emr_output(emr_path)
        if emr is None:
            print('  SKIP: EMR output file not found')
            return
    else:
        print('  (No EMR output provided, showing ground truth only)')
        emr = ground

    all_match = True
    for key in ground:
        gt = ground[key]
        mr = emr.get(key, 'MISSING')
        status = 'OK' if gt == mr else 'MISMATCH'
        if gt != mr:
            all_match = False
        print(f'  {key}: ground_truth={gt}, EMR={mr} [{status}]')

    if all_match:
        print('  RESULT: ALL MATCH')
    else:
        print('  RESULT: MISMATCHES FOUND')


def validate_output2(emr_path=None):
    """Compare warning/error counts by building."""
    print('\n=== Validating Output 2: Warning/Error Count by Building ===')
    ground = load_json(os.path.join(OUTPUTS, 'output2_warning_error.json'))

    if emr_path:
        emr = load_emr_output(emr_path)
        if emr is None:
            print('  SKIP: EMR output file not found')
            return
    else:
        print('  (No EMR output provided, showing ground truth only)')
        emr = ground

    all_match = True
    for key in ground:
        gt = ground[key]
        mr = emr.get(key, 'MISSING')
        status = 'OK' if gt == mr else 'MISMATCH'
        if gt != mr:
            all_match = False
        print(f'  {key}: ground_truth={gt}, EMR={mr} [{status}]')

    if all_match:
        print('  RESULT: ALL MATCH')
    else:
        print('  RESULT: MISMATCHES FOUND')


def validate_output3(emr_path=None):
    """Compare top 10 devices."""
    print('\n=== Validating Output 3: Top 10 Most Active Devices ===')
    ground = load_json(os.path.join(OUTPUTS, 'output3_top10_devices.json'))

    if emr_path:
        emr = load_emr_output(emr_path)
        if emr is None:
            print('  SKIP: EMR output file not found')
            return
    else:
        emr = ground

    # Compare top 10 in order
    gt_list = sorted(ground.items(), key=lambda x: x[1], reverse=True)[:10]
    mr_list = sorted(emr.items(), key=lambda x: x[1], reverse=True)[:10] if emr else []

    all_match = True
    for i, (gt_dev, gt_cnt) in enumerate(gt_list):
        if i < len(mr_list):
            mr_dev, mr_cnt = mr_list[i]
            status = 'OK' if gt_dev == mr_dev and gt_cnt == mr_cnt else 'MISMATCH'
        else:
            mr_dev, mr_cnt = 'MISSING', '-'
            status = 'MISSING'
        if status != 'OK':
            all_match = False
        print(f'  #{i+1}: ground_truth={gt_dev}({gt_cnt}), EMR={mr_dev}({mr_cnt}) [{status}]')

    if all_match:
        print('  RESULT: ALL MATCH')
    else:
        print('  RESULT: MISMATCHES FOUND')


def validate_ray(ray_path=None):
    """Validate Ray abnormal detection against ground truth."""
    print('\n=== Validating Ray: Abnormal Device Detection ===')
    ground = load_json(os.path.join(OUTPUTS, 'abnormal_devices.json'))
    gt_set = {(d['device_id'], d['building'], d['reason']) for d in ground}
    print(f'  Ground truth: {len(gt_set)} entries')

    if ray_path and os.path.exists(ray_path):
        ray_results = []
        with open(ray_path, 'r') as f:
            header = f.readline()  # skip header
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split(',')
                    if len(parts) >= 3:
                        ray_results.append((parts[0], parts[1], parts[2]))
        ray_set = set(ray_results)
        print(f'  Ray output:   {len(ray_set)} entries')

        missing_in_ray = gt_set - ray_set
        extra_in_ray = ray_set - gt_set

        if missing_in_ray:
            print(f'  Missing in Ray ({len(missing_in_ray)}):')
            for item in sorted(missing_in_ray)[:10]:
                print(f'    {item}')
        if extra_in_ray:
            print(f'  Extra in Ray ({len(extra_in_ray)}):')
            for item in sorted(extra_in_ray)[:10]:
                print(f'    {item}')
        if not missing_in_ray and not extra_in_ray:
            print('  RESULT: ALL MATCH')
        else:
            print('  RESULT: DIFFERENCES FOUND')
    else:
        print('  (No Ray output file provided, showing ground truth only)')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Validate MR and Ray outputs')
    parser.add_argument('--mr-output1', help='Path to EMR output1 file')
    parser.add_argument('--mr-output2', help='Path to EMR output2 file')
    parser.add_argument('--mr-output3', help='Path to EMR output3 file')
    parser.add_argument('--ray-output', help='Path to Ray abnormal devices file')
    args = parser.parse_args()

    validate_output1(args.mr_output1)
    validate_output2(args.mr_output2)
    validate_output3(args.mr_output3)
    validate_ray(args.ray_output)

    print('\n=== Validation complete ===')


if __name__ == '__main__':
    main()
