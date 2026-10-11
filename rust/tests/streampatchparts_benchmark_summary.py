#!/usr/bin/env python3
"""Summarize paired full-caller CSV with seeded bootstrap median-ratio CIs.

Each paired sample is a per-operation timing from one batch; resampling pairs
preserves common temporal effects. Intervals are descriptive, not production
workload weights or a universal performance guarantee.
"""
import csv
from collections import defaultdict
from pathlib import Path
import random
import statistics
import sys
rows = defaultdict(list)
with Path(sys.argv[1]).open() as stream:
    for row in csv.DictReader(stream):
        rows[row['fixture']].append({k:float(row[k]) for k in ('old_ns','rust_ns','control_ns','direct_ns')})
randomizer = random.Random(20261011)
print('| Fixture | Old ns | Rust caller ns | C++ control ns | Forced Rust ns | Rust reduction vs old, 95% CI | Rust reduction vs control, 95% CI |')
print('|---|---:|---:|---:|---:|---:|---:|')
for name, data in rows.items():
    def reduction(control):
        ratios = [r['rust_ns']/r[control] for r in data]
        samples = sorted(statistics.median(randomizer.choices(ratios,k=len(ratios))) for _ in range(10000))
        return f'{100*(1-statistics.median(ratios)):.1f}% [{100*(1-samples[9749]):.1f}, {100*(1-samples[249]):.1f}]'
    medians = [statistics.median(r[k] for r in data) for k in ('old_ns','rust_ns','control_ns','direct_ns')]
    print('| '+name+' | '+' | '.join(f'{m:.1f}' for m in medians)+' | '+reduction('old_ns')+' | '+reduction('control_ns')+' |')
