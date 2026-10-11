#!/usr/bin/env python3
"""Compare RarVolume's header parsing (rust/src/rarreader.rs with the C++
wrapper of RarReader.cpp), and its C++ fallback, with the pre-port C++: every
RAR3/RAR5 volume of tests/testdata (plain, encrypted data, encrypted headers),
with and without the password, then the same volumes mutated (byte flips,
truncations, insertions, deletions) - comparing the result, the volume state
and every file's fields. Also covers synthetic integer/crypt-record boundaries,
source exceptions (including crypt records), repeated reads, exhaustive short
synthetic-archive truncations, overlong/overflowing vints, encrypted padding
boundaries, and source call traces. Non-advancing blocks are excluded from
the old-reader comparison; Rust and the fallback are always compared.

All three C++ readers are compiled as separate translation units with renamed
classes and test-only access to the decrypt cache. This also instruments the
Rust-backed wrapper in the sanitizer pass; Rust comes from the build's archive.
The volumes are read from memory through a ContentSource.

Usage: rarreader_differential.py BUILD_DIR [ROUNDS]
(NZBGET_TEST_VERBOSE=1 prints each volume and round; NZBGET_TEST_WRAPPER runs
the binary under a tool, e.g. "gdb -batch -ex run -ex bt --args".)
"""
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b"
BUILD = Path(sys.argv[1]).resolve()
ROUNDS = sys.argv[2] if len(sys.argv) > 2 else "100"

# Compile all three readers with test-only public state, so comparisons cover
# the decrypt cache as well as the public results. Renaming keeps these class
# definitions separate from the production reader linked from libnzbget.
header = (ROOT / "daemon/postprocess/RarReader.h").read_text().replace("\nprivate:", "\npublic:")
old_header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarReader.h"], cwd=ROOT, text=True).replace("\nprivate:", "\npublic:")


def renamed(src, hdr, prefix, fallback=False):
    def r(text):
        for name in ("RarSourceCursor", "RarVolume", "RarFile"):
            text = re.sub(rf"\b{name}\b", prefix + name, text)
        return text.replace("RARREADER_H", prefix.upper() + "RARREADER_H")
    body = r(src).replace('#include "RarReader.h"', r(hdr))
    return ("#undef NZBGET_USE_RUST\n" if fallback else "") + body


old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/postprocess/RarReader.cpp"], cwd=ROOT, text=True)
# Stop the reference at the same block boundary without changing its results
# for advancing inputs. Check the replacement counts so source drift fails.
loop = "\twhile (!file.Eof())\n\t{"
seek = "\t\tif (!file.Seek(skip, DiskFile::soCur))\n\t\t{\n\t\t\treturn false;\n\t\t}"
assert old_src.count(loop) == 2 and old_src.count(seek) == 2
old_src = "struct NonAdvancing {};\n" + old_src.replace(
    loop, loop + "\n\t\tint64 blockStart = file.Position();").replace(
    seek, seek + "\n\t\tif (file.Position() <= blockStart) throw NonAdvancing{};")
new_src = (ROOT / "daemon/postprocess/RarReader.cpp").read_text()

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]
volumes = sorted(str(p) for p in (ROOT / "tests/testdata").rglob("*") if re.search(r"\.(rar|r\d\d)$", p.name))

decls = "\n".join(renamed("", h, p)[0:0] + re.sub(r"\b(RarSourceCursor|RarVolume|RarFile)\b", lambda m: p + m.group(1), h)
                  .replace("RARREADER_H", p.upper() + "RARREADER_H") for h, p in ((old_header, "Old"), (header, "Fallback"), (header, "Port")))

