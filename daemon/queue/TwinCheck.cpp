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

int Attempts(int nzbId)
{
	Guard guard(g_mutex);
	auto it = g_failedAttempts.find(nzbId);
	return it != g_failedAttempts.end() ? it->second : 0;
}

class TwinCheckJob : public Thread
{
public:
	TwinCheckJob(int nzbId, std::string nzbFilename, std::string posting) :
		m_nzbId(nzbId), m_nzbFilename(std::move(nzbFilename)), m_posting(std::move(posting)) {}
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
	std::string m_posting;	// the posting's own id (TwinCheck::Posting)
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
	// "fingerprint\tcomplete" from Rust (twin.rs), which keeps the file list
	std::string fingerprint;
	bool complete = false;
#ifdef NZBGET_USE_RUST
	if (readable && OpenStore())
	{
		std::string result = RsString(nzbget_rs_twin_put_par2(m_nzbId, m_posting.c_str(), (const unsigned char*)data.data(), data.size()));
		size_t tab = result.find('\t');
		fingerprint = result.substr(0, tab);
		complete = tab != std::string::npos && result.substr(tab + 1) == "1";
	}
#endif
	bool known = !fingerprint.empty();
	if (fetched && (!known || !complete))
	{
		// the par2-file's articles weren't all there (gone, or the servers busy):
		// asked again at a later round, a few times; a partial list is kept
		// meanwhile, and stays when the articles don't come
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

std::string TwinCheck::Posting(NzbInfo* nzbInfo)
{
	return std::to_string(nzbInfo->GetFullContentHash());
}

std::string TwinCheck::Identity(NzbInfo* nzbInfo)
{
	NzbParameter* print = nzbInfo->GetParameters()->Find(FilesParam);
	if (!print || Util::EmptyStr(print->GetValue()) || !strcmp(print->GetValue(), "none") ||
		!strcmp(print->GetValue(), "lost"))
	{
		return "";
	}
	return std::string(print->GetValue()) + "#" + Posting(nzbInfo);
}

int TwinCheck::HasSigs(int nzbId, const char* print)
{
	return OpenStore() ? nzbget_rs_twin_has(nzbId, print) : 0;
}

void TwinCheck::Prune(const std::string& live)
{
	if (OpenStore())
	{
		nzbget_rs_twin_prune(live.c_str());
	}
}

std::string TwinCheck::Kind(int primaryId, const char* primaryPrint, int dupeId, const char* dupePrint)
{
	if (!OpenStore())
	{
		return "";
	}
	return RsString(nzbget_rs_twin_kind(primaryId, primaryPrint, dupeId, dupePrint));
}

std::string TwinCheck::MatchByContent(int ownId, const char* ownPrint, const char* target, const char* targetAlt,
	int donorId, const char* donorPrint)
{
	if (!OpenStore())
	{
		return "";
	}
	return RsString(nzbget_rs_twin_match(ownId, ownPrint, target, targetAlt, donorId, donorPrint));
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
// Without the Rust parts the twin check (labels, content matching) doesn't run,
// but par-repair with a twin's par2 set (Repair.cpp) works as before: these
// are the C++ helpers it had, kept for builds without cargo.
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

std::string XmlText(std::string text)
{
	static const std::pair<const char*, const char*> entities[] =
		{ {"&lt;", "<"}, {"&gt;", ">"}, {"&quot;", "\""}, {"&apos;", "'"}, {"&amp;", "&"} };
	for (const auto& entity : entities)
	{
		for (size_t at = text.find(entity.first); at != std::string::npos; at = text.find(entity.first, at + 1))
		{
			text.replace(at, strlen(entity.first), entity.second);
		}
	}
	return text;
}

}

std::vector<TwinCheck::NzbEntry> TwinCheck::ReadNzbEntries(const char* filename)
{
	std::vector<NzbEntry> entries;
	std::ifstream in(fs::u8path(filename), std::ios::binary);
	std::string xml((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
	size_t pos = 0;
	while ((pos = xml.find("<file", pos)) != std::string::npos)
	{
		size_t end = xml.find("</file>", pos);
		if (end == std::string::npos)
		{
			break;
		}
		std::string file = xml.substr(pos, end - pos);
		pos = end + 7;

		NzbEntry entry;
		size_t at = file.find("subject=\"");
		if (at != std::string::npos)
		{
			size_t close = file.find('"', at + 9);
			entry.subject = XmlText(file.substr(at + 9, close == std::string::npos ? 0 : close - at - 9));
		}
		size_t open = entry.subject.find('"');
		size_t close = open == std::string::npos ? std::string::npos : entry.subject.find('"', open + 1);
		if (close != std::string::npos)
		{
			entry.filename = entry.subject.substr(open + 1, close - open - 1);
			// a name, not a path
			std::replace(entry.filename.begin(), entry.filename.end(), '/', '_');
			std::replace(entry.filename.begin(), entry.filename.end(), '\\', '_');
		}
		for (at = file.find("<group>"); at != std::string::npos; at = file.find("<group>", at + 1))
		{
			size_t groupEnd = file.find("</group>", at);
			if (groupEnd != std::string::npos)
			{
				entry.groups.emplace_back(XmlText(file.substr(at + 7, groupEnd - at - 7)).c_str());
			}
		}
		for (at = file.find("<segment"); at != std::string::npos; at = file.find("<segment", at + 1))
		{
			size_t bodyStart = file.find('>', at);
			size_t segmentEnd = file.find("</segment>", at);
			if (bodyStart == std::string::npos || segmentEnd == std::string::npos || bodyStart > segmentEnd)
			{
				continue;
			}
			std::string tag = file.substr(at, bodyStart - at);
			size_t bytesAt = tag.find("bytes=\"");
			int64 bytes = bytesAt != std::string::npos ? atoll(tag.c_str() + bytesAt + 7) : 0;
			std::string id = XmlText(file.substr(bodyStart + 1, segmentEnd - bodyStart - 1)).substr(0, 1000);
			// it goes into NNTP commands as is (see NzbFile): no line breaks, spaces
			// or control characters
			for (char& c : id)
			{
				if ((unsigned char)c <= ' ' || c == 0x7f)
				{
					c = '_';
				}
			}
			entry.segments.emplace_back(bytes, "<" + id + ">");
			entry.size += bytes;
		}
		if (!entry.segments.empty())
		{
			std::string name = entry.filename.empty() ? entry.subject : entry.filename;
			std::transform(name.begin(), name.end(), name.begin(), ::tolower);
			entry.par2 = name.find(".par2") != std::string::npos;
			entries.push_back(std::move(entry));
		}
	}
	return entries;
}

uint64 TwinCheck::BlockSize(const char* data, size_t size)
{
	const uchar* p = (const uchar*)data;
	for (size_t pos = 0; pos + 64 + 8 <= size; pos += 4)
	{
		if (!memcmp(p + pos, "PAR2\0PKT", 8) && !memcmp(p + pos + 48, "PAR 2.0\0Main\0\0\0\0", 16))
		{
			return ReadLe64(p + pos + 64);
		}
	}
	return 0;
}

int TwinCheck::VolumeBlocks(const std::string& filename)
{
	std::string name = filename;
	std::transform(name.begin(), name.end(), name.begin(), ::tolower);
	size_t at = name.rfind(".vol");
	if (at == std::string::npos)
	{
		return -1;
	}
	size_t plus = name.find('+', at);
	if (plus == std::string::npos || !isdigit((uchar)name[plus + 1]))
	{
		return -1;
	}
	return atoi(name.c_str() + plus + 1);
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

std::string TwinCheck::Posting(NzbInfo*) { return ""; }
std::string TwinCheck::Identity(NzbInfo*) { return ""; }
int TwinCheck::HasSigs(int, const char*) { return 0; }
void TwinCheck::Prune(const std::string&) {}
std::string TwinCheck::Kind(int, const char*, int, const char*) { return ""; }
std::string TwinCheck::MatchByContent(int, const char*, const char*, const char*, int, const char*) { return ""; }

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
		std::string posting;		// the posting's own id (fingerprint jobs)
		int rank = 0;				// of its dupe key: the queue first, then the newest history
	};
	std::vector<Job> jobs;
	// the stored file lists are pruned to the postings still there, hourly
	std::string live;
	// (not while a fingerprint job runs: it may store a list its posting doesn't
	// carry the fingerprint of yet)
	static time_t lastPrune = 0;
	bool prune = Util::CurrentTime() - lastPrune >= 60 * 60 && g_jobCount == 0;
	{
		GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
		if (prune)
		{
			lastPrune = Util::CurrentTime();
			auto add = [&live](NzbInfo* nzbInfo)
				{
					std::string identity = Identity(nzbInfo);
					if (!identity.empty())
					{
						live += std::to_string(nzbInfo->GetId()) + "\t" + identity + "\n";
					}
				};
			for (NzbInfo* nzbInfo : downloadQueue->GetQueue())
			{
				add(nzbInfo);
			}
			for (std::unique_ptr<HistoryInfo>& historyInfo : *downloadQueue->GetHistory())
			{
				if (historyInfo->GetKind() == HistoryInfo::hkNzb)
				{
					add(historyInfo->GetNzbInfo());
				}
			}
			// nothing in queue and history: the whole store goes
			if (live.empty())
			{
				live = "\n";
			}
		}
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
			// merged downloads (their nzb-file is two) aren't compared: no fingerprint
			// stands for them
			items.erase(std::remove_if(items.begin(), items.end(),
				[](const Item& item) { return strchr(item.nzbInfo->GetQueuedFilename(), '|') != nullptr; }),
				items.end());
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
				// and so do those whose file list isn't stored (a fingerprint from
				// before the lists were kept, or the store file lost)
				std::string print = fingerprintOf(nzbInfo);
				bool listless = print != "none" && print != "lost" && !print.empty() &&
					HasSigs(nzbInfo->GetId(), Identity(nzbInfo).c_str()) < 2 && Attempts(nzbInfo->GetId()) < MaxAttempts;
				if ((print.empty() || listless) && !strchr(nzbInfo->GetQueuedFilename(), '|') &&
					FileSystem::FileExists(nzbInfo->GetQueuedFilename()))
				{
					// the dupe tool's hints of a twin go first; they prove nothing
					bool hinted = nzbInfo->GetParameters()->Find("DupeSameSize") ||
						nzbInfo->GetParameters()->Find("DupeSameInner");
					Job job{nzbInfo->GetId(), nzbInfo->GetQueuedFilename(), hinted};
					job.posting = Posting(nzbInfo);
					jobs.push_back(std::move(job));
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
					std::string byFiles = Kind(primary->GetId(), Identity(primary).c_str(), nzbInfo->GetId(),
						Identity(nzbInfo).c_str());
					// no lists at all (fingerprints from before they were kept): the
					// fingerprints decide; a partial list leaves it unknown
					bool listed = HasSigs(primary->GetId(), Identity(primary).c_str()) > 0 ||
						HasSigs(nzbInfo->GetId(), Identity(nzbInfo).c_str()) > 0;
					kindText = !byFiles.empty() || listed ? byFiles : print == primaryPrint ? "twin" : "alt";
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

	if (!live.empty())
	{
		Guard guard(g_mutex);
		// a job started since the snapshot: next time (Prune runs under g_mutex,
		// which a new job registers under)
		if (g_jobs.empty())
		{
			Prune(live);
		}
		else
		{
			lastPrune = 0;
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
			new TwinCheckJob(job.nzbId, job.nzbFilename, job.posting);
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
