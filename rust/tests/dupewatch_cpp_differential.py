#!/usr/bin/env python3
"""Source-extracted legacy Prepare parity and matched decision-caller timing.

Emit locally with --emit DIR, copy emitted source + this script to an approved
remote worker, then --build DIR and --run DIR under the shared build/exclusive
measurement lock respectively. No daemon/network/config operations occur.
The old source prefix is unchanged up to its search-stamp mutation; only queue,
options, time and scheduling are stubbed. Matched caller timing includes the
current PrepareNative prefix, real Rust normalization and its real watcher ABI;
postdecision mutation/save/transport is excluded from both callers. Kernel-only
timing is reported separately. Neither timing implies end-to-end speedup.
"""
import argparse
import pathlib
import subprocess
import re
import hashlib
import json

# Reachable default-branch parent; its decision prefix equals the original port baseline.
COMMIT = '2f0840a2e5d2528aca427061ad5d7778ac1e255f'
STUB = r'''
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>
static int64_t clockNow;
namespace Util { static int64_t CurrentTime() { return clockNow; } static bool EmptyStr(const char* value){return !value || !*value;} }
namespace Message { enum { mkInfo }; }
enum { dmScore, dmOther };
struct NzbInfo {
 enum EDeleteStatus { dsNone,dsManual,dsDupe,dsCopy,dsGood,dsFailure };
 enum { nkNzb,nkOther,dhNone,dhRedownloadAuto };
 int id=1,score=0,kind=nkNzb,mode=dmScore,hint=dhNone; EDeleteStatus status=dsNone;
 struct Parameters { bool fleet=false; void* Find(const char*){return fleet?(void*)this:nullptr;} } parameters;
 Parameters* GetParameters(){return &parameters;}
 bool success=false,deleting=false,post=false,donor=false; std::string key="Key";
 std::string name="The.Show.S01E02.2025.1080p.WEB-DL.H264-GRP";
 int GetId()const{return id;} int GetKind()const{return kind;} int GetDupeScore()const{return score;}
 EDeleteStatus GetDeleteStatus()const{return status;} bool IsDupeSuccess()const{return success;}
 bool GetDeleting()const{return deleting;} void* GetPostInfo()const{return post?(void*)this:nullptr;}
 int GetDupeMode()const{return mode;} int GetDupeHint()const{return hint;}
 const char* GetDupeKey()const{return key.c_str();} const char* GetName()const{return name.c_str();} template<class...T> void PrintMessage(T...)const{}
};
struct HistoryInfo { enum {hkNzb}; NzbInfo* item; int GetKind()const{return hkNzb;} NzbInfo* GetNzbInfo()const{return item;} };
struct Queue:std::vector<NzbInfo*> { NzbInfo* Find(int id){for(auto p:*this)if(p->id==id)return p;return nullptr;} };
static auto begin(Queue*q){return q->begin();} static auto end(Queue*q){return q->end();}
struct DownloadQueue { Queue queue;std::vector<HistoryInfo*> history; Queue* GetQueue(){return &queue;}
 std::vector<HistoryInfo*>& GetHistory(){return history;} };
struct Options { bool enabled=true,check=true; bool GetDupeSearch(){return enabled;} bool GetDupeCheck(){return check;}
 int GetDupeSearchDelay(){return 1;} } options;
static Options* g_Options=&options;
static NzbInfo* FindNzb(DownloadQueue*q,int id){if(auto p=q->queue.Find(id))return p;for(auto h:q->history)if(h->item->id==id)return h->item;return nullptr;}
struct RsBuf {char*data;size_t len,cap;};
extern "C" RsBuf nzbget_rs_releasename_normalize(const char*,size_t);
extern "C" void nzbget_rs_free(RsBuf);
namespace ReleaseName { static std::string Normalize(const std::string&name){auto b=nzbget_rs_releasename_normalize(name.data(),name.size());std::string out(b.data,b.len);nzbget_rs_free(b);return out;} }
static std::string EffectiveKey(NzbInfo* n);
static std::string LowerKey(std::string k){for(char&c:k)if(c>='A'&&c<='Z')c+=32;return k;}
struct DupeSearch {
 struct Job {};
 struct Searched {int score=0;int64_t time=0;std::string title;bool retryable=false;std::string rawName;}; using Stamp=Searched;std::set<int>m_rankPending; std::map<std::string,Stamp> m_searched;std::mutex m_mutex;
 bool scheduled=false;static std::string MakeDupeKey(const std::string&);
 static constexpr int BasePickScore=1000000,SearchWindowSec=21600,PostProcessRetrySec=30;
 bool IsDonor(NzbInfo*n){return n->donor;} void Schedule(int,int64_t){scheduled=true;}
 __attribute__((noinline)) bool Prepare(DownloadQueue*,int,Job&);
 __attribute__((noinline)) bool PrepareNative(DownloadQueue*,int,Job&);
};
extern "C" int rust_decide(uint32_t,int,int,int64_t,int64_t,int,int);
'''
DRIVER = r'''
struct Fixture {
 NzbInfo extra[4];HistoryInfo extraHistory[2]{{&extra[2]},{&extra[3]}};
 NzbInfo pick,peer; HistoryInfo historical{&pick}; DownloadQueue queue;DupeSearch search;DupeSearch::Job job;
 uint32_t flags=0; int score=0,higher=0,previousScore=0; int64_t now=0,previousTime=-1;
 void set(uint32_t f,int s,int h,int64_t n,int64_t pt,int ps) {
  flags=f;score=s;higher=h;now=n;previousTime=pt;previousScore=ps;
  options.enabled=f&1;options.check=f&2;pick.score=s;peer.id=2;peer.score=h;peer.key="key";
  pick.kind=(f&(1<<3))?NzbInfo::nkNzb:NzbInfo::nkOther;pick.success=f&(1<<5);pick.deleting=f&(1<<6);
  pick.status=(f&(1<<7))?NzbInfo::dsNone:(f&(1<<8))?NzbInfo::dsManual:(f&(1<<9))?NzbInfo::dsDupe:
   (f&(1<<10))?NzbInfo::dsCopy:(f&(1<<11))?NzbInfo::dsGood:NzbInfo::dsFailure;
  pick.post=f&(1<<12);pick.mode=(f&(1<<13))?dmScore:dmOther;pick.donor=f&(1<<14);
  pick.hint=(f&(1<<15))?NzbInfo::dhRedownloadAuto:NzbInfo::dhNone;
  queue.queue.clear();queue.history.clear();search.m_searched.clear();
  queue.queue.push_back(&peer);
  if(f&(1<<2)){if(f&(1<<4))queue.history.push_back(&historical);else queue.queue.push_back(&pick);}
  if(pt>=0)search.m_searched["key"]={ps,pt};
 }
 __attribute__((noinline)) int cpp(){clockNow=now;search.scheduled=false;return search.Prepare(&queue,1,job)?2:search.scheduled?1:0;}
 __attribute__((noinline)) int native(){clockNow=now;search.scheduled=false;return search.PrepareNative(&queue,1,job)?2:search.scheduled?1:0;}
 __attribute__((noinline)) int rust(){return rust_decide(flags,score,higher,now,previousTime,previousScore,0);}
};
int main(int argc,char**argv) {
 if(argc>1&&std::string(argv[1])=="--bench") {
  Fixture f;f.set(1|2|4|8|128|8192,3,0,100,-1,0);
  constexpr int loops=2000000;volatile uint64_t checksum=0;
  auto start=std::chrono::steady_clock::now();for(int i=0;i<loops;i++)checksum=checksum+f.cpp();
  auto middle=std::chrono::steady_clock::now();for(int i=0;i<loops;i++)checksum=checksum+f.rust();
  auto end=std::chrono::steady_clock::now();
  double cpp=std::chrono::duration<double,std::nano>(middle-start).count()/loops;
  double rust=std::chrono::duration<double,std::nano>(end-middle).count()/loops;
  printf("Policy-only timing: C++ %.3f ns/call; Rust %.3f ns/call; change %.2f%%; checksum %llu\n",cpp,rust,100*(rust/cpp-1),(unsigned long long)checksum);
  // Nonempty explicit client keys: existing EffectiveKey returns these verbatim.
  // Real normalization is retained inside the new caller and the previous title.
  for(int test=0;test<7;test++) {
    const int pickScore=test<2?0:1000000;
    f.set(1|2|4|8|128|8192,pickScore,pickScore-2000,(test==3||test==4)?21700:100,test>=2?99:-1,1000000);
    const std::string key="client:the.show.s01e02.2025.1080p.webdl.h264.grp";
    f.pick.key=key;f.peer.key=key;
    if(test==1 || test==2 || test==4 || test==6) {
      for(int i=0;i<4;i++){f.extra[i].id=i+3;f.extra[i].score=pickScore-1000;f.extra[i].key=i%2?"client:unrelated.release.2025.1080p.grp":key;}
      f.queue.queue.push_back(&f.extra[0]);f.queue.queue.push_back(&f.extra[1]);
      f.extra[2].status=NzbInfo::dsDupe;f.extra[3].status=NzbInfo::dsDupe;
      f.queue.history.push_back(&f.extraHistory[0]);f.queue.history.push_back(&f.extraHistory[1]);
    }
    f.search.m_searched.clear();
    if(test>=2)f.search.m_searched[LowerKey(key)]={1000000,99,ReleaseName::Normalize(f.pick.GetName()),false,test>=3?f.pick.name:""};
    std::string* coldCache=test==2?&f.search.m_searched[LowerKey(key)].rawName:nullptr;
    if(f.cpp()!=f.native()){puts("FAIL matched caller benchmark decisions");return 1;}
    constexpr int nativeLoops=200000;volatile uint64_t sum=0;
    auto a=std::chrono::steady_clock::now();for(int i=0;i<nativeLoops;i++){if(coldCache)coldCache->clear();sum=sum+f.cpp();}
    auto b=std::chrono::steady_clock::now();for(int i=0;i<nativeLoops;i++){if(coldCache)coldCache->clear();sum=sum+f.native();}
    auto c=std::chrono::steady_clock::now();
    double oldNs=std::chrono::duration<double,std::nano>(b-a).count()/nativeLoops;
    double newNs=std::chrono::duration<double,std::nano>(c-b).count()/nativeLoops;
    printf("Matched caller %s: queue=%zu history=%zu loops=%i C++ %.3f ns/call new %.3f ns/call change %+.2f%% checksum %llu\n",
      test==0?"cold-eligible-small":test==1?"cold-eligible-peers":test==2?"restart-cooldown-peers":test==3?"warm-eligible-small":test==4?"warm-eligible-peers":test==5?"warm-cooldown-small":"warm-cooldown-peers",f.queue.queue.size(),f.queue.history.size(),nativeLoops,oldNs,newNs,100*(newNs/oldNs-1),(unsigned long long)sum);
  }
  return 0;
 }
 Fixture f;uint64_t count=0;const int switches[]={0,1,2,3,4,5,6,12,13,14,15};
 const int deletion[]={0,128,256,512,1024,2048};
 const int scores[][2]={{0,0},{3,4},{1000001,1000001}};
 const int64_t times[][3]={{0,-1,0},{100,100,1000000},{21699,100,1000000},{21700,100,1000000},{99,100,1000000}};
 for(int mask=0;mask<2048;mask++)for(int d:deletion)for(auto&s:scores)for(auto&t:times){
  uint32_t flags=d;for(int i=0;i<11;i++)if(mask&(1<<i))flags|=1<<switches[i];
  f.set(flags,s[0],s[1],t[0],t[1],t[2]);int a=f.cpp(),b=f.rust(),native=f.native();count++;
  if(a!=native){printf("FAIL native caller fixture %llu old %i new %i\n",(unsigned long long)count,a,native);return 1;}
  if(a!=b){printf("FAIL fixture %llu flags %u C++ %i Rust %i\n",(unsigned long long)count,flags,a,b);return 1;}
 }
 const uint32_t live=1|2|4|8|128|8192;
 if(rust_decide(live|(1<<16),0,0,1,-1,0,0)!=0 || rust_decide(live,0,0,101,100,1000000,1)!=2){puts("FAIL proxy-only fixtures");return 1;}
 f.set(live,1000000,998000,100,-1,0);f.pick.parameters.fleet=true;
 if(f.cpp()!=2||f.native()!=0){puts("FAIL native managed-fleet intentional difference");return 1;}
 f.pick.parameters.fleet=false;
 f.set(live,1000000,998000,100,-1,0);f.extra[0].id=3;f.extra[0].score=1000001;f.extra[0].key="key";
 HistoryInfo highHistory{&f.extra[0]};f.queue.history.push_back(&highHistory);
 if(f.cpp()!=2||f.native()!=0){puts("FAIL native higher-history intentional difference");return 1;}
 f.set(live,1000000,998000,100,99,1000000);f.search.m_searched["key"].title="old.title";
 if(f.cpp()!=0||f.native()!=2){puts("FAIL native renamed-title intentional difference");return 1;}
 printf("PASS: %llu exact pre-port C++ kernel and current caller decision-prefix fixtures; 2 kernel and 3 caller proxy-only fixtures\n",(unsigned long long)count);
}
'''

