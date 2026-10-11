#!/usr/bin/env python3
"""Export recorded RPC caller samples without inventing missing measurements.

Usage: rpc.py --manifest proof.json --source caller.jsonl --output-dir output

Supported prospective source: JSONL with the shared v1 sample fields. The
manifest additionally identifies each fixture's complete C++ caller in
``caller``. Variant names are literal; before/after labels are never inferred.
Run the shared summarize.py after export for statistical qualification.
Caller labels are supplied provenance, not independent proof of execution.
Binary identity and the caller/fixture attribution still need trusted review.

Historical PR84 SAMPLE|name|round|cpp_ns_per_op|rust_ns_per_op records have
rounded per-operation latency, not recorded elapsed_ns/iterations. Those,
ROW summaries, TSV tables and statistics arrays are retained as HOLD evidence.
No process IDs, elapsed durations, output hashes or cross-process pairs are
retroactively manufactured. Historical proof does not qualify a repaired head.
"""
import argparse
from collections import deque
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


VARIANTS = {"cpp_current", "cpp_optimized", "rust_current", "rust_candidate"}
# These execute/build/list the actual RPC caller result. FFI entry encoders,
# frame classifiers and the historical "Download URL test" are not callers.
CALLERS = {
    "ListBinCommand::Execute", "LogBinCommand::Execute",
    "PostQueueBinCommand::Execute", "HistoryBinCommand::Execute",
    "EditQueueBinCommand::Execute", "DownloadBinCommand::Execute",
    "BinRpcProcessor::Execute", "RemoteClient::BuildFileList",
    "RemoteClient::Log", "RemoteClient::PostQueue", "RemoteClient::History",
}
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
SHA40 = re.compile(r"[0-9a-fA-F]{40}\Z")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_FIXTURES = 64
MAX_ROWS = 100000
MAX_PROCESSES = 128


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(text):
    def invalid_constant(value):
        raise ValueError(f"non-finite JSON number: {value}")
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def check_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("manifest requires schema_version 1")
    for field in ["base_sha", "candidate_sha"]:
        if not isinstance(manifest.get(field), str) or not SHA40.fullmatch(manifest[field]):
            raise ValueError(f"manifest requires full {field}")
    if not isinstance(manifest.get("testbed"), str) or not manifest["testbed"].strip():
        raise ValueError("manifest requires testbed")
    toolchain = manifest.get("toolchain")
    if not isinstance(toolchain, dict) or not toolchain or any(not isinstance(v, str) for v in toolchain.values()):
        raise ValueError("toolchain must be a nonempty string-valued object")
    comparison = manifest.get("comparison")
    if not isinstance(comparison, dict) or any(comparison.get(k) not in VARIANTS for k in ["baseline", "candidate"]):
        raise ValueError("comparison requires literal baseline and candidate variants")
    if comparison["baseline"] == comparison["candidate"]:
        raise ValueError("comparison variants must differ")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not 0 < len(fixtures) <= MAX_FIXTURES:
        raise ValueError("manifest requires 1..64 fixtures")
    by_id = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str) or not 0 < len(fixture["id"]) <= 200 or not fixture["id"].isprintable():
            raise ValueError("fixture requires printable id of 1..200 characters")
        if fixture["id"] in by_id:
            raise ValueError("duplicate fixture id")
        if not isinstance(fixture.get("sha256"), str) or not SHA256.fullmatch(fixture["sha256"]):
            raise ValueError("fixture requires input sha256")
        if fixture.get("scope") not in {"complete_caller", "kernel"}:
            raise ValueError("fixture requires scope")
        required = fixture.get("required_variants", [comparison["baseline"], comparison["candidate"]])
        if not isinstance(required, list) or not required or any(v not in VARIANTS for v in required) or len(set(required)) != len(required):
            raise ValueError("invalid required_variants")
        if not {comparison["baseline"], comparison["candidate"]}.issubset(required):
            raise ValueError("required_variants must include the comparison")
        by_id[fixture["id"]] = (fixture, set(required))
    return by_id


