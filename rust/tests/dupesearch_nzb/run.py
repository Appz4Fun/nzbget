#!/usr/bin/env python3
"""Run in an isolated Linux checkout: shared build lock, exclusive bounded timing."""
import hashlib
import shutil
import argparse
import os
import pathlib
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--config-dir', required=True)
parser.add_argument('--sanitize', action='store_true')
parser.add_argument('--bench', action='store_true')
parser.add_argument('--library')
parser.add_argument('--locales', required=True)
parser.add_argument('--cpp-only', action='store_true')
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[3]
work = root/'rust/tests/dupesearch_nzb/artifacts'
work.mkdir(exist_ok=True)
base = '2f0840a2e5d2528aca427061ad5d7778ac1e255f'
ref = subprocess.check_output(['git', 'show', base+':daemon/dupesearch/NzbReader.cpp'],
                              cwd=root, text=True)
start = ref.index('std::string NzbSummary::Fingerprint()')
end = ref.index('bool NzbReader::Parse', start)
ref = ref[:start]+ref[end:]
for old, new in [('NameOfSubject', 'ReferenceNameOfSubject'),
                 ('ValidMessageId', 'ReferenceValidMessageId'),
                 ('IsParName', 'ReferenceIsParName'), ('Reader', 'ReferenceReader')]:
    ref = re.sub(r'\b'+old+r'\b', new, ref)
ref = ref.replace('bool NzbReader::Parse', 'bool ReferenceParse')
(work/'reference.inc').write_text(ref)
(work/'candidate.inc').write_text((root/'daemon/dupesearch/NzbReader.cpp').read_text())
(work/'xml.inc').write_text((root/'daemon/dupesearch/XmlReader.cpp').read_text())
lock = pathlib.Path(tempfile.gettempdir())/'nzbget-rust-benchmark.lock'

def build(command):
    subprocess.run(['flock', '-s', str(lock), *map(str, command)], check=True, cwd=root)

lib = pathlib.Path(args.library).resolve() if args.library else work/'libdupesearch_nzb.a'
if not args.library:
    build([pathlib.Path.home()/'.cargo/bin/rustc', '--edition', '2021', '--crate-type', 'staticlib',
           '-C', 'opt-level=3', '-C', 'lto=yes', '-C', 'codegen-units=1', '-C', 'panic=abort',
           'rust/src/dupesearch_nzb.rs', '-o', lib])
flags = ['-O3', '-DNDEBUG'] if not args.sanitize else [
    '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
command = ['g++', '-std=c++20', *flags, '-I'+str(work), '-I'+args.config_dir,
           '-I'+args.config_dir+'/rapidyenc/src/rapidyenc',
           '-I'+args.config_dir+'/par2-turbo/src/par2-turbo/include',
           '-I'+str(root/'rust/include')]
if not args.cpp_only:
    command.append('-DNZBGET_USE_RUST')
command += ['-I'+str(path) for path in (root/'daemon').iterdir() if path.is_dir()]
label = 'caller-cpp' if args.cpp_only else 'caller-sanitize' if args.sanitize else 'caller'
object_file = work/(label+'.o')
command += ['-I/usr/include/libxml2', '-c', str(root/'rust/tests/dupesearch_nzb/caller.cpp'),
            '-o', str(object_file)]
build(command)
exe = str(work/label)
build(['g++', *flags, object_file, lib, '-lxml2', '-lssl', '-lcrypto', '-ldl', '-lpthread',
       '-lm', '-o', exe])
env = dict(os.environ, LOCPATH=str(pathlib.Path(args.locales).resolve()))
subprocess.run([exe], check=True, cwd=root, env=env)
if args.bench:
    if args.cpp_only or args.sanitize:
        raise ValueError('timing requires optimized Rust-enabled caller')
    digest = hashlib.sha256(pathlib.Path(exe).read_bytes()).hexdigest()
    frozen = work/('timing-'+digest)
    if not frozen.exists():
        shutil.copy2(exe, frozen)
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != digest:
        raise ValueError('frozen executable hash mismatch')
    print('PASS immutable timing binary SHA256 '+digest, flush=True)
    subprocess.run(['flock', '-x', str(lock), 'taskset', '-c', '2', str(frozen), 'bench'],
                   check=True, cwd=root)
