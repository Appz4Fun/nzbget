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

#include <fstream>
#include <sstream>
#include "NzbFetcher.h"
#include "DupeUtil.h"
#include "HttpGet.h"
#include "DonorHealth.h"
#include "FileSystem.h"
#include "Log.h"
#include "Util.h"
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif

NzbFetcher::Budget::Budget(int maxDonors) : m_left(maxDonors > 0 ? (unsigned long long)maxDonors * 3 : 0), m_unlimited(maxDonors <= 0)
{
#ifdef NZBGET_USE_RUST
    m_rust = nzbget_rs_dupe_budget_new(maxDonors > 0 ? (uint32_t)maxDonors : 0);
#endif
}
NzbFetcher::Budget::~Budget()
{
#ifdef NZBGET_USE_RUST
    nzbget_rs_dupe_budget_free(m_rust);
#endif
}
bool NzbFetcher::Budget::Take()
{
#ifdef NZBGET_USE_RUST
    return nzbget_rs_dupe_budget_take(m_rust) != 0;
#else
    if (m_unlimited) return true;
    unsigned long long left = m_left.load();
    while (left != 0) if (m_left.compare_exchange_weak(left, left - 1)) return true;
    return false;
#endif
}
bool NzbFetcher::Budget::Spent() const
{
#ifdef NZBGET_USE_RUST
    return nzbget_rs_dupe_budget_spent(m_rust) != 0;
#else
    return !m_unlimited && m_left.load() == 0;
#endif
}

void NzbFetcher::Stats::Add(const Stats& other)
{
	ok += other.ok;
	fetch += other.fetch;
	parse += other.parse;
	refused += other.refused;
	relisted += other.relisted;
	listingMismatch += other.listingMismatch;
	budget += other.budget;
}

void NzbFetcher::SetStatePath(const std::string& path)
{
	std::lock_guard<std::mutex> guard(m_mutex);
	m_statePath = path;
}

void NzbFetcher::Load()
{
	std::lock_guard<std::mutex> guard(m_mutex);
	std::ifstream file(fs::u8path(m_statePath));
	std::string line;
	time_t now = Util::CurrentTime();
	while (std::getline(file, line))
	{
		std::stringstream stream(line);
		std::string indexer, until;
		if (std::getline(stream, indexer, '\t') && std::getline(stream, until, '\t'))
		{
			time_t when = (time_t)atoll(until.c_str());
			if (when > now)
			{
				m_refusedUntil[indexer] = when;
			}
		}
	}
}

// called with m_mutex held; written to a temporary file and renamed, so a
// crash can't lose a cooldown (or leave half of the file)
void NzbFetcher::Save()
{
	if (m_statePath.empty())
	{
		return;
	}
	std::ostringstream text;
	time_t now = Util::CurrentTime();
	for (const auto& entry : m_refusedUntil)
	{
		if (entry.second > now)
		{
			text << entry.first << '\t' << (long long)entry.second << "\t\n";
		}
	}
	if (!DupeUtil::WriteAtomic(m_statePath, text.str()))
	{
		warn("Could not save the DupeSearch indexer state to %s", m_statePath.c_str());
	}
}

std::mutex& NzbFetcher::IndexerLock(const std::string& indexer)
{
	std::lock_guard<std::mutex> guard(m_mutex);
	std::unique_ptr<std::mutex>& lock = m_indexerLocks[indexer];
	if (!lock)
	{
		lock = std::make_unique<std::mutex>();
	}
	return *lock;
}

bool NzbFetcher::IsRefused(const std::string& indexer)
{
	std::lock_guard<std::mutex> guard(m_mutex);
	auto it = m_refusedUntil.find(indexer);
	return it != m_refusedUntil.end() && it->second > Util::CurrentTime();
}

void NzbFetcher::Refuse(const std::string& indexer)
{
	std::lock_guard<std::mutex> guard(m_mutex);
	m_refusedUntil[indexer] = Util::CurrentTime() + CooldownSec;
	Save();
}

