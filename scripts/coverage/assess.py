#!/usr/bin/env python3
"""Assess supplied LLVM coverage structure offline; never authenticate execution."""
import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

MAX_JSON = 8 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_COUNT = (1 << 63) - 1
MAX_ITEMS = 4096
MAX_SOURCE_TOTAL = 32 * 1024 * 1024


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def fields(value, required, optional=()):
    require(type(value) is dict, 'expected object')
    require(set(required) <= value.keys() <= set(required) | set(optional), 'missing or unknown fields')


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= MAX_COUNT, 'invalid integer count')
    return value


def text(value):
    require(type(value) is str and 0 < len(value) <= 4096 and
            all(ord(c) >= 32 and ord(c) != 127 for c in value), 'invalid text')
    return value


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'invalid SHA256')
    return value


def sequence(value, minimum=0):
    require(type(value) is list and minimum <= len(value) <= MAX_ITEMS, 'invalid array size')
    return value


def relative(value):
    text(value)
    require(not value.startswith('/') and '\\' not in value and
            all(part not in ('', '.', '..') for part in value.split('/')), 'invalid source path')
    require(PurePosixPath(value).as_posix() == value, 'noncanonical source path')
    return value


def absolute_parts(path):
    # abspath would silently normalize '..', so reject it before any traversal.
    path = os.fspath(path)
    require('..' not in path.split('/') and '\\' not in path, 'invalid filesystem path')
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    require(all(p not in ('', '.', '..') for p in path.split('/')[1:]), 'noncanonical filesystem path')
    return path.split('/')[1:]


def directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute_parts(path):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(path, ceiling):
    parts = absolute_parts(path)
    require(parts, 'missing file name')
    parent = directory('/' + '/'.join(parts[:-1])) if len(parts) > 1 else os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= ceiling, 'nonregular or oversized input')
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            require(chunk, 'incomplete input read')
            chunks.append(chunk)
            remaining -= len(chunk)
        require(not os.read(fd, 1), 'input grew during read')
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after), 'input changed during read')
        return b''.join(chunks), (before.st_dev, before.st_ino)
    finally:
        os.close(fd)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def nonfinite(_):
        raise Invalid('nonfinite JSON value')

    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'nonfinite JSON value')
        return parsed

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise Invalid('malformed JSON') from error


def export_path(value, root):
    text(value)
    if value.startswith('/'):
        # Permit only the exact canonical root prefix for mapped source files.
        require('..' not in value.split('/') and '//' not in value, 'noncanonical export path')
        prefix = str(root) + '/'
        if value.startswith(prefix):
            return relative(value[len(prefix):])
        return value  # retained as unexpected; cannot match a scoped relative path
    return relative(value)


def declared_inventory(scope, result):
    """Retain safe declared identities even if later validation fails."""
    if type(scope) is not dict:
        return
    for name in ('source_files', 'caller_files', 'exclusions'):
        rows = scope.get(name)
        if type(rows) is not list or len(rows) > MAX_ITEMS:
            continue
        retained = []
        for index, row in enumerate(rows):
            if type(row) is not dict:
                retained.append({'index': index, 'path': None, 'status': 'UNKNOWN', 'line_count': None,
                                 'covered_lines': None, 'uncovered_lines': None, 'coverage_percent_display': None,
                                 'advisory_target_status': 'NOT_MEASURED'})
                continue
            path = row.get('path')
            try:
                text(path)
            except Invalid:
                path = None
            retained.append({'index': index, 'path': path,
                             'declared_sha256': row.get('sha256') if type(row.get('sha256')) is str and len(row['sha256']) <= 64 else None,
                             'status': 'UNKNOWN', 'line_count': None, 'covered_lines': None,
                             'uncovered_lines': None, 'coverage_percent_display': None,
                             'advisory_target_status': 'NOT_MEASURED',
                             'declared_mapping': {key: row.get(key) for key in
                                                  ('cpp_origin', 'production_symbols', 'activation_predicate', 'applicability')}})
        if name == 'source_files':
            result['files'] = retained
        elif name == 'caller_files':
            result['declared_caller_files'] = retained
        else:
            result['exclusions'] = rows


