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
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */


#include "nzbget.h"

#include <chrono>
#include <limits>
#include <fstream>
#include <sstream>
#include "DupeSearch.h"
#include "DupeIdentity.h"
#include "DonorHealth.h"
#include "DonorScore.h"
#include "NntpHealthServer.h"
#include "Scanner.h"
#include "HttpGet.h"
#include "Newznab.h"
#include "NzbReader.h"
#include "Posting.h"
#include "DupeUtil.h"
#include <algorithm>
#include <thread>
#include "ReleaseName.h"
#include "FileSystem.h"
#include "Log.h"
#include "Options.h"
#include "Util.h"
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif

DupeSearch* g_DupeSearch = nullptr;

namespace
{
// a download by id, in the queue or else in history
NzbInfo* FindNzb(DownloadQueue* downloadQueue, int nzbId)
{
	if (NzbInfo* nzbInfo = downloadQueue->GetQueue()->Find(nzbId))
	{
		return nzbInfo;
	}
	for (HistoryInfo* historyInfo : downloadQueue->GetHistory())
	{
		if (historyInfo->GetKind() == HistoryInfo::hkNzb && historyInfo->GetNzbInfo()->GetId() == nzbId)
		{
			return historyInfo->GetNzbInfo();
		}
	}
	return nullptr;
}


std::string LowerKey(const std::string& key)
{
	std::string out = key;
	for (char& ch : out)
	{
		ch = (char)tolower((unsigned char)ch);
		if (ch == '\t' || ch == '\n' || ch == '\r')
		{
			ch = ' ';
		}
	}
	return out;
}

// the key a download is searched under: its own, or one made from its name
std::string EffectiveKey(NzbInfo* nzbInfo)
{
	if (!Util::EmptyStr(nzbInfo->GetDupeKey()))
	{
		return nzbInfo->GetDupeKey();
	}
	return DupeSearch::MakeDupeKey(nzbInfo->GetName());
}

}

std::string DupeSearch::MakeDupeKey(const std::string& name)
{
	return "dupes:" + ReleaseName::Normalize(name);
}

bool DupeSearch::IsDonor(NzbInfo* nzbInfo)
{
	return nzbInfo->GetParameters()->Find(DonorParam) || nzbInfo->GetParameters()->Find(AliveParam);
}

DupeSearch::DupeSearch()
{
	HttpGet::Reset();
	DonorHealth::Reset();
	m_observer.m_owner = this;
	DownloadQueue::Guard()->Attach(&m_observer);
}

DupeSearch::~DupeSearch()
{
	debug("Destroying DupeSearch");
	// the queue (QueueCoordinator's) outlives this, and would notify freed memory
	DownloadQueue::Guard()->Detach(&m_observer);
}

void DupeSearch::Stop()
{
	Thread::Stop();
	HttpGet::StopAll();
	DonorHealth::StopAll();
	std::lock_guard<std::mutex> guard(m_mutex);
	m_cond.notify_all();
}

void DupeSearch::NotifyNameChanged(int nzbId)
{
    if (g_Options->GetDupeSearch() && !IsStopped())
        Schedule(nzbId, Util::CurrentTime() + g_Options->GetDupeSearchDelay());
}

void DupeSearch::DownloadQueueUpdate(DownloadQueue* downloadQueue, void* aspect)
{
	DownloadQueue::Aspect* queueAspect = (DownloadQueue::Aspect*)aspect;
	if ((queueAspect->action == DownloadQueue::eaNzbAdded || queueAspect->action == DownloadQueue::eaNzbNamed) && queueAspect->nzbInfo &&
		g_Options->GetDupeSearch() && !IsStopped())
	{
		Schedule(queueAspect->nzbInfo->GetId(), Util::CurrentTime() + g_Options->GetDupeSearchDelay());
#ifdef NZBGET_USE_RUST
        // An external lower-scored backup can arrive after the initial search.
        // Queue notifications run under the queue lock; only schedule work here.
        NzbInfo* added = queueAspect->nzbInfo;
        if (queueAspect->action == DownloadQueue::eaNzbAdded && !IsDonor(added) &&
            added->GetDupeMode() == dmScore && !Util::EmptyStr(added->GetDupeKey()) &&
            !added->GetParameters()->Find("DupeFleet"))
        {
            NzbInfo* parent = nullptr;
            for (NzbInfo* item : downloadQueue->GetQueue())
                if (item != added && item->GetKind() == NzbInfo::nkNzb && !item->GetDeleting() &&
                    item->GetDeleteStatus() == NzbInfo::dsNone && !item->GetPostInfo() &&
                    LowerKey(EffectiveKey(item)) == LowerKey(EffectiveKey(added)) &&
                    item->GetDupeScore() > added->GetDupeScore() &&
                    (!parent || item->GetDupeScore() > parent->GetDupeScore())) parent = item;
            if (parent)
            {
                std::lock_guard<std::mutex> guard(m_mutex);
                m_rankPending.insert(parent->GetId());
                m_pending[parent->GetId()] = Util::CurrentTime() + g_Options->GetDupeSearchDelay();
                m_cond.notify_all();
            }
        }
#endif
	}
}

void DupeSearch::Schedule(int nzbId, time_t due)
{
	std::lock_guard<std::mutex> guard(m_mutex);
	m_pending[nzbId] = due;
	m_cond.notify_all();
}

// an event isn't fired for a download that was queued before a restart; nor for
// a pick that failed over while nzbget was stopping or starting (B64): one that
// failed lately is asked again (Prepare searches it from history once, unless
// its key was searched already)
void DupeSearch::ScanQueue()
{
	std::vector<int> ids;
	{
		GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
		for (NzbInfo* nzbInfo : downloadQueue->GetQueue())
		{
			if (nzbInfo->GetKind() == NzbInfo::nkNzb)
			{
				ids.push_back(nzbInfo->GetId());
			}
		}
		time_t recent = Util::CurrentTime() - RecentFailureSec;
		for (HistoryInfo* historyInfo : downloadQueue->GetHistory())
		{
			if (historyInfo->GetKind() == HistoryInfo::hkNzb && historyInfo->GetTime() >= recent &&
				!historyInfo->GetNzbInfo()->IsDupeSuccess())
			{
				ids.push_back(historyInfo->GetNzbInfo()->GetId());
			}
		}
	}
	for (int id : ids)
	{
		Schedule(id, Util::CurrentTime() + g_Options->GetDupeSearchDelay());
	}
}

void DupeSearch::Run()
{
	debug("Entering DupeSearch-loop");

	while (!DownloadQueue::IsLoaded() && !IsStopped())
	{
		Util::Sleep(20);
	}
	if (IsStopped())
	{
		return;
	}

	LoadState();
	m_fetcher.SetStatePath(std::string(g_Options->GetQueueDir()) + PATH_SEPARATOR + "dupesearch-indexers");
	m_fetcher.Load();
	m_dead.SetStatePath(std::string(g_Options->GetQueueDir()) + PATH_SEPARATOR + "dupesearch-dead");
	m_dead.Load();
	if (g_Options->GetDupeSearch())
	{
		ResumePending();
		ScanQueue();
	}

	while (!IsStopped())
	{
		std::vector<int> due;
		{
			std::unique_lock<std::mutex> lock(m_mutex);
			m_cond.wait_for(lock, std::chrono::milliseconds(500));
			time_t now = Util::CurrentTime();
			for (auto it = m_pending.begin(); it != m_pending.end();)
			{
				if (it->second <= now)
				{
					due.push_back(it->first);
					it = m_pending.erase(it);
				}
				else
				{
					++it;
				}
			}
		}

		for (int nzbId : due)
		{
			if (IsStopped())
			{
				break;
			}
			Job job;
			bool search;
			{
				GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
				search = Prepare(downloadQueue, nzbId, job);
			}
			if (search)
			{
				MarkSearching(job.nzbId);
				Search(job);
			}
		}
	}

	// a health check's walkers may still be in a request: they end before this
	// thread does, so before the server pool goes away
	DonorHealth::WaitAll();
	debug("Exiting DupeSearch-loop");
}

/*
 * Decides whether a download is searched now. Runs under the queue lock.
 */
