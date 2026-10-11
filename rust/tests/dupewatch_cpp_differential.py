#!/usr/bin/env python3
"""Source-extracted legacy Prepare parity and matched decision-caller timing.

Emit locally with --emit DIR, copy emitted source + this script to an approved
remote worker, then --build DIR and --run DIR under the shared build/exclusive
measurement lock respectively. No daemon/network/config operations occur.
The old source prefix is unchanged up to its search-stamp mutation; only queue,
options, time and scheduling are stubbed. Matched caller timing includes the
current PrepareNative prefix, real Rust normalization and its real watcher ABI;
postdecision mutation/save/transport and packed-payload proof are excluded.
The gating control is counterfactual C++ implementing the same new contract and
adapter algorithm, using the real pre-port C++ normalizer. Historical production
Prepare versus scalar Rust decision timings are non-equivalent context only.
Snapshot timings supply identical prebuilt snapshots to both policy backends.
"""
import argparse
import pathlib
import subprocess
import re
import hashlib
import json

# Reachable default-branch parent; its decision prefix equals the original port baseline.
COMMIT = '2f0840a2e5d2528aca427061ad5d7778ac1e255f'
NORMALIZER_REFERENCE = '9c36443d6d81070622b046242a9527afc766f417'
STUB = r'''
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cctype>
#include <clocale>
#include <cstring>
#include <limits>
#include <regex>
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
struct NzbParameter {std::string value;const char* GetValue()const{return value.c_str();}};
struct NzbInfo {
 enum EDeleteStatus { dsNone,dsManual,dsDupe,dsCopy,dsGood,dsFailure };
 enum { nkNzb,nkOther,dhNone,dhRedownloadAuto };
 int id=1,score=0,kind=nkNzb,mode=dmScore,hint=dhNone; EDeleteStatus status=dsNone;
 struct Parameters { bool fleet=false;NzbParameter fleetValue{"1"},owner;
  NzbParameter* Find(const char* name){if(!std::strcmp(name,"DupeFleet"))return fleet?&fleetValue:nullptr;
   if(!std::strcmp(name,"DupeSearchOwnedKey"))return owner.value.empty()?nullptr:&owner;return nullptr;} } parameters;
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
 bool scheduled=false;static std::string MakeDupeKey(const std::string&);static std::string MakeDupeKeyCpp(const std::string&);
 static constexpr const char* OwnedKeyParam="DupeSearchOwnedKey";
 static constexpr int BasePickScore=1000000,SearchWindowSec=21600,PostProcessRetrySec=30;
 bool IsDonor(NzbInfo*n){return n->donor;} void Schedule(int,int64_t){scheduled=true;}
 __attribute__((noinline)) bool Prepare(DownloadQueue*,int,Job&);
 __attribute__((noinline)) bool PrepareNative(DownloadQueue*,int,Job&);
 __attribute__((noinline)) bool PrepareCppControl(DownloadQueue*,int,Job&);
};
extern "C" int rust_decide(uint32_t,int,int,int64_t,int64_t,int,int);
'''
CPP_POLICY = r'''
// Independent counterfactual policy: legacy Prepare ordering plus the specified
// managed-fleet, historical-higher-score and changed-identity enhancements.
// Direct scan, no allocated peer copy. These are new-feature C++ semantics,
// not a claim that production's historical Prepare implemented them.
static bool SameKeyCpp(const char* a,size_t alen,const char* b,size_t blen) {
 if(!a)alen=0;if(!b)blen=0;if(alen!=blen)return false;
 for(size_t i=0;i<alen;i++) {unsigned char x=a[i],y=b[i];
  if(x>='A'&&x<='Z')x+=32;if(y>='A'&&y<='Z')y+=32;if(x!=y)return false;}
 return true;
}
static inline int CppWatchPolicy(const NzbgetRsDupeWatchPeer* pick,const NzbgetRsDupeWatchPeer* peers,
 size_t count,int64_t now,int previousScore,int64_t previousTime,int hasPrevious,int changed) {
 if(!pick)return 0;
 const uint32_t f=pick->flags;
 const uint32_t required=rsDupeEnabled|rsDupeCheck|rsDupePresent|rsDupeNzb;
 if((f&required)!=required)return 0;
 if(f&rsDupeHistory) {
  if(f&(rsDupeSuccess|rsDupeDeleteManual|rsDupeDeleteDupe|rsDupeDeleteCopy|rsDupeDeleteGood))return 0;
 } else {
  if((f&rsDupeDeleting)||!(f&rsDupeDeleteNone))return 0;
  if(f&rsDupePostProcess)return 1;
 }
 if(!(f&rsDupeScoreMode)||(f&(rsDupeDonor|rsDupeAutoRedownload|rsDupeManagedFleet)))return 0;
 // Peers only turn Search into Skip. Recent Skip is final in both backends.
 // Same overflow-safe unsigned elapsed test as the production Rust helper.
 if(hasPrevious&&!changed&&previousScore>=std::max(pick->score,1000000) &&
  (now<previousTime || uint64_t(now)-uint64_t(previousTime)<21600))return 0;
 if(peers)for(size_t i=0;i<count;i++) {
  const auto& p=peers[i];const uint32_t pf=p.flags;
  if(p.id==pick->id||p.score<=pick->score||(pf&(rsDupePresent|rsDupeNzb))!=(rsDupePresent|rsDupeNzb) ||
   (pf&(rsDupeDeleting|rsDupeDeleteManual|rsDupeDeleteCopy)) || (!(pf&rsDupeHistory)&&!(pf&rsDupeDeleteNone)))continue;
  if(SameKeyCpp(p.key,p.key_len,pick->key,pick->key_len))return 0;
 }
 return 2;
}
__attribute__((noinline,pure,nothrow)) int CppWatchMeasure(const NzbgetRsDupeWatchPeer* p,const NzbgetRsDupeWatchPeer* peers,
 size_t count,int64_t now,int score,int64_t time,int previous,int changed) {
 return CppWatchPolicy(p,peers,count,now,score,time,previous,changed);
}
'''
FAIR_DRIVER = r'''
static void SeedFair(Fixture& f,int test) {
 f.pick.name="The.Show.S01E02.2025.1080p.WEB-DL.H264-GRP";f.pick.parameters.owner.value.clear();
 const int score=test<2?0:1000000;
 f.set(1|2|4|8|128|8192,score,score-2000,(test==3||test==4)?21700:100,test>=2?99:-1,1000000);
 const std::string key="client:the.show.s01e02.2025.1080p.webdl.h264.grp";
 f.pick.key=key;f.peer.key=key;
 if(test==1||test==2||test==4||test==6) {
  for(int i=0;i<4;i++){f.extra[i].id=i+3;f.extra[i].score=score-1000;f.extra[i].key=i%2?"client:unrelated.release.2025.1080p.grp":key;}
  f.queue.queue.push_back(&f.extra[0]);f.queue.queue.push_back(&f.extra[1]);
  f.extra[2].status=NzbInfo::dsDupe;f.extra[3].status=NzbInfo::dsDupe;
  f.queue.history.push_back(&f.extraHistory[0]);f.queue.history.push_back(&f.extraHistory[1]);
 }
 f.search.m_searched.clear();
 if(test>=2)f.search.m_searched[LowerKey(key)]={1000000,99,ReleaseName::Normalize(f.pick.name),false,test>=3?f.pick.name:""};
 f.control.m_searched=f.search.m_searched;f.control.m_rankPending=f.search.m_rankPending;
}
static bool ExtraParity() {
 std::vector<std::string> names={"","The.Show.S01E02.2025.1080p.WEB-DL.H264-GRP","[01/17] {tag} Movie.2024.2160p.WEB-DL.DDP5.1.H.265-GRP.mkv",
 "sample.000","Show.S1E1-E3.1080p","MOVIE.2020.1080P-GRP.part01.rar","a H.265 x.264","[broken tag","{one}{two} Name.2025-GRP.mkv.nzb"};
 for(int i=0;i<600;i++)names.push_back("["+std::to_string(i)+"] The_Show-S"+std::to_string(i%20)+"E"+std::to_string(i%99)+".2024.1080p.WEB-DL.x265-GRP.vol"+std::to_string(i)+"+2.par2");
 names.push_back(std::string(700,'x'));names.push_back(std::string("A\0B.MKV",7));
 for(int i=1;i<256;i++){std::string n="The ";n.push_back((char)i);n+=" Show.2025-GRP.mkv";names.push_back(n);}
 for(const auto& n:names)if(cpp_reference::ReleaseName::Normalize(n)!=ReleaseName::Normalize(n)){puts("FAIL faithful CPP/Rust Normalize parity");return false;}
 for(int test=0;test<7;test++) {
  Fixture f;SeedFair(f,test);
  if(f.equivalent()!=f.native()){puts("FAIL equivalent controller normal-state fixture");return false;}
 }
 Fixture f;SeedFair(f,6);
 int caseNumber=0;auto assertSame=[&](int wanted){caseNumber++;int a=f.equivalent(),b=f.native();if(a!=b||a!=wanted){printf("FAIL cache/proxy case %i controller CPP %i Rust %i wanted %i\n",caseNumber,a,b,wanted);return false;}return true;};
 // Raw-name change invalidates an existing runtime cache, even with an explicit key.
 f.pick.name="Other.Show.S02E03.2024.720p.WEB.H264-GRP";if(!assertSame(2))return false;
 // Retired history/deleting fleet carriers cannot suppress a plain live pick.
 SeedFair(f,4);f.extra[2].parameters.fleet=true;f.extra[2].status=NzbInfo::dsManual;
 f.extra[2].key=f.pick.key;if(!assertSame(2))return false;
 f.extra[2].parameters.fleet=false;
 f.extra[0].parameters.fleet=true;f.extra[0].key=f.pick.key;
 if(!assertSame(0))return false;
 f.extra[0].deleting=true;if(!assertSame(2))return false;
 f.extra[0].deleting=false;f.extra[0].status=NzbInfo::dsManual;if(!assertSame(2))return false;
 f.extra[0].status=NzbInfo::dsNone;f.extra[0].parameters.fleet=false;
 // Historical higher scores suppress; deleting or manual/copy entries do not.
 f.extra[2].score=1000001;f.extra[2].status=NzbInfo::dsDupe;if(!assertSame(0))return false;
 f.extra[2].status=NzbInfo::dsManual;if(!assertSame(2))return false;
 f.extra[2].status=NzbInfo::dsCopy;if(!assertSame(2))return false;
 f.extra[2].status=NzbInfo::dsDupe;f.extra[2].deleting=true;if(!assertSame(2))return false;
 // Retarget only a live native-owned key; matching text alone is no ownership.
 SeedFair(f,4);
 const std::string oldName=f.pick.name,oldTitle=ReleaseName::Normalize(oldName),oldKey="dupes:"+oldTitle;
 f.pick.key=oldKey;f.peer.key=oldKey;f.peer.score=1000001;
 f.pick.name="Other.Show.S02E03.2024.720p.WEB.H264-GRP";
 f.search.m_searched.clear();f.search.m_searched[LowerKey(oldKey)]={1000000,99,oldTitle,false,oldName};
 f.control.m_searched=f.search.m_searched;
 if(!assertSame(0))return false;
 f.pick.parameters.owner.value="2:"+oldKey;if(!assertSame(0))return false;
 f.pick.parameters.owner.value="1:stale-key";if(!assertSame(0))return false;
 f.pick.parameters.owner.value="1:"+oldKey;if(!assertSame(2))return false;
 f.queue.queue.erase(std::remove(f.queue.queue.begin(),f.queue.queue.end(),&f.pick),f.queue.queue.end());
 f.queue.history.push_back(&f.historical);f.pick.status=NzbInfo::dsFailure;
 if(!assertSame(0))return false;
 // Raw byte keys and extreme times exercise the same watch contract directly.
 const uint32_t live=rsDupeEnabled|rsDupeCheck|rsDupePresent|rsDupeNzb|rsDupeDeleteNone|rsDupeScoreMode;
 const char bytes[]={char(255),'K'};NzbgetRsDupeWatchPeer pick{1,1000000,live,bytes,2};
 NzbgetRsDupeWatchPeer peer{2,1000001,live,bytes,2};
 for(int64_t now:{INT64_MIN,INT64_MAX})for(int64_t before:{INT64_MIN,INT64_MAX})
  for(int count:{0,1})for(int changed:{0,1}) {
   int a=CppWatchPolicy(&pick,&peer,count,now,1000000,before,1,changed);
   if(a!=cpp_opaque_watch(&pick,&peer,count,now,1000000,before,1,changed)){puts("FAIL opaque CPP parity");return false;}
   int b=nzbget_rs_dupe_watch(&pick,&peer,count,now,1000000,before,1,changed);
   if(a!=b){puts("FAIL watch byte/extreme-time parity");return false;}
  }
 uint64_t rng=0x8cf13a61d7;
 for(int i=0;i<20000;i++) {
  auto draw=[&](){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;int64_t value;std::memcpy(&value,&rng,8);return value;};
  const int64_t now=draw(),before=draw();const bool expected=((__int128)now-(__int128)before)<21600;
  const bool actual=now<before||uint64_t(now)-uint64_t(before)<21600;
  if(expected!=actual){puts("FAIL unsigned timestamp equivalence");return false;}
  const int a=CppWatchPolicy(&pick,nullptr,0,now,1000000,before,1,0);
  const int b=nzbget_rs_dupe_watch(&pick,nullptr,0,now,1000000,before,1,0);
  const int c=cpp_opaque_watch(&pick,nullptr,0,now,1000000,before,1,0);
  if(a!=b||a!=c||a!=(expected?0:2)){puts("FAIL random-i64 stamp policy parity");return false;}
 }
 printf("PASS: %zu faithful normalization inputs; 7 benchmark states; raw-name/fleet/history/byte/time contracts; 20000 random i64 timestamp pairs\n",names.size());
 return true;
}
int OpaqueBench() {
 const uint32_t live=rsDupeEnabled|rsDupeCheck|rsDupePresent|rsDupeNzb|rsDupeDeleteNone|rsDupeScoreMode;
 const char key[]="client:key";NzbgetRsDupeWatchPeer pick{1,1000000,live,key,sizeof(key)-1};
 NzbgetRsDupeWatchPeer peers[3]={{2,999999,live,key,sizeof(key)-1},{3,1000001,live,"other",5},{4,999999,live|rsDupeHistory,key,sizeof(key)-1}};
 for(int test=0;test<3;test++) {
  const int count=test?3:0;const int previous=test==2;
  if(cpp_opaque_watch(&pick,peers,count,100,1000000,99,previous,0)!=nzbget_rs_dupe_watch(&pick,peers,count,100,1000000,99,previous,0)){puts("FAIL snapshot equality");return 1;}
  constexpr int loops=2000000;volatile uint64_t sum=0;
  auto a=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){asm volatile(""::"m"(pick),"m"(peers):"memory");sum=sum+cpp_opaque_watch(&pick,peers,count,100,1000000,99,previous,0);}
  auto b=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){asm volatile(""::"m"(pick),"m"(peers):"memory");sum=sum+nzbget_rs_dupe_watch(&pick,peers,count,100,1000000,99,previous,0);}
  auto c=std::chrono::steady_clock::now();
  double oldNs=std::chrono::duration<double,std::nano>(b-a).count()/loops,newNs=std::chrono::duration<double,std::nano>(c-b).count()/loops;
  printf("Opaque-equivalent prebuilt-snapshot policy %s: peers=%i C++ %.3f ns/call Rust %.3f ns/call change %+.2f%% checksum %llu\n",test==0?"eligible-empty":test==1?"eligible-peers":"cooldown-peers",count,oldNs,newNs,100*(newNs/oldNs-1),(unsigned long long)sum);
 }
 return 0;
}
int FairBench() {
 if(!ExtraParity())return 1;
 const uint32_t live=rsDupeEnabled|rsDupeCheck|rsDupePresent|rsDupeNzb|rsDupeDeleteNone|rsDupeScoreMode;
 const char key[]="client:key";NzbgetRsDupeWatchPeer pick{1,1000000,live,key,sizeof(key)-1};
 NzbgetRsDupeWatchPeer peers[3]={{2,999999,live,key,sizeof(key)-1},{3,1000001,live,"other",5},{4,999999,live|rsDupeHistory,key,sizeof(key)-1}};
 for(int test=0;test<3;test++) {
  const int count=test?3:0;const int previous=test==2;
  if(CppWatchPolicy(&pick,peers,count,100,1000000,99,previous,0)!=nzbget_rs_dupe_watch(&pick,peers,count,100,1000000,99,previous,0)){puts("FAIL snapshot equality");return 1;}
  constexpr int loops=2000000;volatile uint64_t sum=0;
  auto a=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){asm volatile(""::"m"(pick),"m"(peers):"memory");sum=sum+CppWatchPolicy(&pick,peers,count,100,1000000,99,previous,0);}
  auto b=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){asm volatile(""::"m"(pick),"m"(peers):"memory");sum=sum+nzbget_rs_dupe_watch(&pick,peers,count,100,1000000,99,previous,0);}
  auto c=std::chrono::steady_clock::now();
  double oldNs=std::chrono::duration<double,std::nano>(b-a).count()/loops,newNs=std::chrono::duration<double,std::nano>(c-b).count()/loops;
  printf("Equivalent prebuilt-snapshot policy %s: peers=%i C++ %.3f ns/call Rust %.3f ns/call change %+.2f%% checksum %llu\n",test==0?"eligible-empty":test==1?"eligible-peers":"cooldown-peers",count,oldNs,newNs,100*(newNs/oldNs-1),(unsigned long long)sum);
 }
 for(int test=0;test<7;test++) {
  Fixture f;SeedFair(f,test);
  const auto key=LowerKey(f.pick.key);
  std::string* cppCold=test==2?&f.control.m_searched[key].rawName:nullptr;
  std::string* rustCold=test==2?&f.search.m_searched[key].rawName:nullptr;
  // Both controllers are warmed once for regex/allocator initialization only.
  // Cold restart state is identically reset before every measured call.
  if(f.equivalent()!=f.native()){puts("FAIL fair timed-state decisions");return 1;}
  const int loops=test<3?10000:200000;volatile uint64_t sum=0;
  auto a=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){if(cppCold)cppCold->clear();sum=sum+f.equivalent();}
  auto b=std::chrono::steady_clock::now();
  for(int i=0;i<loops;i++){if(rustCold)rustCold->clear();sum=sum+f.native();}
  auto c=std::chrono::steady_clock::now();
  double cppNs=std::chrono::duration<double,std::nano>(b-a).count()/loops,rustNs=std::chrono::duration<double,std::nano>(c-b).count()/loops;
  printf("Counterfactual same-contract controller %s: queue=%zu history=%zu loops=%i C++ %.3f ns/call Rust %.3f ns/call change %+.2f%% checksum %llu\n",
   test==0?"cold-eligible-small":test==1?"cold-eligible-peers":test==2?"restart-cooldown-peers":test==3?"warm-eligible-small":test==4?"warm-eligible-peers":test==5?"warm-cooldown-small":"warm-cooldown-peers",f.queue.queue.size(),f.queue.history.size(),loops,cppNs,rustNs,100*(rustNs/cppNs-1),(unsigned long long)sum);
 }
 return 0;
}
'''

