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

#include <boost/test/unit_test.hpp>
#include "NzbReader.h"
#include "DupeIdentity.h"
#include "Posting.h"
#include "Util.h"
#include "NzbFetcher.h"
#include <thread>
#include <atomic>
#include <stdexcept>

namespace
{

struct NzbFile
{
	std::string name;
	std::vector<int> sizes;
};

std::string MakeNzb(const std::vector<NzbFile>& files, const std::string& prefix, const std::string& meta = "")
{
	std::string xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<nzb xmlns=\"http://www.newzbin.com/DTD/2003/nzb\">\n";
	if (!meta.empty())
	{
		xml += "<head><meta type=\"imdb\">" + meta + "</meta></head>\n";
	}
	for (size_t f = 0; f < files.size(); f++)
	{
		xml += "<file poster=\"poster@example.com\" date=\"1\" subject=\"[1/1] &quot;" + files[f].name + "&quot; yEnc (1/1)\">"
			"<groups><group>alt.binaries.test</group></groups><segments>";
		for (size_t s = 0; s < files[f].sizes.size(); s++)
		{
			xml += "<segment bytes=\"" + std::to_string(files[f].sizes[s]) + "\" number=\"" + std::to_string(s + 1) + "\">" +
				prefix + "-" + std::to_string(f) + "-" + std::to_string(s) + "@x</segment>";
		}
		xml += "</segments></file>\n";
	}
	return xml + "</nzb>\n";
}

Newznab::Result Listing(const char* link, long long size, int grabs, time_t date, const char* indexer = "idx")
{
	Newznab::Result result;
	result.title = "t";
	result.link = link;
	result.size = size;
	result.grabs = grabs;
	result.date = date;
	result.indexer = indexer;
	return result;
}

std::vector<std::string> Ids(const char* prefix, int count, int from = 0)
{
	std::vector<std::string> ids;
	for (int i = from; i < from + count; i++)
	{
		ids.push_back(std::string(prefix) + std::to_string(i) + "@x");
	}
	std::sort(ids.begin(), ids.end());
	return ids;
}

}

BOOST_AUTO_TEST_SUITE(DupeSearchTest)

BOOST_AUTO_TEST_CASE(NzbReaderCountsBytesNamesIdsTest)
{
	NzbSummary info;
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "rel.part1.rar", { 100, 100 } }, { "rel.par2", { 50 } } }, "a", "tt123"), info));
	BOOST_CHECK_EQUAL(info.files, 2);
	BOOST_CHECK_EQUAL(info.totalBytes, 250);
	BOOST_CHECK(info.filenames == (std::set<std::string>{ "rel.part1.rar", "rel.par2" }));
	BOOST_CHECK(info.messageIds == (std::vector<std::string>{ "a-0-0@x", "a-0-1@x", "a-1-0@x" }));
	BOOST_CHECK_EQUAL(info.meta["imdb"], "tt123");
	BOOST_CHECK_EQUAL(info.poster, "poster@example.com");

	// the fingerprint depends on the message-ids only
	NzbSummary other;
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "other", { 1, 2 } }, { "x", { 3 } } }, "a"), other));
	BOOST_CHECK_EQUAL(info.Fingerprint(), other.Fingerprint());
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "other", { 1, 2 } }, { "x", { 3 } } }, "b"), other));
	BOOST_CHECK_NE(info.Fingerprint(), other.Fingerprint());
}

BOOST_AUTO_TEST_CASE(NzbReaderMainNameTest)
{
	NzbSummary info;
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "small.nfo", { 10 } }, { "big.mkv", { 100, 100 } }, { "mid.par2", { 50 } } }, "a"), info));
	BOOST_CHECK_EQUAL(info.mainName, "big.mkv");

	// a par2 volume is never the main file
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "abc.vol063-121.par2", { 500 } }, { "Show.S01E01.1080p.WEB.H264-GRP.mkv", { 100 } } }, "a"), info));
	BOOST_CHECK_EQUAL(info.mainName, "Show.S01E01.1080p.WEB.H264-GRP.mkv");

	// only par2 files: the largest of them
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "a.par2", { 5 } }, { "a.vol0+1.par2", { 50 } } }, "a"), info));
	BOOST_CHECK_EQUAL(info.mainName, "a.vol0+1.par2");
}

BOOST_AUTO_TEST_CASE(NzbReaderNativeIdentityMetadataTest)
{
	NzbSummary info;
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "small.nfo", { 10 } }, { "big.part1.rar", { 100, 100 } },
		{ "rel.vol0+1.par2", { 500 } }, { "rel.par2", { 50 } } }, "identity"), info));
	BOOST_CHECK_EQUAL(info.dataBytes, 210);
	BOOST_CHECK_EQUAL(info.dataFiles, 2);
	BOOST_REQUIRE_EQUAL(info.heads.size(), 2);
	BOOST_CHECK_EQUAL(info.heads[0].name, "big.part1.rar");
	BOOST_CHECK_EQUAL(info.heads[0].messageId, "identity-1-0@x");
	BOOST_CHECK_EQUAL(info.heads[0].bytes, 200);
	BOOST_CHECK_EQUAL(info.heads[1].name, "small.nfo");

	// Input order is not part order, and an invalid first id is no identity source.
	std::string xml = "<nzb><file subject='&quot;x.rar&quot;'><segments>"
		"<segment number='2' bytes='100'>second@x</segment>"
		"<segment number='1' bytes='100'>first@x</segment></segments></file></nzb>";
	BOOST_REQUIRE(NzbReader::Parse(xml, info));
	BOOST_REQUIRE_EQUAL(info.heads.size(), 1);
	BOOST_CHECK_EQUAL(info.heads[0].messageId, "first@x");
	BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "only.par2", { 50 } } }, "p"), info));
	BOOST_CHECK_EQUAL(info.dataBytes, 0);
	BOOST_CHECK_EQUAL(info.dataFiles, 0);
	BOOST_CHECK(info.heads.empty());
}

