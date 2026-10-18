#!/usr/bin/env python3
"""Compare DirectRenamer's RenameContentAnalyzer (rust/src/renameanalyzer.rs
with the C++ wrapper of DirectRenamer.cpp), and its C++ fallback, with the
pre-port C++: random sequences of pieces (PAR2 packet headers, other data,
empty and large pieces, Reset/Finish cycles and wrapping sizes), comparing the PAR2 flag and set
id after every piece and the 16 KiB hash after every Finish. The pre-port
implementation receives an extra zero-length piece after each real piece to
complete its delayed header recognition. This is a correctness oracle for the
intentional eager-recognition fix, never a performance control. A separate
witness keeps the original delayed behavior visible.

Each version's class is compiled into its own namespace from its source.

Usage: renameanalyzer_differential.py BUILD_DIR [ROUNDS]
"""
import os
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import hashlib
import time
import stat
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "02c80b7b98608226fa8daabcbe5fdaf3143ffbdf"
REFERENCE_BLOB = "56ba7bfeebade4e0b322582fe248fa7e1cefdab3"
REFERENCE_BYTES = 20946
REFERENCE_SHA256 = "b79d880b560f738dffe1e4a1cb36337088768bdd11289ca3928be3ee332e6b10"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("build_dir", type=Path)
parser.add_argument("rounds", nargs="?", default="20000")
parser.add_argument("--reference-source", type=Path,
                    help="exact exported pre-port DirectRenamer.cpp for a frozen source tree")
parser.add_argument("--evidence-dir", type=Path,
                    help="new exclusive folder retaining generated caller, commands, raw streams and statuses")
args = parser.parse_args()
BUILD = args.build_dir.resolve()
ROUNDS = args.rounds

evidence = args.evidence_dir.resolve() if args.evidence_dir else None
if evidence:
    evidence.mkdir(parents=True, exist_ok=False)
process_number = 0


def bounded_digest(path, limit, *, include_bytes=False):
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("invalid caller artifact byte limit")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= limit:
            raise ValueError("caller artifact must be a bounded regular file")
        digest = hashlib.sha256()
        chunks = [] if include_bytes else None
        remaining = before.st_size
        while remaining:
            data = os.read(fd, min(remaining, 1024 * 1024))
            if not data:
                raise ValueError("truncated caller artifact")
            digest.update(data)
            if chunks is not None:
                chunks.append(data)
            remaining -= len(data)
        if os.read(fd, 1):
            raise ValueError("caller artifact grew")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
           (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("caller artifact changed during hashing")
        result = {"bytes": before.st_size, "sha256": digest.hexdigest()}
        if chunks is not None:
            result["data"] = b"".join(chunks)
        return result
    finally:
        os.close(fd)


def checked(argv, cwd=None, output_text=False):
    """Capture each compiler/caller process before interpreting its output."""
    global process_number
    if evidence is None:
        if output_text:
            return subprocess.check_output(argv, cwd=cwd, text=True)
        return subprocess.run(argv, cwd=cwd, check=True)
    process_number += 1
    stem = evidence / f"process-{process_number:02d}"
    stem.with_suffix(".command.json").write_text(json.dumps({
        "argv": argv, "cwd": str(cwd or Path.cwd()), "start_ns": time.time_ns(),
        "group_owner": "inherited bounded outer stage group",
    }, indent=2) + "\n")
    child = None
    code = None
    reaped = False
    raw_durable = False
    capture_error = None
    settlement_error = None
    try:
        with stem.with_suffix(".stdout.raw").open("xb") as out, stem.with_suffix(".stderr.raw").open("xb") as err:
            try:
                # Preserve the inherited outer stage group. Its owner also
                # settles compiler descendants; this helper owns the direct child.
                child = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err)
                stem.with_suffix(".process.json").write_text(json.dumps({
                    "pid": child.pid, "pgid": os.getpgrp(), "start_ns": time.time_ns(),
                }, indent=2) + "\n")
                code = child.wait()
                reaped = True
            except BaseException as error:
                capture_error = error
            finally:
                if child is not None and not reaped:
                    try:
                        if child.poll() is None:
                            try:
                                child.terminate()
                            except ProcessLookupError:
                                pass
                        try:
                            code = child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            try:
                                child.kill()
                            except ProcessLookupError:
                                pass
                            code = child.wait(timeout=2)
                        reaped = True
                    except BaseException as error:
                        settlement_error = error
                # Retain an already-known exit before optional raw durability.
                try:
                    stem.with_suffix(".wait-status.json").write_text(json.dumps({
                        "exit": code, "child_created": child is not None,
                        "reaped": reaped, "capture_complete": False,
                        "phase": "CHILD_TERMINAL_RAW_DURABILITY_PENDING",
                        "end_ns": time.time_ns(),
                    }, indent=2) + "\n")
                except BaseException as error:
                    capture_error = capture_error or error
                try:
                    for stream in [out, err]:
                        stream.flush()
                        os.fsync(stream.fileno())
                    raw_durable = True
                except BaseException as error:
                    capture_error = capture_error or error
    except BaseException as error:
        # Includes raw open/close errors after the child has been settled above.
        capture_error = capture_error or error
    terminal = {
        "exit": code, "child_created": child is not None, "reaped": reaped,
        "raw_durable": raw_durable,
        "capture_complete": reaped and raw_durable and capture_error is None and settlement_error is None,
        "capture_error": repr(capture_error) if capture_error else None,
        "settlement_error": repr(settlement_error) if settlement_error else None,
        "group_owner": "inherited bounded outer stage group; direct child only here",
        "end_ns": time.time_ns(),
    }
    try:
        stem.with_suffix(".status.json").write_text(json.dumps(terminal, indent=2) + "\n")
    except BaseException as error:
        capture_error = capture_error or error
        terminal["capture_complete"] = False
        terminal["capture_error"] = repr(capture_error)
        # The outer owner may retain this channel when the evidence disk failed.
        try:
            print("INCOMPLETE CHILD CAPTURE " + json.dumps(terminal), file=sys.stderr, flush=True)
        except BaseException:
            pass
    if not terminal["capture_complete"]:
        raise RuntimeError("Incomplete child capture; next variant must not run") from (capture_error or settlement_error)
    if code:
        raise subprocess.CalledProcessError(code, argv)
    if output_text:
        return stem.with_suffix(".stdout.raw").read_text()
    print(f"PASS captured process {process_number}: {Path(argv[0]).name}", flush=True)
    return subprocess.CompletedProcess(argv, code)


