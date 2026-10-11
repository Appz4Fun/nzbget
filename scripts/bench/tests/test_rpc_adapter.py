"""RPC evidence must never gain precision, pairing, or scope during export."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "rpc.py"


def manifest():
    return {
        "schema_version": 1,
        "base_sha": "a" * 40,
        "candidate_sha": "b" * 40,
        "testbed": "controlled-rpc-testbed",
        "toolchain": {"cxx": "controlled-test-compiler"},
        "fixtures": [{
            "id": "rpc/log-10", "sha256": "c" * 64,
            "scope": "complete_caller", "caller": "LogBinCommand::Execute",
            "required_variants": ["cpp_current", "rust_current", "rust_candidate"],
        }],
        "comparison": {"baseline": "cpp_current", "candidate": "rust_candidate"},
    }


def samples():
    # Synthetic controlled data: deliberately includes a slow candidate round.
    return [{
        "case": "rpc/log-10", "variant": variant, "process": 7,
        "round": round_no, "order": order, "elapsed_ns": elapsed,
        "iterations": 2, "observable_digest": "d" * 64,
    } for round_no, times in enumerate([(120, 180, 90), (122, 182, 900)])
        for order, (variant, elapsed) in enumerate(zip(
            ["cpp_current", "rust_current", "rust_candidate"], times))]


def jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows).encode()


class RpcAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.available = ADAPTER.is_file()
        if cls.available:
            spec = importlib.util.spec_from_file_location("rpc_adapter", ADAPTER)
            cls.adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.adapter)

    def convert(self, proof=None, source=None):
        self.assertTrue(self.available, "RPC adapter has not been implemented")
        return self.adapter.adapt(manifest() if proof is None else proof,
                                  jsonl(samples()) if source is None else source)

    def test_preserves_three_variants_raw_elapsed_and_slow_round(self):
        result = self.convert()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["samples"], samples())
        self.assertEqual(result["samples"][-1]["elapsed_ns"], 900)
        self.assertEqual(result["manifest"]["base_sha"], "a" * 40)

    def test_actual_legacy_samples_are_held_without_fabricating_rows(self):
        source = (b"list data 1541764 bytes\n"
                  b"SAMPLE|Log listing, 1000 lines|0|73411.416|27158.496\n"
                  b"SAMPLE|Log listing, 1000 lines|1|63394.914|24008.010\n")
        result = self.convert(source=source)
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["samples"], [])
        self.assertEqual(len(result["legacy_records"]), 2)
        self.assertEqual(result["legacy_records"][0]["cpp_ns_per_op"], "73411.416")
        self.assertNotIn("observable_digest", result["legacy_records"][0])
        self.assertIn("iterations", " ".join(result["reasons"]))

    def test_aggregate_tables_and_statistics_json_remain_held(self):
        for source in [b"workload\tcpp_before_ns\trust_after_ns\nLog\t12\t10\n",
                       b'[{"name":"Log","cpp_median":12,"ready_median":10}]\n',
                       b"ROW|Log, 10 lines|162.877|122.752\n"]:
            with self.subTest(source=source):
                result = self.convert(source=source)
                self.assertEqual(result["status"], "HOLD")
                self.assertEqual(result["samples"], [])

    def test_historical_evidence_needs_no_manufactured_fixture_hash(self):
        result = self.convert(proof={"historical": True},
                              source=b"SAMPLE|Log, 10 lines|0|162.877|122.752\n")
        self.assertEqual(result["status"], "HOLD")
        self.assertNotIn("base_sha", result["manifest"])
        self.assertEqual(result["manifest"], {"historical": True})

    def test_kernel_or_missing_caller_cannot_be_exported_as_complete(self):
        for change in [{"scope": "kernel", "caller": "nzbget_rs_binrpc_is_url"},
                       {"caller": "nzbget_rs_binrpc_is_url"}, {"caller": None}]:
            proof = manifest()
            proof["fixtures"][0].update(change)
            with self.subTest(change=change):
                result = self.convert(proof=proof)
                self.assertEqual(result["status"], "HOLD")
                self.assertEqual(result["samples"], [])

    def test_invalid_timing_digest_duplicate_and_partial_pair_are_rejected(self):
        mutations = []
        for field, value in [("elapsed_ns", 0), ("elapsed_ns", float("nan")),
                             ("iterations", True), ("process", -1),
                             ("variant", "cpp_before"), ("observable_digest", "wrong")]:
            rows = samples()
            rows[0][field] = value
            mutations.append(rows)
        rows = samples()
        rows[2]["observable_digest"] = "e" * 64
        mutations.append(rows)
        mutations.extend([samples() + [samples()[0]], samples()[:-1]])
        rows = samples()
        rows[1]["order"] = 0
        mutations.append(rows)
        for rows in mutations:
            with self.subTest(rows=rows):
                self.assertTrue(self.available, "RPC adapter has not been implemented")
                with self.assertRaises(ValueError):
                    self.adapter.adapt(manifest(), jsonl(rows))

    def test_duplicate_json_keys_rejected_instead_of_last_value_wins(self):
        row = json.dumps(samples()[0])
        source = (row[:-1] + ', "elapsed_ns": 8}\n').encode()
        self.assertTrue(self.available, "RPC adapter has not been implemented")
        with self.assertRaises(ValueError):
            self.adapter.adapt(manifest(), source)

    def test_missing_entire_baseline_is_hold(self):
        rows = [row for row in samples() if row["variant"] != "cpp_current"]
        result = self.convert(source=jsonl(rows))
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["samples"], rows)

    def test_recorded_kernel_caller_cannot_be_relabelled_by_manifest(self):
        rows = samples()
        rows[0]["caller"] = "nzbget_rs_binrpc_append_entry"
        self.assertTrue(self.available, "RPC adapter has not been implemented")
        with self.assertRaises(ValueError):
            self.adapter.adapt(manifest(), jsonl(rows))

    def test_cli_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            output = root / "out"
            proof.write_text(json.dumps(manifest()))
            source.write_bytes(jsonl(samples()))
            command = [sys.executable, str(ADAPTER), "--manifest", str(proof),
                       "--source", str(source), "--output-dir", str(output)]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual((output / "source.raw").read_bytes(), source.read_bytes())
            self.assertEqual((output / "source-manifest.raw").read_bytes(), proof.read_bytes())
            status = json.loads((output / "adapter-status.json").read_text())
            if (ADAPTER.parent.parent / "summarize.py").exists():
                rows = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
                self.assertEqual(rows, samples())
            else:
                self.assertEqual(status["status"], "HOLD")
                self.assertIn("summarize.py unavailable", " ".join(status["reasons"]))
                self.assertFalse((output / "samples.jsonl").exists())
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)
            self.assertEqual((output / "source.raw").read_bytes(), source.read_bytes())

    def test_invalid_cli_creates_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            proof.write_text(json.dumps(manifest()))
            source.write_text('{"case": "rpc/log-10"}\n')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(root / "out")],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((root / "out").exists())

    def test_cli_collision_never_modifies_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            proof = output / "manifest.json"
            source = root / "source.jsonl"
            proof.write_text(json.dumps(manifest()))
            source.write_bytes(jsonl(samples()))
            original = proof.read_bytes()
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(proof.read_bytes(), original)
            self.assertEqual(source.read_bytes(), jsonl(samples()))

    def test_invalid_proof_clears_previous_owned_exports_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            output = root / "out"
            output.mkdir()
            (output / "adapter-status.json").write_text('{"adapter":"rpc","status":"READY"}')
            (output / "manifest.json").write_text("stale manifest")
            (output / "samples.jsonl").write_text("stale samples")
            (output / "unrelated.txt").write_text("preserve")
            (output / "source.raw").write_text("retained original proof")
            proof.write_text(json.dumps(manifest()))
            source.write_text('{"case":"rpc/log-10"}\n')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((output / "manifest.json").exists())
            self.assertFalse((output / "samples.jsonl").exists())
            self.assertFalse((output / "adapter-status.json").exists())
            self.assertEqual((output / "unrelated.txt").read_text(), "preserve")
            self.assertEqual((output / "source.raw").read_text(), "retained original proof")

    def test_hardlinked_output_alias_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            output = root / "out"
            output.mkdir()
            proof.write_text(json.dumps(manifest()))
            source.write_bytes(jsonl(samples()))
            (output / "source.raw").hardlink_to(source)
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn("alias collision", run.stderr)
            self.assertEqual(source.read_bytes(), jsonl(samples()))

    def test_dangling_input_symlinks_inside_output_survive_rejection(self):
        for argument in ("manifest", "source"):
            with self.subTest(argument=argument), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proof = root / "proof.json"
                source = root / "source.samples"
                output = root / "out"
                output.mkdir()
                proof.write_text('{"historical":true}')
                source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                marker = output / "adapter-status.json"
                marker.write_text('{"adapter":"rpc","status":"READY"}')
                dangling = output / "manifest.json"
                dangling.symlink_to(root / "missing-external-input")
                inputs = {"manifest": proof, "source": source}
                inputs[argument] = dangling
                run = subprocess.run([sys.executable, str(ADAPTER),
                                      "--manifest", str(inputs["manifest"]),
                                      "--source", str(inputs["source"]),
                                      "--output-dir", str(output)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 2)
                self.assertTrue(dangling.is_symlink(), "input symlink was deleted by rejection cleanup")
                self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')
                self.assertIn("collision", run.stderr)

    def test_dangling_output_alias_to_external_input_survives_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.samples"
            output = root / "out"
            output.mkdir()
            proof.write_text('{"historical":true}')
            source.symlink_to(root / "missing-external-input")
            artifact = output / "manifest.json"
            artifact.symlink_to(root / "missing-external-input")
            marker = output / "adapter-status.json"
            marker.write_text('{"adapter":"rpc","status":"READY"}')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertTrue(source.is_symlink())
            self.assertTrue(artifact.is_symlink(), "aliased artifact was deleted by rejection cleanup")
            self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')
            self.assertIn("alias collision", run.stderr)

    def test_unrelated_dangling_artifact_still_allows_invalid_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            output = root / "out"
            output.mkdir()
            proof.write_text(json.dumps(manifest()))
            source.write_text('{"case":"rpc/log-10"}\n')
            artifact = output / "manifest.json"
            artifact.symlink_to(root / "unrelated-missing-file")
            marker = output / "adapter-status.json"
            marker.write_text('{"adapter":"rpc","status":"READY"}')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(marker.exists(), "unrelated dangling output bypassed invalid-proof cleanup")
            self.assertEqual(source.read_text(), '{"case":"rpc/log-10"}\n')

    def test_invalid_deep_json_clears_status_even_with_damaged_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.jsonl"
            output = root / "out"
            output.mkdir()
            (output / "adapter-status.json").write_text('{"adapter":"rpc","status":"READY"}')
            (output / "manifest.json").mkdir()
            proof.write_text(json.dumps(manifest()))
            source.write_text('{"deep":' + '[' * 2000 + '0' + ']' * 2000 + '}')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((output / "adapter-status.json").exists())

    def test_bounded_fixture_ids(self):
        for field, value in [("id", "bad\ncase"), ("id", "x" * 201)]:
            proof = manifest()
            proof["fixtures"][0][field] = value
            rows = samples()
            for row in rows:
                row["case"] = value
            self.assertTrue(self.available, "RPC adapter has not been implemented")
            with self.assertRaises(ValueError):
                self.adapter.adapt(proof, jsonl(rows))


if __name__ == "__main__":
    unittest.main()
