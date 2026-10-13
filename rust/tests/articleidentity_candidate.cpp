#if !defined(NZBGET_USE_RUST) || !defined(NZBGET_RS_EXPERIMENTAL_ARTICLE_MATCH)
#error Candidate correctness fixture requires enabled Rust article matching
#endif
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

// Exact historical matcher bodies; fixture getters, not a performance caller.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cctype>
#include <clocale>
#include <iostream>
#include <stdexcept>
#include "nzbget_rs.h"
#include <memory>
#include <map>
#include <set>
#include <random>
#include <string>
#include <vector>
using int64=int64_t;using uint64=uint64_t;
struct Part {int32_t part,size;};
struct RawFile {const uint8_t* name;size_t name_len;const uint8_t* subject;size_t subject_len;int64_t size;int32_t total,par;const Part* parts;size_t count;};
struct Outcome {int64_t index;uint64_t hash;int32_t declared,structure,steps;};
extern "C" Outcome test_identity(const RawFile*,const RawFile*,size_t,const uint8_t*,size_t,const uint8_t*,size_t,const uint8_t*,const uint8_t*);
struct ArticleInfo {Part p;int GetPartNumber(){return p.part;}int GetSize(){return p.size;}};
class ArticleList:public std::vector<std::unique_ptr<ArticleInfo>> {
public:struct Iterator{std::vector<std::unique_ptr<ArticleInfo>>::iterator it;ArticleInfo* operator*(){return it->get();}Iterator& operator++(){++it;return *this;}bool operator!=(const Iterator& o){return it!=o.it;}};
 Iterator begin(){return {std::vector<std::unique_ptr<ArticleInfo>>::begin()};}Iterator end(){return {std::vector<std::unique_ptr<ArticleInfo>>::end()};}
};
static ArticleList::Iterator begin(ArticleList* v){return v->begin();}
static ArticleList::Iterator end(ArticleList* v){return v->end();}
struct NzbInfo;
struct FileInfo {
 std::string name,subject;int64 size;int total;bool par;ArticleList articles;NzbInfo* owner;
 explicit FileInfo(const RawFile& r):name(reinterpret_cast<const char*>(r.name),r.name_len),subject(reinterpret_cast<const char*>(r.subject),r.subject_len),size(r.size),total(r.total),par(r.par!=0),owner(nullptr){for(size_t i=0;i<r.count;++i){auto a=std::make_unique<ArticleInfo>();a->p=r.parts[i];articles.push_back(std::move(a));}}
 const char* GetFilename(){return name.c_str();}const char* GetSubject(){return subject.c_str();}int64 GetSize(){return size;}int GetTotalArticles(){return total;}ArticleList* GetArticles(){return &articles;}NzbInfo* GetNzbInfo(){return owner;}
};
class FileList:public std::vector<std::unique_ptr<FileInfo>> {
public:struct Iterator{std::vector<std::unique_ptr<FileInfo>>::iterator it;FileInfo* operator*(){return it->get();}Iterator& operator++(){++it;return *this;}bool operator!=(const Iterator& o){return it!=o.it;}};
 Iterator begin(){return {std::vector<std::unique_ptr<FileInfo>>::begin()};}Iterator end(){return {std::vector<std::unique_ptr<FileInfo>>::end()};}
};
static FileList::Iterator begin(FileList* v){return v->begin();}
static FileList::Iterator end(FileList* v){return v->end();}
struct NzbInfo {FileList files;int GetId(){return 1;}FileList* GetFileList(){return &files;}};
namespace TwinCheck {static std::string evidence;static std::string Identity(NzbInfo*){return "validated";}static std::string MatchByContent(int,const char*,const char*,const char*,int,const char*){return evidence;}}
namespace Util {static bool EmptyStr(const char* p){return !p||!*p;}}
class DupeArticleFallback {
public:static constexpr int MinStepFingerprintArticles=8,TotalSizeToleranceDiv=64,PartSizeToleranceDiv=16;
 static bool IsParFile(FileInfo* f){return f->par;}
 static FileInfo* MatchDonorFile(FileInfo*,NzbInfo*,const char*,int,const char*);
 static uint64 ArticleSizeStepsHash(FileInfo*);static bool ArticleSizeStepsMatch(FileInfo*,FileInfo*);static bool StructureMatches(FileInfo*,FileInfo*);static bool SizesMatch(int64,int64,int);
};
static int DeclaredParts(FileInfo* fileInfo)
{
	const char* subject = fileInfo->GetSubject();
	int declared = 0;
	for (const char* p = subject ? strchr(subject, '(') : nullptr; p; p = strchr(p + 1, '('))
	{
		int part = 0;
		int count = 0;
		char close = 0;
		if (sscanf(p, "(%d/%d%c", &part, &count, &close) == 3 && close == ')' && part >= 0 && count > 0)
		{
			declared = count;
		}
	}
	return declared;
}