BOOST_AUTO_TEST_CASE(NativeIdentityHintTest)
{
    NzbSummary pick, donor;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "rel.part1.rar", { 200 } }, { "rel.par2", { 10 } } }, "pick"), pick));
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "rel.part1.rar", { 200 } }, { "rel.vol1+9.par2", { 90 } } }, "donor"), donor));
    BOOST_CHECK(DupeIdentity::SameData(pick, donor));
    BOOST_CHECK(DupeIdentity::Hints(pick, donor, true) == (std::vector<std::string>{ "DupeSameSize=1", "DupeSameInner=1" }));
    donor.dataFiles++;
    BOOST_CHECK(!DupeIdentity::SameData(pick, donor));
    BOOST_CHECK(DupeIdentity::Hints(pick, donor, false).empty());
#ifdef NZBGET_USE_RUST
    std::vector<char> body{ 'v', 'i', 'd', 'e', 'o' };
    DupeIdentity::Identity mine = DupeIdentity::FromArticle(body, "Show.S01E01.1080p.WEB.H264-GRP.mkv", 100000, 100);
    BOOST_REQUIRE((bool)mine);
    BOOST_CHECK_EQUAL(mine.bytes, 100000);
    BOOST_CHECK_EQUAL(mine.extension, "mkv");
    DupeIdentity::Identity renamed = mine;
    renamed.name = "a8f3c9e1b7d24f60.mkv";
    BOOST_CHECK(DupeIdentity::Matches("Show.S01E01.1080p.WEB.H264-GRP", "hash.rar", mine, renamed));
    renamed.name = "Other.S01E01.1080p.WEB.H264-GRP.mkv";
    BOOST_CHECK(!DupeIdentity::Matches("Show.S01E01.1080p.WEB.H264-GRP", "hash.rar", mine, renamed));
    BOOST_CHECK(!DupeIdentity::FromArticle(body, "sample.mkv", 100000, 100));
#endif
}

BOOST_AUTO_TEST_CASE(NativeIdentityDuplicateFileGeometryTest)
{
    NzbSummary separate, joined;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "same.rar", { 100 } }, { "same.rar", { 100 } } }, "a"), separate));
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "same.rar", { 200 } } }, "b"), joined));
    BOOST_CHECK_EQUAL(separate.dataFiles, 2);
    BOOST_CHECK(!DupeIdentity::SameData(separate, joined));
    BOOST_REQUIRE_EQUAL(separate.heads.size(), 2);
    BOOST_CHECK_NE(separate.heads[0].messageId, separate.heads[1].messageId);
}

#ifdef NZBGET_USE_RUST
BOOST_AUTO_TEST_CASE(NativeIdentityFetchExceptionTest)
{
    NzbSummary info;
    info.dataBytes = 200;
    info.heads = { { "first.mkv", "a@x", 100 }, { "second.mkv", "b@x", 100 } };
    int attempts = 0;
    auto found = DupeIdentity::Read(info, Util::CurrentTime() + 10,
        [&](const std::string&, const std::vector<CString>&) -> ArticleFetcher::FetchedArticle {
            if (++attempts == 1) throw std::runtime_error("fake transport exception");
            ArticleFetcher::FetchedArticle result;
            result.Success = true;
            result.FileSize = 1000;
            result.Data = { 'v' };
            return result;
        });
    BOOST_CHECK_EQUAL(attempts, 2);
    BOOST_CHECK((bool)found);
    BOOST_CHECK_EQUAL(found.bytes, 1000);
}
#endif

BOOST_AUTO_TEST_CASE(NativeFetchBudgetChargesRetriesTest)
{
    NzbFetcher::Budget budget(1);
    int calls = 0;
    NzbFetcher fetcher([&](const std::string&, const std::string&, size_t, long long) {
        calls++;
        HttpGet::Reply reply;
        reply.ok = true;
        reply.status = 200;
        reply.body = "<html>indexer error</html>";
        return reply;
    });
    auto listing = Listing("http://fake.invalid/one", 1, 0, 1);
    fetcher.Fetch(listing, Util::CurrentTime() + 20, 3, &budget);
    BOOST_CHECK_EQUAL(calls, 3);
    BOOST_CHECK(budget.Spent());
}

