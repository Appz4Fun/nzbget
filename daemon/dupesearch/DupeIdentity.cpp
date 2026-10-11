#include "nzbget.h"

#include <atomic>
#include <thread>
#include "DupeIdentity.h"
#include "ArticleFetcher.h"
#include "DonorHealth.h"
#include "HttpGet.h"
#include "ReleaseName.h"
#include "Util.h"
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif

DupeIdentity::Identity DupeIdentity::FromArticle(const std::vector<char>& data, const std::string& name,
	unsigned long long total, unsigned long long minimum)
{
	Identity identity;
#ifdef NZBGET_USE_RUST
	NzbgetRsBuf raw = nzbget_rs_dupe_inner(data.data(), data.size(), name.data(), name.size(), total, minimum);
	if (raw.len >= 12)
	{
		const unsigned char* p = (const unsigned char*)raw.data;
		unsigned long long bytes = 0;
		for (int i = 0; i < 8; i++) bytes |= (unsigned long long)p[i] << (8 * i);
		size_t extensionSize = 0;
		for (int i = 0; i < 4; i++) extensionSize |= (size_t)p[8 + i] << (8 * i);
		if (extensionSize > 0 && extensionSize <= 4 && extensionSize <= raw.len - 12)
		{
			identity.bytes = bytes;
			identity.extension.assign(raw.data + 12, extensionSize);
			identity.name.assign(raw.data + 12 + extensionSize, raw.len - 12 - extensionSize);
		}
	}
	nzbget_rs_free(raw);
#endif
	return identity;
}

DupeIdentity::Identity DupeIdentity::Read(const NzbSummary& info, time_t deadline, const FetchFunc& fetch)
{
#ifdef NZBGET_USE_RUST
	std::vector<CString> groups;
	for (const std::string& group : info.groups) groups.emplace_back(group.c_str());
	unsigned long long minimum = info.dataBytes > 0 ?
		(unsigned long long)(info.dataBytes / 5) * 2 + (unsigned long long)(info.dataBytes % 5) * 2 / 5 : 0;
	for (const NzbSummary::Head& head : info.heads)
	{
		if (Util::CurrentTime() >= deadline || HttpGet::Stopped() || DonorHealth::Stopping()) break;
		ArticleFetcher fetcher;
		ArticleFetcher::FetchedArticle article;
		std::atomic<bool> done{false};
		std::string id = head.messageId;
		if (id.empty()) continue;
		if (id.front() != '<') id = "<" + id + ">";
		std::thread worker([&]() {
			try { article = fetch ? fetch(id, groups) : fetcher.Fetch(id.c_str(), groups); }
			catch (...) { article = ArticleFetcher::FetchedArticle(); }
			done = true;
		});
		while (!done && Util::CurrentTime() < deadline && !HttpGet::Stopped() && !DonorHealth::Stopping())
		{
			Util::Sleep(20);
		}
		if (!done) fetcher.Stop();
		worker.join();
		if (Util::CurrentTime() >= deadline || HttpGet::Stopped() || DonorHealth::Stopping()) break;
		if (article.Success && article.Offset == 0)
		{
			Identity found = FromArticle(article.Data, head.name,
				article.FileSize > 0 ? (unsigned long long)article.FileSize : 0, minimum);
			if (found) return found;
		}
	}
#endif
	return Identity();
}

bool DupeIdentity::SameData(const NzbSummary& a, const NzbSummary& b)
{
	if (a.dataBytes <= 0 || b.dataBytes <= 0 || a.dataFiles <= 0 || b.dataFiles <= 0) return false;
#ifdef NZBGET_USE_RUST
	return nzbget_rs_dupe_same_data((uint64_t)a.dataBytes, (uint32_t)a.dataFiles,
		(uint64_t)b.dataBytes, (uint32_t)b.dataFiles) != 0;
#else
	return a.dataBytes == b.dataBytes && a.dataFiles == b.dataFiles;
#endif
}

bool DupeIdentity::Candidate(const std::string& title, long long bytes, const std::string& name, long long size)
{
#ifdef NZBGET_USE_RUST
	return nzbget_rs_dupe_candidate(title.data(), title.size(), bytes > 0 ? bytes : 0,
		name.data(), name.size(), size > 0 ? size : 0) != 0;
#else
	return ReleaseName::SameRelease(title, name);
#endif
}

bool DupeIdentity::Matches(const std::string& title, const std::string& mainName,
	const Identity& mine, const Identity& theirs)
{
#ifdef NZBGET_USE_RUST
	NzbgetRsDupeIdentityInput a{ mine.bytes, mine.name.data(), mine.name.size(), mine.extension.data(), mine.extension.size() };
	NzbgetRsDupeIdentityInput b{ theirs.bytes, theirs.name.data(), theirs.name.size(), theirs.extension.data(), theirs.extension.size() };
	return nzbget_rs_dupe_lenient_ok(title.data(), title.size(), mainName.data(), mainName.size(),
		mine ? &a : nullptr, theirs ? &b : nullptr) != 0;
#else
	return ReleaseName::Readable(mainName) && ReleaseName::SameRelease(title, mainName);
#endif
}

std::vector<std::string> DupeIdentity::Hints(const NzbSummary& pick, const NzbSummary& donor, bool sameInner)
{
	std::vector<std::string> hints;
	if (SameData(pick, donor)) hints.emplace_back("DupeSameSize=1");
	if (sameInner) hints.emplace_back("DupeSameInner=1");
	return hints;
}