def check_rows(rows, fixtures):
    """Reject corrupt raw records before preserving or exporting artifacts.

    The shared summarizer remains authoritative for the full schema and gates.
    This checks adapter-boundary corruption even before that module is present.
    """
    keys, orders, blocks, variants, digests = set(), set(), {}, {}, {}
    processes = {}
    if len(rows) > MAX_ROWS:
        raise ValueError("too many source rows")
    for row in rows:
        if not isinstance(row, dict) or row.get("case") not in fixtures or row.get("variant") not in VARIANTS:
            raise ValueError("sample requires a declared fixture and literal variant")
        for field in ["process", "round", "order", "iterations"]:
            value = row.get(field)
            if type(value) is not int or value < (1 if field == "iterations" else 0):
                raise ValueError(f"invalid sample {field}")
        elapsed = row.get("elapsed_ns")
        if type(elapsed) not in (int, float) or elapsed <= 0 or not math.isfinite(elapsed):
            raise ValueError("elapsed_ns must be positive and finite")
        digest = row.get("observable_digest")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("sample requires observable_digest sha256")
        case, variant = row["case"], row["variant"]
        fixture = fixtures[case][0]
        if "caller" in row and row["caller"] != fixture.get("caller"):
            raise ValueError("recorded caller contradicts fixture provenance")
        if "scope" in row and row["scope"] != fixture["scope"]:
            raise ValueError("recorded scope contradicts fixture provenance")
        processes.setdefault(case, set()).add(row["process"])
        if len(processes[case]) > MAX_PROCESSES:
            raise ValueError("too many processes for fixture")
        block = (case, row["process"], row["round"])
        key = (*block, variant)
        order = (*block, row["order"])
        if key in keys or order in orders:
            raise ValueError("duplicate sample or order within a block")
        keys.add(key)
        orders.add(order)
        blocks.setdefault(block, set()).add(variant)
        variants.setdefault(case, set()).add(variant)
        if case in digests and digests[case] != digest.lower():
            raise ValueError("mismatched observable digests")
        digests[case] = digest.lower()
    reasons = []
    for case, (_, required) in fixtures.items():
        present = variants.get(case, set())
        missing = required - present
        if missing:
            reasons.append(f"{case}: entirely missing variants {', '.join(sorted(missing))}")
        for block, observed in blocks.items():
            if block[0] == case and not (required & present).issubset(observed):
                raise ValueError("unmatched partial sample block")
    return reasons


def legacy_records(text):
    records = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.startswith(("SAMPLE|", "ROW|")):
            continue
        fields = line.split("|")
        sample = fields[0] == "SAMPLE"
        if len(fields) != (5 if sample else 4) or not fields[1]:
            raise ValueError(f"malformed legacy record at line {line_no}")
        values = fields[3:] if sample else fields[2:]
        for value in values:
            try:
                latency = Decimal(value)
            except InvalidOperation as error:
                raise ValueError("invalid legacy latency") from error
            if not latency.is_finite() or latency <= 0:
                raise ValueError("legacy latency must be positive and finite")
        record = {"line": line_no, "kind": fields[0], "case": fields[1],
                  "cpp_ns_per_op": values[0], "rust_ns_per_op": values[1]}
        if sample:
            if not re.fullmatch(r"\d+", fields[2]):
                raise ValueError("invalid legacy round")
            record["round"] = int(fields[2])
        records.append(record)
        if len(records) > MAX_ROWS:
            raise ValueError("too many legacy records")
    return records


