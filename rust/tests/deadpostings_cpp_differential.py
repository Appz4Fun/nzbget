#!/usr/bin/env python3
"""Compare complete persisted records and the actual DeadPostings::Load bodies.

Linux native harness: C++ reference is immutable 2f0840a2; Rust is the supplied
production release library. C++ retains file IO/mutex/containers/pruning. The
clock is fixed at 1800000000 for repeatable synthetic state fixtures. Timings
include construction, Load, checksum of every result and destruction; fixtures
are written before timing, then read by both callers with alternating order.
Build lock is shared, each timing process holds the same exclusive lock.

Example (from repository root):
 python3 rust/tests/deadpostings_cpp_differential.py --library \\
  build/rust/Release/x86_64-unknown-linux-gnu/release/libnzbget_rs.a \\
  --artifacts evidence/final-caller --benchmark
Use --sanitize for the C++ ASan/UBSan differential; Rust's release archive is
not sanitizer-instrumented. Do not combine sanitizer mode with timing.
"""
import argparse
import contextlib
import fcntl
import hashlib
import itertools
import json
import random
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

BASE = "2f0840a2e5d2528aca427061ad5d7778ac1e255f"
HEADER = '#include <algorithm>\n#include <chrono>\n#include <cstdint>\n#include <cstdlib>\n#include <ctime>\n#include <filesystem>\n#include <fstream>\n#include <iostream>\n#include <mutex>\n#include <sstream>\n#include <string>\n#include <vector>\nusing Records=std::vector<std::pair<time_t,std::vector<uint32_t>>>;\nnamespace Posting {using Sketch=std::vector<uint32_t>;}\nnamespace fs=std::filesystem;\nnamespace Util {time_t CurrentTime(){return 1800000000;}}\nextern "C" bool nzbget_rs_deadpostings_parse(const uint8_t*,size_t,void*,void(*)(void*,int64_t,const uint32_t*,size_t));\n'
CLASS = 'struct DeadPostings {\n static constexpr int DeadTtlSec=3*24*3600;\n std::mutex m_mutex; Records m_dead,m_unsaved;std::string m_statePath;\n void Load();void Prune(time_t now);\n};\n'
MAIN = 'Records candidate(const std::string& line) {\n Records records;\n nzbget_rs_deadpostings_parse((const uint8_t*)line.data(),line.size(),&records,\n [](void* ctx,int64_t stamp,const uint32_t* data,size_t count){\n  auto* records=static_cast<Records*>(ctx);records->emplace_back((time_t)stamp,Posting::Sketch(data,data+count));\n });return records;\n}\nuint64_t digest(const Records& records) {\n uint64_t h=records.size();for(const auto& r:records){h=h*31+(uint64_t)r.first;for(auto k:r.second)h=h*31+k;}return h;\n}\nvoid print(const Records& r){std::cout<<r.size();for(const auto& e:r){std::cout<<" "<<(long long)e.first<<":";for(auto h:e.second)std::cout<<h<<",";}std::cout<<"\\n";}\nint main(int argc,char** argv){\n if(argc==1){std::string hex;while(std::getline(std::cin,hex)){std::string s;for(size_t i=0;i<hex.size();i+=2)s.push_back((char)std::stoul(hex.substr(i,2),nullptr,16));auto a=reference(s),b=candidate(s);if(a!=b){std::cerr<<"mismatch "<<hex<<"\\n";print(a);print(b);return 1;}print(a);}return 0;}\n if(std::string(argv[1])=="bench"){\n  const std::string path=argv[2]; const int repeats=std::stoi(argv[3]);\n  DeadPostings old;RustDead next;old.m_statePath=next.m_statePath=path;old.Load();next.Load();if(old.m_dead!=next.m_dead)return 2;\n  volatile uint64_t sink=0;\n  auto run=[&](bool rust){auto start=std::chrono::steady_clock::now();for(int i=0;i<repeats;i++){if(rust){RustDead d;d.m_statePath=path;d.Load();sink^=digest(d.m_dead);}else{DeadPostings d;d.m_statePath=path;d.Load();sink^=digest(d.m_dead);}}return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/repeats;};\n  for(int k=0;k<15;k++){double a,b;if(k%2){b=run(true);a=run(false);}else{a=run(false);b=run(true);}std::cout<<a<<" "<<b<<"\\n";}\n  std::cerr<<"observable_digest="<<digest(old.m_dead)<<" sink="<<sink<<"\\n";return 0;\n }\n return 0;\n}\n'