BOOST_AUTO_TEST_CASE(NativeFetchBudgetCooldownIsFreeTest)
{
    NzbFetcher::Budget budget(1);
    int calls = 0;
    NzbFetcher fetcher([&](const std::string&, const std::string&, size_t, long long) {
        calls++;
        HttpGet::Reply reply;
        reply.status = 403;
        return reply;
    });
    auto listing = Listing("http://fake.invalid/two", 1, 0, 1, "limited");
    fetcher.Fetch(listing, Util::CurrentTime() + 10, 0, &budget);
    BOOST_CHECK_EQUAL(fetcher.Fetch(listing, Util::CurrentTime() + 10, 0, &budget).reason, NzbFetcher::frRefused);
    BOOST_CHECK_EQUAL(calls, 1);
    BOOST_CHECK(budget.Take());
    BOOST_CHECK(budget.Take());
    BOOST_CHECK(!budget.Take());
}

BOOST_AUTO_TEST_CASE(NativeFetchBudgetConcurrentTest)
{
    NzbFetcher::Budget budget(1);
    std::atomic<int> admitted{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < 16; i++) threads.emplace_back([&]() { if (budget.Take()) admitted++; });
    for (auto& thread : threads) thread.join();
    BOOST_CHECK_EQUAL(admitted.load(), 3);
    BOOST_CHECK(budget.Spent());
    NzbFetcher::Budget unlimited(0);
    for (int i = 0; i < 100; i++) BOOST_REQUIRE(unlimited.Take());
    BOOST_CHECK(!unlimited.Spent());
}

#ifdef NZBGET_USE_RUST
BOOST_AUTO_TEST_CASE(NativePartialNzbHealthTest)
{
    NzbSummary info;
    std::string xml="<nzb><file subject='&quot;rel.part01.rar&quot; yEnc (1/150)'><segments>"
        "<segment number='1' bytes='10000'>a@x</segment>"
        "<segment number='2' bytes='10000'>b@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml,info));
    BOOST_CHECK_EQUAL(info.listedParts,2);
    BOOST_CHECK_EQUAL(info.declaredParts,150);
    BOOST_CHECK_EQUAL(info.articleBytes,10000);
    BOOST_CHECK_EQUAL(DupeIdentity::WholeBytes(info),1500000);
    DonorHealth::Health health;
    health.present=13;
    NzbSummary fractional;
    fractional.listedParts=3;
    fractional.declaredParts=10;
    BOOST_CHECK_CLOSE(DupeIdentity::Alive(health,fractional),13.0/43.0,0.00001);
    BOOST_CHECK_EQUAL(DupeIdentity::UnlistedMissing(health,fractional),30);
    health.present=5;health.error=5;
    fractional.listedParts=1;fractional.declaredParts=2;
    BOOST_CHECK_CLOSE(DupeIdentity::Alive(health,fractional),0.25,0.00001);
    health.present=0;health.error=2;
    BOOST_CHECK_EQUAL(DupeIdentity::Alive(health,fractional),-1);
    fractional.listedParts=5; fractional.declaredParts=150;
    health.present=5; health.missing=0; health.error=0;
    BOOST_CHECK(DupeIdentity::IsDead(health,fractional,10));
    fractional.declaredParts=5;
    BOOST_CHECK(!DupeIdentity::IsDead(health,fractional,10));
}
#endif

BOOST_AUTO_TEST_CASE(NativeDataArticleIdsExcludeParityTest)
{
    NzbSummary info;
    std::string xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
        "<segment number='1' bytes='100'>discarded@x</segment>"
        "<segment number='2' bytes='100'>a-data@x</segment>"
        "<segment number='1' bytes='100'>z-data@x</segment>"
        "<segment number='3' bytes='100'>z-data@x</segment></segments></file>"
        "<file subject='&quot;rel.vol00+25.PAR2&quot;'><segments>";
    for (int i = 1; i <= 25; i++)
        xml += "<segment number='" + std::to_string(i) + "' bytes='10'>par-" + std::to_string(i) + "@x</segment>";
    xml += "</segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.dataBytes, 300);
    const std::vector<std::string> expected = { "a-data@x", "z-data@x" };
    BOOST_CHECK_EQUAL_COLLECTIONS(info.dataMessageIds.begin(), info.dataMessageIds.end(), expected.begin(), expected.end());
    BOOST_CHECK_EQUAL(info.messageIds.size(), 27);
    BOOST_CHECK(std::find(info.messageIds.begin(), info.messageIds.end(), "discarded@x") == info.messageIds.end());
    const std::string originalFingerprint = info.Fingerprint();
    const size_t parityId = xml.find("par-1@x");
    BOOST_REQUIRE(parityId != std::string::npos);
    xml.replace(parityId, 7, "par-new@x");
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL_COLLECTIONS(info.dataMessageIds.begin(), info.dataMessageIds.end(), expected.begin(), expected.end());
    BOOST_CHECK_NE(info.Fingerprint(), originalFingerprint);

    // Keep measurable data IDs even when malformed data withholds geometry.
    xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
        "<segment number='1' bytes='100'>valid@x</segment>"
        "<segment number='2' bytes='100'>invalid id@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.dataBytes, 0);
    BOOST_REQUIRE_EQUAL(info.dataMessageIds.size(), 1);
    BOOST_CHECK_EQUAL(info.dataMessageIds[0], "valid@x");
}

