#!/usr/bin/env python3
"""Verify the published pilot artifacts offline; never execute bundled code."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import zipfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
LIMIT = 4 * 1024 * 1024
METHODS = ["original", "cpp-single-buffer", "rust-single-buffer", "identical-control"]
CASES = [[64, 17, 0, "start"], [64, 65531, 0, "cross"], [64, 65531, 1, "cross"],
         [64, 16777216, 0, "start"], [64, 16777216, 1, "start"],
         [1, 17, 0, "start"], [1, 65531, 0, "cross"]]
ORIGINAL_FILES = {"README.md", "caller.cpp", "caller.cpp.in", "nanobench.h", "build.py",
                  "run.py", "original-recorder.py", "check_recorder.py", "results.json",
                  "manifest.json", "proof.html"}
SNAPSHOT_FILES = {"daemon/postprocess/ContentMap.cpp", "rust/src/cryptoread.rs",
                  "rust/src/lib.rs", "rust/include/nzbget_cryptoread.h",
                  "rust/tests/cryptoread_bench.cpp", "rust/tests/cryptoread_caller.cpp",
                  "rust/tests/cryptoread_compare.py", "original/daemon/postprocess/ContentMap.cpp",
                  "COPYING"}
PINNED_ARTIFACT_HASHES = {
    "README.md": "ca4d86adda17fdf5546dd62d20ab67b7c7b04706f64e45ac8fe3dd6a54bea165",
    "index.html": "830f78f372dad11f5acd9ad1b8d431191e88e0383d91a53038801b864fa188bd",
    "proof-of-concept.zip": "c5a78af28eb2d7868774e1484ef092af93b9c3a2665f72ee00d0b6bd5824c600",
    "proof.html": "628df50a9d61c85f2dc7dae8bc6351db544690e8a748352705db5ac2fcc427bd",
    "results.json": "8c333dd1264b9a68c8baf6ec48a5bcae28a03b4ddddfa941df6d32963db550bc",
    "manifest.json": "988d62f0b79014675ca8415e63ad902c0c1a226fe57db79aac5d20761b29fc17",
    "negative-route-check.json": "95da5a556322362d455b42b4724076376f54d3641b541e118c9aaa08383fcdae",
    "original-evidence-manifest.json": "61b9a6885b95561d395a3a01cf67c2a082143e98f26c55d7158838f6b7801c52",
    "source-snapshot-manifest.json": "1dc259e2ddcbc9547b69eac300f00e848ab63d135e18ada40249b408c111275c",
    "source-snapshot.zip": "d83f53e9691f6286e6b68e32914c9d3739e19e5a673dfe3c50355eed9c1985e8",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def packet_directory():
    require(all(hasattr(os, flag) for flag in ["O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"]) and
            os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd,
            "Safe directory-relative no-follow admission unavailable on this platform")
    initial = ROOT.lstat()
    require(stat.S_ISDIR(initial.st_mode), "Packet root is not a regular directory")
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require(stat.S_ISDIR(opened.st_mode) and
                (opened.st_dev, opened.st_ino) == (initial.st_dev, initial.st_ino),
                "Packet directory replaced before open")
        yield fd
    finally:
        os.close(fd)


def read(name, directory_fd=None):
    if directory_fd is None:
        with packet_directory() as fd:
            return read(name, fd)
    require(Path(name).name == name, "Unexpected artifact name")
    initial = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    require(stat.S_ISREG(initial.st_mode), "Not a regular artifact: " + name)
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"),
            "Safe no-follow/nonblocking admission unavailable on this platform")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode), "Not a regular file")
        require((opened.st_dev, opened.st_ino) == (initial.st_dev, initial.st_ino),
                "Artifact replaced before open: " + name)
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, "Artifact exceeds size limit: " + name)
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(data):
    def unique(pairs):
        require(len(pairs) == len({key for key, _ in pairs}), "Duplicate JSON field")
        return dict(pairs)

    def nonfinite(value):
        raise ValueError("Non-finite JSON constant: " + value)

    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)


def check_result(entry):
    values = [entry[k] for k in ["median_ns", "speed_ratio", "speed_low", "speed_high"]]
    require(all(type(value) in (int, float) and math.isfinite(value) and value > 0
                for value in values),
            "Invalid RESULT statistic")
    require(entry["speed_low"] <= entry["speed_high"], "Invalid RESULT interval")
    # This frozen 52-pair sign-median protocol uses the same sorted log-ratios
    # for its median and order-statistic interval; this is not a generic CI rule.
    require(entry["speed_low"] <= entry["speed_ratio"] <= entry["speed_high"],
            "Point estimate outside this pilot's sign-median interval")
    require(type(entry["tied_rounds"]) is int and 0 <= entry["tied_rounds"] <= 52,
            "Invalid tied-round count")


def check_boundary(size, preflight, boundary, recorded_work):
    expected_hits = [0, 0, 0, 0] if size == 17 else [0, 1, 1, 0]
    require([p["scratch_allocations"] for p in preflight] == expected_hits,
            "Scenario scratch boundary was bypassed")
    require(len(boundary) == 4 and boundary[0] == boundary[1] and boundary[2:] == [0, 0],
            "Boundary mismatch")
    require(boundary[0] == 0 if size == 17 else boundary[0] >= recorded_work > 0,
            "Timed scratch work count is incomplete")


def check_case(case):
    require(type(case) is list and len(case) == 4 and
            all(type(value) is int for value in case[:3]) and type(case[3]) is str and
            case in CASES, "Invalid pilot case types or values")


def check_record_schema(record):
    require(type(record["trial"]) is int and 1 <= record["trial"] <= 3,
            "Process trial must be an integer in range")
    check_case(record["case"])
    require(type(record["rounds"]) is int and record["rounds"] == 52 and
            type(record["control_bounded"]) is bool, "Invalid process field types")
    require(type(record["stdout"]) is str and record["stderr"] == "",
            "Successful historical process must have empty stderr")
    require(type(record["boundary"]) is list and len(record["boundary"]) == 4 and
            all(type(value) is int and value >= 0 for value in record["boundary"]),
            "Invalid boundary count types")
    require(len(record["preflight"]) == 4, "Unexpected preflight count")
    for item in record["preflight"]:
        require(item["name"] in METHODS and all(type(item[k]) is int and item[k] >= 0
                for k in ["scratch_allocations", "scratch_releases", "actual_caller_entries"]),
                "Invalid preflight count types")
    for entry in record["entries"]:
        check_result(entry)
        for sample in entry["samples"]:
            require(type(sample["round"]) is int and type(sample["iterations"]) is int and
                    type(sample["ns"]) in (int, float), "Invalid sample field types")


def check_result_method(name, results):
    require(name in METHODS and name not in results, "Unknown or duplicate RESULT method")


def check_export_status(export):
    require(export["qualification"] == "HOLD" and export["production_status"] == "HOLD unchanged",
            "Historical packet cannot claim qualification or release")


def check_publication_metadata(export):
    metadata = {key: value for key, value in export.items() if key != "sha256"}
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    require(digest(canonical) == "780fb79f4d3c5d82e52d47e547bf06b7959bb3bb50669c7e86707ebeddfdc485",
            "Fixed publication metadata changed")


def check_original_inventory(original):
    require(set(original["sha256"]) == ORIGINAL_FILES, "Historical source inventory changed")


def verify():
    with packet_directory() as fd:
        verify_packet(fd)


def verify_packet(directory_fd):
    def read_packet(name):
        return read(name, directory_fd)

    export = load_json(read_packet("export-manifest.json"))
    check_export_status(export)
    check_publication_metadata(export)
    expected = {
        "README.md", "verify.py", "test_verify.py", "index.html", "proof.html", "results.json", "manifest.json",
        "proof-of-concept.zip", "original-evidence-manifest.json",
        "negative-route-check.json", "source-snapshot.zip", "source-snapshot-manifest.json",
    }
    require(set(export["sha256"]) == expected, "Unexpected export inventory")
    artifacts = {name: read_packet(name) for name in expected}
    for name, data in artifacts.items():
        require(digest(data) == export["sha256"][name], "Hash mismatch: " + name)
    for name, expected_hash in PINNED_ARTIFACT_HASHES.items():
        require(digest(artifacts[name]) == expected_hash, "Fixed artifact changed: " + name)
    original = load_json(artifacts["original-evidence-manifest.json"])
    check_original_inventory(original)
    bundle = artifacts["proof-of-concept.zip"]
    require(digest(bundle) == original["archive_sha256"], "Original ZIP hash mismatch")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(names)), "Duplicate ZIP member")
        require(set(names) == {"nanobench-poc/" + n for n in original["sha256"]},
                "Unexpected original ZIP inventory")
        require(sum(entry.file_size for entry in entries) <= LIMIT, "ZIP exceeds limit")
        for entry in entries:
            data = archive.read(entry)
            name = entry.filename.removeprefix("nanobench-poc/")
            require(digest(data) == original["sha256"][name], "ZIP hash mismatch: " + name)
            if name in {"proof.html", "results.json", "manifest.json"}:
                require(data == artifacts[name], "Export differs from original: " + name)
    data = load_json(artifacts["results.json"])
    snapshot = load_json(artifacts["source-snapshot-manifest.json"])
    require(set(snapshot["sha256"]) == SNAPSHOT_FILES, "Snapshot source inventory changed")
    require(digest(artifacts["source-snapshot.zip"]) == snapshot["archive_sha256"],
            "Source snapshot archive mismatch")
    with zipfile.ZipFile(io.BytesIO(artifacts["source-snapshot.zip"])) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        require(len(names) == len(set(names)) and set(names) == set(snapshot["sha256"]),
                "Source snapshot inventory mismatch")
        require(sum(e.file_size for e in entries) <= LIMIT, "Source snapshot exceeds limit")
        for entry in entries:
            require(digest(archive.read(entry)) == snapshot["sha256"][entry.filename],
                    "Source snapshot member mismatch")
    for name in ["daemon/postprocess/ContentMap.cpp", "rust/src/cryptoread.rs"]:
        require(snapshot["sha256"][name] == data["manifest"]["sha256"][name],
                "Measured candidate source hash mismatch")
    require(snapshot["sha256"]["original/daemon/postprocess/ContentMap.cpp"] ==
            data["manifest"]["sha256"]["build-range/nanobench-poc/original.cpp"],
            "Original baseline source hash mismatch")
    negative = load_json(artifacts["negative-route-check.json"])
    require(data["negative_route_check"] == "passed" and type(negative["exit"]) is int and
            negative["exit"] == 1,
            "Broken-route control exit mismatch")
    require(negative["stderr"].strip() ==
            "FAIL preflight active caller or allocation boundary failed",
            "Broken-route control did not fail at preflight")
    require(negative["stdout"].strip() == "PREFLIGHT original 0 0 1",
            "Unexpected broken-route output or timing rows")
    require(data["manifest"] == load_json(artifacts["manifest.json"]),
            "Results/source manifest mismatch")
    match = re.search(r"const DATA=(.*?);\s*const names=", artifacts["proof.html"].decode(), re.S)
    require(match is not None, "Missing embedded viewer data")
    embedded = load_json(match.group(1))
    published_match = re.search(r"const DATA=(.*?);\s*const names=",
                               artifacts["index.html"].decode(), re.S)
    require(published_match is not None and load_json(published_match.group(1)) == embedded,
            "Derived publication view changed the historical measurements")
    provenance = embedded.pop("provenance")
    require(embedded == data, "Viewer/results mismatch")
    require(provenance["attempt"] == "001", "Wrong timing attempt")
    require(provenance["binary_sha256"] == data["manifest"]["sha256"][
        "build-range/nanobench-poc/paired-caller"], "Viewer binary hash mismatch")
    plan = data["plan"]
    require(type(plan["rounds"]) is int and type(plan["trials"]) is int and
            plan["rounds"] == 52 and plan["trials"] == 3 and plan["cases"] == CASES,
            "Unexpected pilot plan")
    for case in plan["cases"]:
        check_case(case)
    expected_keys = {(trial, tuple(case)) for trial in range(1, 4) for case in plan["cases"]}
    seen = set()
    samples = controls = 0
    for record in data["records"]:
        check_record_schema(record)
        key = (record["trial"], tuple(record["case"]))
        require(key in expected_keys and key not in seen, "Missing/duplicate process key")
        seen.add(key)
        entries = record["entries"]
        require([e["name"] for e in entries] == METHODS, "Wrong methods/order")
        require(record["rounds"] == 52 and isinstance(record["stderr"], str), "Bad capture")
        raw = {name: [] for name in METHODS}
        results = {}
        preflight = []
        boundary = None
        rounds = None
        for line in record["stdout"].splitlines():
            fields = line.split()
            require(bool(fields), "Empty raw row")
            kind = fields[0]
            if kind == "RAW":
                require(len(fields) == 5 and fields[1] in raw, "Malformed raw sample")
                raw[fields[1]].append({"round": int(fields[2]), "ns": float(fields[3]),
                                       "iterations": int(fields[4])})
            elif kind == "RESULT":
                require(len(fields) == 7, "Malformed RESULT row")
                check_result_method(fields[1], results)
                results[fields[1]] = [float(v) for v in fields[2:6]] + [int(fields[6])]
            elif kind == "PREFLIGHT":
                require(len(fields) == 5, "Malformed preflight")
                preflight.append(dict(zip(
                    ["name", "scratch_allocations", "scratch_releases", "actual_caller_entries"],
                    [fields[1], *map(int, fields[2:])],
                )))
            elif kind == "BOUNDARY":
                require(boundary is None and len(fields) == 5, "Malformed boundary")
                boundary = list(map(int, fields[1:]))
            elif kind == "ROUNDS":
                require(rounds is None and len(fields) == 2, "Malformed rounds")
                rounds = int(fields[1])
            else:
                raise ValueError("Unexpected raw row kind")
        require(rounds == 52 and preflight == record["preflight"], "Preflight mismatch")
        require(set(results) == set(METHODS), "Missing or extra RESULT methods")
        require([p["name"] for p in preflight] == METHODS, "Wrong preflight methods")
        require(all(p["actual_caller_entries"] == 1 and p["scratch_allocations"] ==
                    p["scratch_releases"] for p in preflight), "Caller/ownership mismatch")
        require(boundary == record["boundary"], "Raw/derived boundary mismatch")
        iterations = set()
        for entry in entries:
            require(raw[entry["name"]] == entry["samples"], "Raw/derived sample mismatch")
            require([s["round"] for s in entry["samples"]] == list(range(52)), "Bad rounds")
            require(results[entry["name"]] == [entry[k] for k in
                    ["median_ns", "speed_ratio", "speed_low", "speed_high", "tied_rounds"]],
                    "Raw/derived result mismatch")
            check_result(entry)
            for sample in entry["samples"]:
                require(math.isfinite(sample["ns"]) and sample["ns"] > 0 and
                        sample["iterations"] > 0, "Invalid sample")
                iterations.add(sample["iterations"])
                samples += 1
        require(len(iterations) == 1, "Unpaired iteration counts")
        recorded_work = sum(s["iterations"] for e in entries[1:3] for s in e["samples"])
        check_boundary(record["case"][1], preflight, boundary, recorded_work)
        control = entries[3]
        band = plan["control_precision_band"]
        bounded = (1 - band <= control["speed_low"] <= 1 <= control["speed_high"] <= 1 + band)
        require(bounded == record["control_bounded"], "Control classification mismatch")
        controls += bounded
    require(seen == expected_keys and samples == 4368 and controls == 14, "Incomplete pilot")
    print("ARTIFACT INTEGRITY OK: hashes, viewer, ZIP, 21 processes, 4,368 samples, 14 controls.")
    print("QUALIFICATION HOLD: exact integer elapsed times and a qualifying floor are absent.")
    print("Historical proof of concept only; no native performance acceptance is granted.")


if __name__ == "__main__":
    try:
        verify()
    except OSError as error:
        print("FAIL: artifact I/O error (errno " + str(error.errno) + ")", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        sys.exit(1)