def emit(directory, candidate):
    root = pathlib.Path(__file__).resolve().parents[2]
    source = subprocess.check_output(['git','show',f'{COMMIT}:daemon/dupesearch/DupeSearch.cpp'],cwd=root,text=True)
    start = source.index('bool DupeSearch::Prepare(')
    stop = source.index('\t\tm_searched[lowerKey] =',start)
    prefix = source[start:stop] + '\t}\n\treturn true;\n}\n'
    directory.mkdir(parents=True,exist_ok=True)
    current_revision=subprocess.check_output(['git','rev-parse',candidate],cwd=root,text=True).strip()
    current=subprocess.check_output(['git','show',f'{current_revision}:daemon/dupesearch/DupeSearch.cpp'],cwd=root,text=True)
    new_start=current.index('bool DupeSearch::PrepareNative(')
    new_stop=current.index('    int score = std::max(pick->GetDupeScore(), BasePickScore);',new_start)
    native_prefix=current[new_start:new_stop]+'    return true;\n#else\n return false;\n#endif\n}\n'
    header=subprocess.check_output(['git','show',f'{current_revision}:rust/include/nzbget_rs.h'],cwd=root,text=True)
    header_start=header.rfind('enum',0,header.index('rsDupeEnabled'))
    header_stop=header.index('NzbgetRsBuf nzbget_rs_dupe_queries',header_start)
    declarations=header[header_start:header_stop]
    declarations=declarations.replace('int nzbget_rs_dupe_watch(', 'extern "C" int nzbget_rs_dupe_watch(')
    lower_start=current.index('std::string LowerKey(')
    lower_stop=current.index('// the key a download',lower_start)
    exact_lower=current[lower_start:lower_stop]
    key_start=current.index('std::string EffectiveKey(')
    key_stop=current.index('\n}\n',key_start)+3
    make_start=current.index('std::string DupeSearch::MakeDupeKey(')
    make_stop=current.index('\n}\n',make_start)+3
    exact_keys=current[key_start:key_stop]+'\n'+current[make_start:make_stop]
    stub=re.sub(r'static std::string LowerKey\(std::string k\)\{[^\n]+\}',lambda _:exact_lower,STUB)
    (directory/'oracle.cpp').write_text('#define NZBGET_USE_RUST\n#include <cstdint>\n#include <cstddef>\n'+declarations+stub+exact_keys+prefix+native_prefix+DRIVER)
    (directory/'wrapper.rs').write_text('''mod bytes;mod releasename;mod dupewatch;
#[no_mangle] pub extern "C" fn rust_decide(flags:u32,score:i32,higher:i32,now:i64,previous_time:i64,previous_score:i32,changed:i32)->i32 {
 let previous=if previous_time<0 {None}else{Some(dupewatch::SearchStamp{score:previous_score,time:previous_time})};
 dupewatch::decide(flags,score,Some(higher),now,previous,changed!=0) as i32
}
''')
    ffi=subprocess.check_output(['git','show',f'{current_revision}:rust/src/ffi.rs'],cwd=root,text=True)
    def function(marker):
        at=ffi.index(marker);brace=ffi.index('{',at);level=1;end=brace+1
        while level:
            level+=(ffi[end]=='{')-(ffi[end]=='}');end+=1
        return ffi[at:end]
    buffer=ffi[ffi.index('#[repr(C)]\npub struct RsBuf'):ffi.index('unsafe fn input')]
    peer_start=ffi.index('#[repr(C)]\npub struct DupeWatchPeer')
    peer_end=ffi.index('/// Returns unique query strings',peer_start)
    exact_ffi=buffer+'\n'+function("unsafe fn arg<'a>")+'\n#[no_mangle]\n'+function('pub unsafe extern "C" fn nzbget_rs_free')+'\n#[no_mangle]\n'+function('pub unsafe extern "C" fn nzbget_rs_releasename_normalize')+'\n'+ffi[peer_start:peer_end]
    with (directory/'wrapper.rs').open('a') as out:out.write('\nuse std::ffi::{c_char,c_int};\n'+exact_ffi)
    for name in ['bytes.rs' ,'releasename.rs','dupewatch.rs']:
        (directory/name).write_bytes(subprocess.check_output(['git','show',f'{current_revision}:rust/src/{name}'],cwd=root))
    manifest={'baseline':COMMIT,'candidate':current_revision,'boundary':'decision prefix through watch FFI; excludes accepted-job mutation, save, transport','fixtures':'explicit nonempty keys; real normalization; 2/4 queued and 0/2 history; cold eligible pick score 0 with lower-score peers; restart cooldown pick score 1000000 with no runtime title cache; warm unchanged raw name and managed pick score 1000000; warm eligible uses an expired normal-score stamp, warm cooldown a recent normal-score stamp. Cold cooldown cache clear is identically included in both timers','files':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ['oracle.cpp','wrapper.rs','bytes.rs','releasename.rs','dupewatch.rs']}}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Emitted old prefix {COMMIT[:12]} and matched current caller/FFI {current_revision[:12]}; real Rust normalization; nonempty explicit keys')