FileInfo* DupeArticleFallback::MatchDonorFile(FileInfo* targetFile, NzbInfo* donorNzb,
	const char* targetNzbFilename, int donorNzbId, const char* donorPrint)
{
	if (IsParFile(targetFile))
	{
		return nullptr;
	}

	// by content first, when the par2 file lists of both postings are known
	// (twin.rs): a donor file with the target's MD5 and length is the same bytes
	// under any name. "-": the donor's complete list has no file with these bytes;
	// "": not known (incomplete or missing lists, several candidates)
	NzbInfo* own = targetFile->GetNzbInfo();
	std::string ownIdentity = own ? TwinCheck::Identity(own) : "";
	std::string byContent = donorNzbId && !ownIdentity.empty() && !Util::EmptyStr(donorPrint) ?
		TwinCheck::MatchByContent(own->GetId(), ownIdentity.c_str(), targetFile->GetFilename(),
			targetNzbFilename, donorNzbId, donorPrint) : "";
#ifdef NZBGET_RS_EXPERIMENTAL_ARTICLE_MATCH
	// Candidate-only full caller route: capture while the queue lock protects
	// the real FileInfo objects. Snapshot/ownership/locale/FFI costs are part
	// of the future complete-caller measurement; this is disabled by default.
	std::vector<std::vector<NzbgetRsIdentityPart>> partStorage;
	partStorage.reserve(donorNzb->GetFileList()->size() + 1);
	auto capture = [&partStorage](FileInfo* file) -> NzbgetRsIdentityFile
	{
		partStorage.emplace_back();
		auto& parts = partStorage.back();
		parts.reserve(file->GetArticles()->size());
		for (ArticleInfo* article : file->GetArticles())
		{
			parts.push_back({article->GetPartNumber(), article->GetSize()});
		}
		const char* name = file->GetFilename();
		const char* subject = file->GetSubject();
		return {reinterpret_cast<const uint8_t*>(name), name ? strlen(name) : 0,
			reinterpret_cast<const uint8_t*>(subject), subject ? strlen(subject) : 0,
			file->GetSize(), file->GetTotalArticles(), IsParFile(file) ? 1 : 0,
			parts.data(), parts.size()};
	};
	NzbgetRsIdentityFile target = capture(targetFile);
	std::vector<NzbgetRsIdentityFile> donors;
	donors.reserve(donorNzb->GetFileList()->size());
	for (FileInfo* donor : donorNzb->GetFileList()) { donors.push_back(capture(donor)); }
	uint8_t fold[256], whitespace[256];
	for (int byte = 0; byte < 256; byte++)
	{
		fold[byte] = static_cast<uint8_t>(std::tolower(byte));
		whitespace[byte] = std::isspace(byte) ? 1 : 0;
	}
	const int64 matched = nzbget_rs_article_match(&target, donors.data(), donors.size(),
		reinterpret_cast<const uint8_t*>(targetNzbFilename), targetNzbFilename ? strlen(targetNzbFilename) : 0,
		reinterpret_cast<const uint8_t*>(byContent.data()), byContent.size(), fold, whitespace);
	if (matched < -1 || (matched >= 0 && static_cast<uint64>(matched) >= static_cast<uint64>(donors.size())))
	{
		// A rejected candidate invalidates qualification, rather than silently
		// falling through to C++ and falsely counting a Rust operation hit.
		throw std::runtime_error("Experimental Rust article matcher rejected its snapshot");
	}
	return matched >= 0 && static_cast<size_t>(matched) < donors.size() ?
		donorNzb->GetFileList()->at(static_cast<size_t>(matched)).get() : nullptr;
#else
	if (byContent == "-")
	{
		return nullptr;
	}
	if (!byContent.empty())
	{
		// the donor's file of that name (exact case first): it holds our bytes, so
		// if its articles don't fit ours, no other file of the donor is the one.
		// A name the donor's nzb doesn't have (it names the file otherwise), or
		// has twice, leaves it to the matching below
		std::vector<FileInfo*> exact;
		std::vector<FileInfo*> folded;
		for (FileInfo* donorFile : donorNzb->GetFileList())
		{
			if (IsParFile(donorFile))
			{
				continue;
			}
			if (!strcmp(donorFile->GetFilename(), byContent.c_str()))
			{
				exact.push_back(donorFile);
			}
			else if (!strcasecmp(donorFile->GetFilename(), byContent.c_str()))
			{
				folded.push_back(donorFile);
			}
		}
		FileInfo* named = exact.size() == 1 ? exact[0] : exact.empty() && folded.size() == 1 ? folded[0] : nullptr;
		if (named)
		{
			return StructureMatches(targetFile, named) ? named : nullptr;
		}
	}

	std::vector<FileInfo*> structuralMatches;
	FileInfo* filenameMatch = nullptr;
	bool filenameAmbiguous = false;

	for (FileInfo* donorFile : donorNzb->GetFileList())
	{
		if (IsParFile(donorFile) || !StructureMatches(targetFile, donorFile))
		{
			continue;
		}

		if (!strcasecmp(targetFile->GetFilename(), donorFile->GetFilename()) ||
			(!Util::EmptyStr(targetNzbFilename) &&
			 !strcasecmp(targetNzbFilename, donorFile->GetFilename())))
		{
			if (filenameMatch)
			{
				filenameAmbiguous = true;
			}
			else
			{
				filenameMatch = donorFile;
			}
			continue;
		}

		structuralMatches.push_back(donorFile);
	}

	// An exact filename is preferred only when it is unique.  Choosing the
	// first exact match is nondeterministic for multi-file duplicate NZBs.
	if (filenameAmbiguous)
	{
		return nullptr;
	}
	if (filenameMatch)
	{
		return filenameMatch;
	}
	if (structuralMatches.size() == 1)
	{
		return structuralMatches[0];
	}

	// Equal-size volumes of an obfuscated repost all match structurally;
	// the identical member is the only one whose article sizes step exactly
	// like the target's.
	FileInfo* stepMatch = nullptr;
	for (FileInfo* donorFile : structuralMatches)
	{
		if (ArticleSizeStepsMatch(targetFile, donorFile))
		{
			if (stepMatch)
			{
				return nullptr;
			}
			stepMatch = donorFile;
		}
	}
	return stepMatch;
#endif
}

