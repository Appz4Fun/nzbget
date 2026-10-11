#!/usr/bin/env python3
"""Require the packet unit/ABI tests to kill representative semantic mutants.
Standalone rustc compilation remains remote and under the build locks.
"""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
source = (ROOT / 'rust/src/parcrc_batch.rs').read_text()
tests = (ROOT / 'rust/tests/parcrc_batch_unit.rs').read_text().replace(
    'use nzbget_rs::parcrc_batch::', 'use crate::parcrc_batch::')
mutations = {
    'big_endian_read': ('u32::from_le_bytes', 'u32::from_be_bytes'),
    'reverse_order': ('for i in 0..count {', 'for i in (0..count).rev() {'),
    'discard_first_crc': ('if i == 0 {\n            block', 'if i == 0 {\n            0'),
    'zero_length_combines': ('else if blocksize == 0 {', 'else if false {'),
    'wrong_polynomial': ('0xedb8_8320', '0xedb8_8321'),
    'accept_short_descriptor': ('if required > len || (count != 0 && bytes.is_null())',
                                'if count != 0 && bytes.is_null()'),
}
with tempfile.TemporaryDirectory(prefix='parcrc-mutants-') as tmp:
    temp = Path(tmp)
    for name, (before, after) in mutations.items():
        assert before in source
        path = temp / f'{name}.rs'
        path.write_text(source.replace(before, after))
        crate = temp / 'check.rs'
        crate.write_text(f'#[path={json.dumps(str(ROOT / "rust/src/crc.rs"))}] mod crc;\n'
                         f'#[path={json.dumps(str(path))}] mod parcrc_batch;\n' + tests)
        binary = temp / 'check'
        subprocess.run(['rustc', '--edition=2021', '--test', '-O', str(crate), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        log = ROOT / 'logs' / f'mutation-{name}.log'
        log.parent.mkdir(exist_ok=True)
        log.write_text(result.stdout + result.stderr)
        if result.returncode == 0:
            raise SystemExit(f'SURVIVED: {name}')
        print(f'killed: {name} (exit {result.returncode})')
