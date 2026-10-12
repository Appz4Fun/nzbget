#!/usr/bin/env python3
"""Black-box shared CLI contract tests; every measurement here is synthetic.

Run with ``python3 -m unittest discover -s scripts/bench/tests -p test_pipeline.py``.
BENCH_PIPELINE_ROOT can select a dependency checkout before integration. Tests do
not build, time migration code, publish, or access a provider/network service.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(os.environ.get("BENCH_PIPELINE_ROOT", Path(__file__).resolve().parents[3]))
PUBLISHER_ROOT = Path(os.environ.get("BENCH_PUBLISHER_ROOT", ROOT))
ASSEMBLER_ROOT = Path(os.environ.get("BENCH_ASSEMBLER_ROOT", ROOT))
BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
INPUT_DIGEST = hashlib.sha256(b"controlled integration input").hexdigest()
OUTPUT_DIGEST = hashlib.sha256(b"controlled equivalent output").hexdigest()
VARIANTS = ("cpp_current", "cpp_optimized", "rust_current", "rust_candidate")
ARTIFACTS = ("summary.json", "bencher.json", "qualification.json", "report.md")
RAW_PROOF_FILES = ("manifest.json", "samples.jsonl", "collection-receipt.json")


def synthetic_receipt(manifest_raw, samples_raw, variants=VARIANTS, review_decision="required"):
    """Explicit synthetic review assertions, never approval of a real capture."""
    def toy_hash(label):
        return hashlib.sha256(("synthetic fixture: " + label).encode()).hexdigest()
    content = {variant: toy_hash("reviewed source " + variant) for variant in variants}
    # The review is supplied independently as a fixed fixture assertion. Tests
    # mutate captures later without regenerating that explicit review.
    approved = {variant: toy_hash("reviewed source " + variant) for variant in variants}
    command = {"name": "controlled-caller", "sha256": toy_hash("caller binary"),
               "argv_sha256": toy_hash("nonsecret command arguments")}
    return {"schema_version": 1,
        "review": {"actor": "xbmc4lyfe", "status": "reviewed", "source_content_hashes": approved,
                   "rust_preservation_applicability": {"controlled/caller": review_decision}},
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "samples_sha256": hashlib.sha256(samples_raw).hexdigest(),
        "base_sha": BASE_SHA, "candidate_sha": CANDIDATE_SHA,
        "testbed": "synthetic-contract-test-no-performance-claim",
        "source_hashes": {variant: CANDIDATE_SHA if variant == "rust_candidate" else BASE_SHA
                          for variant in variants},
        "source_content_hashes": content,
        "binary_hashes": {variant: toy_hash("binary " + variant) for variant in variants},
        "compiler_hashes": {"controlled-compiler": toy_hash("compiler binary")},
        "input_hashes": {"controlled/caller": INPUT_DIGEST},
        "variant_source_attribution": {"cpp_optimized": {"source_sha": BASE_SHA,
            "reason": "Synthetic fixture explicitly models the optimized C++ control."}},
        "commands": {"build": [dict(command)], "time": [dict(command)]},
        "runner": {"implementation_sha256": toy_hash("runner implementation"), "lock_scope": "worker_default",
                   "build_jobs": 3, "build_locks": ["i7-heavy.lock:exclusive", "nzbget-rust-benchmark.lock:shared"],
                   "time_locks": ["nzbget-rust-benchmark.lock:exclusive"], "time_prebuilt": True}}

# Replace only external HTTP transport. The actual publisher CLI, parsing,
# signature/blob checks, identity binding and failure outputs still execute.
# Unknown endpoints and every write are refused; this process cannot network.
PUBLISHER_TRANSPORT = r'''
import io, json, pathlib, runpy, subprocess, sys, urllib.parse, urllib.request
script, fixture, journal, *arguments = sys.argv[1:]
fixture_data = json.loads(pathlib.Path(fixture).read_text())
responses = fixture_data.get("responses", fixture_data)
allowed_status_posts = fixture_data.get("allowed_status_posts", [])
def controlled_open(self, request, *args, **kwargs):
    parsed = urllib.parse.urlsplit(request.full_url)
    endpoint = parsed.path + ("?" + parsed.query if parsed.query else "")
    method = request.get_method()
    record = {"method": method, "endpoint": endpoint}
    if method == "POST":
        record["payload"] = json.loads(request.data)
    with pathlib.Path(journal).open("a") as output:
        output.write(json.dumps(record) + "\n")
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise AssertionError("unexpected network origin")
    if method != "GET":
        if (method != "POST" or endpoint not in allowed_status_posts or
                record["payload"].get("context") != "paired caller qualification" or
                record["payload"].get("state") not in ("pending", "failure")):
            raise AssertionError("unexpected authenticated write")
        return io.BytesIO(b'{"id":1}')
    if endpoint not in responses:
        raise AssertionError("unexpected external API endpoint: " + endpoint)
    class Response(io.BytesIO):
        pass
    return Response(json.dumps(responses[endpoint]).encode())
urllib.request.OpenerDirector.open = controlled_open
original_run = subprocess.run
def no_bencher(command, *args, **kwargs):
    if pathlib.Path(command[0]).name == "bencher":
        raise AssertionError("unexpected Bencher execution")
    return original_run(command, *args, **kwargs)
subprocess.run = no_bencher
sys.argv = [script, *arguments]
runpy.run_path(script, run_name="__main__")
'''


def controlled_manifest(scope="complete_caller"):
    return {
        "schema_version": 1,
        "base_sha": BASE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "testbed": "synthetic-contract-test-no-performance-claim",
        "toolchain": {"compiler": "controlled fixture", "flags": "none"},
        "fixtures": [{"id": "controlled/caller", "sha256": INPUT_DIGEST,
                      "scope": scope, "role": "changed", "required_variants": list(VARIANTS),
                      "rust_preservation_applicability": "required"}],
        "comparison": {"baseline": "cpp_optimized", "candidate": "rust_candidate"},
    }


def controlled_rows(candidate_ns=800, processes=8, rounds=10, case="controlled/caller", variants=VARIANTS):
    """Literal controls; alternate positions without simulating measured clocks."""
    rows = []
    for process in range(processes):
        candidate = candidate_ns[process] if isinstance(candidate_ns, list) else candidate_ns
        latencies = {"cpp_current": 1200, "cpp_optimized": 1000,
                     "rust_current": 1100, "rust_candidate": candidate}
        for round_ in range(rounds):
            order = ("cpp_optimized", "cpp_current", "rust_current", "rust_candidate")
            if round_ % 2:
                order = tuple(reversed(order))
            order = tuple(variant for variant in order if variant in variants)
            for position, variant in enumerate(order):
                rows.append({"case": case, "variant": variant,
                             "process": process, "round": round_, "order": position,
                             "elapsed_ns": latencies[variant] * 100,
                             "iterations": 100, "observable_digest": OUTPUT_DIGEST})
    return rows


class PipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nzbget-pipeline-contract-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.manifest = self.work / "manifest.json"
        self.samples = self.work / "samples.jsonl"
        self.output = self.work / "output"

    def summarize(self, manifest=None, rows=None, manifest_text=None, samples_text=None):
        self.manifest.write_text(manifest_text if manifest_text is not None else
                                 json.dumps(manifest if manifest is not None else controlled_manifest()),
                                 encoding="utf-8")
        self.samples.write_text(samples_text if samples_text is not None else
                                "".join(json.dumps(row) + "\n" for row in
                                        (rows if rows is not None else controlled_rows())), encoding="utf-8")
        before = (self.manifest.read_bytes(), self.samples.read_bytes())
        result = self.invoke_summary(self.manifest, self.samples, self.output)
        self.assertEqual(before, (self.manifest.read_bytes(), self.samples.read_bytes()),
                         "The shared CLI must preserve immutable raw inputs")
        return result

    def invoke_summary(self, manifest, samples, output, timeout=30):
        script = ROOT / "scripts/bench/summarize.py"
        self.assertTrue(script.is_file(), f"Shared CLI dependency missing: {script}")
        return subprocess.run([sys.executable, str(script), "--manifest", str(manifest),
                               "--samples", str(samples), "--output-dir", str(output)],
                              capture_output=True, text=True, timeout=timeout)

    def valid(self, status, **kwargs):
        result = self.summarize(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all((self.output / name).is_file() for name in ARTIFACTS),
                        "Valid evidence, including HOLD, must produce the complete artifact set")
        # Reject non-standard NaN/Infinity in machine-readable output as well.
        def reject_constant(value):
            raise ValueError(f"nonfinite output constant: {value}")
        outputs = {name: json.loads((self.output / name).read_text(encoding="utf-8"),
                                   parse_constant=reject_constant) for name in ARTIFACTS[:-1]}
        qualification = outputs["qualification.json"]
        self.assertEqual(qualification["status"], status)
        self.assertEqual(qualification["base_sha"], BASE_SHA)
        self.assertEqual(qualification["candidate_sha"], CANDIDATE_SHA)
        return outputs

    def invalid(self, **kwargs):
        result = self.summarize(**kwargs)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any((self.output / name).exists() for name in ARTIFACTS),
                         "Rejected evidence must not leave publishable summary artifacts")

    def test_complete_caller_with_all_controls_qualifies(self):
        outputs = self.valid("PASS")
        case = outputs["qualification.json"]["cases"][0]
        self.assertEqual(case["scope"], "complete_caller")
        self.assertEqual(case["status"], "PASS")
        self.assertAlmostEqual(case["ratio"]["estimate"], 0.8)

    def test_equal_latency_is_inconclusive_and_held(self):
        self.valid("HOLD", rows=controlled_rows(candidate_ns=1000))

    def test_slower_candidate_is_held(self):
        self.valid("HOLD", rows=controlled_rows(candidate_ns=1200))

    def test_current_rust_regression_holds_candidate_that_beats_both_cpp_controls(self):
        latencies = {"cpp_current": 1000, "cpp_optimized": 1000,
                     "rust_current": 500, "rust_candidate": 800}
        rows = controlled_rows()
        for row in rows:
            row["elapsed_ns"] = latencies[row["variant"]] * 100
        outputs = self.valid("HOLD", rows=rows)
        case = outputs["summary.json"]["cases"][0]
        self.assertEqual(case["raw_count"], 320, "All four raw control variants must survive HOLD")
        self.assertEqual(set(case["variants"]), set(VARIANTS))
        for variant in VARIANTS:
            self.assertEqual(case["variants"][variant]["count"], 80)
            self.assertEqual(outputs["bencher.json"]["controlled/caller/" + variant]["latency"]["value"],
                             latencies[variant])

    def test_current_rust_tie_allows_candidate_that_beats_optimized_cpp(self):
        rows = controlled_rows()
        for row in rows:
            if row["variant"] == "rust_current":
                row["elapsed_ns"] = 800 * 100
        outputs = self.valid("PASS", rows=rows)
        preservation = outputs["summary.json"]["cases"][0].get("rust_preservation")
        self.assertIsInstance(preservation, dict, "Required current-Rust preservation needs separate evidence")
        self.assertEqual(preservation["status"], "PASS")
        self.assertAlmostEqual(preservation["ratio"]["upper"], 1.0)
        self.assertEqual(outputs["qualification.json"]["cases"][0]["rust_preservation"]["status"], "PASS")

    def test_non_cpp_selected_baseline_remains_diagnostic_hold(self):
        latencies = {"cpp_current": 1000, "cpp_optimized": 1000,
                     "rust_current": 2000, "rust_candidate": 1500}
        for scope in ("complete_caller", "kernel"):
            with self.subTest(scope=scope):
                manifest = controlled_manifest(scope=scope)
                manifest["comparison"]["baseline"] = "rust_current"
                rows = controlled_rows()
                for row in rows:
                    row["elapsed_ns"] = latencies[row["variant"]] * 100
                outputs = self.valid("HOLD", manifest=manifest, rows=rows)
                case = outputs["summary.json"]["cases"][0]
                self.assertAlmostEqual(case["ratio"]["estimate"], 0.75)
                self.assertEqual(case["raw_count"], 320)
                self.assertEqual(set(case["variants"]), set(VARIANTS))

    def test_missing_rust_applicability_decision_is_hold(self):
        manifest = controlled_manifest()
        del manifest["fixtures"][0]["rust_preservation_applicability"]
        self.valid("HOLD", manifest=manifest)

    def test_required_current_rust_without_declared_baseline_is_hold(self):
        manifest = controlled_manifest()
        variants = [variant for variant in VARIANTS if variant != "rust_current"]
        manifest["fixtures"][0]["required_variants"] = variants
        self.valid("HOLD", manifest=manifest, rows=controlled_rows(variants=variants))

    def test_explicit_first_port_applicability_is_numerically_eligible(self):
        manifest = controlled_manifest()
        variants = [variant for variant in VARIANTS if variant != "rust_current"]
        manifest["fixtures"][0].update(required_variants=variants,
            rust_preservation_applicability="not_applicable", provenance={
                "rust_preservation_rationale": "Synthetic first-port fixture has C++ controls and a first Rust candidate; no current Rust control exists."})
        self.valid("PASS", manifest=manifest, rows=controlled_rows(variants=variants))

    def test_not_applicable_with_declared_current_rust_is_rejected(self):
        manifest = controlled_manifest()
        manifest["fixtures"][0].update(rust_preservation_applicability="not_applicable", provenance={
            "rust_preservation_rationale": "This controlled assertion contradicts the declared current Rust control."})
        self.invalid(manifest=manifest)

    def test_optimized_cpp_tie_is_hold_despite_preserved_current_rust(self):
        rows = controlled_rows(candidate_ns=1000)
        for row in rows:
            if row["variant"] == "rust_current":
                row["elapsed_ns"] = 1000 * 100
        outputs = self.valid("HOLD", rows=rows)
        case = outputs["summary.json"]["cases"][0]
        self.assertEqual(case["statistical_status"], "inconclusive")
        self.assertAlmostEqual(case["ratio"]["estimate"], 1.0)
        preservation = case.get("rust_preservation")
        self.assertIsInstance(preservation, dict, "Required current-Rust preservation needs separate evidence")
        self.assertEqual(preservation["status"], "PASS",
                         "No confident C++ speedup is separate from a current-Rust regression")
        self.assertEqual(outputs["qualification.json"]["cases"][0]["rust_preservation"]["status"], "PASS")

    def test_process_disagreement_is_held_despite_faster_pooled_values(self):
        self.valid("HOLD", rows=controlled_rows(candidate_ns=[500, 1300] * 4))

    def test_kernel_speedup_cannot_qualify_runtime_replacement(self):
        outputs = self.valid("HOLD", manifest=controlled_manifest(scope="kernel"))
        self.assertEqual(outputs["qualification.json"]["cases"][0]["scope"], "kernel")

    def test_unchanged_control_parity_and_changed_caller_can_qualify(self):
        manifest = controlled_manifest()
        control = copy.deepcopy(manifest["fixtures"][0])
        control.update(id="controlled/unchanged", role="unchanged_control",
                       provenance={"attribution": "synthetic unchanged caller"})
        manifest["fixtures"].append(control)
        control_rows = controlled_rows(candidate_ns=1000, case=control["id"])
        for row in control_rows:
            if row["variant"] == "rust_current":
                row["elapsed_ns"] = 1000 * 100
        rows = controlled_rows() + control_rows
        self.valid("PASS", manifest=manifest, rows=rows)

    def test_unchanged_control_drift_holds_changed_caller(self):
        manifest = controlled_manifest()
        control = copy.deepcopy(manifest["fixtures"][0])
        control.update(id="controlled/unchanged", role="unchanged_control",
                       provenance={"attribution": "synthetic unchanged caller"})
        manifest["fixtures"].append(control)
        for latency in (800, 1200):
            with self.subTest(control_latency=latency):
                rows = controlled_rows() + controlled_rows(candidate_ns=latency, case=control["id"])
                self.valid("HOLD", manifest=manifest, rows=rows)

    def test_unchanged_control_alone_cannot_qualify_replacement(self):
        manifest = controlled_manifest()
        manifest["fixtures"][0].update(role="unchanged_control",
                                      provenance={"attribution": "synthetic unchanged caller"})
        self.valid("HOLD", manifest=manifest, rows=controlled_rows(candidate_ns=1000))

    def test_unchanged_control_current_rust_drift_holds_equal_cpp_control(self):
        manifest = controlled_manifest()
        control = copy.deepcopy(manifest["fixtures"][0])
        control.update(id="controlled/unchanged", role="unchanged_control",
                       provenance={"attribution": "synthetic unchanged caller"})
        manifest["fixtures"].append(control)
        for current_rust_latency in (500, 1200):
            with self.subTest(current_rust_latency=current_rust_latency):
                controls = controlled_rows(candidate_ns=1000, case=control["id"])
                for row in controls:
                    if row["variant"] == "rust_current":
                        row["elapsed_ns"] = current_rust_latency * 100
                outputs = self.valid("HOLD", manifest=manifest, rows=controlled_rows() + controls)
                case = next(case for case in outputs["summary.json"]["cases"] if case["case"] == control["id"])
                self.assertAlmostEqual(case["ratio"]["estimate"], 1.0)
                self.assertEqual(case["rust_preservation"]["status"], "HOLD")
                qualified = next(case for case in outputs["qualification.json"]["cases"]
                                 if case["case"] == control["id"])
                self.assertEqual(qualified["rust_preservation"]["status"], "HOLD")

    def test_unattributed_unchanged_control_is_rejected(self):
        manifest = controlled_manifest()
        manifest["fixtures"][0]["role"] = "unchanged_control"
        self.invalid(manifest=manifest)

    def test_too_few_processes_are_held(self):
        self.valid("HOLD", rows=controlled_rows(processes=7))

    def test_too_few_paired_rounds_are_held(self):
        self.valid("HOLD", rows=controlled_rows(rounds=9))

    def test_fixed_variant_order_is_held(self):
        rows = controlled_rows()
        for row in rows:
            row["order"] = VARIANTS.index(row["variant"])
        self.valid("HOLD", rows=rows)

    def test_mismatched_observable_output_is_rejected(self):
        rows = controlled_rows()
        rows[-1]["observable_digest"] = hashlib.sha256(b"different output").hexdigest()
        self.invalid(rows=rows)

    def test_entire_missing_baseline_is_held(self):
        self.valid("HOLD", rows=[row for row in controlled_rows() if row["variant"] != "cpp_optimized"])

    def test_entire_missing_required_control_is_held(self):
        self.valid("HOLD", rows=[row for row in controlled_rows() if row["variant"] != "rust_current"])

    def test_empty_evidence_is_held(self):
        self.valid("HOLD", rows=[])

    def test_unmatched_pair_is_rejected(self):
        self.invalid(rows=controlled_rows()[:-1])

    def test_duplicate_row_key_is_rejected(self):
        rows = controlled_rows()
        rows.append(copy.deepcopy(rows[0]))
        self.invalid(rows=rows)

    def test_invalid_manifest_json_is_rejected(self):
        self.invalid(manifest_text='{"schema_version":')

    def test_invalid_sample_json_is_rejected(self):
        self.invalid(samples_text='{"case":\n')

    def test_nonfinite_elapsed_values_are_rejected(self):
        for number in (math.nan, math.inf, -math.inf):
            with self.subTest(number=number):
                rows = controlled_rows()
                rows[0]["elapsed_ns"] = number
                self.invalid(rows=rows)

    def test_missing_output_digest_is_rejected(self):
        rows = controlled_rows()
        del rows[0]["observable_digest"]
        self.invalid(rows=rows)

    def test_invalid_rerun_clears_prior_pass_artifacts(self):
        self.valid("PASS")
        self.invalid(samples_text="not valid JSON\n")

    def test_output_alias_cannot_overwrite_raw_input(self):
        self.output.mkdir()
        # Seed the input before constructing aliases, then invoke the real CLI.
        self.manifest.write_text(json.dumps(controlled_manifest()), encoding="utf-8")
        alias = self.output / "summary.json"
        for kind in ("symlink", "hardlink"):
            with self.subTest(alias=kind):
                if kind == "symlink":
                    alias.symlink_to(self.manifest)
                else:
                    os.link(self.manifest, alias)
                try:
                    result = self.summarize()
                    self.assertEqual(result.returncode, 2, result.stderr)
                finally:
                    alias.unlink(missing_ok=True)

    def test_input_ancestor_entries_survive_rejected_summary(self):
        for input_kind in ("manifest", "samples"):
            for route in ("direct", "output_alias", "dotdot", "dangling_parent"):
                with self.subTest(input_kind=input_kind, route=route):
                    case = self.work / f"ancestor-{input_kind}-{route}"
                    case.mkdir()
                    output = case / "out"
                    output.mkdir()
                    originals = case / "originals"
                    originals.mkdir()
                    manifest = originals / "manifest.json"
                    samples = originals / "samples.jsonl"
                    manifest.write_bytes(json.dumps(controlled_manifest()).encode())
                    samples.write_bytes(b"not-valid-json\n")
                    before = (manifest.read_bytes(), samples.read_bytes())
                    ancestor = output / "summary.json"
                    target = case / "missing-originals" if route == "dangling_parent" else originals
                    ancestor.symlink_to(target, target_is_directory=True)
                    marker = output / "qualification.json"
                    marker.write_bytes(b'{"status":"PASS"}')
                    selected = ancestor / ("manifest.json" if input_kind == "manifest" else "samples.jsonl")
                    if route == "dotdot":
                        selected = ancestor / ".." / ".." / case.name / "originals" / selected.name
                    output_arg = output
                    if route == "output_alias":
                        output_arg = case / "output-alias"
                        output_arg.symlink_to(output, target_is_directory=True)
                    result = self.invoke_summary(selected if input_kind == "manifest" else manifest,
                                                 selected if input_kind == "samples" else samples,
                                                 output_arg)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertTrue(ancestor.is_symlink(), "Rejected proof deleted an input ancestor link")
                    self.assertEqual(ancestor.readlink(), target)
                    self.assertEqual(before, (manifest.read_bytes(), samples.read_bytes()))
                    self.assertEqual(marker.read_bytes(), b'{"status":"PASS"}',
                                     "Alias rejection must precede generated-artifact cleanup")

    def test_input_symlink_target_intermediate_entry_survives_rejection(self):
        for input_kind in ("manifest", "samples"):
            with self.subTest(input_kind=input_kind):
                case = self.work / f"target-intermediate-{input_kind}"
                case.mkdir()
                output = case / "out"
                output.mkdir()
                originals = case / "originals"
                originals.mkdir()
                raw = json.dumps(controlled_manifest()).encode() if input_kind == "manifest" else b"not-json\n"
                original = originals / ("manifest.json" if input_kind == "manifest" else "samples.jsonl")
                original.write_bytes(raw)
                intermediate = output / "summary.json"
                intermediate.symlink_to(originals, target_is_directory=True)
                outer = case / "outer-input"
                outer.symlink_to(intermediate / original.name)
                other = case / "other-input"
                other_raw = b"not-json\n" if input_kind == "manifest" else json.dumps(controlled_manifest()).encode()
                other.write_bytes(other_raw)
                marker = output / "qualification.json"
                marker.write_bytes(b'{"status":"PASS"}')
                original_entries = [(path, path.lstat().st_ino, path.readlink()) for path in (outer, intermediate)]
                result = self.invoke_summary(outer if input_kind == "manifest" else other,
                                             outer if input_kind == "samples" else other, output)
                self.assertEqual(result.returncode, 2, result.stderr)
                for path, inode, target in original_entries:
                    self.assertTrue(path.is_symlink(), "Rejected proof deleted a traversed symlink target entry")
                    self.assertEqual(path.lstat().st_ino, inode)
                    self.assertEqual(path.readlink(), target)
                self.assertEqual(original.read_bytes(), raw)
                self.assertEqual(other.read_bytes(), other_raw)
                self.assertEqual(marker.read_bytes(), b'{"status":"PASS"}')

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO input contract requires POSIX")
    def test_fifo_input_is_rejected_without_blocking_or_mutation(self):
        for input_kind in ("manifest", "samples"):
            with self.subTest(input_kind=input_kind):
                case = self.work / f"fifo-{input_kind}"
                case.mkdir()
                manifest = case / "manifest.json"
                samples = case / "samples.jsonl"
                manifest.write_bytes(json.dumps(controlled_manifest()).encode())
                samples.write_bytes(b"")
                fifo = manifest if input_kind == "manifest" else samples
                other = samples if input_kind == "manifest" else manifest
                other_raw = other.read_bytes()
                fifo.unlink()
                os.mkfifo(fifo)
                inode = fifo.lstat().st_ino
                output = case / "out"
                try:
                    result = self.invoke_summary(manifest, samples, output, timeout=2)
                except subprocess.TimeoutExpired:
                    self.fail("Non-regular FIFO input blocked the shared CLI")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))
                self.assertEqual(fifo.lstat().st_ino, inode)
                self.assertEqual(other.read_bytes(), other_raw)
                self.assertFalse(any((output / name).exists() for name in ARTIFACTS))


class PublisherIdentityContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nzbget-publisher-contract-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.output = self.work / "validated"
        self.journal = self.work / "api-calls.jsonl"
        self.github_output = self.work / "github-output"

    def invoke(self, manifest=None, current_base=BASE_SHA, current_head=CANDIDATE_SHA,
               actor="xbmc4lyfe", identity_only=False, cli_arguments=None,
               raw_manifest=None, response_updates=None, allow_status_posts=False,
               head_repository="Appz4Fun/nzbget", publish=False, raw_samples=b"", raw_receipt=None):
        import base64
        evidence_sha, tree_sha = "3" * 40, "4" * 40
        manifest = controlled_manifest() if manifest is None else manifest
        raw_files = {"manifest.json": raw_manifest if raw_manifest is not None else json.dumps(manifest).encode(),
                     "samples.jsonl": raw_samples}
        if raw_receipt is not None:
            raw_files["collection-receipt.json"] = raw_receipt
        tree, blobs = [], {}
        for name, raw in raw_files.items():
            sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            tree.append({"path": "benchmark-results/" + name, "mode": "100644",
                         "type": "blob", "sha": sha, "size": len(raw)})
            blobs["/repos/Appz4Fun/nzbget/git/blobs/" + sha] = {
                "sha": sha, "encoding": "base64", "content": base64.b64encode(raw).decode()}
        prefix = "/repos/Appz4Fun/nzbget"
        responses = {
            "/user": {"login": actor},
            prefix: {"default_branch": "dupe-article-fallback"},
            prefix + "/branches/dupe-article-fallback": {
                "commit": {"sha": current_base}, "protected": False},
            prefix + "/pulls/7": {"number": 7, "state": "open",
                "base": {"sha": current_base, "ref": "dupe-article-fallback",
                         "repo": {"full_name": "Appz4Fun/nzbget"}},
                "head": {"sha": current_head, "repo": {"full_name": head_repository},
                         "ref": "codex/controlled-contract"}},
            prefix + "/commits/" + evidence_sha: {
                "sha": evidence_sha, "author": {"login": "xbmc4lyfe"},
                "committer": {"login": "xbmc4lyfe"}, "commit": {
                    "author": {"name": "xbmc4lyfe"}, "committer": {"name": "xbmc4lyfe"},
                    "verification": {"verified": True, "reason": "valid"},
                    "tree": {"sha": tree_sha}},
                "files": [{"filename": "benchmark-results/manifest.json", "status": "added"}]},
            prefix + "/git/trees/" + tree_sha + "?recursive=1": {"truncated": False, "tree": tree},
            **blobs,
        }
        responses.update(response_updates or {})
        fixture = self.work / "api-responses.json"
        fixture.write_text(json.dumps({"responses": responses,
            "allowed_status_posts": [prefix + "/statuses/" + CANDIDATE_SHA] if allow_status_posts else []}),
            encoding="utf-8")
        script = PUBLISHER_ROOT / "scripts/bench/publish.py"
        self.assertTrue(script.is_file(), f"Publisher dependency missing: {script}")
        arguments = ["--github-output", str(self.github_output)]
        if cli_arguments is not None:
            arguments += cli_arguments
        elif identity_only:
            arguments += ["--verify-identity-only"]
        else:
            arguments += ["--mode", "pr", "--repository", "Appz4Fun/nzbget", "--pr", "7",
                          "--evidence-sha", evidence_sha, "--expected-base-sha", BASE_SHA,
                          "--expected-head-sha", CANDIDATE_SHA, "--controller-sha", BASE_SHA,
                          "--testbed", manifest["testbed"], "--output-dir", str(self.output)]
        if publish:
            arguments.append("--publish")
        env = {"PATH": os.environ.get("PATH", ""), "BENCH_GITHUB_TOKEN": "controlled-no-network-canary",
               "BENCH_GITHUB_ACTOR": "xbmc4lyfe", "GITHUB_ACTOR": "xbmc4lyfe"}
        result = subprocess.run([sys.executable, "-I", "-c", PUBLISHER_TRANSPORT,
                                 str(script), str(fixture), str(self.journal), *arguments],
                                env=env, capture_output=True, text=True, timeout=30)
        calls = self.api_calls()
        if not allow_status_posts:
            self.assertTrue(all(call["method"] == "GET" for call in calls),
                            "Rejected artifacts/identity must never trigger authenticated writes")
        self.assertNotIn("controlled-no-network-canary", result.stdout + result.stderr)
        return result

    def api_calls(self):
        return [json.loads(line) for line in self.journal.read_text().splitlines()] if self.journal.exists() else []

    def rejected(self, **kwargs):
        result = self.invoke(**kwargs)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("ready=false", self.github_output.read_text())
        qualification = self.output / "qualification.json"
        if qualification.exists():
            self.assertEqual(json.loads(qualification.read_text())["status"], "HOLD",
                             "Stale identities cannot produce publishable qualification")
        self.assertFalse((self.output / "selected-bencher.json").exists(),
                         "Rejected identities must clear prior publication metrics")

    def test_stale_manifest_base_is_rejected(self):
        manifest = controlled_manifest()
        manifest["base_sha"] = "9" * 40
        self.rejected(manifest=manifest)

    def test_stale_manifest_candidate_is_rejected(self):
        manifest = controlled_manifest()
        manifest["candidate_sha"] = "9" * 40
        self.rejected(manifest=manifest)

    def test_pr_that_advanced_after_collection_is_rejected(self):
        self.rejected(current_head="9" * 40)

    def test_canonical_branch_that_advanced_after_collection_is_rejected(self):
        self.rejected(current_base="9" * 40)

    def test_stale_pr_clears_previous_pass_and_publication_metrics(self):
        self.output.mkdir()
        (self.output / "qualification.json").write_text('{"status":"PASS"}')
        (self.output / "selected-bencher.json").write_text('{"old":{}}')
        self.rejected(current_head="9" * 40)

    def test_environment_actor_cannot_override_token_identity(self):
        self.rejected(actor="github-actions[bot]", identity_only=True)

    def lifecycle_arguments(self, intent="manual"):
        arguments = ["--set-pr-status", "pending", "--status-intent", intent,
                     "--repository", "Appz4Fun/nzbget", "--pr", "7", "--controller-sha", BASE_SHA]
        if intent == "manual":
            arguments += ["--expected-head-sha", CANDIDATE_SHA]
        return arguments

    def test_lifecycle_invalid_proof_posts_pending_before_read_then_failure(self):
        result = self.invoke(raw_manifest=b"not valid JSON\n", publish=True, allow_status_posts=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        calls = self.api_calls()
        writes = [call for call in calls if call["method"] == "POST"]
        self.assertEqual([call["payload"]["state"] for call in writes], ["pending", "failure"])
        self.assertEqual([call["payload"]["description"] for call in writes],
                         ["Pending base:" + BASE_SHA, "HOLD base:" + BASE_SHA])
        evidence_read = next(index for index, call in enumerate(calls)
                             if call["endpoint"] == "/repos/Appz4Fun/nzbget/commits/" + "3" * 40)
        self.assertLess(calls.index(writes[0]), evidence_read)
        self.assertLess(evidence_read, calls.index(writes[1]))
        self.assertIn("published=false", self.github_output.read_text())
        self.assertNotIn("published=true", self.github_output.read_text())

    def test_lifecycle_stale_base_success_is_invalidated_to_pending(self):
        endpoint = "/repos/Appz4Fun/nzbget/commits/" + CANDIDATE_SHA + "/statuses?per_page=100&page=1"
        prior = {"context": "paired caller qualification", "state": "success",
                 "creator": {"login": "xbmc4lyfe"}, "description": "PASS base:" + "9" * 40}
        result = self.invoke(cli_arguments=self.lifecycle_arguments("automatic"),
                             response_updates={endpoint: [prior]}, allow_status_posts=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = [call for call in self.api_calls() if call["method"] == "POST"]
        self.assertEqual([call["payload"] for call in writes], [{"state": "pending",
            "context": "paired caller qualification", "description": "Pending base:" + BASE_SHA}])
        self.assertIn("status_written=true", self.github_output.read_text())

    def test_lifecycle_current_base_success_is_preserved_without_write(self):
        endpoint = "/repos/Appz4Fun/nzbget/commits/" + CANDIDATE_SHA + "/statuses?per_page=100&page=1"
        prior = {"context": "paired caller qualification", "state": "success",
                 "creator": {"login": "xbmc4lyfe"}, "description": "PASS base:" + BASE_SHA}
        result = self.invoke(cli_arguments=self.lifecycle_arguments("automatic"),
                             response_updates={endpoint: [prior]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status_written=false", self.github_output.read_text())
        self.assertIn("status=skip_current_pass", self.github_output.read_text())

    def test_lifecycle_wrong_actor_moved_head_and_fork_cannot_write(self):
        cases = ({"actor": "github-actions[bot]"}, {"current_head": "9" * 40},
                 {"head_repository": "controlled-fork/nzbget"})
        for index, controls in enumerate(cases):
            with self.subTest(controls=controls):
                self.journal = self.work / f"guard-calls-{index}.jsonl"
                result = self.invoke(cli_arguments=self.lifecycle_arguments(), **controls)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(self.api_calls(), "Guard must inspect live API identity, not fail argument parsing")
                self.assertTrue(all(call["method"] == "GET" for call in self.api_calls()))

    def test_lifecycle_pr_discovery_rejects_more_than_256_targets(self):
        responses = {}
        for page, count in ((1, 100), (2, 100), (3, 57)):
            rows = [{"number": (page - 1) * 100 + index + 1, "state": "open",
                     "base": {"sha": BASE_SHA, "ref": "dupe-article-fallback",
                              "repo": {"full_name": "Appz4Fun/nzbget"}},
                     "head": {"sha": CANDIDATE_SHA, "repo": {"full_name": "Appz4Fun/nzbget"}}}
                    for index in range(count)]
            responses[f"/repos/Appz4Fun/nzbget/pulls?state=open&base=dupe-article-fallback&per_page=100&page={page}"] = rows
        result = self.invoke(cli_arguments=["--list-prs", "--repository", "Appz4Fun/nzbget",
                                            "--controller-sha", BASE_SHA], response_updates=responses)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(any(call["endpoint"].endswith("&page=3") for call in self.api_calls()))
        self.assertNotIn("prs=", self.github_output.read_text())

    def reviewed_inputs(self, first_port=False):
        manifest = controlled_manifest()
        variants = VARIANTS
        decision = "required"
        if first_port:
            variants = tuple(variant for variant in VARIANTS if variant != "rust_current")
            decision = "not_applicable"
            manifest["fixtures"][0].update(required_variants=list(variants),
                rust_preservation_applicability=decision, provenance={
                    "rust_preservation_rationale": "Synthetic first-port fixture declares only C++ controls and its first Rust candidate."})
        manifest_raw = json.dumps(manifest).encode()
        samples_raw = "".join(json.dumps(row) + "\n" for row in controlled_rows(variants=variants)).encode()
        return manifest_raw, samples_raw, synthetic_receipt(manifest_raw, samples_raw, variants, decision)

    def validate_reviewed(self, manifest_raw, samples_raw, receipt, status):
        result = self.invoke(raw_manifest=manifest_raw, raw_samples=samples_raw,
                             raw_receipt=json.dumps(receipt).encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        qualification = json.loads((self.output / "qualification.json").read_text())
        self.assertEqual(qualification["status"], status)
        self.assertEqual(qualification["collection_provenance"]["receipt_valid"], status == "PASS")
        self.assertIs(qualification["collection_provenance"]["signature_attests_execution"], False)
        return qualification

    def test_publisher_invalid_proof_retains_raw_transport_bytes(self):
        raw = {"manifest.json": b"not valid JSON\n", "samples.jsonl": b"unparsed synthetic samples\n",
               "collection-receipt.json": b'{"synthetic":"unparsed receipt"}\n'}
        result = self.invoke(raw_manifest=raw["manifest.json"], raw_samples=raw["samples.jsonl"],
                             raw_receipt=raw["collection-receipt.json"])
        self.assertEqual(result.returncode, 2, result.stderr)
        for name, original in raw.items():
            self.assertTrue((self.output / name).is_file(), "Invalid import discarded signed transport bytes")
            self.assertEqual((self.output / name).read_bytes(), original)
        self.assertEqual(json.loads((self.output / "qualification.json").read_text())["status"], "HOLD")
        self.assertNotIn("published=true", self.github_output.read_text())

    def test_publisher_raw_output_reuse_preserves_prior_bytes_and_invalidates_pass(self):
        self.output.mkdir()
        prior = {name: ("synthetic prior raw proof: " + name).encode() for name in RAW_PROOF_FILES}
        for name, raw in prior.items():
            (self.output / name).write_bytes(raw)
        (self.output / "qualification.json").write_text('{"status":"PASS"}')
        (self.output / "selected-bencher.json").write_text('{"old":{}}')
        result = self.invoke(raw_manifest=b"invalid new proof\n", raw_samples=b"new samples\n",
                             raw_receipt=b'{"synthetic":"new receipt"}')
        self.assertEqual(result.returncode, 2, result.stderr)
        for name, raw in prior.items():
            self.assertTrue((self.output / name).is_file(), "Rejected reuse discarded prior raw evidence")
            self.assertEqual((self.output / name).read_bytes(), raw)
        self.assertEqual(json.loads((self.output / "qualification.json").read_text())["status"], "HOLD")
        self.assertFalse((self.output / "selected-bencher.json").exists())
        self.assertFalse(any("/git/blobs/" in call["endpoint"] for call in self.api_calls()),
                         "Retained proof must block a new import before blob acquisition")

    def test_publisher_explicit_reviewed_required_and_first_port_are_eligible(self):
        for first_port in (False, True):
            with self.subTest(first_port=first_port):
                self.output = self.work / f"reviewed-positive-{first_port}"
                self.validate_reviewed(*self.reviewed_inputs(first_port), "PASS")
                self.assertIn("ready=true", self.github_output.read_text())

    def test_publisher_changed_source_content_same_checkout_requires_new_review(self):
        manifest, samples, receipt = self.reviewed_inputs()
        self.validate_reviewed(manifest, samples, receipt, "PASS")
        self.output = self.work / "changed-content"
        changed = copy.deepcopy(receipt)
        changed["source_content_hashes"]["rust_candidate"] = hashlib.sha256(b"synthetic edited source, same Git checkout").hexdigest()
        self.assertEqual(changed["source_hashes"], receipt["source_hashes"])
        self.validate_reviewed(manifest, samples, changed, "HOLD")

    def test_publisher_review_maps_and_content_digests_must_match(self):
        manifest, samples, receipt = self.reviewed_inputs()
        variants = []
        missing = copy.deepcopy(receipt)
        del missing["review"]["rust_preservation_applicability"]
        variants.append(missing)
        decision = copy.deepcopy(receipt)
        decision["review"]["rust_preservation_applicability"]["controlled/caller"] = "not_applicable"
        variants.append(decision)
        digest_mismatch = copy.deepcopy(receipt)
        digest_mismatch["review"]["source_content_hashes"]["rust_candidate"] = "f" * 64
        variants.append(digest_mismatch)
        missing_capture = copy.deepcopy(receipt)
        del missing_capture["source_content_hashes"]["rust_current"]
        variants.append(missing_capture)
        invalid_digest = copy.deepcopy(receipt)
        invalid_digest["source_content_hashes"]["rust_candidate"] = "not-a-digest"
        invalid_digest["review"]["source_content_hashes"]["rust_candidate"] = "not-a-digest"
        variants.append(invalid_digest)
        for index, altered in enumerate(variants):
            with self.subTest(alteration=index):
                self.output = self.work / f"review-negative-{index}"
                self.validate_reviewed(manifest, samples, altered, "HOLD")

    def test_publisher_optional_manifest_content_hashes_must_match_receipt(self):
        manifest_raw, samples, receipt = self.reviewed_inputs()
        manifest = json.loads(manifest_raw)
        manifest["provenance"] = {"source_content_hashes": dict(receipt["source_content_hashes"])}
        manifest["provenance"]["source_content_hashes"]["rust_candidate"] = "f" * 64
        changed_manifest = json.dumps(manifest).encode()
        receipt["manifest_sha256"] = hashlib.sha256(changed_manifest).hexdigest()
        self.validate_reviewed(changed_manifest, samples, receipt, "HOLD")


class AssemblerPipelineContractTests(unittest.TestCase):
    api_calls = PublisherIdentityContractTests.api_calls

    def setUp(self):
        PublisherIdentityContractTests.setUp(self)
        # The assembler deliberately rejects symlinked output ancestors; use
        # the physical test directory on macOS as well as GNU/Linux.
        self.work = self.work.resolve()
        self.output = self.work / "published-validation"
        self.journal = self.work / "api-calls.jsonl"
        self.github_output = self.work / "github-output"
        self.receipt_output = self.work / "assembled-receipt.json"

    def collection(self, first_port=False, mixed_kernel=False):
        manifest = controlled_manifest()
        variants, decision = VARIANTS, "required"
        if first_port:
            variants = tuple(variant for variant in VARIANTS if variant != "rust_current")
            decision = "not_applicable"
            manifest["fixtures"][0].update(required_variants=list(variants),
                rust_preservation_applicability=decision, provenance={
                    "rust_preservation_rationale": "Synthetic first-port collection has no declared current Rust variant."})
        rows = controlled_rows(variants=variants)
        if mixed_kernel:
            kernel = copy.deepcopy(manifest["fixtures"][0])
            kernel.update(id="controlled/kernel", scope="kernel")
            kernel.pop("rust_preservation_applicability")
            manifest["fixtures"].append(kernel)
            rows += controlled_rows(variants=variants, case=kernel["id"])
        manifest_raw = json.dumps(manifest).encode()
        samples_raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
        assertions = synthetic_receipt(manifest_raw, samples_raw, variants, decision)
        # These are fixed, explicit synthetic approvals supplied by the test,
        # not approvals inferred from runner captures by the assembler.
        review = copy.deepcopy(assertions["review"])
        records = {"build": [], "time": []}
        bindings = {"schema_version": 1, "variants": {}, "compilers": {
            "controlled-compiler": {"phase": "build", "index": 0, "id": "tool-0"}}, "inputs": {}}
        for index, variant in enumerate(variants):
            source_sha = CANDIDATE_SHA if variant == "rust_candidate" else BASE_SHA
            for phase in ("build", "time"):
                binary = assertions["binary_hashes"][variant]
                source = assertions["source_content_hashes"][variant]
                compiler = assertions["compiler_hashes"]["controlled-compiler"]
                runner = assertions["runner"]["implementation_sha256"]
                captures = [{"id": "runner", "kind": "implementation", "sha256": runner},
                    {"id": "executable", "kind": "executable", "sha256": binary},
                    {"id": "fixture-0", "kind": "fixture", "sha256": source},
                    {"id": "fixture-1", "kind": "fixture", "sha256": INPUT_DIGEST},
                    {"id": "tool-0", "kind": "toolchain", "sha256": compiler}]
                records[phase].append({"schema_version": 1, "capture_version": 1, "mode": phase,
                    "testbed": manifest["testbed"], "lock_scope": "worker_default", "runner_sha256": runner,
                    "checkout_sha": source_sha, "checkout_sha_before": source_sha, "checkout_sha_after": source_sha,
                    "command": {"name": "controlled-caller", "sha256": binary,
                                "argv_sha256": assertions["commands"][phase][0]["argv_sha256"]},
                    "fixtures": [{"id": "fixture-0", "sha256": source}, {"id": "fixture-1", "sha256": INPUT_DIGEST}],
                    "toolchain_binaries": [{"id": "tool-0", "sha256": compiler}],
                    "captures": {"before": captures, "after": copy.deepcopy(captures)},
                    "stability": {"status": "stable", "changed_ids": [], "reason_codes": []},
                    "lock_modes": {"i7-heavy.lock": "exclusive", "nzbget-rust-benchmark.lock": "shared"}
                                  if phase == "build" else {"nzbget-rust-benchmark.lock": "exclusive"},
                    "time_prebuilt": phase == "time", "build_jobs": 3 if phase == "build" else None,
                    "command_started": True, "outcome": "completed", "exit_code": 0})
            bindings["variants"][variant] = {
                "source": {"phase": "build", "index": index, "id": "fixture-0",
                           "reason": "Explicit synthetic source archive binding, without an execution attestation."},
                "binary": {"phase": "time", "index": index, "id": "executable"}}
        for fixture in manifest["fixtures"]:
            bindings["inputs"][fixture["id"]] = [{"phase": "time", "index": index, "id": "fixture-1"}
                                                 for index in range(len(variants))]
        return {"manifest": manifest, "samples": samples_raw, "bindings": bindings,
                "review": review, "records": records}

    def assemble(self, collection):
        script = ASSEMBLER_ROOT / "scripts/bench/collect_receipt.py"
        self.assertTrue(script.is_file(), f"Assembler dependency missing: {script}")
        files = {}
        for name in ("manifest", "bindings", "review"):
            files[name] = self.work / f"assembly-{name}.json"
            files[name].write_bytes(json.dumps(collection[name]).encode())
        files["samples"] = self.work / "assembly-samples.jsonl"
        files["samples"].write_bytes(collection["samples"])
        arguments = [sys.executable, str(script), "--manifest", str(files["manifest"]),
                     "--samples", str(files["samples"]), "--bindings", str(files["bindings"]),
                     "--review-record", str(files["review"]), "--output", str(self.receipt_output)]
        for phase in ("build", "time"):
            for index, record in enumerate(collection["records"][phase]):
                path = self.work / f"assembly-{phase}-{index}.json"
                path.write_bytes(json.dumps(record).encode())
                files[f"{phase}-{index}"] = path
                arguments += ["--" + phase + "-metadata", str(path)]
        original = {path: path.read_bytes() for path in files.values()}
        result = subprocess.run(arguments, env={"PATH": os.environ.get("PATH", "")},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(original, {path: path.read_bytes() for path in files.values()})
        return result, files["manifest"].read_bytes(), files["samples"].read_bytes()

    def assert_rejected(self, collection):
        sentinel = b"synthetic prior receipt, not publication evidence\n"
        self.receipt_output.write_bytes(sentinel)
        result, _, _ = self.assemble(collection)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.receipt_output.read_bytes(), sentinel, "Failed assembly overwrote prior receipt")

    def test_assembler_required_and_first_port_receipts_reach_publisher(self):
        for first_port in (False, True):
            with self.subTest(first_port=first_port):
                collection = self.collection(first_port=first_port)
                result, manifest, samples = self.assemble(collection)
                self.assertEqual(result.returncode, 0, result.stderr)
                receipt_raw = self.receipt_output.read_bytes()
                receipt = json.loads(receipt_raw)
                variants = collection["manifest"]["fixtures"][0]["required_variants"]
                self.assertEqual(set(receipt["source_content_hashes"]), set(variants))
                self.assertEqual(receipt["source_content_hashes"], collection["review"]["source_content_hashes"])
                self.assertEqual(receipt["review"], collection["review"], "Assembler must retain the supplied full review")
                self.assertEqual(receipt["source_hashes"], {variant: CANDIDATE_SHA if variant == "rust_candidate" else BASE_SHA
                                                         for variant in variants})
                self.output = self.work / f"assembler-publisher-{first_port}"
                published = PublisherIdentityContractTests.invoke(self, raw_manifest=manifest,
                    raw_samples=samples, raw_receipt=receipt_raw)
                self.assertEqual(published.returncode, 0, published.stderr)
                qualification = json.loads((self.output / "qualification.json").read_text())
                self.assertEqual(qualification["status"], "PASS")
                self.assertIs(qualification["collection_provenance"]["signature_attests_execution"], False)

    def test_assembler_review_map_excludes_kernel_fixture(self):
        collection = self.collection(mixed_kernel=True)
        result, _, _ = self.assemble(collection)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(self.receipt_output.read_bytes())
        self.assertEqual(receipt["review"]["rust_preservation_applicability"], {"controlled/caller": "required"})
        collection["review"]["rust_preservation_applicability"]["controlled/kernel"] = "required"
        self.assert_rejected(collection)

    def test_assembler_changed_capture_same_checkout_cannot_generate_review(self):
        collection = self.collection()
        original_review = copy.deepcopy(collection["review"])
        for record in (collection["records"]["build"][-1], collection["records"]["time"][-1]):
            self.assertEqual(record["checkout_sha_before"], CANDIDATE_SHA)
            changed = hashlib.sha256(b"synthetic edited source at unchanged checkout").hexdigest()
            record["fixtures"][0]["sha256"] = changed
            for phase in ("before", "after"):
                record["captures"][phase][2]["sha256"] = changed
        self.assert_rejected(collection)
        self.assertEqual(collection["review"], original_review)

    def test_assembler_missing_capture_or_review_decision_is_rejected(self):
        for missing in ("capture", "decision"):
            with self.subTest(missing=missing):
                collection = self.collection()
                if missing == "capture":
                    record = collection["records"]["build"][-1]
                    record["fixtures"][0]["sha256"] = None
                    for phase in ("before", "after"):
                        record["captures"][phase][2]["sha256"] = None
                        record["captures"][phase][2]["error_code"] = "timeout"
                else:
                    collection["review"].pop("rust_preservation_applicability")
                self.assert_rejected(collection)


if __name__ == "__main__":
    unittest.main()
