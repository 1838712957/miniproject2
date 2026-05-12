#!/usr/bin/env python3
"""Mapper for Output 3: Top 10 Most Active Devices.
Reads CSV from stdin, emits: device_id \t 1
"""
import sys
import csv

def main():
    reader = csv.DictReader(sys.stdin)
    for row in reader:
        print(f'{row["device_id"]}\t1')

if __name__ == '__main__':
    main()
