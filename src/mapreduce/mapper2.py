#!/usr/bin/env python3
"""Mapper for Output 2: Warning/Error Count by Building.
Reads CSV from stdin, filters WARNING or ERROR rows, emits: building \t 1
"""
import sys
import csv

def main():
    reader = csv.DictReader(sys.stdin)
    for row in reader:
        if row['status'] in ('WARNING', 'ERROR'):
            print(f'{row["building"]}\t1')

if __name__ == '__main__':
    main()
