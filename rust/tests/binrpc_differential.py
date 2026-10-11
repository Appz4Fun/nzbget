#!/usr/bin/env python3
"""Compare the binary remote protocol's frame (rust/src/binrpc.rs through
its C ABI) with the pre-port C++ logic of BinRpc.cpp, taken verbatim from
the reference: BinRpcProcessor::Execute's credential check and type name,
Dispatch's size check, SendBoolResponse's bytes and ReceiveTrailing's
length check. Random request bases (user names that run on into the
password, as strcmp read them; every request type with right and wrong
sizes; control user names empty or not), random texts and lengths.

Usage: binrpc_differential.py BUILD_DIR [ROUNDS]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "a29de83b"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "500000"

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/remote/BinRpc.cpp"], cwd=ROOT, text=True)
tables = old_src[old_src.index("const char* g_MessageRequestNames[]"):old_src.index("static_assert")]
# the conditions of the reference, verbatim
for needle in ('if ((strlen(g_Options->GetControlUsername()) > 0 && strcmp(m_messageBase.m_username, g_Options->GetControlUsername())) ||\n\t\tstrcmp(m_messageBase.m_password, g_Options->GetControlPassword()))',
               'type <= (uint32)rrHistory ? g_MessageRequestNames[type] : "Unknown"',
               'if (ntohl(m_messageBase.m_type) >= (int)rrDownload &&\n\t\t   ntohl(m_messageBase.m_type) <= (int)rrHistory &&\n\t\t   g_MessageRequestSizes[ntohl(m_messageBase.m_type)] != ntohl(m_messageBase.m_structSize))',
               'BoolResponse.m_trailingDataLength = htonl(textLen);',
               'if (len < 0 || len > maxLen)'):
    assert needle in old_src, needle

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
rust_lib = next(BUILD.glob("rust/*/*/release/libnzbget_rs.a"), None) or next(BUILD.glob("rust/**/libnzbget_rs.a"))

main = r'''
#include "nzbget.h"
#include "MessageBase.h"
#include "nzbget_rs.h"
#include <arpa/inet.h>
#include <cstring>
#include <string>
#include <vector>

''' + tables + r'''

// the pre-port logic, verbatim apart from the option reads
static bool OldCredentialsOk(const SNzbRequestBase& m_messageBase, const char* user, const char* password)
{
	return !((strlen(user) > 0 && strcmp(m_messageBase.m_username, user)) ||
		strcmp(m_messageBase.m_password, password));
}

static const char* OldName(uint32 type)
{
	return type <= (uint32)rrHistory ? g_MessageRequestNames[type] : "Unknown";
}

static bool OldSizeOk(const SNzbRequestBase& m_messageBase, uint32& expected, uint32& received)
{
	if (ntohl(m_messageBase.m_type) >= (int)rrDownload &&
		   ntohl(m_messageBase.m_type) <= (int)rrHistory &&
		   g_MessageRequestSizes[ntohl(m_messageBase.m_type)] != ntohl(m_messageBase.m_structSize))
	{
		expected = g_MessageRequestSizes[ntohl(m_messageBase.m_type)];
		received = ntohl(m_messageBase.m_structSize);
		return false;
	}
	return true;
}

static std::string OldBoolResponse(bool success, const char* text)
{
	SNzbDownloadResponse BoolResponse;
	memset(&BoolResponse, 0, sizeof(BoolResponse));
	BoolResponse.m_messageBase.m_signature = htonl(NZBMESSAGE_SIGNATURE);
	BoolResponse.m_messageBase.m_structSize = htonl(sizeof(BoolResponse));
	BoolResponse.m_success = htonl(success);
	int textLen = strlen(text) + 1;
	BoolResponse.m_trailingDataLength = htonl(textLen);
	return std::string((char*)&BoolResponse, sizeof(BoolResponse)) + std::string(text, textLen);
}

static bool OldTrailingOk(int64 len, int64 maxLen)
{
	return !(len < 0 || len > maxLen);
}

static unsigned long long state = 88172645463325252ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return (int)(next() % n); }

static void Fill(char* field, int size, const char* text, bool terminate)
{
	memset(field, 0, size);
	int len = std::min((int)strlen(text), size);
	memcpy(field, text, len);
	if (!terminate)
		for (int i = len; i < size; i++) field[i] = 'a' + below(3);
}

int main(int argc, char** argv)
{
	long rounds = atol(argv[1]);
	static const char* USERS[] = {"", "nzbget", "NZBGET", "admin", "a", "nzbgetnzbgetnzbgetnzbgetnzbget12", "x\xc3\xa9"};
	static const char* PASSWORDS[] = {"", "tegbzn6789", "secret", "a", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"};
	long failures = 0;
	for (long round = 0; round < rounds; round++)
	{
		SNzbRequestBase base;
		memset(&base, 0, sizeof(base));
		for (size_t i = 0; i < sizeof(base) && below(8) == 0; i++) ((char*)&base)[i] = (char)next();
		base.m_signature = (int32)NZBMESSAGE_SIGNATURE;
		uint32 type = below(4) ? below(16) : (uint32)next();
		base.m_type = htonl(type);
		uint32 size = below(3) && type >= 1 && type <= rrHistory ? g_MessageRequestSizes[type] : (uint32)(below(2) ? below(4000) : next());
		base.m_structSize = htonl(size);
		const char* user = USERS[below(7)];
		const char* password = PASSWORDS[below(5)];
		// the user name may fill its field (strcmp runs on into the password);
		// the password stays terminated inside the struct
		Fill(base.m_username, NZBREQUESTPASSWORDSIZE, below(3) ? user : USERS[below(7)], below(4) != 0);
		Fill(base.m_password, NZBREQUESTPASSWORDSIZE, below(3) ? password : PASSWORDS[below(5)], true);
		base.m_password[NZBREQUESTPASSWORDSIZE - 1] = 0;
		std::string controlUser = below(2) ? user : std::string(base.m_username, strnlen(base.m_username, 64));
		if (below(4) == 0) controlUser = "";

		bool a = OldCredentialsOk(base, controlUser.c_str(), password);
		uint32 rustType = 0;
		bool b = nzbget_rs_binrpc_check((const unsigned char*)&base, sizeof(base), controlUser.c_str(), password, &rustType) != 0;
		if (a != b || rustType != ntohl(base.m_type)) { printf("credentials mismatch round %ld\n", round); failures++; }
		if (strcmp(OldName(ntohl(base.m_type)), nzbget_rs_binrpc_name(ntohl(base.m_type)))) { printf("name mismatch %u\n", ntohl(base.m_type)); failures++; }

		uint32 e1 = 7, r1 = 7, e2 = 7, r2 = 7;
		bool s1 = OldSizeOk(base, e1, r1);
		bool s2 = nzbget_rs_binrpc_size_ok((const unsigned char*)&base, sizeof(base), g_MessageRequestSizes,
			sizeof(g_MessageRequestSizes) / sizeof(g_MessageRequestSizes[0]), &e2, &r2) != 0;
		if (s1 != s2 || e1 != e2 || r1 != r2) { printf("size mismatch type %u size %u\n", type, size); failures++; }

		std::string text;
		for (int n = below(3) ? below(60) : below(3000); n > 0; n--) text += (char)(1 + below(255));
		bool success = below(2);
		std::string oldResponse = OldBoolResponse(success, text.c_str());
		NzbgetRsBuf buf = nzbget_rs_binrpc_bool_response(success, text.c_str());
		if (oldResponse != std::string(buf.data, buf.len)) { printf("bool response mismatch\n"); failures++; }
		nzbget_rs_free(buf);

		int64 len = below(3) ? below(2000) - 500 : (int64)next();
		int64 maxLen = below(2) ? 1024 * 1024 : below(1000);
		if (OldTrailingOk(len, maxLen) != (nzbget_rs_binrpc_trailing_ok(len, maxLen) != 0)) { printf("trailing mismatch\n"); failures++; }
		if (failures > 5) return 1;
	}
	// a short base fails, NULL outputs aren't written
	SNzbRequestBase base{};
	if (nzbget_rs_binrpc_check((const unsigned char*)&base, sizeof(base) - 1, "", "", nullptr) != 0) { printf("short base\n"); return 1; }
	printf("%ld rounds agree (reference %s)\n", rounds, "''' + REFERENCE + r'''");
	return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix="nzbget-binrpc-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "binrpc"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only", str(ROOT / "daemon/remote/BinRpc.cpp")],
                   check=True, cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], ["-O2"]):
        print("C++ flags:", " ".join(extra), flush=True)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")), *extra, "-w",
                        *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary), str(rust_lib),
                        "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lm"], check=True, cwd=BUILD)
        subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary),
                        str(max(1, int(ROUNDS) // 4)) if "-fsanitize=address,undefined" in extra else ROUNDS], check=True)