def extract(src):
    i = src.index("class RenameContentAnalyzer : public ArticleContentAnalyzer")
    decl = src[i:src.index("\n};", i) + 3]
    out = [decl]
    for sig in ("void RenameContentAnalyzer::Reset()", "void RenameContentAnalyzer::Append(const void* buffer, int len)",
                "void RenameContentAnalyzer::Finish()"):
        j = src.index(sig + "\n{")
        out.append(src[j:src.index("\n}\n", j) + 3])
    return "\n".join(out)


if args.reference_source:
    # Consume precisely the bytes hashed through this descriptor, never a
    # later path reopen. Reject nonregular, oversized and changing exports.
    reference_artifact = bounded_digest(args.reference_source, REFERENCE_BYTES, include_bytes=True)
    reference_bytes = reference_artifact.pop("data")
else:
    # The full canonical Git object is fixed, not an ambiguous short revision.
    reference_bytes = checked(["git", "show", f"{REFERENCE}:daemon/queue/DirectRenamer.cpp"],
                              cwd=ROOT, output_text=True).encode("utf-8")
    reference_artifact = {"bytes": len(reference_bytes),
                          "sha256": hashlib.sha256(reference_bytes).hexdigest()}
if reference_artifact != {"bytes": REFERENCE_BYTES, "sha256": REFERENCE_SHA256}:
    raise ValueError("reference source does not match the canonical pre-port Git blob")
reference_binding = {"commit": REFERENCE, "blob": REFERENCE_BLOB, **reference_artifact}
reference_label = f"{REFERENCE} blob {REFERENCE_BLOB} sha256 {reference_artifact['sha256']}"
old_src = reference_bytes.decode("utf-8")
if evidence:
    (evidence / "reference.binding.json").write_text(json.dumps(reference_binding, indent=2) + "\n")
new_src = (ROOT / "daemon/queue/DirectRenamer.cpp").read_text()


def new_first(src):
    # the Rust-backed definitions (the first of each pair)
    return extract(src)


