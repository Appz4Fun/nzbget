#!/usr/bin/env python3
"""Validate complete paired data, then report medians and bootstrap intervals."""
import collections
import csv
import math
import random
import statistics
import sys

expected = {(mode, files, parts) for mode in ('quoted', 'unquoted')
            for files, parts in ((1, 1), (30, 10), (100, 100))}
expected |= {('quoted-par', 1, 1), ('unquoted-par', 1, 1)}
samples = collections.defaultdict(lambda: collections.defaultdict(dict))
with open(sys.argv[1]) as source:
    for row in csv.reader(source):
        if len(row) == 1 and (row[0].startswith('locale ') or row[0].startswith('PASS ')):
            continue
        if len(row) != 7:
            raise ValueError('malformed timing row')
        mode, files, parts, round_, language, ns, checksum = row
        shape = (mode, int(files), int(parts))
        round_ = int(round_)
        ns = float(ns)
        if shape not in expected or round_ not in range(15) or language not in ('cpp', 'rust'):
            raise ValueError('unexpected timing case, round, or language')
        if not math.isfinite(ns) or ns <= 0 or int(checksum) <= 0:
            raise ValueError('invalid timing or output checksum')
        pair = samples[shape][round_]
        if language in pair:
            raise ValueError('duplicate timing sample')
        pair[language] = (ns, checksum)
if set(samples) != expected:
    raise ValueError('missing benchmark cases')
for rounds in samples.values():
    if set(rounds) != set(range(15)):
        raise ValueError('missing timing rounds')
    for pair in rounds.values():
        if set(pair) != {'cpp', 'rust'}:
            raise ValueError('incomplete C++/Rust pair')
        if pair['cpp'][1] != pair['rust'][1]:
            raise ValueError('observable output checksum mismatch')

rng = random.Random(91731)
print('| Subject | Files × parts | C++ µs | Rust µs | Change | Paired 95% CI |')
print('|---|---:|---:|---:|---:|---:|')
for shape, rounds in sorted(samples.items()):
    cpp = [pair['cpp'][0] for pair in rounds.values()]
    rust = [pair['rust'][0] for pair in rounds.values()]
    ratios = [pair['rust'][0] / pair['cpp'][0] for pair in rounds.values()]
    bootstrap = sorted(statistics.median(rng.choices(ratios, k=15)) for _ in range(10000))
    print(f'| {shape[0]} | {shape[1]} × {shape[2]} | {statistics.median(cpp)/1000:.3f} '
          f'| {statistics.median(rust)/1000:.3f} | {(statistics.median(ratios)-1)*100:+.1f}% '
          f'| {(bootstrap[250]-1)*100:+.1f}% to {(bootstrap[9749]-1)*100:+.1f}% |')
