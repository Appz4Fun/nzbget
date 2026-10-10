/*
 *  This file is part of nzbget. See <https://nzbget.com>.
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
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */


#include "nzbget.h"

#include <algorithm>
#include <map>
#include <set>
#include "TwinCheck.h"
#include "ArticleFetcher.h"
#include "DupeArticleFallback.h"
#include "DupeCoordinator.h"
#include "Options.h"
#include "Thread.h"
#include "Util.h"
#include "FileSystem.h"

namespace
{

uint64 ReadLe64(const uchar* p)
{
	uint64 value = 0;
	for (int i = 7; i >= 0; i--)
	{
		value = (value << 8) | p[i];
	}
	return value;
}

std::string Hex(const uchar* p, int len)
{
	static const char* digits = "0123456789abcdef";
	std::string hex;
	for (int i = 0; i < len; i++)
	{
		hex += digits[p[i] >> 4];
		hex += digits[p[i] & 15];
	}
	return hex;
}

class TwinCheckJob;

Mutex g_mutex;
std::set<TwinCheckJob*> g_jobs;
std::set<int> g_checking;		// downloads whose fingerprint is being fetched
std::atomic<int> g_jobCount{0};
bool g_stopping = false;

class TwinCheckJob : public Thread
{
public:
	TwinCheckJob(int nzbId, std::string nzbFilename) :
		m_nzbId(nzbId), m_nzbFilename(std::move(nzbFilename)) {}

	void Cancel() { m_fetcher.Stop(); }
	int GetNzbId() const { return m_nzbId; }

protected:
	void Run() override;

private:
	int m_nzbId;
	std::string m_nzbFilename;
	ArticleFetcher m_fetcher;

	/* the files of the posting's smallest par2-file; false: it has none, or
	 * none could be read (<fetched>: its articles were asked for) */
	bool IndexSigs(std::vector<TwinCheck::FileSig>& sigs, bool& fetched);
};

bool TwinCheckJob::IndexSigs(std::vector<TwinCheck::FileSig>& sigs, bool& fetched)
{
	fetched = false;
	std::unique_ptr<NzbInfo> nzbInfo = DupeArticleFallback::ParseDonorNzb(m_nzbFilename.c_str());
	if (!nzbInfo)
	{
		return false;
	}

	FileInfo* index = nullptr;
	for (FileInfo* fileInfo : nzbInfo->GetFileList())
	{
		if ((fileInfo->GetParFile() || Util::EndsWith(fileInfo->GetFilename(), ".par2", false)) &&
			!fileInfo->GetArticles()->empty() && (!index || fileInfo->GetSize() < index->GetSize()))
		{
			index = fileInfo;
		}
	}
	if (!index || index->GetSize() > TwinCheck::MaxIndexSize)
	{
		return false;
	}

	fetched = true;
	std::vector<char> data;
	for (std::unique_ptr<ArticleInfo>& article : *index->GetArticles())
	{
		if (IsStopped())
		{
			return false;
		}
		ArticleFetcher::FetchedArticle part = m_fetcher.Fetch(article->GetMessageId(), *index->GetGroups());
		if (!part.Success || part.Offset < 0 ||
			part.Offset + (int64)part.Data.size() > TwinCheck::MaxIndexSize)
		{
			// a lost article of the par2-file: what the others hold may still do
			continue;
		}
		if ((size_t)(part.Offset + part.Data.size()) > data.size())
		{
			data.resize((size_t)(part.Offset + part.Data.size()));
		}
		std::copy(part.Data.begin(), part.Data.end(), data.begin() + (size_t)part.Offset);
	}

	sigs = TwinCheck::ParsePar2(data.data(), data.size());
	return !sigs.empty();
}

void TwinCheckJob::Run()
{
	// leaves the registry however the check ends
	struct Unregister
	{
		TwinCheckJob* job;
		~Unregister()
		{
			Guard guard(g_mutex);
			g_jobs.erase(job);
			g_checking.erase(job->GetNzbId());
			g_jobCount--;
		}
	} unregister{this};

	std::vector<TwinCheck::FileSig> sigs;
	bool fetched = false;
	bool known = IndexSigs(sigs, fetched);
	if (IsStopped() || (!known && fetched))
	{
		// stopped, or the par2-file's articles weren't there (servers busy or down):
		// asked again at a later round
		return;
	}

	std::string fingerprint = known ? TwinCheck::Fingerprint(sigs) : "none";
	GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
	NzbInfo* nzbInfo = nullptr;
	for (NzbInfo* queued : downloadQueue->GetQueue())
	{
		if (queued->GetId() == m_nzbId)
		{
			nzbInfo = queued;
		}
	}
	for (std::unique_ptr<HistoryInfo>& historyInfo : *downloadQueue->GetHistory())
	{
		if (!nzbInfo && historyInfo->GetKind() == HistoryInfo::hkNzb && historyInfo->GetNzbInfo()->GetId() == m_nzbId)
		{
			nzbInfo = historyInfo->GetNzbInfo();
		}
	}
	if (nzbInfo)
	{
		nzbInfo->GetParameters()->SetParameter(TwinCheck::FilesParam, fingerprint.c_str());
		nzbInfo->PrintMessage(Message::mkDetail, "Fingerprint of %s: %s (%i file(s) in its par2 set)",
			nzbInfo->GetName(), fingerprint.c_str(), (int)sigs.size());
		downloadQueue->HistoryChanged();
		downloadQueue->Save();
	}
}

struct Item
{
	NzbInfo* nzbInfo;
	bool queued;
};

}

