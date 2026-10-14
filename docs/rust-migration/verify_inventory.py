#!/usr/bin/env python3
"""Reproduce the lexical inventory and verify its immutable source bindings.

Run from the repository root on supported POSIX Python (including WSL).
Native Windows Python is unsupported: safe directory-descriptor traversal is required.
This reads local Git objects and metadata only.
It does not build, run tests, infer compiled coverage, or update the inventory.
The original core scan was recovered from its recorded derivation command;
version 1 preserves those regex rules and verifies the supplemental file sets.
Manual boundary/dependency annotations require separate source review.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

VERSION = 6
INVENTORY_SCHEMA_VERSION = 1
INVENTORY_KEYS = frozenset({
    'cpp_call_like_occurrences', 'daemon_cpp', 'derivation', 'exports',
    'exports_without_daemon_cpp_occurrence', 'functional_test_sources', 'method',
    'rust_cpp_test_sources', 'rust_modules', 'rust_public_abi_headers',
    'rust_test_python_drivers', 'schema_version', 'source_blobs', 'source_commit',
    'source_tree', 'summary', 'supplementary_test_audit_commit',
})
METHOD_DECLARATION = 'Bounded Git blob reads; lexical public C ABI export and call-like symbol occurrence inventory. Comments, preprocessor branches and dead code can match. No compile, linking, reachability, benchmark, or deployment result inferred. Rust source line counts include test code and comments. No language percentage inferred.'
FUNCTIONAL_SOURCE_DISPOSITION = 'Preserve complete-daemon test/provider/generator/runner contract and original evidence; translate assertions and setup to supported Rust daemon/caller owners before retiring native executable/build/platform coupling. Source-only UNRUN, not compiled/route/correctness/performance/deployment proof.'
DERIVATION_DECLARATION = {
    'capture_provenance': 'Original core/Rust ABI-test derivation commands recovered retrospectively; their unchanged results are preserved. Checked-in functional test inputs are a separately identified source audit; no historical execution is recast as prospective.',
    'invocation': 'python3 docs/rust-migration/verify_inventory.py --inventory docs/rust-migration/source-inventory.json',
    'parser_path': 'docs/rust-migration/verify_inventory.py',
    'scope': 'reproduce original lexical fields and immutable source bindings; verify supplemental Rust ABI/test classifications and separately indexed checked-in functional source inputs; manual boundary/dependency annotations and capture-event authenticity require independent review',
    'working_directory': 'repository root',
}
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


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON member: ' + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('nonstandard JSON constant: ' + value)


def bounded_file(path, limit=4 * 1024 * 1024):
    require(all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))
            and os.open in os.supports_dir_fd,
            'supported POSIX Python directory-descriptor traversal required; use WSL on Windows')
    path = Path(path)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    require(bool(parts) and len(parts) <= 256, 'bounded file path required')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    # Pin each directory object; O_NOFOLLOW on the final file alone does not
    # prevent an ancestor symlink from redirecting the input or parser path.
    with ExitStack() as descriptors:
        parent = os.open('/' if path.is_absolute() else '.', directory_flags)
        descriptors.callback(os.close, parent)
        require(stat.S_ISDIR(os.fstat(parent).st_mode), 'directory input required')
        for component in parts[:-1]:
            parent = os.open(component, directory_flags, dir_fd=parent)
            descriptors.callback(os.close, parent)
            require(stat.S_ISDIR(os.fstat(parent).st_mode), 'directory input required')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.callback(os.close, fd)
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


def git(*args, payload=None):
    return subprocess.check_output(['git', '--no-replace-objects', *args], input=payload, timeout=30)


def table(revision):
    require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'full immutable commit ID required')
    require(git('cat-file', '-t', revision).decode().strip() == 'commit', 'source ID must name a commit object')
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
    inventory = json.loads(bounded_file(path), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
    require(type(inventory) is dict and set(inventory) == INVENTORY_KEYS, 'unsupported inventory key set')
    require(inventory['method'] == METHOD_DECLARATION, 'unsupported method declaration')
    schema = inventory.get('schema_version')
    require(type(schema) is int and schema == INVENTORY_SCHEMA_VERSION, 'unsupported inventory schema version')
    derivation = inventory['derivation']
    require(type(derivation['parser_version']) is int and derivation['parser_version'] == VERSION, 'unsupported parser version')
    require(derivation['parser_path'] == 'docs/rust-migration/verify_inventory.py', 'unexpected parser path')
    require(derivation['parser_sha256'] == hashlib.sha256(bounded_file(Path(__file__))).hexdigest(), 'parser identity mismatch')
    expected_derivation = dict(DERIVATION_DECLARATION, parser_version=VERSION,
                              parser_sha256=derivation['parser_sha256'])
    require(same_json(derivation, expected_derivation), 'unsupported derivation key set/types/values')
    revision = inventory['source_commit']
    require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'full immutable source commit required')
    require(git('cat-file', '-t', revision).decode().strip() == 'commit', 'source ID must name a commit object')
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
                or (p.startswith('rust/include/') and p.endswith(('.h', '.hpp', '.hh')))
                or p.startswith('tests/functional/')}
    extra_bindings, extra_sources = read_sources(selected)
    original = table(revision)
    for p, row in extra_bindings.items():
        require(original.get(p) == supplemental[p], 'supplemental source differs from original: ' + p)
    bindings.update(extra_bindings)
    require(same_json(inventory['source_blobs'], bindings), 'source binding set/content mismatch')
    cpp_paths = {p for p in selected if p.startswith('rust/tests/') and p.endswith(CPP_TEST_SUFFIXES)}
    py_paths = {p for p in selected if p.startswith('rust/tests/') and p.endswith('.py')}
    abi_paths = {p for p in selected if p.startswith('rust/include/')}
    functional_paths = {p for p in selected if p.startswith('tests/functional/')}
    for key, expected in [('rust_cpp_test_sources', cpp_paths), ('rust_test_python_drivers', py_paths),
                          ('rust_public_abi_headers', abi_paths), ('functional_test_sources', functional_paths)]:
        rows = inventory[key]
        require(len(rows) == len(expected) and {r['path'] for r in rows} == expected, 'supplemental file set mismatch: ' + key)
        for row in rows:
            require(row['git_blob'] == bindings[row['path']]['blob'], 'supplemental blob mismatch')
    expected_functional_sources = [{
        'path': p, 'git_blob': bindings[p]['blob'],
        'source_audit_commit': inventory['supplementary_test_audit_commit'],
        'disposition': FUNCTIONAL_SOURCE_DISPOSITION,
        'execution_status': 'UNRUN in this inventory audit',
        'source_role': 'platform runner' if p.endswith('.sh') else 'functional test, fixture provider or generator source',
    } for p in sorted(functional_paths)]
    require(same_json(inventory['functional_test_sources'], expected_functional_sources),
            'functional source declarations mismatch')
    expected_cpp_sources = [{
        'path': p, 'git_blob': bindings[p]['blob'],
        'kind': 'C++ include fragment' if p.endswith('.inc') else 'C++ test/caller harness',
        'compiled_readiness': 'unknown',
        'disposition': 'preserve contracts, translate to Rust tests, retire C++ source',
    } for p in sorted(cpp_paths)]
    require(same_json(inventory['rust_cpp_test_sources'], expected_cpp_sources),
            'C++ test source declarations mismatch')
    expected_abi_headers = [{
        'path': p, 'git_blob': bindings[p]['blob'], 'kind': 'public C ABI header',
        'compiled_abi_coverage': 'unknown',
        'disposition': 'preserve struct/callback/ownership/ABI contracts; replace C++ consumers/adapters and migrate required interface declarations under reviewed Rust ownership before final retirement',
    } for p in sorted(abi_paths)]
    require(same_json(inventory['rust_public_abi_headers'], expected_abi_headers),
            'public ABI header declarations mismatch')
    expected_python_drivers = []
    for p in sorted(py_paths):
        text = extra_sources[p]
        include, build = bool(INCLUDE_RE.search(text)), bool(BUILD_RE.search(text))
        classification = ('emitted C++ source' if include else 'C++-related driver candidate' if build
                          else 'analysis/orchestration source; transitive C++ dependency review pending')
        expected_python_drivers.append({
            'path': p, 'git_blob': bindings[p]['blob'],
            'cpp_include_literal': include, 'cpp_build_or_artifact_literal': build,
            'classification': classification, 'execution': 'not inferred from source',
            'disposition': 'preserve assertions/evidence; translate or remove C++ coupling before native target retirement; retain justified Python analysis',
        })
    require(same_json(inventory['rust_test_python_drivers'], expected_python_drivers),
            'Python driver declarations mismatch')
    expected_summary = dict(derived['summary'])
    expected_summary.update({
        'rust_cpp_test_harness_files': sum(p.endswith('.cpp') for p in cpp_paths),
        'rust_cpp_test_include_fragments': sum(p.endswith('.inc') for p in cpp_paths),
        'rust_test_python_drivers': len(py_paths),
        'rust_public_abi_headers': len(abi_paths),
        'functional_test_source_inputs': len(functional_paths),
        'functional_dupefallback_source_inputs': sum(p.startswith('tests/functional/dupefallback/') for p in functional_paths),
    })
    require(type(inventory['summary']) is dict and same_json(inventory['summary'], expected_summary),
            'summary key set/type/count mismatch')
    return {'result': 'VERIFIED_LEXICAL_INVENTORY_ONLY', 'parser_version': VERSION,
            'source_commit': revision, 'summary': expected_summary, 'source_bindings': len(bindings),
            'limitations': 'No transitive graph, native build, compiled coverage, parity, speed or deletion proof.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('docs/rust-migration/source-inventory.json'))
    args = parser.parse_args()
    print(json.dumps(verify(args.inventory), indent=2))