def build(directory):
    subprocess.run([str(pathlib.Path.home()/'.cargo/bin/rustc'),'--edition=2021','--crate-type=staticlib','-O','-Awarnings',str(directory/'wrapper.rs'),'-o',str(directory/'policy.a')],check=True)
    for name,flags in [('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer']),('optimized',['-O3'])]:
        subprocess.run(['g++','-std=c++17',*flags,str(directory/'oracle.cpp'),str(directory/'policy.a'),'-lpthread','-ldl','-lm','-o',str(directory/name)],check=True)
    toolchain={'rustc':subprocess.check_output([str(pathlib.Path.home()/'.cargo/bin/rustc'),'--version'],text=True).strip(),'g++':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],'rust_flags':['--edition=2021','--crate-type=staticlib','-O'],'cpp_optimized_flags':['-std=c++17','-O3'],'cpp_sanitized_flags':['-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'],'sample_method':'5 fresh process samples; fixed C++ then Rust order; steady_clock; 2 million kernel calls and 200000 calls per adapter fixture; volatile checksums; real normalization inside candidate loop; externally held exclusive common benchmark lock'}
    (directory/'toolchain.json').write_text(json.dumps(toolchain,indent=2)+'\n')
    print('Built C++ ASan/UBSan and optimized C++/Rust policy harnesses')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',default='HEAD',help='Immutable commit or tree to extract (default HEAD, never working-tree files)')
    for mode in ['emit','build','run']:
        parser.add_argument('--'+mode,type=pathlib.Path)
    args=parser.parse_args()
    if args.emit: emit(args.emit.resolve(),args.candidate)
    if args.build: build(args.build.resolve())
    if args.run:
        directory=args.run.resolve()
        parity=subprocess.check_output([str(directory/'sanitized')],text=True,stderr=subprocess.STDOUT)
        (directory/'parity.log').write_text(parity);print(parity,end='')
        for index in range(1,6):
            sample=subprocess.check_output([str(directory/'optimized'),'--bench'],text=True,stderr=subprocess.STDOUT)
            (directory/f'sample-{index}.log').write_text(sample);print(sample,end='')
if __name__=='__main__':main()