bool DupeSearch::Prepare(DownloadQueue* downloadQueue, int nzbId, Job& job)
{
#ifdef NZBGET_USE_RUST
    return PrepareNative(downloadQueue, nzbId, job);
#else
	if (!g_Options->GetDupeSearch() || !g_Options->GetDupeCheck())
	{
		return false;
	}

	// gone from the queue: a backup that the duplicate check filed in history,
	// a download that was deleted, or one that already failed (B56: dead within
	// DupeSearchDelay, it failed over before its search was due). A failed one is
	// searched from history: its key's backups may not be enough.
	NzbInfo* nzbInfo = downloadQueue->GetQueue()->Find(nzbId);
	bool failed = false;
	if (!nzbInfo)
	{
		for (HistoryInfo* historyInfo : downloadQueue->GetHistory())
		{
			if (historyInfo->GetKind() == HistoryInfo::hkNzb && historyInfo->GetNzbInfo()->GetId() == nzbId)
			{
				NzbInfo* item = historyInfo->GetNzbInfo();
				NzbInfo::EDeleteStatus status = item->GetDeleteStatus();
				if (!item->IsDupeSuccess() && status != NzbInfo::dsManual && status != NzbInfo::dsDupe &&
					status != NzbInfo::dsCopy && status != NzbInfo::dsGood)
				{
					nzbInfo = item;
					failed = true;
				}
				break;
			}
		}
	}
	if (!nzbInfo || nzbInfo->GetKind() != NzbInfo::nkNzb)
	{
		return false;
	}

	if (!failed)
	{
		if (nzbInfo->GetDeleting() || nzbInfo->GetDeleteStatus() != NzbInfo::dsNone)
		{
			return false;
		}
		// in post-processing: asked again once it is done (searched if it failed)
		if (nzbInfo->GetPostInfo())
		{
			Schedule(nzbId, Util::CurrentTime() + std::max(PostProcessRetrySec, g_Options->GetDupeSearchDelay()));
			return false;
		}
	}

	// the score decides which of several duplicates is the main one; a
	// download that bypasses duplicate handling can't be managed
	if (nzbInfo->GetDupeMode() != dmScore)
	{
		return false;
	}

	// a duplicate this search (or the proxy) queued; a promotion from history
	// after a failover: its key was searched for the pick
	if (IsDonor(nzbInfo) || nzbInfo->GetDupeHint() == NzbInfo::dhRedownloadAuto)
	{
		return false;
	}

	std::string key = EffectiveKey(nzbInfo);
	std::string lowerKey = LowerKey(key);

	// the top-scored item of its key only (a submitter's backups, scored a
	// little lower, are filed in history shortly after they are added)
	for (NzbInfo* other : downloadQueue->GetQueue())
	{
		if (other != nzbInfo && other->GetKind() == NzbInfo::nkNzb && !other->GetDeleting() &&
			other->GetDeleteStatus() == NzbInfo::dsNone && LowerKey(EffectiveKey(other)) == lowerKey &&
			other->GetDupeScore() > nzbInfo->GetDupeScore())
		{
			nzbInfo->PrintMessage(Message::mkInfo, "DupeSearch: %s is not searched: %s scores higher under its key",
				nzbInfo->GetName(), other->GetName());
			return false;
		}
	}

	int pickScore = std::max(nzbInfo->GetDupeScore(), BasePickScore);
	time_t now = Util::CurrentTime();
	{
		std::lock_guard<std::mutex> guard(m_mutex);
		auto it = m_searched.find(lowerKey);
		if (it != m_searched.end() && now - it->second.time < SearchWindowSec && it->second.score >= pickScore)
		{
			return false;
		}
		m_searched[lowerKey] = { pickScore, now };
	}
	// a dry run's search is remembered in memory only: written down, it would hold
	// off the real search for SearchWindowSec once the dry run is switched off
	if (!g_Options->GetDupeSearchDryRun())
	{
		SaveState();
	}

	// a managed pick: it has a key and a score that leave room below it for
	// duplicates (they score pick - 1000 + 2..90). One in history keeps both: the
	// duplicates are placed by the job's score, and a failed item isn't fetched again.
	bool changed = false;
	bool edit = !g_Options->GetDupeSearchDryRun() && !failed;
	if (edit && Util::EmptyStr(nzbInfo->GetDupeKey()))
	{
		nzbInfo->SetDupeKey(key.c_str());
		changed = true;
	}
	if (edit && nzbInfo->GetDupeScore() < BasePickScore)
	{
		nzbInfo->SetDupeScore(BasePickScore);
		changed = true;
	}
	if (changed)
	{
		downloadQueue->SaveChanged();
	}

	Collect(downloadQueue, nzbInfo, job);
	job.score = pickScore;
	nzbInfo->PrintMessage(Message::mkInfo, "DupeSearch: searching duplicates of %s (key %s)%s",
		nzbInfo->GetName(), key.c_str(), failed ? ": it failed before its search was due" : "");
	return true;
#endif
}

bool DupeSearch::PrepareNative(DownloadQueue* downloadQueue, int nzbId, Job& job)
{
#ifdef NZBGET_USE_RUST
    if (!g_Options->GetDupeSearch() || !g_Options->GetDupeCheck()) return false;
    NzbInfo* pick = FindNzb(downloadQueue, nzbId);
    if (!pick) { std::lock_guard<std::mutex> guard(m_mutex); m_rankPending.erase(nzbId); return false; }
    bool history = downloadQueue->GetQueue()->Find(nzbId) != pick;
    std::string key = EffectiveKey(pick);
    std::string lowerKey = LowerKey(key);
    std::string title;
    Searched previous;
    bool havePrevious = false, changedIdentity = false, rankOnly = false, cachedName = false;
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        auto found = m_searched.find(lowerKey);
        if (found != m_searched.end()) {
            previous = found->second;
            havePrevious = true;
            cachedName = !previous.title.empty() && previous.rawName == pick->GetName();
        }
        rankOnly = m_rankPending.erase(nzbId) != 0 && havePrevious;
    }
    title = cachedName ? previous.title :
        Util::EmptyStr(pick->GetDupeKey()) ? key.substr(6) : ReleaseName::Normalize(pick->GetName());
    changedIdentity = havePrevious && !previous.title.empty() && previous.title != title;
    if (havePrevious && !changedIdentity && !cachedName && !previous.title.empty())
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        auto found = m_searched.find(lowerKey);
        if (found != m_searched.end() && found->second.title == title) found->second.rawName = pick->GetName();
    }
    if (changedIdentity) rankOnly = false;
    // Only rewrite a key this search previously generated; explicit client keys stay.
    if (changedIdentity && key == "dupes:" + previous.title)
    {
        key = "dupes:" + title;
        lowerKey = LowerKey(key);
        // The key remains a snapshot until the Rust policy accepts the job.
        havePrevious = false;
    }
    auto flags = [&](NzbInfo* item, bool inHistory) -> uint32_t {
        uint32_t value = rsDupeEnabled | rsDupeCheck | rsDupePresent;
        if (item->GetKind() == NzbInfo::nkNzb) value |= rsDupeNzb;
        if (inHistory) value |= rsDupeHistory;
        if (item->IsDupeSuccess()) value |= rsDupeSuccess;
        if (item->GetDeleting()) value |= rsDupeDeleting;
        if (item->GetDeleteStatus() == NzbInfo::dsNone) value |= rsDupeDeleteNone;
        if (item->GetDeleteStatus() == NzbInfo::dsManual) value |= rsDupeDeleteManual;
        if (item->GetDeleteStatus() == NzbInfo::dsDupe) value |= rsDupeDeleteDupe;
        if (item->GetDeleteStatus() == NzbInfo::dsCopy) value |= rsDupeDeleteCopy;
        if (item->GetDeleteStatus() == NzbInfo::dsGood) value |= rsDupeDeleteGood;
        if (item->GetPostInfo()) value |= rsDupePostProcess;
        if (item->GetDupeMode() == dmScore) value |= rsDupeScoreMode;
        if (IsDonor(item)) value |= rsDupeDonor;
        if (item->GetDupeHint() == NzbInfo::dhRedownloadAuto) value |= rsDupeAutoRedownload;
        if (item->GetParameters()->Find("DupeFleet")) value |= rsDupeManagedFleet;
        return value;
    };
    uint32_t pickFlags = flags(pick, history);
    time_t now = Util::CurrentTime();
    NzbgetRsDupeWatchPeer snapshot{ nzbId, pick->GetDupeScore(), pickFlags, lowerKey.data(), lowerKey.size() };
    if (cachedName && havePrevious && !previous.retryable && !rankOnly)
    {
        // A known unchanged title can be suppressed before building snapshots.
        // Any higher peer/fleet could only suppress it too; a Search still needs
        // the complete peer check below. Post-process retry precedes peer rules.
        int preliminary = nzbget_rs_dupe_watch(&snapshot, nullptr, 0, (int64_t)now,
            previous.score, (int64_t)previous.time, true, false);
        if (preliminary == 0) return false;
        if (preliminary == 1) {
            Schedule(nzbId, now + std::max(PostProcessRetrySec, g_Options->GetDupeSearchDelay()));
            return false;
        }
    }
    std::vector<NzbInfo*> others;
    std::vector<bool> histories;
    auto retain = [&](NzbInfo* item, bool inHistory) {
        // Lower/equal ordinary peers cannot affect the Rust highest-score rule.
        // Fleet markers still matter at any score, including history entries.
        if (item != pick && (item->GetDupeScore() > pick->GetDupeScore() || item->GetParameters()->Find("DupeFleet")))
        { others.push_back(item); histories.push_back(inHistory); }
    };
    for (NzbInfo* item : downloadQueue->GetQueue()) retain(item, false);
    for (HistoryInfo* item : downloadQueue->GetHistory()) if (item->GetKind() == HistoryInfo::hkNzb)
        retain(item->GetNzbInfo(), true);
    std::vector<std::string> keys;
    keys.reserve(others.size());
    for (NzbInfo* other : others) keys.push_back(LowerKey(EffectiveKey(other)));
    std::vector<NzbgetRsDupeWatchPeer> peers;
    for (size_t i = 0; i < others.size(); i++)
    {
        uint32_t f = flags(others[i], histories[i]);
        if (keys[i] == lowerKey && (f & rsDupeManagedFleet)) pickFlags |= rsDupeManagedFleet;
        peers.push_back({ others[i]->GetId(), others[i]->GetDupeScore(), f, keys[i].data(), keys[i].size() });
    }
    snapshot.flags = pickFlags;
    int decision = nzbget_rs_dupe_watch(&snapshot, peers.data(), peers.size(), (int64_t)now,
        previous.score, (int64_t)previous.time, havePrevious && !previous.retryable && !rankOnly, changedIdentity);
    if (decision == 1) {
        if (rankOnly) { std::lock_guard<std::mutex> guard(m_mutex); m_rankPending.insert(nzbId); }
        Schedule(nzbId, now + std::max(PostProcessRetrySec, g_Options->GetDupeSearchDelay()));
        return false;
    }
    if (decision != 2) return false;
    int score = std::max(pick->GetDupeScore(), BasePickScore);
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        if (!rankOnly) m_searched[lowerKey] = { score, now, title, false, pick->GetName() };
    }
    if (!g_Options->GetDupeSearchDryRun() && !rankOnly) SaveState();
    bool edit = !g_Options->GetDupeSearchDryRun() && !history;
    if (edit)
    {
        pick->SetDupeKey(key.c_str());
        if (pick->GetDupeScore() < BasePickScore) pick->SetDupeScore(BasePickScore);
        pick->SetChanged(true);
        downloadQueue->SaveChanged();
    }
    job.rankOnly = rankOnly;
    Collect(downloadQueue, pick, job);
    job.dupeKey = key;
    job.score = score;
    job.failed = history;
    job.rankOnly = rankOnly;
    pick->PrintMessage(Message::mkInfo, "DupeSearch: searching duplicates of %s (key %s)%s",
        pick->GetName(), key.c_str(), rankOnly ? ": ranking new backups" : history ? ": it failed before its search was due" : "");
    return true;