DRIVER = r'''
int FairBench();int OpaqueBench();
extern "C" __attribute__((pure,nothrow)) int cpp_opaque_watch(const NzbgetRsDupeWatchPeer*,const NzbgetRsDupeWatchPeer*,size_t,int64_t,int,int64_t,int,int);
struct Fixture {
 NzbInfo extra[4];HistoryInfo extraHistory[2]{{&extra[2]},{&extra[3]}};
 NzbInfo pick,peer; HistoryInfo historical{&pick}; DownloadQueue queue;DupeSearch search,control;DupeSearch::Job job;
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
  control.m_searched=search.m_searched;control.m_rankPending=search.m_rankPending;
 }
 __attribute__((noinline)) int cpp(){clockNow=now;search.scheduled=false;return search.Prepare(&queue,1,job)?2:search.scheduled?1:0;}
 __attribute__((noinline)) int equivalent(){clockNow=now;control.scheduled=false;return control.PrepareCppControl(&queue,1,job)?2:control.scheduled?1:0;}
 __attribute__((noinline)) int native(){clockNow=now;search.scheduled=false;return search.PrepareNative(&queue,1,job)?2:search.scheduled?1:0;}
 __attribute__((noinline)) int rust(){return rust_decide(flags,score,higher,now,previousTime,previousScore,0);}
};
''' + FAIR_DRIVER + r'''
int main(int argc,char**argv) {
 std::setlocale(LC_CTYPE,"");
 if(argc>1&&std::string(argv[1])=="--bench") return FairBench();
 if(argc>1&&std::string(argv[1])=="--bench-opaque")return OpaqueBench();
 if(argc>1&&std::string(argv[1])=="--bench-legacy") {
  Fixture f;f.set(1|2|4|8|128|8192,3,0,100,-1,0);
  constexpr int loops=2000000;volatile uint64_t checksum=0;
  auto start=std::chrono::steady_clock::now();for(int i=0;i<loops;i++)checksum=checksum+f.cpp();
  auto middle=std::chrono::steady_clock::now();for(int i=0;i<loops;i++)checksum=checksum+f.rust();
  auto end=std::chrono::steady_clock::now();
  double cpp=std::chrono::duration<double,std::nano>(middle-start).count()/loops;
  double rust=std::chrono::duration<double,std::nano>(end-middle).count()/loops;
  printf("Historical NON-EQUIVALENT context/kernel timing: C++ %.3f ns/call; Rust %.3f ns/call; change %.2f%%; checksum %llu\n",cpp,rust,100*(rust/cpp-1),(unsigned long long)checksum);
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
  f.set(flags,s[0],s[1],t[0],t[1],t[2]);int a=f.cpp(),b=f.rust(),native=f.native(),equivalent=f.equivalent();count++;
  NzbgetRsDupeWatchPeer purePick{1,s[0],flags,"key",3},purePeer{2,s[1],uint32_t(rsDupePresent|rsDupeNzb|rsDupeDeleteNone),"key",3};
  int opaque=cpp_opaque_watch(&purePick,&purePeer,1,t[0],t[2],t[1],t[1]>=0,0);
  if(opaque!=b){printf("FAIL opaque CPP legacy fixture %llu CPP %i Rust %i\n",(unsigned long long)count,opaque,b);return 1;}
  if(equivalent!=native){printf("FAIL equivalent CPP controller fixture %llu CPP %i Rust %i\n",(unsigned long long)count,equivalent,native);return 1;}
  if(a!=native){printf("FAIL native caller fixture %llu old %i new %i\n",(unsigned long long)count,a,native);return 1;}
  if(a!=b){printf("FAIL fixture %llu flags %u C++ %i Rust %i\n",(unsigned long long)count,flags,a,b);return 1;}
 }
 const uint32_t live=1|2|4|8|128|8192;
 if(rust_decide(live|(1<<16),0,0,1,-1,0,0)!=0 || rust_decide(live,0,0,101,100,1000000,1)!=2){puts("FAIL proxy-only fixtures");return 1;}
 f.set(live,1000000,998000,100,-1,0);f.pick.parameters.fleet=true;
 if(f.cpp()!=2||f.native()!=0||f.equivalent()!=0){puts("FAIL native managed-fleet intentional difference");return 1;}
 f.pick.parameters.fleet=false;
 f.set(live,1000000,998000,100,-1,0);f.extra[0].id=3;f.extra[0].score=1000001;f.extra[0].key="key";
 HistoryInfo highHistory{&f.extra[0]};f.queue.history.push_back(&highHistory);
 if(f.cpp()!=2||f.native()!=0||f.equivalent()!=0){puts("FAIL native higher-history intentional difference");return 1;}
 f.set(live,1000000,998000,100,99,1000000);f.search.m_searched["key"].title="old.title";
 f.control.m_searched=f.search.m_searched;
 if(f.cpp()!=0||f.native()!=2||f.equivalent()!=2){puts("FAIL native renamed-title intentional difference");return 1;}
 if(!ExtraParity())return 1;
 printf("PASS: %llu legacy fixtures across production CPP, Rust scalar, Rust controller and equivalent CPP controller; proxy/cache/normalization checks pass\n",(unsigned long long)count);
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
    declarations='extern "C" {\n'+declarations+'\n}\n'
    lower_start=current.index('std::string LowerKey(')
    lower_stop=current.index('// the key a download',lower_start)
    exact_lower=current[lower_start:lower_stop]
    key_start=current.index('std::string EffectiveKey(')
    key_stop=current.index('\n}\n',key_start)+3
    make_start=current.index('std::string DupeSearch::MakeDupeKey(')
    make_stop=current.index('\n}\n',make_start)+3
    exact_keys=current[key_start:key_stop]+'\n'+current[make_start:make_stop]
    stub=re.sub(r'static std::string LowerKey\(std::string k\)\{[^\n]+\}',lambda _:exact_lower,STUB)
    cpp_source=subprocess.check_output(['git','show',f'{NORMALIZER_REFERENCE}:daemon/dupesearch/ReleaseName.cpp'],cwd=root,text=True)
    cpp_header=subprocess.check_output(['git','show',f'{NORMALIZER_REFERENCE}:daemon/dupesearch/ReleaseName.h'],cwd=root,text=True)
    cpp_util=subprocess.check_output(['git','show',f'{NORMALIZER_REFERENCE}:daemon/dupesearch/DupeUtil.h'],cwd=root,text=True)
    # Archive the exact reference bytes, not only the extracted functions.
    for name,value in [('cpp_reference_source.cpp',cpp_source),('cpp_reference_header.h',cpp_header),('cpp_reference_util.h',cpp_util)]:
        (directory/name).write_text(value)
    cpp_body=cpp_source[cpp_source.index('namespace\n{\n\nbool IsDigits'):cpp_source.index('namespace\n{\n\nbool IsEpisodeToken')]
    cpp_decl=cpp_header[cpp_header.index('class ReleaseName'):cpp_header.index('#endif')]
    helper_start=cpp_util.index('\tinline std::string Lower(')
    helper_stop=cpp_util.index('\tinline std::string ReadAll(',helper_start)
    cpp_normalizer='namespace cpp_reference {\n'+cpp_util[helper_start:helper_stop]+cpp_decl+cpp_body+'\n}\n'
    cpp_keys=exact_keys.replace('EffectiveKey(', 'EffectiveKeyCpp(').replace('MakeDupeKey(', 'MakeDupeKeyCpp(').replace('ReleaseName::Normalize', 'cpp_reference::ReleaseName::Normalize')
    cpp_prefix=native_prefix.replace('DupeSearch::PrepareNative(', 'DupeSearch::PrepareCppControl(').replace('EffectiveKey(', 'EffectiveKeyCpp(').replace('ReleaseName::Normalize', 'cpp_reference::ReleaseName::Normalize').replace('nzbget_rs_dupe_watch(', 'CppWatchPolicy(')
    (directory/'cpp_normalizer_extracted.cpp').write_text(cpp_normalizer)
    (directory/'cpp_policy_control.cpp').write_text(CPP_POLICY)
    opaque_policy=CPP_POLICY[:CPP_POLICY.index('__attribute__((noinline,pure,nothrow)) int CppWatchMeasure')].replace('static inline int CppWatchPolicy(', 'extern "C" __attribute__((pure,nothrow)) int cpp_opaque_watch(')
    (directory/'cpp_opaque_watch.cpp').write_text('#include <algorithm>\n#include <cstdint>\n#include <cstddef>\n'+declarations+opaque_policy)
    (directory/'oracle.cpp').write_text('#define NZBGET_USE_RUST\n#include <cstdint>\n#include <cstddef>\n'+declarations+stub+cpp_normalizer+CPP_POLICY+exact_keys+cpp_keys+prefix+native_prefix+cpp_prefix+DRIVER)
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
    manifest={'baseline':COMMIT,'candidate':current_revision,'normalizer_reference':NORMALIZER_REFERENCE,'control':'counterfactual same-contract C++ controller, identical adapter/cache/prefilter, allocation-free independent source-derived policy, faithful pre-port C++ Normalize','boundary':'decision preparation through backend watch; excludes accepted-job mutation, save, transport, packed-payload proof','fixtures':'explicit nonempty keys; real normalization; 2/4 queued and 0/2 history; cold eligible pick score 0 with lower-score peers; restart cooldown pick score 1000000 with no runtime title cache; warm unchanged raw name and managed pick score 1000000; warm eligible uses an expired normal-score stamp, warm cooldown a recent normal-score stamp. Cold cooldown cache clear is identically included in both timers','files':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ['oracle.cpp','wrapper.rs','bytes.rs','releasename.rs','dupewatch.rs','cpp_normalizer_extracted.cpp','cpp_policy_control.cpp','cpp_reference_source.cpp','cpp_reference_header.h','cpp_reference_util.h','cpp_opaque_watch.cpp']}}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Emitted old prefix {COMMIT[:12]} and matched current caller/FFI {current_revision[:12]}; real Rust normalization; nonempty explicit keys')

def build(directory):
    subprocess.run([str(pathlib.Path.home()/'.cargo/bin/rustc'),'--edition=2021','--crate-type=staticlib','-O','-Awarnings',str(directory/'wrapper.rs'),'-o',str(directory/'policy.a')],check=True)
    for name,flags in [('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer']),('optimized',['-O3'])]:
        subprocess.run(['g++','-std=c++17',*flags,str(directory/'oracle.cpp'),str(directory/'cpp_opaque_watch.cpp'),str(directory/'policy.a'),'-lpthread','-ldl','-lm','-o',str(directory/name)],check=True)
    toolchain={'rustc':subprocess.check_output([str(pathlib.Path.home()/'.cargo/bin/rustc'),'--version'],text=True).strip(),'g++':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],'rust_flags':['--edition=2021','--crate-type=staticlib','-O'],'cpp_optimized_flags':['-std=c++17','-O3'],'cpp_sanitized_flags':['-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'],'sample_method':'5 fresh process samples; fixed C++ then Rust order; steady_clock; 2 million calls per identical prebuilt snapshot case; 10000 cold controller or 200000 warm controller calls; volatile checksums; faithful respective normalization inside cold loops; identical cache/prefilter and state; externally held exclusive common benchmark lock released between samples; historical non-equivalent metrics excluded from gating'}
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
