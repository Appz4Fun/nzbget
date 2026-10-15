"""Synthetic campaign-v1 contract tests, never native performance evidence.

All clocks, process IDs, source/archive/executable hashes and review rationales
below are explicit dummy fixtures. They attest no execution, independence,
build lineage, actual caller/ABI behavior, preservation or retirement readiness.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "summarize.py"
PROFILE = "rust-replacement-campaign-v1"
ARTIFACTS = ("campaign-qualification.json", "campaign-report.md")
GENERIC_ARTIFACTS = ("summary.json", "bencher.json", "qualification.json", "report.md")
VARIANTS = ("cpp_current", "cpp_optimized", "rust_current", "rust_candidate")


def campaign_manifest():
    """Literal prospective synthetic grid: two clusters, four paired rounds."""
    return {
        "schema_version": 1, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
        "testbed": "synthetic-no-native-or-independence-claim",
        "toolchain": {"compiler": "dummy", "flags": "synthetic only"},
        "comparison": {"baseline": "cpp_optimized", "candidate": "rust_candidate"},
        "qualification_policy": {"min_processes": 2, "min_rounds": 4,
                                 "min_each_order": 1, "max_relative_ci_width": 0.01},
        "fixtures": [{"id": "changed", "sha256": "c" * 64,
                      "scope": "complete_caller", "role": "changed",
                      "required_variants": list(VARIANTS),
                      "rust_preservation_applicability": "required"},
                     {"id": "unchanged", "sha256": "8" * 64,
                      "scope": "complete_caller", "role": "unchanged_control",
                      "required_variants": list(VARIANTS),
                      "rust_preservation_applicability": "required",
                      "provenance": {"attribution": "Synthetic same operation and equal variant durations; no native source attestation"}}],
        "qualification_profile": {
            "id": "rust-replacement-campaign", "version": 1,
            "plan_id": "synthetic-plan-not-an-admitted-native-run",
            "plan_sha256": "d" * 64,
            "variant_bindings": {
                variant: {"source_sha": ("b" if variant == "rust_candidate" else "a") * 40,
                          "source_content_sha256": str(index + 1) * 64,
                          "executable_sha256": str(index + 5) * 64,
                          **({"rust_archive_sha256": ("e" if variant == "rust_current" else "f") * 64}
                             if variant.startswith("rust_") else {})}
                for index, variant in enumerate(VARIANTS)},
            "collection_design": {
                "changed": {"elapsed_floor_ns": 200000, "process_count": 2, "round_count": 4,
                            "order_cycle": [list(VARIANTS), list(reversed(VARIANTS))]},
                "unchanged": {"elapsed_floor_ns": 200000, "process_count": 2, "round_count": 4,
                              "order_cycle": [list(VARIANTS), list(reversed(VARIANTS))]}}}}


def campaign_rows(latencies=None, case=None, variants=VARIANTS):
    """Explicit changed + equal unchanged data, or one requested fixture only."""
    rows = []
    for fixture in (("changed", "unchanged") if case is None else (case,)):
        elapsed = {"cpp_current": 2000000, "cpp_optimized": 1000000,
                   "rust_current": 500000, "rust_candidate": 400000}
        if fixture == "unchanged":
            elapsed = {variant: 1000000 for variant in VARIANTS}
        if fixture != "unchanged" or case is not None:
            elapsed.update(latencies or {})
        for process in range(2):
            for round_ in range(4):
                order = variants if round_ % 2 == 0 else tuple(reversed(variants))
                for position, variant in enumerate(order):
                    rows.append({"case": fixture, "variant": variant, "process": process,
                                 "round": round_, "order": position, "elapsed_ns": elapsed[variant],
                                 "iterations": 100, "observable_digest": "9" * 64})
    return rows


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-campaign-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name).resolve()
        self.sequence = 0

    def invoke(self, manifest=None, rows=None, *, generic=False, selector=PROFILE,
               raw_manifest=None, raw_samples=None, output=None, prepare=None,
               script=None, wrapper_source=None):
        self.sequence += 1
        folder = self.work / str(self.sequence)
        folder.mkdir()
        manifest_path, sample_path = folder / "manifest.json", folder / "samples.jsonl"
        manifest = campaign_manifest() if manifest is None else manifest
        rows = campaign_rows() if rows is None else rows
        manifest_path.write_bytes(raw_manifest if raw_manifest is not None else json.dumps(manifest).encode())
        sample_path.write_bytes(raw_samples if raw_samples is not None else
                               "".join(json.dumps(row) + "\n" for row in rows).encode())
        original = (manifest_path.read_bytes(), sample_path.read_bytes())
        output = folder / "output" if output is None else output
        if prepare is not None:
            prepare(manifest_path, sample_path, output)
        script = SCRIPT if script is None else script
        argv = [sys.executable, "-B"]
        argv += [str(script)] if wrapper_source is None else ["-c", wrapper_source, str(script)]
        argv += ["--manifest", str(manifest_path),
                "--samples", str(sample_path), "--output-dir", str(output)]
        if not generic:
            argv += ["--qualification-profile", selector]
        result = subprocess.run(argv, cwd=SCRIPT.parents[2], capture_output=True,
                                text=True, timeout=10,
                                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(original, (manifest_path.read_bytes(), sample_path.read_bytes()),
                         "Analyzer changed immutable synthetic input bytes")
        return result, output

    def valid(self, want="PASS", manifest=None, rows=None, **kwargs):
        result, output = self.invoke(manifest, rows, **kwargs)
        self.assertEqual(result.returncode, 0,
                         "Campaign capability absent/rejected: " + result.stderr)
        self.assertTrue((output / ARTIFACTS[0]).is_file(), "Missing campaign qualification artifact")
        q = json.loads((output / ARTIFACTS[0]).read_text())
        self.assertEqual(q["status"], want)
        self.assertEqual(q["qualification_profile"]["id"], "rust-replacement-campaign")
        self.assertEqual(q["qualification_profile"]["version"], 1)
        self.assertEqual(q["eligibility_scope"], "numerical_only")
        self.assertTrue((output / ARTIFACTS[1]).is_file())
        self.assertTrue(all(not (output / name).exists() for name in GENERIC_ARTIFACTS),
                        "Campaign mode must not emit legacy PASS artifacts")
        return q, output

    def invalid(self, manifest=None, rows=None, **kwargs):
        result, output = self.invoke(manifest, rows, **kwargs)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("unrecognized arguments", result.stderr,
                         "Missing CLI capability is not input-rejection evidence")
        self.assertIn("rejected", result.stderr)
        self.assertTrue(all(not (output / name).exists() for name in ARTIFACTS))
        return result, output

    def test_campaign_gate_reports_both_cpp_ratios(self):
        # A selected-only gate or CLI fall-through cannot supply both results.
        legacy = campaign_manifest()
        legacy.pop("qualification_profile")
        baseline, out = self.invoke(legacy, generic=True)
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.assertEqual(json.loads((out / "qualification.json").read_text())["status"], "PASS")
        q, _ = self.valid()
        comparisons = q["cases"][0]["comparisons"]
        self.assertEqual(set(comparisons), {"cpp_current", "cpp_optimized", "rust_current"})
        for name, want, threshold in (("cpp_current", 0.2, 0.5), ("cpp_optimized", 0.4, 0.5),
                                      ("rust_current", 0.8, 1)):
            self.assertAlmostEqual(comparisons[name]["ratio"]["upper"], want)
            self.assertEqual(comparisons[name]["upper_bound_limit"], threshold)
            self.assertEqual(comparisons[name]["status"], "PASS")

    def test_generic_pass_is_not_campaign_pass(self):
        rows = campaign_rows({"rust_candidate": 800000, "rust_current": 900000})
        legacy = campaign_manifest()
        legacy.pop("qualification_profile")
        result, output = self.invoke(legacy, rows, generic=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "PASS")
        q, _ = self.valid("HOLD", rows=rows)
        self.assertEqual(q["cases"][0]["comparisons"]["cpp_optimized"]["status"], "HOLD")

    def test_each_cpp_control_is_gated_separately(self):
        for baseline in ("cpp_current", "cpp_optimized"):
            with self.subTest(baseline=baseline):
                q, _ = self.valid("HOLD", rows=campaign_rows({baseline: 500000}))
                self.assertEqual(q["cases"][0]["comparisons"][baseline]["status"], "HOLD")

    def test_cpp_and_rust_threshold_equality_is_eligible(self):
        q, _ = self.valid(rows=campaign_rows({"rust_candidate": 500000}))
        comparisons = q["cases"][0]["comparisons"]
        self.assertEqual(comparisons["cpp_optimized"]["ratio"]["upper"], 0.5)
        self.assertEqual(comparisons["rust_current"]["ratio"]["upper"], 1)

    def test_cpp_success_cannot_hide_current_rust_regression(self):
        q, _ = self.valid("HOLD", rows=campaign_rows({"rust_current": 300000}))
        self.assertEqual(q["cases"][0]["comparisons"]["rust_current"]["status"], "HOLD")

    def test_integer_elapsed_floor_applies_to_every_variant(self):
        for variant in VARIANTS:
            for invalid in (199999, 200000.0, 200000.5, True, 0, -1, 2**63):
                with self.subTest(variant=variant, invalid=invalid):
                    rows = campaign_rows()
                    next(row for row in rows if row["variant"] == variant)["elapsed_ns"] = invalid
                    self.invalid(rows=rows)
        rows = campaign_rows()
        del rows[0]["elapsed_ns"]
        self.invalid(rows=rows)
        self.valid(rows=campaign_rows({"rust_candidate": 200000}))

    def test_invalid_floor_is_rejected_without_a_default(self):
        for invalid in (None, 0, -1, 200000.0, True, 2**63):
            with self.subTest(floor=invalid):
                m = campaign_manifest()
                design = m["qualification_profile"]["collection_design"]["changed"]
                if invalid is None:
                    del design["elapsed_floor_ns"]
                else:
                    design["elapsed_floor_ns"] = invalid
                self.invalid(m)

    def test_profile_and_plan_bindings_are_explicit(self):
        mutations = []
        for field in ("plan_sha256", "variant_bindings", "collection_design"):
            m = campaign_manifest()
            del m["qualification_profile"][field]
            mutations.append(m)
        m = campaign_manifest()
        m["qualification_profile"]["version"] = 2
        mutations.append(m)
        m = campaign_manifest()
        del m["qualification_policy"]["min_processes"]
        mutations.append(m)
        m = campaign_manifest()
        del m["qualification_profile"]["variant_bindings"]["rust_current"]["rust_archive_sha256"]
        mutations.append(m)
        for m in mutations:
            self.invalid(m)
        self.invalid(selector="rust-replacement-campaign-v2")
        m = campaign_manifest()
        m.pop("qualification_profile")
        self.invalid(m)
        self.invalid(campaign_manifest(), generic=True)

    def test_duplicate_and_unmatched_keys_reject(self):
        rows = campaign_rows()
        self.invalid(rows=rows + [copy.deepcopy(rows[0])])
        duplicate = copy.deepcopy(rows[0])
        duplicate["order"] = 1
        self.invalid(rows=rows + [duplicate])
        self.invalid(rows=rows[:-1])
        for field, value in (("order", 1), ("process", 2), ("round", 4),
                             ("case", "unknown"), ("observable_digest", "0" * 64)):
            mutated = campaign_rows()
            mutated[0][field] = value
            self.invalid(rows=mutated)

    def test_whole_missing_design_keys_hold_without_subset_statistics(self):
        removals = (
            lambda row: row["variant"] == "rust_current",
            lambda row: row["variant"] == "cpp_current",
            lambda row: row["process"] == 1,
            lambda row: row["round"] == 3,
            lambda row: True)
        for remove in removals:
            q, _ = self.valid("HOLD", rows=[row for row in campaign_rows() if not remove(row)])
            self.assertEqual(q["cases"][0]["comparisons"], {})

    def test_required_rust_cannot_be_omitted_or_inferred(self):
        m = campaign_manifest()
        m["fixtures"][0]["required_variants"].remove("rust_current")
        cycle = m["qualification_profile"]["collection_design"]["changed"]["order_cycle"]
        for permutation in cycle:
            permutation.remove("rust_current")
        variants = tuple(v for v in VARIANTS if v != "rust_current")
        rows = campaign_rows(case="changed", variants=variants) + campaign_rows(case="unchanged")
        q, _ = self.valid("HOLD", m, rows)
        self.assertEqual(q["cases"][0]["comparisons"], {})
        m = campaign_manifest()
        del m["fixtures"][0]["rust_preservation_applicability"]
        self.valid("HOLD", m)

    def test_not_applicable_requires_source_bound_rationale_and_no_held_rust(self):
        m = campaign_manifest()
        m["fixtures"][0]["rust_preservation_applicability"] = "not_applicable"
        m["fixtures"][0]["provenance"] = {
            "rust_preservation_rationale": "Synthetic first port has no current Rust; dummy source bindings only"}
        self.invalid(m)
        variants = tuple(v for v in VARIANTS if v != "rust_current")
        m["fixtures"][0]["required_variants"] = list(variants)
        design = m["qualification_profile"]["collection_design"]["changed"]
        design["order_cycle"] = [list(variants), list(reversed(variants))]
        rows = campaign_rows(case="changed", variants=variants) + campaign_rows(case="unchanged")
        q, _ = self.valid(manifest=m, rows=rows)
        self.assertNotIn("rust_current", q["cases"][0]["comparisons"])
        del m["fixtures"][0]["provenance"]["rust_preservation_rationale"]
        self.invalid(m, rows)

    def test_frozen_order_and_every_pair_balance_are_checked(self):
        m = campaign_manifest()
        cycle = m["qualification_profile"]["collection_design"]["changed"]["order_cycle"]
        m["qualification_profile"]["collection_design"]["changed"]["order_cycle"] = [cycle[0]]
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed":
                row["order"] = VARIANTS.index(row["variant"])
        self.valid("HOLD", m, rows)
        rows = campaign_rows()
        for row in rows:
            if row["round"] == 1:
                row["order"] = VARIANTS.index(row["variant"])
        self.invalid(rows=rows)

    def test_noisy_process_interval_cannot_be_pooled_away(self):
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed" and row["variant"] == "rust_candidate" and row["process"] == 1:
                row["elapsed_ns"] = 800000
        self.valid("HOLD", rows=rows)

    def test_unchanged_controls_are_checked_against_all_baselines(self):
        m = campaign_manifest()
        self.valid(manifest=m, rows=campaign_rows())
        for baseline in ("cpp_current", "cpp_optimized", "rust_current"):
            for duration in (800000, 1200000):
                rows = campaign_rows()
                for row in rows:
                    if row["case"] == "unchanged" and row["variant"] == baseline:
                        row["elapsed_ns"] = duration
                q, _ = self.valid("HOLD", m, rows)
                self.assertEqual(q["cases"][1]["comparisons"][baseline]["status"], "HOLD")

    def test_one_failed_fixture_and_kernel_cannot_disappear(self):
        m = campaign_manifest()
        other = copy.deepcopy(m["fixtures"][0])
        other["id"] = "tiny"
        m["fixtures"].append(other)
        m["qualification_profile"]["collection_design"]["tiny"] = copy.deepcopy(
            m["qualification_profile"]["collection_design"]["changed"])
        self.valid("HOLD", m, campaign_rows() + campaign_rows({"rust_candidate": 800000}, case="tiny"))
        other["scope"] = "kernel"
        self.valid("HOLD", m, campaign_rows() + campaign_rows(case="tiny"))

    def test_grid_and_comparison_work_are_bounded_before_resampling(self):
        for field, value in (("process_count", 129), ("round_count", 100000),
                             ("process_count", True), ("round_count", 3)):
            m = campaign_manifest()
            m["qualification_profile"]["collection_design"]["changed"][field] = value
            self.invalid(m)
        m = campaign_manifest()
        m["fixtures"] = []
        m["qualification_profile"]["collection_design"] = {}
        for index in range(3):
            fixture = {"id": str(index), "sha256": "c" * 64, "scope": "complete_caller", "role": "changed",
                       "required_variants": list(VARIANTS), "rust_preservation_applicability": "required"}
            m["fixtures"].append(fixture)
            m["qualification_profile"]["collection_design"][str(index)] = {
                "elapsed_floor_ns": 200000, "process_count": 128, "round_count": 4,
                "order_cycle": [list(VARIANTS), list(reversed(VARIANTS))]}
        # 3 cases * 128 clusters * 3 ratios * 5000 = 5,760,000 > 4,000,000.
        self.invalid(m, [])

    def test_invalid_reimport_removes_only_owned_campaign_artifacts(self):
        output = self.work / "reuse"
        self.valid(output=output)
        sentinel = output / "historical-generic.json"
        sentinel.write_bytes(b"preserved historical evidence\n")
        rows = campaign_rows()
        rows[0]["elapsed_ns"] = 199999
        self.invalid(rows=rows, output=output)
        self.assertEqual(sentinel.read_bytes(), b"preserved historical evidence\n")

    def test_campaign_outputs_cannot_alias_immutable_inputs(self):
        def alias(_manifest, samples, output):
            output.mkdir()
            os.link(samples, output / ARTIFACTS[0])
        result, output = self.invoke(prepare=alias)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertTrue((output / ARTIFACTS[0]).is_file(), "Alias protection must precede owned cleanup")

    def test_missing_selector_invalidates_only_campaign_outputs(self):
        # Selector-only ownership leaves stale campaign PASS and erases history.
        _, output = self.valid()
        historical = {name: ("immutable generic history: " + name).encode()
                      for name in GENERIC_ARTIFACTS}
        for name, raw in historical.items():
            (output / name).write_bytes(raw)
        result, _ = self.invoke(generic=True, output=output)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("rejected", result.stderr)
        actual = {"campaign_remaining": [name for name in ARTIFACTS if (output / name).exists()],
                  "generic_bytes": {name: (output / name).read_bytes() if (output / name).exists() else None
                                    for name in GENERIC_ARTIFACTS}}
        self.assertEqual(actual, {"campaign_remaining": [], "generic_bytes": historical},
                         "Missing selector must reject and invalidate campaign only, preserving all generic history")

    def test_missing_selector_campaign_alias_protects_inputs_and_generic_history(self):
        # Classification must protect the eventual campaign targets before unlink.
        historical = {name: ("immutable generic history: " + name).encode()
                      for name in GENERIC_ARTIFACTS}

        def alias(_manifest, samples, output):
            output.mkdir()
            for name, raw in historical.items():
                (output / name).write_bytes(raw)
            os.link(samples, output / ARTIFACTS[0])

        result, output = self.invoke(generic=True, prepare=alias)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("collides with immutable input", result.stderr)
        self.assertTrue((output / ARTIFACTS[0]).is_file(), "Protected alias must not be unlinked")
        self.assertEqual({name: (output / name).read_bytes() for name in GENERIC_ARTIFACTS}, historical)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_rows(self):
        m = json.dumps(campaign_manifest())
        self.invalid(raw_manifest=(m[:-1] + ',"schema_version":1}').encode())
        for number in ("NaN", "Infinity", "-Infinity"):
            rows = campaign_rows()
            raw = "".join(json.dumps(row) + "\n" for row in rows)
            self.invalid(raw_samples=raw.replace('"elapsed_ns": 2000000', '"elapsed_ns": ' + number, 1).encode())

    def test_artifacts_bind_exact_raw_inputs_and_analysis(self):
        q, output = self.valid()
        folder = output.parent
        self.assertEqual(q["input_hashes"]["manifest_sha256"], hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest())
        self.assertEqual(q["input_hashes"]["samples_sha256"], hashlib.sha256((folder / "samples.jsonl").read_bytes()).hexdigest())
        self.assertEqual(q["analysis_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(q["qualification_profile"]["plan_sha256"], "d" * 64)
        self.assertEqual(q["cases"][0]["raw_count"], 32)

    def test_campaign_variant_revision_bindings_must_match_manifest(self):
        # Well-formed digest syntax cannot override canonical source association.
        for variant in ("rust_candidate", "cpp_current", "rust_current"):
            with self.subTest(variant=variant):
                m = campaign_manifest()
                m["qualification_profile"]["variant_bindings"][variant]["source_sha"] = "0" * 40
                self.invalid(m)
        # A separately attributed fair optimized C++ revision remains permitted.
        m = campaign_manifest()
        m["qualification_profile"]["variant_bindings"]["cpp_optimized"]["source_sha"] = "e" * 40
        self.valid(manifest=m)

    def test_campaign_without_unchanged_control_holds(self):
        # Favorable changed cases cannot replace the mandatory drift control.
        m = campaign_manifest()
        m["fixtures"] = [f for f in m["fixtures"] if f["role"] != "unchanged_control"]
        fixture_ids = {f["id"] for f in m["fixtures"]}
        designs = m["qualification_profile"]["collection_design"]
        m["qualification_profile"]["collection_design"] = {
            case: design for case, design in designs.items() if case in fixture_ids}
        rows = [row for row in campaign_rows() if row["case"] in fixture_ids]
        self.valid("HOLD", manifest=m, rows=rows)

    def test_kernel_without_preservation_decision_keeps_cpp_diagnostics(self):
        # Kernel diagnostics need no runtime applicability decision, yet never qualify.
        m = campaign_manifest()
        m["fixtures"][0]["scope"] = "kernel"
        del m["fixtures"][0]["rust_preservation_applicability"]
        q, _ = self.valid("HOLD", manifest=m)
        case = q["cases"][0]
        self.assertTrue({"cpp_current", "cpp_optimized"} <= set(case["comparisons"]),
                        "Missing runtime preservation decision must not suppress kernel C++ ratios")
        self.assertIn("kernel_cannot_qualify_campaign", case["reasons"])

    def test_invocation_source_change_after_private_load_rejects(self):
        # Sequential runpy load -> replace -> SAME loaded main, without sleeps,
        # hash mocks, .pyc reuse, or any mutation of the repository analyzer.
        original = SCRIPT.read_bytes()
        original_sha = hashlib.sha256(original).hexdigest()
        private_script = self.work / "private-analyzer.py"
        historical = {name: ("immutable generic identity history: " + name).encode()
                      for name in GENERIC_ARTIFACTS}
        stale_report = b"stale campaign report\n"

        def seed_stale(_manifest, _samples, output):
            output.mkdir()
            (output / ARTIFACTS[0]).write_text(json.dumps(
                {"status": "PASS", "analysis_sha256": "0" * 64, "stale_fixture": True}))
            (output / ARTIFACTS[1]).write_bytes(stale_report)
            for name, raw in historical.items():
                (output / name).write_bytes(raw)

        for phase in ("unchanged", "before_analysis", "after_analysis"):
            with self.subTest(source_change_phase=phase):
                private_script.write_bytes(original)
                wrapper = (
                    "import hashlib,json,os,runpy,sys\nfrom pathlib import Path\n"
                    "source=Path(sys.argv[1])\n"
                    "loaded=runpy.run_path(str(source),run_name='private_campaign_fixture')\n"
                    "main=loaded['main']\n"
                    "assert Path(main.__globals__['__file__'])==source\n"
                    "before=hashlib.sha256(source.read_bytes()).hexdigest()\n"
                    f"phase={phase!r}\n"
                    "print(json.dumps({'event':'private_load_complete','before':before,'phase':phase}),flush=True)\n"
                    "def replace_source():\n"
                    "    replacement=source.with_suffix('.replacement')\n"
                    "    replacement.write_bytes(source.read_bytes()+b'\\n# replaced after private load\\n')\n"
                    "    os.replace(replacement,source)\n"
                    "    print(json.dumps({'event':'private_source_replaced','after':hashlib.sha256(source.read_bytes()).hexdigest()}),flush=True)\n"
                    "if phase=='before_analysis':\n"
                    "    replace_source()\n"
                    "elif phase=='after_analysis':\n"
                    "    actual_campaign=main.__globals__['summarize_campaign']\n"
                    "    def campaign_then_replace(*args,**kwargs):\n"
                    "        result=actual_campaign(*args,**kwargs)\n"
                    "        replace_source()\n"
                    "        return result\n"
                    "    main.__globals__['summarize_campaign']=campaign_then_replace\n"
                    "code=main(sys.argv[2:])\n"
                    "print(json.dumps({'event':'same_loaded_main_returned','exit':code,'after':hashlib.sha256(source.read_bytes()).hexdigest()}),flush=True)\n"
                    "sys.exit(code)\n")
                result, output = self.invoke(script=private_script, wrapper_source=wrapper, prepare=seed_stale)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(events[0]["before"], original_sha)
                self.assertEqual(events[-1]["event"], "same_loaded_main_returned")
                self.assertEqual(events[-1]["exit"], result.returncode)
                q_path = output / ARTIFACTS[0]
                q = json.loads(q_path.read_text()) if q_path.exists() else None
                # Preserve the wrapper's actual stdout/stderr/exit in the outer
                # admitted raw stream, including the successful control case.
                print(json.dumps({"private_source_phase": phase, "cli_exit": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr,
                    "artifact_status": q.get("status") if q else None,
                    "artifact_analysis_sha256": q.get("analysis_sha256") if q else None}), flush=True)
                self.assertEqual({name: (output / name).read_bytes() if (output / name).is_file() else None
                                  for name in GENERIC_ARTIFACTS}, historical,
                                 "Invocation-source validation must preserve all generic history")
                if phase != "unchanged":
                    self.assertNotEqual(events[-1]["after"], original_sha)
                    self.assertTrue(any(event["event"] == "private_source_replaced" for event in events))
                    self.assertEqual(result.returncode, 2,
                                     "Changed invocation source must reject, not relabel loaded functions with replacement bytes")
                    self.assertTrue(all(not (output / name).exists() for name in ARTIFACTS))
                else:
                    self.assertEqual(events[-1]["after"], original_sha)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(q["status"], "PASS")
                    self.assertEqual(q["analysis_sha256"], original_sha)
                    self.assertNotIn("stale_fixture", q)
                    self.assertNotEqual((output / ARTIFACTS[1]).read_bytes(), stale_report)

    def test_cpp_gate_preserves_exact_half_integer_boundaries(self):
        cases = (
            ("above", 9223372036854775807, 4611686018427387904, 100, 100, "HOLD"),
            ("below", 9223372036854775807, 4611686018427387903, 100, 100, "PASS"),
            ("exact", 9223372036854775806, 4611686018427387903, 100, 100, "PASS"),
            ("normalized_exact", 9223372036854775807, 9223372036854775807, 1, 2, "PASS"))
        for label, baseline, candidate, baseline_iterations, candidate_iterations, want in cases:
            with self.subTest(boundary=label):
                rows = campaign_rows()
                for row in rows:
                    if row["case"] == "changed":
                        cpp = row["variant"] in ("cpp_current", "cpp_optimized")
                        row["elapsed_ns"] = baseline if cpp else candidate
                        row["iterations"] = baseline_iterations if cpp else candidate_iterations
                q, _ = self.valid(want, rows=rows)
                for baseline_name in ("cpp_current", "cpp_optimized"):
                    self.assertEqual(q["cases"][0]["comparisons"][baseline_name]["status"], want)

    def test_rust_preservation_preserves_exact_one_integer_boundaries(self):
        cases = (
            ("above", 9223372036854775806, 9223372036854775807, 100, 100, "HOLD"),
            ("below", 9223372036854775807, 9223372036854775806, 100, 100, "PASS"),
            ("exact", 9223372036854775807, 9223372036854775807, 100, 100, "PASS"),
            ("normalized_exact", 2000000, 4000000, 1, 2, "PASS"))
        for label, baseline, candidate, baseline_iterations, candidate_iterations, want in cases:
            with self.subTest(boundary=label):
                rows = campaign_rows()
                for row in rows:
                    if row["case"] == "changed":
                        is_candidate = row["variant"] == "rust_candidate"
                        row["elapsed_ns"] = candidate if is_candidate else baseline
                        row["iterations"] = candidate_iterations if is_candidate else baseline_iterations
                # The C++ ratios are approximately one here, so global HOLD is
                # expected independently of the precise Rust preservation gate.
                q, _ = self.valid("HOLD", rows=rows)
                self.assertEqual(q["cases"][0]["comparisons"]["rust_current"]["status"], want)

    def test_mixed_multiplicative_exact_boundaries_remain_eligible(self):
        for boundary in ("half", "one"):
            with self.subTest(boundary=boundary):
                rows = campaign_rows()
                for row in rows:
                    if row["case"] == "changed":
                        candidate = ((250000 if row["round"] % 2 == 0 else 4000000)
                                     if boundary == "half" else
                                     (200000 if row["round"] % 2 == 0 else 20000000))
                        row["elapsed_ns"] = (candidate if row["variant"] == "rust_candidate" or
                            (boundary == "half" and row["variant"] == "rust_current") else 2000000)
                # Half: (1/8 * 2)^(1/2)=1/2 against each C++ control.
                # One: (1/10 * 10)^(1/2)=1 for Rust, while both C++ ratios
                # are also one and intentionally keep the whole packet on HOLD.
                q, _ = self.valid("PASS" if boundary == "half" else "HOLD", rows=rows)
                names = ("cpp_current", "cpp_optimized") if boundary == "half" else ("rust_current",)
                for baseline_name in names:
                    self.assertEqual(q["cases"][0]["comparisons"][baseline_name]["status"], "PASS")

    def test_arithmetic_budget_and_cache_rematerialization_are_bounded(self):
        # These small synthetic limit injections exercise rejection/accounting,
        # never an alternative production policy or a performance measurement.
        wrapper = (
            "import runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='private_budget_fixture')['main']\n"
            "g=main.__globals__\n"
            "a=g['CampaignArithmetic']()\n"
            "limits=g['CAMPAIGN_ARITHMETIC_LIMITS']\n"
            "try:\n"
            "    a.charge('limb_work',limits['limb_work']+1)\n"
            "except g['ValidationError'] as error:\n"
            "    assert 'resource limit' in str(error) and a.used['limb_work']==0\n"
            "else:\n"
            "    raise AssertionError('Unbounded arithmetic admitted')\n"
            "original=limits['integer_bits']\n"
            "limits['integer_bits']=16\n"
            "try:\n"
            "    a.mul(256,256)\n"
            "except g['ValidationError'] as error:\n"
            "    assert 'preallocation' in str(error) and a.used['limb_work']==0\n"
            "else:\n"
            "    raise AssertionError('Oversize allocation admitted')\n"
            "finally:\n"
            "    limits['integer_bits']=original\n"
            "original=limits['cache_bytes']\n"
            "limits['cache_bytes']=2\n"
            "try:\n"
            "    products=g['CampaignProducts'](a,[(2,1),(3,1)])\n"
            "    assert products.get((1,0))==(2,1)\n"
            "    assert products.get((1,0))==(2,1) and a.used['materializations']==1\n"
            "    assert products.get((0,1))==(3,1) and products.resident==2\n"
            "    assert products.get((1,0))==(2,1) and a.used['materializations']==3\n"
            "    assert len(products.cache)==1 and a.peak_cache_bytes==2\n"
            "finally:\n"
            "    limits['cache_bytes']=original\n"
            "sys.exit(main(sys.argv[2:]))\n")
        self.valid(wrapper_source=wrapper)

    def test_witness_budget_rejection_clears_only_owned_campaign_outputs(self):
        historical = {name: ("immutable budget history: " + name).encode()
                      for name in GENERIC_ARTIFACTS}

        def stale(_manifest, _samples, output):
            output.mkdir()
            for name in ARTIFACTS:
                (output / name).write_bytes(b"stale synthetic PASS")
            for name, raw in historical.items():
                (output / name).write_bytes(raw)

        wrapper = (
            "import runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='private_witness_fixture')['main']\n"
            "main.__globals__['CAMPAIGN_ARITHMETIC_LIMITS']['witness_bytes']=1\n"
            "sys.exit(main(sys.argv[2:]))\n")
        result, output = self.invalid(wrapper_source=wrapper, prepare=stale)
        self.assertIn("witness byte limit", result.stderr)
        self.assertEqual({name: (output / name).read_bytes() for name in GENERIC_ARTIFACTS}, historical)

    def test_decimal_context_isolation_unit_logs_and_witness_provenance(self):
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed":
                if row["variant"] == "rust_candidate":
                    row["elapsed_ns"] = 250000 if row["process"] == 0 else 400000
                elif row["variant"] == "rust_current" and row["process"] == 0:
                    row["elapsed_ns"] = 250000  # Exactly ln(1), in a nonuniform comparison.
        wrapper = (
            "import decimal,runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='private_context_fixture')['main']\n"
            "context=decimal.getcontext()\n"
            "context.prec=2\ncontext.rounding=decimal.ROUND_DOWN\n"
            "context.Emax=9\ncontext.Emin=-9\n"
            "for signal in context.traps:\n    context.traps[signal]=True\n"
            "sys.exit(main(sys.argv[2:]))\n")
        q, _ = self.valid("HOLD", rows=rows, wrapper_source=wrapper)
        # Independent fixed-seed oracle: 5000 x 2 test-only RNG selections,
        # no additional analyzer draws or CLI children.
        import random
        expected_rng = random.Random(20261011)
        expected_draws = []
        for _ in range(5000):
            multiplicities = [0, 0]
            for _ in range(2):
                multiplicities[expected_rng.randrange(2)] += 1
            expected_draws.append(multiplicities)
        # These exact fixture ratios determine the extreme critical ranks:
        # >=126 draws of either pure process put ranks124/125 at the minimum
        # and4874/4875 at the maximum, without a second statistical analysis.
        for pure in ([2, 0], [0, 2]):
            self.assertGreaterEqual(expected_draws.count(pure), 126)
        from decimal import (Decimal, Context, ROUND_FLOOR, ROUND_CEILING,
                             ROUND_HALF_EVEN, InvalidOperation, DivisionByZero,
                             Overflow, Underflow, Subnormal, Clamped, FloatOperation)
        reference = Context(prec=200, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                            traps=[InvalidOperation, DivisionByZero, Overflow, Underflow,
                                   Subnormal, Clamped, FloatOperation])
        process_ratios = {"cpp_current": (Decimal("0.125"), Decimal("0.2")),
                          "cpp_optimized": (Decimal("0.25"), Decimal("0.4")),
                          "rust_current": (Decimal("1"), Decimal("0.8"))}
        log_references = {Decimal("1"): (Decimal("0"), Decimal("0"))}
        for literal in ("0.125", "0.2", "0.25", "0.4", "0.8"):
            # Correctly rounded200-digit ln is not declared exact: bracket it
            # with adjacent context values, then require interval overlap.
            value = Decimal(literal, context=reference)
            rounded = reference.ln(value)
            log_references[value] = (reference.next_minus(rounded), reference.next_plus(rounded))
        for case in q["cases"]:
            for check in case["comparisons"].values():
                witness = check["certificate"]
                self.assertEqual(witness["bindings"]["analysis_sha256"], q["analysis_sha256"])
                self.assertEqual(witness["bindings"]["input_hashes"], q["input_hashes"])
                self.assertEqual(witness["bindings"]["plan_sha256"], "d" * 64)
                self.assertEqual(witness["bindings"]["fixture_sha256"], case["fixture_sha256"])
                self.assertEqual(witness["common_root_degree"], 8)
                self.assertEqual(witness["precision"], 80)
                self.assertTrue(all(value in ("LT", "EQ", "GT") for value in witness["relations"].values()))
                self.assertLessEqual(len(json.dumps(witness, sort_keys=True).encode()), 32768)
                self.assertLessEqual(witness["work_cumulative"].get("exp_calls", 0), 7680)
                contributors = witness["bounding_contributors"]
                self.assertIn("rank_enclosures", witness)
                enclosure = witness["rank_enclosures"]
                self.assertEqual(set(enclosure), {"route", "uniform", "selected"})
                if contributors is None:
                    self.assertEqual(enclosure["route"], "uniform_exact_process_product")
                    self.assertIsNone(enclosure["selected"])
                    self.assertIsInstance(enclosure["uniform"], dict)
                    records = {"uniform": enclosure["uniform"]}
                else:
                    self.assertEqual(enclosure["route"], "log_endpoint_order_statistics")
                    self.assertIsNone(enclosure["uniform"])
                    self.assertEqual(set(enclosure["selected"]), {"124", "125", "4874", "4875"})
                    records = enclosure["selected"]
                parsed_ranks = {}
                for rank, record in records.items():
                    self.assertEqual(set(record), {"log", "ratio"})
                    parsed = {}
                    for domain in ("log", "ratio"):
                        pair = record[domain]
                        self.assertIsInstance(pair, list)
                        self.assertEqual(len(pair), 2)
                        for raw in pair:
                            self.assertIs(type(raw), str)
                            self.assertLessEqual(len(raw), witness["precision"] + 32)
                            self.assertRegex(raw, r"^-?[0-9]+(?:\.[0-9]+)?(?:E[+-]?[0-9]+)?$")
                        parsed[domain] = [Decimal(raw, context=reference) for raw in pair]
                        self.assertTrue(all(value.is_finite() for value in parsed[domain]))
                        self.assertLessEqual(*parsed[domain])
                    self.assertGreater(parsed["ratio"][0], 0)
                    known = Decimal("1") if rank == "uniform" else (
                        min(process_ratios[check["baseline"]]) if rank in ("124", "125") else
                        max(process_ratios[check["baseline"]]))
                    self.assertLessEqual(parsed["ratio"][0], known)
                    self.assertLessEqual(known, parsed["ratio"][1])
                    reference_log = log_references[known]
                    self.assertLessEqual(parsed["log"][0], reference_log[1])
                    self.assertLessEqual(reference_log[0], parsed["log"][1])
                    parsed_ranks[rank] = parsed
                    if contributors is not None:
                        pure = [2, 0] if known == process_ratios[check["baseline"]][0] else [0, 2]
                        for side in ("lower", "upper"):
                            self.assertEqual(contributors[rank][side + "_process_multiplicities"], pure)
                if contributors is None:
                    self.assertEqual(parsed_ranks["uniform"]["log"], [Decimal("0"), Decimal("0")])
                    self.assertEqual(parsed_ranks["uniform"]["ratio"], [Decimal("1"), Decimal("1")])
                    for name in ("lower", "upper", "estimate"):
                        self.assertEqual(witness["bounds"][name], enclosure["uniform"]["ratio"])
                else:
                    for left, right in (("124", "125"), ("125", "4874"), ("4874", "4875")):
                        for domain in ("log", "ratio"):
                            for endpoint in (0, 1):
                                self.assertLessEqual(parsed_ranks[left][domain][endpoint],
                                                     parsed_ranks[right][domain][endpoint])
                    down, up = reference.copy(), reference.copy()
                    down.prec = up.prec = witness["precision"]
                    down.rounding, up.rounding = ROUND_FLOOR, ROUND_CEILING
                    for name, terms in (("lower", (("124", 1), ("125", 39))),
                                        ("upper", (("4874", 39), ("4875", 1)))):
                        replay = []
                        for endpoint, context in ((0, down), (1, up)):
                            first, second = terms
                            total = context.add(
                                context.multiply(parsed_ranks[first[0]]["ratio"][endpoint], Decimal(first[1])),
                                context.multiply(parsed_ranks[second[0]]["ratio"][endpoint], Decimal(second[1])))
                            replay.append(context.divide(context.multiply(total, Decimal("1")), Decimal("40")))
                        self.assertEqual(replay, [Decimal(raw, context=reference) for raw in witness["bounds"][name]])
                if contributors is not None:
                    self.assertEqual(set(contributors), {"124", "125", "4874", "4875"})
                    for contributor in contributors.values():
                        for side in ("lower", "upper"):
                            replicate_id = contributor[side + "_id"]
                            multiplicities = contributor[side + "_process_multiplicities"]
                            self.assertIs(type(replicate_id), int)
                            self.assertGreaterEqual(replicate_id, 0)
                            self.assertLess(replicate_id, 5000)
                            self.assertEqual(len(multiplicities), 2)
                            self.assertTrue(all(type(value) is int and 0 <= value <= 2
                                                for value in multiplicities))
                            self.assertEqual(sum(multiplicities), 2)
                            self.assertEqual(multiplicities, expected_draws[replicate_id])
        self.assertIsNotNone(q["cases"][0]["comparisons"]["rust_current"]["certificate"]["bounding_contributors"])

    def test_exact_quantile_radical_equality_and_stable_rank_helpers(self):
        wrapper = (
            "import runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='private_equality_fixture')['main']\n"
            "g=main.__globals__\na=g['CampaignArithmetic']()\n"
            "products=g['CampaignProducts'](a,[(1,16),(81,16)])\n"
            "assert a.root(81,4)==3 and a.root(82,4) is None\n"
            "terms=[((1,0),(1,2)),((0,1),(1,2))]\n"
            "assert g['campaign_quantile_equality'](terms,(1,1),products,4,a)\n"
            "assert not g['campaign_quantile_equality'](terms,(1,2),products,4,a)\n"
            "assert g['campaign_width_equality']([((1,0),(3,1)),((0,1),(-1,1))],products,4,a)\n"
            "distinct=g['CampaignProducts'](a,[(2,1),(3,1)])\n"
            "assert not g['campaign_width_equality']([((1,0),(1,1)),((0,1),(-1,1))],distinct,2,a)\n"
            "unit=g['CampaignProducts'](a,[(1,1)])\n"
            "draws=[(1,)]*5000\nlogs=[(g['Decimal'](0),g['Decimal'](0))]*5000\n"
            "assert g['campaign_exact_ranks'](logs,draws,unit)=={124:124,125:125,4874:4874,4875:4875}\n"
            "sys.exit(main(sys.argv[2:]))\n")
        self.valid(wrapper_source=wrapper)


    def test_exact_declared_decimal_width_rejects_constructed_false_lt(self):
        # Prospective synthetic construction, NOT recovered reviewer sample rows.
        # The recurrence preserves 10*v*v-u*v-10*u*u=1, so the width
        # (v*v-u*u)/(u*v) is strictly above 1/10 but below binary float(0.1).
        u, v = 39, 41
        for _ in range(3):
            u, v = 761 * u + 800 * v, 800 * u + 841 * v
        self.assertEqual(10 * v * v - u * v - 10 * u * u, 1)
        self.assertGreater(10 * u * v, 180143985094819840)
        self.assertTrue(200000 <= u <= v < 2**61)
        # Verify that the selected percentile ranks lie in the pure clusters.
        import random
        rng = random.Random(20261011)
        pure = [0, 0]
        for _ in range(5000):
            first, second = rng.randrange(2), rng.randrange(2)
            if first == second:
                pure[first] += 1
        self.assertTrue(all(count >= 126 for count in pure))
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed":
                cpp = row["variant"].startswith("cpp_")
                row["elapsed_ns"] = v if cpp or row["process"] == 1 else u
                row["iterations"] = (u if row["process"] == 0 else v) if cpp else 4 * v
        raw = json.dumps(campaign_manifest()).encode()
        needle = b'"max_relative_ci_width": 0.01'
        self.assertEqual(raw.count(needle), 1)
        for token, want, relation in (("0.1", "HOLD", "GT"), ("1e-1", "HOLD", "GT"),
                                      ("0.10000000000000001", "PASS", "LT")):
            with self.subTest(token=token):
                source = raw.replace(needle, b'"max_relative_ci_width": ' + token.encode())
                q, _ = self.valid(want, rows=rows, raw_manifest=source)
                exact = q["methodology"]["exact_width_policy"]
                self.assertEqual(exact["manifest_sha256"], hashlib.sha256(source).hexdigest())
                self.assertEqual(exact["token_sha256"], hashlib.sha256(token.encode()).hexdigest())
                self.assertEqual(exact["token_bytes"], len(token))
                expected = ("10000000000000001", "100000000000000000") if relation == "LT" else ("1", "10")
                self.assertEqual((exact["numerator"], exact["denominator"]), expected)
                for name in ("cpp_current", "cpp_optimized"):
                    certificate = q["cases"][0]["comparisons"][name]["certificate"]
                    self.assertEqual(certificate["relations"]["width_vs_policy"], relation)
                    self.assertEqual(certificate["width_policy_rational"],
                                     {"numerator": expected[0], "denominator": expected[1]})

    def test_exact_declared_decimal_width_equality_and_neighbors(self):
        # q0=4/25, q1=1/4: estimate=1/5 and exact relative width=9/20.
        import random
        rng = random.Random(20261011)
        pure = [0, 0]
        for _ in range(5000):
            first, second = rng.randrange(2), rng.randrange(2)
            if first == second:
                pure[first] += 1
        self.assertTrue(all(count >= 126 for count in pure))
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed":
                row["elapsed_ns"] = (2000000 if row["variant"].startswith("cpp_") else
                                     320000 if row["process"] == 0 else 500000)
        raw = json.dumps(campaign_manifest()).encode()
        needle = b'"max_relative_ci_width": 0.01'
        self.assertEqual(raw.count(needle), 1)
        for token, want, relation in (("0.44999999999999999999999999999999999999999999999999", "HOLD", "GT"),
                                      ("0.45", "PASS", "EQ"),
                                      ("0.45000000000000000000000000000000000000000000000001", "PASS", "LT")):
            with self.subTest(token=token):
                q, _ = self.valid(want, rows=rows,
                                  raw_manifest=raw.replace(needle, b'"max_relative_ci_width": ' + token.encode()))
                for name in ("cpp_current", "cpp_optimized"):
                    self.assertEqual(q["cases"][0]["comparisons"][name]["certificate"]
                                     ["relations"]["width_vs_policy"], relation)
                self.assertEqual(q["cases"][0]["comparisons"]["rust_current"]["status"], "PASS")

    def test_exact_declared_decimal_width_bounds_types_and_cleanup(self):
        raw = json.dumps(campaign_manifest()).encode()
        needle = b'"max_relative_ci_width": 0.01'
        self.assertEqual(raw.count(needle), 1)
        historical = {name: ("immutable-history-" + name).encode() for name in GENERIC_ARTIFACTS}

        def stale(_manifest, _samples, output):
            output.mkdir(exist_ok=True)
            for name in ARTIFACTS:
                (output / name).write_bytes(b'{"status":"PASS","stale_fixture":true}')
            for name, content in historical.items():
                (output / name).write_bytes(content)

        invalid_tokens = ("0", "-0.1", "2", "true", '"0.1"', "NaN", "Infinity",
                          "1.00000000000000001", "1e99999999999999999999",
                          "1e-99999999999999999999", "1e-3000", "0." + "1" * 3000)
        for token in invalid_tokens:
            with self.subTest(token=token[:60]):
                _, output = self.invalid(raw_manifest=raw.replace(needle, b'"max_relative_ci_width": ' + token.encode()),
                                         prepare=stale)
                self.assertEqual({name: (output / name).read_bytes() for name in GENERIC_ARTIFACTS}, historical)
        for token, numerator, denominator in (("1", "1", "1"), ("1e-324", "1", "1" + "0" * 324)):
            with self.subTest(token=token):
                q, _ = self.valid(raw_manifest=raw.replace(needle, b'"max_relative_ci_width": ' + token.encode()))
                exact = q["methodology"]["exact_width_policy"]
                self.assertEqual((exact["numerator"], exact["denominator"]), (numerator, denominator))
                self.assertIn("approximate", exact["display_policy_width"])
                if token == "1e-324":
                    self.assertEqual(q["methodology"]["policy"]["max_relative_ci_width"], 0.0)
        one = raw.replace(needle, b'"max_relative_ci_width": 1')
        token = b"1." + b"0" * (1024 * 1024 - len(one) - 1)
        longest = raw.replace(needle, b'"max_relative_ci_width": ' + token)
        self.assertEqual(len(longest), 1024 * 1024)
        q, _ = self.valid(raw_manifest=longest)
        self.assertEqual(q["methodology"]["exact_width_policy"]["token_bytes"], len(token))
        self.assertEqual(q["methodology"]["exact_width_policy"]["denominator"], "1")
        _, output = self.invalid(raw_manifest=longest + b" ", prepare=stale)
        self.assertEqual({name: (output / name).read_bytes() for name in GENERIC_ARTIFACTS}, historical)

    def test_exact_declared_decimal_width_raw_api_and_context_isolation(self):
        # One existing harness child; no hash mocking, model, or extra process.
        wrapper = (
            "import decimal,runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='private_exact_width_fixture')['main']\n"
            "g=main.__globals__\n"
            "try:\n g['summarize_campaign']({},[], 'a'*64)\n"
            "except g['ValidationError'] as error:\n assert 'retained manifest bytes' in str(error)\n"
            "else:\n raise AssertionError('materialized float API accepted without original token')\n"
            "context=decimal.getcontext();context.prec=2;context.Emax=9;context.Emin=-9\n"
            "for signal in context.traps: context.traps[signal]=True\n"
            "manifest,rational,provenance=g['campaign_width_policy'](b'{}',g['CampaignArithmetic']())\n"
            "assert rational==(1,10) and provenance['token_bytes']==0\n"
            "assert provenance['source']=='exact_default_decimal_declaration'\n"
            "assert provenance['token_sha256'] is None and provenance['default_decimal']=='0.10'\n"
            "for token in (b'0.1',b'1e-1'):\n"
            " assert g['campaign_width_policy'](b'{\"qualification_policy\":{\"max_relative_ci_width\":'+token+b'}}',g['CampaignArithmetic']())[1]==(1,10)\n"
            "assert type(g['strict_json'](b'{\"width\":0.1}')['width']) is float\n"
            "sys.exit(main(sys.argv[2:]))\n")
        raw = json.dumps(campaign_manifest()).encode().replace(b'"max_relative_ci_width": 0.01',
                                                               b'"max_relative_ci_width": 1e-324')
        q, _ = self.valid(raw_manifest=raw, wrapper_source=wrapper)
        self.assertEqual(q["methodology"]["exact_width_policy"]["denominator"], "1" + "0" * 324)

    def test_exact_declared_decimal_width_keeps_generic_float_contract(self):
        manifest = campaign_manifest()
        manifest.pop("qualification_profile")
        raw = json.dumps(manifest).encode().replace(b'"max_relative_ci_width": 0.01',
                                                    b'"max_relative_ci_width": 0.10000000000000001')
        result, output = self.invoke(generic=True, raw_manifest=raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["methodology"]["policy"], json.loads(raw)["qualification_policy"])
        self.assertNotIn("exact_width_policy", summary["methodology"])
        self.assertTrue(all(not (output / name).exists() for name in ARTIFACTS))

    def test_campaign_pass_schema_literal_source_contract_only(self):
        # Source-shape regression ONLY. This does not run a JSON Schema validator
        # or establish acceptance/rejection of the separate semantic fixture contract.
        schema = json.loads((SCRIPT.parent / "schema" / "campaign-qualification.schema.json").read_text())
        item = schema["properties"]["cases"]["items"]
        case_rule = item["allOf"][0]
        self.assertEqual(case_rule["if"], {"properties": {"status": {"const": "PASS"}}, "required": ["status"]})
        then = case_rule["then"]
        self.assertEqual(then["properties"]["complete"], {"const": True})
        self.assertEqual(then["properties"]["scope"], {"const": "complete_caller"})
        self.assertEqual(then["properties"]["rust_preservation_applicability"], {"enum": ["required", "not_applicable"]})
        self.assertEqual(then["properties"]["required_variants"], {"allOf": [
            {"contains": {"const": name}} for name in ("cpp_current", "cpp_optimized", "rust_candidate")]})
        comparisons = then["properties"]["comparisons"]
        self.assertEqual(comparisons["required"], ["cpp_current", "cpp_optimized"])
        for name in ("cpp_current", "cpp_optimized", "rust_current"):
            self.assertEqual(comparisons["properties"][name],
                             {"properties": {"baseline": {"const": name}, "status": {"const": "PASS"},
                                             "upper_bound_limit": {"const": 1 if name == "rust_current" else 0.5}}})
        self.assertEqual(len(then["allOf"]), 3)
        self.assertEqual(then["allOf"][0], {"if": {"properties": {"rust_preservation_applicability": {"const": "required"}},
                                                   "required": ["rust_preservation_applicability"]},
                                         "then": {"properties": {
                                             "required_variants": {"contains": {"const": "rust_current"}},
                                             "comparisons": {"required": ["rust_current"]}}}})
        self.assertEqual(then["allOf"][1], {"if": {"properties": {"rust_preservation_applicability": {"const": "not_applicable"}},
                                                   "required": ["rust_preservation_applicability"]},
                                         "then": {"properties": {
                                             "required_variants": {"not": {"contains": {"const": "rust_current"}}},
                                             "comparisons": {"not": {"required": ["rust_current"]}}}}})
        role_rule = then["allOf"][2]
        self.assertEqual(role_rule["if"], {"properties": {"role": {"const": "unchanged_control"}}, "required": ["role"]})
        for branch, rule in (("then", "interval_contains_one"), ("else", "upper_bound_limit")):
            self.assertEqual(role_rule[branch], {"properties": {"comparisons": {"properties": {
                name: {"properties": {"rule": {"const": rule}}}
                for name in ("cpp_current", "cpp_optimized", "rust_current")}}}})
        global_rule = schema["allOf"][0]
        self.assertEqual(global_rule["if"], case_rule["if"])
        cases = global_rule["then"]["properties"]["cases"]
        self.assertEqual(cases["items"], {"properties": {"status": {"const": "PASS"}}})
        self.assertEqual(cases["allOf"], [{"contains": {"properties": {"role": {"const": role}}, "required": ["role"]}}
                                        for role in ("changed", "unchanged_control")])


    def test_campaign_pass_schema_semantics_offline_draft202012(self):
        # Real validator, no dependency fallback/skip and no remote retrieval.
        # These authored metadata fixtures exercise schema semantics only;
        # they do not attest numerical certificates or actual runtime evidence.
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import ValidationError as SchemaValidationError
        from referencing import Registry, Resource
        from referencing.exceptions import NoSuchResource

        folder = SCRIPT.parent / "schema"
        schema_names = ("campaign-qualification.schema.json", "manifest.schema.json")
        schemas = {}
        for name in schema_names:
            raw = (folder / name).read_bytes()
            self.assertLessEqual(len(raw), 1024 * 1024)
            schemas[name] = json.loads(raw)
        retrieval_attempts = []

        def reject_retrieval(uri):
            retrieval_attempts.append(uri)
            raise NoSuchResource(ref=uri)

        prefix = "https://nzbget.invalid/offline-synthetic-schema/"
        registry = Registry(retrieve=reject_retrieval).with_resources(
            (prefix + name, Resource.from_contents(schema)) for name, schema in schemas.items())
        validator = Draft202012Validator({"$ref": prefix + schema_names[0]}, registry=registry)
        manifest = campaign_manifest()
        profile = copy.deepcopy(manifest["qualification_profile"])
        del profile["variant_bindings"]["rust_current"]
        variants = [name for name in VARIANTS if name != "rust_current"]
        for design in profile["collection_design"].values():
            design["order_cycle"] = [variants, list(reversed(variants))]
        cases = []
        for fixture in manifest["fixtures"]:
            control = fixture["role"] == "unchanged_control"
            ratio = {name: 1 if control else 0.25 for name in ("estimate", "lower", "upper")}
            comparisons = {name: {"baseline": name, "candidate": "rust_candidate", "ratio": ratio,
                                  "upper_bound_limit": 0.5, "rule": "interval_contains_one" if control else "upper_bound_limit",
                                  "status": "PASS", "reasons": []}
                           for name in ("cpp_current", "cpp_optimized")}
            cases.append({"case": fixture["id"], "scope": "complete_caller", "role": fixture["role"],
                          "fixture_sha256": fixture["sha256"], "required_variants": variants,
                          "rust_preservation_applicability": "not_applicable",
                          "collection_design": profile["collection_design"][fixture["id"]],
                          "raw_count": 24, "process_count": 2, "round_counts": {"0": 4, "1": 4},
                          "complete": True, "comparisons": comparisons, "status": "PASS", "reasons": []})
        base = {"schema_version": 1, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
                "testbed": "synthetic-schema-only-no-numerical-runtime-evidence",
                "qualification_profile": profile, "analysis_sha256": "1" * 64,
                "input_hashes": {"manifest_sha256": "2" * 64, "samples_sha256": "3" * 64},
                "eligibility_scope": "numerical_only", "status": "PASS", "reasons": [],
                "methodology": {"fixture": "authored schema metadata only; no timing or certification"}, "cases": cases}
        required = copy.deepcopy(base)
        required["qualification_profile"] = copy.deepcopy(manifest["qualification_profile"])
        for case in required["cases"]:
            case["required_variants"] = list(VARIANTS)
            case["rust_preservation_applicability"] = "required"
            case["collection_design"] = required["qualification_profile"]["collection_design"][case["case"]]
            case["raw_count"] = 32
            case["comparisons"]["rust_current"] = {
                "baseline": "rust_current", "candidate": "rust_candidate",
                "ratio": {"estimate": 1, "lower": 1, "upper": 1}, "upper_bound_limit": 1,
                "rule": "interval_contains_one" if case["role"] == "unchanged_control" else "upper_bound_limit",
                "status": "PASS", "reasons": []}
        incomplete = copy.deepcopy(base)
        incomplete["status"] = "HOLD"
        for case in incomplete["cases"]:
            case.update(status="HOLD", complete=False, comparisons={}, rust_preservation_applicability=None)
        kernel = copy.deepcopy(base)
        kernel["status"] = "HOLD"
        for case in kernel["cases"]:
            case.update(scope="kernel", status="HOLD")
        mixed = copy.deepcopy(base)
        mixed["status"] = "HOLD"
        mixed["cases"][1] = copy.deepcopy(incomplete["cases"][1])
        missing = copy.deepcopy(incomplete)
        for case in missing["cases"]:
            case["complete"] = True
        valid = [("valid_pass_no_current_rust", base), ("valid_pass_required_rust", required),
                 ("valid_incomplete_hold", incomplete), ("valid_kernel_diagnostic", kernel),
                 ("valid_mixed_pass_and_hold", mixed), ("valid_hold_missing_preservation", missing),
                 ("valid_unchanged_control_rule", copy.deepcopy(base))]
        invalid = []
        for identifier in ("pass_empty_comparisons", "pass_missing_cpp_current", "pass_missing_cpp_optimized",
                           "pass_required_rust_missing", "pass_required_rust_hold", "pass_cpp_comparison_hold",
                           "global_pass_has_hold_case", "pass_case_incomplete", "pass_case_kernel",
                           "pass_case_unknown_preservation", "pass_wrong_cpp_baseline_tag",
                           "global_pass_missing_changed_role", "global_pass_missing_control_role",
                           "pass_cpp_current_wrong_limit", "pass_cpp_optimized_wrong_limit",
                           "pass_required_rust_wrong_limit", "pass_control_required_rust_wrong_limit",
                           "pass_changed_cpp_current_wrong_rule", "pass_changed_cpp_optimized_wrong_rule",
                           "pass_changed_rust_wrong_rule", "pass_control_cpp_current_wrong_rule",
                           "pass_control_cpp_optimized_wrong_rule", "pass_control_rust_wrong_rule",
                           "pass_missing_required_cpp_current_variant", "pass_missing_required_cpp_optimized_variant",
                           "pass_missing_required_rust_candidate_variant", "pass_required_rust_missing_declaration",
                           "pass_not_applicable_declared_rust", "pass_not_applicable_comparison_rust",
                           "pass_not_applicable_declared_and_compared_rust"):
            rust_required = identifier.startswith("pass_required_rust_") or identifier in (
                "pass_changed_rust_wrong_rule", "pass_control_rust_wrong_rule",
                "pass_control_required_rust_wrong_limit")
            artifact = copy.deepcopy(required if rust_required else base)
            case = artifact["cases"][1 if identifier.startswith("pass_control_") else 0]
            if not identifier.startswith("global_"):
                artifact["status"] = "HOLD"  # Isolate the PASS case rule.
            if identifier == "pass_empty_comparisons":
                case["comparisons"] = {}
            elif identifier == "pass_missing_cpp_current":
                del case["comparisons"]["cpp_current"]
            elif identifier == "pass_missing_cpp_optimized":
                del case["comparisons"]["cpp_optimized"]
            elif identifier == "pass_required_rust_missing":
                del case["comparisons"]["rust_current"]
            elif identifier == "pass_required_rust_hold":
                case["comparisons"]["rust_current"]["status"] = "HOLD"
            elif identifier == "pass_cpp_comparison_hold":
                case["comparisons"]["cpp_optimized"]["status"] = "HOLD"
            elif identifier == "global_pass_has_hold_case":
                artifact["cases"][1] = copy.deepcopy(incomplete["cases"][1])
            elif identifier == "pass_case_incomplete":
                case["complete"] = False
            elif identifier == "pass_case_kernel":
                case["scope"] = "kernel"
            elif identifier == "pass_case_unknown_preservation":
                case["rust_preservation_applicability"] = None
            elif identifier == "pass_wrong_cpp_baseline_tag":
                case["comparisons"]["cpp_optimized"]["baseline"] = "cpp_current"
            elif identifier == "global_pass_missing_changed_role":
                artifact["cases"] = [artifact["cases"][1]]
            elif identifier == "global_pass_missing_control_role":
                artifact["cases"] = [case]
            elif identifier in ("pass_cpp_current_wrong_limit", "pass_cpp_optimized_wrong_limit"):
                name = "cpp_current" if identifier == "pass_cpp_current_wrong_limit" else "cpp_optimized"
                case["comparisons"][name]["upper_bound_limit"] = 1
            elif identifier == "pass_required_rust_wrong_limit":
                case["comparisons"]["rust_current"]["upper_bound_limit"] = 0.5
            elif identifier == "pass_control_required_rust_wrong_limit":
                # The required-preservation seed is accepted above; change ONLY
                # the control Rust limit, without a not_applicable conflict.
                case["comparisons"]["rust_current"]["upper_bound_limit"] = 0.5
            elif identifier.startswith("pass_missing_required_"):
                name = identifier.removeprefix("pass_missing_required_").removesuffix("_variant")
                case["required_variants"].remove(name)
            elif identifier == "pass_required_rust_missing_declaration":
                case["required_variants"].remove("rust_current")
            elif identifier.startswith("pass_not_applicable_"):
                if identifier in ("pass_not_applicable_declared_rust", "pass_not_applicable_declared_and_compared_rust"):
                    case["required_variants"].append("rust_current")
                if identifier in ("pass_not_applicable_comparison_rust", "pass_not_applicable_declared_and_compared_rust"):
                    case["comparisons"]["rust_current"] = copy.deepcopy(required["cases"][0]["comparisons"]["rust_current"])
            elif identifier.startswith("pass_changed_"):
                name = ("rust_current" if identifier == "pass_changed_rust_wrong_rule" else
                        "cpp_current" if identifier == "pass_changed_cpp_current_wrong_rule" else "cpp_optimized")
                case["comparisons"][name]["rule"] = "interval_contains_one"
            elif identifier.startswith("pass_control_"):
                name = ("rust_current" if identifier == "pass_control_rust_wrong_rule" else
                        "cpp_current" if identifier == "pass_control_cpp_current_wrong_rule" else "cpp_optimized")
                case["comparisons"][name]["rule"] = "upper_bound_limit"
            invalid.append((identifier, artifact))
        self.assertEqual((len(invalid), len(valid)), (30, 7))
        self.assertEqual(len({identifier for identifier, _ in invalid + valid}), 37)
        for identifier, artifact in valid:
            with self.subTest(scenario=identifier):
                validator.validate(artifact)
        for identifier, artifact in invalid:
            with self.subTest(scenario=identifier):
                with self.assertRaises(SchemaValidationError):
                    validator.validate(artifact)
        self.assertEqual(retrieval_attempts, [], "schema references escaped the fixed offline registry")


if __name__ == "__main__":
    unittest.main()
