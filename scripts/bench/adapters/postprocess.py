#!/usr/bin/env python3
"""Preserve postprocess caller evidence without manufacturing shared v1 samples.

Usage: python3 scripts/bench/adapters/postprocess.py --format par-crc
       --manifest MANIFEST --source RAW [--source RAW ...] --output-dir OUTPUT_DIR

Legacy inputs contain rounded nanoseconds per operation. They cannot recover
elapsed totals, iteration counts, process clusters, or SHA-256 output digests.
Every original row (including slower controls and initialization) is retained
in adapter-evidence.json, with empty samples.jsonl and HOLD qualification.
Optional --metadata JSON preserves reviewed caller metadata and its hash.

Formats match retained DeadPostings Load logs/summaries, ArticleWriter CRC CSV,
PAR CRC packet-fold CSV, PAR damage CSV, and PAR range-plan CSV. Empty CRC/PAR
calls are empty_call overhead; nonempty calls are throughput. DeadPostings
Load is initialization even when the state file is nonempty. These phases never
establish complete-caller scope. Only --format v1 consumes already recorded v1
raw samples, using the shared summarize.py validator unchanged. Harness scope
and build/event freshness remain responsibilities of the evidence producer.
No harness is run, no metadata is inferred, and no legacy evidence is promoted.
"""

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import re
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
GENERATED = {"manifest.json", "samples.jsonl", "summary.json", "bencher.json",
             "qualification.json", "adapter-evidence.json", "report.md"}
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
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
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


def adapt(kind, paths, manifest, metadata_paths=()):
    validate_manifest(manifest)
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
        evidence = {"schema_version": 1, "format": kind, "status": "HOLD", "reasons": reasons,
                    "sources": sources, "metadata": metadata}
        cases = {}
        for source in sources:
            for row in source["rows"]:
                cases[row["case"]] = {"case": row["case"], "phase": row["phase"], "status": "HOLD"}
        identity = {key: manifest[key] for key in ("schema_version", "base_sha", "candidate_sha", "testbed")}
        qualification = {**identity, "status": "HOLD", "reasons": reasons, "cases": list(cases.values())}
        summary = {**identity, "method": "legacy_hold_only", "cases": list(cases.values()),
                   "input_hashes": {s["name"]: s["sha256"] for s in sources}}
        rows, bencher = [], {}
    return {"manifest": manifest, "samples": rows, "summary": summary, "bencher": bencher,
            "qualification": qualification, "adapter-evidence": evidence, "_report": report}


def check_aliases(output, inputs):
    destination = output.resolve()
    for source in inputs:
        resolved = source.resolve()
        if resolved == destination or destination in resolved.parents:
            raise AliasError("input/output paths overlap; refusing mutation")
        for name in GENERATED:
            artifact = output / name
            if artifact.exists() and (artifact.resolve() == resolved or
                                      (source.exists() and artifact.samefile(source))):
                raise AliasError("input/output artifact alias; refusing mutation")
    if output.exists() and not output.is_dir():
        raise AliasError("output path is not a directory")


def clear_generated(output):
    if output.is_dir():
        for name in GENERATED:
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
        check_aliases(args.output_dir, [args.manifest, *args.source, *args.metadata])
        manifest = load_json(read_source(args.manifest, MAX_MANIFEST_BYTES)["text"])
        result = adapt(args.format, args.source, manifest, args.metadata)
        # Finish all validation/serialization before creating any output.
        manifest_text = json.dumps(result["manifest"], indent=2, allow_nan=False) + "\n"
        sample_text = "".join(json.dumps(r, allow_nan=False) + "\n" for r in result["samples"])
        hashes = {"manifest_sha256": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                  "samples_sha256": hashlib.sha256(sample_text.encode("utf-8")).hexdigest()}
        result["summary"]["input_hashes"] = hashes
        result["qualification"]["input_hashes"] = hashes
        contents = {f"{key}.json": json.dumps(value, indent=2, allow_nan=False) + "\n"
                    for key, value in result.items() if key not in {"samples", "_report"}}
        contents["manifest.json"] = manifest_text
        contents["samples.jsonl"] = sample_text
        status = result["qualification"]["status"]
        reasons = result["adapter-evidence"]["reasons"]
        contents["report.md"] = result["_report"] or (f"Postprocess adapter status: **{status}**\n\n" +
                                 "\n".join(f"- {r}" for r in reasons) +
                                 "\n\nAll original source rows and metadata are preserved in adapter-evidence.json.\n")
        contents["report.md"] += ("\nSerialized v1 input SHA256: manifest `" + hashes["manifest_sha256"] +
                                  "`; samples `" + hashes["samples_sha256"] + "`.\n")
        clear_generated(args.output_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in contents.items():
            (args.output_dir / name).write_text(content, encoding="utf-8")
        print(status)
        return 0
    except AliasError as error:
        print(f"postprocess adapter: {error}", file=sys.stderr)
        return 2
    except (ValueError, OSError, UnicodeError, csv.Error, TypeError, OverflowError, RecursionError) as error:
        try:
            clear_generated(args.output_dir)
        except OSError:
            pass
        print(f"postprocess adapter: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