BOOST_AUTO_TEST_CASE(NativeDataPartGeometryExcludesParityTest)
{
    NzbSummary info;
    std::string xml = "<nzb><file subject='&quot;rel.mkv&quot; yEnc (1/150)'><segments>"
        "<segment number='1' bytes='100'>data-1@x</segment>"
        "<segment number='2' bytes='100'>data-2@x</segment></segments></file>"
        "<file subject='&quot;rel.vol00+25.par2&quot;'><segments>";
    for (int i = 1; i <= 25; i++)
        xml += "<segment number='" + std::to_string(i) + "' bytes='10'>par-" + std::to_string(i) + "@x</segment>";
    xml += "</segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.listedParts, 27);
    BOOST_CHECK_EQUAL(info.declaredParts, 175);
    BOOST_CHECK_EQUAL(info.dataListedParts, 2);
    BOOST_CHECK_EQUAL(info.dataDeclaredParts, 150);
    BOOST_CHECK_EQUAL(info.dataMessageIds.size(), 2);

    // Numbered data gaps remain data geometry, independently of PAR parts.
    xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
        "<segment number='1' bytes='100'>data-1@x</segment>"
        "<segment number='3' bytes='100'>data-3@x</segment></segments></file>"
        "<file subject='&quot;rel.par2&quot;'><segments>"
        "<segment number='1' bytes='10'>par@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.dataListedParts, 2);
    BOOST_CHECK_EQUAL(info.dataDeclaredParts, 3);
    BOOST_CHECK_EQUAL(info.listedParts, 3);
    BOOST_CHECK_EQUAL(info.declaredParts, 4);
}


BOOST_AUTO_TEST_CASE(NativeDeclaredTailGuardTableTest)
{
    struct Case
    {
        const char* name;
        std::vector<std::pair<long long, long long>> parts;
        const char* tail;
        bool parity;
        uint64_t listed, declared;
        long long bytes;
        bool geometry;
    };
    auto MakeParts = [](int count)
    {
        std::vector<std::pair<long long, long long>> parts;
        for (int n = 1; n <= count; n++) parts.emplace_back(n, 100);
        return parts;
    };
    const std::vector<Case> cases = {
		{"true_tail", {{1, 100}, {2, 100}}, "(1/150)", false, 2, 150, 200, true},
		{"number_gap_without_tail", {{1, 100}, {3, 100}}, "(1/0)", false, 2, 3, 200, true},
		{"single_segment", {{9374, 100}}, "(1/10000)", false, 1, 9374, 100, true},
		{"zero_subject_count", {{1, 100}, {2, 100}}, "(1/0)", false, 2, 2, 200, true},
		{"max_subject_count", {{1, 100}, {2, 100}}, "(1/200000)", false, 2, 200000, 200, true},
		{"over_max_subject_count", {{1, 100}, {2, 100}}, "(1/200001)", false, 2, 2, 200, true},
		{"two_thirds_equal", MakeParts(200), "(1/300)", false, 200, 200, 20000, true},
		{"two_thirds_below", MakeParts(199), "(1/300)", false, 199, 300, 19900, true},
		{"tail_gap_99", {{1, 100}, {101, 100}}, "(1/200)", false, 2, 101, 200, true},
		{"tail_gap_100", {{1, 100}, {101, 100}}, "(1/201)", false, 2, 201, 200, true},
		{"zero_part_number", {{0, 100}, {2, 100}}, "(1/1000)", false, 2, 2, 200, true},
		{"negative_part_number", {{-1, 100}, {2, 100}}, "(1/1000)", false, 2, 2, 200, true},
		{"invalid_number_suppresses_valid_max", {{1, 100}, {199999, 100}, {200001, 100}}, "(1/200000)", false, 3, 3, 300, true},
		{"maximum_valid_part", {{1, 100}, {200000, 100}}, "(1/200000)", false, 2, 200000, 200, true},
		{"zero_bytes", {{1, 100}, {2, 0}}, "(1/150)", false, 2, 2, 100, false},
		{"negative_bytes", {{1, 100}, {2, -1}}, "(1/150)", false, 2, 2, 99, false},
		{"strict_majority_short_last", {{1, 100}, {2, 100}, {3, 98}}, "(1/150)", false, 3, 3, 298, true},
		{"strict_majority_large_last", {{1, 100}, {2, 100}, {3, 101}}, "(1/150)", false, 3, 3, 301, true},
		{"strict_majority_equal_last", {{1, 100}, {2, 98}, {3, 100}}, "(1/150)", false, 3, 150, 298, true},
		{"median_exact_99_percent", {{1, 900}, {2, 1000}, {3, 1100}, {4, 990}}, "(1/150)", false, 4, 150, 3990, true},
		{"median_below_99_percent", {{1, 900}, {2, 1000}, {3, 1100}, {4, 989}}, "(1/150)", false, 4, 4, 3989, true},
		{"half_is_not_strict_majority", {{1, 99}, {2, 100}, {3, 99}, {4, 100}}, "(1/150)", false, 4, 150, 398, true},
		{"parity_never_infers", {{1, 100}, {2, 100}}, "(1/150)", true, 2, 2, 200, true},
		{"malformed_tail", {{1, 100}, {3, 100}}, "(x/150)", false, 2, 3, 200, true},
		{"trailing_subject_whitespace", {{1, 100}, {2, 100}}, "(1/150)  ", false, 2, 150, 200, true},
		{"unsorted_input", {{3, 100}, {1, 100}, {2, 100}}, "(1/150)", false, 3, 150, 300, true},
		{"duplicate_keeps_last_bytes", {{1, 100}, {2, 100}, {2, 30}}, "(1/150)", false, 2, 2, 130, true},
    };
    BOOST_REQUIRE_EQUAL(cases.size(), 27);
    for (const auto& c : cases)
    {
        BOOST_TEST_CONTEXT(c.name)
        {
            const std::string name = c.parity ? "guard.par2" : "guard.mkv";
            std::string xml = "<nzb><file subject='&quot;" + name + "&quot; yEnc " + c.tail + "'><segments>";
            for (size_t i = 0; i < c.parts.size(); i++)
                xml += "<segment number='" + std::to_string(c.parts[i].first) + "' bytes='" +
                    std::to_string(c.parts[i].second) + "'>guard-" + std::to_string(i) + "@x</segment>";
            xml += "</segments></file></nzb>";
            NzbSummary info;
            BOOST_REQUIRE(NzbReader::Parse(xml, info));
            BOOST_CHECK_EQUAL(info.files, 1);
            BOOST_CHECK_EQUAL(info.listedParts, c.listed);
            BOOST_CHECK_EQUAL(info.declaredParts, c.declared);
            BOOST_CHECK_EQUAL(info.dataListedParts, c.parity ? 0 : c.listed);
            BOOST_CHECK_EQUAL(info.dataDeclaredParts, c.parity ? 0 : c.declared);
            BOOST_CHECK_EQUAL(info.messageIds.size(), c.listed);
            BOOST_CHECK_EQUAL(info.dataMessageIds.size(), c.parity ? 0 : c.listed);
            BOOST_CHECK_EQUAL(info.totalBytes, c.bytes);
            BOOST_CHECK_EQUAL(info.dataBytes, c.parity || !c.geometry ? 0 : c.bytes);
            BOOST_CHECK_EQUAL(info.dataFiles, c.parity || !c.geometry ? 0 : 1);
            if (std::string(c.name) == "duplicate_keeps_last_bytes")
            {
                BOOST_CHECK(std::find(info.messageIds.begin(), info.messageIds.end(), "guard-1@x") == info.messageIds.end());
                BOOST_CHECK(std::find(info.messageIds.begin(), info.messageIds.end(), "guard-2@x") != info.messageIds.end());
            }
        }
    }
}