main = r'''
#include "nzbget.h"
#include "RarReader.h"
#include "ContentMap.h"
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include <stdexcept>
''' + globals_block + r'''
#undef NZBGET_USE_RUST
''' + decls + r'''

struct NonAdvancing {};
static size_t filtered = 0;

struct MemSource : ContentSource
{
	std::string data;
	int failAt = -1;
	int reads = 0;
	int sizes = 0;
	int fault = 0; // throw Read, refuse Read, throw Size
	std::string trace;
	int64 Size() override
	{
		trace += "S;";
		if (sizes++ == failAt && fault == 2) throw std::runtime_error("size failure");
		return (int64)data.size();
	}
	bool Read(int64 offset, void* buffer, int64 size) override
	{
		trace += "R" + std::to_string(offset) + "," + std::to_string(size) + ";";
		if (reads++ == failAt && fault != 2)
		{
			if (fault == 1) return false;
			throw std::runtime_error("source failure");
		}
		if (offset < 0 || size < 0 || offset > (int64)data.size() || size > (int64)data.size() - offset) return false;
		memcpy(buffer, data.data() + offset, (size_t)size);
		return true;
	}
};

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return n <= 0 ? 0 : (int)(next() % (unsigned long long)n); }

static std::string hex(const uint8* p, int n) { std::string s; char b[3]; for (int i = 0; i < n; i++) { snprintf(b, 3, "%02x", p[i]); s += b; } return s; }

template <class V> static std::string run(const std::string& data, const char* password, int failAt = -1, int repeats = 1, int fault = 0)
{
	MemSource source;
	source.data = data;
	source.failAt = repeats > 1 ? -1 : failAt;
	source.fault = fault;
	V volume("vol.rar");
	if (password) volume.SetPassword(password);
	std::string result;
	for (int attempt = 0; attempt < repeats; ++attempt)
	{
		bool ok = false;
		bool threw = false;
		try { ok = volume.ReadFrom(source); }
		catch (const std::runtime_error&) { threw = true; }
		std::string s = std::to_string(ok) + std::to_string(threw) + "|" + std::to_string(volume.GetVersion()) + "," + std::to_string(volume.GetVolumeNo()) + "," +
			std::to_string(volume.GetNewNaming()) + std::to_string(volume.GetHasNextVolume()) + std::to_string(volume.GetMultiVolume()) +
			std::to_string(volume.GetEncrypted()) + "|";
		s += std::to_string(volume.m_decryptPos) + ":" + hex(volume.m_decryptBuf, 16) + "|";
		for (auto& f : *volume.GetFiles())
		{
			s += hex((const uint8*)f.GetFilename(), (int)strlen(f.GetFilename())) + "/" + std::to_string(f.GetTime()) + "/" + std::to_string(f.GetAttr()) + "/" +
				std::to_string(f.GetSize()) + "/" + std::to_string(f.GetSplitBefore()) + std::to_string(f.GetSplitAfter()) + "/" +
				std::to_string(f.GetMethod()) + "/" + std::to_string(f.GetStored()) + "/" + std::to_string(f.GetPackedSize()) + "/" +
				std::to_string(f.GetDataOffset()) + "/" + std::to_string(f.GetEncryptedData()) + "/" + std::to_string(f.GetHasSalt()) +
				hex(f.GetSalt(), 8) + "/";
			if (auto* c = f.GetCrypt())
				s += std::to_string(c->Version) + "," + std::to_string(c->Flags) + "," + std::to_string(c->KdfCount) + "," +
					hex(c->Salt, 16) + hex(c->Iv, 16) + hex(c->CheckValue, 12) + std::to_string(c->HasCheck);
			s += ";";
		}
		result += s + "|" + source.trace + "\n";
		source.trace.clear();
		source.reads = 0;
		source.sizes = 0;
		source.failAt = failAt;
	}
	return result;
}

static bool check(const std::string& data, const char* password, const std::string& what, int failAt = -1, int repeats = 1, int fault = 0, bool allowNonAdvancing = true)
{
	std::string b = run<PortRarVolume>(data, password, failAt, repeats, fault);
	std::string c = run<FallbackRarVolume>(data, password, failAt, repeats, fault);
	if (b != c)
	{
		fprintf(stderr, "mismatch: %s (password %s)\nrust:     %s\nfallback: %s\n", what.c_str(),
			password ? password : "-", b.c_str(), c.c_str());
		return false;
	}
	try
	{
		std::string a = run<OldRarVolume>(data, password, failAt, repeats, fault);
		if (a != b)
		{
			fprintf(stderr, "mismatch: %s (password %s)\nold:      %s\nrust:     %s\n", what.c_str(),
				password ? password : "-", a.c_str(), b.c_str());
			return false;
		}
	}
	catch (const NonAdvancing&)
	{
		if (!allowNonAdvancing)
		{
			fprintf(stderr, "non-advancing fixture: %s\n", what.c_str());
			return false;
		}
		++filtered;
	}
	return true;
}

template <class Cursor> static bool wrappingRead()
{
	struct Source : ContentSource
	{
		int64 Size() override { return INT64_MIN; }
		bool Read(int64 offset, void* buffer, int64 size) override
		{
			if (offset != INT64_MAX || size != 1) return false;
			*(char*)buffer = 'x';
			return true;
		}
	} source;
	Cursor cursor(source);
	char byte = 0;
	return cursor.Seek(INT64_MAX) && cursor.Read(&byte, 1) == 1 &&
		byte == 'x' && cursor.Position() == INT64_MIN;
}

#ifndef DISABLE_TLS
// Use a one-iteration RAR5 key to exercise encrypted plaintext layouts without
// multiplying the expensive KDF work of the real encrypted fixtures.
static std::string encrypted5(const std::string& header)
{
	uint8 key[32], salt[16] = {}, iv[16] = {};
	if (!PKCS5_PBKDF2_HMAC("123", 3, salt, 16, 1, EVP_sha256(), 32, key))
		throw std::runtime_error("test key derivation failed");
	std::string padded = header;
	padded.resize((padded.size() + 15) & ~size_t(15), '\0');
	std::string encrypted(padded.size() + 16, '\0');
	OpenSSL::EVPCipherCtxPtr ctx{EVP_CIPHER_CTX_new(), &EVP_CIPHER_CTX_free};
	int count = 0;
	if (!ctx || !EVP_EncryptInit_ex(ctx.get(), EVP_aes_256_cbc(), nullptr, key, iv) ||
		!EVP_CIPHER_CTX_set_padding(ctx.get(), 0) ||
		!EVP_EncryptUpdate(ctx.get(), (uint8*)&encrypted[0], &count,
			(const uint8*)padded.data(), (int)padded.size()) || count != (int)padded.size())
		throw std::runtime_error("test encryption failed");
	encrypted.resize(count);
	return std::string((char*)iv, 16) + encrypted;
}

static bool encryptedBoundaries()
{
	std::string prefix("Rar!\x1a\x07\x01\0", 8);
	const char crypt[] = {0,0,0,0,21,4,0,0,0,0};
	prefix.append(crypt, sizeof(crypt));
	prefix.append(16, '\0'); // salt, KDF count above is zero
	const char end[] = {0,0,0,0,3,5,0,1};
	for (int length = 0; length <= 32; ++length)
	{
		for (int packed : {0, 1, 15, 16, 17})
		{
			const char file[] = {0,0,0,0,(char)(9 + length),2,2,(char)packed,0,0,0,0,0,(char)length};
			std::string header(file, sizeof(file));
			header.append(length, 'a');
			std::string data = prefix + encrypted5(header) + std::string(packed, '\0') +
				encrypted5(std::string(end, sizeof(end)));
			std::string label = "encrypted name/data lengths " + std::to_string(length) + "/" + std::to_string(packed);
			if (!check(data, "123", label, -1, 2, 0, false)) return false;
			if (packed == 0)
			{
				for (size_t cut = prefix.size(); cut < data.size(); ++cut)
					if (!check(data.substr(0, cut), "123", label + " cut " + std::to_string(cut))) return false;
				for (int at = 0; at < 32; ++at)
					for (int fault = 0; fault < 3; ++fault)
						if (!check(data, "123", label + " failure " + std::to_string(at) + "/" +
							std::to_string(fault), at, 1, fault)) return false;
			}
		}
	}
	return true;
}
#endif

int main(int argc, char** argv)
{
#ifndef DISABLE_TLS
	if (!encryptedBoundaries()) return 1;
#endif
	if (!wrappingRead<OldRarSourceCursor>() || !wrappingRead<PortRarSourceCursor>() ||
		!wrappingRead<FallbackRarSourceCursor>()) return 1;
	// Exercise the reference filter as well as agreement between both readers.
	for (int wrapped = 0; wrapped < 2; ++wrapped)
	{
		std::string cycling("Rar!\x1a\x07\0", 7);
		const char header[] = {0,0,0x74,0,(char)0x80,(char)wrapped,0};
		cycling.append(header, sizeof(header));
		cycling.append(4, wrapped ? (char)0xff : '\0');
		cycling.append(32, '\0');
		for (int fault = 0; fault < 3; ++fault)
			if (!check(cycling, nullptr, "non-progressing RAR3 header " + std::to_string(wrapped),
				40, 1, fault)) return 1;
	}
	long rounds = atol(argv[1]);
	std::vector<std::string> files;
	for (int i = 2; i < argc; i++)
	{
		std::ifstream f(argv[i], std::ios::binary);
		files.emplace_back(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
		for (const char* pw : {(const char*)nullptr, "123", "wrong"})
		{
			if (getenv("NZBGET_TEST_VERBOSE")) fprintf(stderr, "volume %s pw %s\n", argv[i], pw ? pw : "-");
			if (!check(files.back(), pw, argv[i], -1, 1, 0,
				std::string(argv[i]).find("synthetic-") != std::string::npos)) return 1;
		}
		// Synthetic archives are small and unencrypted, so exhaust every byte
		// boundary and source failure without paying for password derivation.
		// This includes failures in ReadVLimited: a refused read may be ignored
		// by the legacy crypt parser, while a thrown exception must stop it.
		if (std::string(argv[i]).find("synthetic-") != std::string::npos && files.back().size() <= 256)
		{
			for (size_t length = 0; length <= files.back().size(); ++length)
				if (!check(files.back().substr(0, length), nullptr,
					std::string(argv[i]) + " truncated at " + std::to_string(length))) return 1;
			for (int at = 0; at < (int)files.back().size() + 1; ++at)
				for (int fault = 0; fault < 3; ++fault)
					if (!check(files.back(), nullptr, std::string(argv[i]) + " source failure " +
						std::to_string(at) + "/" + std::to_string(fault), at, 2, fault)) return 1;
		}
		// Exercise the cached decrypt position across calls and a short encrypted
		// header, using only the first volume to keep key derivations bounded.
		if (std::string(argv[i]).find("encnam.part01") != std::string::npos)
		{
			if (!check(files.back(), "123", "repeated encrypted read", -1, 2)) return 1;
			if (!check(files.back().substr(0, 64), "123", "truncated encrypted header")) return 1;
			for (int at = 0; at < 20; ++at)
				for (int fault = 0; fault < 3; ++fault)
					if (!check(files.back(), "123", "encrypted source failure " + std::to_string(at) + "/" + std::to_string(fault), at, 1, fault)) return 1;
		}
	}
	// Fail each read of a tiny two-file archive, including after one file was
	// committed. The reference preserves completed files when a source throws.
	std::string tiny("Rar!\x1a\x07\x01\0", 8);
	const char file[] = {0,0,0,0,9,2,0,0,0,0,0,0,1,'a'};
	tiny.append(file, sizeof(file));
	tiny.append(file, sizeof(file));
	for (int at = 0; at < 35; ++at)
		for (int fault = 0; fault < 3; ++fault)
			if (!check(tiny, nullptr, "source failure " + std::to_string(at) + "/" + std::to_string(fault), at, 2, fault)) return 1;
	for (size_t length = 0; length <= tiny.size(); ++length)
		if (!check(tiny.substr(0, length), nullptr, "truncated two-file archive", -1, 2)) return 1;
	long parsed = 0;
	for (long round = 0; round < rounds; round++)
	{
		int which = below((int)files.size());
		// the headers sit at the start: mutate mostly there
		std::string data = files[which].substr(0, below(4) == 0 ? files[which].size() : std::min<size_t>(files[which].size(), 512 + below(4096)));
		int m = 1 + below(6);
		for (int i = 0; i < m && !data.empty(); i++)
		{
			size_t at = below(below(3) ? std::min<int>(256, (int)data.size()) : (int)data.size());
			switch (below(5))
			{
				case 0: data[at] = (char)next(); break;
				case 1: data[at] ^= (char)(1 << below(8)); break;
				case 2: data.erase(at, 1 + below(8)); break;
				case 3: data.insert(at, std::string(1 + below(8), (char)next())); break;
				default: data.resize(at);
			}
		}
		const char* pw = below(3) ? "123" : below(2) ? nullptr : "x";
		if (getenv("NZBGET_TEST_VERBOSE")) fprintf(stderr, "round %ld file %d size %zu pw %s\n", round, which, data.size(), pw ? pw : "-");
		if (!check(data, pw, "mutated " + std::string(argv[2 + which]) + " round " + std::to_string(round))) return 1;
		parsed++;
	}
	if (filtered == 0) return 1;
	printf("%zu volumes and %ld mutations agree; %zu non-advancing comparisons filtered (reference %s)\n", files.size(), parsed, filtered, "''' + REFERENCE + r'''");
}
'''


