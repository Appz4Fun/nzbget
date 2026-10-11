#!/usr/bin/env python3
"""Offline complete-caller benchmark; no NZBGet service is launched."""
import argparse,hashlib,io,json,os,re,shlex,subprocess,tempfile
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline",required=True)
parser.add_argument("--build-dir",default="build")
parser.add_argument("--output")
parser.add_argument("--cpu",type=int,default=2)
parser.add_argument("--trials",type=int,default=9)
parser.add_argument("--emit-only",action="store_true")
args=parser.parse_args()
root=Path(__file__).resolve().parents[3]
out=Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix="nzbget-latin1-caller-"))
out.mkdir(parents=True,exist_ok=True);(out/"logs").mkdir(exist_ok=True)
build_dir=root/args.build_dir
lock=Path(tempfile.gettempdir())/"nzbget-rust-benchmark.lock"
env=dict(os.environ,CARGO_BUILD_JOBS="3",CARGO_NET_OFFLINE=os.environ.get("CARGO_NET_OFFLINE","true"))
default=out/"default";default.mkdir(exist_ok=True)
archive=subprocess.check_output(["git","archive",args.baseline,"rust"],cwd=root)
subprocess.run(["tar","-x","-C",str(default)],input=archive,check=True)
count=0
def build(command,cwd=None,check=True):
    global count
    if args.emit_only:return
    with (out/"logs"/f"build-{count:02}.log").open("w") as log:
        subprocess.run(["chrt","-i","0","nice","-n","19","flock","-s",str(lock),*command],
                       cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    count+=1
build(["cargo","build","--release","--locked","-j3","--manifest-path",str(root/"rust/Cargo.toml")],cwd=root)
build(["cargo","build","--release","--locked","-j3","--manifest-path",str(default/"rust/Cargo.toml")],cwd=root)
old=subprocess.check_output(['git','show','78dcb938:daemon/util/Util.cpp'],cwd=root,text=True);current=(root/'daemon/util/Util.cpp').read_text()
def block(s,m):
 a=s.index(m);return s[a:s.index('\n}\n',a)+3]
helper=block(current,'namespace\n{\n\t// Caller-owned bounded encodings')
base='#include "nzbget.h"\n#include "Util.h"\n#include <limits>\n'
provider=base+'namespace oldimpl {\nstruct WebUtil {static CString JsonEncode(const char*);static CString Latin1ToUtf8(const char*);};\n'
provider+='__attribute__((section(".latinref")))\n'+block(old,'CString WebUtil::Latin1ToUtf8(const char* str)')
provider+='__attribute__((section(".jsonencoderef")))\n'+block(old,'CString WebUtil::JsonEncode(const char* raw)')+'}\n'
(out/'latin-ci-native-reference.cpp').write_text(provider)
default_cpp=subprocess.check_output(['git','show',args.baseline+':daemon/util/Util.cpp'],cwd=root,text=True)
for stage,body in [('before',default_cpp),('after',current)]:
 provider=base+'#include "nzbget_rs.h"\nnamespace portimpl {struct WebUtil {static CString JsonEncode(const char*);static CString Latin1ToUtf8(const char*);};\n'
 if stage=='after':provider+=helper
 provider+='__attribute__((section(".jsonport")))\n'+block(body,'CString WebUtil::JsonEncode(const char* raw)')
 provider+='__attribute__((section(".latinport")))\n'+block(body,'CString WebUtil::Latin1ToUtf8(const char* str)')+'}\n'
 (out/f'latin-whole-wrapper-{stage}.cpp').write_text(provider)
(out/'latin-whole-driver.cpp').write_text(Path(__file__).with_name('driver.cpp').read_text())
f=(build_dir/'CMakeFiles/libnzbget.dir/flags.make').read_text();get=lambda k:shlex.split(re.search(rf'^{k} = (.*)$',f,re.M).group(1))
flags=[*get('CXX_FLAGS'),*get('CXX_DEFINES'),*get('CXX_INCLUDES'),'-O3','-DNDEBUG']
build(['c++',*flags,'-fPIC','-c',str(root/'daemon/util/NString.cpp'),'-o',str(out/'latin-whole-NString.o')],cwd=build_dir,check=True)
libs=['-lcrypto','-lgcc_s','-lutil','-lrt','-lpthread','-lm','-ldl','-lc']
common=['-Wl,-Bsymbolic-functions']
build(['c++',*flags,'-shared','-fPIC',str(out/'latin-ci-native-reference.cpp'),str(out/'latin-whole-NString.o'),'-lcrypto',*common,'-Wl,--section-start=.latinref=0x2000030','-Wl,--section-start=.jsonencoderef=0x2002030','-o',str(out/'liblatin-whole-reference.so')],cwd=build_dir,check=True)
build(['c++',*flags,'-c',str(out/'latin-whole-driver.cpp'),'-o',str(out/'latin-whole-driver.o')],cwd=build_dir,check=True)
for stage in ['before','after']:
 archive=out/'default/rust/target/release/libnzbget_rs.a' if stage=='before' else root/'rust/target/release/libnzbget_rs.a'
 build(['c++',*flags,'-shared','-fPIC',str(out/f'latin-whole-wrapper-{stage}.cpp'),str(out/'latin-whole-NString.o'),str(archive),*common,'-Wl,--section-start=.latinport=0x2000030','-Wl,--section-start=.jsonport=0x2002030',*libs,'-o',str(out/f'liblatin-whole-{stage}.so')],cwd=build_dir,check=True)
 build(['c++',str(out/'latin-whole-driver.o'),'-L',str(out),'-llatin-whole-reference',f'-llatin-whole-{stage}','-Wl,-rpath,$ORIGIN',*libs,'-o',str(out/f'latin-whole-{stage}')],cwd=build_dir,check=True)
if not args.emit_only: print('Equivalent CPP caller providers compiled; identical driver object reused.')

if args.emit_only:
    print("Emitted caller sources; no builds or timings run.")
    raise SystemExit()
for trial in range(args.trials):
    for stage in ("before","after"):
        command=['date -u +%FT%TZ; ps -eo pid,comm | awk \'$2=="cargo" || $2=="rustc" || $2=="cc1plus" || $2=="cc1" {print}\'; exec taskset -c "$1" "$2"']
        with (out/"logs"/f"latin-whole-{trial}-{stage}.log").open("w") as log:
            subprocess.run(["chrt","-i","0","nice","-n","19","flock","-x",str(lock),"bash","-c",*command,"timer",str(args.cpu),str(out/f"latin-whole-{stage}")],
                           cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
runtime=["daemon/util/Util.cpp","rust/include/nzbget_rs.h","rust/src/ffi.rs","rust/src/text.rs","rust/tests/text_differential.py"]
patch=subprocess.check_output(["git","diff","--binary",args.baseline,"--",*runtime],cwd=root)
meta={"baseline":subprocess.check_output(["git","rev-parse",args.baseline],cwd=root,text=True).strip(),
      "runtime_patch_sha256":hashlib.sha256(patch).hexdigest(),
      "runtime_source_sha256":{f:sha(root/f) for f in runtime},
      "cpp_reference_commit":subprocess.check_output(["git","rev-parse","78dcb938"],cwd=root,text=True).strip(),
      "cpp_flags":get("CXX_FLAGS"),"cpp_defines":get("CXX_DEFINES"),
      "compiler":subprocess.check_output(["c++","--version"],text=True).splitlines()[0],
      "rustc":subprocess.check_output(["rustc","--version"],text=True).strip(),
      "cpu":args.cpu,"process_pairs":args.trials,"rounds":21,
      "binary_sha256":{f:sha(out/f) for f in ("latin-whole-driver.o","latin-whole-before","latin-whole-after","liblatin-whole-reference.so","liblatin-whole-before.so","liblatin-whole-after.so")},
      "topology":"Equivalent outer CPP DSO entrypoints; defined internal functions bind locally. Static production linking may differ.",
      "quiescence":"Common exclusive lock per process; compiler-process inventory at admission in every raw log."}
(out/"metadata.json").write_text(json.dumps(meta,indent=2)+"\n")
subprocess.run(["python3",str(Path(__file__).with_name("summarize.py")),str(out),"--trials",str(args.trials)],check=True)
print("Temporary artifact directory label:",out.name)