def adapt(manifest, source):
    """Return exportable raw rows or held legacy evidence; never compute times."""
    if not isinstance(manifest, dict):
        raise ValueError("source manifest must be a JSON object")
    if len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds 32 MiB")
    text = source.decode("utf-8")
    result = {"manifest": copy.deepcopy(manifest), "samples": [],
              "legacy_records": [], "status": "HOLD", "reasons": [],
              "source_sha256": hashlib.sha256(source).hexdigest()}
    if not text.strip():
        result["reasons"] = ["empty source; no recorded measurements"]
        return result
    if text.lstrip().startswith("{"):
        fixtures = check_manifest(manifest)
        rows = [load_json(line) for line in text.splitlines() if line.strip()]
        reasons = check_rows(rows, fixtures)
        unqualified = [case for case, (fixture, _) in fixtures.items()
                       if fixture["scope"] != "complete_caller" or fixture.get("caller") not in CALLERS]
        if unqualified:
            result["reasons"] = ["complete RPC caller provenance missing or kernel-only: " + ", ".join(unqualified)]
        else:
            result["samples"] = rows
            result["reasons"] = reasons
            result["status"] = "HOLD" if reasons else "READY"
        result["source_format"] = "v1_jsonl"
    else:
        result["legacy_records"] = legacy_records(text)
        if result["legacy_records"]:
            result["source_format"] = "legacy_rpc"
            result["reasons"] = ["historical rounded ns_per_op lacks recorded elapsed_ns, iterations, process identity and observable_digest; no paired v1 export"]
        elif text.lstrip().startswith("["):
            if not isinstance(load_json(text), list):
                raise ValueError("invalid statistics array")
            result["source_format"] = "aggregate_json"
            result["reasons"] = ["aggregate statistics are not raw complete-caller samples"]
        else:
            result["source_format"] = "aggregate_or_unsupported_text"
            result["reasons"] = ["unsupported source or aggregate table; raw complete-caller samples absent"]
    return result


def shared_validator():
    path = Path(__file__).resolve().parents[1] / "summarize.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("nzbget_bench_summary", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.summarize


