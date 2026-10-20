/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2026 Denis <denis@nzbget.com>
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 */

#include "nzbget.h"

#include <boost/test/unit_test.hpp>
#include <fstream>
#include <sstream>
#include "Options.h"
#include "ScriptConfig.h"
#if defined(__APPLE__) || defined(__linux__)
#include <sys/stat.h>
#include <future>
#include <thread>
#endif

BOOST_AUTO_TEST_SUITE(ExtensionTest)

struct TempConfigFile
{
	fs::path path = fs::temp_directory_path() / fs::make_unique_filename();

	~TempConfigFile()
	{
		fs::error_code error;
		fs::remove(path, error);
	}
};

struct OptionsGuard
{
	Options* oldOptions = g_Options;

	~OptionsGuard()
	{
		g_Options = oldOptions;
	}
};

BOOST_AUTO_TEST_CASE(SaveConfigDoesNotAppendDuplicateOptionNames)
{
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config\n";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	Options::OptEntries optEntries;
	optEntries.emplace_back("Extension.Option", "first");
	optEntries.emplace_back("extension.option", "second");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string firstContents;
	{
		std::ifstream firstFile(configFile.path);
		std::stringstream contents;
		contents << firstFile.rdbuf();
		firstContents = contents.str();
	}
	// one line only, carrying the last entry's value - Options::SetOption
	// resolves duplicates the same way, so the file matches what nzbget loads
	BOOST_CHECK_EQUAL(firstContents, "# existing config\nExtension.Option=second\n");

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string secondContents;
	{
		std::ifstream secondFile(configFile.path);
		std::stringstream contents;
		contents << secondFile.rdbuf();
		secondContents = contents.str();
	}
	BOOST_CHECK_EQUAL(secondContents, firstContents);
}

BOOST_AUTO_TEST_CASE(SaveConfigRemovesDuplicateLinesFromDamagedConfig)
{
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config\n"
			<< "Server1.Active=yes\n"
			<< "Server2.Active=yes\n"
			<< "Server2.Active=yes\n"
			<< "server2.active=yes\n"
			<< "Server2.Host=news.example.com\n";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	Options::OptEntries optEntries;
	optEntries.emplace_back("Server1.Active", "yes");
	optEntries.emplace_back("Server2.Active", "no");
	optEntries.emplace_back("Server2.Host", "news.example.com");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string contents;
	{
		std::ifstream file(configFile.path);
		std::stringstream buffer;
		buffer << file.rdbuf();
		contents = buffer.str();
	}
	BOOST_CHECK_EQUAL(contents,
		"# existing config\n"
		"Server1.Active=yes\n"
		"Server2.Active=no\n"
		"Server2.Host=news.example.com\n");
}

// When a config file carries duplicate lines for one option, Options::SetOption
// overwrites the same entry while parsing, so the LAST line is the value nzbget
// actually runs on. Collapsing the duplicates must preserve that value,
// otherwise saving a damaged config silently changes settings.
BOOST_AUTO_TEST_CASE(SaveConfigKeepsLastValueWhenConfigHasDuplicateLines)
{
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config\n"
			<< "Server2.Active=yes\n"
			<< "Server2.Name=xsusenet\n"
			<< "server2.active=no\n";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	// as loadconfig reports it: raw file lines, duplicates included
	Options::OptEntries optEntries;
	optEntries.emplace_back("Server2.Active", "yes");
	optEntries.emplace_back("Server2.Name", "xsusenet");
	optEntries.emplace_back("server2.active", "no");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string contents;
	{
		std::ifstream file(configFile.path);
		std::stringstream buffer;
		buffer << file.rdbuf();
		contents = buffer.str();
	}
	// one line per option, keeping the first occurrence's name and position
	// but the last occurrence's value - exactly what Options::SetOption does
	BOOST_CHECK_EQUAL(contents,
		"# existing config\n"
		"Server2.Active=no\n"
		"Server2.Name=xsusenet\n");
}

BOOST_AUTO_TEST_CASE(SaveConfigDropsOrphanedOptionLines)
{
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config\n"
			<< "ActiveOption=yes\n"
			<< "RemovedExtension.Option=old_value\n";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	Options::OptEntries optEntries;
	optEntries.emplace_back("ActiveOption", "yes");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string contents;
	{
		std::ifstream file(configFile.path);
		std::stringstream buffer;
		buffer << file.rdbuf();
		contents = buffer.str();
	}
	BOOST_CHECK_EQUAL(contents,
		"# existing config\n"
		"ActiveOption=yes\n");
}

