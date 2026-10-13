/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2026 Denis <denis@nzbget.com>
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

// Exact historical state/pin bodies with fixture getters; correctness only.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <set>
#include <string>
#include <vector>
using int64=int64_t;
struct CString {
 std::string value;
 CString(const char* text=nullptr):value(text?text:"") {}
 operator const char*() const {return value.c_str();}
};
struct ArticleInfo {
 int round=0, lead=0, next=0, count=0;
 int64 offset=-1,end=-1;
 std::vector<CString> sources;
 std::vector<int> owners;
 int GetDupeFallbackRound(){return round;}
 int GetDupeLeadSnapshot(){return lead;}
 int GetDupeNextLead(){return next;}
 int GetDupeDonorCount(){return count;}
 void SetDupeLeadSnapshot(int v){lead=v;}
 void SetDupeNextLead(int v){next=v;}
 void SetDupeDonorCount(int v){count=v;}
 std::vector<CString>* GetDupeSources(){return &sources;}
 std::vector<int>* GetDupeSourceDonors(){return &owners;}
};
struct FileInfo {
 int donor=0,failures=0,switches=0;
 int GetDupeLeadDonorId(){return donor;}
 int GetDupeLeadFailures(){return failures;}
 int GetDupeLeadSwitches(){return switches;}
 void SetDupeLeadDonorId(int v){donor=v;}
 void SetDupeLeadFailures(int v){failures=v;}
 void SetDupeLeadSwitches(int v){switches=v;}
};
class DupeArticleFallback {
public:
 static constexpr int LeadDemoteThreshold=3;
 static bool RegisterLeadFailure(FileInfo*,ArticleInfo*);
 static void RegisterLeadSuccess(FileInfo*,ArticleInfo*);
 static void FinishPin(FileInfo*,ArticleInfo*,const std::vector<CString>&,const std::vector<int>&,bool,const char*);
 static std::vector<CString> OrderSources(const std::vector<CString>&,bool,const char*);
 static int64 ExpectedSegmentOffset(FileInfo*,ArticleInfo* a){return a->offset;}
 static int64 ExpectedSegmentEnd(FileInfo*,ArticleInfo* a){return a->end;}
};
struct State {int32_t donor,failures,switches;};
struct Pin {int32_t donor,next,count;};
struct CandidateInput {const uint8_t* bytes;size_t len;int32_t donor;};
extern "C" int32_t test_lead_failure(State*,const Pin*,int32_t);
extern "C" void test_lead_success(State*,const Pin*,int32_t,int64_t,int64_t);
extern "C" size_t test_pin_sources(State*,const CandidateInput*,size_t,int32_t,const uint8_t*,size_t,uint8_t*,size_t);
bool DupeArticleFallback::RegisterLeadFailure(FileInfo* fileInfo, ArticleInfo* articleInfo)
{
	// only a failed fetch of the pinned lead donor counts, and only while that
	// donor is still the file's lead: late failures of an already demoted lead
	// reported by in-flight articles must not cascade-demote donors that were
	// never tried, and a part whose slot 0 belongs to ANOTHER donor (the lead
	// does not carry that part) must not charge the lead's streak
	if (articleInfo->GetDupeFallbackRound() != 1 ||
		articleInfo->GetDupeLeadSnapshot() == 0 ||
		articleInfo->GetDupeLeadSnapshot() != fileInfo->GetDupeLeadDonorId())
	{
		return false;
	}

	int failures = fileInfo->GetDupeLeadFailures() + 1;
	fileInfo->SetDupeLeadFailures(failures);

	// rotate only while another donor exists and the rotation budget lasts:
	// once every duplicate has led without a single lead success, the
	// duplicates are equally holed and further rotation (and its log line,
	// once per switch) would be pure noise
	if (failures >= LeadDemoteThreshold && articleInfo->GetDupeNextLead() != 0 &&
		fileInfo->GetDupeLeadSwitches() < articleInfo->GetDupeDonorCount())
	{
		fileInfo->SetDupeLeadDonorId(articleInfo->GetDupeNextLead());
		fileInfo->SetDupeLeadFailures(0);
		fileInfo->SetDupeLeadSwitches(fileInfo->GetDupeLeadSwitches() + 1);
		return true;
	}
	return false;
}

