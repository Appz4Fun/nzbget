/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2007-2019 Andrey Prygunkov <hugbug@users.sourceforge.net>
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
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */


#include "nzbget.h"
#include "CommandLineParser.h"
#include "Log.h"
#include "MessageBase.h"
#include "DownloadInfo.h"
#include "FileSystem.h"
#include "Util.h"
#ifdef NZBGET_USE_RUST
#include <exception>
#include <stdexcept>
#include "nzbget_rs.h"
#endif

#ifdef HAVE_GETOPT_LONG
static struct option long_options[] =
	{
		{"help", no_argument, nullptr, 'h'},
		{"configfile", required_argument, nullptr, 'c'},
		{"noconfigfile", no_argument, nullptr, 'n'},
		{"printconfig", no_argument, nullptr, 'p'},
		{"server", no_argument, nullptr, 's' },
		{"daemon", no_argument, nullptr, 'D' },
		{"version", no_argument, nullptr, 'v'},
		{"serverversion", no_argument, nullptr, 'V'},
		{"option", required_argument, nullptr, 'o'},
		{"append", no_argument, nullptr, 'A'},
		{"list", no_argument, nullptr, 'L'},
		{"pause", no_argument, nullptr, 'P'},
		{"unpause", no_argument, nullptr, 'U'},
		{"rate", required_argument, nullptr, 'R'},
		{"system", no_argument, nullptr, 'B'},
		{"log", required_argument, nullptr, 'G'},
		{"top", no_argument, nullptr, 'T'},
		{"edit", required_argument, nullptr, 'E'},
		{"connect", no_argument, nullptr, 'C'},
		{"quit", no_argument, nullptr, 'Q'},
		{"reload", no_argument, nullptr, 'O'},
		{"write", required_argument, nullptr, 'W'},
		{"category", required_argument, nullptr, 'K'},
		{"scan", no_argument, nullptr, 'S'},
		{nullptr, 0, nullptr, 0}
	};
#endif

static char short_options[] = "c:hno:psvAB:DCE:G:K:LPR:STUQOVW:";


#ifdef NZBGET_USE_RUST
// a callback that threw stops the parser; the exception is rethrown after
// Rust returned
struct CommandLineParser::RsSink
{
	CommandLineParser* parser;
	char** argv;
	std::exception_ptr error;

	// getopt permutes pointers, not CString objects. Transfer the existing
	// ownership into that order without aliasing a vector<CString> as char**.
	void SyncArgs() noexcept
	{
		for (CString& arg : parser->m_args) arg.Unbind();
		for (size_t i = 0; i < parser->m_args.size(); i++) parser->m_args[i].Bind(argv[i]);
	}

	template <typename F>
	static int Call(void* ctx, F f) noexcept
	{
		RsSink* sink = static_cast<RsSink*>(ctx);
		try
		{
			f(sink->parser);
			return 0;
		}
		catch (...)
		{
			sink->error = std::current_exception();
			return -1;
		}
	}
};