#else
    return false;
#endif
}

/*
 * What a search of a pick needs to know of the queue and history. Runs under the queue lock.
 */
void DupeSearch::Collect(DownloadQueue* downloadQueue, NzbInfo* nzbInfo, Job& job)
{
	std::string key = EffectiveKey(nzbInfo);
	std::string lowerKey = LowerKey(key);
	job.nzbId = nzbInfo->GetId();
	job.name = nzbInfo->GetName();
	job.dupeKey = key;
	job.category = nzbInfo->GetCategory();
	job.queuedFile = nzbInfo->GetQueuedFilename() ? nzbInfo->GetQueuedFilename() : "";

	// the nzb-files nzbget keeps for this release: queue and history items
	// with this duplicate key, or whose name is the same release
	auto addKnown = [&](NzbInfo* item)
	{
		// one the user deleted is no duplicate nzbget would fetch: its posting may
		// be found and added again (B41)
		if (item->GetKind() != NzbInfo::nkNzb || Util::EmptyStr(item->GetQueuedFilename()) ||
			item->GetDeleteStatus() == NzbInfo::dsManual)
		{
			return;
		}
		if (LowerKey(EffectiveKey(item)) == lowerKey || ReleaseName::SameRelease(nzbInfo->GetName(), item->GetName()))
		{
			// the file of a merged group names several, separated by "|"
			std::stringstream names(item->GetQueuedFilename());
			std::string name;
			while (std::getline(names, name, '|'))
			{
				job.knownFiles.push_back(name);
			}
		}
	};
	for (NzbInfo* item : downloadQueue->GetQueue())
	{
		addKnown(item);
        // Zero-delay ranking can precede asynchronous duplicate filing. The
        // score editor handles either live or history IDs, so include that
        // snapshot rather than losing the only add notification.
        if (job.rankOnly && item != nzbInfo && item->GetKind()==NzbInfo::nkNzb &&
            item->GetDupeMode()==dmScore && !item->GetPostInfo() &&
            (item->GetDeleteStatus()==NzbInfo::dsNone || item->GetDeleteStatus()==NzbInfo::dsDupe) &&
            item->GetDupeScore()<nzbInfo->GetDupeScore() && LowerKey(EffectiveKey(item))==lowerKey &&
            ReleaseName::SameRelease(nzbInfo->GetName(),item->GetName()) &&
            !Util::EmptyStr(item->GetQueuedFilename()) && !strchr(item->GetQueuedFilename(),'|'))
        {
            job.members.emplace_back(item->GetId(),item->GetQueuedFilename());
            job.memberScores.push_back(item->GetDupeScore());
        }
	}
	for (HistoryInfo* historyInfo : downloadQueue->GetHistory())
	{
		if (historyInfo->GetKind() == HistoryInfo::hkNzb)
		{
			NzbInfo* item = historyInfo->GetNzbInfo();
			addKnown(item);
			// the same release only: a client's key can be broad (one key for two editions);
			// a copy (an nzb-file sent again) too, unless it is a copy of the pick
			bool backup = item->GetDeleteStatus() == NzbInfo::dsDupe ||
				(item->GetDeleteStatus() == NzbInfo::dsCopy && item->GetFullContentHash() != nzbInfo->GetFullContentHash());
			if (item != nzbInfo && backup && LowerKey(EffectiveKey(item)) == lowerKey &&
				ReleaseName::SameRelease(nzbInfo->GetName(), item->GetName()) &&
				!Util::EmptyStr(item->GetQueuedFilename()) && !strchr(item->GetQueuedFilename(), '|'))
			{
				job.members.emplace_back(item->GetId(), item->GetQueuedFilename());
				job.memberScores.push_back(item->GetDupeScore());
			}
		}
	}
}

