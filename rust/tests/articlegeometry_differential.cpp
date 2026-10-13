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

// Exact baseline geometry bodies with a minimal object-access fixture.
// Correctness oracle only: these fixture objects are NOT a complete caller speed control.
#include <algorithm>
#include <cstdint>
#include <cstddef>
#include <iostream>
#include <limits>
#include <memory>
#include <random>
#include <vector>
using int64 = int64_t;
struct InputArticle { int32_t part, size; int64_t offset; int32_t segment_size; uint8_t finished, borrowed; };
struct OutputArticle { int64_t expected_offset, expected_end; int32_t aligned; };
static_assert(sizeof(InputArticle)==24 && offsetof(InputArticle, offset)==8 && offsetof(InputArticle, segment_size)==16, "input ABI layout");
static_assert(sizeof(OutputArticle)==24 && offsetof(OutputArticle, aligned)==16, "output ABI layout");
extern "C" int64_t nzbget_rs_article_geometry(const InputArticle*, size_t, int64_t, OutputArticle*, size_t);
class ArticleInfo {
public:
 enum EStatus { aiUndefined, aiFinished };
 InputArticle input;
 int GetPartNumber() const { return input.part; }
 int GetSegmentSize() const { return input.segment_size; }
 int64 GetSegmentOffset() const { return input.offset; }
 EStatus GetStatus() const { return input.finished ? aiFinished : aiUndefined; }
 int GetDupeFallbackRound() const { return input.borrowed ? 1 : 0; }
};
// Match the historical container's unique ownership and raw-pointer iteration.
class ArticleList : public std::vector<std::unique_ptr<ArticleInfo>> {
public:
 struct Iterator {
  std::vector<std::unique_ptr<ArticleInfo>>::iterator it;
  ArticleInfo* operator*() const { return it->get(); }
  Iterator& operator++() { ++it; return *this; }
  bool operator!=(const Iterator& other) const { return it != other.it; }
 };
 Iterator begin() { return {std::vector<std::unique_ptr<ArticleInfo>>::begin()}; }
 Iterator end() { return {std::vector<std::unique_ptr<ArticleInfo>>::end()}; }
};
class FileInfo {
public:
 ArticleList articles;
 int64 decoded_size;
 ArticleList* GetArticles() { return &articles; }
 int64 GetDecodedFileSize() const { return decoded_size; }
};
class DupeArticleFallback {
public:
 static int64 ExpectedSegmentOffset(FileInfo*, ArticleInfo*);
 static int64 ExpectedSegmentEnd(FileInfo*, ArticleInfo*);
 static bool SegmentAligned(FileInfo*, ArticleInfo*);
 static ArticleInfo* FirstUntiledArticle(FileInfo*);
};
static int FindArticleIndex(ArticleList* articles, ArticleInfo* articleInfo)
{
	for (size_t i = 0; i < articles->size(); i++)
	{
		if ((*articles)[i].get() == articleInfo)
		{
			return (int)i;
		}
	}
	return -1;
}

int64 DupeArticleFallback::ExpectedSegmentOffset(FileInfo* fileInfo, ArticleInfo* articleInfo)
{
	ArticleList* articles = fileInfo->GetArticles();
	int index = FindArticleIndex(articles, articleInfo);
	if (index < 0)
	{
		return -1;
	}

	if (articleInfo->GetPartNumber() == 1)
	{
		// the first part of a file always decodes to offset 0
		return 0;
	}
	if (index == 0)
	{
		// earlier parts are missing from the nzb-file: the offset is unknown
		return -1;
	}

	// a list neighbour is the previous part only when the nzb-file lists every part
	ArticleInfo* prev = (*articles)[index - 1].get();
	if (prev->GetPartNumber() == articleInfo->GetPartNumber() - 1 &&
		prev->GetStatus() == ArticleInfo::aiFinished && prev->GetSegmentSize() > 0)
	{
		return prev->GetSegmentOffset() + prev->GetSegmentSize();
	}

	return -1;
}

int64 DupeArticleFallback::ExpectedSegmentEnd(FileInfo* fileInfo, ArticleInfo* articleInfo)
{
	ArticleList* articles = fileInfo->GetArticles();
	int index = FindArticleIndex(articles, articleInfo);
	if (index < 0)
	{
		return -1;
	}

	if (index == (int)articles->size() - 1)
	{
		// the last article of a file must decode up to the decoded file size
		// (known once any article of the file was decoded)
		return fileInfo->GetDecodedFileSize() > 0 ? fileInfo->GetDecodedFileSize() : -1;
	}

	ArticleInfo* next = (*articles)[index + 1].get();
	if (next->GetPartNumber() == articleInfo->GetPartNumber() + 1 &&
		next->GetStatus() == ArticleInfo::aiFinished && next->GetSegmentSize() > 0)
	{
		return next->GetSegmentOffset();
	}

	return -1;
}

bool DupeArticleFallback::SegmentAligned(FileInfo* fileInfo, ArticleInfo* articleInfo)
{
	int64 begin = articleInfo->GetSegmentOffset();
	int size = articleInfo->GetSegmentSize();
	if (size <= 0)
	{
		// no decoded placement recorded - nothing to validate against
		return true;
	}

	int64 expectedOffset = ExpectedSegmentOffset(fileInfo, articleInfo);
	if (expectedOffset >= 0 && begin != expectedOffset)
	{
		return false;
	}

	int64 expectedEnd = ExpectedSegmentEnd(fileInfo, articleInfo);
	if (expectedEnd >= 0 && begin + size != expectedEnd)
	{
		return false;
	}

	return true;
}

