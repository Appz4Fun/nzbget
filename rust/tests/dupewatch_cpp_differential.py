#!/usr/bin/env python3
"""Source-extracted legacy Prepare policy parity and policy-only timing.

Emit locally with --emit DIR, copy emitted source + this script to an approved
remote worker, then --build DIR and --run DIR under the shared build/exclusive
measurement lock respectively. No daemon/network/config operations occur.
The old source prefix is unchanged up to its search-stamp mutation; only queue,
options, time and scheduling are stubbed. Rust receives the already-made snapshot:
these timings exclude native adapter costs and do not imply end-to-end speedup.
"""
import argparse
import pathlib
import subprocess

# Reachable default-branch parent; its decision prefix equals the original port baseline.
COMMIT = '2f0840a2e5d2528aca427061ad5d7778ac1e255f'
STUB = r'''
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>
#include <vector>
static int64_t clockNow;
namespace Util { static int64_t CurrentTime() { return clockNow; } }
namespace Message { enum { mkInfo }; }
enum { dmScore, dmOther };
struct NzbInfo {
 enum EDeleteStatus { dsNone,dsManual,dsDupe,dsCopy,dsGood,dsFailure };
 enum { nkNzb,nkOther,dhNone,dhRedownloadAuto };
 int id=1,score=0,kind=nkNzb,mode=dmScore,hint=dhNone; EDeleteStatus status=dsNone;
 bool success=false,deleting=false,post=false,donor=false; std::string key="Key";
 int GetId()const{return id;} int GetKind()const{return kind;} int GetDupeScore()const{return score;}
 EDeleteStatus GetDeleteStatus()const{return status;} bool IsDupeSuccess()const{return success;}
 bool GetDeleting()const{return deleting;} void* GetPostInfo()const{return post?(void*)this:nullptr;}
 int GetDupeMode()const{return mode;} int GetDupeHint()const{return hint;}
 const char* GetName()const{return "name";} template<class...T> void PrintMessage(T...)const{}
};
struct HistoryInfo { enum {hkNzb}; NzbInfo* item; int GetKind()const{return hkNzb;} NzbInfo* GetNzbInfo()const{return item;} };
struct Queue:std::vector<NzbInfo*> { NzbInfo* Find(int id){for(auto p:*this)if(p->id==id)return p;return nullptr;} };
static auto begin(Queue*q){return q->begin();} static auto end(Queue*q){return q->end();}
struct DownloadQueue { Queue queue;std::vector<HistoryInfo*> history; Queue* GetQueue(){return &queue;}
 std::vector<HistoryInfo*>& GetHistory(){return history;} };
struct Options { bool enabled=true,check=true; bool GetDupeSearch(){return enabled;} bool GetDupeCheck(){return check;}
 int GetDupeSearchDelay(){return 1;} } options;
static Options* g_Options=&options;
static std::string EffectiveKey(NzbInfo* n){return n->key;}
static std::string LowerKey(std::string k){for(char&c:k)if(c>='A'&&c<='Z')c+=32;return k;}
struct DupeSearch {
 struct Job {};
 struct Stamp {int score;int64_t time;}; std::map<std::string,Stamp> m_searched;std::mutex m_mutex;
 bool scheduled=false;
 static constexpr int BasePickScore=1000000,SearchWindowSec=21600,PostProcessRetrySec=30;
 bool IsDonor(NzbInfo*n){return n->donor;} void Schedule(int,int64_t){scheduled=true;}
 __attribute__((noinline)) bool Prepare(DownloadQueue*,int,Job&);
};
extern "C" int rust_decide(uint32_t,int,int,int64_t,int64_t,int,int);
'''
DRIVER = r'''
struct Fixture {
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
  return 0;
 }
 Fixture f;uint64_t count=0;const int switches[]={0,1,2,3,4,5,6,12,13,14,15};
 const int deletion[]={0,128,256,512,1024,2048};
 const int scores[][2]={{0,0},{3,4},{1000001,1000001}};
 const int64_t times[][3]={{0,-1,0},{100,100,1000000},{21699,100,1000000},{21700,100,1000000},{99,100,1000000}};
 for(int mask=0;mask<2048;mask++)for(int d:deletion)for(auto&s:scores)for(auto&t:times){
  uint32_t flags=d;for(int i=0;i<11;i++)if(mask&(1<<i))flags|=1<<switches[i];
  f.set(flags,s[0],s[1],t[0],t[1],t[2]);int a=f.cpp(),b=f.rust();count++;
  if(a!=b){printf("FAIL fixture %llu flags %u C++ %i Rust %i\n",(unsigned long long)count,flags,a,b);return 1;}
 }
 const uint32_t live=1|2|4|8|128|8192;
 if(rust_decide(live|(1<<16),0,0,1,-1,0,0)!=0 || rust_decide(live,0,0,101,100,1000000,1)!=2){puts("FAIL proxy-only fixtures");return 1;}
 printf("PASS: %llu exact pre-port C++ decision-prefix fixtures; 2 separate proxy-only fixtures\n",(unsigned long long)count);
}
'''

def emit(directory):
    root = pathlib.Path(__file__).resolve().parents[2]
    source = subprocess.check_output(['git','show',f'{COMMIT}:daemon/dupesearch/DupeSearch.cpp'],cwd=root,text=True)
    start = source.index('bool DupeSearch::Prepare(')
    stop = source.index('\t\tm_searched[lowerKey] =',start)
    prefix = source[start:stop] + '\t}\n\treturn true;\n}\n'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'oracle.cpp').write_text(STUB+prefix+DRIVER)
    (directory/'wrapper.rs').write_text('''mod bytes;mod releasename;mod dupewatch;
#[no_mangle] pub extern "C" fn rust_decide(flags:u32,score:i32,higher:i32,now:i64,previous_time:i64,previous_score:i32,changed:i32)->i32 {
 let previous=if previous_time<0 {None}else{Some(dupewatch::SearchStamp{score:previous_score,time:previous_time})};
 dupewatch::decide(flags,score,Some(higher),now,previous,changed!=0) as i32
}
''')
    for name in ['bytes.rs','releasename.rs','dupewatch.rs']:
        (directory/name).write_bytes((root/'rust/src'/name).read_bytes())
    print(f'Emitted unchanged decision prefix from {COMMIT}; queue/options/time/scheduling stubs only')

def build(directory):
    subprocess.run([str(pathlib.Path.home()/'.cargo/bin/rustc'),'--edition=2021','--crate-type=staticlib','-O','-Awarnings',str(directory/'wrapper.rs'),'-o',str(directory/'policy.a')],check=True)
    for name,flags in [('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer']),('optimized',['-O3'])]:
        subprocess.run(['g++','-std=c++17',*flags,str(directory/'oracle.cpp'),str(directory/'policy.a'),'-lpthread','-ldl','-lm','-o',str(directory/name)],check=True)
    print('Built C++ ASan/UBSan and optimized C++/Rust policy harnesses')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for mode in ['emit','build','run']:
        parser.add_argument('--'+mode,type=pathlib.Path)
    args=parser.parse_args()
    if args.emit: emit(args.emit.resolve())
    if args.build: build(args.build.resolve())
    if args.run:
        directory=args.run.resolve()
        subprocess.run([str(directory/'sanitized')],check=True)
        for _ in range(5):subprocess.run([str(directory/'optimized'),'--bench'],check=True)
if __name__=='__main__':main()
