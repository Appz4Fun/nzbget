#!/usr/bin/env python3
"""Paired latency ratios and deterministic bootstrap median uncertainty."""
import csv
import json
import random
import statistics
import sys
from pathlib import Path

raw = Path(sys.argv[1])
rows = list(csv.DictReader(raw.open()))
fixtures = sorted({r['fixture'] for r in rows})
rng = random.Random(0xCA1B20261011)
report = []
for fixture in fixtures:
    cases = [r for r in rows if r['fixture'] == fixture]
    entries = {}
    for name in ('original', 'control', 'rust'):
        group = [r for r in cases if r['implementation'] == name]
        entries[name] = {int(r['sample']): float(r['ns']) for r in group}
    result = {'fixture': fixture, 'median_ns': {k: statistics.median(v.values()) for k,v in entries.items()}}
    for control in ('original','control'):
        ratios = [entries[control][i]/entries['rust'][i] for i in entries['rust']]
        med = statistics.median(ratios)
        boot = sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
        result[control+'_over_rust'] = {'median': med, 'bootstrap_95_percent_interval': [boot[249],boot[9750]], 'paired_samples':len(ratios)}
    result['allocations'] = {name: sorted({int(r['allocations']) for r in cases if r['implementation']==name}) for name in entries}
    result['allocated_bytes'] = {name: sorted({int(r['allocated_bytes']) for r in cases if r['implementation']==name}) for name in entries}
    report.append(result)
print(json.dumps(report,indent=2))