BOOST_AUTO_TEST_CASE(NativeEmptyFilePartCountsTest)
{
    const std::string empty = "<file subject='&quot;empty.mkv&quot; yEnc (1/150)'><segments></segments></file>";
    NzbSummary info;
    BOOST_CHECK(!NzbReader::Parse("<nzb>" + empty + "</nzb>", info));
    const std::string valid = "<file subject='&quot;valid.mkv&quot;'><segments>"
        "<segment number='1' bytes='100'>valid@x</segment></segments></file>";
    BOOST_REQUIRE(NzbReader::Parse("<nzb>" + empty + valid + "</nzb>", info));
    BOOST_CHECK_EQUAL(info.files, 2);
    BOOST_CHECK_EQUAL(info.listedParts, 1);
    BOOST_CHECK_EQUAL(info.declaredParts, 1);
    BOOST_CHECK_EQUAL(info.dataListedParts, 1);
    BOOST_CHECK_EQUAL(info.dataDeclaredParts, 1);
    BOOST_CHECK_EQUAL(info.totalBytes, 100);
    // An empty data file makes whole-NZB data geometry unknown.
    BOOST_CHECK_EQUAL(info.dataBytes, 0);
    BOOST_CHECK_EQUAL(info.dataFiles, 0);
    BOOST_CHECK(info.heads.empty());
    BOOST_REQUIRE_EQUAL(info.messageIds.size(), 1);
    BOOST_CHECK_EQUAL(info.messageIds[0], "valid@x");
}

BOOST_AUTO_TEST_CASE(NativeDuplicateSegmentKeepsLastTest)
{
    NzbSummary info;
    std::string xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
        "<segment number='1' bytes='50'>old@x</segment>"
        "<segment number='2' bytes='200'>second@x</segment>"
        "<segment number='1' bytes='100'>last@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.totalBytes, 300);
    BOOST_CHECK_EQUAL(info.dataBytes, 300);
    BOOST_CHECK_EQUAL(info.listedParts, 2);
    BOOST_CHECK_EQUAL(info.declaredParts, 2);
    BOOST_CHECK_EQUAL(info.messageIds.size(), 2);
    BOOST_CHECK(std::find(info.messageIds.begin(), info.messageIds.end(), "old@x") == info.messageIds.end());
    BOOST_REQUIRE_EQUAL(info.heads.size(), 1);
    BOOST_CHECK_EQUAL(info.heads[0].messageId, "last@x");

    // Repeated XML entries are one unique part, not evidence for tail inference.
    xml = "<nzb><file subject='&quot;rel.mkv&quot; yEnc (1/150)'><segments>"
        "<segment number='1' bytes='100'>old@x</segment>"
        "<segment number='1' bytes='100'>last@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.listedParts, 1);
    BOOST_CHECK_EQUAL(info.declaredParts, 1);
}

