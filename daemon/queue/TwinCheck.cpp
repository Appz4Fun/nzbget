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
#include <climits>
#include <fstream>
#include <iterator>
#include "TwinCheck.h"
#include "ArticleFetcher.h"
#include "DupeCoordinator.h"
#include "Options.h"
#include "Thread.h"
#include "Util.h"
#include "FileSystem.h"
#include <sstream>
#include <mutex>
#include <atomic>
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif

namespace
{

#ifdef NZBGET_USE_RUST
// the result of a Rust call, copied and released
std::string RsString(NzbgetRsBuf buf)
{
	std::string text(buf.data ? buf.data : "", buf.len);
	nzbget_rs_free(buf);
	return text;
}

// the store of par2 file lists (queue directory, file "twincheck"), opened on
// first use: the constructors run before the options are read
bool OpenStore()
{
	// no options (unit tests): no store, and every list unknown
	static std::atomic<bool> opened{false};
	static std::mutex mutex;
	if (opened)
	{
		return true;
	}
	std::lock_guard<std::mutex> guard(mutex);
	if (!opened && g_Options && !Util::EmptyStr(g_Options->GetQueueDir()))
	{
		nzbget_rs_twin_open((std::string(g_Options->GetQueueDir()) + PATH_SEPARATOR + "twincheck").c_str());
		opened = true;
	}
	return opened;
}

std::vector<TwinCheck::FileSig> SigLines(const std::string& text)
{
	std::vector<TwinCheck::FileSig> sigs;
	std::istringstream lines(text);
	std::string line;
	while (std::getline(lines, line))
	{
		size_t a = line.find('\t'), b = line.find('\t', a + 1);
		if (a == std::string::npos || b == std::string::npos)
		{
			continue;
		}
		TwinCheck::FileSig sig;
		sig.length = strtoull(line.c_str(), nullptr, 10);
		sig.md5 = line.substr(a + 1, b - a - 1);
		sig.name = line.substr(b + 1);
		sigs.push_back(std::move(sig));
	}
	return sigs;
}
#endif

class TwinCheckJob;

Mutex g_mutex;
std::set<TwinCheckJob*> g_jobs;
std::set<int> g_checking;		// downloads whose fingerprint is being fetched
std::atomic<int> g_jobCount{0};
bool g_stopping = false;
// fetches of a posting's par2-file that came to nothing (its articles gone, or
// the servers busy): after MaxAttempts it's given up, not tried first forever
std::map<int, int> g_failedAttempts;
constexpr int MaxAttempts = 3;

class TwinCheckJob : public Thread
{
public:
	TwinCheckJob(int nzbId, std::string nzbFilename) :
		m_nzbId(nzbId), m_nzbFilename(std::move(nzbFilename)) {}
	/* sampling mode: the posting against the primary's */
	TwinCheckJob(int nzbId, std::string nzbFilename, int primaryId, std::string primaryNzbFilename) :
		m_nzbId(nzbId), m_nzbFilename(std::move(nzbFilename)), m_primaryId(primaryId),
		m_primaryNzbFilename(std::move(primaryNzbFilename)) {}

	void Cancel() { m_fetcher.Stop(); }
	int GetNzbId() const { return m_nzbId; }

protected:
	void Run() override;

private:
	int m_nzbId;
	std::string m_nzbFilename;
	int m_primaryId = 0;
	std::string m_primaryNzbFilename;
	ArticleFetcher m_fetcher;

	void Sample();
	void Store(const char* name, const char* value, const char* name2 = nullptr, const char* value2 = nullptr);

	/* the bytes of the posting's smallest par2-file; false: it has none, or
	 * none could be read (<fetched>: its articles were asked for) */
	bool IndexData(std::vector<char>& data, bool& fetched);
};

bool TwinCheckJob::IndexData(std::vector<char>& data, bool& fetched)
{
	fetched = false;
	std::vector<TwinCheck::NzbEntry> entries = TwinCheck::ReadNzbEntries(m_nzbFilename.c_str());

	// its smallest par2-file: every par2-file of a set holds the FileDesc packets
	const TwinCheck::NzbEntry* index = nullptr;
	for (const TwinCheck::NzbEntry& entry : entries)
	{
		if (entry.par2 && (!index || entry.size < index->size))
		{
			index = &entry;
		}
	}
	if (!index || index->size > TwinCheck::MaxIndexSize)
	{
		return false;
	}

	fetched = true;
	return TwinCheck::FetchEntry(m_fetcher, *index, TwinCheck::MaxIndexSize, [this]() { return IsStopped(); }, data);
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

	if (m_primaryId)
	{
		Sample();
		return;
	}

	std::vector<char> data;
	bool fetched = false;
	bool readable = IndexData(data, fetched);
	if (IsStopped())
	{
		return;
	}
	// parsed, kept with its file list and fingerprinted in Rust (twin.rs)
	std::string fingerprint;
#ifdef NZBGET_USE_RUST
	if (readable)
	{
		if (OpenStore())
		{
			fingerprint = RsString(nzbget_rs_twin_put_par2(m_nzbId, (const unsigned char*)data.data(), data.size()));
		}
	}
#endif
	bool known = !fingerprint.empty();
	if (!known && fetched)
	{
		// the par2-file's articles weren't there (gone, or the servers busy): asked
		// again at a later round, a few times
		Guard guard(g_mutex);
		if (++g_failedAttempts[m_nzbId] < MaxAttempts)
		{
			return;
		}
	}
	if (!known)
	{
		fingerprint = fetched ? "lost" : "none";
	}
	int files = known ? atoi(fingerprint.c_str() + fingerprint.rfind('-') + 1) : 0;

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
			nzbInfo->GetName(), fingerprint.c_str(), files);
		downloadQueue->HistoryChanged();
		downloadQueue->Save();
	}
}

