#!/usr/bin/env python3
"""Pure offline differential oracle; no importing proxy configuration or network code.

Emit a standalone Rust CLI beside bytes.rs/releasename.rs/dupeidentity.rs:
  python3 rust/tests/dupeidentity_differential.py --emit-wrapper /tmp/identity_cli.rs
Compile/run it on an eligible remote worker, then pass its invocation with --command.
The Python reference is loaded with AST selection of pure definitions only.
"""
import argparse
import ast
import functools
import json
import statistics
import re
import random
import shlex
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

WRAPPER = r'''
mod bytes; mod releasename; mod dupeidentity;
use std::io::{self, BufRead};
use dupeidentity::*;
fn unhex(s: &str) -> Vec<u8> { if s=="-" { return vec![]; } (0..s.len()).step_by(2).map(|i|u8::from_str_radix(&s[i..i+2],16).unwrap()).collect() }
fn hex(b: &[u8]) -> String { b.iter().map(|b|format!("{b:02x}")).collect() }
fn main() {
 for line in io::stdin().lock().lines() {
  let line=line.unwrap(); let p:Vec<_>=line.split_whitespace().collect();
  if p[0]=="I" {
   match inner_entry(&unhex(p[1]),&unhex(p[2]),p[3].parse().unwrap(),p[4].parse().unwrap()) {
    None=>println!("-"),Some(i)=>println!("{} {} {}",hex(&i.extension),i.bytes,hex(&i.name))
   }
  } else if p[0]=="B" {
   let iterations:u64=p[1].parse().unwrap();
   let data=unhex(p[2]);let name=unhex(p[3]);
   let total:u64=p[4].parse().unwrap();let minimum:u64=p[5].parse().unwrap();
   for _ in 0..iterations.min(2000) { std::hint::black_box(inner_entry(&data,&name,total,minimum)); }
   let start=std::time::Instant::now(); let mut checksum=0u64;
   for _ in 0..iterations {
    if let Some(id)=std::hint::black_box(inner_entry(std::hint::black_box(&data),std::hint::black_box(&name),std::hint::black_box(total),std::hint::black_box(minimum))) {
     checksum=checksum.wrapping_add(id.bytes).wrapping_add(id.name.len() as u64).wrapping_add(id.extension.len() as u64);
    }
   }
   println!("{} {}",start.elapsed().as_nanos(),std::hint::black_box(checksum));
  } else if p[0]=="P" {
   let a=unhex(p[1]);let b=unhex(p[2]);
   println!("{} {} {} {} {}",conflicts(&a,&b) as u8,consistent(&a,&b) as u8,hashlike(&b) as u8,
    candidate_ok(&a,p[3].parse().unwrap(),&b,p[4].parse().unwrap(),p[5].parse().unwrap(),false) as u8,
    candidate_ok(&a,p[3].parse().unwrap(),&b,p[4].parse().unwrap(),p[5].parse().unwrap(),true) as u8);
  } else if p[0]=="S" {
   println!("{}",same_data(p[1].parse().unwrap(),p[2].parse().unwrap(),p[3].parse().unwrap(),p[4].parse().unwrap()) as u8);
  } else if p[0]=="L" {
   let a=unhex(p[1]);let name=unhex(p[2]);
   let mine=Identity{name:unhex(p[3]),extension:unhex(p[4]),bytes:p[5].parse().unwrap()};
   let theirs=Identity{name:unhex(p[6]),extension:unhex(p[7]),bytes:p[8].parse().unwrap()};
   println!("{}",lenient_ok(&a,&name,if mine.bytes==0 {None}else{Some(&mine)},if theirs.bytes==0{None}else{Some(&theirs)}) as u8);
  }
 }
}
'''

def oracle(path):
    # Import only PTT's pure parser. Never execute proxy module top-level code.
    sys.path.insert(0, str(path.parent / 'vendor'))
    from ptt import parse_title
    wanted = {'clean_name', 'normalize_title', '_tokens', 'release_attrs', 'readable',
              'same_release', 'is_media', '_vint', '_rar5_file', '_rar4_file',
              'inner_entry', 'candidate_ok', 'digest_tags', 'hashlike', 'basename',
              'other_title', 'conflicts', 'consistent', 'same_data', 'lenient_ok'}
    constants = {'EXT_RE', 'JUNK_RE', 'COMPAT', 'EXACT', 'MEDIA_RE', 'SAMPLE_RE', 'TAG_WORDS', 'LENIENT_LISTED'}
    tree = ast.parse(path.read_text())
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted
                or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)]
    env = {'re': re, 'functools': functools, 'parse_title': parse_title}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), env)
    return env