BOOST_AUTO_TEST_CASE(NativeDuplicateSegmentInvalidLastTest)
{
    NzbSummary info;
    for (const std::string& last : { std::string("<segment number='1' bytes='100'>invalid id@x</segment>"),
        std::string("<segment number='1' bytes='0'>last@x</segment>") })
    {
        std::string xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
            "<segment number='1' bytes='100'>old@x</segment>"
            "<segment number='2' bytes='200'>second@x</segment>" + last + "</segments></file></nzb>";
        BOOST_REQUIRE(NzbReader::Parse(xml, info));
        BOOST_CHECK_EQUAL(info.dataBytes, 0);
        BOOST_CHECK(info.heads.empty());
        BOOST_CHECK(std::find(info.messageIds.begin(), info.messageIds.end(), "old@x") == info.messageIds.end());
        BOOST_CHECK_EQUAL(info.totalBytes, 200);
    }
    // An invalid overwritten occurrence is absent from the queued file.
    std::string xml = "<nzb><file subject='&quot;rel.mkv&quot;'><segments>"
        "<segment number='1' bytes='0'>invalid id@x</segment>"
        "<segment number='1' bytes='100'>last@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(xml, info));
    BOOST_CHECK_EQUAL(info.dataBytes, 100);
    BOOST_REQUIRE_EQUAL(info.heads.size(), 1);
    BOOST_CHECK_EQUAL(info.heads[0].messageId, "last@x");
}

BOOST_AUTO_TEST_CASE(NativeIndependentParityCollectionsUnknownTest)
{
    for (bool reverse : { false, true })
    {
        NzbSummary info;
        std::vector<NzbFile> files = {
            { "first.par2", { 100 } }, { "first.vol00+01.par2", { 200 } },
            { "second.par2", { 300 } }, { "second.vol00+01.par2", { 400 } },
            { "first.mkv", { 1000 } }, { "second.mkv", { 2000 } }
        };
        if (reverse) std::reverse(files.begin(), files.end());
        BOOST_REQUIRE(NzbReader::Parse(MakeNzb(files, "par-sets"), info));
        BOOST_CHECK_EQUAL(info.dataBytes, 3000);
        BOOST_CHECK(info.parIndex.messageId.empty());
        BOOST_CHECK(info.recoveryBytes.empty());
    }
}

BOOST_AUTO_TEST_CASE(NativeParityIndexByFilenameTest)
{
    NzbSummary info;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({
        { "rel.vol00+01.par2", { 100 } },
        { "rel.par2", { 900 } },
        { "rel.vol01+02.PAR2", { 200 } },
        { "other.vol00+10.par2", { 1000 } },
        { "rel.mkv", { 10000 } }
    }, "par-index"), info));
    BOOST_CHECK_EQUAL(info.parIndex.name, "rel.par2");
    BOOST_REQUIRE_EQUAL(info.recoveryBytes.size(), 2);
    BOOST_CHECK_EQUAL(info.recoveryBytes[0], 100);
    BOOST_CHECK_EQUAL(info.recoveryBytes[1], 200);

    // Without an identifiable base index, recovery capacity is unknown.
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({
        { "rel.vol00+01.par2", { 100 } },
        { "rel.vol01+02.par2", { 200 } },
        { "rel.mkv", { 10000 } }
    }, "par-volumes"), info));
    BOOST_CHECK(info.parIndex.messageId.empty());
    BOOST_CHECK(info.recoveryBytes.empty());
}

BOOST_AUTO_TEST_CASE(NativeIdentityParitySuffixTest)
{
    NzbSummary pick, donor;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } } }, "p"), pick));
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } }, { "movie.vol1+2.mkv", { 500 } } }, "d"), donor));
    BOOST_CHECK_EQUAL(donor.dataBytes, 700);
    BOOST_CHECK_EQUAL(donor.dataFiles, 2);
    BOOST_CHECK_EQUAL(donor.mainName, "movie.vol1+2.mkv");
    BOOST_CHECK(!DupeIdentity::SameData(pick, donor));
}

BOOST_AUTO_TEST_CASE(NativeIdentityUnquotedParityTest)
{
    NzbSummary donor;
    std::string nzb = "<nzb><file subject='ordinary.mkv yEnc (1/1)'><segments>"
        "<segment number='1' bytes='200'>data@x</segment></segments></file>"
        "<file subject='rel.vol001+002.PAR2 yEnc (1/20)'><segments>"
        "<segment number='1' bytes='500'>par@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(nzb, donor));
    BOOST_CHECK_EQUAL(donor.dataBytes, 200);
    BOOST_CHECK_EQUAL(donor.dataFiles, 1);
    BOOST_CHECK_EQUAL(donor.mainName, "ordinary.mkv");
    BOOST_CHECK_EQUAL(donor.heads.size(), 1);
}