int CommandLineParser::RsSetInt(void* ctx, int field, int value)
{
	// in the order of rust/src/cmdline.rs: edit, and the dupe modes and log kinds
	static const int EDIT_ACTIONS[] = {
		DownloadQueue::eaPostDelete, DownloadQueue::eaHistoryDelete, DownloadQueue::eaHistoryReturn,
		DownloadQueue::eaHistoryProcess, DownloadQueue::eaHistoryRedownload, DownloadQueue::eaHistoryRetryFailed,
		DownloadQueue::eaHistorySetParameter, DownloadQueue::eaHistoryMarkBad, DownloadQueue::eaHistoryMarkGood,
		DownloadQueue::eaHistoryMarkSuccess, DownloadQueue::eaGroupMoveTop, DownloadQueue::eaFileMoveTop,
		DownloadQueue::eaGroupMoveBottom, DownloadQueue::eaFileMoveBottom, DownloadQueue::eaGroupPause,
		DownloadQueue::eaFilePause, DownloadQueue::eaGroupPauseAllPars, DownloadQueue::eaFilePauseAllPars,
		DownloadQueue::eaGroupPauseExtraPars, DownloadQueue::eaFilePauseExtraPars, DownloadQueue::eaGroupResume,
		DownloadQueue::eaFileResume, DownloadQueue::eaGroupDelete, DownloadQueue::eaFileDelete,
		DownloadQueue::eaGroupParkDelete, DownloadQueue::eaGroupSortFiles, DownloadQueue::eaGroupApplyCategory,
		DownloadQueue::eaGroupSetCategory, DownloadQueue::eaGroupSetName, DownloadQueue::eaGroupMerge,
		DownloadQueue::eaFileSplit, DownloadQueue::eaGroupSetParameter, DownloadQueue::eaGroupSetPriority,
		DownloadQueue::eaGroupMoveOffset, DownloadQueue::eaFileMoveOffset};
	static const int DUPE_MODES[] = {dmScore, dmAll, dmForce};
	static const int LOG_KINDS[] = {(int)Message::mkInfo, (int)Message::mkWarning, (int)Message::mkError,
		(int)Message::mkDetail, (int)Message::mkDebug};
	return RsSink::Call(ctx, [field, value](CommandLineParser* p)
	{
		switch (field)
		{
			case 0: p->m_noConfig = value; break;
			case 1: p->m_printUsage = value; break;
			case 2: p->m_printVersion = value; break;
			case 3: p->m_printOptions = value; break;
			case 4: p->m_serverMode = value; break;
			case 5: p->m_daemonMode = value; break;
			case 6: p->m_remoteClientMode = value; break;
			case 7: p->m_clientOperation = (EClientOperation)value; break;
			case 8: p->m_addTop = value; break;
			case 9: p->m_addPaused = value; break;
			case 10: p->m_addPriority = value; break;
			case 11: p->m_addDupeScore = value; break;
			case 12: p->m_addDupeMode = DUPE_MODES[value]; break;
			case 13: p->m_matchMode = (EMatchMode)value; break;
			case 15: p->m_testBacktrace = value; break;
			case 16: p->m_webGet = value; break;
			case 17: p->m_sigVerify = value; break;
			case 18: p->m_logLines = value; break;
			case 19: p->m_editQueueAction = EDIT_ACTIONS[value]; break;
			case 20: p->m_editQueueOffset = value; break;
			case 21: p->m_writeLogKind = LOG_KINDS[value]; break;
			case 22: p->m_pauseDownload = value; break;
			case 23: p->m_errors = value; break;
		}
	});
}

int CommandLineParser::RsSetStr(void* ctx, int field, const char* value)
{
	return RsSink::Call(ctx, [field, value](CommandLineParser* p)
	{
		switch (field)
		{
			case 30: p->m_configFilename = value; break;
			case 31: p->m_webGetFilename = value; break;
			case 32: p->m_pubKeyFilename = value; break;
			case 33: p->m_sigFilename = value; break;
			case 34: p->SetAddCategory(value); break;
			case 35: p->m_lastArg = value; break;
			case 36: p->m_argFilename = value; break;
			// Keep the original host conversion, including its platform-specific
			// result for NaN and out-of-range values (not portable C++ behavior).
			case 40: p->m_setRate = (int)(atof(value) * 1024); break;
		}
	});
}

int CommandLineParser::RsSteal(void* ctx, int field, int index)
{
	return RsSink::Call(ctx, [ctx, field, index](CommandLineParser* p)
	{
		RsSink* sink = static_cast<RsSink*>(ctx);
		sink->SyncArgs();
		CString& arg = p->m_args[index];
		switch (field)
		{
			case 37: p->m_addNzbFilename = std::move(arg); break;
			case 38: p->m_addDupeKey = std::move(arg); break;
			case 39: p->m_editQueueText = std::move(arg); break;
		}
		sink->argv[index] = arg;
	});
}

int CommandLineParser::RsPushOption(void* ctx, const char* value)
{
	return RsSink::Call(ctx, [value](CommandLineParser* p) { p->m_optionList.push_back(value); });
}

int CommandLineParser::RsPushId(void* ctx, int id)
{
	return RsSink::Call(ctx, [id](CommandLineParser* p) { p->m_editQueueIdList.push_back(id); });
}

int CommandLineParser::RsPushName(void* ctx, const char* value)
{
	return RsSink::Call(ctx, [value](CommandLineParser* p) { p->m_editQueueNameList.push_back(value); });
}

int CommandLineParser::RsError(void* ctx, const char* msg)
{
	return RsSink::Call(ctx, [msg](CommandLineParser* p) { p->ReportError(msg); });
}

#ifdef HAVE_GETOPT_LONG
static int RsGetoptLong(int argc, char** argv) noexcept
{
	int index = 0;
	return getopt_long(argc, argv, short_options, long_options, &index);
}
#endif

