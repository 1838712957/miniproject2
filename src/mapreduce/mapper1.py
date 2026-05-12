#!/usr/bin/env python3
"""Mapper for Output 1: Event Count by Sensor Type.
Reads CSV from stdin, emits: sensor_type \t 1
"""
import sys
import csv

def main():
    reader = csv.DictReader(sys.stdin)
    for row in reader:
        sensor_type = row['sensor_type']
        print(f'{sensor_type}\t1')

if __name__ == '__main__':
    main()