uint64 DupeArticleFallback::ArticleSizeStepsHash(FileInfo* fileInfo)
{
	ArticleList* articles = fileInfo->GetArticles();
	if ((int)articles->size() < MinStepFingerprintArticles)
	{
		return 0;
	}

	// FNV-1a over the article count and the steps between consecutive sizes
	uint64 hash = 14695981039346656037ULL;
	auto mix = [&hash](int64 value)
	{
		for (int i = 0; i < 8; i++)
		{
			hash ^= (uint64)((value >> (i * 8)) & 0xff);
			hash *= 1099511628211ULL;
		}
	};

	mix((int64)articles->size());
	bool varying = false;
	for (size_t i = 1; i < articles->size(); i++)
	{
		int step = (*articles)[i]->GetSize() - (*articles)[i - 1]->GetSize();
		mix(step);
		varying |= step != 0 && i < articles->size() - 1;
	}
	return varying && hash != 0 ? hash : 0;
}

bool DupeArticleFallback::ArticleSizeStepsMatch(FileInfo* targetFile, FileInfo* donorFile)
{
	// An NZB lists the encoded size of each article including its headers.
	// Two postings of the same bytes with the same segmentation differ there
	// only by a per-file constant (their subject lines differ), so the steps
	// between consecutive article sizes are equal. Encoded sizes vary with
	// the content (yEnc escaping), which makes the step sequence a strong
	// identity fingerprint once a file has enough articles.
	ArticleList* targetArticles = targetFile->GetArticles();
	ArticleList* donorArticles = donorFile->GetArticles();
	if ((int)targetArticles->size() < MinStepFingerprintArticles ||
		targetArticles->size() != donorArticles->size())
	{
		return false;
	}

	bool varying = false;
	for (size_t i = 1; i < targetArticles->size(); i++)
	{
		int targetStep = (*targetArticles)[i]->GetSize() - (*targetArticles)[i - 1]->GetSize();
		int donorStep = (*donorArticles)[i]->GetSize() - (*donorArticles)[i - 1]->GetSize();
		if (targetStep != donorStep)
		{
			return false;
		}
		// a posting tool that lists one fixed size per article proves nothing
		varying |= targetStep != 0 && i < targetArticles->size() - 1;
	}
	return varying;
}

