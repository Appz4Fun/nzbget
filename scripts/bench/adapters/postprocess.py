#!/usr/bin/env python3
"""Preserve postprocess caller evidence without manufacturing shared v1 samples.

Usage: python3 scripts/bench/adapters/postprocess.py --format par-crc
       --manifest MANIFEST --source RAW [--source RAW ...] --output-dir OUTPUT_DIR

Legacy inputs contain rounded nanoseconds per operation. They cannot recover
elapsed totals, iteration counts, process clusters, or SHA-256 output digests.
Every original row (including slower controls and initialization) is retained
in adapter-evidence.json, with empty samples.jsonl and HOLD qualification.
For legacy formats --manifest accepts bounded partial historical metadata,
archived as legacy-metadata.json rather than a v1 manifest. Missing identities
and fixture hashes remain absent. Optional --metadata JSON preserves reviewed
caller metadata and its hash.

Formats match retained DeadPostings Load logs/summaries, ArticleWriter CRC CSV,
PAR CRC packet-fold CSV, PAR damage CSV, and PAR range-plan CSV. Empty CRC/PAR
calls are empty_call overhead; nonempty calls are throughput. DeadPostings
Load is initialization even when the state file is nonempty. These phases never
establish complete-caller scope. Only --format v1 consumes already recorded v1
raw samples, using the shared summarize.py validator unchanged. Harness scope
and build/event freshness remain responsibilities of the evidence producer.
No harness is run, no metadata is inferred, and no legacy evidence is promoted.
An output directory containing an input/evidence archive cannot be reused:
reimports require a fresh directory. Rejected imports invalidate derived
qualification and metrics while preserving earlier archives byte for byte.
"""

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys


VARIANTS = {"cpp_current", "cpp_optimized", "rust_current", "rust_candidate"}
CSV_HEADERS = {
    "article-crc": (
        ("size", "pattern", "sample", "baseline_ns", "candidate_ns"),
        ("size", "pattern", "sample", "baseline_ns", "candidate_ns", "cpp_control_ns"),
    ),
    "par-crc": (("count", "size", "sample", "order", "old_ns", "rust_ns", "optimized_ns"),),
    "par-damage": (("case", "n", "sample", "baseline_ns", "rust_caller_ns", "cpp_sorted_ns"),),
    "par-range": (("segments", "runs", "shape", "sample", "original_ns", "rust_ns", "cpp_lb_ns", "cpp_branchless_ns"),),
}
LIMITATIONS = [
    "Legacy ns/op values are rounded; elapsed_ns and iterations were not recorded and cannot be reconstructed.",
    "Legacy evidence lacks complete v1 process/round/order blocks and SHA-256 verified output digests.",
    "Legacy rows are HOLD-only; source hashes preserve bytes but do not verify harness scope or build freshness.",
]
ARCHIVED = {"manifest.json", "samples.jsonl", "adapter-evidence.json", "legacy-metadata.json"}
DERIVED = {"summary.json", "bencher.json", "qualification.json", "report.md"}
GENERATED = ARCHIVED | DERIVED
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000


class EvidenceError(ValueError):
    pass


class AliasError(EvidenceError):
    """Collision errors never mutate sources, including stale-looking files."""


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(text):
    def nonfinite(value):
        raise EvidenceError(f"nonfinite JSON value: {value}")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            return nonfinite(value)
        return number
    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=nonfinite,
                      parse_float=finite_float)


def integer(value, label):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise EvidenceError(f"{label} must be a nonnegative integer")
    return int(value)


def positive(value, label):
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise EvidenceError(f"{label} must be finite and positive") from error
    if not number.is_finite() or number <= 0:
        raise EvidenceError(f"{label} must be finite and positive")


def digest(value, width, label):
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-fA-F]{{{width}}}", value):
        raise EvidenceError(f"invalid {label}")


