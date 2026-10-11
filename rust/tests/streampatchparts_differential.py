#!/usr/bin/env python3
"""Build/run exact-base versus actual caller parity (ASan/UBSan) or paired timing.

Usage: streampatchparts_differential.py BUILD [--bench] [--reference-dir DIR]
The optional reference directory holds verbatim base .cpp/.h for an offline
remote source snapshot without Git history. Output/build logs remain in BUILD.
No endpoint/index-overflow cases enter parity: those are UB in the C++ source.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = 'c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('build', type=Path)
p.add_argument('--bench', action='store_true')
p.add_argument('--cpp-fallback', action='store_true', help='force the actual daemon method to its C++ fallback')
p.add_argument('--reference-dir', type=Path)
a = p.parse_args()
build = a.build.resolve()
def reference(name):
    if a.reference_dir:
        return (a.reference_dir / name).read_text()
    return subprocess.check_output(['git','show',f'{BASE}:daemon/queue/{name}'],cwd=ROOT,text=True)
old = reference('DupeStreamRepair.cpp')
hdr = reference('DupeStreamRepair.h')
assert hashlib.sha256(old.encode()).hexdigest() == '610e187e1c42a9e712e733fb2ac23f0f721877ff65d68c1f69135fa3cc249251'
assert hashlib.sha256(hdr.encode()).hexdigest() == 'cbec54ec78d47fa7cc30814dfff83372be08253179089939589179cc352e8698'
def body(source, signature):
    start = source.index(signature)
    opening = source.index('{',start)
    depth = 0
    for i in range(opening,len(source)):
        depth += {'{':1,'}':-1}.get(source[i],0)
        if not depth:
            return source[start:i+1]
    raise ValueError(signature)
methods = '\n'.join(body(old,s).replace('DupeStreamRepair::','Old::') for s in (
    'bool DupeStreamRepair::IntersectsAny(', 'std::vector<int> DupeStreamRepair::SelectPatchParts('))
predicate = body(hdr,'static bool RangesIntersect(')
source = '#include "nzbget.h"\n#include "DupeStreamRepair.h"\nclass Old { public:\n' + predicate + '\nstatic bool IntersectsAny(const StreamRange&, const StreamRangeList&);\nstatic std::vector<int> SelectPatchParts(const StreamRangeList&,const StreamRangeList&,int);\n};\n' + methods + '\n' + (ROOT/'rust/tests/streampatchparts_harness.cpp').read_text()
work = build/'streampatchparts'
work.mkdir(exist_ok=True)
cpp = work/'caller.cpp'
cpp.write_text(source)
flags = (build/'CMakeFiles/libnzbget.dir/flags.make').read_text()
def get(key): return shlex.split(re.search(rf'^{key} = (.*)$',flags,re.M).group(1))
includes = get('CXX_INCLUDES')
defines = get('CXX_DEFINES')
assert '-DNZBGET_USE_RUST' in defines
if a.cpp_fallback: defines.remove('-DNZBGET_USE_RUST')
lib = next(build.glob('rust/**/release/libnzbget_rs.a'))
mode = ('bench' if a.bench else 'parity') + ('-cpp' if a.cpp_fallback else '-rust')
exe = work/mode
cmd = ['g++','-std=c++17','-O3','-g','-ffunction-sections','-fdata-sections']
if not a.bench: cmd += ['-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-sanitize-recover=all','-no-pie']
cmd += includes + defines + [str(cpp),str(ROOT/'daemon/queue/DupeStreamRepair.cpp'),str(lib),'-Wl,--gc-sections','-ldl','-lpthread','-lm','-o',str(exe)]
(work/(mode+'-command.txt')).write_text(shlex.join(cmd)+'\n')
(work/'reference-manifest.txt').write_text(BASE+'\n'+hashlib.sha256(old.encode()).hexdigest()+' DupeStreamRepair.cpp\n'+hashlib.sha256(hdr.encode()).hexdigest()+' DupeStreamRepair.h\n')
subprocess.run(cmd,check=True)
(work/(mode+'-manifest.json')).write_text(json.dumps({
    'base': BASE, 'command': cmd,
    'sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        exe, lib, ROOT/'rust/src/streampatchparts.rs', ROOT/'daemon/queue/DupeStreamRepair.cpp', cpp)},
    'compiler': subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
    'rustc': subprocess.check_output(['rustc','--version'],text=True).strip(),
    'kernel': subprocess.check_output(['uname','-a'],text=True).strip(),
}, indent=2)+'\n')
subprocess.run([str(exe)]+(['bench'] if a.bench else []),check=True)