def vi(n):
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def r4(name, size, packed=b'', flags=0, large=False):
    name=name.encode(); h=bytearray(32)
    flags |= 0x8000 | (0x100 if large else 0)
    struct.pack_into('<BHHII',h,2,0x74,flags,32+len(name)+(8 if large else 0),len(packed),size & 0xffffffff)
    struct.pack_into('<H',h,26,len(name))
    return bytes(h)+(struct.pack('<II',0,size >> 32) if large else b'')+name+packed


def r5(name,size,packed=b'',fileflags=0,kind=2):
    name=name.encode()
    h=vi(kind)+vi(2)+vi(len(packed))+vi(fileflags)+vi(size)+vi(0)
    if fileflags & 2: h+=b'\0'*4
    if fileflags & 4: h+=b'\0'*4
    h+=vi(0)+vi(0)+vi(len(name))+name
    return b'\0'*4+vi(len(h))+h+packed


def hx(s):
    if isinstance(s,str): s=s.encode()
    return s.hex() or '-'


def cases(o):
    rows=[]
    def inner(data,name='',total=0,minimum=0,expected='reference'):
        actual=o['inner_entry'](data,name,total,minimum)
        if expected != 'reference': actual=expected
        output='-' if actual is None else f'{hx(actual[0])} {actual[1]} {hx(actual[2])}'
        rows.append((f'I {hx(data)} {hx(name)} {total} {minimum}',output))
    names=['movie.mkv','movie.MP4','path/movie.m2ts','notes.nfo','movie.sample.mkv','sample/movie.mkv','movie_sample.mkv','moviesample.mkv']
    for name in names:
        for size in [0,1,999,1000,1234,0xffffffff,0x100000001]:
            for minimum in [0,1000,1235]:
                inner(b'bare',name,size,minimum)
                inner(b'Rar!\x1a\x07\x00'+r4(name,size,large=size>0xffffffff),'archive.rar',0,minimum)
                inner(b'Rar!\x1a\x07\x01\0'+r5(name,size),'archive.rar',0,minimum)
    for make,magic in [(r4,b'Rar!\x1a\x07\0'),(r5,b'Rar!\x1a\x07\x01\0')]:
        data=magic+make('notes.nfo',3,b'abc')+make('movie.sample.mkv',3,b'abc')+make('movie.mkv',1234)
        inner(data,'archive.rar',0,1000)
        for n in range(len(data)):
            inner(data[:n],'archive.rar',0,1000)
    for ff in [1,8,2,4,6]:
        inner(b'Rar!\x1a\x07\x01\0'+r5('movie.mkv',1234,fileflags=ff),'archive.rar')
    # Intentional stricter safety behavior than the Python parser for malformed headers.
    inner(b'Rar!\x1a\x07\0'+b'\0\0\x73\x80\0\x07\0'+r4('movie.mkv',1234),'archive.rar',expected=None)
    malformed=bytearray(b'Rar!\x1a\x07\0'+r4('movie.mkv',1234)); malformed[12:14]=struct.pack('<H',32)
    inner(bytes(malformed),'archive.rar',expected=None)
    inner(b'Rar!\x1a\x07\x01\0'+b'\0'*4+b'\xff'*10,'archive.rar',expected=None)
    rng=random.Random(0xD0FE)
    for _ in range(200):
        magic=rng.choice([b'Rar!\x1a\x07\0',b'Rar!\x1a\x07\x01\0'])
        inner(magic+bytes(rng.randrange(256) for _ in range(rng.randrange(0,100))),'archive.rar')
    for abytes in [0,1,1234]:
        for bbytes in [0,1,1234]:
            for afiles in [0,1,2]:
                for bfiles in [0,1,2]:
                    # Model summaries contain parity; native API takes data-file counts.
                    ainfo=SimpleNamespace(data_bytes=abytes, files=afiles+3, vol_bytes=(10,20), par_index='index')
                    binfo=SimpleNamespace(data_bytes=bbytes, files=bfiles+1, vol_bytes=(), par_index='index')
                    rows.append((f'S {abytes} {afiles} {bbytes} {bfiles}',str(int(o['same_data'](ainfo,binfo)))))
    a='Show.S01E02.2025.1080p.WEB-DL.x264-GRP'
    variations=[a,'Show.S01E02.2025.1080p.WEB-DL.x264-GRP.mkv','Show.S01E03.2025.1080p.WEB-DL.x264-GRP',
      'Show.S02E02.2025.1080p.WEB-DL.x264-GRP','Show.S01E02.2024.1080p.WEB-DL.x264-GRP',
      'Show.S01E02.2025.720p.WEB-DL.x264-GRP','Show.S01E02.2025.1080p.BluRay.x264-GRP',
      'Show.S01E02.2025.1080p.WEB-DL.x265-GRP','Show.S01E02.2025.1080p.WEB-DL.x264-OTHER',
      'Show.S01E02.2025.1080p.WEB-DL.x264.HDR-GRP','Show.S01E02.2025.1080p.WEB-DL.x264.DV-GRP',
      'Show.S01E02','Other.S01E02.2025.1080p.WEB-DL.x264-GRP','abcdef1234567890','abcdef1234567890.1080p',
      'abcdef1234567890.S01E02','abcdef1234567890.2025','abcdef1234567890.Other.1080p']
    for b in variations:
        for size in [0,990,1000,1010,1011]:
            for tol in [0,0.005,0.01]:
                vals=[o['conflicts'](a,b),o['consistent'](a,b),o['hashlike'](b)]
                for lenient in [False,True]: vals.append(o['candidate_ok'](a,1000,SimpleNamespace(title=b,size=size),tol,lenient))
                rows.append((f'P {hx(a)} {hx(b)} 1000 {size} {tol}', ' '.join(str(int(v)) for v in vals)))
    for b in variations:
        for mine in [None,('mkv',1234,a+'.mkv')]:
            for theirs in [None,('mkv',1234,b+'.mkv'),('mp4',1234,b+'.mp4'),('mkv',1235,b+'.mkv')]:
                def fields(v): return f'{hx(v[2])} {hx(v[0])} {v[1]}' if v else '- - 0'
                expected=o['lenient_ok'](a,None,SimpleNamespace(main_name=b),mine,theirs)
                rows.append((f'L {hx(a)} {hx(b)} {fields(mine)} {fields(theirs)}',str(int(expected))))
    return rows