def vint(n):
    result = bytearray()
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def block5(kind, flags, body=b"", extra=b"", data=0, size=None):
    header = vint(kind) + vint(flags)
    if flags & 1:
        header += vint(len(extra))
    if flags & 2:
        header += vint(data)
    header += body + extra
    return bytes(4) + vint(len(header) if size is None else size) + header


def record(kind, body):
    body = vint(kind) + body
    return vint(len(body)) + body


def synthetic_volumes():
    sig5 = b"Rar!\x1a\x07\x01\0"
    end5 = block5(5, 0, b"\1")
    for name in [b"", b"a", b"a\0ignored", b"\xff\x80", b"x" * 8192, b"x" * 8193]:
        body = b"\0" + vint((1 << 64) - 1) + vint((1 << 32) + 7) + vint(7 << 7) + b"\0" + vint(len(name)) + name
        yield sig5 + block5(258, 1 << 16, body) + end5
    for distance in [0, 1, 8]:
        yield sig5 + block5(3, 2, data=(1 << 64) - 17 - distance) + end5
    body = b"\0\0\0\0\0\1a"
    crypt = b"\0\1\0" + bytes(range(44))
    for length in range(len(crypt) + 1):
        extra = record(1, crypt[:length])
        yield sig5 + block5(2, 1, body, extra) + end5
    for extra in [record(1, b"\0\0\0" + bytes(32)),
                  record(1, b"\x80" * 10), record(1, crypt) + record(1, b"\0"),
                  record(3, b"\1" + bytes(4)), record(3, b"\0" + bytes(8)),
                  record(3, b"\0" + b"\xff" * 8), record(99, bytes(9))]:
        yield sig5 + block5(2, 1, body, extra) + end5
    for value in [0, 1, 127, 128, (1 << 32), (1 << 63) - 1, (1 << 63), (1 << 64) - 1]:
        yield sig5 + block5(1, 0, vint(3) + vint(value)) + end5
        yield sig5 + block5(2, 0, body, size=value) + end5
        yield sig5 + block5(2, 2, body, data=value) + end5
    # Ten-byte vints accept (and discard) high bits in the last byte;
    # an eleventh byte is refused. Exercise ordinary and bounded readers.
    for raw in [b"\x80" * 9 + b"\x02", b"\xff" * 9 + b"\x7f",
                b"\x80" * 10, b"\x80" * 10 + b"\0"]:
        yield sig5 + block5(1, 0, b"\3" + raw) + end5
        yield sig5 + block5(2, 1, body, record(1, raw + crypt)) + end5
        yield sig5 + block5(2, 1, body, record(1, b"\0" + raw + crypt)) + end5
    # Preserve a previous complete crypt record when a later one is ignored,
    # and preserve the previous file if the next header cannot be completed.
    first = block5(2, 1, body, record(1, crypt))
    for tail in [record(1, b""), record(1, b"\0"), record(1, b"\0\1")]:
        yield sig5 + first + block5(2, 1, body, record(1, crypt) + tail) + end5
    # RAR3 end flags and block-size boundaries, including the reference filter.
    sig3 = b"Rar!\x1a\x07\0"
    for flags in range(16):
        yield sig3 + struct.pack("<HBHHII", 0, 0x7b, flags, 15, 0x12345678, 0x87654321)
    for size in [0, 1, 6, 7, 10, 11, 65535]:
        for add in [0, 1, 0xfffffff0, 0xffffffff]:
            yield sig3 + struct.pack("<HBHHI", 0, 0x74, 0x8000, size, add) + bytes(32)
    for high in [None, 0, 1, 0x80000000, 0xffffffff]:
        for salt in [b"", bytes(range(8))]:
            flags = 0x8000 | (0x100 if high is not None else 0) | (0x404 if salt else 0)
            name = b"a\0hidden"
            body = struct.pack("<IBIIBBHI", 7, 0, 0, 123, 20, 0x30, len(name), 32)
            if high is not None:
                body += struct.pack("<II", high, high)
            body += name + salt
            block = struct.pack("<HBHHI", 0, 0x74, flags, 11 + len(body), 0) + body
            yield b"Rar!\x1a\x07\0" + block + struct.pack("<HBHHI", 0, 0x7b, 9, 11, 123)