void TwinCheckJob::Store(const char* name, const char* value, const char* name2, const char* value2)
{
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
		nzbInfo->GetParameters()->SetParameter(name, value);
		if (name2)
		{
			nzbInfo->GetParameters()->SetParameter(name2, value2);
		}
		downloadQueue->HistoryChanged();
		downloadQueue->Save();
	}
}

void TwinCheckJob::Sample()
{
	// the data files of both, by name: the same count, and article by article
	// the same sizes, or there's no telling by samples
	auto dataFiles = [](const std::string& nzbFilename)
		{
			std::vector<TwinCheck::NzbEntry> files;
			for (TwinCheck::NzbEntry& entry : TwinCheck::ReadNzbEntries(nzbFilename.c_str()))
			{
				if (!entry.par2)
				{
					files.push_back(std::move(entry));
				}
			}
			std::sort(files.begin(), files.end(), [](const TwinCheck::NzbEntry& a, const TwinCheck::NzbEntry& b)
				{ return (a.filename.empty() ? a.subject : a.filename) < (b.filename.empty() ? b.subject : b.filename); });
			return files;
		};
	std::vector<TwinCheck::NzbEntry> primary = dataFiles(m_primaryNzbFilename);
	std::vector<TwinCheck::NzbEntry> dupe = dataFiles(m_nzbFilename);
	std::string primaryId = std::to_string(m_primaryId);

	std::vector<std::pair<size_t, size_t>> places;	// file, segment
	bool sameLayout = !primary.empty() && primary.size() == dupe.size();
	for (size_t i = 0; sameLayout && i < primary.size(); i++)
	{
		sameLayout = primary[i].segments.size() == dupe[i].segments.size();
		for (size_t k = 0; sameLayout && k < primary[i].segments.size(); k++)
		{
			sameLayout = primary[i].segments[k].first == dupe[i].segments[k].first;
			places.emplace_back(i, k);
		}
	}
	if (!sameLayout || places.empty())
	{
		Store(TwinCheck::SampledParam, "none", TwinCheck::SampledOfParam, primaryId.c_str());
		return;
	}

	int compared = 0;
	int differ = 0;
	for (int n = 0; n < TwinCheck::SampleCount && !IsStopped(); n++)
	{
		const auto& place = places[((2 * n + 1) * places.size()) / (2 * TwinCheck::SampleCount)];
		const TwinCheck::NzbEntry& a = primary[place.first];
		const TwinCheck::NzbEntry& b = dupe[place.first];
		ArticleFetcher::FetchedArticle partA = m_fetcher.Fetch(a.segments[place.second].second.c_str(), a.groups);
		ArticleFetcher::FetchedArticle partB = m_fetcher.Fetch(b.segments[place.second].second.c_str(), b.groups);
		if (partA.Success && partB.Success)
		{
			compared++;
			differ += partA.Offset != partB.Offset || partA.Data != partB.Data;
		}
	}
	if (IsStopped() || (compared < TwinCheck::SampleCount / 2 && !differ))
	{
		return;	// too few arrived: asked again at a later round
	}
	Store(TwinCheck::SampledParam, differ ? "alt" : "twin", TwinCheck::SampledOfParam, primaryId.c_str());
}

struct Item
{
	NzbInfo* nzbInfo;
	bool queued;
	int rank;	// the queue first, then history newest first: who needs it soonest
};

}

