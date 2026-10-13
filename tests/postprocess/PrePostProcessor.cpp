#include "nzbget.h"

#include <boost/test/unit_test.hpp>
#include "DownloadInfo.h"
#include "Options.h"
#include "PrePostProcessor.h"
#include "QueueScript.h"

BOOST_AUTO_TEST_SUITE(PostprocessTest)

namespace
{
class CompletionQueue final : public DownloadQueue
{
public:
	CompletionQueue() { Init(this); }
	~CompletionQueue() { Final(); }
	bool EditEntry(int, EEditAction, const char*) override { return false; }
	bool EditList(IdList*, NameList*, EMatchMode, EEditAction, const char*) override { return false; }
	void HistoryChanged() override {}
	void Save() override {}
	void SaveChanged() override {}
};

class NamedPostProcessor final : public PrePostProcessor
{
public:
	void Named(DownloadQueue* queue, NzbInfo* nzb)
	{
		DownloadQueue::Aspect aspect = { DownloadQueue::eaNzbNamed, queue, nzb, nullptr };
		Update(nullptr, &aspect);
	}
};

struct CompletionFixture
{
	Options* previousOptions = g_Options;
	QueueScriptCoordinator* previousScripts = g_QueueScriptCoordinator;
	CompletionQueue queue;
	QueueScriptCoordinator scripts;
	std::unique_ptr<Options> options;
	std::unique_ptr<NamedPostProcessor> processor;
	NzbInfo* nzb = nullptr;

	CompletionFixture()
	{
		Options::CmdOptList cmdOpts;
		cmdOpts.emplace_back("SevenZipCmd=7z");
		cmdOpts.emplace_back("UnrarCmd=unrar");
		cmdOpts.emplace_back("WriteLog=none");
		cmdOpts.emplace_back("NzbLog=no");
		cmdOpts.emplace_back("DirectUnpack=no");
		options = std::make_unique<Options>(&cmdOpts, nullptr);
		g_QueueScriptCoordinator = &scripts;
		processor = std::make_unique<NamedPostProcessor>();
		auto info = std::make_unique<NzbInfo>();
		info->SetName("LateRename");
		info->SetDirectRenameStatus(NzbInfo::tsSuccess);
		info->GetCompletedFiles()->emplace_back(1, "movie.mkv", "obfuscated.bin",
			CompletedFile::cfSuccess, 0, false, "", "");
		auto parity = std::make_unique<FileInfo>();
		parity->SetFilename("movie.vol001+01.par2");
		parity->SetParFile(true);
		parity->SetPaused(true);
		parity->SetSize(1000);
		parity->SetRemainingSize(1000);
		parity->SetNzbInfo(info.get());
		info->GetFileList()->Add(std::move(parity), false);
		nzb = info.get();
		queue.GetQueue()->Add(std::move(info));
	}

	~CompletionFixture()
	{
		queue.Detach(processor.get());
		processor.reset();
		g_QueueScriptCoordinator = previousScripts;
		options.reset();
		g_Options = previousOptions;
	}
};
}

BOOST_FIXTURE_TEST_CASE(DirectRenameSchedulesCompletedDownload, CompletionFixture)
{
	// Data finished before the asynchronous direct renamer paused the last
	// in-progress PAR volumes. There will be no further file-completion event.
	BOOST_REQUIRE(nzb->IsDownloadCompleted(true));
	BOOST_REQUIRE(!nzb->GetPostInfo());
	processor->Named(&queue, nzb);
	BOOST_REQUIRE(nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 1);
	// A later name notification must not enqueue the collection twice.
	processor->Named(&queue, nzb);
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 1);
}

BOOST_FIXTURE_TEST_CASE(DirectRenameWaitsForRemainingData, CompletionFixture)
{
	nzb->GetFileList()->begin()->get()->SetParFile(false);
	BOOST_REQUIRE(!nzb->IsDownloadCompleted(true));
	processor->Named(&queue, nzb);
	BOOST_CHECK(!nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 0);
}

BOOST_FIXTURE_TEST_CASE(DirectRenameWaitsForActiveDownloads, CompletionFixture)
{
	nzb->SetActiveDownloads(1);
	processor->Named(&queue, nzb);
	BOOST_CHECK(!nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 0);
	nzb->SetActiveDownloads(0);
}

BOOST_FIXTURE_TEST_CASE(DirectRenameWaitsForRenamerToFinish, CompletionFixture)
{
	nzb->SetDirectRenameStatus(NzbInfo::tsRunning);
	processor->Named(&queue, nzb);
	BOOST_CHECK(!nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 0);
}

BOOST_FIXTURE_TEST_CASE(DirectRenameDoesNotCompleteHealthDeletion, CompletionFixture)
{
	nzb->SetDeleteStatus(NzbInfo::dsHealth);
	processor->Named(&queue, nzb);
	BOOST_CHECK(!nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 0);
}

BOOST_FIXTURE_TEST_CASE(DirectRenameSchedulesAfterPausedRequestsDrain, CompletionFixture)
{
	nzb->SetActiveDownloads(1);
	processor->Named(&queue, nzb);
	BOOST_REQUIRE(!nzb->GetPostInfo());
	nzb->SetActiveDownloads(0);
	processor->CheckDownloadCompleted(&queue, nzb);
	BOOST_REQUIRE(nzb->GetPostInfo());
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 1);
	processor->CheckDownloadCompleted(&queue, nzb);
	BOOST_CHECK_EQUAL(processor->GetJobCount(), 1);
}

BOOST_AUTO_TEST_SUITE_END()