BOOST_AUTO_TEST_CASE(NativeIdentityInvalidIdsTest)
{
    NzbSummary pick, donor;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } } }, "p"), pick));
    std::string broken = "<nzb><file subject='&quot;ordinary.mkv&quot;'><segments>"
        "<segment number='1' bytes='200'>good@x</segment></segments></file>"
        "<file subject='&quot;extra.rar&quot;'><segments>"
        "<segment number='1' bytes='300'>invalid id@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(broken, donor));
    BOOST_CHECK_EQUAL(donor.dataBytes, 0);
    BOOST_CHECK_EQUAL(donor.dataFiles, 0);
    BOOST_CHECK(donor.heads.empty());
    BOOST_CHECK(!DupeIdentity::SameData(pick, donor));
    // A malformed segment inside an otherwise valid file also makes its geometry unknown.
    broken = "<nzb><file subject='&quot;ordinary.mkv&quot;'><segments>"
        "<segment number='1' bytes='200'>good@x</segment>"
        "<segment number='2' bytes='300'>invalid id@x</segment></segments></file></nzb>";
    BOOST_REQUIRE(NzbReader::Parse(broken, donor));
    BOOST_CHECK(!DupeIdentity::SameData(pick, donor));
    BOOST_CHECK(donor.heads.empty());
}

BOOST_AUTO_TEST_CASE(NativeIdentityEmptyDataFileTest)
{
    NzbSummary pick, donor;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } } }, "p"), pick));
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } }, { "empty.rar", {} } }, "d"), donor));
    BOOST_CHECK_EQUAL(donor.dataBytes, 0);
    BOOST_CHECK_EQUAL(donor.dataFiles, 0);
    BOOST_CHECK(donor.heads.empty());
    BOOST_CHECK(!DupeIdentity::SameData(pick, donor));
}

BOOST_AUTO_TEST_CASE(NativeIdentityParityGeometryIndependenceTest)
{
    NzbSummary pick, donor;
    BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } } }, "p"), pick));
    for (int parityBytes : { 0, -10 })
    {
        BOOST_REQUIRE(NzbReader::Parse(MakeNzb({ { "ordinary.mkv", { 200 } }, { "extra.PAR2", { parityBytes } } }, "d"), donor));
        BOOST_CHECK_EQUAL(donor.dataBytes, 200);
        BOOST_CHECK_EQUAL(donor.dataFiles, 1);
        BOOST_CHECK_EQUAL(donor.heads.size(), 1);
        BOOST_CHECK(DupeIdentity::SameData(pick, donor));
    }
}

BOOST_AUTO_TEST_CASE(NzbReaderRejectsBadNzbTest)
{
	NzbSummary info;
	BOOST_CHECK(!NzbReader::Parse("<nzb><file", info));
	BOOST_CHECK(!NzbReader::Parse("<nzb></nzb>", info));
	BOOST_CHECK(!NzbReader::Parse("", info));
	BOOST_CHECK(!NzbReader::Parse("<html><body>Forbidden</body></html>", info));
	BOOST_CHECK(!NzbReader::Parse("<?xml version=\"1.0\"?><error code=\"429\" description=\"Request limit reached\"/>", info));

	// declared entities (billion laughs), also after padding
	std::string bomb = "<?xml version=\"1.0\"?><!DOCTYPE n [<!ENTITY a \"aaaa\"><!ENTITY b \"&a;&a;\">]>"
		"<nzb><file subject=\"&b;\"><segments><segment bytes=\"1\">x@y</segment></segments></file></nzb>";
	BOOST_CHECK(!NzbReader::Parse(bomb, info));
	std::string padded = "<?xml version=\"1.0\"?><!--" + std::string(8000, ' ') + "-->" + bomb.substr(bomb.find("<!DOCTYPE"));
	BOOST_CHECK(!NzbReader::Parse(padded, info));

	// a standard doctype is fine
	std::string standard = MakeNzb({ { "a.mkv", { 5 } } }, "a");
	standard.insert(standard.find("<nzb"),
		"<!DOCTYPE nzb PUBLIC \"-//newzBin//DTD NZB 1.1//EN\" \"http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd\">\n");
	BOOST_CHECK(NzbReader::Parse(standard, info));
	BOOST_CHECK_EQUAL(info.files, 1);
}

BOOST_AUTO_TEST_CASE(PostingSketchTest)
{
	std::vector<std::string> a = Ids("a", 6000);
	// a re-listed posting with two re-uploaded segments is the same posting, another posting is not
	std::vector<std::string> reupload = Ids("a", 5996, 2);
	reupload.push_back("z1@x");
	reupload.push_back("z2@x");
	std::sort(reupload.begin(), reupload.end());
	std::vector<std::string> other = Ids("b", 6000);

	BOOST_CHECK_EQUAL(Posting::MakeSketch(a).size(), 64U);
	BOOST_CHECK(Posting::SameSketch(Posting::MakeSketch(a), Posting::MakeSketch(reupload)));
	BOOST_CHECK(!Posting::SameSketch(Posting::MakeSketch(a), Posting::MakeSketch(other)));

	// tiny postings too
	std::vector<std::string> tiny = { "t1@x", "t2@x" };
	BOOST_CHECK(Posting::SameSketch(Posting::MakeSketch(tiny), Posting::MakeSketch(tiny)));
	BOOST_CHECK(!Posting::SameSketch(Posting::MakeSketch(tiny), Posting::Sketch()));
	BOOST_CHECK(!Posting::SameSketch(Posting::Sketch(), Posting::Sketch()));
}