with tempfile.TemporaryDirectory(prefix="nzbget-rarreader-") as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    (temp / "old.cpp").write_text(renamed(old_src, old_header, "Old"))
    (temp / "fallback.cpp").write_text(renamed(new_src, header, "Fallback", fallback=True))
    (temp / "port.cpp").write_text(renamed(new_src, header, "Port"))
    for i, data in enumerate(synthetic_volumes()):
        path = temp / f"synthetic-{i}.rar"
        path.write_bytes(data)
        volumes.append(str(path))
    binary = temp / "rarreader"
    # an encrypted volume derives its key (PBKDF2, up to 2^24 rounds for a
    # mutated KDF count) on every read: the sanitizer build gets a quarter of
    # the mutations
    for extra, rounds in ((["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"], str(max(1, int(ROUNDS) // 4))), ([], ROUNDS)):
        compiler = [*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")),
                    *shlex.split(get("CXX_DEFINES")), *extra, "-w", *shlex.split(get("CXX_INCLUDES"))]
        # The reference has signed cursor/offset overflows on hostile sizes.
        # Pin its intended two's-complement behavior; leave the current reader
        # and fallback under normal UBSan checks so new UB is still caught.
        subprocess.run([*compiler, "-fwrapv", "-c", str(temp / "old.cpp"),
                        "-o", str(temp / "old.o")], check=True, cwd=BUILD)
        subprocess.run([*compiler, str(temp / "main.cpp"), str(temp / "old.o"),
                        str(temp / "fallback.cpp"), str(temp / "port.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
        # NZBGET_TEST_WRAPPER (e.g. "gdb -batch -ex run -ex bt --args") runs the binary under a tool
        subprocess.run([*shlex.split(os.environ.get("NZBGET_TEST_WRAPPER", "")), str(binary), rounds, *volumes], check=True)