void DupeSearch::Expand(const Job& job, const NzbSummary& pick, const std::vector<Newznab::Result>& prior,
    time_t deadline, NzbFetcher::Budget& budget, std::vector<NzbFetcher::Fetched>& fetched,
    std::set<std::string>& attempted, NzbFetcher::Stats& stats, Newznab::SearchStats& queryStats, int& results, int& candidates, int& postings)
{
#ifdef NZBGET_USE_RUST
    if (IsStopped() || budget.Spent() || Util::CurrentTime()>=deadline || pick.messageIds.empty()) return;
    auto servers=NntpHealthServer::Servers();
    if (servers.empty()) return;
    auto healthOptions = [&]() {
        DonorHealth::Options options;
        options.sample.percent=g_Options->GetDupeHealthPercent();
        options.sample.minimum=g_Options->GetDupeHealthMin();
        options.sample.maximum=g_Options->GetDupeHealthMax();
        options.sample.maxBody=g_Options->GetDupeBodyChecks();
        options.budgetMs=(int)std::max(1LL,std::min((long long)g_Options->GetDupeHealthBudget()*1000,
            (long long)(deadline-Util::CurrentTime())*1000));
        return options;
    };
    auto check = [&](const NzbSummary& info) {
        return DonorHealth::CheckPosting(servers,info.messageIds,
            std::make_shared<std::vector<std::string>>(info.groups),healthOptions(),true);
    };
    DonorHealth::Health health;
    double alive=-1;
    bool doomed=false;
    int missing=0;
    if (!job.failed)
    {
        health=check(pick);
        alive=DupeIdentity::Alive(health,pick);
        long long combined=(long long)health.missing+DupeIdentity::UnlistedMissing(health,pick);
        missing=(int)std::min(combined,(long long)std::numeric_limits<int>::max());
        if (alive>=0.85 && health.missing>=DonorHealth::MinKnown)
            doomed=DupeIdentity::ParDoomed(pick,alive,deadline);
    }
    if (!nzbget_rs_dupe_should_expand(alive,missing,job.failed || doomed,false)) return;
    // Do not spend indexer grabs when a usable whole backup already exists.
    std::set<std::string> probed;
    auto whole=[&](const NzbSummary& info) {
        // A failed pick is not its own backup, even if all of its articles exist.
        // Match the same-posting rejection used later before adding donors.
        if (info.Fingerprint()==pick.Fingerprint() || Posting::SamePosting(pick.messageIds,info.messageIds)) return false;
        if (Util::CurrentTime()>=deadline || IsStopped() || !probed.insert(info.Fingerprint()).second) return false;
        auto h=check(info);
        return DupeIdentity::Alive(h,info)>=0.999;
    };
    for (const auto& posting : fetched)
        if ((!ReleaseName::Readable(posting.info.mainName) || ReleaseName::SameRelease(job.name,posting.info.mainName)) && whole(posting.info)) return;
    for (const auto& member : job.members)
    {
        NzbSummary info;
        if (NzbReader::Parse(DupeUtil::ReadAll(member.second),info) && whole(info)) return;
    }
    if (IsStopped() || budget.Spent() || Util::CurrentTime()>=deadline) return;
    std::vector<Newznab::Params> queries;
    NzbgetRsBuf raw=nzbget_rs_dupe_queries(job.name.data(),job.name.size());
    size_t at=0;
    auto number=[&]() -> uint32_t {
        if (at>raw.len || raw.len-at<4) { at=raw.len; return 0; }
        uint32_t value=0;
        for (int i=0;i<4;i++) value|=(uint32_t)(unsigned char)raw.data[at++]<<(8*i);
        return value;
    };
    uint32_t count=number();
    auto strict=Newznab::BuildQueries(job.name,pick.meta.count("imdb")?pick.meta.at("imdb"):"",pick.meta.count("tvdb")?pick.meta.at("tvdb"):"");
    for (uint32_t i=0;i<count && i<8;i++)
    {
        uint32_t len=number();
        if (at>raw.len || len>raw.len-at) break;
        std::string q(raw.data+at,len);at+=len;
        bool duplicate=std::any_of(strict.begin(),strict.end(),[&](const Newznab::Params& params) {
            return std::any_of(params.begin(),params.end(),[&](const auto& p) {return p.first=="q" && p.second==q;});
        });
        if (!q.empty() && !duplicate) queries.push_back({{"t","search"},{"q",q}});
    }
    nzbget_rs_free(raw);
    Newznab::SearchStats searchStats;
    auto wider=Newznab::Search(g_Options->GetDupeSearchUrl(),g_Options->GetDupeSearchApiKey(),queries,deadline,&searchStats);
    queryStats.queries += searchStats.queries;
    queryStats.failed += searchStats.failed;
    queryStats.pages += searchStats.pages;
    std::vector<Newznab::Result> all=prior;
    std::set<std::string> seen;
    for (const auto& r:prior) seen.insert(r.link);
    for (auto& r:wider) if (seen.insert(r.link).second) { results++;all.push_back(std::move(r)); }
    unsigned long long estimate=DupeIdentity::WholeBytes(pick);
    long long bytes=(long long)std::min(estimate,(unsigned long long)std::numeric_limits<long long>::max());
    std::vector<Newznab::Result> accepted;
    for (const auto& r:all)
        if (!attempted.count(r.link) && DupeIdentity::Candidate(job.name,bytes,r.title,r.size)) accepted.push_back(r);
    candidates+=(int)accepted.size();
    auto order=Posting::OrderPostings(accepted,bytes,g_Options->GetDupeSearchMaxDonors());
    postings+=(int)order.size();
    Note(job.nzbId,Message::mkInfo,"DupeSearch: %s: failing pick has no whole backup; broader discovery (%i candidate(s))",job.name.c_str(),(int)accepted.size());
    DupeIdentity::Identity mine;
    bool readMine=false;
    for (const auto& group:order)
    {
        if (IsStopped() || budget.Spent() || Util::CurrentTime()>=deadline) break;
        for (const auto& r:group) attempted.insert(r.link);
        NzbFetcher::Stats counts;
        auto posting=m_fetcher.FetchPosting(group,deadline,counts,&budget);
        stats.Add(counts);
        if (posting.reason!=NzbFetcher::frOk || !DupeIdentity::OuterCompatible(job.name,posting.info.mainName)) continue;
        // Known-release names retain the strict path. Everything else needs inner proof or a fully matching readable data name.
        if (ReleaseName::SameRelease(job.name,posting.listing.title) &&
            (!ReleaseName::Readable(posting.info.mainName) || ReleaseName::SameRelease(job.name,posting.info.mainName)))
        { fetched.push_back(std::move(posting));continue; }
        if (!readMine) { mine=DupeIdentity::Read(pick,deadline);readMine=true; }
        auto theirs=DupeIdentity::Read(posting.info,deadline);
        if (!DupeIdentity::Matches(job.name,posting.info.mainName,mine,theirs)) continue;
        posting.lenient=true;
        posting.sameInner=mine && theirs && mine.bytes==theirs.bytes && mine.extension==theirs.extension;
        fetched.push_back(std::move(posting));
    }
#endif
}

void DupeSearch::Search(const Job& job)
{
	// search and fetch together are meant to fit in about this long
	time_t deadline = Util::CurrentTime() + SearchDeadlineSec;

	// what the pick's own nzb-file says: its size ranks the candidates (the
	// closest size is the likeliest byte-identical repost), its ids narrow the search
	NzbSummary pick;
	if (!job.queuedFile.empty())
	{
		if (!NzbReader::Parse(DupeUtil::ReadAll(job.queuedFile), pick))
		{
			Note(job.nzbId, Message::mkDetail, "DupeSearch: could not read the nzb-file of %s", job.name.c_str());
		}
	}
    if (job.rankOnly)
    {
        std::vector<NzbFetcher::Fetched> verified;
        std::map<std::string,int> rejected;
        Place(job,pick,verified,rejected,0,0,0);
        return;
    }
    NzbFetcher::Budget budget(g_Options->GetDupeSearchMaxDonors());
    std::set<std::string> attempted;
	std::string imdb = pick.meta.count("imdb") ? pick.meta["imdb"] : "";
	std::string tvdb = pick.meta.count("tvdb") ? pick.meta["tvdb"] : "";

	std::vector<Newznab::Params> queries = Newznab::BuildQueries(job.name, imdb, tvdb);
	Newznab::SearchStats stats;
	std::vector<Newznab::Result> results = Newznab::Search(g_Options->GetDupeSearchUrl(),
		g_Options->GetDupeSearchApiKey(), queries, deadline, &stats);

	// the same release by name; the size isn't a criterion (postings of one
	// release differ by gigabytes in par2 and packaging)
	std::vector<Newznab::Result> candidates;
	for (const Newznab::Result& result : results)
	{
		if (ReleaseName::SameRelease(job.name, result.title))
		{
			candidates.push_back(result);
		}
	}

	Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: %i result(s) from %i search(es) (%i failed, %i page(s)), %i of them the same release",
		job.name.c_str(), (int)results.size(), stats.queries, stats.failed, stats.pages, (int)candidates.size());

	// the postings to fetch, best first: fetching each costs a grab of an indexer
	std::vector<Posting::Group> order = Posting::OrderPostings(candidates, pick.totalBytes,
		g_Options->GetDupeSearchMaxDonors());

	// the sketches of what nzbget already holds, read beside the fetches
	std::vector<Posting::Sketch> known;
	std::thread knownReader([&]()
		{
			for (const std::string& path : job.knownFiles)
			{
				Posting::Sketch sketch;
				if (Posting::SketchOfFile(path, sketch))
				{
					known.push_back(std::move(sketch));
				}
			}
		});

	NzbFetcher::Stats fetchStats;
	std::vector<NzbFetcher::Fetched> fetched;
	int notTried = 0;
	size_t parallel = g_Options->GetDupeSearchMaxDonors() > 0 ? 1 : FetchParallel;
    for (size_t from = 0; from < order.size(); from += parallel)
	{
		if (IsStopped() || Util::CurrentTime() >= deadline || budget.Spent())
		{
			notTried = (int)(order.size() - from);
			break;
		}

		size_t count = std::min(parallel, order.size() - from);
		std::vector<NzbFetcher::Fetched> chunk(count);
		std::vector<NzbFetcher::Stats> chunkStats(count);
		std::vector<std::thread> threads;
		for (size_t i = 0; i < count; i++)
		{
            for (const Newznab::Result& listing : order[from+i]) attempted.insert(listing.link);
			threads.emplace_back([&, i]()
				{ chunk[i] = m_fetcher.FetchPosting(order[from + i], deadline, chunkStats[i], &budget); });
		}
		for (std::thread& thread : threads)
		{
			thread.join();
		}
		for (size_t i = 0; i < count; i++)
		{
			fetchStats.Add(chunkStats[i]);
			if (chunk[i].reason == NzbFetcher::frOk)
			{
				fetched.push_back(std::move(chunk[i]));
			}
		}
	}

	knownReader.join();
    int resultCount=(int)results.size(), candidateCount=(int)candidates.size(), postingCount=(int)order.size();
    Expand(job,pick,results,deadline,budget,fetched,attempted,fetchStats,stats,resultCount,candidateCount,postingCount);

	// what is worth keeping, in this order: another release (by the name of
	// its largest data file, when that name is readable), a posting nzbget
	// already holds, one found dead before, one that shares articles with
	// the pick or an accepted duplicate
	std::vector<std::vector<std::string>> postings;
	postings.push_back(pick.messageIds);
	std::vector<NzbFetcher::Fetched> verified;
	std::map<std::string, int> rejected;
	for (NzbFetcher::Fetched& posting : fetched)
	{
		Posting::Sketch sketch = Posting::MakeSketch(posting.info.messageIds);
		const std::vector<std::string>& ids = posting.info.messageIds;
		if (!posting.lenient && ReleaseName::Readable(posting.info.mainName) && !ReleaseName::SameRelease(job.name, posting.info.mainName))
		{
			rejected["other-release"]++;
		}
		else if (std::any_of(known.begin(), known.end(), [&](const Posting::Sketch& k) { return Posting::SameSketch(sketch, k); }))
		{
			rejected["in-nzbget"]++;
		}
		else if (m_dead.IsDead(sketch))
		{
			rejected["known-dead"]++;
		}
		else if (std::any_of(postings.begin(), postings.end(), [&](const std::vector<std::string>& p) { return Posting::SamePosting(ids, p); }))
		{
			rejected["same-posting"]++;
		}
		else
		{
			postings.push_back(ids);
			verified.push_back(std::move(posting));
		}
	}
	rejected["listing-mismatch"] += fetchStats.listingMismatch;
	rejected["refused"] += fetchStats.refused;
	rejected["relisted"] += fetchStats.relisted;
	rejected["fetch"] += fetchStats.fetch;
	rejected["parse"] += fetchStats.parse;
	rejected["deadline"] += notTried;
    rejected["budget"] += fetchStats.budget;

	// a search that learned nothing - a query failed and nothing came back, or no
	// posting could be fetched (indexers refusing, the deadline) - doesn't hold the
	// key for SearchWindowSec: the next add of the key, or a restart, searches it again
	bool allFailed = stats.queries > 0 && stats.failed == stats.queries;
	bool queriesFailed = stats.failed > 0 && verified.empty();
	bool nothingFetched = fetched.empty() && fetchStats.refused + fetchStats.fetch + notTried > 0;
	if (queriesFailed || nothingFetched)
	{
		ForgetSearch(job.dupeKey);
		Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: %s, the key may be searched again", job.name.c_str(),
			allFailed ? "no indexer answered" : queriesFailed ? "an indexer query failed and nothing came back" :
			"no posting could be fetched");
	}

	// what was fetched is kept until it is placed: a restart resumes from it
	// without fetching again (every fetch costs a grab)
	SavePending(job, pick, verified);
	Place(job, pick, verified, rejected, resultCount, candidateCount, postingCount);
}