def validate_manifest(manifest):
    """Check v1 structure for HOLD reports; raw v1 uses the shared validator."""
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise EvidenceError("manifest schema_version must be 1")
    for key in ("base_sha", "candidate_sha"):
        digest(manifest.get(key), 40, key)
    if (not isinstance(manifest.get("testbed"), str) or not manifest["testbed"].strip()
            or len(manifest["testbed"]) > 200 or not manifest["testbed"].isprintable()):
        raise EvidenceError("manifest testbed is required")
    toolchain = manifest.get("toolchain")
    if (not isinstance(toolchain, dict) or not 0 < len(toolchain) <= 64 or
            not all(isinstance(k, str) and 0 < len(k) <= 200 and k.strip() and k.isprintable()
                    and isinstance(v, str) and 0 < len(v) <= 4096 and v.strip() and v.isprintable()
                    for k, v in toolchain.items())):
        raise EvidenceError("manifest toolchain must be a string-valued object")
    comparison = manifest.get("comparison")
    if not isinstance(comparison, dict) or any(not isinstance(comparison.get(k), str) or comparison[k] not in VARIANTS for k in ("baseline", "candidate")):
        raise EvidenceError("invalid comparison variants")
    if comparison["baseline"] == comparison["candidate"]:
        raise EvidenceError("comparison variants must differ")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not 0 < len(fixtures) <= 64:
        raise EvidenceError("manifest fixtures must be an array with at most 64 entries")
    ids = set()
    for fixture in fixtures:
        if (not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str) or
                not fixture["id"] or len(fixture["id"]) > 200 or not fixture["id"].isprintable()):
            raise EvidenceError("fixture id is required")
        if fixture["id"] in ids:
            raise EvidenceError("duplicate fixture id")
        ids.add(fixture["id"])
        digest(fixture.get("sha256"), 64, "fixture sha256")
        if not isinstance(fixture.get("scope"), str) or fixture["scope"] not in {"complete_caller", "kernel"}:
            raise EvidenceError("invalid fixture scope")
        required = fixture.get("required_variants", [comparison["baseline"], comparison["candidate"]])
        if (not isinstance(required, list) or any(not isinstance(v, str) or v not in VARIANTS for v in required)
                or len(set(required)) != len(required)):
            raise EvidenceError("invalid fixture required_variants")
        if any(comparison[k] not in required for k in ("baseline", "candidate")):
            raise EvidenceError("fixture must require both comparison variants")


def read_source(path, limit=MAX_SOURCE_BYTES):
    # Opening a FIFO normally blocks before a byte limit can be checked.
    # Validate the opened descriptor (following regular-file symlinks) before
    # reading; never reopen the path after this check.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise EvidenceError(f"{path.name}: input must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
    finally:
        os.close(descriptor)
    if len(data) > limit:
        raise EvidenceError(f"{path.name}: input exceeds {limit} bytes")
    return {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(),
            "text": data.decode("utf-8")}


def csv_rows(kind, source):
    reader = csv.DictReader(io.StringIO(source["text"], newline=""), strict=True)
    if tuple(reader.fieldnames or ()) not in CSV_HEADERS[kind]:
        raise EvidenceError(f"{source['name']}: unsupported {kind} CSV header")
    rows, seen = [], set()
    work_key = {"article-crc": "size", "par-crc": "count", "par-damage": "n", "par-range": "segments"}[kind]
    for raw in reader:
        if len(rows) >= MAX_ROWS:
            raise EvidenceError("source exceeds 100000 rows")
        if None in raw or any(v is None or v == "" for v in raw.values()):
            raise EvidenceError(f"{source['name']}: incomplete CSV row")
        for key, value in raw.items():
            if key.endswith("_ns"):
                positive(value, key)
            elif key != "case":
                integer(value, key)
        if "order" in raw and raw["order"] not in {"0", "1"}:
            raise EvidenceError("PAR CRC order must be 0 or 1")
        keys = [k for k in raw if not k.endswith("_ns") and k not in {"sample", "order"}]
        case = kind + "/" + "/".join(f"{k}={raw[k]}" for k in keys)
        unique = (case, int(raw["sample"]))
        if unique in seen:
            raise EvidenceError(f"{source['name']}: duplicate sample")
        seen.add(unique)
        rows.append({"case": case, "phase": "empty_call" if int(raw[work_key]) == 0 else "throughput",
                     "status": "HOLD", "measurement_unit": "ns_per_operation", "raw": raw})
    if not rows:
        raise EvidenceError(f"{source['name']}: no samples")
    source["rows"] = rows