HEADER = HEADER.replace("#include <cstdlib>", "#include <cstdlib>\n#include <clocale>")
MAIN = MAIN.replace("int main(int argc,char** argv){", "int main(int argc,char** argv){\n if(const char* name=std::getenv(\"NZBGET_DEADPOSTINGS_LOCALE\")){if(!std::setlocale(LC_CTYPE,name)){std::cerr<<\"locale unavailable\\n\";return 77;}}")

def loaders(source):
    return source[source.index("void DeadPostings::Load()"):source.index("// with m_mutex held: a temporary")]

def harness(root):
    old = subprocess.check_output(["git", "show", BASE + ":daemon/dupesearch/DeadPostings.cpp"], cwd=root, text=True)
    current = (root / "daemon/dupesearch/DeadPostings.cpp").read_text()
    body = old[old.index("\t\tstd::stringstream stream(line);"):old.index("\n\t}\n\tPrune(Util::CurrentTime());")]
    body = body.replace("continue;", "return {};").replace("m_dead.emplace_back((time_t)stamp, std::move(sketch));", "return {{(time_t)stamp, std::move(sketch)}};")
    return HEADER + CLASS + loaders(old) + "#define NZBGET_USE_RUST 1\n" + CLASS.replace("DeadPostings", "RustDead") + loaders(current).replace("DeadPostings", "RustDead") + "Records reference(const std::string& line) {\n" + body + "\nreturn {};\n}\n" + MAIN

def locked_run(cmd, exclusive=False, **kwargs):
    with contextlib.ExitStack() as stack:
        if not exclusive:
            heavy = stack.enter_context((Path(tempfile.gettempdir()) / "i7-heavy.lock").open("a"))
            fcntl.flock(heavy, fcntl.LOCK_EX)
        lock = stack.enter_context((Path(tempfile.gettempdir()) / "nzbget-rust-benchmark.lock").open("a"))
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return subprocess.run(cmd, **kwargs)

