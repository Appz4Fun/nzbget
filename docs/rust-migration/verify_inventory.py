#!/usr/bin/env python3
"""Reproduce the lexical inventory and verify its immutable source bindings.

Run from the repository root. This reads local Git objects and metadata only.
It does not build, run tests, infer compiled coverage, or update the inventory.
The original core scan was recovered from its recorded derivation command;
version 1 preserves those regex rules and verifies the supplemental file sets.
Manual boundary/dependency annotations require separate source review.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

VERSION = 1
EXPORT_RE = re.compile(r'pub\s+(?:unsafe\s+)?extern\s+"C"\s+fn\s+(nzbget_rs_\w+)\s*\(')
CPP_SYMBOL_RE = re.compile(r'\bnzbget_rs_\w+\s*(?=\()')
INCLUDE_RE = re.compile(r'#\s*include\b')
BUILD_RE = re.compile(r'\.cpp\b|\.inc\b|clang\+\+|g\+\+|\bCXX\b|CMakeFiles|\blibnzbget\b|--build')
CPP_TEST_SUFFIXES = ('.cpp', '.cc', '.cxx', '.C', '.inc', '.hpp', '.hh', '.ipp', '.tpp')
SOURCE_SUFFIXES = ('.rs', '.cpp', '.h', '.cc', '.cxx', '.hpp', '.hh', '.cmake')


def require(predicate, message):
    if not predicate:
        raise ValueError(message)


def same_json(left, right):
    # Preserve JSON types: Python otherwise treats true == 1 and false == 0.
    return json.dumps(left, sort_keys=True, separators=(',', ':')) == json.dumps(right, sort_keys=True, separators=(',', ':'))


def bounded_file(path, limit=4 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'bounded regular input required')
        chunks, remaining = [], before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            require(bool(chunk), 'incomplete input read')
            chunks.append(chunk)
            remaining -= len(chunk)
        require(os.read(fd, 1) == b'', 'input grew during read')
        after = os.fstat(fd)
        fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(fields(before) == fields(after), 'input changed during read')
        return b''.join(chunks)
    finally:
        os.close(fd)


def git(*args, payload=None):
    return subprocess.check_output(['git', *args], input=payload, timeout=30)


def table(revision):
    require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'full immutable commit ID required')
    entries = {}
    for raw in git('ls-tree', '-rlz', revision).split(b'\0'):
        if not raw:
            continue
        meta, name = raw.split(b'\t', 1)
        mode, kind, blob, size = meta.decode().split()
        name = name.decode('utf-8')
        entries[name] = (mode, kind, blob, size)
    return entries


def read_sources(entries):
    bindings = {}
    for name, (mode, kind, blob, size) in entries.items():
        require(kind == 'blob' and mode in ('100644', '100755'), 'nonregular source: ' + name)
        size = int(size)
        require(0 <= size <= 16 * 1024 * 1024, 'source exceeds bound: ' + name)
        bindings[name] = {'blob': blob, 'size': size}
    require(sum(x['size'] for x in bindings.values()) < 64 * 1024 * 1024, 'source aggregate exceeds bound')
    payload = ('\n'.join(x['blob'] for x in bindings.values()) + '\n').encode()
    output = git('cat-file', '--batch', payload=payload)
    sources, at = {}, 0
    for name, info in bindings.items():
        end = output.index(b'\n', at)
        require(output[at:end].decode().split() == [info['blob'], 'blob', str(info['size'])], 'unexpected Git object header')
        at = end + 1
        body = output[at:at + info['size']]
        require(len(body) == info['size'], 'incomplete Git blob')
        identity = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        require(identity == info['blob'], 'Git blob content identity mismatch')
        sources[name] = body.decode('utf-8')
        at += info['size']
        require(output[at:at + 1] == b'\n', 'missing Git object delimiter')
        at += 1
    require(at == len(output), 'unexpected trailing Git output')
    return bindings, sources


def core_inventory(revision):
    entries = {p: v for p, v in table(revision).items()
               if (p.startswith(('rust/src/', 'daemon/', 'tests/', 'platforms/'))
                   or p in ('cmake/rust.cmake', 'daemon/sources.cmake', 'CMakeLists.txt'))
               and (p.endswith(SOURCE_SUFFIXES) or p == 'CMakeLists.txt')}
    bindings, sources = read_sources(entries)
    rust = {p: s for p, s in sources.items() if p.startswith('rust/src/') and p.endswith('.rs')}
    cpp = {p: s for p, s in sources.items() if p.startswith('daemon/') and p.endswith('.cpp')}
    exports = {}
    for path, source in rust.items():
        for match in EXPORT_RE.finditer(source):
            symbol = match.group(1)
            require(symbol not in exports, 'duplicate lexical export: ' + symbol)
            exports[symbol] = {'path': path, 'line': source.count('\n', 0, match.start()) + 1}
    references = {symbol: [{'path': p, 'line': s.count('\n', 0, m.start()) + 1}
                           for p, s in cpp.items()
                           for m in re.finditer(r'\b' + re.escape(symbol) + r'\s*\(', s)]
                  for symbol in exports}
    modules = []
    for path, source in sorted(rust.items()):
        name = Path(path).stem
        defined = [symbol for symbol, row in exports.items() if row['path'] == path]
        mentions = []
        if name not in ('ffi', 'lib'):
            for other, text in rust.items():
                if other == path:
                    continue
                mentions.extend({'path': other, 'line': text.count('\n', 0, m.start()) + 1}
                                for m in re.finditer(r'\bcrate::' + re.escape(name) + r'\b', text))
        modules.append({'module': name, 'path': path, 'blob': bindings[path]['blob'],
                        'lines': len(source.splitlines()), 'exported_symbols': defined,
                        'export_symbol_cpp_reference_files': sorted({r['path'] for symbol in defined for r in references[symbol]}),
                        'cross_module_mentions': mentions})
    cpp_rows = [{'path': p, 'blob': bindings[p]['blob'], 'lines': len(s.splitlines()),
                 'rust_symbol_mentions': [x.strip() for x in sorted(set(CPP_SYMBOL_RE.findall(s)))],
                 'rust_build_guard_mentions': s.count('NZBGET_USE_RUST')}
                for p, s in sorted(cpp.items())]
    without = sorted(symbol for symbol in exports if not references[symbol])
    summary = {'rust_src_files': len(rust),
               'rust_src_total_lines_including_tests_comments': sum(len(s.splitlines()) for s in rust.values()),
               'c_abi_exports': len(exports), 'c_abi_exports_with_cpp_call_like_occurrence': sum(bool(x) for x in references.values()),
               'c_abi_exports_without_cpp_call_like_occurrence': len(without), 'daemon_cpp_files': len(cpp),
               'daemon_cpp_total_lines_including_comments': sum(len(s.splitlines()) for s in cpp.values()),
               'daemon_cpp_with_rust_call_like_occurrence': sum(bool(r['rust_symbol_mentions']) for r in cpp_rows),
               'daemon_headers': sum(p.startswith('daemon/') and p.endswith('.h') for p in sources)}
    return bindings, {'rust_modules': modules, 'exports': exports, 'cpp_call_like_occurrences': references,
                      'exports_without_daemon_cpp_occurrence': without, 'daemon_cpp': cpp_rows, 'summary': summary}


def verify(path):
    inventory = json.loads(bounded_file(path))
    derivation = inventory['derivation']
    require(type(derivation['parser_version']) is int and derivation['parser_version'] == VERSION, 'unsupported parser version')
    require(derivation['parser_path'] == 'docs/rust-migration/verify_inventory.py', 'unexpected parser path')
    require(derivation['parser_sha256'] == hashlib.sha256(bounded_file(Path(__file__))).hexdigest(), 'parser identity mismatch')
    revision = inventory['source_commit']
    require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'full immutable source commit required')
    require(git('rev-parse', revision + '^{tree}').decode().strip() == inventory['source_tree'], 'source tree mismatch')
    bindings, derived = core_inventory(revision)
    for key, value in derived.items():
        if key == 'summary':
            for field, count in value.items():
                require(same_json(inventory[key][field], count), 'summary mismatch: ' + field)
        else:
            require(same_json(inventory[key], value), 'derived field mismatch: ' + key)
    supplemental = table(inventory['supplementary_test_audit_commit'])
    selected = {p: v for p, v in supplemental.items()
                if (p.startswith('rust/tests/') and p.endswith(CPP_TEST_SUFFIXES + ('.py',)))
                or (p.startswith('rust/include/') and p.endswith(('.h', '.hpp', '.hh')))}
    extra_bindings, extra_sources = read_sources(selected)
    original = table(revision)
    for p, row in extra_bindings.items():
        require(original.get(p) == supplemental[p], 'supplemental source differs from original: ' + p)
    bindings.update(extra_bindings)
    require(same_json(inventory['source_blobs'], bindings), 'source binding set/content mismatch')
    cpp_paths = {p for p in selected if p.startswith('rust/tests/') and p.endswith(CPP_TEST_SUFFIXES)}
    py_paths = {p for p in selected if p.endswith('.py')}
    abi_paths = {p for p in selected if p.startswith('rust/include/')}
    for key, expected in [('rust_cpp_test_sources', cpp_paths), ('rust_test_python_drivers', py_paths), ('rust_public_abi_headers', abi_paths)]:
        rows = inventory[key]
        require(len(rows) == len(expected) and {r['path'] for r in rows} == expected, 'supplemental file set mismatch: ' + key)
        for row in rows:
            require(row['git_blob'] == bindings[row['path']]['blob'], 'supplemental blob mismatch')
    for row in inventory['rust_test_python_drivers']:
        text = extra_sources[row['path']]
        include, build = bool(INCLUDE_RE.search(text)), bool(BUILD_RE.search(text))
        classification = ('emitted C++ source' if include else 'C++-related driver candidate' if build
                          else 'analysis/orchestration source; transitive C++ dependency review pending')
        require(same_json([row['cpp_include_literal'], row['cpp_build_or_artifact_literal'], row['classification']], [include, build, classification]), 'Python classification mismatch')
    for key, count in [('rust_cpp_test_harness_files', sum(p.endswith('.cpp') for p in cpp_paths)),
                       ('rust_cpp_test_include_fragments', sum(p.endswith('.inc') for p in cpp_paths)),
                       ('rust_test_python_drivers', len(py_paths)), ('rust_public_abi_headers', len(abi_paths))]:
        require(same_json(inventory['summary'][key], count), 'supplemental count mismatch: ' + key)
    return {'result': 'VERIFIED_LEXICAL_INVENTORY_ONLY', 'parser_version': VERSION,
            'source_commit': revision, 'summary': inventory['summary'], 'source_bindings': len(bindings),
            'limitations': 'No transitive graph, native build, compiled coverage, parity, speed or deletion proof.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('docs/rust-migration/source-inventory.json'))
    args = parser.parse_args()
    print(json.dumps(verify(args.inventory), indent=2))