void DupeSearch::Place(const Job& job, const NzbSummary& pick, std::vector<NzbFetcher::Fetched>& verified,
	std::map<std::string, int>& rejected, int results, int candidates, int postings)
{
	// closest size first: the likeliest byte-identical repost; then the most grabbed
	long long pickBytes = pick.totalBytes;
	auto distance = [&](const NzbFetcher::Fetched& f)
		{ return f.info.totalBytes > pickBytes ? f.info.totalBytes - pickBytes : pickBytes - f.info.totalBytes; };
	std::stable_sort(verified.begin(), verified.end(), [&](const NzbFetcher::Fetched& x, const NzbFetcher::Fetched& y)
		{
			if (distance(x) != distance(y)) return distance(x) < distance(y);
			if (x.listing.grabs != y.listing.grabs) return x.listing.grabs > y.listing.grabs;
			return x.listing.date > y.listing.date;
		});

	DonorHealth::ServerList servers;
	if (!verified.empty() || !job.members.empty())
	{
		servers = NntpHealthServer::Servers();
		if (servers.empty())
		{
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: no active news servers, the postings are added unchecked", job.name.c_str());
		}
	}
	DonorHealth::Options healthOptions;
	healthOptions.sample.percent = g_Options->GetDupeHealthPercent();
	healthOptions.sample.minimum = g_Options->GetDupeHealthMin();
	healthOptions.sample.maximum = g_Options->GetDupeHealthMax();
	healthOptions.sample.maxBody = g_Options->GetDupeBodyChecks();
	healthOptions.budgetMs = g_Options->GetDupeHealthBudget() * 1000;

	auto groupsOf = [](const NzbSummary& summary)
		{ return std::make_shared<std::vector<std::string>>(summary.groups); };

	// the pick's own posting: found dead, it is remembered (the dead-pick probe of
	// the queue is what swaps it out)
	std::thread pickCheck;
	if (!servers.empty() && !pick.messageIds.empty())
	{
		pickCheck = std::thread([&]()
			{
				DonorHealth::Health health = DonorHealth::CheckPosting(servers, pick.messageIds,
					groupsOf(pick), healthOptions, false);
				if (DonorHealth::DeadProbe(health))
				{
					m_dead.Add(Posting::MakeSketch(pick.messageIds), 0, !g_Options->GetDupeSearchDryRun());
					Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: the pick is dead (%i of %i probe articles on no server)",
						job.name.c_str(), health.missing, health.Answered());
				}
			});
	}

	int dead = 0;
	int overCap = 0;
	int rescoreFailed = 0;
	int added = 0;
	int cap = g_Options->GetDupeSearchMaxDonors();
	std::mutex placeMutex;
	std::map<size_t, DonorHealth::Health> probe;

	// the quick probe of every posting
	if (!servers.empty())
	{
		std::vector<DonorHealth::Posting> list;
		for (size_t i = 0; i < verified.size(); i++)
		{
			list.push_back({ std::to_string(i), verified[i].info.messageIds, groupsOf(verified[i].info) });
		}
		DonorHealth::CheckPostings(servers, list, healthOptions, false, FetchParallel,
			[&](const std::string& key, const DonorHealth::Health& health)
			{
				std::lock_guard<std::mutex> guard(placeMutex);
				probe[(size_t)atoi(key.c_str())] = health;
			});
	}

	std::vector<size_t> live;
	for (size_t i = 0; i < verified.size(); i++)
	{
		auto it = probe.find(i);
		if (it != probe.end() && DonorHealth::DeadProbe(it->second))
		{
			m_dead.Add(Posting::MakeSketch(verified[i].info.messageIds), 0, !g_Options->GetDupeSearchDryRun());
			dead++;
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: dropping dead posting %s [%s] after the probe: %i of %i probe articles on no server",
				job.name.c_str(), verified[i].listing.title.c_str(), verified[i].listing.indexer.c_str(),
				it->second.missing, it->second.Answered());
			continue;
		}
		live.push_back(i);
	}

	struct Placed
	{
		int id;
		DonorScore::Entry entry;
		std::string title;
		bool member = false;	// a duplicate that was already in history: always rescored
		int oldScore = 0;		// a member's score before: never raised unless it is whole
	};
	std::map<size_t, Placed> placed;
	DonorScore::Ranks ranks;
	int base = DonorScore::Base(job.score);

	auto twinOf = [&](const NzbFetcher::Fetched& f)
		{ return DupeIdentity::SameData(pick, f.info); };
	auto aliveOf = [&](const DonorHealth::Health& health, const NzbSummary& summary) { return DupeIdentity::Alive(health, summary); };
	auto entryOf = [&](size_t i, int score, double alive)
		{
			DonorScore::Entry entry;
			entry.score = score;
			entry.alive = alive;
			entry.twin = twinOf(verified[i]);
			entry.bytes = verified[i].info.totalBytes;
			entry.grabs = verified[i].listing.grabs;
			return entry;
		};
	// nzbget shuts down: a check cut short knows nothing, and adding a duplicate now
	// would wait for the stopped scanner for good (B37). The search keeps its saved
	// postings and resumes after the restart.
	auto interrupted = [&]()
		{
			if (!IsStopped())
			{
				return false;
			}
			if (pickCheck.joinable())
			{
				pickCheck.join();
			}
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: nzbget shuts down, the search resumes after the restart",
				job.name.c_str());
			return true;
		};
	auto place = [&](size_t i, double alive, const char* how)
		{
			int score = ranks.Take(alive, twinOf(verified[i]));
			int id = AddDonor(job, pick, verified[i], base + score, alive);
			if (id == 0)
			{
				ranks.Release(score);
				return;
			}
			added++;
			placed[i] = { id, entryOf(i, score, alive), verified[i].listing.title };
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: added %s [%s] score=%i alive=%i%% (%s)", job.name.c_str(),
				verified[i].listing.title.c_str(), verified[i].listing.indexer.c_str(), base + score,
				alive < 0 ? -1 : (int)std::lround(100 * alive), how);
		};

	// the probe-alive postings go in at once, then each is rescored when its
	// full sample lands; the rest are added as their samples finish
	size_t fast = std::min((size_t)g_Options->GetDupeFastDonors(), live.size());
	if (cap > 0)
	{
		fast = std::min(fast, (size_t)cap);
	}
	std::set<size_t> fastSet;
	for (size_t n = 0; n < fast; n++)
	{
		auto it = probe.find(live[n]);
		place(live[n], it == probe.end() ? -1.0 : aliveOf(it->second, verified[live[n]].info), "fast");
		fastSet.insert(live[n]);
	}

	std::set<size_t> todo(live.begin(), live.end());
	if (!servers.empty() && !todo.empty())
	{
		std::vector<DonorHealth::Posting> list;
		for (size_t i : todo)
		{
			list.push_back({ std::to_string(i), verified[i].info.messageIds, groupsOf(verified[i].info) });
		}
		DonorHealth::CheckPostings(servers, list, healthOptions, true, FetchParallel,
			[&](const std::string& key, const DonorHealth::Health& health)
			{
				std::lock_guard<std::mutex> guard(placeMutex);
				size_t i = (size_t)atoi(key.c_str());
				if (IsStopped() || !todo.erase(i))
				{
					return;
				}
				double alive = aliveOf(health, verified[i].info);
				bool isDead = DupeIdentity::IsDead(health, verified[i].info, g_Options->GetDupeMinAlive());
				Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: %s [%s]: alive=%i%% (%i of %i articles)", job.name.c_str(),
					verified[i].listing.title.c_str(), verified[i].listing.indexer.c_str(),
					alive < 0 ? -1 : (int)std::lround(100 * alive), health.present, health.Answered());

				auto it = placed.find(i);
				if (it != placed.end())
				{
					// a fast donor: its real health moves its score
					Placed& donor = it->second;
					ranks.Release(donor.entry.score);
					int score = isDead ? DonorScore::Dead : ranks.Take(alive, donor.entry.twin);
					std::string param = std::string(AliveParam) + "=" + std::to_string(isDead ? 0 : alive < 0 ? 100 : (int)std::lround(100 * alive));
					if (alive < 0 || SetScore(donor.id, base + score,
						param.empty() ? std::vector<std::string>() : std::vector<std::string>{ param }))
					{
						if (alive < 0)
						{
							// inconclusive: the donor keeps its score, and the rank taken for
							// the new one is given back (F19: it stayed taken, the old one free)
							ranks.Release(score);
							ranks.Use(donor.entry.score);
						}
						else
						{
							donor.entry.score = score;
						}
						donor.entry.alive = alive;
						if (isDead)
						{
							m_dead.Add(Posting::MakeSketch(verified[i].info.messageIds), 0, !g_Options->GetDupeSearchDryRun());
							dead++;
						}
					}
					else
					{
						ranks.Release(score);
						ranks.Use(donor.entry.score);
						rescoreFailed++;
						Note(job.nzbId, Message::mkWarning, "DupeSearch: could not rescore %s: keeps score %i", verified[i].listing.title.c_str(),
							base + donor.entry.score);
					}
				}
				else if (cap > 0 && added >= cap)
				{
					overCap++;
				}
				else if (isDead)
				{
					m_dead.Add(Posting::MakeSketch(verified[i].info.messageIds), 0, !g_Options->GetDupeSearchDryRun());
					dead++;
					Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: dropping dead posting %s: alive=%i%%", job.name.c_str(),
						verified[i].listing.title.c_str(), (int)std::lround(100 * alive));
				}
				else
				{
					place(i, alive, "checked");
				}
			});
	}

	if (interrupted())
	{
		return;
	}

	// whatever no check reported on (no servers, a failed check) is added unchecked
	for (size_t i : std::set<size_t>(todo))
	{
		todo.erase(i);
		if (placed.count(i))
		{
			continue;
		}
		if (cap > 0 && added >= cap)
		{
			overCap++;
			continue;
		}
		place(i, -1.0, "unchecked");
	}

	// the duplicates nzbget already kept for the key (a client's own backups,
	// earlier searches' donors) are measured the same way and ranked with the
	// new ones: nzbget tries them by score, whoever sent them. Each is read
	// from its own nzb-file, never matched by size: two postings can have one size.
	if (!servers.empty() && !job.members.empty())
	{
		std::vector<NzbSummary> summaries(job.members.size());
		std::vector<DonorHealth::Posting> list;
		std::map<size_t, size_t> sameAs;	// a member whose posting another member already is
		for (size_t m = 0; m < job.members.size(); m++)
		{
			if (!NzbReader::Parse(DupeUtil::ReadAll(job.members[m].second), summaries[m]) || Posting::SamePosting(summaries[m].messageIds, pick.messageIds))
			{
				continue;
			}
			// each posting is checked once: the client's copies of it share the answer
			auto first = std::find_if(list.begin(), list.end(), [&](const DonorHealth::Posting& posting)
				{ return Posting::SamePosting(summaries[m].messageIds, posting.ids); });
			if (first != list.end())
			{
				sameAs[m] = (size_t)atoi(first->key.c_str());
				continue;
			}
			list.push_back({ std::to_string(m), summaries[m].messageIds, groupsOf(summaries[m]) });
		}
		std::map<size_t, DonorHealth::Health> measured;
		DonorHealth::CheckPostings(servers, list, healthOptions, true, FetchParallel,
			[&](const std::string& key, const DonorHealth::Health& health)
			{
				std::lock_guard<std::mutex> guard(placeMutex);
				measured[(size_t)atoi(key.c_str())] = health;
			});
		for (const auto& alias : sameAs)
		{
			auto health = measured.find(alias.second);
			if (health != measured.end())
			{
				measured[alias.first] = health->second;
			}
		}
		for (const auto& entry : measured)
		{
			const NzbSummary& summary = summaries[entry.first];
			double alive = aliveOf(entry.second, summary);
			if (alive < 0)
			{
				continue;	// too few answers to judge: its score stays
			}
			bool isDead = DupeIdentity::IsDead(entry.second, summary, g_Options->GetDupeMinAlive());
			if (isDead)
			{
				m_dead.Add(Posting::MakeSketch(summary.messageIds), 0, !g_Options->GetDupeSearchDryRun());
			}
			Placed member;
			member.id = job.members[entry.first].first;
			member.title = FileSystem::BaseFileName(job.members[entry.first].second.c_str());
			member.member = true;
			member.oldScore = entry.first < job.memberScores.size() ? job.memberScores[entry.first] : 0;
			member.entry.score = isDead ? DonorScore::Dead : DonorScore::Dead + 1;
			member.entry.alive = alive;
			member.entry.twin = DupeIdentity::SameData(pick, summary);
			member.entry.bytes = summary.totalBytes;
			placed[verified.size() + entry.first] = member;
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: duplicate %s in history: alive=%i%% (%i of %i articles)%s", job.name.c_str(),
				member.title.c_str(), (int)std::lround(100 * alive), entry.second.present, entry.second.Answered(),
				isDead ? ", dead" : "");
		}
	}

	if (interrupted())
	{
		return;
	}

	// once every check is in, the scores in order of wholeness
	std::vector<size_t> order2;
	std::vector<DonorScore::Entry> entries;
	for (auto& entry : placed)
	{
		order2.push_back(entry.first);
		entries.push_back(entry.second.entry);
	}
	std::vector<int> wanted = DonorScore::Rerank(entries, pickBytes);
	// with every one of them dead there is nothing to order: scores stay, the dead are marked
	bool allDead = std::all_of(wanted.begin(), wanted.end(), [](int score) { return score == DonorScore::Dead; });
	for (size_t n = 0; n < order2.size(); n++)
	{
		Placed& donor = placed[order2[n]];
		if (wanted[n] == donor.entry.score && !donor.member)
		{
			continue;
		}
		std::vector<std::string> params;
		int score = base + wanted[n];
		if (donor.member)
		{
			// not DupeAlive: that marks a duplicate a dupe tool added, and this one
			// may be a client's own backup - unless it is dead: then DupeAlive=0 keeps
			// any failover from fetching it
			int percent = (int)std::lround(100 * donor.entry.alive);
			params.push_back(std::string(HealthParam) + "=" + std::to_string(percent));
			if (wanted[n] == DonorScore::Dead)
			{
				params.push_back(std::string(AliveParam) + "=0");
			}
			// a copy that isn't whole is never raised: only lowered, or kept
			if ((percent < 100 && score > donor.oldScore) || allDead)
			{
				score = donor.oldScore;
			}
		}
		if (SetScore(donor.id, score, params))
		{
			Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: reranked %s: score %i", job.name.c_str(), donor.title.c_str(), score);
			donor.entry.score = wanted[n];
		}
		else
		{
			rescoreFailed++;
		}
	}

	if (pickCheck.joinable())
	{
		pickCheck.join();
	}

	rejected["dead"] += dead;
	rejected["over-cap"] += overCap;
	rejected["rescore"] += rescoreFailed;
	std::string outcome;
	for (const auto& entry : rejected)
	{
		if (entry.second > 0)
		{
			outcome += (outcome.empty() ? "" : ", ") + entry.first + ": " + std::to_string(entry.second);
		}
	}
	Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: results=%i candidates=%i postings=%i verified=%i added=%i rejected={%s}",
		job.name.c_str(), results, candidates, postings, (int)verified.size(), added, outcome.c_str());
	RemovePending(job.nzbId);
	{
		std::lock_guard<std::mutex> guard(m_mutex);
		m_sent.erase(job.nzbId);
	}
    // Empty searches are retryable while the pick remains queued; no new grabs for a completed key.
    bool usableBackup=std::any_of(placed.begin(),placed.end(),[](const auto& item) {
        return item.second.entry.score>DonorScore::Dead && item.second.entry.alive>=0.999;
    });
    bool retryWanted=!job.rankOnly;
    if (job.rankOnly)
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        auto state=m_searched.find(LowerKey(job.dupeKey));
        retryWanted=state!=m_searched.end() && state->second.retryable;
    }
    if (usableBackup)
    {
        { std::lock_guard<std::mutex> guard(m_mutex);
          auto state=m_searched.find(LowerKey(job.dupeKey));
          if (state!=m_searched.end()) state->second.retryable=false; }
        if (!g_Options->GetDupeSearchDryRun()) SaveState();
    }
    if (retryWanted && !usableBackup && added == 0 && !IsStopped())
    {
        GuardedDownloadQueue queue=DownloadQueue::Guard();
        NzbInfo* current=queue->GetQueue()->Find(job.nzbId);
        if (current && !current->GetDeleting() && current->GetDeleteStatus()==NzbInfo::dsNone &&
            !current->GetPostInfo() && LowerKey(EffectiveKey(current))==LowerKey(job.dupeKey) &&
            ReleaseName::Normalize(current->GetName())==ReleaseName::Normalize(job.name))
        {
            ForgetSearch(job.dupeKey);
            Schedule(job.nzbId,Util::CurrentTime()+900);
        }
    }
}

