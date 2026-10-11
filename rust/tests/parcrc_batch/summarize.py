#!/usr/bin/env python3
"""Paired full-caller raw timings and deterministic bootstrap 95% intervals."""
import csv
from collections import defaultdict
from pathlib import Path
import random
import statistics
import sys

rows = defaultdict(list)
for row in csv.DictReader(Path(sys.argv[1]).open()):
    rows[(int(row['count']), int(row['size']))].append(row)
rng = random.Random(20261011)
print('| Blocks | Block bytes | Old ns | Rust ns | Optimized C++ ns | Rust gain vs old (95% CI) | Rust gain vs control (95% CI) |')
print('|---:|---:|---:|---:|---:|---:|---:|')
for (count, size), samples in rows.items():
    old = [float(s['old_ns']) for s in samples]
    rust = [float(s['rust_ns']) for s in samples]
    control = [float(s['optimized_ns']) for s in samples]
    intervals = []
    for reference in [old, control]:
        ratios = [1 - r / c for r, c in zip(rust, reference)]
        boots = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) * 100 for _ in range(5000))
        intervals.append(f'{statistics.median(ratios)*100:.2f}% [{boots[125]:.2f}, {boots[4874]:.2f}]')
    print(f'| {count} | {size} | {statistics.median(old):.1f} | {statistics.median(rust):.1f} | {statistics.median(control):.1f} | {intervals[0]} | {intervals[1]} |')
