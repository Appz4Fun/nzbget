#!/usr/bin/env python3
"""Build exact-old, candidate and optimized C++ full-fold callers.
Run remotely under the documented heavy/shared benchmark locks; run the
printed prebuilt benchmark command under exclusive benchmark lock only.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
p = argparse.ArgumentParser()
p.add_argument('--build', type=Path, required=True, help='daemon CMake build (PAR2 headers/libraries)')
p.add_argument('--rust-lib', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--only', choices=['all', 'sanitized', 'release', 'fallback-sanitized'], default='all')
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
source = (ROOT / 'daemon/postprocess/ParChecker.cpp').read_text()
start = source.index('\t// compute file CRC using CRCs of blocks', source.index('bool ParChecker::VerifySuccessDataFile'))
end = source.index('\tstd::string fileName', start)
(a.out / 'candidate.inc').write_text(source[start:end])
method_start = source.index('{', source.index('bool ParChecker::VerifySuccessDataFile')) + 1
method_end = source.index('\nbool ParChecker::VerifyPartialDataFile', method_start)
body = source[method_start:method_end].rstrip()
assert body.endswith('}')
(a.out / 'candidate-full.inc').write_text(body[:-1])
reference_full = Path(__file__).with_name('reference-full.inc').read_text()
fold_start = reference_full.index('\t// compute file CRC using CRCs of blocks')
fold_end = reference_full.index('\tstd::string fileName', fold_start)
(a.out / 'control-full.inc').write_text(reference_full[:fold_start] +
    '\tuint32 parCrc = optimized(packet, blocksize);\n' + reference_full[fold_end:])
par = a.build / 'par2-turbo/src'
common = ['g++', '-std=c++17', '-g', '-DHAVE_CONFIG_H',
          '-DPARPAR_ENABLE_HASHER_MD5CRC', '-DPARPAR_INVERT_SUPPORT', '-DPARPAR_SLIM_GF16',
          '-I' + str(par / 'par2-turbo/include'), '-I' + str(par / 'par2-turbo-build'),
          '-DNZBGET_USE_RUST', '-I' + str(a.out), '-I' + str(ROOT / 'rust/include'), str(Path(__file__).with_name('caller.cpp')),
          str(a.rust_lib), str(par / 'par2-turbo-build/libpar2-turbo.a'),
          str(par / 'par2-turbo-build/libgf16.a'), str(par / 'par2-turbo-build/libhasher.a'),
          '-lz', '-lpthread', '-lm', '-ldl', '-lrt', '-lutil']
for name, flags in [('sanitized', ['-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']),
                    ('release', ['-O3', '-DNDEBUG']),
                    ('fallback-sanitized', ['-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'])]:
    if a.only != 'all' and a.only != name:
        continue
    binary = a.out / name
    compile_args = [arg for arg in common if name != 'fallback-sanitized' or arg != '-DNZBGET_USE_RUST']
    subprocess.run(compile_args + flags + ['-o', str(binary)], check=True)
    subprocess.run([str(binary), str(ROOT / 'tests/testdata/parchecker/testfile.par2')], check=True)
print(f'Prebuilt cropped benchmark: {a.out / "release"} bench')
print(f'Prebuilt full-body benchmark: {a.out / "release"} full-bench')