std::string DupeSearch::PickGone(const Job& job)
{
	GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
	// in history after a download or a failure it still wants its duplicates;
	// deleted by the user it doesn't: the first duplicate would download
	NzbInfo* pick = FindNzb(downloadQueue, job.nzbId);
	if (!pick || pick->GetDeleting() || pick->GetDeleteStatus() == NzbInfo::dsManual)
	{
		return "the pick was deleted";
	}
	// under another key the duplicates would match nothing and download beside it
	if (LowerKey(EffectiveKey(pick)) != LowerKey(job.dupeKey))
	{
		return "the duplicate key of the pick changed";
	}
    if (ReleaseName::Normalize(pick->GetName()) != ReleaseName::Normalize(job.name))
    {
        return "the name of the pick changed";
    }
	return "";
}

int DupeSearch::AddDonor(const Job& job, const NzbSummary& pick, const NzbFetcher::Fetched& posting, int score, double alive)
{
	if (IsStopped())
	{
		return 0;
	}
	std::string gone = PickGone(job);
	if (!gone.empty())
	{
		Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: not adding %s [%s]: %s", job.name.c_str(),
			posting.listing.title.c_str(), posting.listing.indexer.c_str(), gone.c_str());
		return 0;
	}
	if (g_Options->GetDupeSearchDryRun())
	{
		Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: dry run, would add %s [%s] score=%i alive=%i%%", job.name.c_str(),
			posting.listing.title.c_str(), posting.listing.indexer.c_str(), score,
			alive < 0 ? -1 : (int)std::lround(100 * alive));
		return -1;
	}
	std::string fingerprint = posting.info.Fingerprint();
	{
		std::lock_guard<std::mutex> guard(m_mutex);
		if (!m_sent[job.nzbId].insert(fingerprint).second)
		{
			return 0;
		}
	}

	NzbParameterList parameters;
	parameters.SetParameter(DonorParam, "yes");
	for (const std::string& hint : DupeIdentity::Hints(pick, posting.info, posting.sameInner))
	{
		size_t equals = hint.find('=');
		parameters.SetParameter(hint.substr(0, equals).c_str(), hint.substr(equals + 1).c_str());
	}
	if (alive >= 0)
	{
		parameters.SetParameter(AliveParam, std::to_string((int)std::lround(100 * alive)).c_str());
	}
	std::string name = posting.listing.title;
	if (name.size() < 4 || strcasecmp(name.c_str() + name.size() - 4, ".nzb"))
	{
		name += ".nzb";
	}

	int nzbId = 0;
	Scanner::EAddStatus status = g_Scanner->AddExternalFile(name.c_str(), job.category.c_str(), false, 0,
		job.dupeKey.c_str(), score, dmScore, &parameters, false, false, nullptr, nullptr,
		posting.data.data(), (int)posting.data.size(), &nzbId);
	if (status != Scanner::asSuccess || nzbId <= 0)
	{
		std::lock_guard<std::mutex> guard(m_mutex);
		m_sent[job.nzbId].erase(fingerprint);
		return 0;
	}

	// the pick may have been deleted, or have got another key, while the add ran
	// (it takes the queue lock itself, after PickGone let it go): the new duplicate
	// goes again (B33)
	gone = PickGone(job);
	if (!gone.empty())
	{
		{
			GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
			IdList ids{ nzbId };
			bool queued = downloadQueue->GetQueue()->Find(nzbId) != nullptr;
			downloadQueue->EditList(&ids, nullptr, DownloadQueue::mmId,
				queued ? DownloadQueue::eaGroupFinalDelete : DownloadQueue::eaHistoryFinalDelete, nullptr);
		}
		Note(job.nzbId, Message::mkInfo, "DupeSearch: %s: removed the duplicate %s just added: %s",
			job.name.c_str(), posting.listing.title.c_str(), gone.c_str());
		return 0;
	}

	// remembered with the search in progress: a resume after a restart must not add
	// it again, even when the user deleted it meanwhile (then nzbget keeps only a
	// hidden duplicate record, which the resume can't recognize)
	std::string sentPath = PendingDir(job.nzbId) + PATH_SEPARATOR + "sent";
	if (FileSystem::DirectoryExists(PendingDir(job.nzbId).c_str()))
	{
		std::ofstream sent(fs::u8path(sentPath), std::ios::app);
		sent << fingerprint << "\n";
	}
	return nzbId;
}

