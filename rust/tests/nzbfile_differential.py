#!/usr/bin/env python3
"""Compare NzbFile with its Rust parts (rust/src/nzbfile.rs: the segments'
order, the declared parts and tail, the file sizes, the duplicate-filename
test) against the pre-port NzbFile.cpp, by parsing the same nzb files with
both and comparing everything they produce: the files in order with their
names, subjects, sizes, missed and total counts, par flag, cut-short flag
and segments (part number, size, message-id), and the nzb's totals, par
sizes, content hashes, ManyDupeFiles, password and meta names.

Two programs are built from the build's flags: one from the reference's
NzbFile.cpp, one from this tree's (with Rust). Each reads nzb paths from
stdin and prints a dump per nzb; the dumps must be identical.

Usage:
  nzbfile_differential.py BUILD_DIR [COUNT]
      random nzbs (subjects with and without "(1/N)", tails cut short or
      padded, par2 files, segments out of order, repeated and missing,
      sizes even and mixed, colliding filenames, Latin-1 bytes) under the C
      and C.UTF-8 locales, the old program under ASan/UBSan too.
  nzbfile_differential.py BUILD_DIR --corpus DIR...
      every *.nzb under the directories, read only, in batches of 300; a
      summary on stdout.
"""
import os
from pathlib import Path
import random
import re
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "c4672f0b"
BUILD = Path(sys.argv[1]).resolve()
CORPUS = sys.argv[3:] if len(sys.argv) > 2 and sys.argv[2] == "--corpus" else None
COUNT = int(sys.argv[2]) if len(sys.argv) > 2 and not CORPUS else 3000

old_src = subprocess.check_output(["git", "show", f"{REFERENCE}:daemon/queue/NzbFile.cpp"], cwd=ROOT, text=True)
assert "NZBGET_USE_RUST" not in old_src, "the reference must be the pre-port NzbFile.cpp"
for needle in ("int NzbFile::DeclaredParts(const char* subject)", "int NzbFile::DeclaredTail(FileInfo* fileInfo)",
               "bool NzbFile::HasDuplicateFilenames()", "std::stable_sort(articles->begin(), articles->end(),"):
    assert needle in old_src, needle

flags = (BUILD / "CMakeFiles/libnzbget.dir/flags.make").read_text()
get = lambda k: re.search(rf"^{k} = (.*)$", flags, re.M).group(1)
if "-DNZBGET_USE_RUST" not in get("CXX_DEFINES"):
    sys.exit("the build doesn't use Rust: nothing to compare")
link = (BUILD / "CMakeFiles/nzbget.dir/link.txt").read_text().split()
libs = link[link.index("liblibnzbget.a"):]
tests_main = (ROOT / "tests/main.cpp").read_text()
globals_block = tests_main[tests_main.index('#include "ServerPool.h"'):tests_main.index("void ExitProc(){}") + len("void ExitProc(){}")]

main = r'''
#include "nzbget.h"
#include "NzbFile.h"
#include "Options.h"
#include "Log.h"
#include <chrono>
#include <clocale>
#include <iostream>
#include <string>
''' + globals_block + r'''

int main(int argc, char** argv)
{
	setlocale(LC_ALL, "");
	Log log;
	Options::CmdOptList cmdOpts;
	cmdOpts.push_back("ParIgnoreExt=.nfo,.sfv");
	Options options(&cmdOpts, nullptr);
	double seconds = 0;
	std::string path;
	long count = 0;
	while (std::getline(std::cin, path))
	{
		NzbFile nzb(path.c_str(), "");
		auto start = std::chrono::steady_clock::now();
		bool ok = nzb.Parse();
		seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
		count++;
		std::string out = "nzb " + path + (ok ? " ok\n" : " failed\n");
		if (ok)
		{
			NzbInfo* n = nzb.DetachNzbInfo().release();
			out += *CString::FormatStr(" totals %lli %lli %lli %lli %lli %i %i %i %u %u %i %i [%s][%s][%s][%s]\n",
				n->GetSize(), n->GetRemainingSize(), n->GetFailedSize(), n->GetParSize(), n->GetParFailedSize(),
				n->GetFileCount(), n->GetTotalArticles(), n->GetFailedArticles(), n->GetFullContentHash(),
				n->GetFilteredContentHash(), (int)n->GetManyDupeFiles(), n->GetRemainingParCount(),
				nzb.GetPassword().c_str(), nzb.GetMetaName().c_str(), nzb.GetMetaTitle().c_str(),
				nzb.GetCategoryFromFile().c_str());
			for (FileInfo* f : n->GetFileList())
			{
				out += *CString::FormatStr(" file [%s][%s] %lli %lli %lli %i %i %i %i\n", f->GetFilename(), f->GetSubject(),
					f->GetSize(), f->GetRemainingSize(), f->GetMissedSize(), f->GetTotalArticles(), f->GetMissedArticles(),
					(int)f->GetParFile(), (int)nzb.GetCutShortFiles().count(f));
				for (ArticleInfo* a : f->GetArticles())
				{
					out += *CString::FormatStr("  seg %i %lli %s\n", a->GetPartNumber(), a->GetSize(), a->GetMessageId());
				}
			}
			delete n;
		}
		fwrite(out.data(), 1, out.size(), stdout);
	}
	fprintf(stderr, "parsed %ld nzbs in %.3f s\n", count, seconds);
	return 0;
}
'''