bool DupeArticleFallback::StructureMatches(FileInfo* targetFile, FileInfo* donorFile)
{
	ArticleList* targetArticles = targetFile->GetArticles();
	ArticleList* donorArticles = donorFile->GetArticles();

	if (targetArticles->empty())
	{
		return false;
	}

	// twins are posted in as many parts: a file whose subject counts other parts, or
	// that has a part beyond the count the release's subject declares, is another file
	// (B39: dead volumes of 29 parts paired with a healthy 30-part file)
	int targetDeclared = DeclaredParts(targetFile);
	int donorDeclared = DeclaredParts(donorFile);
	if (targetDeclared > 0 && donorDeclared > 0 && targetDeclared != donorDeclared)
	{
		return false;
	}
	if (targetDeclared > 0)
	{
		for (ArticleInfo* donorArticle : donorFile->GetArticles())
		{
			if (donorArticle->GetPartNumber() > targetDeclared)
			{
				return false;
			}
		}
	}

	// The release's nzb-file may lack a few segments (an indexer that didn't
	// capture them all): it still pairs with a twin that lists them, part by part.
	// Every part the release lists must be in the duplicate at a matching size;
	// the duplicate's other parts must be gaps in the release's list (at most one
	// in 16), and at most one may follow the release's last part - more would be a
	// longer encode with the same article size, not a twin.
	if (targetArticles->size() < donorArticles->size())
	{
		size_t extra = donorArticles->size() - targetArticles->size();
		if (extra > std::max<size_t>(1, donorArticles->size() / 16))
		{
			return false;
		}
		std::map<int, ArticleInfo*> donorParts;
		for (ArticleInfo* donorArticle : donorFile->GetArticles())
		{
			donorParts[donorArticle->GetPartNumber()] = donorArticle;
		}
		int lastTargetPart = 0;
		std::set<int> targetParts;
		for (ArticleInfo* targetArticle : targetFile->GetArticles())
		{
			auto it = donorParts.find(targetArticle->GetPartNumber());
			if (it == donorParts.end() ||
				!SizesMatch(targetArticle->GetSize(), it->second->GetSize(), PartSizeToleranceDiv))
			{
				return false;
			}
			targetParts.insert(targetArticle->GetPartNumber());
			lastTargetPart = std::max(lastTargetPart, targetArticle->GetPartNumber());
		}
		int trailing = 0;
		int64 trailingSize = 0;
		for (ArticleInfo* donorArticle : donorFile->GetArticles())
		{
			if (!targetParts.count(donorArticle->GetPartNumber()) && donorArticle->GetPartNumber() > lastTargetPart)
			{
				trailing++;
				trailingSize += donorArticle->GetSize();
			}
		}
		// nzbget counts a segment the nzb-file lacks between listed parts as missed,
		// so the release's size includes an estimate for it, close to the twin's size
		return trailing <= 1 &&
			SizesMatch(targetFile->GetSize() + trailingSize, donorFile->GetSize(), TotalSizeToleranceDiv);
	}

	if (targetArticles->size() != donorArticles->size() ||
		targetFile->GetTotalArticles() != donorFile->GetTotalArticles() ||
		!SizesMatch(targetFile->GetSize(), donorFile->GetSize(), TotalSizeToleranceDiv))
	{
		return false;
	}

	for (size_t i = 0; i < targetArticles->size(); i++)
	{
		ArticleInfo* targetArticle = (*targetArticles)[i].get();
		ArticleInfo* donorArticle = (*donorArticles)[i].get();
		if (targetArticle->GetPartNumber() != donorArticle->GetPartNumber() ||
			!SizesMatch(targetArticle->GetSize(), donorArticle->GetSize(), PartSizeToleranceDiv))
		{
			return false;
		}
	}

	return true;
}