CommandLineParser::CommandLineParser(int argc, const char* argv[])
{
	if (argc < 1 || !argv)
	{
		throw std::invalid_argument("Invalid command line");
	}
	// getopt_long reorders it (non-options to the end): rust/src/cmdline.rs
	// parses it in place, as InitCommandLine did
	m_args.reserve(argc);
	for (int i = 0; i < argc; i++)
	{
		m_args.emplace_back(argv[i]);
	}

	std::vector<char*> args;
	args.reserve(static_cast<size_t>(argc) + 1);
	for (CString& arg : m_args) args.push_back(arg);
	args.push_back(nullptr); // getopt's argv[argc] sentinel
	RsSink sink{this, args.data(), nullptr};
	NzbgetRsCmdlineSink rsSink{nullptr, &sink, RsSetInt, RsSetStr, RsSteal, RsPushOption, RsPushId, RsPushName, RsError};
#ifdef HAVE_GETOPT_LONG
	const int useLong = 1;
	rsSink.getoptLong = RsGetoptLong;
#else
	const int useLong = 0;
#endif
	int result = nzbget_rs_cmdline_parse(argc, args.data(), useLong, &rsSink);
	sink.SyncArgs();
	if (sink.error)
	{
		std::rethrow_exception(sink.error);
	}
	if (result != 0)
	{
		throw std::runtime_error("Command line parsing failed");
	}
}
#else
CommandLineParser::CommandLineParser(int argc, const char* argv[])
{
	InitCommandLine(argc, argv);

	if (argc == 1)
	{
		m_printUsage = true;
		return;
	}

	if (!m_printOptions && !m_printUsage && !m_printVersion)
	{
		// the arguments in getopt's order: optind counts in it (with an option
		// after the file, "-A file.nzb -c conf", the original order gave "conf")
		std::vector<const char*> args;
		for (CString& arg : m_args)
		{
			args.push_back(arg);
		}
		InitFileArg(argc, args.data());
	}
}
#endif