def assess(scope, export, root, export_sha, seen_inputs, context, capture_source):
    fields(scope, ('schema_version', 'scope_id', 'source_files', 'caller_files', 'capture', 'required_boundaries', 'exclusions'))
    require(type(scope['schema_version']) is int and scope['schema_version'] == 1, 'unsupported scope schema')
    text(scope['scope_id'])
    expected = {}
    callers = {}
    source_hashes = {}
    for target, rows in ((expected, sequence(scope['source_files'], 1)), (callers, sequence(scope['caller_files']))):
        for row in rows:
            fields(row, ('path', 'sha256', 'cpp_origin', 'production_symbols', 'activation_predicate', 'applicability') if target is expected else ('path', 'sha256'))
            path = relative(row['path'])
            digest(row['sha256'])
            require(path not in expected and path not in callers, 'duplicate source path')
            if target is expected:
                require(path.endswith('.rs'), 'expected Rust production source')
            raw, inode, actual = capture_source(path, row['sha256'], 'replacement' if target is expected else 'caller')
            require(inode not in seen_inputs, 'source/input hardlink alias')
            seen_inputs.add(inode)
            require(actual == row['sha256'], 'source hash mismatch: ' + path)
            source_hashes[path] = actual
            target[path] = row
    excluded = set()
    for exclusion in sequence(scope['exclusions']):
        fields(exclusion, ('path', 'sha256', 'kind', 'reason', 'review_sha256'))
        path = relative(exclusion['path'])
        require(path not in expected and path not in callers and path not in excluded, 'production or duplicate exclusion')
        require(exclusion['kind'] in ('test', 'benchmark', 'example', 'dependency', 'generated_nonproduction'), 'unsupported exclusion kind')
        text(exclusion['reason'])
        digest(exclusion['review_sha256'])
        digest(exclusion['sha256'])
        raw, inode, actual = capture_source(path, exclusion['sha256'], 'excluded')
        require(inode not in seen_inputs, 'excluded input alias')
        seen_inputs.add(inode)
        require(actual == exclusion['sha256'], 'exclusion source hash mismatch')
        excluded.add(path)
    capture = scope['capture']
    fields(capture, ('variant', 'mode', 'production_only', 'test_cfg_enabled', 'completion', 'export_sha256', 'binary_sha256', 'profile_sha256'))
    require(capture['variant'] in ('rust_candidate', 'rust_current'), 'unsupported captured variant')
    require(capture['mode'] in ('production_caller', 'unit_diagnostic'), 'unsupported capture mode')
    require(type(capture['production_only']) is bool and type(capture['test_cfg_enabled']) is bool, 'invalid configuration flag')
    fields(capture['completion'], ('state', 'exit_code'))
    require(capture['completion']['state'] == 'EXITED' and type(capture['completion']['exit_code']) is int and
            capture['completion']['exit_code'] == 0, 'failed or incomplete producer capture')
    for name in ('export_sha256', 'binary_sha256', 'profile_sha256'):
        digest(capture[name])
    require(capture['export_sha256'] == export_sha, 'export digest mismatch')
    production = capture['mode'] == 'production_caller'
    require(not production or (capture['production_only'] and not capture['test_cfg_enabled']), 'test code cannot satisfy production denominator')
    require(type(export) is dict and export.get('type') == 'llvm.coverage.json.export' and
            export.get('version') in ('2.0.1', '3.1.0'), 'unsupported LLVM export schema')
    datasets = sequence(export.get('data'), 1)
    require(len(datasets) == 1, 'multiple export datasets require a reviewed merge rule')
    dataset = datasets[0]
    require(type(dataset) is dict, 'invalid LLVM dataset')
    reported = {}
    for row in sequence(dataset.get('files')):
        require(type(row) is dict and type(row.get('summary')) is dict, 'invalid file record')
        path = export_path(row.get('filename'), root)
        require(path not in reported, 'duplicate or aliased export file')
        lines = row['summary'].get('lines')
        require(type(lines) is dict and 'count' in lines and 'covered' in lines, 'missing line summary')
        count, covered = integer(lines['count']), integer(lines['covered'])
        require(covered <= count, 'covered lines exceed total')
        reported[path] = (count, covered)
    missing = sorted(set(expected) - reported.keys())
    context['missing_expected_files'] = missing
    require(not missing, 'missing expected files: ' + ', '.join(missing))
    files = []
    for path in sorted(expected):
        count, covered = reported[path]
        require(count > 0, 'zero denominator: ' + path)
        above = 100 * covered > 70 * count
        files.append({'path': path, 'source_sha256': source_hashes[path], 'line_count': count,
                      'covered_lines': covered, 'uncovered_lines': count-covered,
                      'coverage_percent_display': round(100 * covered / count, 3),
                      'advisory_target_status': ('ABOVE_70' if above else 'LOW') if production else 'NOT_MEASURED'})
    functions = {}
    for function in sequence(dataset.get('functions')):
        require(type(function) is dict, 'invalid function record')
        name, count = text(function.get('name')), integer(function.get('count'))
        filenames = tuple(export_path(path, root) for path in sequence(function.get('filenames'), 1))
        require(len(set(filenames)) == len(filenames), 'duplicate function file identity')
        for path in filenames:
            key = (path, name)
            require(key not in functions, 'ambiguous function identity')
            functions[key] = count
    boundaries = []
    ids = set()
    boundary_keys = set()
    required = sequence(scope['required_boundaries'], 1 if production else 0)
    for row in required:
        fields(row, ('id', 'rust_file', 'rust_function', 'caller_file', 'caller_function'))
        boundary_id = text(row['id'])
        require(boundary_id not in ids, 'duplicate boundary id')
        ids.add(boundary_id)
        rust_file, caller_file = relative(row['rust_file']), relative(row['caller_file'])
        require(rust_file in expected and caller_file in callers, 'boundary outside expected source scope')
        rust_key, caller_key = (rust_file, text(row['rust_function'])), (caller_file, text(row['caller_function']))
        pair = (rust_key, caller_key)
        require(pair not in boundary_keys, 'duplicate boundary mapping')
        boundary_keys.add(pair)
        rust_count, caller_count = functions.get(rust_key), functions.get(caller_key)
        if production:
            require(rust_count is not None and caller_count is not None and rust_count > 0 and caller_count > 0,
                    'missing or zero boundary counter: ' + boundary_id)
        boundaries.append({**row, 'rust_count': rust_count, 'caller_count': caller_count, 'execution_verified': False})
    for row in scope['source_files']:
        fields(row['cpp_origin'], ('path', 'symbols', 'sha256', 'applicability'))
        relative(row['cpp_origin']['path'])
        digest(row['cpp_origin']['sha256'])
        require(row['cpp_origin']['applicability'] == 'baseline_metadata_only', 'original C++ baseline must be separate from surviving caller')
        cpp_symbols = sequence(row['cpp_origin']['symbols'], 1)
        require(len({text(symbol) for symbol in cpp_symbols}) == len(cpp_symbols), 'duplicate original C++ symbol')
        text(row['activation_predicate'])
        application = row['applicability']
        fields(application, ('variant', 'kind', 'boundary_ids', 'review_sha256', 'source_sha256'))
        require(application['variant'] == capture['variant'], 'source variant applicability mismatch')
        require(application['kind'] in ('direct_boundary', 'helper'), 'unsupported source applicability')
        digest(application['review_sha256'])
        require(digest(application['source_sha256']) == row['sha256'], 'review source identity mismatch')
        related = sequence(application['boundary_ids'], 1)
        require(len({text(value) for value in related}) == len(related) and (not production or set(related) <= ids),
                'source applicability references absent/duplicate boundary')
        if production and application['kind'] == 'direct_boundary':
            require(any(boundary['id'] in related and boundary['rust_file'] == row['path'] for boundary in required),
                    'replacement has no direct boundary mapping')
        symbols = sequence(row['production_symbols'], 1)
        require(len({text(symbol) for symbol in symbols}) == len(symbols), 'duplicate production symbol')
        records = []
        for symbol in symbols:
            require(not production or (row['path'], symbol) in functions, 'unmapped production symbol: ' + row['path'] + ':' + symbol)
            records.append({'name': symbol, 'count': functions.get((row['path'], symbol))})
        for boundary in required:
            if boundary['rust_file'] == row['path']:
                require(boundary['rust_function'] in symbols, 'active Rust boundary omitted from production symbols')
        parsed = next(item for item in files if item['path'] == row['path'])
        parsed.update(production_symbols=records, cpp_origin=row['cpp_origin'],
                      activation_predicate=row['activation_predicate'], applicability=application, status='PARSED_UNVERIFIED')
    total, covered = sum(r['line_count'] for r in files), sum(r['covered_lines'] for r in files)
    integer(total)
    return {'schema_version': 1, 'scope_id': scope['scope_id'], 'evidence_status': 'VALID_STRUCTURE',
            'execution_verified': False, 'lineage_status': 'UNVERIFIED', 'scope_completeness_review': 'UNVERIFIED',
            'capture_mode': capture['mode'], 'capture_assertions': capture, 'source_hashes': source_hashes,
            'producer_export_version': export['version'],
            'files': files, 'missing_expected_files': missing,
            'unexpected_report_files': sorted(set(reported) - set(expected)), 'exclusions': scope['exclusions'],
            'boundaries': boundaries, 'caller_reach_status': 'COUNTERS_PRESENT_REVIEW_REQUIRED' if production else 'UNKNOWN',
            'target_status': ('ABOVE_70_ALL_EXPECTED_FILES' if all(r['advisory_target_status'] == 'ABOVE_70' for r in files) else 'LOW') if production else 'NOT_MEASURED',
            'aggregate': {'line_count': total, 'covered_lines': covered, 'uncovered_lines': total-covered},
            'advisory_only': True, 'speed_qualification': 'NOT_ASSESSED', 'reasons': [],
            'limitations': ['Counts are parsed from supplied export; execution and source scope are not authenticated.',
                            'Production configuration and binary/profile identities are unverified assertions.',
                            'Counter presence does not prove causal C++ dispatch into Rust or native speed.']}


