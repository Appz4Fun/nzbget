#!/usr/bin/env python3
"""Run standalone module tests against representative wrong implementations."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]
source = (ROOT/'rust/src/streampatchparts.rs').read_text()
mutations = {
    'sorted-inclusive-adjacency': ('d.offset.wrapping_add(d.size) <= hole.offset', 'd.offset.wrapping_add(d.size) < hole.offset'),
    'inclusive-adjacency': ('h.offset < end)', 'h.offset <= end)'),
    'drop-zero-negative-sizes': ('let end = donor.offset.wrapping_add(donor.size);', 'if donor.size <= 0 { continue; }\n        let end = donor.offset.wrapping_add(donor.size);'),
    'lose-margin-marking': ('next_index = to + 1;', 'next_index = to + 2;'),
    'lose-prefix-maximum': ('maximum = maximum.max(hole.1);', 'maximum = hole.1;'),
}
with tempfile.TemporaryDirectory(prefix='streampatch-mutations-') as temp:
    for name, (old, new) in mutations.items():
        assert old in source, name
        path = Path(temp)/f'{name}.rs'
        path.write_text(source.replace(old,new,1))
        exe = path.with_suffix('')
        subprocess.run(['rustc','--crate-name','streampatch_mutant','--test',str(path),'-o',str(exe)],check=True)
        result = subprocess.run([str(exe)],capture_output=True,text=True)
        if result.returncode == 0:
            raise SystemExit(f'SURVIVED {name}')
        if 'test result: FAILED' not in result.stdout:
            raise SystemExit(f'non-test failure {name}: {result.stdout} {result.stderr}')
        print(f'KILLED {name}: '+next(x for x in result.stdout.splitlines() if x.startswith('test result:')))
