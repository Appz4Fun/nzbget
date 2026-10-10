#!/usr/bin/env python3
"""Compare the article Decoder (rust/src/decoder.rs) with the pre-port C++ on
generated articles fed in random pieces: yEnc single and multi-part (=ypart
on its own line or on the =ybegin line), right and wrong CRCs and sizes,
missing =yend, NNTP dot-stuffing and the end marker, UU-encoded articles,
NULs, Latin-1 names and garbage; in line and raw mode. Every DecodeBuffer
result, the decoded bytes and Check and every getter at the end must match
(the calculated CRC for yEnc only: the C++ left it uninitialized otherwise).

The reference has one fix: the C++ appended the rest of the line buffer to
itself with an overlapping strncpy (undefined behavior that glibc's vector
strncpy turns into garbled =yend lines); see the note below.

The pre-port code is compiled as OldDecoder and linked with a built libnzbget.

Usage: decoder_differential.py BUILD_DIR [ARTICLES]
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "fdc741d2"
BUILD = Path(sys.argv[1]).resolve()
ARTICLES = sys.argv[2] if len(sys.argv) > 2 else "40000"

old = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/nntp/Decoder.cpp"], cwd=ROOT, text=True)
old = re.sub(r"\bDecoder\b", "OldDecoder", old).replace('#include "OldDecoder.h"', '#include "OldDecoder.h"')
header = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/nntp/Decoder.h"], cwd=ROOT, text=True)
header = re.sub(r"\bDecoder\b", "OldDecoder", header).replace("DECODER_H", "OLDDECODER_H")
old = old.replace('#include "Decoder.h"', '#include "OldDecoder.h"')
# The C++ DecodeYenc appended the rest of the line buffer to the same buffer
# (overlapping strncpy, undefined behavior; glibc's vector strncpy can garble
# it). The Rust decoder copies it correctly, so the reference copies the rest
# first; otherwise the C++ is used as it was. OVERLAP=1 keeps the original.
if not os.environ.get("OVERLAP"):
    fixed = old.replace("m_lineBuf.Append((const char*)src, rem);",
                        "{ std::string tmp((const char*)src, rem); m_lineBuf.Append(tmp.data(), rem); }")
    assert fixed != old
    old = fixed

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]

harness = r'''
#include "nzbget.h"
#include "Decoder.h"
#include "OldDecoder.h"
#include <random>
#include <clocale>
#include <limits>
#include <string>
#include <vector>

static std::mt19937 rng(29);
static int pick(int n) { return std::uniform_int_distribution<int>(0, n - 1)(rng); }

static uint32_t crc(const std::string& s) { return rapidyenc_crc(s.data(), s.size(), 0); }

static std::string yenc_lines(const std::string& data) {
    std::string out;
    int col = 0;
    for (unsigned char c : data) {
        unsigned char e = (unsigned char)(c + 42);
        bool esc = e == 0 || e == '\n' || e == '\r' || e == '=' || (col == 0 && (e == '.' || e == '\t' || e == ' '));
        if (esc) { out += '='; out += (char)(e + 64); col += 2; } else { out += (char)e; col++; }
        if (col >= 128) { out += "\r\n"; col = 0; }
    }
    if (col) out += "\r\n";
    return out;
}

static std::string article() {
    std::string data(pick(4) ? pick(3000) : pick(20), '\0');
    for (char& c : data) c = (char)pick(256);
    const char* names[] = {"file.bin", "caf\xe9.mkv", "", "name with spaces.r01", "x=ypart begin=5 end=9"};
    std::string name = names[pick(5)];
    std::string a;
    if (pick(3)) a += "Path: x\r\nSubject: y\r\n\r\n";
    int kind = pick(12);
    if (kind < 9) {
        bool multi = pick(2);
        long size = data.size() + (pick(10) == 0 ? pick(5) - 2 : 0);
        a += "=ybegin" + std::string(multi ? " part=1 total=3" : "") + " line=128 size=" + std::to_string(size) + " name=" + name;
        if (multi && pick(3) == 0) a += "=ypart begin=1 end=" + std::to_string(data.size());
        a += pick(5) ? "\r\n" : "\n";
        if (multi && pick(2)) a += "=ypart begin=1 end=" + std::to_string(data.size()) + "\r\n";
        a += yenc_lines(data);
        if (pick(15)) {
            uint32_t c = crc(data) ^ (pick(10) == 0 ? 1u : 0u);
            char buf[64];
            snprintf(buf, sizeof buf, multi ? " pcrc32=%08x" : " crc32=%08X", c);
            a += "=yend size=" + std::to_string(data.size() + (pick(12) == 0 ? 1 : 0)) + (multi ? " part=1" : "") + buf + "\r\n";
        }
    } else if (kind < 11) {
        a += "begin 644 " + name + "\r\n";
        for (size_t i = 0; i < data.size(); i += 45) {
            size_t n = std::min<size_t>(45, data.size() - i);
            std::string line(1, (char)(' ' + n));
            for (size_t k = 0; k < n; k += 3) {
                unsigned char b0 = data[i + k], b1 = k + 1 < n ? data[i + k + 1] : 0, b2 = k + 2 < n ? data[i + k + 2] : 0;
                for (int v : {b0 >> 2, ((b0 & 3) << 4) | (b1 >> 4), ((b1 & 15) << 2) | (b2 >> 6), b2 & 63}) line += (char)(v ? ' ' + v : '`');
            }
            if (pick(20) == 0) line.resize(line.size() / 2);
            a += line + "\r\n";
        }
        a += "`\r\nend\r\n";
    } else {
        a += std::string(pick(200), 'x');
        for (int i = 0; i < 30; ++i) a += "=ybegin \r\n=yend \r\n.\r\nM\r\n"[pick(26)];
    }
    // NNTP: dot-stuffing and the end marker
    std::string out;
    size_t start = 0;
    while (start < a.size()) {
        size_t nl = a.find('\n', start);
        std::string line = a.substr(start, nl == std::string::npos ? std::string::npos : nl - start + 1);
        if (!line.empty() && line[0] == '.') out += '.';
        out += line;
        start = nl == std::string::npos ? a.size() : nl + 1;
    }
    if (pick(8)) out += ".\r\n";
    if (pick(20) == 0) for (int i = 0; i < 3; ++i) out[pick(out.size())] = (char)pick(256);
    return out;
}


// Check every piece, including output beyond its input length. The caller owns
// 63 bytes of decode slack, followed by a canary checked after every call.
static void regression(const std::vector<std::string>& pieces, bool raw = false, bool zeroLength = false) {
    OldDecoder o;
    Decoder r;
    o.SetRawMode(raw); r.SetRawMode(raw);
    o.SetCrcCheck(true); r.SetCrcCheck(true);
    for (const auto& piece : pieces) {
        size_t capacity = piece.size() + 63;
        std::vector<char> bo(capacity + 32, 'Z'), br(bo);
        memcpy(bo.data(), piece.data(), piece.size());
        memcpy(br.data(), piece.data(), piece.size());
        bo[piece.size()] = br[piece.size()] = 0;
        int len = zeroLength ? 0 : (int)piece.size();
        int lo = o.DecodeBuffer(bo.data(), len), lr = r.DecodeBuffer(br.data(), len);
        bool same = lo == lr && lo >= 0 && (size_t)lo <= capacity &&
            !memcmp(bo.data(), br.data(), lo) && o.GetEof() == r.GetEof() &&
            o.Check() == r.Check() && o.GetFormat() == r.GetFormat() &&
            o.GetSize() == r.GetSize() && o.GetBeginPos() == r.GetBeginPos() &&
            o.GetEndPos() == r.GetEndPos() && o.GetExpectedCrc() == r.GetExpectedCrc() &&
            !strcmp(o.GetArticleFilename(), r.GetArticleFilename());
        for (size_t i = capacity; i < bo.size(); ++i) same &= bo[i] == 'Z' && br[i] == 'Z';
        if (!same) {
            fprintf(stderr, "regression mismatch: piece size %zu, raw %d, zero length %d, output %d/%d\n",
                piece.size(), raw, zeroLength, lo, lr);
            exit(1);
        }
    }
}

static void regressions() {
    regression({"\r\n.\r\nx", "more"}, true); // state 0 preserves EOF
    regression({"\r\n.\r\nx", "\r", "x"}, true); // state 1 resets EOF
    regression({"begin 644 x\r\n#04)#\r\n`\r\n"}, false, true);
    regression({"begin 644 x\r\n_" + std::string(84, 'A'), "\n"}); // 63 bytes from one input byte
    regression({"begin 644 x\r\n" + std::string(20000, '\n')});
    regression({"=ybegin part=1\r\n" + std::string(20000, '\n')});
    const char* numbers[] = {"0", "-1", "+0xabcdef", "-10000000000000000",
        "100000000", "-fffffffffffffffff", "fffffffffffffffffffffffffff", " \t\v\f123abc", "0x", "0Xf"};
    for (const char* locale : {"C", "C.UTF-8", "en_US.UTF-8"}) {
        if (!std::setlocale(LC_ALL, locale)) continue;
        for (const char* number : numbers) {
            std::string a = "=ybegin size=" + std::string(number) + " name=x\r\n*\r\n=yend size=1 crc32=" + number + "\r\n.\r\n";
            for (size_t split = 1; split < a.size(); ++split)
                regression({a.substr(0, split), a.substr(split)});
        }
    }
    std::setlocale(LC_ALL, "C");
    // Buffer contents past a line are intentionally visible to the old parser.
    for (const std::string& a : {
        std::string("=ybegin part=1 name=\r\n=ypart begin=1 end=2\r\n**\r\n=yend size=2 pcrc32=0\r\n"),
        std::string("begin 644 \r\n#04)#\r\n`\r\n"),
        std::string("begin 644 x\r\nM") + std::string(60, 'A') + "\n\n`\r\n",
        std::string("ignored\r\n\0=ybegin size=1 name=x\r\n", sizeof("ignored\r\n\0=ybegin size=1 name=x\r\n") - 1)}) {
        for (size_t split = 1; split < a.size(); ++split)
            regression({a.substr(0, split), a.substr(split)});
    }
    puts("decoder regressions agree");
}

int main(int argc, char** argv) {
    rapidyenc_decode_init();
    rapidyenc_crc_init();
    regressions();
    long cases = 0;
    int articles = atoi(argv[1]);
    for (int n = 0; n < articles; ++n) {
        std::string a = article();
        OldDecoder o;
        Decoder r;
        bool raw = pick(10) == 0;
        bool crcCheck = pick(4) != 0;
        o.Clear(); r.Clear();
        o.SetCrcCheck(crcCheck); r.SetCrcCheck(crcCheck);
        o.SetRawMode(raw); r.SetRawMode(raw);
        size_t at = 0;
        while (at < a.size()) {
            size_t len = std::min(a.size() - at, (size_t)(pick(4) ? 1 + pick(64) : 1 + pick(4000)));
            // the connection's buffer: room past the piece for what the C++ wrote there
            std::vector<char> bo(len + 63 + 32, 0), br(len + 63 + 32, 0);
            std::fill(bo.begin() + len + 63, bo.end(), 'Z');
            std::fill(br.begin() + len + 63, br.end(), 'Z');
            memcpy(bo.data(), a.data() + at, len);
            memcpy(br.data(), a.data() + at, len);
            int lo = o.DecodeBuffer(bo.data(), (int)len), lr = r.DecodeBuffer(br.data(), (int)len);
            bool guard = lo >= 0 && lr >= 0 && (size_t)lo <= len + 63 && (size_t)lr <= len + 63;
            for (size_t q = len + 63; q < bo.size(); ++q) guard &= bo[q] == 'Z' && br[q] == 'Z';
            if (!guard || lo != lr || memcmp(bo.data(), br.data(), std::max(lo, 0)) || o.GetEof() != r.GetEof()) {
                printf("MISMATCH DecodeBuffer article %d at %zu len %zu: %d vs %d eof %d %d\n", n, at, len, lo, lr, o.GetEof(), r.GetEof());
                int k = 0;
                while (k < std::min(lo, lr) && bo[k] == br[k]) ++k;
                printf("  first difference at %d of the output\n  piece:", k);
                for (size_t q = 0; q < std::min<size_t>(len, 120); ++q) printf(" %02x", (unsigned char)a[at + q]);
                printf("\n  piece end:");
                for (size_t q = len > 60 ? len - 60 : 0; q < len; ++q) printf(" %02x", (unsigned char)a[at + q]);
                printf("\n  C++ out:");
                for (int q = std::max(0, k - 8); q < std::min(lo, k + 8); ++q) printf(" %02x", (unsigned char)bo[q]);
                printf("\n  Rust out:");
                for (int q = std::max(0, k - 8); q < std::min(lr, k + 8); ++q) printf(" %02x", (unsigned char)br[q]);
                printf("\n  input around:");
                for (size_t q = 0; q + 1 < len; ++q) if (a[at+q] == '\n') { printf(" [nl@%zu]", q); }
                printf("\n");
                return 1;
            }
            at += len;
            if (o.GetEof() && pick(2)) break;
        }
        int so = o.Check(), sr = r.Check();
        if (so != sr || o.GetFormat() != r.GetFormat() || o.GetBeginPos() != r.GetBeginPos() || o.GetEndPos() != r.GetEndPos() ||
            o.GetSize() != r.GetSize() || o.GetExpectedCrc() != r.GetExpectedCrc() ||
            // the C++ left the calculated CRC uninitialized for UU articles (Check sets it for yEnc only)
            (o.GetFormat() == OldDecoder::efYenc && o.GetCalculatedCrc() != r.GetCalculatedCrc()) ||
            strcmp(o.GetArticleFilename(), r.GetArticleFilename())) {
            printf("MISMATCH end of article %d: status %d %d format %d %d begin %lld %lld end %lld %lld size %lld %lld crc %x %x / %x %x name [%s] [%s]\n",
                n, so, sr, o.GetFormat(), r.GetFormat(), (long long)o.GetBeginPos(), (long long)r.GetBeginPos(), (long long)o.GetEndPos(),
                (long long)r.GetEndPos(), (long long)o.GetSize(), (long long)r.GetSize(), o.GetExpectedCrc(), r.GetExpectedCrc(),
                o.GetCalculatedCrc(), r.GetCalculatedCrc(), "", "");
            for (const char* nm : {o.GetArticleFilename(), r.GetArticleFilename()}) {
                printf("  name:");
                for (const unsigned char* q = (const unsigned char*)nm; *q; ++q) printf(" %02x", *q);
                printf("\n");
            }
            return 1;
        }
        ++cases;
    }
    printf("%ld articles agree (reference %s)\n", cases, "''' + REFERENCE + r'''");
}
'''
with tempfile.TemporaryDirectory(prefix="nzbget-decoder-") as temp:
    temp = Path(temp)
    (temp / "OldDecoder.h").write_text(header)
    (temp / "OldDecoder.cpp").write_text(old)
    (temp / "main.cpp").write_text(harness)
    binary = temp / "decoder"
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-w", f"-I{temp}", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), str(temp / "OldDecoder.cpp"),
                    "-o", str(binary), *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], check=True, cwd=BUILD)
    subprocess.run([str(binary), ARTICLES], check=True)