def report(result):
    lines = ['# Coverage evidence assessment', '', 'Evidence structure: **' + result['evidence_status'] + '**.', '',
             'Execution and build lineage: **UNVERIFIED**. Speed qualification: **NOT_ASSESSED**.', '',
             'Advisory strictly-above-70% target: **' + result['target_status'] + '**.', '',
             'Caller reach: **' + result['caller_reach_status'] + '**.', '',
             'Parsed counts do not authenticate production coverage, C++ retirement, integration or deployment.', '',
             '| Expected Rust file | Covered / instrumentable lines | Advisory target |',
             '| --- | --- | --- |']
    for row in result['files']:
        label = html.escape(row['path'] or '[invalid declared path]').replace('|', '&#124;').replace('`', '&#96;')
        lines.append('| ' + label + ' | ' + ('UNKNOWN' if row['line_count'] is None else str(row['covered_lines']) + ' / ' + str(row['line_count'])) + ' | ' + row['advisory_target_status'] + ' |')
    for reason in result['reasons']:
        lines.extend(['', 'HOLD reason: ' + html.escape(reason)])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--export', dest='export_path', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output_fd = None
    try:
        parts = absolute_parts(args.output_dir)
        require(parts, 'invalid output directory')
        parent = directory('/' + '/'.join(parts[:-1])) if len(parts) > 1 else os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.mkdir(parts[-1], mode=0o700, dir_fd=parent)
            output_fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
    except (Invalid, OSError) as error:
        print('Output not created: ' + str(error), file=sys.stderr)
        return 2

    def write(name, raw):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    result = {'schema_version': 1, 'evidence_status': 'HOLD', 'execution_verified': False,
              'lineage_status': 'UNVERIFIED', 'scope_completeness_review': 'UNVERIFIED',
              'target_status': 'NOT_MEASURED', 'caller_reach_status': 'UNKNOWN', 'speed_qualification': 'NOT_ASSESSED',
              'files': [], 'boundaries': [], 'aggregate': None, 'advisory_only': True, 'reasons': [],
              'source_custody': [], 'source_hashes': {}, 'exclusions': [], 'declared_caller_files': [],
              'missing_expected_files': [], 'source_capture_bytes': 0, 'source_capture_limit_bytes': MAX_SOURCE_TOTAL}
    inputs = {}
    try:
        seen = set()
        captures = {}
        for name, path in (('scope', args.scope), ('export', args.export_path)):
            raw, inode = read_regular(path, MAX_JSON)
            write(name + '.raw', raw)
            inputs[name + '_sha256'] = hashlib.sha256(raw).hexdigest()
            captures[name] = raw
            if name == 'scope':
                try:
                    declared_inventory(strict_json(raw), result)
                except Invalid:
                    # Preserve readable export bytes before strict scope rejection.
                    pass
            require(inode not in seen, 'aliased control inputs')
            seen.add(inode)
        scope = strict_json(captures['scope'])
        declared_inventory(scope, result)
        root_fd = directory(args.source_root)
        os.close(root_fd)
        root = Path('/' + '/'.join(absolute_parts(args.source_root)))
        export = strict_json(captures['export'])
        # Preliminary safe missing-map information survives source/hash failures.
        if type(export) is dict and type(export.get('data')) is list:
            names = set()
            for dataset in export['data'][:MAX_ITEMS]:
                if type(dataset) is dict and type(dataset.get('files')) is list:
                    for row in dataset['files'][:MAX_ITEMS]:
                        try:
                            if type(row) is dict:
                                names.add(export_path(row.get('filename'), root))
                        except Invalid:
                            pass
            result['missing_expected_files'] = [row['path'] for row in result['files']
                                                if row['path'] is not None and row['path'] not in names]

        def capture_source(path, declared, role):
            remaining = MAX_SOURCE_TOTAL - result['source_capture_bytes']
            try:
                raw, inode = read_regular(root / path, min(MAX_SOURCE, remaining))
            except (Invalid, OSError) as error:
                record = {'path': path, 'role': role, 'declared_sha256': declared,
                          'observed_sha256': None, 'raw_path': None, 'status': 'UNAVAILABLE', 'reason': str(error)}
                result['source_custody'].append(record)
                write('source-unavailable-' + str(len(result['source_custody'])).zfill(4) + '.json', (json.dumps(record, indent=2) + '\n').encode())
                raise
            name = 'source-' + str(len(result['source_custody'])).zfill(4) + '.raw'
            observed = hashlib.sha256(raw).hexdigest()
            write(name, raw)
            record = {'path': path, 'role': role, 'declared_sha256': declared, 'observed_sha256': observed,
                      'bytes': len(raw), 'raw_path': name, 'status': 'CAPTURED_UNINTERPRETED'}
            result['source_custody'].append(record)
            result['source_capture_bytes'] += len(raw)
            result['source_hashes'][path] = observed
            # Immutable receipt committed before any declared-hash comparison.
            write(name + '.json', (json.dumps(record, indent=2) + '\n').encode())
            return raw, inode, observed

        measured = assess(scope, export, root, inputs['export_sha256'], seen, result, capture_source)
        measured.update(source_custody=result['source_custody'], source_capture_bytes=result['source_capture_bytes'],
                        source_capture_limit_bytes=MAX_SOURCE_TOTAL)
        result = measured
    except (Invalid, OSError, RecursionError, OverflowError) as error:
        result['reasons'].append(str(error))
        for row in result['files']:
            row['reasons'] = [str(error)]
    try:
        result['input_hashes'] = inputs
        write('source-custody.json', (json.dumps(result['source_custody'], indent=2) + '\n').encode())
        write('coverage-assessment.json', (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
        write('coverage-report.md', report(result).encode())
    except OSError as error:
        print('Output failure; incomplete attempt retained: ' + str(error), file=sys.stderr)
        return 2
    finally:
        os.close(output_fd)
    return 0 if result['evidence_status'] == 'VALID_STRUCTURE' else 2


if __name__ == '__main__':
    sys.exit(main())