ESC = {ord("&"): "&amp;", ord("<"): "&lt;", ord(">"): "&gt;", ord('"'): "&quot;"}


def random_nzbs(folder, count, rnd):
    paths = []
    for n in range(count):
        files = rnd.choice([1, 2, 2, 3, 5, 8, 40]) if rnd.random() < 0.97 else rnd.choice([300, 1200])
        base = rnd.choice(["Show.S01E01.1080p", "movie", "a", "x" * rnd.randint(1, 1100), "caf\xe9 \xc0", "name {{pw}}"])
        names = [rnd.choice(["%s.part%02d.rar" % (base, k), "%s.vol%02d+%02d.PAR2" % (base, k, k), "%s.nfo" % base,
                             "%s.r%02d" % (base, k % 4), "same.bin"]) for k in range(files)]
        body = []
        for k in range(files):
            listed = rnd.choice([1, 2, 3, 5, 20, 150, 400]) if files < 50 else rnd.choice([1, 2, 5])
            declared = rnd.choice([0, listed, listed + rnd.randint(1, 99), listed + 100 + rnd.randint(0, 5000),
                                   int(listed * 1.6), 1000000, 1000001, 12345678])
            tail = rnd.choice(["", " ", "  \t", "\r"])
            subject = rnd.choice([
                '"%s" yEnc (1/%d)%s' % (names[k], declared, tail),
                '[%d/%d] - "%s" yEnc (%d/%d)%s' % (k + 1, files, names[k], 1, declared, tail),
                '%s (%d/%d)' % (names[k], rnd.randint(0, 9), declared),
                '"%s" yEnc [1/%d]' % (names[k], declared),
                '"%s" yEnc (/%d)' % (names[k], declared),
                '"%s"' % names[k],
                "(1/%d)" % declared,
            ])
            if rnd.random() < 0.1:
                subject = "%s %s" % ("p" * 1015, subject)
            if rnd.random() < 0.05:
                # ".par2" ending at the 1023rd, 1024th or 1025th byte: the cut is 1023
                subject = "%s.par2 yEnc (1/%d)" % ("q" * rnd.choice([1017, 1018, 1019, 1020]), declared)
            full = rnd.choice([716800, 768000, 400000])
            parts = list(range(1, listed + 1))
            if rnd.random() < 0.3:
                parts = rnd.sample(range(1, listed * 2 + 3), listed)
            if rnd.random() < 0.2 and parts:
                parts += [rnd.choice(parts) for _ in range(rnd.randint(1, 3))]
            if rnd.random() < 0.3:
                rnd.shuffle(parts)
            mixed = rnd.random() < 0.3
            sizes = [full + (rnd.randint(-9000, 9000) if mixed else 0) for _ in parts]
            if sizes and rnd.random() < 0.5:
                sizes[-1] = rnd.choice([full, full - 1, full + 1, full * 2, int(full * 0.995), rnd.randint(1, full)])
            if len(parts) >= 3 and rnd.random() < 0.15:
                # distinct sizes in hundreds and a last one at 99 % of the median, give or take one
                sizes = [full + 100 * k for k in rnd.sample(range(-2000, 2000), len(parts))]
                median = sorted(sizes[:-1] + [0])[len(parts) // 2]
                sizes[-1] = median * 99 // 100 + rnd.choice([-1, 0, 0, 1])
            segs = []
            for i, part in enumerate(parts):
                size = sizes[i]
                if rnd.random() < 0.02:
                    size = rnd.choice([0, -5])
                segs.append('<segment bytes="%d" number="%d">%s-%d-%d@news.example</segment>' % (size, part, rnd.choice(["m", "id"]), k, i))
            poster = "p@example.com"
            body.append('<file poster="%s" date="%d" subject="%s"><groups><group>a.b</group></groups><segments>%s</segments></file>'
                        % (poster, 1700000000 + k, subject.translate(ESC), "".join(segs)))
        head = rnd.choice(["", '<head><meta type="password">secret</meta><meta type="name">Meta Name</meta></head>',
                           '<head><meta type="title">T\xeftle</meta><meta type="category">TV &gt; HD</meta></head>'])
        xml = ('<?xml version="1.0" encoding="iso-8859-1"?>\n<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">%s%s</nzb>\n'
               % (head, "".join(body)))
        path = folder / ("%05d%s.nzb" % (n, rnd.choice(["", " {{filepw}}"])))
        path.write_bytes(xml.encode("latin-1"))
        paths.append(str(path))
    return paths


def build(temp, name, source, rust, extra):
    (temp / f"{name}.cpp").write_text(source)
    (temp / f"{name}-main.cpp").write_text(main)
    binary = temp / name
    defines = shlex.split(get("CXX_DEFINES")) + ([] if rust else ["-UNZBGET_USE_RUST"])
    subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", *shlex.split(os.environ.get("CXX", "c++")),
                    *shlex.split(get("CXX_FLAGS")), *defines, *extra, "-w", *shlex.split(get("CXX_INCLUDES")),
                    str(temp / f"{name}.cpp"), str(temp / f"{name}-main.cpp"), "-o", str(binary), *libs],
                   check=True, cwd=BUILD)
    return binary