def new_fallback(src):
    # the class declaration is shared; the fallback's methods are the last definitions
    i = src.index("class RenameContentAnalyzer : public ArticleContentAnalyzer")
    decl = src[i:src.index("\n};", i) + 3]
    parts = [decl]
    for sig in ("void RenameContentAnalyzer::Reset()", "void RenameContentAnalyzer::Append(const void* buffer, int len)",
                "void RenameContentAnalyzer::Finish()"):
        j = src.rindex(sig + "\n{")
        parts.append(src[j:src.index("\n}\n", j) + 3])
    return "\n".join(parts)


flags_path = BUILD / "CMakeFiles/libnzbget.dir/flags.make"
if flags_path.exists():
    flags = flags_path.read_text()
    get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
    link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
else:
    rows = json.loads((BUILD / "compile_commands.json").read_text())
    row, = [r for r in rows if r["file"].endswith("/daemon/queue/DirectRenamer.cpp")]
    argv = row.get("arguments") or shlex.split(row["command"])
    groups = {"CXX_DEFINES": [], "CXX_INCLUDES": [], "CXX_FLAGS": []}
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("-o", "-include"):
            i += 2
            continue
        if token in ("-c", "-Winvalid-pch") or token == row["file"]:
            i += 1
            continue
        key = "CXX_DEFINES" if token.startswith("-D") else "CXX_INCLUDES" if token.startswith("-I") or token == "-isystem" else "CXX_FLAGS"
        groups[key].append(token)
        if token == "-isystem":
            i += 1
            groups[key].append(argv[i])
        i += 1
    get = lambda k: shlex.join(groups[k])
    commands = checked(["ninja", "-C", str(BUILD), "-t", "commands", "nzbget"], output_text=True)
    link = shlex.split(commands.splitlines()[-1])
    library_start = next(i for i, token in enumerate(link)
                         if Path(token).name in ("libnzbget.a", "liblibnzbget.a"))
    if "&&" in link[library_start:]:
        link = link[:link.index("&&", library_start)]
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
library_start = next(i for i, token in enumerate(link)
                     if Path(token).name in ("libnzbget.a", "liblibnzbget.a"))
libs = link[library_start:]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]