void DupeArticleFallback::RegisterLeadSuccess(FileInfo* fileInfo, ArticleInfo* articleInfo)
{
	if (articleInfo->GetDupeFallbackRound() != 1 ||
		articleInfo->GetDupeLeadSnapshot() == 0 ||
		articleInfo->GetDupeLeadSnapshot() != fileInfo->GetDupeLeadDonorId())
	{
		return;
	}

	fileInfo->SetDupeLeadFailures(0);

	// re-arm the rotation budget only when the success is verifiable: with
	// unfinished neighbours the alignment check passes vacuously, the article
	// may be demoted again later (DemoteMisalignedDupeNeighbors), and its
	// bogus success - although the streak reset is recharged at demotion -
	// must not bypass the rotation bound
	if (ExpectedSegmentOffset(fileInfo, articleInfo) != -1 &&
		ExpectedSegmentEnd(fileInfo, articleInfo) != -1)
	{
		fileInfo->SetDupeLeadSwitches(0);
	}
}

void DupeArticleFallback::FinishPin(FileInfo* fileInfo, ArticleInfo* articleInfo,
	const std::vector<CString>& candidates, const std::vector<int>& contributors,
	bool cutover, const char* primaryMessageId)
{
	// the distinct donors behind the candidates, in candidate order: [0] is
	// the donor whose article the pinned slot 0 fetches, [1] the donor a
	// demotion would rotate the lead to
	std::vector<int> donorIds;
	for (int donorId : contributors)
	{
		if (std::find(donorIds.begin(), donorIds.end(), donorId) == donorIds.end())
		{
			donorIds.push_back(donorId);
		}
	}

	articleInfo->SetDupeLeadSnapshot(donorIds.empty() ? 0 : donorIds[0]);
	articleInfo->SetDupeNextLead(donorIds.size() > 1 ? donorIds[1] : 0);
	articleInfo->SetDupeDonorCount((int)donorIds.size());

	// the file's lead is decided by its first pinned article (the donors were
	// iterated in score order then, so this is the top-scored donor offering
	// that part); until rotated it stays this donor by nzb-id
	if (fileInfo->GetDupeLeadDonorId() == 0 && !donorIds.empty())
	{
		fileInfo->SetDupeLeadDonorId(donorIds[0]);
	}

	*articleInfo->GetDupeSources() = OrderSources(candidates, cutover, primaryMessageId);
	// OrderSources keeps the candidates' order (the primary goes last)
	*articleInfo->GetDupeSourceDonors() = contributors;
}