std::vector<TwinCheck::FileSig> TwinCheck::ParsePar2(const char* data, size_t size)
{
	std::map<std::string, FileSig> files;	// by file id: volumes repeat the packets
	const uchar* p = (const uchar*)data;
	size_t pos = 0;
	while (pos + 64 <= size)
	{
		if (memcmp(p + pos, "PAR2\0PKT", 8))
		{
			// a lost article leaves a gap: find the next packet
			pos += 4;
			continue;
		}
		uint64 length = ReadLe64(p + pos + 8);
		if (length < 64 || length % 4 || length > size - pos)
		{
			pos += 4;
			continue;
		}
		if (!memcmp(p + pos + 48, "PAR 2.0\0FileDesc", 16) && length >= 64 + 56)
		{
			// file id, MD5 of the file, MD5 of its first 16 KB, length, name
			const uchar* body = p + pos + 64;
			FileSig& sig = files[Hex(body, 16)];
			sig.md5 = Hex(body + 16, 16);
			sig.hash16k = Hex(body + 32, 16);
			sig.length = ReadLe64(body + 48);
			sig.name.assign((const char*)body + 56, (size_t)(length - 64 - 56));
			sig.name = sig.name.substr(0, sig.name.find('\0'));
		}
		pos += (size_t)length;
	}

	std::vector<FileSig> sigs;
	for (auto& entry : files)
	{
		sigs.push_back(std::move(entry.second));
	}
	return sigs;
}

std::string TwinCheck::Fingerprint(const std::vector<FileSig>& sigs)
{
	// by content only: names may differ between postings
	std::vector<std::string> files;
	for (const FileSig& sig : sigs)
	{
		files.push_back(sig.md5 + ":" + std::to_string(sig.length));
	}
	if (files.empty())
	{
		return "";
	}
	std::sort(files.begin(), files.end());
	files.erase(std::unique(files.begin(), files.end()), files.end());

	// FNV-1a, 64 bits: kept in the queue, so it mustn't vary between builds
	uint64 hash = 14695981039346656037ULL;
	for (const std::string& file : files)
	{
		for (char c : file + "\n")
		{
			hash ^= (uchar)c;
			hash *= 1099511628211ULL;
		}
	}
	BString<1024> hex("%016llx-%i", (unsigned long long)hash, (int)files.size());
	return *hex;
}