main = r'''
#include "nzbget.h"
#include "ArticleDownloader.h"
#include "DirectRenamer.h"
#include "nzbget_rs.h"
#include <cstddef>
#include <memory>
#include <string>
#include <vector>
#include <par2/libpar2.h>
#include <par2/par2repairer.h>
#include <par2/par2fileformat.h>
#include <par2/md5.h>
''' + globals_block + r'''
namespace oldimpl {
''' + extract(old_src) + r'''
}
namespace newimpl {
#define NZBGET_RS_RENAME_ANALYZER
''' + new_first(new_src) + r'''
#undef NZBGET_RS_RENAME_ANALYZER
}
namespace fallbackimpl {
''' + new_fallback(new_src) + r'''
}
// These definitions must remain inert with parcheck disabled, even when the
// application otherwise links Rust. This also checks the conditional members.
#define DISABLE_PARCHECK
namespace disabledold {
''' + extract(old_src) + r'''
}
namespace disablednew {
''' + new_fallback(new_src) + r'''
}
#undef DISABLE_PARCHECK

template<class A> static void check_disabled()
{
	A a;
	a.Reset(); a.Append("PAR2\0PKT", 8); a.Append("", 0); a.Finish();
	if (a.GetParFile() || a.GetParSetId() || a.GetHash16k()) std::abort();
}

// Exercise the linked production factory and the flag read by QueueCoordinator,
// as well as the extracted implementations below. Finish must not be needed to
// make the PAR2-content guard work, and Reset must retain a recognized header.
static void check_par_content_guard()
{
	struct Renamer : DirectRenamer {
		void RenameCompleted(DownloadQueue*, NzbInfo*) override {}
	} renamer;
	auto a = renamer.MakeArticleContentAnalyzer();
	char header[64] = "PAR2\0PKT";
	a->Reset();
	if (DirectRenamer::AnalyzedParFile(a.get())) std::abort();
	a->Append(header, 63);
	if (DirectRenamer::AnalyzedParFile(a.get())) std::abort();
	a->Append(header + 63, 1);
	if (!DirectRenamer::AnalyzedParFile(a.get())) std::abort();
	a->Reset();
	a->Append("ordinary data", 13);
	if (!DirectRenamer::AnalyzedParFile(a.get())) std::abort();
}

static unsigned long long state = 0x9e3779b97f4a7c15ull;
static unsigned long long next() { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }
static int below(int n) { return n <= 0 ? 0 : (int)(next() % (unsigned long long)n); }

static void check_intentional_recognition_change()
{
	oldimpl::RenameContentAnalyzer old;
	newimpl::RenameContentAnalyzer rust;
	fallbackimpl::RenameContentAnalyzer cpp;
	char header[64] = "PAR2\0PKT";
	old.Reset(); rust.Reset(); cpp.Reset();
	old.Append(header, 64); rust.Append(header, 64); cpp.Append(header, 64);
	if (old.GetParFile() || !rust.GetParFile() || !cpp.GetParFile()) std::abort();
	old.Append(header, 0);
	if (!old.GetParFile()) std::abort();
}

template <class A> static std::string run(const std::vector<std::vector<char>>& pieces, const std::vector<int>& resets,
                                        bool complete_legacy_header = false)
{
	A a;
	std::string out;
	char empty = 0; // The legacy memcpy requires a real pointer even for zero bytes.
	a.Reset();
	for (size_t i = 0; i < pieces.size(); i++)
	{
		if (resets[i] == 1 || resets[i] == 2 || resets[i] == 4)
		{
			a.Finish(); out += std::string("H") + a.GetHash16k() + ";";
			if (resets[i] == 4) { a.Finish(); out += std::string("H") + a.GetHash16k() + ";"; }
		}
		if (resets[i] == 1 || resets[i] == 3) { a.Reset(); }
		a.Append(pieces[i].empty() ? &empty : pieces[i].data(), (int)pieces[i].size());
		if (complete_legacy_header) a.Append(&empty, 0);
		out += std::to_string(a.GetParFile()) + (a.GetParSetId() ? a.GetParSetId() : "-") + ",";
	}
	a.Finish();
	return out + "H" + a.GetHash16k();
}

static void compare(const std::vector<std::vector<char>>& pieces, const std::vector<int>& resets)
{
	std::string a = run<oldimpl::RenameContentAnalyzer>(pieces, resets, true);
	std::string b = run<newimpl::RenameContentAnalyzer>(pieces, resets);
	std::string c = run<fallbackimpl::RenameContentAnalyzer>(pieces, resets);
	if (a != b || a != c)
	{
		fprintf(stderr, "mismatch:\nold:      %s\nrust:     %s\nfallback: %s\n", a.c_str(), b.c_str(), c.c_str());
		exit(1);
	}
}

#ifdef TEST_SIZE_WRAP
// Reuse a modest real buffer: after 16 KiB the positive-size calls only count.
// The reference is built with -fwrapv in this run because its signed arithmetic
// is undefined at these boundaries. This records the intended legacy wrapping.
template<class A> static std::string wrap()
{
	A a;
	a.Reset();
	std::vector<char> buf(1024 * 1024, 'x');
	memcpy(buf.data(), "PAR2\0PKT", 8);
	for (int i = 0; i < 2048; ++i) a.Append(buf.data(), (int)buf.size());
	// INT_MIN, INT_MIN+8192, INT_MIN+16384, INT_MIN+16385.
	a.Append(buf.data(), 8192);
	a.Append(buf.data(), 8192);
	a.Append(buf.data(), 1);
	a.Append(buf.data(), 63);
	a.Finish();
	return std::to_string(a.GetParFile()) + a.GetParSetId() + a.GetHash16k();
}
#endif

int main(int argc, char** argv)
{
	check_par_content_guard();
	check_intentional_recognition_change();
	check_disabled<disabledold::RenameContentAnalyzer>();
	check_disabled<disablednew::RenameContentAnalyzer>();
#ifdef TEST_SIZE_WRAP
	auto a = wrap<oldimpl::RenameContentAnalyzer>();
	auto b = wrap<newimpl::RenameContentAnalyzer>();
	auto c = wrap<fallbackimpl::RenameContentAnalyzer>();
	if (a != b || a != c) { fprintf(stderr, "size wrap mismatch\n%s\n%s\n%s\n", a.c_str(), b.c_str(), c.c_str()); return 1; }
#endif
	std::vector<char> empty;
	empty.reserve(1);
	std::vector<char> header(64);
	memcpy(header.data(), "PAR2\0PKT", 8);
	for (int i = 8; i < 64; ++i) header[i] = (char)i;
	// Every split through the magic and the 64-byte header, with empty pieces.
	for (int split = 0; split <= 64; ++split)
	{
		std::vector<char> first(header.begin(), header.begin() + split);
		std::vector<char> second(header.begin() + split, header.end());
		first.reserve(1); second.reserve(1);
		compare({first, empty, second, empty, {'x'}, header, empty}, {0, 0, 0, 0, 1, 3, 0});
	}
	for (int byte = 0; byte < 8; ++byte)
	{
		auto bad = header; bad[byte] ^= 1;
		compare({bad, empty}, {0, 0});
	}
	for (int value = 0; value < 256; ++value)
	{
		auto h = header;
		std::fill(h.begin() + 32, h.begin() + 48, (char)value);
		compare({h, empty, {'x'}, empty, header, empty}, {0, 0, 3, 0, 3, 0});
	}
	for (int size : {0, 1, 7, 8, 31, 32, 55, 56, 63, 64, 65, 127, 128, 16383, 16384, 16385, 40000})
	{
		std::vector<char> p(size, 'a'); p.reserve(1);
		for (int mode = 0; mode <= 4; ++mode)
			compare({p, empty, {'b'}, empty, p, empty}, {0, mode, 2, 4, 1, 0});
	}
	long rounds = atol(argv[1]);
	for (long round = 0; round < rounds; round++)
	{
		std::vector<std::vector<char>> pieces;
		std::vector<int> resets;
		int n = 1 + below(8);
		for (int i = 0; i < n; i++)
		{
			int size = below(4) == 0 ? 0 : below(3) == 0 ? below(70) : below(3) == 0 ? below(40000) : below(5000);
			std::vector<char> p(size);
			p.reserve(1);  // a real buffer even when empty (the C++ memcpy'd from it)
			for (char& c : p) c = (char)next();
			if (i == 0 && size >= 8 && below(2)) memcpy(p.data(), "PAR2\0PKT", 8);
			if (i > 0 && size >= 8 && below(8) == 0) memcpy(p.data(), "PAR2\0PKT", 8);
			pieces.push_back(std::move(p));
			resets.push_back(below(3) == 0 ? below(5) : 0);
		}
		compare(pieces, resets);
	}
	printf("%ld sequences agree (reference %s with zero-piece header completion; corrected C++/Rust exact)\n", rounds, "''' + reference_label + r'''");
}
'''