def dead_rows(source):
    match = re.fullmatch(r"load-([0-9]+)-([0-9]+)\.log", source["name"])
    # Filename coordinates label originals only, never assert a v1 process id.
    source["filename_coordinates"] = ({"records": int(match[1]), "process_label": int(match[2])}
                                      if match else None)
    rows, trailer = [], None
    for line in source["text"].splitlines():
        if len(rows) > MAX_ROWS:
            raise EvidenceError("source exceeds 100000 rows")
        footer = re.fullmatch(r"observable_digest=([0-9]+) sink=([0-9]+)", line)
        if footer:
            if trailer is not None or not rows:
                raise EvidenceError("duplicate or misplaced DeadPostings trailer")
            if any(int(v) > 2**64 - 1 for v in footer.groups()):
                raise EvidenceError("DeadPostings digest is outside u64")
            trailer = footer.groups()
            continue
        cells = line.split()
        if trailer is not None or len(cells) != 2:
            raise EvidenceError("malformed DeadPostings sample")
        for cell in cells:
            positive(cell, "DeadPostings latency")
        rows.append({"case": "deadpostings/load/records=" + (match[1] if match else "unknown"),
                     "phase": "initialization", "status": "HOLD", "measurement_unit": "ns_per_operation",
                     "raw": {"cpp_ns": cells[0], "rust_ns": cells[1]}})
    if not rows:
        raise EvidenceError("no DeadPostings samples")
    if len(rows) > MAX_ROWS:
        raise EvidenceError("source exceeds 100000 rows")
    source["rows"] = rows
    source["observable_digest_u64"] = trailer[0] if trailer else None
    source["sink_u64"] = trailer[1] if trailer else None


def aggregate_rows(source):
    data = load_json(source["text"])
    if not isinstance(data, list) or not data or len(data) > MAX_ROWS:
        raise EvidenceError("DeadPostings summary must be a nonempty array")
    rows, seen = [], set()
    for row in data:
        if not isinstance(row, dict) or not {"records", "samples", "cpp_ns", "rust_ns"} <= row.keys():
            raise EvidenceError("incomplete DeadPostings aggregate")
        records = integer(row["records"], "records")
        if integer(row["samples"], "samples") == 0 or records in seen:
            raise EvidenceError("empty or duplicate DeadPostings aggregate")
        seen.add(records)
        positive(row["cpp_ns"], "cpp_ns")
        positive(row["rust_ns"], "rust_ns")
        # Even a source-reported gain or PASS is merely retained source data.
        rows.append({"case": f"deadpostings/load/records={records}", "phase": "initialization",
                     "status": "HOLD", "measurement_unit": "aggregate_ns_per_operation", "raw": row})
    source["rows"] = rows


def shared_summary(manifest, sources):
    path = Path(__file__).resolve().parents[1] / "summarize.py"
    if not path.is_file():
        raise EvidenceError("v1 requires the shared scripts/bench/summarize.py validator")
    rows = []
    for source in sources:
        for line in source["text"].splitlines():
            if len(rows) >= MAX_ROWS:
                raise EvidenceError("samples exceed 100000 rows")
            if not line.strip():
                raise EvidenceError("blank v1 JSONL row")
            rows.append(load_json(line))
    spec = importlib.util.spec_from_file_location("nzbget_bench_summarize", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    summary, bencher, qualification = module.summarize(manifest, rows)
    return rows, summary, bencher, qualification, module.render_report(summary, qualification)


def legacy_identity(metadata):
    """Retain usable historical assertions, never fill unknown identities."""
    identity = {}
    for key in ("base_sha", "candidate_sha"):
        value = metadata.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value):
            identity[key] = value
    testbed = metadata.get("testbed")
    if isinstance(testbed, str) and testbed.strip() and len(testbed) <= 200 and testbed.isprintable():
        identity["testbed"] = testbed
    return identity