BOOST_AUTO_TEST_CASE(PostingSamePostingTest)
{
	std::vector<std::string> a = Ids("a", 1000);
	// the same articles, an almost identical copy (2% differ), a partial overlap of 0.5%, no overlap
	BOOST_CHECK(Posting::SamePosting(a, a));
	BOOST_CHECK(Posting::SamePosting(a, Ids("a", 980, 20)));
	std::vector<std::string> partial = Ids("a", 5);
	std::vector<std::string> rest = Ids("c", 995);
	partial.insert(partial.end(), rest.begin(), rest.end());
	std::sort(partial.begin(), partial.end());
	BOOST_CHECK(!Posting::SamePosting(a, partial));
	BOOST_CHECK(!Posting::SamePosting(a, Ids("b", 1000)));
}

BOOST_AUTO_TEST_CASE(PostingGroupListingsTest)
{
	// one posting on three indexers: same size, usenet dates seconds apart
	std::vector<Posting::Group> groups = Posting::GroupListings({
		Listing("a", 5000, 10, 1000), Listing("b", 5000, 5, 1003), Listing("c", 5000, 1, 1010) });
	BOOST_REQUIRE_EQUAL(groups.size(), 1U);
	BOOST_CHECK_EQUAL(groups[0].size(), 3U);

	// a repost of the same files: the same size at another time is another posting
	groups = Posting::GroupListings({ Listing("a", 5000, 10, 1000), Listing("b", 5000, 5, 1000 + 3600) });
	BOOST_CHECK_EQUAL(groups.size(), 2U);

	// the window runs from the first listing of a group
	groups = Posting::GroupListings({ Listing("a", 5000, 1, 1000), Listing("b", 5000, 1, 1100), Listing("c", 5000, 1, 1200) });
	BOOST_REQUIRE_EQUAL(groups.size(), 2U);
	BOOST_CHECK_EQUAL(groups[0].size(), 2U);

	// other sizes don't group
	BOOST_CHECK_EQUAL(Posting::GroupListings({ Listing("a", 5000, 1, 1000), Listing("b", 5001, 1, 1000) }).size(), 2U);

	// listings without a size or a date never group
	BOOST_CHECK_EQUAL(Posting::GroupListings({ Listing("a", 0, 0, 1000), Listing("b", 0, 0, 1001), Listing("c", 0, 0, 1002) }).size(), 3U);
	BOOST_CHECK_EQUAL(Posting::GroupListings({ Listing("a", 5000, 0, 0), Listing("b", 5000, 0, 0) }).size(), 2U);
}

BOOST_AUTO_TEST_CASE(PostingListingMismatchTest)
{
	Newznab::Result listing = Listing("a", 10000, 1, 1);
	BOOST_CHECK(!Posting::ListingMismatch(listing, 10000));
	BOOST_CHECK(!Posting::ListingMismatch(listing, 10200));	// 2% off is fine
	BOOST_CHECK(Posting::ListingMismatch(listing, 10201));
	BOOST_CHECK(Posting::ListingMismatch(listing, 9000));
	BOOST_CHECK(!Posting::ListingMismatch(Listing("a", 0, 1, 1), 123456));	// no listed size: nothing to compare
}

BOOST_AUTO_TEST_CASE(PostingOrderPostingsTest)
{
	// closest size first, then grabs, then date
	std::vector<Posting::Group> order = Posting::OrderPostings({
		Listing("far", 9000, 99, 1), Listing("near", 5100, 1, 1), Listing("exact", 5000, 0, 1),
		Listing("exactmore", 5000, 7, 5000) }, 5000, 0);
	BOOST_REQUIRE_EQUAL(order.size(), 4U);
	BOOST_CHECK_EQUAL(order[0][0].link, "exactmore");	// one posting of each distinct size first: exact size, most grabs
	BOOST_CHECK_EQUAL(order[1][0].link, "near");
	BOOST_CHECK_EQUAL(order[2][0].link, "far");
	BOOST_CHECK_EQUAL(order[3][0].link, "exact");		// the second posting of a size comes after

	// a posting's listings: the most grabbed first
	order = Posting::OrderPostings({ Listing("a", 5000, 1, 1000, "A"), Listing("b", 5000, 9, 1002, "B"),
		Listing("c", 5000, 4, 1004, "C") }, 5000, 0);
	BOOST_REQUIRE_EQUAL(order.size(), 1U);
	BOOST_CHECK_EQUAL(order[0][0].link, "b");
	BOOST_CHECK_EQUAL(order[0][1].link, "c");
	BOOST_CHECK_EQUAL(order[0][2].link, "a");

	// at most three times the wanted duplicates
	std::vector<Newznab::Result> many;
	for (int i = 0; i < 20; i++)
	{
		many.push_back(Listing(("l" + std::to_string(i)).c_str(), 5000 + i, 1, 1));
	}
	BOOST_CHECK_EQUAL(Posting::OrderPostings(many, 5000, 2).size(), 6U);
	BOOST_CHECK_EQUAL(Posting::OrderPostings(many, 5000, 0).size(), 20U);
	BOOST_CHECK_EQUAL(Posting::OrderPostings(many, 5000, -1).size(), 20U);
}

BOOST_AUTO_TEST_SUITE_END()