def bounded_read(path, maximum):
    # O_NONBLOCK prevents a FIFO open from waiting for a writer. Check the
    # opened descriptor, so symlinks to regular files work without a separate
    # pathname type check that could race the open.
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("input must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
    finally:
        os.close(descriptor)
    if len(data) > maximum:
        raise ValueError("input exceeds byte limit")
    return data


def input_traversal_entries(path):
    """Keep entries reached through symlink targets, including before '..'."""
    absolute = path.absolute()
    pending = deque(absolute.parts[1:])
    current = Path(absolute.anchor)
    links = steps = 0
    while pending:
        steps += 1
        if steps > 4096:
            raise ValueError("input path traversal exceeds component limit")
        component = pending.popleft()
        if component == "..":
            current = current.parent
            continue
        if component in ("", "."):
            continue
        entry = current / component
        yield entry
        if entry.is_symlink():
            links += 1
            if links > 40:
                raise ValueError("input path traversal exceeds symlink limit")
            target = Path(os.readlink(entry))
            parts = target.parts
            if target.is_absolute():
                current = Path(target.anchor)
                parts = parts[1:]
            pending.extendleft(reversed(parts))
        else:
            current = entry


def check_paths(manifest, source, output):
    """Resolve aliases before any cleanup; an input under output is unsafe."""
    destination = output.resolve()
    if output.is_symlink():
        raise ValueError("output-dir must not be a symlink")
    inputs = [manifest.resolve(), source.resolve()]
    if inputs[0] == inputs[1] or (manifest.exists() and source.exists() and manifest.samefile(source)):
        raise ValueError("manifest and source must be separate files")
    for original, path in zip((manifest, source), inputs):
        lexical = Path(os.path.abspath(original))
        lexical_output = Path(os.path.abspath(output))
        if (path == destination or destination in path.parents or
                lexical == destination or destination in lexical.parents or
                lexical == lexical_output or lexical_output in lexical.parents):
            raise ValueError("input/output collision")
        # Keep every directory entry used to reach the input, not just its
        # final resolved target. Resolving parents can erase a directory link
        # under output; '..' may also hide that link from lexical containment.
        absolute = original.absolute()
        for ancestor in (absolute, *absolute.parents):
            entry = ancestor.parent.resolve() / ancestor.name
            if entry == destination or destination in entry.parents:
                raise ValueError("input/output ancestor collision")
        # An outer input link can name an owned output link inside its target.
        # Inspect the traversal itself: the final target and lexical ancestors
        # alone lose intermediates, especially targets containing '..'.
        for entry in input_traversal_entries(original):
            if entry == destination or destination in entry.parents:
                raise ValueError("input/output symlink-target collision")
    for filename in ["source.raw", "source-manifest.raw", "manifest.json", "samples.jsonl", "adapter-status.json", "legacy-evidence.json"]:
        target = output / filename
        if target.exists() or target.is_symlink():
            if (target.resolve() in inputs or
                    (target.exists() and any(path.exists() and target.samefile(path) for path in inputs))):
                raise ValueError("input/output alias collision")


def clear_owned_exports(output):
    marker = output / "adapter-status.json"
    try:
        if marker.is_symlink() or load_json(bounded_read(marker, MAX_MANIFEST_BYTES)).get("adapter") != "rpc":
            return
        # Remove the READY marker first, even if another generated artifact
        # was damaged into a directory that cannot safely be unlinked.
        for name in ["adapter-status.json", "manifest.json", "samples.jsonl"]:
            try:
                (output / name).unlink(missing_ok=True)
            except OSError:
                pass
    except (OSError, ValueError, AttributeError):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    temp = None
    clear_invalid = False
    try:
        check_paths(args.manifest, args.source, args.output_dir)
        clear_invalid = True
        source = bounded_read(args.source, MAX_SOURCE_BYTES)
        metadata = bounded_read(args.manifest, MAX_MANIFEST_BYTES)
        result = adapt(load_json(metadata), source)
        if result["samples"]:
            validator = shared_validator()
            if validator is None:
                result["status"] = "HOLD"
                result["reasons"].append("shared summarize.py unavailable; v1 export held pending authoritative validation")
                result["samples"] = []
            else:
                # Validate with task2's frozen API. Never turn its qualification
                # PASS into an adapter speedup claim; READY means exportable.
                _, _, qualification = validator(result["manifest"], result["samples"])
                if qualification["status"] == "HOLD":
                    result["status"] = "HOLD"
                    result["reasons"].extend(qualification["reasons"])
        clear_invalid = False
        output = args.output_dir
        if output.exists():
            raise ValueError("output-dir already exists; immutable evidence is not overwritten")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".rpc-adapter-", dir=output.parent))
        (temp / "source.raw").write_bytes(source)
        (temp / "source-manifest.raw").write_bytes(metadata)
        if result["samples"]:
            (temp / "manifest.json").write_text(json.dumps(result["manifest"], indent=2, allow_nan=False) + "\n")
            (temp / "samples.jsonl").write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in result["samples"]))
        if result["legacy_records"]:
            (temp / "legacy-evidence.json").write_text(json.dumps(result["legacy_records"], indent=2) + "\n")
        status = {key: value for key, value in result.items() if key not in {"manifest", "samples", "legacy_records"}}
        status.update(adapter="rpc", schema_version=1,
                      source_manifest_sha256=hashlib.sha256(metadata).hexdigest(),
                      exported_rows=len(result["samples"]), legacy_rows=len(result["legacy_records"]))
        for field in ["base_sha", "candidate_sha"]:
            if field in result["manifest"]:
                status[field] = result["manifest"][field]
        (temp / "adapter-status.json").write_text(json.dumps(status, indent=2, allow_nan=False) + "\n")
        temp.rename(output)
        temp = None
        print(json.dumps(status, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        if clear_invalid:
            clear_owned_exports(args.output_dir)
        print(f"rpc adapter: {error}", file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            shutil.rmtree(temp)


if __name__ == "__main__":
    raise SystemExit(main())