BOOST_AUTO_TEST_CASE(SaveConfigNormalizesOptionNameCasing)
{
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config\n"
			<< "server2.active=yes\n";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	Options::OptEntries optEntries;
	optEntries.emplace_back("Server2.Active", "no");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::string contents;
	{
		std::ifstream file(configFile.path);
		std::stringstream buffer;
		buffer << file.rdbuf();
		contents = buffer.str();
	}
	BOOST_CHECK_EQUAL(contents,
		"# existing config\n"
		"Server2.Active=no\n");
}

BOOST_AUTO_TEST_CASE(SaveConfigLastLineWithoutLineEnd)
{
	// a last line without a line end had the first new option glued onto it
	TempConfigFile configFile;
	{
		std::ofstream output(configFile.path);
		output << "# existing config";
	}

	OptionsGuard optionsGuard;
	Options options("nzbget", configFile.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;

	Options::OptEntries optEntries;
	optEntries.emplace_back("Extension.Option", "value");
	ScriptConfig scriptConfig;

	BOOST_REQUIRE(scriptConfig.SaveConfig(&optEntries));
	std::ifstream file(configFile.path);
	std::stringstream contents;
	contents << file.rdbuf();
	BOOST_CHECK_EQUAL(contents.str(), "# existing config\nExtension.Option=value\n");
}

#if defined(__APPLE__) || defined(__linux__)
static std::string ReadCipherTestFile(const fs::path& path)
{
	std::ifstream file(path, std::ios::binary);
	return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

BOOST_AUTO_TEST_CASE(CipherPatchConflictPreservesOriginal)
{
	TempConfigFile file;
	{ std::ofstream out(file.path); out << "# unchanged\nExtension.Option=original\n"; }
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config;
	std::string snapshot; BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	{ std::ofstream out(file.path); out << "# concurrent change\nExtension.Option=new\n"; }
	auto before = ReadCipherTestFile(file.path);
	BOOST_CHECK(config.CommitCipherPatch(snapshot, "replacement", [] { return false; }) == ScriptConfig::CipherCommit::Conflict);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), before);
}

BOOST_AUTO_TEST_CASE(CipherPatchPreservesModeAndExactBytes)
{
	TempConfigFile file;
	{ std::ofstream out(file.path, std::ios::binary); out << "# original\r\nExtension.Option=private\r\n"; }
	BOOST_REQUIRE(chmod(file.path.string().c_str(), 0640) == 0);
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config;
	std::string snapshot; BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	std::string replacement = snapshot + "# appended\r\n";
	BOOST_CHECK(config.CommitCipherPatch(snapshot, replacement, [] { return false; }) == ScriptConfig::CipherCommit::Saved);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), replacement);
	struct stat metadata; BOOST_REQUIRE(stat(file.path.string().c_str(), &metadata) == 0);
	BOOST_CHECK_EQUAL(metadata.st_mode & 07777, 0640);
}

BOOST_AUTO_TEST_CASE(CipherPatchRejectsSymlink)
{
	TempConfigFile file, link;
	{ std::ofstream out(file.path); out << "Extension.Option=original\n"; }
	fs::create_symlink(file.path, link.path);
	OptionsGuard guard;
	Options options("nzbget", link.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config; std::string snapshot;
	BOOST_CHECK(!config.ReadCipherSnapshot(snapshot));
	BOOST_CHECK(config.CommitCipherPatch("", "replacement", [] { return false; }) == ScriptConfig::CipherCommit::Failed);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), "Extension.Option=original\n");
}

BOOST_AUTO_TEST_CASE(CipherPatchRejectsDirectory)
{
	TempConfigFile file;
	fs::create_directory(file.path);
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;
	ScriptConfig config;
	std::string snapshot;
	BOOST_CHECK(!config.ReadCipherSnapshot(snapshot));
	BOOST_CHECK(config.CommitCipherPatch("", "replacement", [] { return false; }) == ScriptConfig::CipherCommit::Failed);
	BOOST_CHECK(fs::is_directory(file.path));
}

BOOST_AUTO_TEST_CASE(CipherPatchSerializesOrdinarySave)
{
	TempConfigFile file;
	{ std::ofstream output(file.path); output << "Server1.Host=example.invalid\nServer1.Cipher=old\n"; }
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr);
	g_Options = &options;
	ScriptConfig config;
	std::string snapshot;
	BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	Options::OptEntries saved;
	BOOST_REQUIRE(config.LoadConfig(&saved));
	std::string baseline = ScriptConfig::CipherBaseline(saved);
	Options::OptEntries entries;
	entries.emplace_back("Server1.Host", "example.invalid");
	entries.emplace_back("Server1.Cipher", "ordinary");
	std::promise<void> go, entered;
	std::promise<bool> finished;
	auto ready = go.get_future(); auto started = entered.get_future(); auto done = finished.get_future();
	std::thread writer([&] {
		ready.wait(); entered.set_value();
		try { finished.set_value(config.SaveConfig(&entries, baseline.c_str())); }
		catch (...) { finished.set_value(false); }
	});
	bool triggered = false, blocked = false;
	auto committed = config.CommitCipherPatch(snapshot, "Server1.Host=example.invalid\nServer1.Cipher=optimized\n", [&] {
		if (!triggered)
		{
			triggered = true; go.set_value();
			if (started.wait_for(std::chrono::seconds(1)) == std::future_status::ready)
				blocked = done.wait_for(std::chrono::milliseconds(25)) == std::future_status::timeout;
		}
		return false;
	});
	if (!triggered) go.set_value();
	writer.join();
	BOOST_CHECK(blocked);
	BOOST_CHECK(committed == ScriptConfig::CipherCommit::Saved);
	BOOST_CHECK(!done.get());
	BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	BOOST_CHECK_EQUAL(snapshot, "Server1.Host=example.invalid\nServer1.Cipher=optimized\n");
}

