#!/usr/bin/env python3
"""Offline watcher differential. Run on the approved remote build host only.

The Python legacy oracle follows DupeSearch::Prepare's branch order; proxy-only
managed fleets, historical ranking and rename decisions have separate fixtures.
No daemon, config, indexer or NNTP connection is made.
"""
import itertools
from collections import Counter
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
BITS = {name: 1 << bit for bit, name in enumerate([
    "enabled", "check", "present", "nzb", "history", "success", "deleting",
    "none", "manual", "dupe", "copy", "good", "post", "score", "donor", "auto", "fleet"])}
LIVE = sum(BITS[x] for x in ["enabled", "check", "present", "nzb", "none", "score"])


def legacy(flags, score, higher, now, prev_time, prev_score, changed):
    def has(name):
        return bool(flags & BITS[name])
    if not (has("enabled") and has("check") and has("present") and has("nzb")):
        return 0
    if has("history"):
        if has("success") or any(has(s) for s in ["manual", "dupe", "copy", "good"]):
            return 0
    else:
        if has("deleting") or not has("none"):
            return 0
        if has("post"):
            return 1
    if not has("score") or has("donor") or has("auto"):
        return 0
    if higher > score:
        return 0
    if prev_time >= 0 and now - prev_time < 21600 and prev_score >= max(score, 1000000):
        return 0
    return 2