NzbFetcher::Fetched NzbFetcher::Fetch(const Newznab::Result& listing, time_t deadline, int retries, Budget* budget)
{
	Fetched fetched;
	fetched.listing = listing;
    if (budget && budget->Spent()) { fetched.reason = frBudget; return fetched; }
    if (HttpGet::Stopped() || Util::CurrentTime() >= deadline) return fetched;

	// one download per indexer at a time: its refusal is known before the next grab
	std::lock_guard<std::mutex> indexerGuard(IndexerLock(listing.indexer));
	if (IsRefused(listing.indexer))
	{
		fetched.reason = frRefused;
		return fetched;
	}

	int status = 0;
	for (int attempt = 0; attempt <= retries; attempt++)
	{
        if (HttpGet::Stopped() || Util::CurrentTime() >= deadline) break;
        if (budget && !budget->Take()) { fetched.reason = frBudget; return fetched; }
		std::string why;
		// the deadline ends a download that drips, not only the retries
		long long deadlineMs = DonorHealth::NowMs() + (long long)(deadline - Util::CurrentTime()) * 1000;
		HttpGet::Reply reply = m_fetch ? m_fetch(listing.link, "DupeSearch nzb of " + listing.indexer, MaxNzbBytes, std::max(1LL, deadlineMs)) :
			HttpGet::Fetch(listing.link, "DupeSearch nzb of " + listing.indexer, MaxNzbBytes, std::max(1LL, deadlineMs));
		if (reply.ok)
		{
			status = 0;
			NzbSummary info;
			if (NzbReader::Parse(reply.body, info))
			{
				fetched.reason = frOk;
				fetched.data = std::move(reply.body);
				fetched.info = std::move(info);
				return fetched;
			}
			// an error answer served with HTTP 200 (code 300, code 429) lands
			// here too: retried, but no sign of a grab limit by itself
			fetched.reason = frParse;
			why = "not an nzb-file: " + Newznab::Mask(reply.body.substr(0, 160));
		}
		else
		{
			status = reply.status;
			fetched.reason = frFetch;
			why = "HTTP " + std::to_string(reply.status);
		}
		info("DupeSearch: the nzb-file of %s from %s failed (attempt %i): %s",
			listing.title.c_str(), listing.indexer.c_str(), attempt + 1, why.c_str());

        if (budget && budget->Spent()) break;
		if (attempt < retries)
		{
			// no time for the pause: no more attempts (they went out at once,
			// each one an indexer grab, and a 429 was asked again unpaused)
			if (Util::CurrentTime() + RetryDelaySec >= deadline)
			{
				break;
			}
			for (int waited = 0; waited < RetryDelaySec * 10 && !HttpGet::Stopped(); waited++)
			{
				Util::Sleep(100);
			}
		}
		if (HttpGet::Stopped())
		{
			break;
		}
	}

	if ((status == 403 || status == 429) && !listing.indexer.empty())
	{
		Refuse(listing.indexer);
		info("DupeSearch: indexer %s refused nzb-file downloads (HTTP %i): not asking it for %i minutes",
			listing.indexer.c_str(), status, CooldownSec / 60);
	}
	return fetched;
}

NzbFetcher::Fetched NzbFetcher::FetchPosting(const Posting::Group& listings, time_t deadline, Stats& stats, Budget* budget)
{
	Fetched last;
    if (listings.empty()) { stats.parse++; return last; }
	last.listing = listings.front();
	bool haveOther = false;
	Fetched other;

	for (size_t i = 0; i < listings.size(); i++)
	{
		Fetched fetched = Fetch(listings[i], deadline, 1, budget);
        if (fetched.reason == frBudget) { stats.budget++; last = std::move(fetched); break; }
		if (fetched.reason == frOk && !Posting::ListingMismatch(listings[i], fetched.info.totalBytes))
		{
			stats.ok++;
			// the other listings of the posting were not fetched: the same posting
			stats.relisted += (int)(listings.size() - i - 1);
			return fetched;
		}
		if (fetched.reason == frOk)
		{
			if (!haveOther)
			{
				other = std::move(fetched);
				haveOther = true;
			}
			continue;
		}
		switch (fetched.reason)
		{
			case frFetch: stats.fetch++; break;
			case frParse: stats.parse++; break;
			case frRefused: stats.refused++; break;
			default: break;
		}
		last = std::move(fetched);
	}

	if (haveOther)
	{
		stats.ok++;
		stats.listingMismatch++;
		return other;
	}
	return last;
}
