#include "nzbget.h"
#include "Util.h"
#include <limits>
namespace oldimpl {struct WebUtil {static CString JsonEncode(const char*);static CString Latin1ToUtf8(const char*);};}
namespace portimpl {struct WebUtil {static CString JsonEncode(const char*);static CString Latin1ToUtf8(const char*);};}
#include <algorithm>
#include <chrono>
static volatile unsigned long long g_sink;
template <class F> static double Best1(F f) { auto t0 = std::chrono::steady_clock::now(); f(); return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(); }
template <class Old, class New> static void Compare(const char* name, Old o, New n, int rounds, long ops)
{
 if (getenv("ONLY") && !strstr(name, getenv("ONLY"))) return;
 double cs[21], rs[21], bo=1e100, bn=1e100;
 if(rounds!=21)abort();
 for(int r=0;r<21;++r) {
  cs[r]=Best1(o)/ops*1e9; rs[r]=Best1(n)/ops*1e9;
  bo=std::min(bo,cs[r]);bn=std::min(bn,rs[r]);
 }
 printf("BENCH|%s|%.1f|%.1f|%.2f\n",name,bo,bn,bo/bn);
 for(int r=0;r<21;++r)printf("RAW|%s|%d|%.6f|%.6f\n",name,r,cs[r],rs[r]);
 fflush(stdout);
}
static std::string RepeatTo(const std::string& s, size_t n) { std::string r; while (r.size() < n) r += s; return r; }

static CString New(const char* s,bool latin) {
 return latin?portimpl::WebUtil::Latin1ToUtf8(s):portimpl::WebUtil::JsonEncode(s);
}
int main() {
 struct W{const char*name;std::string input;int reps;};
 W cases[]={
 {"JSON ASCII name, actual CString","Some.Show.S01E01.1080p.WEB-DL.DDP5.1.H.264-GROUP \"quoted\" / x",20000},
 {"JSON accented title, actual CString","Caf\xc3\xa9 \xc3\x9c" "ber \xe2\x80\x93 Fran\xc3\xa7" "ais d\xc3\xa9j\xc3\xa0 vu \xe6\x97\xa5\xe6\x9c\xac",20000},
 {"JSON4KiB, actual CString",RepeatTo("[INFO] Unpacking \"Show.S01E01.part01.rar\" (12/34)\r\n\tpath/to/file\\x: done\n",4096),2000},
 {"JSON64KiB, actual CString",RepeatTo("[INFO] Unpacking \"Show.S01E01.part01.rar\" (12/34)\r\n\tpath/to/file\\x: done\n",65536),200}};
 for(auto& c:cases){
  auto ref=oldimpl::WebUtil::JsonEncode(c.input.c_str());auto value=New(c.input.c_str(),false);
  if(strcmp(ref.Str(),value.Str())||ref.Length()!=value.Length())abort();
  Compare(c.name,[&]{for(int i=0;i<c.reps;++i)g_sink+=oldimpl::WebUtil::JsonEncode(c.input.c_str()).Str()[0];},[&]{for(int i=0;i<c.reps;++i)g_sink+=New(c.input.c_str(),false).Str()[0];},21,c.reps);
 }
 const char* lat="Caf\xe9 \xfc" "ber \xe7" "a va \xe0 la carte - Fran\xe7" "ais.nzb";
 auto ref=oldimpl::WebUtil::Latin1ToUtf8(lat);auto value=New(lat,true);if(strcmp(ref.Str(),value.Str())||ref.Length()!=value.Length())abort();
 Compare("Latin1 name, actual CString",[&]{for(int i=0;i<300000;++i)g_sink+=oldimpl::WebUtil::Latin1ToUtf8(lat).Str()[0];},[&]{for(int i=0;i<300000;++i)g_sink+=New(lat,true).Str()[0];},21,300000);
}