def compare(exe, artifacts):
    stamps = [b"", b"0", b"-0", b"+0", b"123", b"-123", b" 123", b"\v123", b"123 ", b"+", b"garbage", b"\0", b" \0", b"123\0tail", b"9223372036854775807", b"9223372036854775808", b"-9223372036854775808", b"-9223372036854775809", b"9" * 300]
    hashes = [b"", b"0", b"1", b"1,", b"1,1,2", b"2,1", b"4294967295", b"4294967296", b"18446744073709551615", b"18446744073709551616", b"-1", b"-18446744073709551615", b"-18446744073709551616", b"+1", b" 1", b"1 ", b",1", b"1,,2", b"1,garbage,2", b"\0", b"1\0tail", b" \0", b"1,\0", b"9" * 300]
    rows = [a + b"\t" + b + t for a, b, t in itertools.product(stamps, hashes, [b"", b"\t", b"\textra\t", b"\0tail"])]
    rng = random.Random(72412)
    for _ in range(40000):
        stamp = str(rng.randrange(-(1 << 80), 1 << 80)).encode()
        hs = [str(rng.randrange(-(1 << 65), 1 << 65)).encode() for _ in range(rng.randrange(1, 10))]
        if rng.randrange(3) == 0:
            hs[rng.randrange(len(hs))] = str(rng.randrange(1 << 32)).encode()
        row = stamp + b"\t" + b",".join(hs) + b"\t"
        if rng.randrange(4) == 0:
            at = rng.randrange(len(row))
            row = row[:at] + rng.choice([b"\0", b"x", b",", b" "]) + row[at:]
        rows.append(row)
    for n in [1, 2, 63, 64, 65, 128, 1024, 10000]:
        rows.append(b"1800000000\t" + b",".join(str(rng.randrange(1 << 32)).encode() for _ in range(n)) + b"\t")
    # Balance malformed inputs with complete valid records: every hash width,
    # nonempty list length, leading whitespace/sign, embedded NUL and dedup path.
    valid_rng = random.Random(95283)
    for i in range(40000):
        stamp = str(valid_rng.randrange(-(1 << 63), 1 << 63)).encode()
        if i % 7 == 0:
            stamp = b" \v" + stamp
        if i % 11 == 0:
            stamp += b"\0ignored"
        hs = [str(valid_rng.randrange(1 << 32)).encode() for _ in range(valid_rng.randrange(1, 129))]
        if i % 3 == 0:
            hs.extend(hs[:min(5, len(hs))])
        if i % 13 == 0:
            hs[0] = b" +" + hs[0] + b"\0suffix"
        rows.append(stamp + b"\t" + b",".join(hs) + (b"," if i % 5 == 0 else b"") + b"\textra")
    corpus = "".join(row.hex() + "\n" for row in rows)
    (artifacts / "corpus.hex").write_text(corpus)
    result = locked_run([str(exe)], input=corpus, text=True, capture_output=True)
    (artifacts / "differential.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("complete-record differential failed; see differential.log")
    print(json.dumps({"cases": len(rows), "complete_outputs_match": True}), flush=True)

def benchmark(exe, artifacts, cpu):
    rng = random.Random(43167)
    summary = []
    for n, repeats in [(0, 1000), (1, 1000), (10, 100), (1000, 5), (10000, 1)]:
        state = artifacts / ("state-" + str(n) + ".txt")
        rows = []
        for i in range(n):
            hashes = [rng.randrange(1 << 32) for _ in range(64)]
            if i % 5 == 0:
                hashes.reverse()
                hashes[-1] = hashes[0]
            stamp = 1800000000 - (300000 if i % 13 == 0 else i % 259000)
            rows.append(str(stamp) + "\t" + ",".join(map(str, hashes)) + "\t\n")
        state.write_text("".join(rows))
        samples = []
        for process in range(3):
            result = locked_run(["taskset", "-c", str(cpu), str(exe), "bench", str(state), str(repeats)], exclusive=True, text=True, capture_output=True)
            (artifacts / f"load-{n}-{process}.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError("full Load caller benchmark failed")
            samples.extend(tuple(map(float, line.split())) for line in result.stdout.splitlines())
            time.sleep(0.2)
        cpp = statistics.median(x[0] for x in samples)
        rust = statistics.median(x[1] for x in samples)
        paired = [100 * (b / a - 1) for a, b in samples]
        item = {"records": n, "samples": len(samples), "cpp_ns": cpp, "rust_ns": rust, "change_percent": 100 * (rust / cpp - 1), "median_paired_change_percent": statistics.median(paired), "paired_rust_faster": sum(b < a for a, b in samples)}
        summary.append(item)
        print(json.dumps(item), flush=True)
    (artifacts / "benchmark-summary.json").write_text(json.dumps(summary, indent=2) + "\n")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--cpu", type=int, default=2)
    args = parser.parse_args()
    if args.benchmark and args.sanitize:
        parser.error("sanitizers and timing must be separate")
    root = Path(__file__).resolve().parents[2]
    library = args.library.resolve()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=False)
    source = artifacts / "driver.cpp"
    source.write_text(harness(root))
    exe = artifacts / "driver"
    flags = ["-std=c++17", "-O3", "-DNDEBUG", "-fPIC"]
    if args.sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    result = locked_run(["chrt", "-i", "0", "nice", "-n", "19", "g++", *flags, str(source), str(library), "-ldl", "-lpthread", "-lm", "-o", str(exe)], text=True, capture_output=True)
    (artifacts / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("native harness build failed; see build.log")
    metadata = {"reference_commit": BASE, "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0], "cpp_flags": flags, "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(), "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ["daemon/dupesearch/DeadPostings.cpp", "rust/src/deadpostings.rs", "rust/include/nzbget_rs.h", "rust/tests/deadpostings_cpp_differential.py"]}}
    compare(exe, artifacts)
    if args.benchmark:
        benchmark(exe, artifacts, args.cpu)
    metadata["artifact_sha256"] = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in artifacts.iterdir() if file.is_file()}
    (artifacts / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

if __name__ == "__main__":
    main()
