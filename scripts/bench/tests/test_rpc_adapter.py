"""RPC evidence must never gain precision, pairing, or scope during export."""
import importlib.util
import io
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


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
            "rust_preservation_applicability": "required",
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

    def retained_archive_alias_case(self, archive_name, topology, malformed):
        # Existing archive bytes are controlled lifecycle inputs, not measured
        # RPC proof. The current input pair is unrelated to the retained graph.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "out"
            output.mkdir()
            archive = output / archive_name
            marker = output / "adapter-status.json"
            backing_name = {"source.raw": "samples.jsonl", "source-manifest.raw": "manifest.json",
                            "legacy-evidence.json": "adapter-status.json"}[archive_name]
            intermediate = output / backing_name
            raw = b'{"adapter":"rpc","status":"READY","retained_raw":"controlled fixture"}\n'
            links = []
            marker.write_bytes(raw)
            if topology == "hardlink":
                intermediate.write_bytes(raw)
                os.link(intermediate, archive)
                backing = intermediate
            elif topology == "leaf_symlink":
                intermediate.write_bytes(raw)
                archive.symlink_to(backing_name)
                links.append((archive, archive.readlink()))
                backing = intermediate
            else:
                real = root / "real"
                real.mkdir()
                sibling = root / "retained-sibling"
                sibling.mkdir()
                backing = sibling / "raw.dat"
                backing.write_bytes(raw)
                intermediate.unlink(missing_ok=True)
                intermediate.symlink_to("../real", target_is_directory=True)
                outer = root / "outer"
                outer.symlink_to(intermediate / ".." / "retained-sibling/raw.dat")
                archive.symlink_to("../outer")
                links.extend((path, path.readlink()) for path in (intermediate, outer, archive))
            metadata = root / "current-manifest.json"
            source = root / "current-source.jsonl"
            metadata.write_text(json.dumps(manifest()))
            current_raw = b'{"malformed":' if malformed else jsonl(samples())
            source.write_bytes(current_raw)
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True, timeout=2)
            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            self.assertTrue(backing.exists(), "retained raw backing was deleted")
            self.assertEqual(backing.read_bytes(), raw, "retained raw backing bytes were deleted or rewritten")
            self.assertEqual(archive.read_bytes(), raw)
            for link, target in links:
                self.assertTrue(link.is_symlink(), "retained traversal entry was deleted")
                self.assertEqual(link.readlink(), target)
            if topology == "hardlink":
                self.assertTrue(intermediate.samefile(archive), "retained inode alias was removed")
            self.assertEqual(source.read_bytes(), current_raw)
            self.assertIn("HOLD", run.stdout + run.stderr, "unsafe import must report HOLD without overwriting retained data")

    def test_retained_archive_aliases_survive_unrelated_invalid_import(self):
        for archive_name in ("source.raw", "source-manifest.raw", "legacy-evidence.json"):
            for topology in ("leaf_symlink", "target_traversal", "hardlink"):
                with self.subTest(archive=archive_name, topology=topology):
                    self.retained_archive_alias_case(archive_name, topology, malformed=True)

    def test_retained_archive_aliases_survive_valid_hold_reimport(self):
        for archive_name in ("source.raw", "source-manifest.raw", "legacy-evidence.json"):
            for topology in ("leaf_symlink", "target_traversal", "hardlink"):
                with self.subTest(archive=archive_name, topology=topology):
                    self.retained_archive_alias_case(archive_name, topology, malformed=False)

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

    def test_input_directory_symlink_ancestors_survive_rejection(self):
        for argument in ("manifest", "source"):
            for route in ("direct", "output_alias", "dotdot"):
                with self.subTest(argument=argument, route=route), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    output = root / "out"
                    output.mkdir()
                    external = root / "external"
                    external.mkdir()
                    (external / "input.json").write_text('{"malformed":')
                    proof = root / "proof.json"
                    proof.write_text('{"historical":true}')
                    source = root / "source.samples"
                    source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    ancestor = output / "manifest.json"
                    ancestor.symlink_to(external, target_is_directory=True)
                    marker = output / "adapter-status.json"
                    marker.write_text('{"adapter":"rpc","status":"READY"}')
                    if route == "output_alias":
                        alias = root / "output-alias"
                        alias.symlink_to(output, target_is_directory=True)
                        selected = alias / "manifest.json/input.json"
                    elif route == "dotdot":
                        # The supplied route traverses the protected symlink
                        # even though lexical normalization leaves output.
                        selected = output / "manifest.json" / ".." / ".." / root.name / "external/input.json"
                    else:
                        selected = ancestor / "input.json"
                    inputs = {"manifest": proof, "source": source}
                    inputs[argument] = selected
                    run = subprocess.run([sys.executable, str(ADAPTER),
                                          "--manifest", str(inputs["manifest"]),
                                          "--source", str(inputs["source"]),
                                          "--output-dir", str(output)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 2)
                    self.assertTrue(ancestor.is_symlink(), "input ancestor link was deleted")
                    self.assertEqual((external / "input.json").read_text(), '{"malformed":')
                    self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')
                    self.assertIn("collision", run.stderr)

    def test_dangling_input_parent_symlink_survives_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            ancestor = output / "manifest.json"
            ancestor.symlink_to(root / "missing-external-directory", target_is_directory=True)
            (output / "adapter-status.json").write_text('{"adapter":"rpc","status":"READY"}')
            proof = root / "proof.json"
            proof.write_text('{"historical":true}')
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                  "--source", str(ancestor / "source.jsonl"),
                                  "--output-dir", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertTrue(ancestor.is_symlink(), "dangling input ancestor was deleted")
            self.assertIn("collision", run.stderr)

    def test_outer_symlink_targets_preserve_owned_intermediate_links(self):
        for argument in ("manifest", "source"):
            for route in ("direct", "dotdot_to_sibling"):
                with self.subTest(argument=argument, route=route), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    output = root / "out"
                    output.mkdir()
                    real = root / "real"
                    real.mkdir()
                    sibling = root / "sibling"
                    sibling.mkdir()
                    real_input = real / "input.json"
                    sibling_input = sibling / "input.json"
                    for path in (real_input, sibling_input):
                        path.write_text('{"malformed":')
                    intermediate = output / "manifest.json"
                    intermediate.symlink_to(real, target_is_directory=True)
                    target = intermediate / "input.json"
                    if route == "dotdot_to_sibling":
                        # The final input is outside the intermediate link's
                        # resolved target. Target-parent containment alone
                        # cannot detect this traversed input link.
                        target = intermediate / ".." / "sibling/input.json"
                    outer = root / "outer"
                    outer.symlink_to(target)
                    proof = root / "proof.json"
                    proof.write_text('{"historical":true}')
                    source = root / "source.samples"
                    source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    marker = output / "adapter-status.json"
                    marker.write_text('{"adapter":"rpc","status":"READY"}')
                    inputs = {"manifest": proof, "source": source}
                    inputs[argument] = outer
                    run = subprocess.run([sys.executable, str(ADAPTER),
                                          "--manifest", str(inputs["manifest"]),
                                          "--source", str(inputs["source"]),
                                          "--output-dir", str(output)], capture_output=True, text=True, timeout=1)
                    self.assertEqual(run.returncode, 2)
                    self.assertTrue(intermediate.is_symlink(), "traversed symlink target ancestor was deleted")
                    self.assertTrue(outer.is_symlink())
                    self.assertTrue(outer.exists(), "input pathname was broken by deleting its intermediate target")
                    self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')
                    self.assertEqual(real_input.read_text(), '{"malformed":')
                    self.assertEqual(sibling_input.read_text(), '{"malformed":')
                    self.assertIn("collision", run.stderr)

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

    def test_fifo_inputs_fail_within_deadline_without_mutation(self):
        for argument in ("manifest", "source"):
            for symlink in (False, True):
                with self.subTest(argument=argument, symlink=symlink), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    proof = root / "proof.json"
                    source = root / "source.samples"
                    proof.write_text('{"historical":true}')
                    source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    fifo = root / "unconnected.fifo"
                    os.mkfifo(fifo)
                    selected = fifo
                    if symlink:
                        selected = root / "fifo-alias"
                        selected.symlink_to(fifo)
                    inputs = {"manifest": proof, "source": source}
                    inputs[argument] = selected
                    command = [sys.executable, str(ADAPTER), "--manifest", str(inputs["manifest"]),
                               "--source", str(inputs["source"]), "--output-dir", str(root / "out")]
                    try:
                        run = subprocess.run(command, capture_output=True, text=True, timeout=1)
                    except subprocess.TimeoutExpired:
                        self.fail("RPC adapter blocked opening an unconnected FIFO")
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertFalse((root / "out").exists())
                    self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))
                    self.assertEqual(proof.read_text(), '{"historical":true}')
                    self.assertEqual(source.read_text(), "SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    if symlink:
                        self.assertTrue(selected.is_symlink())

    def test_directory_and_device_inputs_rejected_before_reading(self):
        for kind in ("directory", "device"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proof = root / "proof.json"
                proof.write_text('{"historical":true}')
                source = root / "source-alias"
                if kind == "directory":
                    target = root / "input-directory"
                    target.mkdir()
                else:
                    target = Path(os.devnull)
                source.symlink_to(target, target_is_directory=(kind == "directory"))
                run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof),
                                      "--source", str(source), "--output-dir", str(root / "out")],
                                     capture_output=True, text=True, timeout=1)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertFalse((root / "out").exists())
                self.assertTrue(source.is_symlink())
                self.assertIn("regular file", run.stderr)

    def test_regular_file_symlinks_preserve_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = root / "proof.json"
            source = root / "source.samples"
            proof.write_bytes(b'{"historical":true}\r\n')
            raw = b"SAMPLE|Log, 10 lines|0|162.877|122.752\r\n"
            source.write_bytes(raw)
            proof_alias = root / "proof-alias"
            source_alias = root / "source-alias"
            proof_alias.symlink_to(proof)
            source_alias.symlink_to(source)
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(proof_alias),
                                  "--source", str(source_alias), "--output-dir", str(root / "out")],
                                 capture_output=True, text=True, timeout=1)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual((root / "out/source.raw").read_bytes(), raw)
            self.assertEqual((root / "out/source-manifest.raw").read_bytes(), proof.read_bytes())
            self.assertTrue(proof_alias.is_symlink())
            self.assertTrue(source_alias.is_symlink())

    def test_rejected_nonregular_inputs_do_not_leak_descriptors(self):
        self.assertTrue(self.available, "RPC adapter has not been implemented")
        with tempfile.TemporaryDirectory() as directory:
            before = len(os.listdir("/dev/fd"))
            for _ in range(100):
                with self.assertRaises((OSError, ValueError)):
                    self.adapter.bounded_read(Path(directory), 100)
            self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_traversal_budget_precedes_resolution_and_cleanup(self):
        for argument in ("manifest", "source"):
            for budget in ("symlink", "component"):
                with self.subTest(argument=argument, budget=budget), tempfile.TemporaryDirectory() as directory:
                    self.assertTrue(self.available, "RPC adapter has not been implemented")
                    root = Path(directory).resolve()
                    output = root / "out"
                    output.mkdir()
                    marker = output / "adapter-status.json"
                    marker.write_text('{"adapter":"rpc","status":"READY"}')
                    proof = root / "proof.json"
                    proof.write_text('{"historical":true}')
                    source = root / "source.samples"
                    source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    leaf = root / "leaf"
                    leaf.write_text('{"malformed":')
                    count = 45 if budget == "symlink" else 35
                    links = [root / f"link-{i}" for i in range(count)]
                    for index, link in enumerate(links):
                        target = links[index + 1].name if index + 1 < count else leaf.name
                        if budget == "component":
                            target += "/" + "../" * 140
                        link.symlink_to(target)
                    inputs = {"manifest": proof, "source": source}
                    inputs[argument] = links[0]
                    real_readlink = os.readlink
                    calls = []

                    def counted_readlink(*args, **kwargs):
                        calls.append(args[0])
                        return real_readlink(*args, **kwargs)

                    stderr = io.StringIO()
                    with patch.object(self.adapter.os, "readlink", counted_readlink), redirect_stderr(stderr):
                        result = self.adapter.main(["--manifest", str(inputs["manifest"]),
                                                    "--source", str(inputs["source"]),
                                                    "--output-dir", str(output)])
                    self.assertEqual(result, 2)
                    self.assertLessEqual(len(calls), 40, "unbounded preliminary resolve expanded symlinks before rejecting")
                    self.assertIn(budget + " limit", stderr.getvalue())
                    self.assertTrue(all(link.is_symlink() for link in links))
                    self.assertEqual(leaf.read_text(), '{"malformed":')
                    self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')

    def test_equivalent_double_slash_inputs_survive_alias_rejection(self):
        for argument in ("manifest", "source"):
            for kind in ("dangling_leaf", "dangling_parent", "directory_parent"):
                with self.subTest(argument=argument, kind=kind), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory).resolve()
                    output = root / "out"
                    output.mkdir()
                    proof = root / "proof.json"
                    proof.write_text('{"historical":true}')
                    source = root / "source.samples"
                    source.write_text("SAMPLE|Log, 10 lines|0|162.877|122.752\n")
                    link = output / "manifest.json"
                    selected = link
                    if kind == "dangling_leaf":
                        link.symlink_to("../missing-input")
                    elif kind == "dangling_parent":
                        link.symlink_to("../missing-directory", target_is_directory=True)
                        selected = link / "input.json"
                    else:
                        real = root / "real"
                        real.mkdir()
                        (real / "input.json").write_text('{"malformed":')
                        link.symlink_to("../real", target_is_directory=True)
                        selected = link / "input.json"
                    marker = output / "adapter-status.json"
                    marker.write_text('{"adapter":"rpc","status":"READY"}')
                    inputs = {"manifest": str(proof), "source": str(source)}
                    inputs[argument] = "//" + str(selected).lstrip("/")
                    run = subprocess.run([sys.executable, str(ADAPTER),
                                          "--manifest", inputs["manifest"], "--source", inputs["source"],
                                          "--output-dir", str(output)], capture_output=True, text=True, timeout=1)
                    self.assertEqual(run.returncode, 2)
                    self.assertTrue(link.is_symlink(), "equivalent // input link was deleted")
                    self.assertEqual(marker.read_text(), '{"adapter":"rpc","status":"READY"}')
                    self.assertIn("collision", run.stderr)

    def test_windows_unc_anchor_is_not_posix_double_slash(self):
        self.assertTrue(self.available, "RPC adapter has not been implemented")
        unc = PureWindowsPath("//server/share/input.json")
        self.assertTrue(hasattr(self.adapter, "canonical_root_identity"), "root identity normalization is missing")
        self.assertIs(self.adapter.canonical_root_identity(unc), unc)

    def test_cli_accepts_canonical_remote_client_caller_provenance(self):
        # Canonical C++ identities, verified from RemoteClient.cpp; these
        # controlled records exercise import/classification, never performance.
        for caller in ("RemoteClient::RequestServerLog", "RemoteClient::RequestPostQueue",
                       "RemoteClient::RequestHistory"):
            with self.subTest(caller=caller), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proof = manifest()
                proof["fixtures"][0]["caller"] = caller
                metadata = root / "proof.json"
                source = root / "source.jsonl"
                output = root / "out"
                metadata.write_text(json.dumps(proof))
                source.write_bytes(jsonl(samples()))
                run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                      "--source", str(source), "--output-dir", str(output)],
                                     capture_output=True, text=True, timeout=2)
                self.assertEqual(run.returncode, 0, run.stderr)
                status = json.loads((output / "adapter-status.json").read_text())
                reasons = " ".join(status["reasons"])
                self.assertNotIn("complete RPC caller provenance missing", reasons)
                self.assertEqual(status["status"], "HOLD", "controlled records must not qualify real performance")
                self.assertEqual((output / "source.raw").read_bytes(), source.read_bytes())
                if (ADAPTER.parent.parent / "summarize.py").exists():
                    exported = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
                    self.assertEqual(exported, samples())
                    self.assertEqual(json.loads((output / "manifest.json").read_text())["fixtures"][0]["caller"], caller)
                else:
                    self.assertIn("summarize.py unavailable", reasons)
                    self.assertFalse((output / "samples.jsonl").exists())

    def test_cli_refuses_obsolete_remote_client_aliases(self):
        for caller in ("RemoteClient::Log", "RemoteClient::PostQueue", "RemoteClient::History"):
            with self.subTest(caller=caller), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proof = manifest()
                proof["fixtures"][0]["caller"] = caller
                metadata = root / "proof.json"
                source = root / "source.jsonl"
                output = root / "out"
                metadata.write_text(json.dumps(proof))
                source.write_bytes(jsonl(samples()))
                run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                      "--source", str(source), "--output-dir", str(output)],
                                     capture_output=True, text=True, timeout=2)
                self.assertEqual(run.returncode, 0, run.stderr)
                status = json.loads((output / "adapter-status.json").read_text())
                self.assertEqual(status["status"], "HOLD")
                self.assertIn("complete RPC caller provenance missing", " ".join(status["reasons"]))
                self.assertEqual(status["exported_rows"], 0)
                self.assertFalse((output / "manifest.json").exists())
                self.assertFalse((output / "samples.jsonl").exists())
                self.assertEqual((output / "source.raw").read_bytes(), source.read_bytes())

    def test_cli_refuses_recorded_caller_contradicting_canonical_manifest(self):
        for recorded in ("RemoteClient::RequestHistory", "RemoteClient::Log"):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proof = manifest()
                proof["fixtures"][0]["caller"] = "RemoteClient::RequestServerLog"
                rows = samples()
                rows[0]["caller"] = recorded
                metadata = root / "manifest.json"
                source = root / "source.jsonl"
                output = root / "out"
                metadata.write_text(json.dumps(proof))
                raw = jsonl(rows)
                source.write_bytes(raw)
                run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                      "--source", str(source), "--output-dir", str(output)],
                                     capture_output=True, text=True, timeout=2)
                self.assertEqual(run.returncode, 2)
                self.assertIn("recorded caller contradicts fixture provenance", run.stderr)
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), raw)

    def test_cli_accepts_digest_changes_between_matched_rounds_and_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = samples()
            for row in rows:
                row["observable_digest"] = ("d" if row["round"] == 0 else "e") * 64
            rows += [{**row, "process": 8,
                      "observable_digest": ("f" if row["round"] == 0 else "a") * 64}
                     for row in samples()]
            metadata = root / "manifest.json"
            source = root / "source.jsonl"
            output = root / "out"
            metadata.write_text(json.dumps(manifest()))
            raw = jsonl(rows)
            source.write_bytes(raw)
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True, timeout=2)
            self.assertEqual(run.returncode, 0, run.stderr)
            status = json.loads((output / "adapter-status.json").read_text())
            self.assertEqual(status["status"], "HOLD", "controlled records cannot qualify native performance")
            self.assertEqual((output / "source.raw").read_bytes(), raw)
            if (ADAPTER.parent.parent / "summarize.py").exists():
                exported = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
                self.assertEqual(exported, rows)
                self.assertEqual(status["exported_rows"], 12)
            else:
                self.assertIn("summarize.py unavailable", " ".join(status["reasons"]))

    def test_cli_refuses_different_variant_digests_inside_one_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "manifest.json"
            source = root / "source.jsonl"
            output = root / "out"
            metadata.write_text(json.dumps(manifest()))
            rows = samples()
            rows[1]["observable_digest"] = "e" * 64
            raw = jsonl(rows)
            source.write_bytes(raw)
            run = subprocess.run([sys.executable, str(ADAPTER), "--manifest", str(metadata),
                                  "--source", str(source), "--output-dir", str(output)],
                                 capture_output=True, text=True, timeout=2)
            self.assertEqual(run.returncode, 2)
            self.assertIn("mismatched observable digests", run.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