ArticleInfo* DupeArticleFallback::FirstUntiledArticle(FileInfo* fileInfo)
{
	// DecodedFileSize is only set from a decoded yEnc article; when it is 0 the
	// file is non-yEnc (e.g. uuencode, whose articles all record offset 0) or
	// its geometry is not yet known - either way the tiling cannot be judged.
	// After a restart it is repopulated from the first yEnc article that
	// completes, so it is available again by the time a reloaded file finishes.
	int64 decodedSize = fileInfo->GetDecodedFileSize();
	if (decodedSize <= 0)
	{
		return nullptr;
	}

	int64 expected = 0;
	ArticleList* articles = fileInfo->GetArticles();
	for (size_t index = 0; index < articles->size(); index++)
	{
		ArticleInfo* article = (*articles)[index].get();
		if (article->GetStatus() != ArticleInfo::aiFinished || article->GetSegmentSize() <= 0)
		{
			// an unfinished article or one without a recorded decoded placement
			// leaves the geometry incomplete: do not judge (avoids false positives
			// on partial or non-decoded states)
			return nullptr;
		}
		if (article->GetSegmentOffset() != expected)
		{
			// a gap (offset > expected) or overlap (offset < expected) at this seam.
			// A duplicate's article is the likelier culprit than the release's own.
			// Otherwise, at a gap, an article that ends exactly where the next one
			// begins (or at the file's end) is placed right: the one before it
			// decoded short. Anything else is this article's fault.
			ArticleInfo* prev = index > 0 ? (*articles)[index - 1].get() : nullptr;
			if (prev)
			{
				bool prevBorrowed = prev->GetDupeFallbackRound() > 0;
				bool thisBorrowed = article->GetDupeFallbackRound() > 0;
				if (prevBorrowed != thisBorrowed)
				{
					return prevBorrowed ? prev : article;
				}
				int64 end = article->GetSegmentOffset() + article->GetSegmentSize();
				ArticleInfo* next = index + 1 < articles->size() ? (*articles)[index + 1].get() : nullptr;
				bool placedRight = next ? next->GetStatus() == ArticleInfo::aiFinished &&
					next->GetSegmentSize() > 0 && next->GetSegmentOffset() == end : end == decodedSize;
				if (article->GetSegmentOffset() > expected && placedRight)
				{
					return prev;
				}
			}
			return article;
		}
		expected = article->GetSegmentOffset() + article->GetSegmentSize();
	}

	if (expected != decodedSize)
	{
		// the assembled decoded bytes fall short of / exceed the file size
		return articles->empty() ? nullptr : (*articles)[articles->size() - 1].get();
	}

	return nullptr;
}
static bool check(const std::vector<InputArticle>& input, int64_t decoded) {
 FileInfo file; file.decoded_size = decoded;
 for (const auto& a:input) { auto item=std::make_unique<ArticleInfo>(); item->input=a; file.articles.push_back(std::move(item)); }
 std::vector<OutputArticle> output(input.size());
 auto rust = nzbget_rs_article_geometry(input.data(), input.size(), decoded, output.data(), output.size());
 auto native = DupeArticleFallback::FirstUntiledArticle(&file);
 int64_t native_index=-1;
 for(size_t i=0;i<input.size();++i) if(file.articles[i].get()==native) native_index=static_cast<int64_t>(i);
 if(rust != native_index) { std::cerr << "first untiled differs: "<<rust<<" vs "<<native_index<<"\n"; return false; }
 for(size_t i=0;i<input.size();++i) {
  auto a=file.articles[i].get();
  if(output[i].expected_offset != DupeArticleFallback::ExpectedSegmentOffset(&file,a) ||
     output[i].expected_end != DupeArticleFallback::ExpectedSegmentEnd(&file,a) ||
     output[i].aligned != int(DupeArticleFallback::SegmentAligned(&file,a))) {
   std::cerr << "geometry differs at article "<<i<<"\n"; return false;
  }
 }
 return true;
}
int main() {
 std::mt19937_64 random(0x85020261013ULL);
 size_t cases=0;
 for(size_t count: {size_t(0),size_t(1),size_t(2),size_t(3),size_t(32),size_t(4096)}) {
  // Complete, incomplete, seam, borrower, negative and missing-part states.
  for(int mode=0;mode<10;++mode) {
   std::vector<InputArticle> input;
   for(size_t i=0;i<count;++i) input.push_back({int32_t(i+1),110,int64_t(i*100),100,1,0});
   if(count) {
    auto at=count/2;
    switch(mode) {
     case 1: input[at].offset+=10; break;
     case 2: input[at].offset-=10; break;
     case 3: input[at].finished=0; break;
     case 4: input[at].segment_size=0; break;
     case 5: input[at].borrowed=1; input[at].offset+=10; break;
     case 6: input[at].part+=2; break;
     case 7: input[at].offset=-2; break;
     case 8: input[at].segment_size=-1; break;
     case 9: input.back().segment_size=90; break;
    }
   }
   for(int64_t decoded: {int64_t(-1),int64_t(0),int64_t(count*100),int64_t(count*100+1)}) {
    if(!check(input,decoded)) return 1; ++cases;
   }
  }
 }
 for(size_t trial=0;trial<20000;++trial) {
  size_t count=random()%65; std::vector<InputArticle> input;
  for(size_t i=0;i<count;++i) input.push_back({int32_t(random()%80)-2,int32_t(random()%300),int64_t(random()%10000)-200,int32_t(random()%250)-20,uint8_t(random()%2),uint8_t(random()%2)});
  if(!check(input,int64_t(random()%10000)-200)) return 1; ++cases;
 }
 std::cout << "PASS "<<cases<<" actual extracted C++/Rust geometry fixtures\n";
}