BOOST_AUTO_TEST_CASE(CipherBaselineCanonicalValuesAndOrdinarySaveFirst)
{
	Options::OptEntries parity;
	parity.emplace_back("Server1.Host", "h\xc3\xa9");
	parity.emplace_back("Server1.Cipher", "old");
	parity.emplace_back("server1.cipher", "");
	parity.emplace_back("Server1.Port", "563");
	parity.emplace_back("Server01.Host", "ignored");
	BOOST_CHECK_EQUAL(ScriptConfig::CipherBaseline(parity), "v1\nserver1.cipher=\nserver1.host=68c3a9\nserver1.port=353633\n");
	Options::OptEntries absent; absent.emplace_back("Server1.Host", "h\xc3\xa9"); absent.emplace_back("Server1.Port", "563");
	BOOST_CHECK(ScriptConfig::CipherBaseline(parity) != ScriptConfig::CipherBaseline(absent));
	TempConfigFile file;
	{ std::ofstream out(file.path); out << "Server1.Host=example.invalid\nServer1.Cipher=old\n"; }
	OptionsGuard guard; Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config; std::string original; BOOST_REQUIRE(config.ReadCipherSnapshot(original));
	Options::OptEntries entries; BOOST_REQUIRE(config.LoadConfig(&entries));
	std::string token = ScriptConfig::CipherBaseline(entries);
	entries.emplace_back("Server1.Cipher", "ordinary");
	bool conflict = true; BOOST_REQUIRE(config.SaveConfig(&entries, token.c_str(), &conflict)); BOOST_CHECK(!conflict);
	BOOST_CHECK(config.CommitCipherPatch(original, "Server1.Host=example.invalid\nServer1.Cipher=optimized\n", [] { return false; }) == ScriptConfig::CipherCommit::Conflict);
	std::string changed = ReadCipherTestFile(file.path);
	BOOST_CHECK(!config.SaveConfig(&entries, token.c_str(), &conflict)); BOOST_CHECK(conflict);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), changed);
}

BOOST_AUTO_TEST_CASE(CipherPatchCancelledDuringWritePreservesOriginal)
{
	TempConfigFile file;
	{ std::ofstream out(file.path); out << "Extension.Option=original\n"; }
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config; std::string snapshot; BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	int calls = 0;
	BOOST_CHECK(config.CommitCipherPatch(snapshot, "replacement", [&] { return ++calls >= 2; }) == ScriptConfig::CipherCommit::Cancelled);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), snapshot);
}

BOOST_AUTO_TEST_CASE(CancelAfterCommitReportsSaved)
{
	TempConfigFile file;
	{ std::ofstream out(file.path); out << "Extension.Option=original\n"; }
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config; std::string snapshot; BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	int calls = 0;
	// A cancel observable only after the final precommit check cannot undo rename.
	BOOST_CHECK(config.CommitCipherPatch(snapshot, "replacement", [&] { return ++calls > 3; }) == ScriptConfig::CipherCommit::Saved);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), "replacement");
}

BOOST_AUTO_TEST_CASE(CipherPatchCreationFailurePreservesOriginal)
{
	TempConfigFile file;
	file.path = file.path.parent_path() / std::string(250, 'x');
	{ std::ofstream out(file.path); out << "Extension.Option=original\n"; }
	OptionsGuard guard;
	Options options("nzbget", file.path.string().c_str(), true, nullptr, nullptr); g_Options = &options;
	ScriptConfig config; std::string snapshot; BOOST_REQUIRE(config.ReadCipherSnapshot(snapshot));
	BOOST_CHECK(config.CommitCipherPatch(snapshot, "replacement", [] { return false; }) == ScriptConfig::CipherCommit::Failed);
	BOOST_CHECK_EQUAL(ReadCipherTestFile(file.path), snapshot);
}
#endif

BOOST_AUTO_TEST_SUITE_END()
