#!/usr/bin/env python3
"""Assemble a collection receipt offline from recorded runner facts.

No commands, Git operations, statistics or publication run here. A review record
is the assertion already required by publish.py; neither that assertion nor a
signature attests execution. Source bindings identify a recorded checkout and a
stable captured source fixture with an explicit reviewed meaning. They do not
prove cleanliness or compilation linkage.

Bindings v1:
  variants: {variant: {source: {phase: "build", index: N, id: "fixture-N",
                              reason: "reviewed source binding"},
                       binary: {phase: "time", index: N, id: "executable"}}}
  compilers: {name: {phase: "build", index: N, id: "tool-N"}}
  inputs: {manifest_fixture_id: [{phase: "time", index: N, id: "fixture-N"}]}
  controls (optional): {fixture_id: {phase, index, id: "fixture-N", reason}}
Record indices follow repeated --build-metadata/--time-metadata arguments.
Bindings contain references and reasons, never replacement hashes or SHAs.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import stat
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[A-Za-z0-9_.+-]{1,128}")
VARIANTS = {"cpp_current", "cpp_optimized", "rust_current", "rust_candidate"}
BUILD_LOCKS = {"i7-heavy.lock": "exclusive", "nzbget-rust-benchmark.lock": "shared"}
TIME_LOCKS = {"nzbget-rust-benchmark.lock": "exclusive"}
JSON_LIMIT = 1024 * 1024
SAMPLES_LIMIT = 32 * 1024 * 1024

class ReceiptError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise ReceiptError(message)

def digest(value, pattern=SHA256):
    return isinstance(value, str) and bool(pattern.fullmatch(value))

def object_keys(value, required, optional=()):
    return isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional)

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result

def invalid_constant(value):
    raise ReceiptError("nonfinite JSON number")

def finite_float(value):
    number = float(value)
    require(math.isfinite(number), "nonfinite JSON number")
    return number

def read_bytes(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "input must be a regular file")
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "input exceeds collection size limit")
    require(bool(raw), "empty collection input")
    return raw

def read_json(path):
    raw = read_bytes(path, JSON_LIMIT)
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant, parse_float=finite_float)
    require(isinstance(value, dict), "collection JSON must be an object")
    return value, raw

def aliases(records, prefix, kind):
    require(isinstance(records, list) and len(records) <= 256, "invalid capture aliases")
    result = {}
    for index, record in enumerate(records):
        require(object_keys(record, {"id", "sha256"}) and record["id"] == f"{prefix}-{index}"
                and digest(record["sha256"]), "invalid capture alias")
        result[record["id"]] = (kind, record["sha256"])
    return result

def captured(records):
    require(isinstance(records, list) and 2 <= len(records) <= 514, "missing bounded captures")
    result = {}
    for record in records:
        require(object_keys(record, {"id", "kind", "sha256"}) and digest(record["sha256"]),
                "unavailable or malformed captured artifact")
        key, kind = record["id"], record["kind"]
        require(isinstance(key, str) and key not in result, "duplicate or invalid capture ID")
        valid = ((key == "runner" and kind == "implementation") or
                 (key == "executable" and kind == "executable") or
                 (bool(re.fullmatch(r"fixture-[0-9]+", key)) and kind == "fixture") or
                 (bool(re.fullmatch(r"tool-[0-9]+", key)) and kind == "toolchain"))
        require(valid, "unsupported capture kind or ID")
        result[key] = (kind, record["sha256"])
    return result

def validate_metadata(record, mode, testbed):
    require(type(record.get("schema_version")) is int and record["schema_version"] == 1
            and type(record.get("capture_version")) is int and record["capture_version"] == 1,
            "missing supported capture version")
    require(record.get("mode") == mode and record.get("testbed") == testbed
            and record.get("lock_scope") == "worker_default", "noncanonical collection environment")
    require(record.get("command_started") is True and type(record.get("exit_code")) is int
            and record["exit_code"] == 0 and record.get("outcome") == "completed",
            "command did not complete successfully")
    require(record.get("lock_modes") == (BUILD_LOCKS if mode == "build" else TIME_LOCKS),
            "recorded locks differ")
    require(record.get("time_prebuilt") is (mode == "time"), "prebuilt timing fact differs")
    if mode == "build":
        require(type(record.get("build_jobs")) is int and 1 <= record["build_jobs"] <= 3,
                "build jobs exceed contract")
    else:
        require(record.get("build_jobs") is None, "timing record contains build jobs")
    command = record.get("command")
    require(object_keys(command, {"name", "sha256", "argv_sha256"}) and
            isinstance(command["name"], str) and bool(NAME.fullmatch(command["name"])) and
            digest(command["sha256"]) and digest(command["argv_sha256"]),
            "invalid hashed command record")
    require(digest(record.get("runner_sha256")), "missing runner invocation identity")
    capture = record.get("captures")
    require(object_keys(capture, {"before", "after"}), "missing before/after captures")
    before, after = captured(capture["before"]), captured(capture["after"])
    require(before == after, "artifact captures changed")
    require(record.get("stability") == {"status": "stable", "changed_ids": [], "reason_codes": []},
            "capture stability is incomplete")
    expected = {"runner": ("implementation", record["runner_sha256"]),
                "executable": ("executable", command["sha256"])}
    expected.update(aliases(record.get("fixtures"), "fixture", "fixture"))
    expected.update(aliases(record.get("toolchain_binaries"), "tool", "toolchain"))
    require(before == expected, "aliases differ from observed captures")
    start, end = record.get("checkout_sha_before"), record.get("checkout_sha_after")
    require(start == end and record.get("checkout_sha") == start,
            "recorded checkout identity changed or alias differs")
    require(start is None or digest(start, SHA), "invalid recorded checkout identity")
    return before

def assemble(manifest, manifest_raw, samples_raw, records, bindings, review):
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
            "unsupported manifest version")
    require(object_keys(bindings, {"schema_version", "variants", "compilers", "inputs"}, {"controls"})
            and type(bindings["schema_version"]) is int and bindings["schema_version"] == 1,
            "unsupported binding shape")
    # This is the existing publisher assertion, never inferred from signatures.
    require(review == {"actor": "xbmc4lyfe", "status": "reviewed"}, "unsupported recorded review assertion")
    testbed = manifest.get("testbed")
    require(isinstance(testbed, str) and bool(NAME.fullmatch(testbed)), "invalid manifest testbed")
    observed = {}
    for mode in ("build", "time"):
        require(isinstance(records.get(mode), list) and 1 <= len(records[mode]) <= 64,
                "missing bounded build/time records")
        observed[mode] = [validate_metadata(record, mode, testbed) for record in records[mode]]
    implementations = {record["runner_sha256"] for phase in records.values() for record in phase}
    require(len(implementations) == 1, "runner implementation records contradict")
    comparison = manifest.get("comparison")
    require(object_keys(comparison, {"baseline", "candidate"}) and
            set(comparison.values()) <= VARIANTS, "invalid manifest comparison")
    fixtures = manifest.get("fixtures")
    require(isinstance(fixtures, list) and 1 <= len(fixtures) <= 256
            and all(isinstance(item, dict) and isinstance(item.get("id"), str)
                    and digest(item.get("sha256")) for item in fixtures), "invalid manifest fixture identities")
    fixture_map = {item["id"]: item for item in fixtures}
    require(len(fixture_map) == len(fixtures), "duplicate manifest fixture identity")
    required = set(comparison.values())
    for fixture in fixtures:
        variants = fixture.get("required_variants", list(comparison.values()))
        require(isinstance(variants, list) and bool(variants) and all(isinstance(v, str) and v in VARIANTS for v in variants),
                "invalid required variants")
        required.update(variants)
    require(isinstance(bindings["variants"], dict) and set(bindings["variants"]) == required,
            "variant bindings differ from required variants")

    def resolve(ref, kind, phase=None, reason=False):
        keys = {"phase", "index", "id"} | ({"reason"} if reason else set())
        require(object_keys(ref, keys), "binding must contain only recorded references")
        mode, index = ref["phase"], ref["index"]
        require(isinstance(mode, str) and mode in observed and (phase is None or mode == phase)
                and type(index) is int and 0 <= index < len(observed[mode])
                and isinstance(ref["id"], str), "invalid record reference")
        value = observed[mode][index].get(ref["id"])
        require(value is not None and value[0] == kind, "binding lacks recorded artifact kind")
        if reason:
            require(isinstance(ref["reason"], str) and 0 < len(ref["reason"]) <= 1000,
                    "missing explicit recorded binding reason")
        return records[mode][index], value[1]

    sources, binaries, optimized, variant_times = {}, {}, {}, {}
    for variant, binding in bindings["variants"].items():
        require(object_keys(binding, {"source", "binary"}), "invalid variant binding")
        record, _ = resolve(binding["source"], "fixture", "build", reason=True)
        require(digest(record.get("checkout_sha_before"), SHA), "source lacks recorded checkout SHA")
        sources[variant] = record["checkout_sha_before"]
        _, binaries[variant] = resolve(binding["binary"], "executable", "time")
        variant_times[variant] = binding["binary"]["index"]
        if variant == "cpp_optimized":
            optimized[variant] = {"source_sha": sources[variant], "reason": binding["source"]["reason"]}

    compiler_bindings = bindings["compilers"]
    require(isinstance(compiler_bindings, dict) and 1 <= len(compiler_bindings) <= 64
            and all(isinstance(name, str) and bool(NAME.fullmatch(name)) for name in compiler_bindings),
            "missing bounded compiler bindings")
    compilers = {name: resolve(ref, "toolchain", "build")[1] for name, ref in compiler_bindings.items()}
    require(isinstance(bindings["inputs"], dict) and set(bindings["inputs"]) == set(fixture_map),
            "input bindings differ from manifest fixtures")
    inputs = {}
    for key, refs in bindings["inputs"].items():
        require(isinstance(refs, list) and 1 <= len(refs) <= 64, "missing bounded input references")
        selected = set()
        for ref in refs:
            _, value = resolve(ref, "fixture", "time")
            require(value == fixture_map[key]["sha256"], "captured input differs from manifest")
            require(ref["index"] not in selected, "duplicate input record binding")
            selected.add(ref["index"])
        needed = fixture_map[key].get("required_variants", list(comparison.values()))
        require({variant_times[v] for v in needed} <= selected,
                "input not captured for every required timed variant")
        inputs[key] = fixture_map[key]["sha256"]
    controls = {}
    control_bindings = bindings.get("controls", {})
    required_controls = {key for key, fixture in fixture_map.items() if fixture.get("role") == "unchanged_control"}
    require(isinstance(control_bindings, dict) and set(control_bindings) == required_controls,
            "unchanged controls lack captured source bindings")
    for key, ref in control_bindings.items():
        _, value = resolve(ref, "fixture", reason=True)
        controls[key] = {"source_sha256": value, "reason": ref["reason"]}
    receipt = {"schema_version": 1, "review": review,
               "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
               "samples_sha256": hashlib.sha256(samples_raw).hexdigest(),
               "base_sha": manifest.get("base_sha"), "candidate_sha": manifest.get("candidate_sha"),
               "testbed": testbed, "source_hashes": sources, "binary_hashes": binaries,
               "compiler_hashes": compilers, "input_hashes": inputs,
               "commands": {mode: [r["command"] for r in records[mode]] for mode in ("build", "time")},
               "runner": {"implementation_sha256": implementations.pop(), "lock_scope": "worker_default",
                          "build_jobs": max(r["build_jobs"] for r in records["build"]),
                          "build_locks": ["i7-heavy.lock:exclusive", "nzbget-rust-benchmark.lock:shared"],
                          "time_locks": ["nzbget-rust-benchmark.lock:exclusive"], "time_prebuilt": True}}
    if controls:
        receipt["control_attribution"] = controls
    if optimized:
        receipt["variant_source_attribution"] = optimized
    # Reuse the sole publisher-owned receipt contract, not another validator.
    from publish import receipt_reasons
    require(not receipt_reasons(receipt, manifest, manifest_raw, samples_raw),
            "recorded facts do not satisfy publisher receipt contract")
    return receipt

def guard_output(output, inputs):
    require(not output.is_symlink(), "output must not be a symbolic link")
    require(output.parent.is_dir(), "output parent must already exist")
    require(all(not parent.is_symlink() for parent in output.parents), "output ancestor must not be a symbolic link")
    target = output.resolve()
    for path in inputs:
        require(target != path.resolve(), "output aliases a collection input")
        if output.exists() and path.exists():
            require(not os.path.samefile(output, path), "output aliases a collection input inode")
    require(not output.exists() or output.is_file(), "output must be a regular file")

def save_receipt(output, inputs, receipt):
    guard_output(output, inputs)
    raw = (json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    require(len(raw) <= JSON_LIMIT, "receipt exceeds collection size limit")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".receipt-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        guard_output(output, inputs)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("manifest", "samples", "bindings", "review-record", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("build-metadata", "time-metadata"):
        parser.add_argument("--" + name, type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    inputs = [args.manifest, args.samples, args.bindings, args.review_record, *args.build_metadata, *args.time_metadata]
    try:
        require(1 <= len(args.build_metadata) <= 64 and 1 <= len(args.time_metadata) <= 64,
                "metadata count exceeds collection limit")
        guard_output(args.output, inputs)
        manifest, manifest_raw = read_json(args.manifest)
        samples_raw = read_bytes(args.samples, SAMPLES_LIMIT)
        bindings, _ = read_json(args.bindings)
        review, _ = read_json(args.review_record)
        records = {phase: [read_json(path)[0] for path in getattr(args, phase + "_metadata")]
                   for phase in ("build", "time")}
        receipt = assemble(manifest, manifest_raw, samples_raw, records, bindings, review)
        save_receipt(args.output, inputs, receipt)
    except (ReceiptError, OSError, ValueError, TypeError, KeyError, ImportError, RecursionError):
        # Do not echo paths, binding reasons, raw arguments or input content.
        print("collection receipt HOLD: missing, inconsistent or unsupported recorded facts", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