void CommandLineParser::InitCommandLine(int argc, const char* const_argv[])
{
	m_clientOperation = opClientNoOperation; // default

	// getopt_long reorders it (non-options to the end): kept for InitFileArg,
	// which reads the arguments from where getopt left optind
	std::vector<CString>& argv = m_args;
	argv.clear();
	argv.reserve(argc);
	for (int i = 0; i < argc; i++)
	{
		argv.emplace_back(const_argv[i]);
	}

	// reset getopt
	optind = 0;

	while (true)
	{
		int c;

#ifdef HAVE_GETOPT_LONG
		int option_index  = 0;
		c = getopt_long(argc, (char**)argv.data(), short_options, long_options, &option_index);
#else
		c = getopt(argc, (char**)argv.data(), short_options);
#endif

		if (c == -1) break;

		switch (c)
		{
			case 'c':
				m_configFilename = optarg;
				break;
			case 'n':
				m_configFilename = nullptr;
				m_noConfig = true;
				break;
			case 'h':
				m_printUsage = true;
				return;
			case 'v':
				m_printVersion = true;
				return;
			case 'p':
				m_printOptions = true;
				break;
			case 'o':
				m_optionList.push_back(optarg);
				break;
			case 's':
				m_serverMode = true;
				break;
			case 'D':
				m_serverMode = true;
				m_daemonMode = true;
				break;
			case 'A':
				m_clientOperation = opClientRequestDownload;

				while (true)
				{
					optind++;
					optarg = optind > argc ? nullptr : (char*)argv[optind-1];
					if (optarg && (!strcasecmp(optarg, "F") || !strcasecmp(optarg, "U")))
					{
						// option ignored (but kept for compatibility)
					}
					else if (optarg && !strcasecmp(optarg, "T"))
					{
						m_addTop = true;
					}
					else if (optarg && !strcasecmp(optarg, "P"))
					{
						m_addPaused = true;
					}
					else if (optarg && !strcasecmp(optarg, "I"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
						m_addPriority = atoi(argv[optind-1]);
					}
					else if (optarg && !strcasecmp(optarg, "C"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
						SetAddCategory(argv[optind-1]);
					}
					else if (optarg && !strcasecmp(optarg, "N"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
						m_addNzbFilename = std::move(argv[optind-1]);
					}
					else if (optarg && !strcasecmp(optarg, "DK"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
						m_addDupeKey = std::move(argv[optind-1]);
					}
					else if (optarg && !strcasecmp(optarg, "DS"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
						m_addDupeScore = atoi(argv[optind-1]);
					}
					else if (optarg && !strcasecmp(optarg, "DM"))
					{
						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}

						const char* dupeMode = argv[optind-1];
						if (!strcasecmp(dupeMode, "score"))
						{
							m_addDupeMode = dmScore;
						}
						else if (!strcasecmp(dupeMode, "all"))
						{
							m_addDupeMode = dmAll;
						}
						else if (!strcasecmp(dupeMode, "force"))
						{
							m_addDupeMode = dmForce;
						}
						else
						{
							ReportError("Could not parse value of option 'A'");
							return;
						}
					}
					else
					{
						optind--;
						break;
					}
				}
				break;
			case 'L':
				optind++;
				optarg = optind > argc ? nullptr : (char*)argv[optind-1];
				if (!optarg || !strncmp(optarg, "-", 1))
				{
					m_clientOperation = opClientRequestListFiles;
					optind--;
				}
				else if (!strcasecmp(optarg, "F") || !strcasecmp(optarg, "FR"))
				{
					m_clientOperation = opClientRequestListFiles;
				}
				else if (!strcasecmp(optarg, "G") || !strcasecmp(optarg, "GR"))
				{
					m_clientOperation = opClientRequestListGroups;
				}
				else if (!strcasecmp(optarg, "O"))
				{
					m_clientOperation = opClientRequestPostQueue;
				}
				else if (!strcasecmp(optarg, "S"))
				{
					m_clientOperation = opClientRequestListStatus;
				}
				else if (!strcasecmp(optarg, "H"))
				{
					m_clientOperation = opClientRequestHistory;
				}
				else if (!strcasecmp(optarg, "HA"))
				{
					m_clientOperation = opClientRequestHistoryAll;
				}
				else
				{
					ReportError("Could not parse value of option 'L'");
					return;
				}

				if (optarg && (!strcasecmp(optarg, "FR") || !strcasecmp(optarg, "GR")))
				{
					m_matchMode = mmRegEx;

					optind++;
					if (optind > argc)
					{
						ReportError("Could not parse value of option 'L'");
						return;
					}
					m_editQueueText = std::move(argv[optind-1]);
				}
				break;
			case 'P':
			case 'U':
				optind++;
				optarg = optind > argc ? nullptr : (char*)argv[optind-1];
				if (!optarg || !strncmp(optarg, "-", 1))
				{
					m_clientOperation = c == 'P' ? opClientRequestDownloadPause : opClientRequestDownloadUnpause;
					optind--;
				}
				else if (!strcasecmp(optarg, "D"))
				{
					m_clientOperation = c == 'P' ? opClientRequestDownloadPause : opClientRequestDownloadUnpause;
				}
				else if (!strcasecmp(optarg, "O"))
				{
					m_clientOperation = c == 'P' ? opClientRequestPostPause : opClientRequestPostUnpause;
				}
				else if (!strcasecmp(optarg, "S"))
				{
					m_clientOperation = c == 'P' ? opClientRequestScanPause : opClientRequestScanUnpause;
				}
				else
				{
					ReportError(c == 'P' ? "Could not parse value of option 'P'\n" : "Could not parse value of option 'U'");
					return;
				}
				break;
			case 'R':
				m_clientOperation = opClientRequestSetRate;
				m_setRate = (int)(atof(optarg)*1024);
				break;
			case 'B':
				if (!strcasecmp(optarg, "dump"))
				{
					m_clientOperation = opClientRequestDumpDebug;
				}
				else if (!strcasecmp(optarg, "trace"))
				{
					m_testBacktrace = true;
				}
				else if (!strcasecmp(optarg, "webget"))
				{
					m_webGet = true;
					optind++;
					if (optind > argc)
					{
						ReportError("Could not parse value of option 'B'");
						return;
					}
					optarg = argv[optind-1];
					m_webGetFilename = optarg;
				}
				else if (!strcasecmp(optarg, "verify"))
				{
					m_sigVerify = true;
					optind++;
					if (optind > argc)
					{
						ReportError("Could not parse value of option 'B'");
						return;
					}
					optarg = argv[optind-1];
					m_pubKeyFilename = optarg;

					optind++;
					if (optind > argc)
					{
						ReportError("Could not parse value of option 'B'");
						return;
					}
					optarg = argv[optind-1];
					m_sigFilename = optarg;
				}
				else
				{
					ReportError("Could not parse value of option 'B'");
					return;
				}
				break;
			case 'G':
				m_clientOperation = opClientRequestLog;
				m_logLines = atoi(optarg);
				if (m_logLines == 0)
				{
					ReportError("Could not parse value of option 'G'");
					return;
				}
				break;
			case 'T':
				m_addTop = true;
				break;
			case 'C':
				m_remoteClientMode = true;
				break;
			case 'E':
			{
				m_clientOperation = opClientRequestEditQueue;
				bool group = !strcasecmp(optarg, "G") || !strcasecmp(optarg, "GN") || !strcasecmp(optarg, "GR");
				bool file = !strcasecmp(optarg, "F") || !strcasecmp(optarg, "FN") || !strcasecmp(optarg, "FR");
				if (!strcasecmp(optarg, "GN") || !strcasecmp(optarg, "FN"))
				{
					m_matchMode = mmName;
				}
				else if (!strcasecmp(optarg, "GR") || !strcasecmp(optarg, "FR"))
				{
					m_matchMode = mmRegEx;
				}
				else
				{
					m_matchMode = mmId;
				};
				bool post = !strcasecmp(optarg, "O");
				bool history = !strcasecmp(optarg, "H");
				if (group || file || post || history)
				{
					optind++;
					if (optind > argc)
					{
						ReportError("Could not parse value of option 'E'");
						return;
					}
					optarg = argv[optind-1];
				}

				if (post)
				{
					// edit-commands for post-processor-queue
					if (!strcasecmp(optarg, "D"))
					{
						m_editQueueAction = DownloadQueue::eaPostDelete;
					}
					else
					{
						ReportError("Could not parse value of option 'E'");
						return;
					}
				}
				else if (history)
				{
					// edit-commands for history
					if (!strcasecmp(optarg, "D"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryDelete;
					}
					else if (!strcasecmp(optarg, "R"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryReturn;
					}
					else if (!strcasecmp(optarg, "P"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryProcess;
					}
					else if (!strcasecmp(optarg, "A"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryRedownload;
					}
					else if (!strcasecmp(optarg, "F"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryRetryFailed;
					}
					else if (!strcasecmp(optarg, "O"))
					{
						m_editQueueAction = DownloadQueue::eaHistorySetParameter;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);

						if (!strchr(m_editQueueText, '='))
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
					}
					else if (!strcasecmp(optarg, "B"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryMarkBad;
					}
					else if (!strcasecmp(optarg, "G"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryMarkGood;
					}
					else if (!strcasecmp(optarg, "S"))
					{
						m_editQueueAction = DownloadQueue::eaHistoryMarkSuccess;
					}
					else
					{
						ReportError("Could not parse value of option 'E'");
						return;
					}
				}
				else
				{
					// edit-commands for download-queue
					if (!strcasecmp(optarg, "T"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupMoveTop : DownloadQueue::eaFileMoveTop;
					}
					else if (!strcasecmp(optarg, "B"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupMoveBottom : DownloadQueue::eaFileMoveBottom;
					}
					else if (!strcasecmp(optarg, "P"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupPause : DownloadQueue::eaFilePause;
					}
					else if (!strcasecmp(optarg, "A"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupPauseAllPars : DownloadQueue::eaFilePauseAllPars;
					}
					else if (!strcasecmp(optarg, "R"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupPauseExtraPars : DownloadQueue::eaFilePauseExtraPars;
					}
					else if (!strcasecmp(optarg, "U"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupResume : DownloadQueue::eaFileResume;
					}
					else if (!strcasecmp(optarg, "D"))
					{
						m_editQueueAction = group ? DownloadQueue::eaGroupDelete : DownloadQueue::eaFileDelete;
					}
					else if (!strcasecmp(optarg, "DP"))
					{
						m_editQueueAction = DownloadQueue::eaGroupParkDelete;
					}
					else if (!strcasecmp(optarg, "SF"))
					{
						m_editQueueAction = DownloadQueue::eaGroupSortFiles;
					}
					else if (!strcasecmp(optarg, "C") || !strcasecmp(optarg, "K") || !strcasecmp(optarg, "CP"))
					{
						// switch "K" is provided for compatibility with v. 0.8.0 and can be removed in future versions
						if (!group)
						{
							ReportError("Category can be set only for groups");
							return;
						}
						m_editQueueAction = !strcasecmp(optarg, "CP") ? DownloadQueue::eaGroupApplyCategory : DownloadQueue::eaGroupSetCategory;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);
					}
					else if (!strcasecmp(optarg, "N"))
					{
						if (!group)
						{
							ReportError("Only groups can be renamed");
							return;
						}
						m_editQueueAction = DownloadQueue::eaGroupSetName;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);
					}
					else if (!strcasecmp(optarg, "M"))
					{
						if (!group)
						{
							ReportError("Only groups can be merged");
							return;
						}
						m_editQueueAction = DownloadQueue::eaGroupMerge;
					}
					else if (!strcasecmp(optarg, "S"))
					{
						m_editQueueAction = DownloadQueue::eaFileSplit;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);
					}
					else if (!strcasecmp(optarg, "O"))
					{
						if (!group)
						{
							ReportError("Post-process parameter can be set only for groups");
							return;
						}
						m_editQueueAction = DownloadQueue::eaGroupSetParameter;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);

						if (!strchr(m_editQueueText, '='))
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
					}
					else if (!strcasecmp(optarg, "I"))
					{
						if (!group)
						{
							ReportError("Priority can be set only for groups");
							return;
						}
						m_editQueueAction = DownloadQueue::eaGroupSetPriority;

						optind++;
						if (optind > argc)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueText = std::move(argv[optind-1]);

						if (atoi(m_editQueueText) == 0 && strcmp("0", m_editQueueText))
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
					}
					else
					{
						m_editQueueOffset = atoi(optarg);
						if (m_editQueueOffset == 0)
						{
							ReportError("Could not parse value of option 'E'");
							return;
						}
						m_editQueueAction = group ? DownloadQueue::eaGroupMoveOffset : DownloadQueue::eaFileMoveOffset;
					}
				}
				break;
			}
			case 'Q':
				m_clientOperation = opClientRequestShutdown;
				break;
			case 'O':
				m_clientOperation = opClientRequestReload;
				break;
			case 'V':
				m_clientOperation = opClientRequestVersion;
				break;
			case 'W':
				m_clientOperation = opClientRequestWriteLog;
				if (!strcasecmp(optarg, "I")) {
					m_writeLogKind = (int)Message::mkInfo;
				}
				else if (!strcasecmp(optarg, "W")) {
					m_writeLogKind = (int)Message::mkWarning;
				}
				else if (!strcasecmp(optarg, "E")) {
					m_writeLogKind = (int)Message::mkError;
				}
				else if (!strcasecmp(optarg, "D")) {
					m_writeLogKind = (int)Message::mkDetail;
				}
				else if (!strcasecmp(optarg, "G")) {
					m_writeLogKind = (int)Message::mkDebug;
				}
				else
				{
					ReportError("Could not parse value of option 'W'");
					return;
				}
				break;
			case 'K':
				// switch "K" is provided for compatibility with v. 0.8.0 and can be removed in future versions
				SetAddCategory(optarg);
				break;
			case 'S':
				optind++;
				optarg = optind > argc ? nullptr : (char*)argv[optind-1];
				if (!optarg || !strncmp(optarg, "-", 1))
				{
					m_clientOperation = opClientRequestScanAsync;
					optind--;
				}
				else if (!strcasecmp(optarg, "W"))
				{
					m_clientOperation = opClientRequestScanSync;
				}
				else
				{
					ReportError("Could not parse value of option 'S'");
					return;
				}
				break;
			case '?':
				m_errors = true;
				return;
		}
	}

	if (m_serverMode && m_clientOperation == opClientRequestDownloadPause)
	{
		m_pauseDownload = true;
		m_clientOperation = opClientNoOperation;
	}
}

void CommandLineParser::PrintUsage(const char* com)
{
	printf("Usage:\n"
		"  %s [switches]\n\n"
		"Switches:\n"
		"  -h, --help                Print this help-message\n"
		"  -v, --version             Print version and exit\n"
		"  -c, --configfile <file>   Filename of configuration-file\n"
		"  -n, --noconfigfile        Prevent loading of configuration-file\n"
		"                            (required options must be passed with --option)\n"
		"  -p, --printconfig         Print configuration and exit\n"
		"  -o, --option <name=value> Set or override option in configuration-file\n"
		"  -s, --server              Start nzbget as a server in console-mode\n"
#ifndef WIN32
		"  -D, --daemon              Start nzbget as a server in daemon-mode\n"
#endif
		"  -V, --serverversion       Print server's version and exit\n"
		"  -Q, --quit                Shutdown server\n"
		"  -O, --reload              Reload config and restart all services\n"
		"  -A, --append [<options>] <nzb-file/url> Send file/url to server's\n"
		"                            download queue\n"
		"    <options> are (multiple options must be separated with space):\n"
		"       T                    Add file to the top (beginning) of queue\n"
		"       P                    Pause added files\n"
		"       C <name>             Assign category to nzb-file\n"
		"       N <name>             Use this name as nzb-filename\n"
		"       I <priority>         Set priority (signed integer)\n"
		"       DK <dupekey>         Set duplicate key (string)\n"
		"       DS <dupescore>       Set duplicate score (signed integer)\n"
		"       DM (score|all|force) Set duplicate mode\n"
		"  -C, --connect             Attach client to server\n"
		"  -L, --list    [F|FR|G|GR|O|H|S] [RegEx] Request list of items from server\n"
		"                 F          List individual files and server status (default)\n"
		"                 FR         Like \"F\" but apply regular expression filter\n"
		"                 G          List groups (nzb-files) and server status\n"
		"                 GR         Like \"G\" but apply regular expression filter\n"
		"                 O          List post-processor-queue\n"
		"                 H          List history\n"
		"                 HA         List history, all records (incl. hidden)\n"
		"                 S          Print only server status\n"
		"    <RegEx>                 Regular expression (only with options \"FR\", \"GR\")\n"
		"                            using POSIX Extended Regular Expression Syntax\n"
		"  -P, --pause   [D|O|S]     Pause server\n"
		"                 D          Pause download queue (default)\n"
		"                 O          Pause post-processor queue\n"
		"                 S          Pause scan of incoming nzb-directory\n"
		"  -U, --unpause [D|O|S]     Unpause server\n"
		"                 D          Unpause download queue (default)\n"
		"                 O          Unpause post-processor queue\n"
		"                 S          Unpause scan of incoming nzb-directory\n"
		"  -R, --rate <speed>        Set download rate on server, in KB/s\n"
		"  -G, --log <lines>         Request last <lines> lines from server's screen-log\n"
		"  -W, --write <D|I|W|E|G> \"Text\" Send text to server's log\n"
		"  -S, --scan    [W]         Scan incoming nzb-directory on server\n"
		"                 W          Wait until scan completes (synchronous mode)\n"
		"  -E, --edit [F|FN|FR|G|GN|GR|O|H] <action> <IDs/Names/RegExs> Edit items\n"
		"                            on server\n"
		"              F             Edit individual files (default)\n"
		"              FN            Like \"F\" but uses names (as \"group/file\")\n"
		"                            instead of IDs\n"
		"              FR            Like \"FN\" but with regular expressions\n"
		"              G             Edit all files in the group (same nzb-file)\n"
		"              GN            Like \"G\" but uses group names instead of IDs\n"
		"              GR            Like \"GN\" but with regular expressions\n"
		"              O             Edit post-processor-queue\n"
		"              H             Edit history\n"
		"    <action> is one of:\n"
		"    - for files (F) and groups (G):\n"
		"       <+offset|-offset>    Move in queue relative to current position,\n"
		"                            offset is an integer value\n"
		"       T                    Move to top of queue\n"
		"       B                    Move to bottom of queue\n"
		"       D                    Delete\n"
		"       P                    Pause\n"
		"       U                    Resume (unpause)\n"
		"    - for groups (G):\n"
		"       A                    Pause all pars\n"
		"       R                    Pause extra pars\n"
		"       DP                   Delete but keep downloaded files\n"
		"       I <priority>         Set priority (signed integer)\n"
		"       C <name>             Set category\n"
		"       CP <name>            Set category and apply post-process parameters\n"
		"       N <name>             Rename\n"
		"       M                    Merge\n"
		"       SF                   Sort inner files for optimal order\n"
		"       S <name>             Split - create new group from selected files\n"
		"       O <name>=<value>     Set post-process parameter\n"
		"    - for post-jobs (O):\n"
		"       D                    Delete (cancel post-processing)\n"
		"    - for history (H):\n"
		"       D                    Delete\n"
		"       P                    Post-process again\n"
		"       R                    Download remaining files\n"
		"       A                    Download again\n"
		"       F                    Retry download of failed articles\n"
		"       O <name>=<value>     Set post-process parameter\n"
		"       B                    Mark as bad\n"
		"       G                    Mark as good\n"
		"       S                    Mark as success\n"
		"    <IDs>                   Comma-separated list of file- or group- ids or\n"
		"                            ranges of file-ids, e. g.: 1-5,3,10-22\n"
		"    <Names>                 List of names (with options \"FN\" and \"GN\"),\n"
		"                            e. g.: \"my nzb download%cmyfile.nfo\" \"another nzb\"\n"
		"    <RegExs>                List of regular expressions (options \"FR\", \"GR\")\n"
		"                            using POSIX Extended Regular Expression Syntax\n",
		FileSystem::BaseFileName(com),
		PATH_SEPARATOR);
}

void CommandLineParser::InitFileArg(int argc, const char* argv[])
{
	if (optind >= argc)
	{
		// no nzb-file passed
		if (!m_serverMode && !m_remoteClientMode &&
				(m_clientOperation == opClientNoOperation ||
				 m_clientOperation == opClientRequestDownload ||
				 m_clientOperation == opClientRequestWriteLog))
		{
			if (m_clientOperation == opClientRequestWriteLog)
			{
				ReportError("Log-text not specified");
			}
			else
			{
				ReportError("Nzb-file or Url not specified");
			}
		}
	}
	else if (m_clientOperation == opClientRequestEditQueue)
	{
		if (m_matchMode == mmId)
		{
			ParseFileIdList(argc, argv, optind);
		}
		else
		{
			ParseFileNameList(argc, argv, optind);
		}
	}
	else
	{
		m_lastArg = argv[optind];

		// Check if the file-name is a relative path or an absolute path
		// If the path starts with '/' its an absolute, else relative
		const char* fileName = argv[optind];

#ifdef WIN32
		m_argFilename = fileName;
#else
		if (fileName[0] == '/' || !strncasecmp(fileName, "http://", 6) || !strncasecmp(fileName, "https://", 7))
		{
			m_argFilename = fileName;
		}
		else
		{
			// TEST
			m_argFilename.Reserve(1024 - 1);
			getcwd(m_argFilename, 1024);
			m_argFilename.AppendFmt("/%s", fileName);
		}
#endif

		if (m_serverMode || m_remoteClientMode ||
				!(m_clientOperation == opClientNoOperation ||
				  m_clientOperation == opClientRequestDownload ||
				  m_clientOperation == opClientRequestWriteLog))
		{
			ReportError("Too many arguments");
		}
	}
}

void CommandLineParser::ParseFileIdList(int argc, const char* argv[], int optind)
{
	m_editQueueIdList.clear();

	while (optind < argc)
	{
		CString writableFileIdList = argv[optind++];

		char* optarg = strtok(writableFileIdList, ", ");
		while (optarg)
		{
			int editQueueIdFrom = 0;
			int editQueueIdTo = 0;
			const char* p = strchr(optarg, '-');
			if (p)
			{
				BString<100> buf;
				buf.Set(optarg, (int)(p - optarg));
				editQueueIdFrom = atoi(buf);
				editQueueIdTo = atoi(p + 1);
				if (editQueueIdFrom <= 0 || editQueueIdTo <= 0)
				{
					ReportError("invalid list of file IDs");
					return;
				}
			}
			else
			{
				editQueueIdFrom = atoi(optarg);
				if (editQueueIdFrom <= 0)
				{
					ReportError("invalid list of file IDs");
					return;
				}
				editQueueIdTo = editQueueIdFrom;
			}

			int editQueueIdCount = 0;
			if (editQueueIdFrom < editQueueIdTo)
			{
				editQueueIdCount = editQueueIdTo - editQueueIdFrom + 1;
			}
			else
			{
				editQueueIdCount = editQueueIdFrom - editQueueIdTo + 1;
			}

			for (int i = 0; i < editQueueIdCount; i++)
			{
				if (editQueueIdFrom < editQueueIdTo)
				{
					m_editQueueIdList.push_back(editQueueIdFrom + i);
				}
				else
				{
					m_editQueueIdList.push_back(editQueueIdFrom - i);
				}
			}

			optarg = strtok(nullptr, ", ");
		}
	}
}

void CommandLineParser::ParseFileNameList(int argc, const char* argv[], int optind)
{
	while (optind < argc)
	{
		m_editQueueNameList.push_back(argv[optind++]);
	}
}

void CommandLineParser::ReportError(const char* errMessage)
{
	m_errors = true;
	printf("%s\n", errMessage);
}
