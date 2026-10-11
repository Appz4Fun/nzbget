#!/usr/bin/env python3
"""Offline producer tests use explicitly synthetic recorded metadata, never runs."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "collect_receipt.py"
BASE, HEAD = "1" * 40, "2" * 40
RUNNER, CPP, RUST, TOOL, SOURCE, INPUT = [c * 64 for c in "abcdef"]

def encoded(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()

def metadata(mode, source=BASE, binary=CPP):
    captures = [{"id": "runner", "kind": "implementation", "sha256": RUNNER},
                {"id": "executable", "kind": "executable", "sha256": binary},
                {"id": "fixture-0", "kind": "fixture", "sha256": SOURCE},
                {"id": "fixture-1", "kind": "fixture", "sha256": INPUT},
                {"id": "tool-0", "kind": "toolchain", "sha256": TOOL}]
    return {"schema_version": 1, "capture_version": 1, "mode": mode,
            "testbed": "synthetic-worker", "lock_scope": "worker_default",
            "runner_sha256": RUNNER, "checkout_sha": source,
            "checkout_sha_before": source, "checkout_sha_after": source,
            "command": {"name": "synthetic-caller", "sha256": binary, "argv_sha256": "9" * 64},
            "fixtures": [{"id": "fixture-0", "sha256": SOURCE}, {"id": "fixture-1", "sha256": INPUT}],
            "toolchain_binaries": [{"id": "tool-0", "sha256": TOOL}],
            "captures": {"before": captures, "after": copy.deepcopy(captures)},
            "stability": {"status": "stable", "changed_ids": [], "reason_codes": []},
            "lock_modes": {"i7-heavy.lock": "exclusive", "nzbget-rust-benchmark.lock": "shared"} if mode == "build" else {"nzbget-rust-benchmark.lock": "exclusive"},
            "time_prebuilt": mode == "time", "build_jobs": 3 if mode == "build" else None,
            "command_started": True, "outcome": "completed", "exit_code": 0}

def reference(phase, index, record):
    return {"phase": phase, "index": index, "id": record}

class CollectReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"schema_version": 1, "base_sha": BASE, "candidate_sha": HEAD,
                         "testbed": "synthetic-worker", "toolchain": {"label": "synthetic"},
                         "comparison": {"baseline": "cpp_current", "candidate": "rust_candidate"},
                         "fixtures": [{"id": "caller", "sha256": INPUT, "scope": "complete_caller"}]}
        self.samples = b'{"synthetic_only":true}\n'
        self.builds = [metadata("build"), metadata("build", HEAD, RUST)]
        self.times = [metadata("time"), metadata("time", HEAD, RUST)]
        self.bindings = {"schema_version": 1, "variants": {}, "compilers": {"c++": reference("build", 0, "tool-0")},
                         "inputs": {"caller": [reference("time", 0, "fixture-1"), reference("time", 1, "fixture-1")]}}
        for index, variant in enumerate(("cpp_current", "rust_candidate")):
            source = reference("build", index, "fixture-0")
            source["reason"] = "Synthetic source archive binding; not execution attestation"
            self.bindings["variants"][variant] = {"source": source, "binary": reference("time", index, "executable")}
        self.review = {"actor": "xbmc4lyfe", "status": "reviewed"}
        self.output = self.root / "receipt.json"

    def write(self, name, value):
        path = self.root / name
        path.write_bytes(value if isinstance(value, bytes) else encoded(value))
        return path

    def arguments(self):
        args = [sys.executable, str(SCRIPT), "--manifest", str(self.write("manifest.json", self.manifest)),
                "--samples", str(self.write("samples.jsonl", self.samples)),
                "--bindings", str(self.write("bindings.json", self.bindings)),
                "--review-record", str(self.write("review.json", self.review)),
                "--output", str(self.output)]
        for phase, records in (("build", self.builds), ("time", self.times)):
            for index, record in enumerate(records):
                args += ["--" + phase + "-metadata", str(self.write(f"{phase}-{index}.json", record))]
        return args

    def run_cli(self):
        return subprocess.run(self.arguments(), capture_output=True, text=True)

    def rejected(self):
        self.output.write_bytes(b"existing receipt\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.output.read_bytes(), b"existing receipt\n")
        self.assertNotIn(str(self.root), result.stderr)
        self.assertEqual(list(self.root.glob(".receipt-*")), [])

    def test_assembles_only_captured_named_facts_and_raw_byte_hashes(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(self.output.read_bytes())
        self.assertEqual(receipt["source_hashes"], {"cpp_current": BASE, "rust_candidate": HEAD})
        self.assertEqual(receipt["binary_hashes"], {"cpp_current": CPP, "rust_candidate": RUST})
        self.assertEqual(receipt["compiler_hashes"], {"c++": TOOL})
        self.assertEqual(receipt["input_hashes"], {"caller": INPUT})
        self.assertEqual(receipt["manifest_sha256"], hashlib.sha256(encoded(self.manifest)).hexdigest())
        self.assertEqual(receipt["samples_sha256"], hashlib.sha256(self.samples).hexdigest())
        self.assertEqual(receipt["runner"]["implementation_sha256"], RUNNER)
        self.assertEqual(receipt["runner"]["lock_scope"], "worker_default")
        self.assertEqual(receipt["commands"]["time"][1], self.times[1]["command"])
        self.assertEqual(set(receipt["commands"]["time"][0]), {"name", "sha256", "argv_sha256"})
        self.assertEqual(receipt["review"], self.review)

    def test_changed_or_unavailable_captures_cannot_be_called_stable(self):
        for value in ("0" * 64, None):
            with self.subTest(value=value):
                self.times[0]["captures"]["after"][1]["sha256"] = value
                self.rejected()
        self.times[0]["captures"]["after"][1]["sha256"] = CPP
        self.times[0]["stability"]["status"] = "changed"
        self.rejected()

    def test_failed_unstarted_and_legacy_records_never_become_ready(self):
        changes = ({"command_started": False}, {"outcome": "timeout"}, {"exit_code": 76},
                   {"capture_version": None}, {"lock_scope": "test_override"})
        for change in changes:
            with self.subTest(change=change):
                original = copy.deepcopy(self.times[0])
                self.times[0].update(change)
                self.rejected()
                self.times[0] = original

    def test_invocation_and_aliases_must_equal_observed_before(self):
        for change in (lambda m: m.update(runner_sha256="0" * 64),
                       lambda m: m["command"].update(sha256="0" * 64),
                       lambda m: m["fixtures"][0].update(sha256="0" * 64),
                       lambda m: m["toolchain_binaries"][0].update(sha256="0" * 64)):
            original = copy.deepcopy(self.builds[0])
            change(self.builds[0])
            self.rejected()
            self.builds[0] = original

    def test_bindings_cannot_replace_hashes_or_source_identity(self):
        for key in ("sha256", "source_sha", "checkout_sha"):
            self.bindings["variants"]["rust_candidate"]["source"][key] = HEAD
            self.rejected()
            del self.bindings["variants"]["rust_candidate"]["source"][key]

    def test_missing_source_capture_or_recorded_revision_is_incomplete(self):
        del self.builds[1]["checkout_sha"]
        self.rejected()
        self.builds[1]["checkout_sha"] = HEAD
        self.bindings["variants"]["rust_candidate"]["source"]["id"] = "absent"
        self.rejected()

    def test_current_and_candidate_sources_match_manifest(self):
        self.builds[1]["checkout_sha"] = BASE
        self.builds[1]["checkout_sha_before"] = BASE
        self.builds[1]["checkout_sha_after"] = BASE
        self.rejected()

    def test_changed_checkout_cannot_be_called_stable(self):
        self.builds[0]["checkout_sha_after"] = HEAD
        self.rejected()

    def test_inputs_must_bind_every_selected_timed_variant(self):
        self.bindings["inputs"]["caller"].pop()
        self.rejected()

    def test_contradictory_runner_identity_testbed_locks_or_jobs_is_rejected(self):
        for change in ({"runner_sha256": "0" * 64}, {"testbed": "other"},
                       {"lock_modes": {"nzbget-rust-benchmark.lock": "shared"}},
                       {"time_prebuilt": False}):
            original = copy.deepcopy(self.times[0])
            self.times[0].update(change)
            self.rejected()
            self.times[0] = original
        self.builds[0]["build_jobs"] = 4
        self.rejected()

    def test_optimized_and_control_attribution_comes_from_capture(self):
        self.manifest["fixtures"][0].update(role="unchanged_control", required_variants=["cpp_current", "rust_candidate", "cpp_optimized"])
        self.builds.append(metadata("build", "3" * 40, "7" * 64))
        self.times.append(metadata("time", "3" * 40, "7" * 64))
        source = reference("build", 2, "fixture-0")
        source["reason"] = "Reviewed synthetic optimized source"
        self.bindings["variants"]["cpp_optimized"] = {"source": source, "binary": reference("time", 2, "executable")}
        self.bindings["inputs"]["caller"].append(reference("time", 2, "fixture-1"))
        control = reference("build", 0, "fixture-0")
        control["reason"] = "Reviewed synthetic unchanged caller source"
        self.bindings["controls"] = {"caller": control}
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(self.output.read_bytes())
        self.assertEqual(receipt["control_attribution"]["caller"], {"source_sha256": SOURCE, "reason": control["reason"]})
        self.assertEqual(receipt["variant_source_attribution"]["cpp_optimized"], {"source_sha": "3" * 40, "reason": source["reason"]})

    def test_manifest_provenance_is_bound_without_rewriting(self):
        self.manifest["provenance"] = {"binary_hashes": {"rust_candidate": "0" * 64}}
        self.rejected()

    def test_atomic_output_preserves_symlink_and_dangling_input_ancestors(self):
        self.output.symlink_to(self.root / "missing")
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        self.root.joinpath("dangling").symlink_to(self.root / "absent-dir", target_is_directory=True)
        self.output = self.root / "dangling" / "manifest.json"
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.root.joinpath("dangling").is_symlink())

    def test_output_cannot_replace_input_through_alias(self):
        self.arguments()
        self.output = self.root / "manifest.json"
        before = self.output.read_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.output.read_bytes(), before)

    def test_unknown_raw_argv_and_duplicate_capture_ids_are_rejected(self):
        self.times[0]["command"]["argv"] = ["secret-argument"]
        self.rejected()
        del self.times[0]["command"]["argv"]
        self.times[0]["captures"]["before"].append(copy.deepcopy(self.times[0]["captures"]["before"][0]))
        self.rejected()

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        args = self.arguments()
        self.root.joinpath("bindings.json").write_bytes(b'{"schema_version":1,"schema_version":1}')
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        self.root.joinpath("bindings.json").write_bytes(b'{"schema_version":NaN}')
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


    def test_existing_review_assertion_is_never_inferred(self):
        self.review = {"actor": "bot", "status": "reviewed"}
        self.rejected()
        self.review = {}
        self.rejected()

    def test_hard_link_input_alias_is_preserved(self):
        args = self.arguments()
        input_path = self.root / "manifest.json"
        self.output.hardlink_to(input_path)
        before = input_path.read_bytes()
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(input_path.read_bytes(), before)
        self.assertTrue(os.path.samefile(input_path, self.output))

    def test_atomic_replace_failure_preserves_prior_output_and_cleans_only_temp(self):
        spec = importlib.util.spec_from_file_location("collect_receipt", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.output.write_bytes(b"prior output")
        with mock.patch.object(module.os, "replace", side_effect=OSError("synthetic replacement failure")):
            with self.assertRaises(OSError):
                module.save_receipt(self.output, [], {"new": "receipt"})
        self.assertEqual(self.output.read_bytes(), b"prior output")
        self.assertEqual(list(self.root.glob(".receipt-*")), [])

    def test_oversized_input_and_excessive_metadata_are_rejected(self):
        args = self.arguments()
        self.root.joinpath("manifest.json").write_bytes(b" " * (1024 * 1024 + 1))
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        args = self.arguments()
        args += ["--build-metadata", str(self.root / "build-0.json")] * 64
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX input non-read check")
    def test_excessive_metadata_is_rejected_before_opening_any_more_inputs(self):
        args = self.arguments()
        fifo = self.root / "must-not-read"
        os.mkfifo(fifo)
        args += ["--build-metadata", str(fifo)] * 64
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            self.fail("excess metadata opened a blocking input instead of rejecting the bound")
        self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX bounded-input check")
    def test_nonregular_input_is_rejected_without_blocking(self):
        args = self.arguments()
        path = self.root / "bindings.json"
        path.unlink()
        os.mkfifo(path)
        timed_out = False
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            timed_out = True
        self.assertFalse(timed_out, "producer blocked on nonregular input")
        self.assertEqual(result.returncode, 2)

    def test_json_exponent_overflow_is_rejected_even_in_unconsumed_metadata(self):
        args = self.arguments()
        path = self.root / "build-0.json"
        raw = path.read_bytes().rstrip()
        path.write_bytes(raw[:-1] + b', "unused":1e9999}')
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_valid_capture_shape_with_false_or_missing_checkout_alias_is_rejected(self):
        self.builds[0]["checkout_sha"] = None
        self.rejected()
        self.builds[0]["checkout_sha"] = BASE
        del self.builds[0]["checkout_sha_before"]
        self.rejected()

if __name__ == "__main__":
    unittest.main()