def reference_parts(parts, declared, parity):
    listed = len(parts)
    numbers = [n for n, _ in parts]
    valid = bool(numbers) and min(numbers) >= 1 and max(numbers) <= 200000
    numbered = max(max(numbers), listed) if valid else listed
    # Exact proxy truncation guards, with explicit extra safety guards for
    # unusable numbering/size and malicious subject counts over200000.
    if (not valid or declared > 200000 or any(b <= 0 for _, b in parts)
            or parity or listed < 2 or listed * 3 >= declared * 2):
        return listed, numbered
    last_no, last_bytes = max(parts)
    if declared - last_no < 100:
        return listed, numbered
    sizes = [b for _, b in parts]
    common, count = Counter(sizes).most_common(1)[0]
    full = last_bytes == common if count * 2 > listed else last_bytes >= 0.99 * sorted(sizes)[listed // 2]
    return listed, declared if full else numbered


def main():
    # Full Boolean combinations of legacy flags, legal native deletion statuses,
    # score ties, six-hour boundary, clock rollback, and score escalation.
    switches = ["enabled", "check", "present", "nzb", "history", "success", "deleting", "post", "score", "donor", "auto"]
    stamp_cases = [(0, -1, 0), (100, 100, 1000000), (21699, 100, 1000000),
                   (21700, 100, 1000000), (99, 100, 1000000)]
    rows, expected = [], []
    for choices in itertools.product([False, True], repeat=len(switches)):
        base = sum(BITS[s] for s, yes in zip(switches, choices) if yes)
        for deletion in [0] + [BITS[s] for s in ["none", "manual", "dupe", "copy", "good"]]:
            flags = base | deletion
            for score, higher in [(0, 0), (3, 4), (1000001, 1000001)]:
                for now, prev_time, prev_score in stamp_cases:
                    row = (flags, score, higher, now, prev_time, prev_score, 0)
                    rows.append(row)
                    expected.append(legacy(*row))
    legacy_count = len(rows)
    # Deliberate proxy-only behavior, not claimed as legacy equivalence.
    for row, answer in [
        ((LIVE | BITS["fleet"], 0, 0, 1, -1, 0, 0), 0),
        ((LIVE, 0, 0, 101, 100, 1000000, 1), 2),
        ((LIVE, 0, 0, 102, 101, 1000000, 0), 0),
    ]:
        rows.append(row)
        expected.append(answer)
    with tempfile.TemporaryDirectory(prefix="dupewatch-differential-") as tmp:
        harness = pathlib.Path(tmp) / "harness.rs"
        harness.write_text('''#[allow(dead_code)]
#[path = "''' + str(ROOT / "src/dupewatch.rs") + '''"] mod dupewatch;
#[path = "''' + str(ROOT / "src/bytes.rs") + '''"] mod bytes;
#[path = "''' + str(ROOT / "src/releasename.rs") + '''"] mod releasename;
use std::io::{self, BufRead, Write};
fn main() {
    let title = b"The.Show.S01E02.2025.1080p.WEB-DL.x264-GRP";
    assert_eq!(dupewatch::lenient_queries(title), vec![b"the show".to_vec(), b"the show s01e02 2025".to_vec()]);
    assert_eq!(dupewatch::lenient_queries(b"Some.Movie.2024.2160p.BluRay-GRP"), vec![b"some movie".to_vec(), b"some movie 2024".to_vec()]);
    let began = std::time::Instant::now();
    for _ in 0..10_000 {
        std::hint::black_box(dupewatch::lenient_queries(std::hint::black_box(title)));
        std::hint::black_box(dupewatch::should_expand(std::hint::black_box(0.84), 5, false, false));
    }
    eprintln!("Actual Rust query/expansion benchmark: 10000 iterations in {:?}; episode/year fixtures passed", began.elapsed());
    let mut out = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields[0] == "C" {
            let declared = fields[1].parse().unwrap(); let parity = fields[2] == "1";
            let parts: Vec<_> = fields[3..].chunks_exact(2).map(|p| (p[0].parse().unwrap(),p[1].parse().unwrap())).collect();
            let (listed,total) = dupewatch::part_counts(&parts,declared,parity);
            writeln!(out,"{} {}",listed,total).unwrap(); continue;
        }
        if fields[0] == "D" {
            let volumes: Vec<u64> = fields[5..].iter().map(|p|p.parse().unwrap()).collect();
            writeln!(out,"{}",dupewatch::par_doomed(fields[1].parse().unwrap(),fields[2].parse().unwrap(),&volumes,fields[3].parse().unwrap(),fields[4].parse().unwrap()) as u8).unwrap(); continue;
        }
        if fields[0] == "U" {
            writeln!(out,"{}",dupewatch::unlisted_missing(fields[1].parse().unwrap(),fields[2].parse().unwrap(),fields[3].parse().unwrap())).unwrap(); continue;
        }
        if fields[0] == "E" {
            writeln!(out,"{}",dupewatch::effective_alive(fields[1].parse().unwrap(),fields[2].parse().unwrap(),fields[3].parse().unwrap(),fields[4].parse().unwrap(),fields[5].parse().unwrap())).unwrap(); continue;
        }
        if fields[0] == "W" {
            writeln!(out,"{}",dupewatch::whole_bytes(fields[1].parse().unwrap(),fields[2].parse().unwrap(),fields[3].parse().unwrap())).unwrap(); continue;
        }
        if fields[0] == "A" {
            writeln!(out,"{}",dupewatch::weighted_alive(fields[1].parse().unwrap(),fields[2].parse().unwrap(),fields[3].parse().unwrap())).unwrap(); continue;
        }
        let v: Vec<i64> = line.split_whitespace().map(|x| x.parse().unwrap()).collect();
        let previous = if v[4] < 0 { None } else { Some(dupewatch::SearchStamp {time:v[4],score:v[5] as i32}) };
        let decision = dupewatch::decide(v[0] as u32, v[1] as i32, Some(v[2] as i32), v[3], previous, v[6] != 0);
        writeln!(out, "{}", decision as u32).unwrap();
    }
}''')
        binary = pathlib.Path(tmp) / "harness"
        rustc = pathlib.Path.home() / ".cargo/bin/rustc"
        subprocess.run([str(rustc), "--edition=2021", "-Awarnings", "-O", str(harness), "-o", str(binary)], check=True)
        text = "".join(" ".join(map(str, row)) + "\n" for row in rows)
        proc = subprocess.run([str(binary)], input=text, text=True, capture_output=True, check=True)
        actual = list(map(int, proc.stdout.splitlines()))
        print(proc.stderr.strip())
        assert len(actual) == len(expected), (len(actual), len(expected))
        for i, (got, want) in enumerate(zip(actual, expected)):
            assert got == want, (i, rows[i], got, want)
        print(f"PASS: {legacy_count} legacy decisions; {len(rows) - legacy_count} explicit proxy-only decisions")
        fixtures = []
        for parts in [[], [(9374,100)], [(1,100),(2,100)], [(1,100),(2,30)],
                      [(1,100),(3,100)], [(0,100),(2,100)], [(-1,100),(2,100)],
                      [(1,100),(200001,100)], [(1,100),(2,-100)],
                      [(1,100),(2,101),(3,102),(4,99)], [(1,100),(2,101),(3,102),(4,100)]]:
            for declared in [0,101,140,1000,200001]:
                for parity in [False,True]:
                    request = f'C {declared} {int(parity)} ' + ' '.join(str(v) for pair in parts for v in pair)
                    expected_parts = reference_parts(parts,declared,parity)
                    fixtures.append((request, ' '.join(map(str,expected_parts))))
        for total in [0,1,3,123456789]:
            for listed,declared in [(0,100),(2,5),(5,5),(5,2),(2,1000)]:
                share = listed / declared
                whole = round(total / share) if 0 < share < 1 else total
                fixtures.append((f'W {total} {listed} {declared}',str(whole)))
        for alive in [-1,0,0.5,1,2]:
            for listed,declared in [(0,100),(2,5),(5,5),(5,2)]:
                share = listed / declared
                health = alive if alive < 0 else min(1,alive) * (share if 0 < share < 1 else 1)
                fixtures.append((f'A {alive} {listed} {declared}',str(health)))
        for present,missing,error in [(13,0,0),(5,0,0),(7,0,0),(4,0,100),(0,0,100),(8,2,99),(5,5,0)]:
            answered = present + missing + error
            for listed,declared in [(0,10),(3,10),(2,3),(10,3),(5,10)]:
                extra = min(2147483647,round(answered*(declared/listed -1))) if answered >= 5 and 0 < listed < declared else 0
                alive = present/(answered+extra) if answered >= 5 else -1
                fixtures.append((f'U {answered} {listed} {declared}',str(extra)))
                fixtures.append((f'E {present} {missing} {error} {listed} {declared}',str(alive)))
        for data in [1,10000,10001]:
            for article in [100,1000]:
                for block in [100,1000,10000]:
                    for alive in [0,0.8,0.999,1.0]:
                        volumes = [3000,1000]
                        blocks = -(-data // block)
                        damaged = blocks*(1-alive**(block/article))
                        recovery = sum(round(v/(block*1.02+68)) for v in volumes)
                        doomed = damaged > 1.25*recovery+2
                        fixtures.append((f'D {data} {article} {alive} {block} 3000 1000',str(int(doomed))))
        proc = subprocess.run([str(binary)],input='\n'.join(r for r,_ in fixtures)+'\n',text=True,capture_output=True,check=True)
        actual = proc.stdout.splitlines()
        assert len(actual) == len(fixtures)
        for got,(request,want) in zip(actual,fixtures):
            assert (float(got) == float(want) if request.startswith(('A ','E ')) else got == want), (request,got,want)
        print(f'PASS: {len(fixtures)} offline partial-NZB reference fixtures; invalid-number/subject-count cases use documented stricter safety guards')


if __name__ == "__main__":
    main()