bool DupeSearch::SetScore(int id, int score, const std::vector<std::string>& params)
{
	if (g_Options->GetDupeSearchDryRun() || id < 0)
	{
		std::string text;
		for (const std::string& param : params)
		{
			text += " " + param;
		}
		info("DupeSearch: dry run, would set the score of download %i to %i%s", id, score, text.c_str());
		return true;
	}
	GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
	// a duplicate the user deleted is kept as a hidden record (hkDup): its score
	// edit succeeds but means nothing, so it counts as gone
	for (HistoryInfo* historyInfo : downloadQueue->GetHistory())
	{
		if (historyInfo->GetId() == id && historyInfo->GetKind() == HistoryInfo::hkDup)
		{
			return false;
		}
	}
	IdList ids{ id };
	std::string text = std::to_string(score);
	const std::pair<DownloadQueue::EEditAction, DownloadQueue::EEditAction> kinds[] = {
		{ DownloadQueue::eaHistorySetDupeScore, DownloadQueue::eaHistorySetParameter },
		{ DownloadQueue::eaGroupSetDupeScore, DownloadQueue::eaGroupSetParameter } };
	for (const auto& kind : kinds)
	{
		if (downloadQueue->EditList(&ids, nullptr, DownloadQueue::mmId, kind.first, text.c_str()))
		{
			for (const std::string& param : params)
			{
				downloadQueue->EditList(&ids, nullptr, DownloadQueue::mmId, kind.second, param.c_str());
			}
			return true;
		}
	}
	return false;
}

void DupeSearch::Note(int nzbId, Message::EKind kind, const char* format, ...)
{
	char text[1024];
	va_list ap;
	va_start(ap, format);
	vsnprintf(text, sizeof(text), format, ap);
	va_end(ap);

	// into the pick's own log as well (with InfoTarget=log and no log file,
	// the global log keeps no info lines); the global log alone once it's gone
	GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
	NzbInfo* nzbInfo = FindNzb(downloadQueue, nzbId);
	if (nzbInfo)
	{
		nzbInfo->AddMessage(kind, text);
		return;
	}
	switch (kind)
	{
		case Message::mkWarning: warn("%s", text); break;
		case Message::mkDetail: detail("%s", text); break;
		default: info("%s", text); break;
	}
}

std::string DupeSearch::PendingDir(int nzbId)
{
	std::string dir = std::string(g_Options->GetQueueDir()) + PATH_SEPARATOR + "dupesearch-pending";
	return nzbId > 0 ? dir + PATH_SEPARATOR + std::to_string(nzbId) : dir;
}

namespace
{

void RemoveDir(const std::string& dir)
{
	CString errmsg;
	FileSystem::DeleteDirectoryWithContent(dir.c_str(), errmsg);
}


}

void DupeSearch::MarkSearching(int nzbId)
{
	if (g_Options->GetDupeSearchDryRun())
	{
		return;
	}
	std::string dir = PendingDir(nzbId);
	RemoveDir(dir);
	CString errmsg;
	if (!FileSystem::ForceDirectories(dir.c_str(), errmsg) || !DupeUtil::WriteAtomic(dir + PATH_SEPARATOR + "phase", "searching\n"))
	{
		warn("Could not save the DupeSearch state to %s", dir.c_str());
	}
}