#ifdef NZBGET_USE_RUST
std::vector<TwinCheck::NzbEntry> TwinCheck::ReadNzbEntries(const char* filename)
{
	// "F\tsize\tpar2\tfilename\tsubject", then its "G\tgroup" and "S\tbytes\tmessage-id" lines
	std::vector<NzbEntry> entries;
	std::istringstream lines(RsString(nzbget_rs_nzb_entries(filename)));
	std::string line;
	while (std::getline(lines, line))
	{
		if (line.size() < 2 || line[1] != '\t')
		{
			continue;
		}
		std::string rest = line.substr(2);
		if (line[0] == 'F')
		{
			NzbEntry entry;
			size_t a = rest.find('\t'), b = rest.find('\t', a + 1), c = rest.find('\t', b + 1);
			if (c == std::string::npos)
			{
				continue;
			}
			entry.size = atoll(rest.c_str());
			entry.par2 = rest[a + 1] == '1';
			entry.filename = rest.substr(b + 1, c - b - 1);
			entry.subject = rest.substr(c + 1);
			entries.push_back(std::move(entry));
		}
		else if (line[0] == 'G' && !entries.empty())
		{
			entries.back().groups.emplace_back(rest.c_str());
		}
		else if (line[0] == 'S' && !entries.empty())
		{
			size_t a = rest.find('\t');
			if (a != std::string::npos)
			{
				entries.back().segments.emplace_back(atoll(rest.c_str()), rest.substr(a + 1));
			}
		}
	}
	return entries;
}

uint64 TwinCheck::BlockSize(const char* data, size_t size)
{
	return nzbget_rs_par2_block_size((const unsigned char*)data, size);
}

int TwinCheck::VolumeBlocks(const std::string& filename)
{
	return nzbget_rs_par2_volume_blocks(filename.c_str());
}

std::vector<TwinCheck::FileSig> TwinCheck::ParsePar2(const char* data, size_t size)
{
	return SigLines(RsString(nzbget_rs_twin_par2_sigs((const unsigned char*)data, size)));
}

std::vector<TwinCheck::FileSig> TwinCheck::SigsOf(int nzbId)
{
	if (!OpenStore())
	{
		return {};
	}
	return SigLines(RsString(nzbget_rs_twin_sigs(nzbId)));
}

std::string TwinCheck::Kind(int primaryId, int dupeId)
{
	if (!OpenStore())
	{
		return "";
	}
	return RsString(nzbget_rs_twin_kind(primaryId, dupeId));
}

std::string TwinCheck::MatchByContent(int ownId, const char* target, const char* targetAlt, int donorId)
{
	if (!OpenStore())
	{
		return "";
	}
	return RsString(nzbget_rs_twin_match(ownId, target, targetAlt, donorId));
}

std::string TwinCheck::Fingerprint(const std::vector<FileSig>& sigs)
{
	std::string lines;
	for (const FileSig& sig : sigs)
	{
		lines += std::to_string(sig.length) + "\t" + sig.md5 + "\t" + sig.name + "\n";
	}
	return RsString(nzbget_rs_twin_fingerprint(lines.c_str()));
}
#else
// without the Rust parts there is no twin check (TwinCheck::Available() is false)
std::vector<TwinCheck::NzbEntry> TwinCheck::ReadNzbEntries(const char*) { return {}; }
uint64 TwinCheck::BlockSize(const char*, size_t) { return 0; }
int TwinCheck::VolumeBlocks(const std::string&) { return -1; }
std::vector<TwinCheck::FileSig> TwinCheck::ParsePar2(const char*, size_t) { return {}; }
std::vector<TwinCheck::FileSig> TwinCheck::SigsOf(int) { return {}; }
std::string TwinCheck::Kind(int, int) { return ""; }
std::string TwinCheck::MatchByContent(int, const char*, const char*, int) { return ""; }
std::string TwinCheck::Fingerprint(const std::vector<FileSig>&) { return ""; }
#endif

bool TwinCheck::FetchEntry(ArticleFetcher& fetcher, const NzbEntry& entry, int64 maxSize,
	const std::function<bool()>& stopped, std::vector<char>& data)
{
	data.clear();
	for (const auto& segment : entry.segments)
	{
		if (stopped())
		{
			return false;
		}
		ArticleFetcher::FetchedArticle part = fetcher.Fetch(segment.second.c_str(), entry.groups);
		if (!part.Success || part.Offset < 0 || part.Offset + (int64)part.Data.size() > maxSize)
		{
			// a lost article: what the others hold may still do
			continue;
		}
		if ((size_t)(part.Offset + part.Data.size()) > data.size())
		{
			data.resize((size_t)(part.Offset + part.Data.size()));
		}
		std::copy(part.Data.begin(), part.Data.end(), data.begin() + (size_t)part.Offset);
	}
	return !data.empty();
}