std::vector<CString> DupeArticleFallback::OrderSources(const std::vector<CString>& donorCandidates,
	bool cutover, const char* primaryMessageId)
{
	std::vector<CString> sources;

	if (!cutover || donorCandidates.empty())
	{
		// reactive: the primary was already tried via the normal path; offer
		// the donor candidates only (empty if none, so the article just fails)
		for (const CString& candidate : donorCandidates)
		{
			sources.emplace_back((const char*)candidate);
		}
		return sources;
	}

	// cut over: lead with the top donor, then the remaining donors, then the
	// primary as the final fallback. The file cut over precisely because the
	// primary is missing many articles, so on a lead-donor miss the other
	// duplicates are better bets than paying a (likely failing) full server
	// sweep on the primary; the primary still backstops parts every duplicate
	// misses. NOTE: proactive fetches must never count as "recovered"
	// regardless of round (see QueueCoordinator::ArticleCompleted) - with the
	// primary last, no donor round proves the primary was missing the part
	sources.reserve(donorCandidates.size() + 1);
	for (const CString& candidate : donorCandidates)
	{
		sources.emplace_back((const char*)candidate);
	}
	sources.emplace_back(primaryMessageId);
	return sources;
}
extern "C" int64_t test_next_source(const CandidateInput*,size_t,int32_t,const uint8_t*,size_t,int32_t,const int32_t*,size_t,int32_t*);
static int original_next_source(ArticleInfo& article,int round,std::set<int>& blocked) {
 auto& sources=article.sources;auto& sourceDonors=article.owners;
 struct NzbInfoFixture {std::set<int>* blocked;std::set<int>* GetDupeBlockedDonors(){return blocked;}} fixture{&blocked};auto* nzbInfo=&fixture;
	while (round < (int)sources.size() && round < (int)sourceDonors.size() &&
		nzbInfo->GetDupeBlockedDonors()->count(sourceDonors[round]))
	{
		round++;
	}
 return round < int(sources.size()) ? round : -1;
}
static void put(std::vector<uint8_t>& out,int32_t value){auto bits=uint32_t(value);for(int i=0;i<4;++i)out.push_back(uint8_t(bits>>(8*i)));}
int main(){
 std::mt19937_64 random(0x85020261013ULL);size_t events=0,pins=0;
 for(size_t trial=0;trial<10000;++trial){
  State rust{int32_t(random()%4),int32_t(random()%5),int32_t(random()%5)};
  FileInfo cpp;cpp.donor=rust.donor;cpp.failures=rust.failures;cpp.switches=rust.switches;
  for(int event=0;event<20;++event){
   ArticleInfo article;article.round=int(random()%4);article.lead=int(random()%4);article.next=int(random()%4);article.count=int(random()%5);
   article.offset=int64_t(random()%5)-2;article.end=int64_t(random()%5)-2;
   Pin pin{article.lead,article.next,article.count};
   if(random()%2){
    bool expected=DupeArticleFallback::RegisterLeadFailure(&cpp,&article);
    if(test_lead_failure(&rust,&pin,article.round)!=int(expected)){std::cerr<<"failure verdict mismatch\n";return 1;}
   }else{DupeArticleFallback::RegisterLeadSuccess(&cpp,&article);test_lead_success(&rust,&pin,article.round,article.offset,article.end);}
   if(rust.donor!=cpp.donor||rust.failures!=cpp.failures||rust.switches!=cpp.switches){std::cerr<<"state mismatch\n";return 1;}
   ++events;
  }
 }
 for(size_t trial=0;trial<2048;++trial){
  size_t count=trial<5?trial:random()%129;
  std::vector<std::string> text;std::vector<int> owners;std::vector<CString> native;
  for(size_t i=0;i<count;++i){std::string message="id"+std::to_string(random()%17);if(i%7==0)message+=std::string("\0extra",6);if(i%11==0)message[0]=char(0xff);text.push_back(message);owners.push_back(int(random()%8));}
  std::vector<CandidateInput> input;for(size_t i=0;i<count;++i){native.emplace_back(text[i].c_str());input.push_back({reinterpret_cast<const uint8_t*>(text[i].data()),text[i].size(),owners[i]});}
  State rust{int32_t(random()%3),int32_t(random()%5),int32_t(random()%5)};
  FileInfo cpp;cpp.donor=rust.donor;cpp.failures=rust.failures;cpp.switches=rust.switches;ArticleInfo article;
  bool cutover=(trial%2)==0;const std::string primary="primary";
  DupeArticleFallback::FinishPin(&cpp,&article,native,owners,cutover,primary.c_str());
  std::vector<uint8_t> expected;for(int v:{article.lead,article.next,article.count,cpp.donor,cpp.failures,cpp.switches})put(expected,v);put(expected,int(article.sources.size()));
  for(size_t i=0;i<article.sources.size();++i){bool owner=i<article.owners.size();expected.push_back(owner?1:0);put(expected,owner?article.owners[i]:0);auto& value=article.sources[i].value;put(expected,int(value.size()));expected.insert(expected.end(),value.begin(),value.end());}
  std::vector<uint8_t> result(65536);
  // Empty vectors supply a valid aligned dummy; the test ABI never borrows NULL.
  CandidateInput dummy{reinterpret_cast<const uint8_t*>(primary.data()),primary.size(),0};
  size_t size=test_pin_sources(&rust,input.empty()?&dummy:input.data(),input.size(),cutover,reinterpret_cast<const uint8_t*>(primary.data()),primary.size(),result.data(),result.size());result.resize(size);
  if(result!=expected||rust.donor!=cpp.donor||rust.failures!=cpp.failures||rust.switches!=cpp.switches){std::cerr<<"pin bytes/state mismatch\n";return 1;}
  std::set<int> blocked;for(int owner:owners)if(random()%2)blocked.insert(owner);
  std::vector<int32_t> block_input(blocked.begin(),blocked.end());int32_t block_dummy=0;
  for(int32_t round=0;round<int32_t(article.sources.size()+3);++round){
   int expected_index=original_next_source(article,round,blocked);int32_t next_round=-7;
   int64_t actual=test_next_source(input.empty()?&dummy:input.data(),input.size(),cutover,reinterpret_cast<const uint8_t*>(primary.data()),primary.size(),round,block_input.empty()?&block_dummy:block_input.data(),block_input.size(),&next_round);
   if(actual!=expected_index||(actual>=0&&next_round!=expected_index+1)||(actual<0&&next_round!=-7)){std::cerr<<"blocked-source advancement mismatch\n";return 1;}
  }
  ++pins;
 }
 std::cout<<"PASS "<<events<<" state events and "<<pins<<" pinned-source byte and advancement fixtures\n";
}
