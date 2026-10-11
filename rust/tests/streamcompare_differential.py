#!/usr/bin/env python3
"""Compile the actual DupeStreamRepair.cpp adapter and caller harness.

Reference method bodies are verbatim from c2316ef5 (class name only changed).
Usage: streamcompare_differential.py BUILD_DIR [--sanitize] [--mutation] [--bench]
Compilation/tests must run remotely under the task's heavy/benchmark locks.
Invalid indexes and signed-overflow C++ inputs are excluded: they are undefined
reference behavior. Negative sizes/offsets with defined arithmetic are included.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('build', type=Path)
p.add_argument('--sanitize', action='store_true')
p.add_argument('--mutation', action='store_true')
p.add_argument('--mutation-threshold', action='store_true')
p.add_argument('--fallback', action='store_true')
p.add_argument('--bench', action='store_true')
p.add_argument('--rounds', default='100000')
p.add_argument('--tag', default='')
a = p.parse_args()
build = a.build.resolve()
commands = json.loads((build / 'compile_commands.json').read_text())
entry = next(e for e in commands if e['file'].endswith('/daemon/queue/DupeStreamRepair.cpp'))
args = shlex.split(entry['command'])
flags = []
i = 1
while i < len(args):
    arg = args[i]
    if arg in ('-o', '-include'):
        i += 2
    elif arg == '-c' or arg == entry['file']:
        i += 1
    else:
        flags.append(arg)
        i += 1
assert '-DNZBGET_USE_RUST' in flags, 'CMake integration must enable Rust'
if a.fallback:
    flags.remove('-DNZBGET_USE_RUST')
flags += ['-ffunction-sections', '-fdata-sections']
if a.sanitize:
    flags += ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
else:
    flags += ['-O3']
name = ('sanitized' if a.sanitize else 'release') + ('-mutant' if a.mutation else '') + ('-threshold-mutant' if a.mutation_threshold else '') + ('-fallback' if a.fallback else '')
if a.tag:
    assert a.tag.replace('-', '').isalnum(), 'tag must be alphanumeric/hyphen'
    name += '-' + a.tag
out = ROOT / 'evidence' / name
out.mkdir(parents=True, exist_ok=True)
source = Path(entry['file'])
if a.mutation:
    text = source.read_text()
    # Mutation of the actual production adapter changes the returned floor.
    needle = 'probeParts.data(), probeParts.size());'
    assert text.count(needle) == 1
    source = out / 'DupeStreamRepair-mutant.cpp'
    source.write_text(text.replace(needle, 'probeParts.data(), probeParts.size()) + 1;'))
obj = out / 'DupeStreamRepair.o'
cpp = ROOT / 'rust/tests/streamcompare_caller.cpp'
ref = ROOT / 'rust/tests/streamcompare_reference.inc'
archive = next(build.glob('rust/**/release/libnzbget_rs.a'))
if a.mutation_threshold:
    text = (ROOT / 'rust/src/streamcompare.rs').read_text()
    needle = 'if achievable >= 64'
    assert text.count(needle) == 2
    mutant = out / 'streamcompare-mutant.rs'
    mutant.write_text(text.replace(needle, 'if achievable >= 65'))
    archive = out / 'libmutant.a'
    subprocess.run(['rustc', '--crate-name', 'streamcompare_mutant', '--crate-type', 'staticlib',
                    '--edition=2021', '-C', 'opt-level=3', '-C', 'panic=abort', str(mutant), '-o', str(archive)],
                   cwd=ROOT / 'rust', check=True)
run = lambda cmd: subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)
run([args[0], *flags, '-c', source, '-o', obj])
binary = out / 'caller'
link = [args[0], *flags, cpp, obj, *([] if a.fallback else [archive]), '-Wl,--gc-sections',
        '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=free', '-ldl', '-lpthread', '-lm', '-lrt', '-o', binary]
run(link)
manifest = {'reference': 'c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e', 'compile_flags': flags,
            'link_command': [str(v) for v in link],
            'sha256': {str(v): hashlib.sha256(v.read_bytes()).hexdigest() for v in (source, cpp, ref, archive, binary)}}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
if a.bench:
    with (out / 'raw.csv').open('w') as f:
        subprocess.run([binary, 'bench'], cwd=ROOT, stdout=f, check=True)
    print(out / 'raw.csv')
elif a.mutation or a.mutation_threshold:
    result = subprocess.run([binary, a.rounds], cwd=ROOT, capture_output=True, text=True)
    print(result.stdout, end='')
    print(result.stderr, end='')
    assert result.returncode != 0 and 'Mismatch' in result.stderr, 'mutation did not fail at parity oracle'
    print('Mutation rejected by complete production caller parity oracle')
else:
    run([binary, a.rounds])