with (nullcontext(evidence) if evidence else tempfile.TemporaryDirectory(prefix="nzbget-renameanalyzer-")) as temp:
    temp = Path(temp)
    (temp / "main.cpp").write_text(main)
    binary = temp / "renameanalyzer"
    # Compile the actual translation unit as well as extracted classes. In
    # particular, DISABLE_PARCHECK must not require the PAR2 headers or Rust ABI.
    for defines in (["-UNZBGET_USE_RUST"], ["-DDISABLE_PARCHECK"],
                    ["-DDISABLE_PARCHECK", "-UNZBGET_USE_RUST"]):
        includes = shlex.split(get("CXX_INCLUDES"))
        if "-DDISABLE_PARCHECK" in defines:
            includes = [flag for flag in includes if "par2-turbo" not in flag]
        checked(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                        *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *defines, *includes, "-fsyntax-only", str(ROOT / "daemon/queue/DirectRenamer.cpp")],
                       cwd=BUILD)
    for extra in (["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"],
                  ["-fwrapv", "-DTEST_SIZE_WRAP"]):
        # Keep the two independently compiled callers instead of overwriting
        # the sanitizer executable with the wrapping-arithmetic executable.
        binary = temp / ("renameanalyzer-sanitized" if "-fsanitize=address,undefined" in extra else "renameanalyzer-wrap")
        checked(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                        *extra, "-w", *shlex.split(get("CXX_INCLUDES")), str(temp / "main.cpp"), "-o", str(binary),
                        *[str(BUILD / l) if not l.startswith(("-", "/")) else l for l in libs]], cwd=BUILD)
        if evidence:
            (temp / (binary.name + ".binding.json")).write_text(json.dumps({
                **bounded_digest(binary, 512 * 1024 * 1024),
                "source_sha256": bounded_digest(temp / "main.cpp", 1024 * 1024)["sha256"],
                "reference": reference_binding,
                "Rust_archive_instrumented": False,
            }, indent=2) + "\n")
        checked(["chrt", "-i", "0", "nice", "-n", "19", str(binary), ROUNDS])