void DupeSearch::SavePending(const Job& job, const NzbSummary& pick, const std::vector<NzbFetcher::Fetched>& verified)
{
	if (g_Options->GetDupeSearchDryRun())
	{
		return;
	}
	std::string dir = PendingDir(job.nzbId);
    bool ok = DupeUtil::WriteAtomic(dir + PATH_SEPARATOR + "pick-title", ReleaseName::Normalize(job.name)) &&
        DupeUtil::WriteAtomic(dir + PATH_SEPARATOR + "pick-key", LowerKey(job.dupeKey)) &&
        DupeUtil::WriteAtomic(dir + PATH_SEPARATOR + "pick-posting", pick.Fingerprint());
	for (size_t i = 0; i < verified.size() && ok; i++)
	{
		const Newznab::Result& listing = verified[i].listing;
		std::string base = dir + PATH_SEPARATOR + std::to_string(i);
		std::stringstream meta;
		meta << listing.title << '\t' << listing.indexer << '\t' << listing.grabs << '\t' << listing.size << '\t'
			<< (long long)listing.date << "\t\n";
		ok = DupeUtil::WriteAtomic(base + ".nzb", verified[i].data) && DupeUtil::WriteAtomic(base + ".meta", meta.str()) &&
            DupeUtil::WriteAtomic(base + ".inner", verified[i].sameInner ? "1\n" : "0\n");
	}
	if (!ok || !DupeUtil::WriteAtomic(dir + PATH_SEPARATOR + "phase", "fetched\n"))
	{
		warn("Could not save the DupeSearch state to %s", dir.c_str());
	}
}

void DupeSearch::RemovePending(int nzbId)
{
	if (IsStopped())
	{
		return;	// interrupted: resumed after the restart
	}
	RemoveDir(PendingDir(nzbId));
}

void DupeSearch::ResumePending()
{
	std::vector<int> ids;
	DirBrowser dirBrowser(PendingDir(0).c_str());
	while (const char* name = dirBrowser.Next())
	{
		if (atoi(name) > 0 && std::to_string(atoi(name)) == name)
		{
			ids.push_back(atoi(name));
		}
	}

	for (int nzbId : ids)
	{
		if (IsStopped())
		{
			return;
		}
		std::string dir = PendingDir(nzbId);
		bool fetched = DupeUtil::ReadAll(dir + PATH_SEPARATOR + "phase") == "fetched\n";

		Job job;
		{
			GuardedDownloadQueue downloadQueue = DownloadQueue::Guard();
			NzbInfo* nzbInfo = FindNzb(downloadQueue, nzbId);
			if (nzbInfo && fetched)
			{
				Collect(downloadQueue, nzbInfo, job);
				job.score = std::max(nzbInfo->GetDupeScore(), BasePickScore);
			}
			else if (nzbInfo)
			{
				// the search itself was cut off: it runs again
				std::lock_guard<std::mutex> guard(m_mutex);
				m_searched.erase(LowerKey(EffectiveKey(nzbInfo)));
			}
		}
		if (!fetched || job.nzbId == 0)
		{
			RemoveDir(dir);
			continue;
		}

		Note(job.nzbId, Message::mkInfo, "DupeSearch: resuming the search of %s after a restart", job.name.c_str());
		NzbSummary pick;
		NzbReader::Parse(DupeUtil::ReadAll(job.queuedFile), pick);
        // Proof belongs to the original pick. Old state without that binding is
        // searched again rather than assigning its donors to an unknown release.
        if (!FileSystem::FileExists((dir + PATH_SEPARATOR + "pick-title").c_str()) ||
            DupeUtil::ReadAll(dir + PATH_SEPARATOR + "pick-title") != ReleaseName::Normalize(job.name) ||
            DupeUtil::ReadAll(dir + PATH_SEPARATOR + "pick-key") != LowerKey(job.dupeKey) ||
            DupeUtil::ReadAll(dir + PATH_SEPARATOR + "pick-posting") != pick.Fingerprint())
        {
            Note(job.nzbId, Message::mkInfo, "DupeSearch: saved search identity changed; searching the current pick again");
            RemoveDir(dir);
            ForgetSearch(job.dupeKey);
            Schedule(job.nzbId, Util::CurrentTime() + g_Options->GetDupeSearchDelay());
            continue;
        }
		std::vector<Posting::Sketch> known;
		for (const std::string& path : job.knownFiles)
		{
			Posting::Sketch sketch;
			if (Posting::SketchOfFile(path, sketch))
			{
				known.push_back(std::move(sketch));
			}
		}

		std::set<std::string> sent;
		{
			std::stringstream lines(DupeUtil::ReadAll(dir + PATH_SEPARATOR + "sent"));
			for (std::string line; std::getline(lines, line);)
			{
				sent.insert(line);
			}
		}

		std::vector<NzbFetcher::Fetched> verified;
		std::map<std::string, int> rejected;
		for (int i = 0;; i++)
		{
			std::string base = dir + PATH_SEPARATOR + std::to_string(i);
			if (!FileSystem::FileExists((base + ".meta").c_str()))
			{
				break;
			}
			NzbFetcher::Fetched posting;
			std::stringstream meta(DupeUtil::ReadAll(base + ".meta"));
			std::string grabs, size, date;
			std::getline(meta, posting.listing.title, '\t');
			std::getline(meta, posting.listing.indexer, '\t');
			std::getline(meta, grabs, '\t');
			std::getline(meta, size, '\t');
			std::getline(meta, date, '\t');
			posting.listing.grabs = atoi(grabs.c_str());
			posting.listing.size = atoll(size.c_str());
			posting.listing.date = (time_t)atoll(date.c_str());
			posting.data = DupeUtil::ReadAll(base + ".nzb");
			if (!NzbReader::Parse(posting.data, posting.info))
			{
				continue;
			}
			posting.reason = NzbFetcher::frOk;
            posting.sameInner = DupeUtil::ReadAll(base + ".inner") == "1\n";
			// the postings added before the restart are in nzbget now (ranked with
			// the key's other duplicates), or were deleted by the user since
			Posting::Sketch sketch = Posting::MakeSketch(posting.info.messageIds);
			if (sent.count(posting.info.Fingerprint()))
			{
				rejected["already-sent"]++;
				continue;
			}
			if (std::any_of(known.begin(), known.end(), [&](const Posting::Sketch& k) { return Posting::SameSketch(sketch, k); }))
			{
				rejected["in-nzbget"]++;
				continue;
			}
			verified.push_back(std::move(posting));
		}
		Place(job, pick, verified, rejected, 0, 0, 0);
	}
}

std::string DupeSearch::StatePath()
{
	return std::string(g_Options->GetQueueDir()) + PATH_SEPARATOR + "dupesearch";
}

void DupeSearch::LoadState()
{
	std::ifstream file(fs::u8path(StatePath()));
	std::string line;
	time_t now = Util::CurrentTime();
	std::lock_guard<std::mutex> guard(m_mutex);
	while (std::getline(file, line))
	{
		std::stringstream stream(line);
		std::string key, score, time;
		if (std::getline(stream, key, '\t') && std::getline(stream, score, '\t') && std::getline(stream, time, '\t'))
		{
			Searched searched;
			searched.score = atoi(score.c_str());
			searched.time = (time_t)atoll(time.c_str());
            std::getline(stream, searched.title, '\t');
            std::string retry;
            std::getline(stream,retry,'\t');
            // Three-field legacy stamps stored generated ownership in the key.
            if (searched.title.empty() && key.compare(0, 6, "dupes:") == 0)
                searched.title = key.substr(6);
            // An explicit legacy key has no old title: refresh its identity once.
            searched.retryable=retry=="1" || searched.title.empty();
			if (now - searched.time < StateTtlSec)
			{
				m_searched[key] = searched;
			}
		}
	}
}

void DupeSearch::ForgetSearch(const std::string& dupeKey)
{
	{
		std::lock_guard<std::mutex> guard(m_mutex);
#ifdef NZBGET_USE_RUST
        auto found=m_searched.find(LowerKey(dupeKey));
        if (found!=m_searched.end()) found->second.retryable=true;
#else
		m_searched.erase(LowerKey(dupeKey));
#endif
	}
	if (!g_Options->GetDupeSearchDryRun())
	{
		SaveState();
	}
}

void DupeSearch::SaveState()
{
	std::ostringstream text;
	{
		std::lock_guard<std::mutex> guard(m_mutex);
		time_t now = Util::CurrentTime();
		for (const auto& entry : m_searched)
		{
			if (now - entry.second.time < StateTtlSec)
			{
				text << entry.first << '\t' << entry.second.score << '\t' << (long long)entry.second.time << '\t' << entry.second.title << '\t' << (entry.second.retryable ? 1 : 0) << "\t\n";
			}
		}
	}
	if (!DupeUtil::WriteAtomic(StatePath(), text.str()))
	{
		warn("Could not save the DupeSearch state to %s", StatePath().c_str());
	}
}