def benchmark(args):
    """Function hot loops; timers exclude decoding, startup, SSH and IPC.

    Use --python-command to run the extracted pure Python reference on the
    same machine as --command. Proxy configuration and network code never run.
    Both timings include loop/checksum overhead and result allocations.
    """
    name='Show.S01E02.2025.1080p.WEB-DL.x264-GRP.mkv'
    size=5_000_000_001
    minimum=1_000_000
    fixtures=[
        ('bare-media',b'first article decoded data',name,size,minimum),
        ('RAR4',b'Rar!\x1a\x07\0'+r4(name,size,large=True),'archive.rar',0,minimum),
        ('RAR5',b'Rar!\x1a\x07\x01\0'+r5(name,size),'archive.rar',0,minimum),
        ('RAR4-sidecars',b'Rar!\x1a\x07\0'+r4('notes.nfo',3,b'abc')+r4('movie.sample.mkv',3,b'abc')+r4(name,size,large=True),'archive.rar',0,minimum),
        ('RAR5-sidecars',b'Rar!\x1a\x07\x01\0'+r5('notes.nfo',3,b'abc')+r5('movie.sample.mkv',3,b'abc')+r5(name,size),'archive.rar',0,minimum),
    ]
    wanted={'is_media','_vint','_rar5_file','_rar4_file','inner_entry'}
    constants={'MEDIA_RE','SAMPLE_RE'}
    tree=ast.parse(args.reference.read_text())
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted
              or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
    baseline=ast.unparse(ast.Module(body=selected,type_ignores=[]))
    python_source='import re, time, json, sys, platform\n'+baseline+'\n'
    python_source+=f'fixtures={fixtures!r}\niterations={args.iterations}\nsamples={args.samples}\n'
    python_source+=r'''
results=[]
for label,data,name,total,minimum in fixtures:
    for _ in range(min(iterations,2000)):
        inner_entry(data,name,total,minimum)
    elapsed=[]
    checksum=0
    for sample in range(samples):
        checksum=0
        start=time.perf_counter_ns()
        for _ in range(iterations):
            found=inner_entry(data,name,total,minimum)
            if found:
                checksum+=found[1]+len(found[2])+len(found[0])
        elapsed.append(time.perf_counter_ns()-start)
    results.append({'label':label,'elapsed_ns':elapsed,'checksum':checksum & ((1<<64)-1)})
print(json.dumps({'python':sys.version.split()[0],'platform':platform.platform(),'results':results}))
'''
    py=subprocess.run(shlex.split(args.python_command),input=python_source,text=True,capture_output=True,check=True)
    baseline_results=json.loads(py.stdout)
    requests=[]
    for label,data,name,total,minimum in fixtures:
        requests.extend([f'B {args.iterations} {hx(data)} {hx(name)} {total} {minimum}']*args.samples)
    rust=subprocess.run(shlex.split(args.command),input='\n'.join(requests)+'\n',text=True,capture_output=True,check=True)
    lines=rust.stdout.splitlines()
    if len(lines)!=len(requests): raise AssertionError('Rust benchmark output count mismatch')
    print(f'Python baseline {baseline_results["python"]}; {baseline_results["platform"]}')
    print(f'Hot loops: {args.samples} samples x {args.iterations:,} calls per fixture; median ns/call')
    print('fixture             Python       Rust    speed ratio    time reduction')
    for index,entry in enumerate(baseline_results['results']):
        rust_elapsed=[]
        for line in lines[index*args.samples:(index+1)*args.samples]:
            elapsed,checksum=map(int,line.split())
            if checksum!=entry['checksum']: raise AssertionError(f'Benchmark result mismatch: {entry["label"]}')
            rust_elapsed.append(elapsed)
        py_ns=statistics.median(entry['elapsed_ns'])/args.iterations
        rs_ns=statistics.median(rust_elapsed)/args.iterations
        print(f'{entry["label"]:19s} {py_ns:10.1f} {rs_ns:10.1f} {py_ns/rs_ns:12.2f}x {(1-rs_ns/py_ns)*100:15.2f}%')
    print('Timings exclude subprocess/SSH/IPC and request parsing. Include loop/checksum and result allocation.')
    print('Python/Rust comparison only; this new functionality has no previous C++ implementation.')
    print('Use the same worker for --command and --python-command; shared-machine contention makes results provisional.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--emit-wrapper',type=Path)
    p.add_argument('--reference',type=Path,default=Path.home()/'git/submit_dupes_to_nzbget_hydra_connector/nzbget_dupe_proxy.py')
    p.add_argument('--command',help='Standalone identity CLI invocation, optionally ssh to an eligible worker')
    p.add_argument('--benchmark',action='store_true',help='Opt-in Python-reference/Rust function timing; default remains differential tests')
    p.add_argument('--iterations',type=int,default=100000,help='Benchmark calls per sample (default: 100000)')
    p.add_argument('--samples',type=int,default=5,help='Benchmark samples per fixture (default: 5)')
    p.add_argument('--python-command',default=f'{shlex.quote(sys.executable)} -',help='Python baseline invocation; use same remote worker as --command')
    args=p.parse_args()
    if args.emit_wrapper:
        args.emit_wrapper.write_text(WRAPPER); return
    if not args.command: p.error('--command is required unless emitting a wrapper')
    if args.benchmark:
        if args.iterations<=0 or args.samples<=0: p.error('benchmark iterations and samples must be positive')
        benchmark(args)
        return
    rows=cases(oracle(args.reference))
    proc=subprocess.run(shlex.split(args.command),input='\n'.join(r[0] for r in rows)+'\n',text=True,capture_output=True,check=True)
    outputs=proc.stdout.splitlines()
    if len(outputs)!=len(rows): raise AssertionError(f'{len(outputs)} outputs for {len(rows)} cases')
    failures=[]
    for n,((request,expected),actual) in enumerate(zip(rows,outputs)):
        if expected!=actual: failures.append(f'case {n}: {request}\nexpected={expected!r} actual={actual!r}')
    if failures: raise AssertionError('\n'.join(failures[:12])+f'\n{len(failures)} mismatches')
    print(f'PASS {len(rows)} offline differential cases (including 3 stricter malformed-header cases)')

if __name__=='__main__': main()