void TwinCheck::ServiceWork()
{
	if (!Available() || !g_Options->GetDupeCheck())
	{
		return;
	}

	struct Job
	{
		int nzbId;
		std::string nzbFilename;
		bool hinted;
		int primaryId = 0;			// sampling against this one
		std::string primaryNzbFilename;
		int rank = 0;				// of its dupe key: the queue first, then the newest history
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
				keys[keyOf(nzbInfo)].push_back({nzbInfo, true, 0});
			}
		}
		int rank = 0;
		for (std::unique_ptr<HistoryInfo>& historyInfo : *downloadQueue->GetHistory())
		{
			rank++;
			if (historyInfo->GetKind() == HistoryInfo::hkNzb && !keyOf(historyInfo->GetNzbInfo()).empty())
			{
				keys[keyOf(historyInfo->GetNzbInfo())].push_back({historyInfo->GetNzbInfo(), false, rank});
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
			size_t firstJob = jobs.size();
			int keyRank = INT_MAX;
			for (Item& item : items)
			{
				keyRank = std::min(keyRank, item.rank);
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

			// the labels: of the primary's twins and alts, by their par2 fingerprints,
			// else by articles sampled at the same places (none without either)
			std::string primaryPrint = primary ? fingerprintOf(primary) : "";
			bool primaryOk = primary && !strchr(primary->GetQueuedFilename(), '|') &&
				FileSystem::FileExists(primary->GetQueuedFilename());
			std::string primaryId = primary ? std::to_string(primary->GetId()) : "";
			for (Item& item : items)
			{
				NzbInfo* nzbInfo = item.nzbInfo;
				std::string print = fingerprintOf(nzbInfo);
				auto usable = [](const std::string& value) { return !value.empty() && value != "none" && value != "lost"; };
				bool byPar2 = usable(primaryPrint) && usable(print);
				bool sampleable = primaryOk && nzbInfo != primary && isDupe(item) && !print.empty() &&
					!primaryPrint.empty() && !byPar2;
				NzbParameter* sampled = nzbInfo->GetParameters()->Find(SampledParam);
				NzbParameter* sampledOf = nzbInfo->GetParameters()->Find(SampledOfParam);
				bool sampledNow = sampled && sampledOf && primaryId == sampledOf->GetValue();
				if (sampleable && !sampledNow && !strchr(nzbInfo->GetQueuedFilename(), '|') &&
					FileSystem::FileExists(nzbInfo->GetQueuedFilename()))
				{
					jobs.push_back({nzbInfo->GetId(), nzbInfo->GetQueuedFilename(), false,
						primary->GetId(), primary->GetQueuedFilename()});
				}
				// by the files of both par2 sets: a re-packed archive header (7z, rar) makes a
				// near-twin, most files the same; else by their fingerprints
				std::string kindText;
				if (nzbInfo != primary && isDupe(item) && byPar2)
				{
					std::string byFiles = Kind(primary->GetId(), nzbInfo->GetId());
					kindText = !byFiles.empty() ? byFiles : print == primaryPrint ? "twin" : "alt";
				}
				const char* kind = nzbInfo == primary || !isDupe(item) ? "" :
					byPar2 ? kindText.c_str() :
					sampleable && sampledNow && !strcmp(sampled->GetValue(), "twin") ? "twin" :
					sampleable && sampledNow && !strcmp(sampled->GetValue(), "alt") ? "alt" : "";
				NzbParameter* old = nzbInfo->GetParameters()->Find(KindParam);
				if (strcmp(old ? old->GetValue() : "", kind))
				{
					nzbInfo->GetParameters()->SetParameter(KindParam, kind);
					changed = true;
					if (*kind)
					{
						nzbInfo->PrintMessage(Message::mkInfo, "%s is %s%s of %s (%s)", nzbInfo->GetName(),
							*kind == 't' ? (strchr(kind, ':') ? "a near-twin (files the same: " : "a twin") : "an alt",
							strchr(kind, ':') ? (std::string(strchr(kind, ':') + 1) + ")").c_str() : "", primary->GetName(),
							!byPar2 ? (*kind == 't' ? "the articles sampled are identical" :
								"another encode: the articles sampled differ") :
							*kind == 't' ? "byte-identical files by their par2 checksums" :
							"another encode: its files' par2 checksums differ");
					}
				}
			}

			for (size_t i = firstJob; i < jobs.size(); i++)
			{
				jobs[i].rank = keyRank;
			}
		}

		if (changed)
		{
			downloadQueue->HistoryChanged();
			downloadQueue->Save();
		}
	}

	std::stable_sort(jobs.begin(), jobs.end(), [](const Job& a, const Job& b)
		{ return a.rank != b.rank ? a.rank < b.rank : a.hinted > b.hinted; });

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
		TwinCheckJob* thread = job.primaryId ?
			new TwinCheckJob(job.nzbId, job.nzbFilename, job.primaryId, job.primaryNzbFilename) :
			new TwinCheckJob(job.nzbId, job.nzbFilename);
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