def adapt(kind, paths, manifest, metadata_paths=(), manifest_source=None):
    if kind == "v1":
        validate_manifest(manifest)
    elif not isinstance(manifest, dict):
        raise EvidenceError("legacy historical metadata must be a JSON object")
    sources = []
    remaining = MAX_SOURCE_BYTES
    for path in paths:
        source = read_source(path, remaining)
        remaining -= len(source["text"].encode("utf-8"))
        sources.append(source)
    if not sources or len({s["name"] for s in sources}) != len(sources):
        raise EvidenceError("sources must have distinct names")
    metadata = []
    for path in metadata_paths:
        source = read_source(path, MAX_MANIFEST_BYTES)
        source["data"] = load_json(source["text"])
        metadata.append(source)
    report = None
    if kind == "v1":
        rows, summary, bencher, qualification, report = shared_summary(manifest, sources)
        evidence = {"schema_version": 1, "format": kind, "status": qualification["status"],
                    "sources": sources, "metadata": metadata,
                    "reasons": ["v1 validation does not independently prove build/event freshness or harness scope."]}
    else:
        for source in sources:
            if kind in CSV_HEADERS:
                csv_rows(kind, source)
            elif kind == "deadpostings":
                dead_rows(source)
            elif kind == "deadpostings-summary":
                aggregate_rows(source)
            else:
                raise EvidenceError("unsupported source format")
        if sum(len(s["rows"]) for s in sources) > MAX_ROWS:
            raise EvidenceError("combined sources exceed 100000 rows")
        reasons = list(LIMITATIONS)
        if kind == "deadpostings" and any(s["observable_digest_u64"] is None for s in sources):
            reasons.append("DeadPostings source has no observable digest trailer.")
        if kind == "deadpostings-summary":
            reasons.append("Aggregate medians/counts are not individual raw timing samples.")
        reasons.append("Historical metadata is an unverified assertion; missing identities and fixture hashes remain unknown.")
        archive = {"archive_schema_version": 1, "artifact_kind": "legacy_hold_archive"}
        evidence = {**archive, "format": kind, "status": "HOLD", "reasons": reasons,
                    "sources": sources, "metadata": metadata,
                    "legacy_metadata": {**(manifest_source or {}), "data": manifest}}
        cases = {}
        for source in sources:
            for row in source["rows"]:
                cases[row["case"]] = {"case": row["case"], "phase": row["phase"], "status": "HOLD"}
        identity = legacy_identity(manifest)
        qualification = {**archive, **identity, "status": "HOLD", "reasons": reasons, "cases": list(cases.values())}
        summary = {**archive, **identity, "method": "legacy_hold_only", "cases": list(cases.values()),
                   "input_hashes": {s["name"]: s["sha256"] for s in sources}}
        rows, bencher = [], {}
    metadata_key = "manifest" if kind == "v1" else "legacy-metadata"
    return {metadata_key: manifest, "samples": rows, "summary": summary, "bencher": bencher,
            "qualification": qualification, "adapter-evidence": evidence, "_report": report}


def check_aliases(output, inputs):
    # resolve() follows a dangling input symlink outside the output directory.
    # Check its lexical directory entry before following it: cleanup must never
    # unlink that immutable input entry, even when its target does not exist.
    lexical_destination = Path(os.path.abspath(output))
    destination = output.resolve()
    for source in inputs:
        lexical_source = Path(os.path.abspath(source))
        if lexical_source == lexical_destination or lexical_destination in lexical_source.parents:
            raise AliasError("lexical input/output paths overlap; refusing mutation")
        # Preserve each entry before following its final component. An input
        # may traverse OUT/manifest.json (a directory symlink) while output is
        # named through another symlink to OUT. Resolving only the leaf loses
        # the ancestor entry that generated-artifact cleanup would unlink.
        # Preserve '..' in the original traversal: removing it before following
        # symlinks can erase an input ancestor that cleanup would mutate.
        original_source = source.absolute()
        for ancestor in (original_source, *original_source.parents):
            entry = ancestor.parent.resolve() / ancestor.name
            if entry == destination or destination in entry.parents:
                raise AliasError("input ancestor traverses the output directory; refusing mutation")
        resolved = source.resolve()
        if resolved == destination or destination in resolved.parents:
            raise AliasError("input/output paths overlap; refusing mutation")
        for name in GENERATED:
            artifact = output / name
            if (artifact.exists() or artifact.is_symlink()) and (artifact.resolve() == resolved or
                                      (artifact.exists() and source.exists() and artifact.samefile(source))):
                raise AliasError("input/output artifact alias; refusing mutation")
    if output.exists() and not output.is_dir():
        raise AliasError("output path is not a directory")


