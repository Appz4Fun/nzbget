#!/usr/bin/env python3
"""Compare EditQueue's trailing-data checks and split and Download's URL test
(rust/src/binrpc.rs through its C ABI) with the pre-port C++ of BinRpc.cpp,
taken verbatim from the reference: the size check of the client's counts and
lengths, the ids and names read after the text, and the strncasecmp prefix
test. Random counts around the limits and random data, names that end within
their part or don't, contents with and without a URL scheme.

Usage: binrpc_edit_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "3843520c"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "500000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/BinRpc.cpp"], cwd=ROOT, text=True)
SIZES = '''	if (nrIdEntries < 0 || nrNameEntries < 0 || textLen < 0 || nameEntriesLen < 0 ||
		nrIdEntries > 10000000 || nrNameEntries > nameEntriesLen ||
		(int64)nrIdEntries * (int64)sizeof(int32) + textLen + nameEntriesLen != (int64)bufLength)
'''
URL = 'if (!strncasecmp(nzbContent, "http://", 6) || !strncasecmp(nzbContent, "https://", 7))'
assert SIZES in old_src and URL in old_src
start = old_src.index("	int32* ids = (int32*)(buf + textLen);")
split = old_src[start:old_src.index("	bool ok = DownloadQueue::Guard()->EditList(", start)]
assert "memchr(names, '\\0', namesEnd - names)" in split

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

main = r'''
#include "nzbget.h"
#include "nzbget_rs.h"
#include <arpa/inet.h>
#include <clocale>
#include <cstring>
#include <string>
#include <vector>

static void error(const char*) {}
typedef std::vector<int> IdList;
typedef std::vector<std::string> NameList;

// the pre-port checks, verbatim (its ids were read through an int32* at any
// offset: alignment isn't sanitized here)
static bool OldSizesOk(int nrIdEntries, int nrNameEntries, int nameEntriesLen, int textLen, uint32 bufLength)
{
''' + SIZES + r'''	{
		return false;
	}
	return true;
}

static bool OldSplit(char* buf, int textLen, int nrIdEntries, int nrNameEntries, int nameEntriesLen,
	IdList& oldIds, NameList& oldNames)
{
''' + split.replace("return;", "return false;") + r'''	oldIds = cIdList;
	oldNames = cNameList;
	return true;
}

static bool OldUrl(const char* nzbContent)
{
	return ''' + URL[4:-1] + r''';
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static int Count()
{
	switch (below(6))
	{
		case 0: return (int)next();
		case 1: return -below(3);
		case 2: return 10000000 + below(3) - 1;
		default: return below(12);
	}
}

int main(int argc, char** argv)
{
	setlocale(LC_ALL, "");
	long rounds = atol(argv[1]);
	long failures = 0, splits = 0, accepted = 0;
	for (long round = 0; round < rounds; round++)
	{
		int nrIds = Count(), nrNames = Count(), namesLen = Count(), textLen = Count();
		uint32 bufLength = below(3) ? (uint32)((int64)nrIds * 4 + textLen + namesLen) + (below(4) ? 0 : below(3) - 1) : (uint32)next();
		bool a = OldSizesOk(nrIds, nrNames, namesLen, textLen, bufLength);
		bool b = nzbget_rs_binrpc_edit_sizes(nrIds, nrNames, namesLen, textLen, bufLength) != 0;
		if (a != b) { printf("sizes mismatch %d %d %d %d %u\n", nrIds, nrNames, namesLen, textLen, bufLength); failures++; }

		// a split of data that passed the size check, as Execute makes it
		nrIds = below(5); nrNames = below(6); textLen = below(4); namesLen = nrNames + below(8);
		bufLength = nrIds * 4 + textLen + namesLen;
		std::vector<char> data(bufLength + 1);
		for (uint32 i = 0; i < bufLength; i++) data[i] = below(3) ? (char)next() : 0;
		char* names = data.data() + textLen + nrIds * 4;
		for (int i = 0; i < namesLen; i++) names[i] = below(3) ? 'a' + below(3) : 0;
		data[bufLength] = 0;
		if (textLen > 0) data[textLen - 1] = 0;
		if (!(nrIds <= 0 && nrNames <= 0))
		{
			IdList oldIds; NameList oldNames;
			bool c = OldSplit(data.data(), textLen, nrIds, nrNames, namesLen, oldIds, oldNames);
			std::vector<uint32_t> ids(nrIds, 0x5a5a5a5a);
			bool d = nzbget_rs_binrpc_edit_split(data.data(), bufLength, textLen, nrIds, nrNames, ids.data()) != 0;
			splits++;
			if (c != d) { printf("split mismatch round %ld: %d %d\n", round, c, d); failures++; }
			else if (c)
			{
				accepted++;
				for (int i = 0; i < nrIds; i++) if (oldIds[i] != (int)ids[i]) { printf("id mismatch\n"); failures++; }
				// the names as Execute walks them after the check
				const char* names = data.data() + textLen + nrIds * 4;
				for (int i = 0; i < nrNames; i++, names += strlen(names) + 1)
					if (oldNames[i] != std::string(names)) { printf("name mismatch\n"); failures++; }
			}
			else
			{
				for (uint32_t id : ids) if (id != 0x5a5a5a5a) { printf("ids written on failure\n"); failures++; }
			}
		}

		static const char* HEADS[] = {"http://", "https://", "HTTP://", "HtTpS://", "http:/", "https:", "http:", "ftp://", "<?xml", "h", "", "http:\\", "https:/", "httpS:/x"};
		std::string content = HEADS[below(14)];
		if (below(3)) content.resize(below(content.size() + 1));
		for (int n = below(4); n > 0; n--) content += below(4) ? (char)('a' + below(26)) : (char)next();
		if (below(5) == 0 && !content.empty()) content[below(content.size())] = (char)(below(2) ? 0 : 0xc0 + below(64));
		if (OldUrl(content.c_str()) != (nzbget_rs_binrpc_is_url(content.c_str()) != 0)) { printf("url mismatch '%s'\n", content.c_str()); failures++; }
		if (failures > 5) return 1;
	}
	if (nzbget_rs_binrpc_edit_split(nullptr, 0, 0, 1, 0, nullptr) != 0) { printf("null ids\n"); return 1; }
	printf("%ld rounds agree, %ld splits (%ld accepted) (reference %s)\n", rounds, splits, accepted, "''' + REFERENCE + r'''");
	return failures ? 1 : 0;
}
'''

LOCALES = {"C"} | {l.strip().replace(".utf8", ".UTF-8").replace(".iso88591", ".ISO-8859-1")
                    for l in subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()}

with tempfile.TemporaryDirectory(prefix="nzbget-binrpc-edit-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "binrpc-edit"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only", str(ROOT / "daemon/remote/BinRpc.cpp")],
                   check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize=alignment", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary), str(rust_lib),
                        "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lm"], check=True, cwd=BUILD)
        # strncasecmp folds by the locale
        for locale in [l for l in ("C", "C.UTF-8", "tr_TR.UTF-8", "en_US.ISO-8859-1") if l in LOCALES]:
            print("locale:", locale, flush=True)
            subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                            str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS],
                           check=True, env={**os.environ, "LC_ALL": locale})