bool DupeArticleFallback::SizesMatch(int64 size1, int64 size2, int div)
{
	int64 diff = size1 > size2 ? size1 - size2 : size2 - size1;
	return diff <= std::max(size1, size2) / div;
}
struct OwnedFile {std::string name,subject;int64_t size;int32_t total,par;std::vector<Part> parts;RawFile view() const {static const Part dummy{0,0};return {reinterpret_cast<const uint8_t*>(name.data()),name.size(),reinterpret_cast<const uint8_t*>(subject.data()),subject.size(),size,total,par,parts.empty()?&dummy:parts.data(),parts.size()};}};
extern "C" uint64_t nzbget_rs_article_match_trace_count();
int main(){
 std::setlocale(LC_CTYPE,"C");uint8_t fold[256],space[256];for(int i=0;i<256;++i){fold[i]=uint8_t(std::tolower(i));space[i]=uint8_t(bool(std::isspace(i)));}
 std::mt19937_64 random(0x85020261013ULL);size_t cases=0;
 auto file=[&](int count,std::string name){OwnedFile f{std::move(name),"",0,count,0,{}};for(int p=1;p<=count;++p){int size=1000+int(random()%15);f.parts.push_back({p,size});f.size+=size;}return f;};
 for(size_t trial=0;trial<20000;++trial){
  int count=trial%25==0?0:int(random()%65);auto target=file(count,"target");if(trial%17==0)target.par=1;
  std::vector<OwnedFile> donors;
  for(size_t j=0;j<1+random()%5;++j){auto d=target;d.name="donor"+std::to_string(j);if(random()%3==0)d.name="TARGET";if(random()%7==0)d.par=1;
   if(!d.parts.empty()&&random()%3==0)d.parts[random()%d.parts.size()].size+=int(random()%150);
   if(!d.parts.empty()&&random()%7==0)d.parts.push_back(d.parts[0]);
   donors.push_back(std::move(d));
  }
  if(!target.parts.empty()&&random()%4==0)target.parts.erase(target.parts.begin()+random()%target.parts.size());
  if(trial%9==0)target.subject="(1/"+std::to_string(count)+")";
  if(trial%11==0)donors[0].subject="(1/"+std::to_string(count+1)+")";
  if(trial%13==0)target.name=std::string("target\0tail",11);
  if(trial%19==0)donors[0].name=std::string("\xffname",5);
  std::string evidence,alternate;
  switch(trial%7){case 1:evidence="-";break;case 2:evidence=donors[0].name;break;case 3:evidence=std::string("-\0tail",6);donors[0].name="-";break;case 4:evidence=std::string("\0tail",5);donors[0].name="";break;case 5:alternate=donors[0].name;break;}
  auto raw_target=target.view();std::vector<RawFile> raw_donors;NzbInfo own,donor_nzb;FileInfo native_target(raw_target);native_target.owner=&own;
  for(const auto& d:donors){auto raw=d.view();raw_donors.push_back(raw);donor_nzb.files.push_back(std::make_unique<FileInfo>(raw));}
  TwinCheck::evidence=evidence;auto* found=DupeArticleFallback::MatchDonorFile(&native_target,&donor_nzb,alternate.c_str(),1,"validated");int64_t index=-1;for(size_t i=0;i<donor_nzb.files.size();++i)if(found==donor_nzb.files[i].get())index=int64_t(i);
  Outcome expected{index,DupeArticleFallback::ArticleSizeStepsHash(&native_target),DeclaredParts(&native_target),int32_t(DupeArticleFallback::StructureMatches(&native_target,donor_nzb.files[0].get())),int32_t(DupeArticleFallback::ArticleSizeStepsMatch(&native_target,donor_nzb.files[0].get()))};
  auto result=test_identity(&raw_target,raw_donors.data(),raw_donors.size(),reinterpret_cast<const uint8_t*>(alternate.data()),alternate.size(),reinterpret_cast<const uint8_t*>(evidence.data()),evidence.size(),fold,space);
  if(result.index!=expected.index||result.hash!=expected.hash||result.declared!=expected.declared||result.structure!=expected.structure||result.steps!=expected.steps){std::cerr<<"matcher parity failure fixture "<<trial<<" index "<<result.index<<"/"<<expected.index<<"\n";return 1;}++cases;
 }
 if(nzbget_rs_article_match_trace_count()==0){std::cerr<<"Rust matching boundary not reached\n";return 1;}
 std::cout<<"Rust boundary calls "<<nzbget_rs_article_match_trace_count()<<"\n";
 std::cout<<"PASS "<<cases<<" historical C++/Rust matcher fixtures\n";
}
