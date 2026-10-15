// SPDX-License-Identifier: GPL-2.0-or-later
#include "nzbget.h"

#include <boost/test/unit_test.hpp>
#include <array>
#include <fstream>
#include <iterator>
#include "DirectRenamer.h"

namespace
{
class TestRenamer : public DirectRenamer
{
	void RenameCompleted(DownloadQueue*, NzbInfo*) override {}
};

std::array<char, 64> ParHeader()
{
	std::array<char, 64> header{};
	memcpy(header.data(), "PAR2\0PKT", 8);
	return header;
}
}

BOOST_AUTO_TEST_SUITE(QueueTest)
BOOST_AUTO_TEST_SUITE(DirectRenamerContent)

#ifndef DISABLE_PARCHECK
BOOST_AUTO_TEST_CASE(CompleteHeaderIsVisibleBeforeArticleDownloaded)
{
	TestRenamer renamer;
	auto header = ParHeader();
	for (size_t size : {size_t(64), size_t(2472)})
	{
		auto analyzer = renamer.MakeArticleContentAnalyzer();
		std::vector<char> bytes(size, 0);
		std::copy(header.begin(), header.end(), bytes.begin());
		analyzer->Reset();
		analyzer->Append(bytes.data(), (int)bytes.size());
		// QueueCoordinator reads this flag before ArticleDownloaded calls Finish.
		BOOST_CHECK(DirectRenamer::AnalyzedParFile(analyzer.get()));
	}
}

BOOST_AUTO_TEST_CASE(SplitHeaderIsVisibleOnItsCompletingPiece)
{
	TestRenamer renamer;
	auto header = ParHeader();
	for (int split = 1; split < (int)header.size(); ++split)
	{
		auto analyzer = renamer.MakeArticleContentAnalyzer();
		analyzer->Reset();
		analyzer->Append(header.data(), split);
		BOOST_CHECK(!DirectRenamer::AnalyzedParFile(analyzer.get()));
		analyzer->Append(header.data() + split, (int)header.size() - split);
		BOOST_CHECK(DirectRenamer::AnalyzedParFile(analyzer.get()));
	}
}

BOOST_AUTO_TEST_CASE(CommittedParIndexIsVisibleFromOneAppend)
{
	std::ifstream input(fs::current_path() / "parchecker" / "testfile.par2", std::ios::binary);
	BOOST_REQUIRE(input.is_open());
	std::vector<char> bytes{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
	BOOST_REQUIRE_EQUAL(bytes.size(), 4608u);
	BOOST_REQUIRE_EQUAL(memcmp(bytes.data(), "PAR2\0PKT", 8), 0);
	TestRenamer renamer;
	auto analyzer = renamer.MakeArticleContentAnalyzer();
	analyzer->Reset();
	analyzer->Append(bytes.data(), (int)bytes.size());
	BOOST_CHECK(DirectRenamer::AnalyzedParFile(analyzer.get()));
}

BOOST_AUTO_TEST_CASE(PartialAndNonParDataCannotAuthorizeBorrowing)
{
	TestRenamer renamer;
	auto header = ParHeader();
	for (int size = 0; size < (int)header.size(); ++size)
	{
		auto analyzer = renamer.MakeArticleContentAnalyzer();
		analyzer->Reset();
		analyzer->Append(header.data(), size);
		BOOST_CHECK(!DirectRenamer::AnalyzedParFile(analyzer.get()));
	}
	for (size_t byte = 0; byte < 8; ++byte)
	{
		auto invalid = header;
		invalid[byte] ^= 1;
		auto analyzer = renamer.MakeArticleContentAnalyzer();
		analyzer->Reset();
		analyzer->Append(invalid.data(), (int)invalid.size());
		BOOST_CHECK(!DirectRenamer::AnalyzedParFile(analyzer.get()));
	}
}
#else
BOOST_AUTO_TEST_CASE(DisabledParCheckHasNoContentAuthority)
{
	TestRenamer renamer;
	auto analyzer = renamer.MakeArticleContentAnalyzer();
	auto header = ParHeader();
	analyzer->Reset();
	analyzer->Append(header.data(), (int)header.size());
	BOOST_CHECK(!DirectRenamer::AnalyzedParFile(analyzer.get()));
}
#endif

BOOST_AUTO_TEST_SUITE_END()
BOOST_AUTO_TEST_SUITE_END()
