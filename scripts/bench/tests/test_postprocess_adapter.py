"""Offline tests using the real caller headers and retained recovery rows."""
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "postprocess.py"
# Format excerpts: deadpostings evidence/c231-release-caller/load-0-0.log,
# three-rust-article-crc-20261011/cached.csv, three-rust-par-damage-20261011/
# exact-paired-samples.csv, ca1b-par-crc-batch-20261011/logs/initial-samples.csv,
# and three-rust-par-range-plan-20261011/samples.csv. These are parser fixtures,
# never measurements made by this test or qualification evidence.
DEAD = "2799.59 2789.42\n2789.2 2804.34\nobservable_digest=0 sink=0\n"
ARTICLE = ("size,pattern,sample,baseline_ns,candidate_ns,cpp_control_ns\n"
           "0,0,0,3.8518,3.844,3.851\n0,0,1,3.823,3.8292,3.8255\n")
PAR_CRC = ("count,size,sample,order,old_ns,rust_ns,optimized_ns\n"
           "0,512,0,0,1.673,5.123,1.574\n0,512,1,1,1.499,4.795,1.609\n")
PAR_DAMAGE = ("case,n,sample,baseline_ns,rust_caller_ns,cpp_sorted_ns\n"
              "sorted,0,0,2.13195,1.93708,1.70169\n")
PAR_RANGE = ("segments,runs,shape,sample,original_ns,rust_ns,cpp_lb_ns,cpp_branchless_ns\n"
             "0,1,0,0,12.1477,12.6553,12.4825,12.4192\n")


class PostprocessAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
            "testbed": "offline-parser-fixture", "toolchain": {"compiler": "fixture"},
            "fixtures": [{"id": "caller", "sha256": "c" * 64, "scope": "complete_caller"}],
            "comparison": {"baseline": "cpp_current", "candidate": "rust_candidate"},
        }))
        self.output = self.root / "out"

    def run_adapter(self, kind, text, name="raw.csv", extra=()):
        source = self.root / name
        source.write_text(text)
        result = subprocess.run([
            sys.executable, str(ADAPTER), "--format", kind, "--manifest", str(self.manifest),
            "--source", str(source), "--output-dir", str(self.output), *extra,
        ], capture_output=True, text=True)
        return result, source

    def evidence(self):
        return json.loads((self.output / "adapter-evidence.json").read_text())

    def assert_invalid(self, kind, text, name="raw.csv"):
        result, _ = self.run_adapter(kind, text, name)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.output.exists(), "invalid proof must leave no outputs")

    def test_legacy_article_keeps_slower_rows_and_empty_call(self):
        result, source = self.run_adapter("article-crc", ARTICLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.evidence()
        self.assertEqual(evidence["status"], "HOLD")
        rows = evidence["sources"][0]["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["raw"]["candidate_ns"], "3.8292")
        self.assertEqual(rows[0]["phase"], "empty_call")
        self.assertEqual(evidence["sources"][0]["text"], ARTICLE)
        self.assertEqual(evidence["sources"][0]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual((self.output / "samples.jsonl").read_text(), "")
        self.assertEqual(json.loads((self.output / "bencher.json").read_text()), {})
        self.assertEqual(json.loads((self.output / "qualification.json").read_text())["status"], "HOLD")

    def test_deadpostings_does_not_promote_numeric_digest(self):
        result, _ = self.run_adapter("deadpostings", DEAD, "load-0-0.log")
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.evidence()["sources"][0]
        self.assertEqual(source["observable_digest_u64"], "0")
        self.assertEqual(len(source["rows"]), 2)
        self.assertEqual(source["rows"][1]["phase"], "initialization")
        self.assertNotIn("observable_digest", source["rows"][0])

    def test_all_par_controls_and_nonpassing_samples_survive(self):
        for kind, text in (("par-crc", PAR_CRC), ("par-damage", PAR_DAMAGE), ("par-range", PAR_RANGE)):
            with self.subTest(kind=kind):
                self.output = self.root / kind
                result, _ = self.run_adapter(kind, text)
                self.assertEqual(result.returncode, 0, result.stderr)
                source = self.evidence()["sources"][0]
                self.assertEqual(source["text"], text)
                self.assertEqual(source["rows"][0]["status"], "HOLD")
                self.assertTrue(any("cpp" in key or "optimized" in key for key in source["rows"][0]["raw"]))

    def test_nonzero_work_has_separate_throughput_phase(self):
        text = ARTICLE + "4096,0,0,100,200,90\n"
        result, _ = self.run_adapter("article-crc", text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r["phase"] for r in self.evidence()["sources"][0]["rows"]],
                         ["empty_call", "empty_call", "throughput"])

    def test_aggregate_deadpostings_summary_is_hold_only(self):
        text = '[{"records":0,"samples":45,"cpp_ns":2874.9,"rust_ns":2896.99,"change_percent":0.7683745521583241,"paired_rust_faster":21}]\n'
        result, _ = self.run_adapter("deadpostings-summary", text, "summary.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.evidence()["sources"][0]["text"], text)
        self.assertEqual((self.output / "samples.jsonl").read_text(), "")

    def test_plain_article_header_without_control_is_retained(self):
        self.assertEqual(self.run_adapter("article-crc", "size,pattern,sample,baseline_ns,candidate_ns\n0,0,0,4.2179,4.0598\n")[0].returncode, 0)

    def test_missing_column_rejected(self):
        self.assert_invalid("par-crc", PAR_CRC.replace(",optimized_ns", "").replace(",1.574", "").replace(",1.609", ""))

    def test_duplicate_sample_rejected(self):
        self.assert_invalid("article-crc", ARTICLE + ARTICLE.splitlines()[1] + "\n")

    def test_nonfinite_negative_or_zero_latency_rejected(self):
        for value in ("NaN", "Infinity", "-1", "0"):
            with self.subTest(value=value):
                self.assert_invalid("article-crc", ARTICLE.replace("3.8518", value))

    def test_malformed_deadpostings_trailer_rejected(self):
        self.assert_invalid("deadpostings", DEAD + "unexpected output\n", "load-0-0.log")

    def test_deadpostings_missing_trailer_is_retained_as_hold(self):
        result, _ = self.run_adapter("deadpostings", DEAD.split("observable_digest")[0], "load-0-0.log")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("digest" in reason for reason in self.evidence()["reasons"]))

    def test_duplicate_json_keys_rejected(self):
        self.assert_invalid("deadpostings-summary", '[{"records":0,"records":1}]', "summary.json")

    def test_no_samples_rejected(self):
        self.assert_invalid("article-crc", ARTICLE.splitlines()[0] + "\n")

    def test_invalid_rerun_clears_generated_stale_pass(self):
        self.output.mkdir()
        sentinel = self.output / "qualification.json"
        sentinel.write_text("PASS-from-older-run")
        keep = self.output / "user-notes.txt"
        keep.write_text("keep")
        result, _ = self.run_adapter("article-crc", ARTICLE.replace("3.8518", "NaN"))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(sentinel.exists())
        self.assertEqual(keep.read_text(), "keep")

    def test_input_inside_output_rejected_without_mutation(self):
        self.output.mkdir()
        sentinel = self.output / "qualification.json"
        sentinel.write_text(ARTICLE)
        result = subprocess.run([sys.executable, str(ADAPTER), "--format", "article-crc",
                                 "--manifest", str(self.manifest), "--source", str(sentinel),
                                 "--output-dir", str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), ARTICLE)

    def test_output_symlink_to_source_rejected_without_mutation(self):
        self.output.mkdir()
        source = self.root / "input.csv"
        source.write_text(ARTICLE)
        sentinel = self.output / "qualification.json"
        sentinel.symlink_to(source)
        result, _ = self.run_adapter("article-crc", ARTICLE, "input.csv")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(sentinel.is_symlink())
        self.assertEqual(source.read_text(), ARTICLE)

    def test_output_hardlink_to_source_rejected_without_mutation(self):
        self.output.mkdir()
        source = self.root / "input.csv"
        source.write_text(ARTICLE)
        sentinel = self.output / "qualification.json"
        os.link(source, sentinel)
        result, _ = self.run_adapter("article-crc", ARTICLE, "input.csv")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), ARTICLE)
        self.assertTrue(sentinel.samefile(source))

    def test_dangling_input_symlink_in_output_is_never_unlinked(self):
        for spelling in ("direct", "dotdot", "output-directory-symlink"):
            with self.subTest(spelling=spelling):
                physical = self.root / spelling / "physical"
                physical.mkdir(parents=True)
                output = physical
                if spelling == "output-directory-symlink":
                    output = self.root / spelling / "out-link"
                    output.symlink_to(physical, target_is_directory=True)
                sentinel = physical / "qualification.json"
                sentinel.symlink_to(self.root / "missing-external-target")
                source = output / "qualification.json"
                if spelling == "dotdot":
                    source = output / ".." / "physical" / "qualification.json"
                result = subprocess.run([sys.executable, str(ADAPTER), "--format", "article-crc",
                                         "--manifest", str(self.manifest), "--source", str(source),
                                         "--output-dir", str(output)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(sentinel.is_symlink(), "alias rejection must preserve the input symlink")
                self.assertEqual(sentinel.readlink(), self.root / "missing-external-target")

    def test_input_parent_directory_symlink_is_preserved_on_rejected_import(self):
        for output_route in ("direct", "alias"):
            for input_kind in ("source", "metadata"):
                with self.subTest(output_route=output_route, input_kind=input_kind):
                    case = self.root / f"{output_route}-{input_kind}"
                    case.mkdir()
                    physical_output = case / "out"
                    physical_output.mkdir()
                    external = case / "external"
                    external.mkdir()
                    immutable = external / ("samples.csv" if input_kind == "source" else "metadata.json")
                    text = "bad,header\n" if input_kind == "source" else '{"historical":true}\n'
                    immutable.write_text(text)
                    ancestor = physical_output / "manifest.json"
                    ancestor.symlink_to(external, target_is_directory=True)
                    output = physical_output
                    if output_route == "alias":
                        output = case / "output-alias"
                        output.symlink_to(physical_output, target_is_directory=True)
                    source = ancestor / immutable.name if input_kind == "source" else case / "invalid.csv"
                    metadata = ancestor / immutable.name if input_kind == "metadata" else case / "metadata.json"
                    if input_kind == "metadata":
                        source.write_text("bad,header\n")
                    else:
                        metadata.write_text('{"historical":true}\n')
                    result = subprocess.run([sys.executable, str(ADAPTER), "--format", "article-crc",
                                             "--manifest", str(metadata), "--source", str(source),
                                             "--output-dir", str(output)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertTrue(ancestor.is_symlink(), "immutable input ancestors must survive rejection")
                    self.assertEqual(immutable.read_text(), text)

    def test_repeat_hold_run_replaces_only_generated_outputs(self):
        self.assertEqual(self.run_adapter("article-crc", ARTICLE)[0].returncode, 0)
        result, _ = self.run_adapter("par-crc", PAR_CRC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.evidence()["format"], "par-crc")
        self.assertEqual((self.output / "samples.jsonl").read_text(), "")

    def test_hostile_manifest_types_rejected(self):
        for updates in ({"comparison": {"baseline": [], "candidate": "rust_candidate"}},
                        {"fixtures": [{"id": "x", "sha256": "a" * 64, "scope": {}}]}):
            with self.subTest(updates=updates):
                original = json.loads(self.manifest.read_text())
                original.update(updates)
                self.manifest.write_text(json.dumps(original))
                self.assert_invalid("v1", '{"case":"caller"}\n', "samples.jsonl")

    def test_partial_historical_metadata_archives_all_legacy_rows_under_hold(self):
        metadata_text = '{"historical":true}\n'
        self.manifest.write_text(metadata_text)
        result, _ = self.run_adapter("article-crc", ARTICLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.evidence()
        self.assertEqual(evidence["status"], "HOLD")
        self.assertEqual(evidence["artifact_kind"], "legacy_hold_archive")
        self.assertEqual(evidence["legacy_metadata"]["text"], metadata_text)
        self.assertEqual(evidence["legacy_metadata"]["sha256"], hashlib.sha256(metadata_text.encode()).hexdigest())
        self.assertEqual(evidence["sources"][0]["text"], ARTICLE)
        self.assertEqual(len(evidence["sources"][0]["rows"]), 2)
        self.assertEqual(json.loads((self.output / "legacy-metadata.json").read_text()), {"historical": True})
        self.assertFalse((self.output / "manifest.json").exists(), "legacy metadata must not impersonate a v1 manifest")
        qualification = json.loads((self.output / "qualification.json").read_text())
        self.assertEqual(qualification["status"], "HOLD")
        for key in ("schema_version", "base_sha", "candidate_sha", "testbed", "fixtures"):
            self.assertNotIn(key, qualification, "unknown historical identities must remain absent")
        self.assertEqual((self.output / "samples.jsonl").read_text(), "")

    def test_empty_historical_metadata_stays_hold_and_native_stays_strict(self):
        self.manifest.write_text('{}')
        result, _ = self.run_adapter("par-crc", PAR_CRC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.output = self.root / "native-rejected"
        self.assert_invalid("v1", '{"case":"caller"}\n', "samples.jsonl")

    def test_legacy_retains_only_supplied_identity_assertions(self):
        self.manifest.write_text(json.dumps({"base_sha": "a" * 40, "historical": True}))
        result, _ = self.run_adapter("par-damage", PAR_DAMAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        qualification = json.loads((self.output / "qualification.json").read_text())
        self.assertEqual(qualification["base_sha"], "a" * 40)
        self.assertNotIn("candidate_sha", qualification)
        self.assertNotIn("testbed", qualification)

    def test_legacy_rerun_removes_stale_v1_manifest(self):
        self.output.mkdir()
        (self.output / "manifest.json").write_text('{"old":"v1"}')
        self.manifest.write_text('{"historical":true}')
        result, _ = self.run_adapter("article-crc", ARTICLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertTrue((self.output / "legacy-metadata.json").exists())

    def test_overflowing_json_number_rejected(self):
        self.assert_invalid("deadpostings-summary", '[{"records":0,"samples":45,"cpp_ns":1e999,"rust_ns":1}]')

    def test_manifest_size_bound(self):
        self.manifest.write_text(" " * (1024 * 1024 + 1))
        self.assert_invalid("article-crc", ARTICLE)

    def test_source_size_bound(self):
        self.assert_invalid("article-crc", " " * (32 * 1024 * 1024 + 1))

    def test_missing_source_rejected(self):
        result = subprocess.run([sys.executable, str(ADAPTER), "--format", "article-crc",
                                 "--manifest", str(self.manifest), "--source", str(self.root / "missing.csv"),
                                 "--output-dir", str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_row_budget_rejected_before_outputs(self):
        spec = importlib.util.spec_from_file_location("postprocess_budget_fixture", ADAPTER)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        adapter.MAX_ROWS = 1
        with self.assertRaisesRegex(adapter.EvidenceError, "rows"):
            adapter.csv_rows("article-crc", {"name": "fixture.csv", "text": ARTICLE})

    def test_reviewed_metadata_preserved_with_hash(self):
        metadata = self.root / "metadata.json"
        metadata.write_text('{"compiler":"g++ fixture","source_sha256":{"caller.cpp":"' + "d" * 64 + '"}}')
        result, _ = self.run_adapter("article-crc", ARTICLE, extra=("--metadata", str(metadata)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.evidence()["metadata"][0]["text"], metadata.read_text())
        self.assertEqual(self.evidence()["metadata"][0]["sha256"], hashlib.sha256(metadata.read_bytes()).hexdigest())

    def test_v1_without_shared_validator_fails_closed(self):
        isolated = self.root / "without-validator/scripts/bench/adapters"
        isolated.mkdir(parents=True)
        shutil.copyfile(ADAPTER, isolated / "postprocess.py")
        source = self.root / "samples.jsonl"
        source.write_text('{"case":"caller"}\n')
        result = subprocess.run([sys.executable, str(isolated / "postprocess.py"), "--format", "v1",
                                 "--manifest", str(self.manifest), "--source", str(source),
                                 "--output-dir", str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("requires the shared", result.stderr)
        self.assertFalse(self.output.exists())

    def native_rows(self):
        if not (ADAPTER.parents[1] / "summarize.py").exists():
            self.skipTest("requires the sibling shared validator; exercised in integration copy")
        return [{"case": "caller", "variant": variant, "process": 0, "round": 0, "order": order,
                 "elapsed_ns": elapsed, "iterations": 2, "observable_digest": "d" * 64}
                for order, (variant, elapsed) in enumerate((("cpp_current", 100), ("rust_candidate", 90)))]

    def test_native_valid_but_insufficient_raw_proof_is_hold_with_real_hashes(self):
        rows = self.native_rows()
        text = "".join(json.dumps(r) + "\n" for r in rows)
        result, _ = self.run_adapter("v1", text, "samples.jsonl")
        self.assertEqual(result.returncode, 0, result.stderr)
        qualification = json.loads((self.output / "qualification.json").read_text())
        self.assertEqual(qualification["status"], "HOLD")
        self.assertEqual(len((self.output / "samples.jsonl").read_text().splitlines()), 2)
        for field, file in (("manifest_sha256", "manifest.json"), ("samples_sha256", "samples.jsonl")):
            self.assertEqual(qualification["input_hashes"][field],
                             hashlib.sha256((self.output / file).read_bytes()).hexdigest())
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertIn("insufficient_processes", summary["cases"][0]["reasons"])
        self.assertIn("Numerical qualification: **HOLD**", (self.output / "report.md").read_text())

    def test_native_mismatched_observable_digest_rejected(self):
        rows = self.native_rows()
        rows[1]["observable_digest"] = "e" * 64
        self.assert_invalid("v1", "".join(json.dumps(r) + "\n" for r in rows), "samples.jsonl")

    def test_native_duplicate_or_partial_blocks_rejected(self):
        rows = self.native_rows()
        for added in (rows[0], {**rows[0], "round": 1}):
            with self.subTest(added=added):
                self.assert_invalid("v1", "".join(json.dumps(r) + "\n" for r in [*rows, added]), "samples.jsonl")

    def test_native_kernel_cannot_qualify_runtime(self):
        rows = self.native_rows()
        manifest = json.loads(self.manifest.read_text())
        manifest["fixtures"][0]["scope"] = "kernel"
        self.manifest.write_text(json.dumps(manifest))
        result, _ = self.run_adapter("v1", "".join(json.dumps(r) + "\n" for r in rows), "samples.jsonl")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertIn("kernel_cannot_qualify_runtime", summary["cases"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