def reject_archive_reuse(output):
    if any((output / name).exists() or (output / name).is_symlink() for name in ARCHIVED):
        raise EvidenceError("output contains an immutable archive; use a fresh output directory")


def clear_derived(output):
    if output.is_dir():
        for name in DERIVED:
            artifact = output / name
            if artifact.is_file() or artifact.is_symlink():
                artifact.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", required=True, choices=[*CSV_HEADERS, "deadpostings", "deadpostings-summary", "v1"])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--metadata", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        try:
            check_aliases(args.output_dir, [args.manifest, *args.source, *args.metadata])
        except (OSError, RuntimeError) as error:
            raise AliasError("cannot safely resolve input/output aliases; refusing mutation") from error
        reject_archive_reuse(args.output_dir)
        manifest_source = read_source(args.manifest, MAX_MANIFEST_BYTES)
        manifest = load_json(manifest_source["text"])
        result = adapt(args.format, args.source, manifest, args.metadata, manifest_source)
        # Finish all validation/serialization before creating any output.
        native = args.format == "v1"
        metadata_key = "manifest" if native else "legacy-metadata"
        manifest_text = json.dumps(result[metadata_key], indent=2, allow_nan=False) + "\n"
        sample_text = "".join(json.dumps(r, allow_nan=False) + "\n" for r in result["samples"])
        hashes = {("manifest_sha256" if native else "metadata_sha256"): hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                  ("samples_sha256" if native else "empty_samples_sha256"): hashlib.sha256(sample_text.encode("utf-8")).hexdigest()}
        if not native:
            hashes["source_sha256"] = {s["name"]: s["sha256"] for s in result["adapter-evidence"]["sources"]}
        result["summary"]["input_hashes"] = hashes
        result["qualification"]["input_hashes"] = hashes
        contents = {f"{key}.json": json.dumps(value, indent=2, allow_nan=False) + "\n"
                    for key, value in result.items() if key not in {"samples", "_report"}}
        contents[f"{metadata_key}.json"] = manifest_text
        contents["samples.jsonl"] = sample_text
        status = result["qualification"]["status"]
        reasons = result["adapter-evidence"]["reasons"]
        contents["report.md"] = result["_report"] or (f"Postprocess adapter status: **{status}**\n\n" +
                                 "\n".join(f"- {r}" for r in reasons) +
                                 "\n\nAll original source rows and metadata are preserved in adapter-evidence.json.\n")
        if native:
            contents["report.md"] += ("\nSerialized v1 input SHA256: manifest `" + hashes["manifest_sha256"] +
                                      "`; samples `" + hashes["samples_sha256"] + "`.\n")
        else:
            contents["report.md"] += ("\nLegacy HOLD archive metadata SHA256: `" + hashes["metadata_sha256"] +
                                      "`. Original source and metadata bytes/hashes are retained in adapter-evidence.json.\n")
        clear_derived(args.output_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in contents.items():
            # Exclusive creation also prevents overwriting an archive that
            # appears after the reuse preflight. Never truncate preserved raw
            # evidence, including during a failed write or concurrent import.
            with (args.output_dir / name).open("x" if name in ARCHIVED else "w", encoding="utf-8") as stream:
                stream.write(content)
        print(status)
        return 0
    except AliasError as error:
        print(f"postprocess adapter: {error}", file=sys.stderr)
        return 2
    except (ValueError, OSError, UnicodeError, csv.Error, TypeError, OverflowError, RecursionError) as error:
        try:
            clear_derived(args.output_dir)
        except OSError:
            pass
        print(f"postprocess adapter: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