def run(binary, paths, locale):
    proc = subprocess.run(["chrt", "-i", "0", "nice", "-n", "19", str(binary)], input="\n".join(paths) + "\n",
                          capture_output=True, text=True, errors="surrogateescape", check=True,
                          env={**os.environ, "LC_ALL": locale, "ASAN_OPTIONS": "detect_leaks=0"})
    return proc.stdout, proc.stderr.strip()


def compare(a, b):
    """The nzbs whose dumps differ."""
    split = lambda s: re.split(r"(?m)^(?=nzb )", s)
    left, right = split(a), split(b)
    if len(left) != len(right):
        return ["(different numbers of nzbs)"]
    return [x.split("\n", 1)[0] for x, y in zip(left, right) if x != y]


with tempfile.TemporaryDirectory(prefix="nzbget-nzbfile-") as temp:
    temp = Path(temp)
    new_src = (ROOT / "daemon/queue/NzbFile.cpp").read_text()
    subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), *shlex.split(get("CXX_FLAGS")), *shlex.split(get("CXX_DEFINES")),
                    "-UNZBGET_USE_RUST", *shlex.split(get("CXX_INCLUDES")), "-fsyntax-only", str(ROOT / "daemon/queue/NzbFile.cpp")],
                   check=True, cwd=BUILD)
    old = build(temp, "old", old_src, False, ["-O2"])
    new = build(temp, "new", new_src, True, ["-O2"])
    if CORPUS:
        # in batches: a big corpus's dumps don't fit in memory at once
        paths = sorted(str(p) for d in CORPUS for p in Path(d).rglob("*.nzb"))
        bad = []
        seconds = {"old": 0.0, "new": 0.0}
        for start in range(0, len(paths), 300):
            batch = paths[start:start + 300]
            a, ta = run(old, batch, "C.UTF-8")
            b, tb = run(new, batch, "C.UTF-8")
            bad += compare(a, b)
            for name, t in (("old", ta), ("new", tb)):
                seconds[name] += float(re.search(r"in ([0-9.]+) s", t).group(1))
        print(f"{len(paths)} nzbs; parsed by old in {seconds['old']:.1f} s, by new in {seconds['new']:.1f} s")
        print(f"{len(paths) - len(bad)} identical, {len(bad)} differ")
        for line in bad[:20]:
            print("  differs:", line)
        sys.exit(1 if bad else 0)

    rnd = random.Random(20261011)
    folder = temp / "nzbs"
    folder.mkdir()
    paths = random_nzbs(folder, COUNT, rnd)
    sanitize = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    sanitized = build(temp, "new-asan", new_src, True, sanitize)
    old_sanitized = build(temp, "old-asan", old_src, False, sanitize)
    failures = 0
    for locale in ("C", "C.UTF-8"):
        a, ta = run(old, paths, locale)
        # the reference under ASan/UBSan too: its dump must not change either
        bad = compare(a, run(old_sanitized, paths, locale)[0])
        print(f"locale {locale}, old-asan: {len(paths) - len(bad)} of {len(paths)} nzbs identical to old")
        failures += len(bad)
        for binary in (new, sanitized):
            b, tb = run(binary, paths, locale)
            bad = compare(a, b)
            print(f"locale {locale}, {binary.name}: {len(paths) - len(bad)} of {len(paths)} nzbs identical ({ta}; {tb})")
            for line in bad[:5]:
                print("  differs:", line)
            failures += len(bad)
    lines = a.splitlines()
    cut = sum(1 for line in lines if line.startswith(" file ") and line.endswith(" 1"))
    many = sum(1 for line in lines if line.startswith(" totals ") and line.split()[11] == "1")
    failed = sum(1 for line in lines if line.startswith("nzb ") and line.endswith(" failed"))
    print(f"(reference {REFERENCE}; in the last run {cut} cut-short files, {many} nzbs with ManyDupeFiles, {failed} failed parses)")
    sys.exit(1 if failures else 0)
