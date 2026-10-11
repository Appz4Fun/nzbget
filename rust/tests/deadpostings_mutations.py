#!/usr/bin/env python3
from pathlib import Path
import subprocess,fcntl,tempfile,os,json,argparse,contextlib
p=Path(__file__).resolve().parents[2]
env=os.environ.copy();env['PATH']=str(Path.home()/'.cargo/bin')+':'+env['PATH'];env['RUSTUP_TOOLCHAIN']='1.99.0'
parser=argparse.ArgumentParser();parser.add_argument('--artifacts',type=Path,required=True);args=parser.parse_args();artifacts=args.artifacts.resolve();artifacts.mkdir(parents=True,exist_ok=False)
source=(p/'rust/src/deadpostings.rs').read_text()
mutants={'skip-sort':('sketch.sort_unstable();',''), 'skip-dedup':('sketch.dedup();',''), 'accept-number-tail':('if !digit.is_ascii_digit() { return None; }','if !digit.is_ascii_digit() { break; }'), 'reject-saturated-time':('let magnitude = if overflow { limit }','let magnitude = if overflow { return None; }')}
results=[]
for name,(old,new) in mutants.items():
 assert old in source
 file=artifacts/('mutation_'+name.replace('-','_')+'.rs');file.write_text(source.replace(old,new))
 exe=file.with_suffix('')
 with contextlib.ExitStack() as stack:
  heavy=stack.enter_context((Path(tempfile.gettempdir())/'i7-heavy.lock').open('a'));fcntl.flock(heavy,fcntl.LOCK_EX)
  lock=stack.enter_context((Path(tempfile.gettempdir())/'nzbget-rust-benchmark.lock').open('a'));fcntl.flock(lock,fcntl.LOCK_SH)
  compile=subprocess.run(['chrt','-i','0','nice','-n','19','rustc','--edition=2021','--test',str(file),'-o',str(exe)],env=env,capture_output=True,text=True)
  assert not compile.returncode,compile.stderr
  test=subprocess.run([str(exe)],text=True,capture_output=True)
  fcntl.flock(lock,fcntl.LOCK_UN)
 (artifacts/('mutation-'+name+'.log')).write_text(test.stdout+test.stderr)
 assert test.returncode!=0,name+' survived'
 results.append({'mutation':name,'caught':True})
print(json.dumps(results))