void TwinCheck::ServiceWork()
{
	if (!g_Options->GetDupeCheck())
	{
		return;
	}

	struct Job
	{
		int nzbId;
		std::string nzbFilename;
		bool hinted;
	};
	std::vector<Job> jobs;
	{
		GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
		bool changed = false;

		// every download with a dupe key, by key
		std::map<std::string, std::vector<Item>> keys;
		auto keyOf = [](NzbInfo* nzbInfo)
			{
				std::string key = nzbInfo->GetDupeKey() ? nzbInfo->GetDupeKey() : "";
				std::transform(key.begin(), key.end(), key.begin(), ::tolower);
				return key;
			};
		for (NzbInfo* nzbInfo : downloadQueue->GetQueue())
		{
			if (nzbInfo->GetKind() == NzbInfo::nkNzb && !keyOf(nzbInfo).empty())
			{
				keys[keyOf(nzbInfo)].push_back({nzbInfo, true});
			}
		}
		for (std::unique_ptr<HistoryInfo>& historyInfo : *downloadQueue->GetHistory())
		{
			if (historyInfo->GetKind() == HistoryInfo::hkNzb && !keyOf(historyInfo->GetNzbInfo()).empty())
			{
				keys[keyOf(historyInfo->GetNzbInfo())].push_back({historyInfo->GetNzbInfo(), false});
			}
		}

		auto isDupe = [](const Item& item)
			{
				NzbInfo* nzbInfo = item.nzbInfo;
				return item.queued ?
					nzbInfo->GetRemainingSize() > 0 && nzbInfo->GetPausedSize() >= nzbInfo->GetRemainingSize() :
					nzbInfo->GetDeleteStatus() == NzbInfo::dsDupe || nzbInfo->GetDeleteStatus() == NzbInfo::dsCopy;
			};
		auto fingerprintOf = [](NzbInfo* nzbInfo)
			{
				NzbParameter* files = nzbInfo->GetParameters()->Find(FilesParam);
				return std::string(files ? files->GetValue() : "");
			};

		for (auto& entry : keys)
		{
			std::vector<Item>& items = entry.second;
			if (items.size() < 2)
			{
				continue;
			}

			// postings without a fingerprint yet get one
			for (Item& item : items)
			{
				NzbInfo* nzbInfo = item.nzbInfo;
				if (fingerprintOf(nzbInfo).empty() && !strchr(nzbInfo->GetQueuedFilename(), '|') &&
					FileSystem::FileExists(nzbInfo->GetQueuedFilename()))
				{
					// the dupe tool's hints of a twin go first; they prove nothing
					bool hinted = nzbInfo->GetParameters()->Find("DupeSameSize") ||
						nzbInfo->GetParameters()->Find("DupeSameInner");
					jobs.push_back({nzbInfo->GetId(), nzbInfo->GetQueuedFilename(), hinted});
				}
			}

			// the primary: the download running (the highest score of the queued
			// ones not held back as duplicates), else the newest one in history
			// that wasn't deleted as a duplicate
			NzbInfo* primary = nullptr;
			for (Item& item : items)
			{
				if (item.queued && !isDupe(item) && (!primary || item.nzbInfo->GetDupeScore() > primary->GetDupeScore()))
				{
					primary = item.nzbInfo;
				}
			}
			for (Item& item : items)
			{
				if (!primary && !item.queued && !isDupe(item))
				{
					primary = item.nzbInfo;	// history: newest first
				}
			}

			// the labels: of the primary's twins and alts (none without fingerprints)
			std::string primaryPrint = primary ? fingerprintOf(primary) : "";
			bool comparable = !primaryPrint.empty() && primaryPrint != "none";
			for (Item& item : items)
			{
				NzbInfo* nzbInfo = item.nzbInfo;
				std::string print = fingerprintOf(nzbInfo);
				const char* kind = nzbInfo == primary || !isDupe(item) || !comparable ||
					print.empty() || print == "none" ? "" : print == primaryPrint ? "twin" : "alt";
				NzbParameter* old = nzbInfo->GetParameters()->Find(KindParam);
				if (strcmp(old ? old->GetValue() : "", kind))
				{
					nzbInfo->GetParameters()->SetParameter(KindParam, kind);
					changed = true;
					if (*kind)
					{
						nzbInfo->PrintMessage(Message::mkInfo, "%s is %s of %s (%s)", nzbInfo->GetName(),
							*kind == 't' ? "a twin" : "an alt", primary->GetName(),
							*kind == 't' ? "byte-identical files by their par2 checksums" :
							"another encode: its files' par2 checksums differ");
					}
				}
			}
		}

		if (changed)
		{
			downloadQueue->HistoryChanged();
			downloadQueue->Save();
		}
	}

	std::stable_sort(jobs.begin(), jobs.end(), [](const Job& a, const Job& b) { return a.hinted > b.hinted; });

	Guard guard(g_mutex);
	for (Job& job : jobs)
	{
		if (g_stopping || (int)g_jobs.size() >= MaxRunning)
		{
			break;
		}
		if (g_checking.count(job.nzbId))
		{
			continue;
		}
		TwinCheckJob* thread = new TwinCheckJob(job.nzbId, job.nzbFilename);
		g_jobs.insert(thread);
		g_checking.insert(job.nzbId);
		g_jobCount++;
		thread->SetAutoDestroy(true);
		thread->Start();
	}
}

void TwinCheck::StopAll()
{
	Guard guard(g_mutex);
	g_stopping = true;
	for (TwinCheckJob* job : g_jobs)
	{
		job->Stop();
		job->Cancel();
	}
}

void TwinCheck::WaitAll()
{
	while (g_jobCount > 0)
	{
		Util::Sleep(20);
	}
}

void TwinCheck::Reset()
{
	Guard guard(g_mutex);
	g_stopping = false;
}
