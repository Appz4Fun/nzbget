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
        # Case-insensitive Git identity is campaign-local; original data stays
        # unmodified and the ordinary generic digest contract is unchanged.
        import runpy
        design = runpy.run_path(str(SCRIPT), run_name="campaign_sha_source_fixture")["campaign_design"]
        for variant, field in (("cpp_current", "base_sha"), ("rust_current", "base_sha"),
                               ("rust_candidate", "candidate_sha")):
            for uppercase_binding in (True, False):
                with self.subTest(variant=variant, uppercase_binding=uppercase_binding):
                    m = campaign_manifest()
                    binding = m["qualification_profile"]["variant_bindings"][variant]
                    if uppercase_binding:
                        binding["source_sha"] = binding["source_sha"].upper()
                    else:
                        m[field] = m[field].upper()
                    original = json.dumps(m, sort_keys=True)
                    design(m)
                    self.assertEqual(json.dumps(m, sort_keys=True), original)
        m = campaign_manifest()
        m["base_sha"], m["candidate_sha"] = m["base_sha"].upper(), m["candidate_sha"].upper()
        for binding in m["qualification_profile"]["variant_bindings"].values():
            binding["source_sha"] = binding["source_sha"].upper()
        design(m)
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
        self.assertEqual(then["properties"]["collection_design"],
                         {"$ref": "manifest.schema.json#/$defs/campaign_collection_design"})
        manifest_schema = json.loads((SCRIPT.parent / "schema" / "manifest.schema.json").read_text())
        profile_design = manifest_schema["$defs"]["campaign_profile"]["properties"]["collection_design"]
        self.assertEqual(profile_design["additionalProperties"], {"$ref": "#/$defs/campaign_collection_design"})
        definition = manifest_schema["$defs"]["campaign_collection_design"]
        self.assertEqual(definition["required"], ["elapsed_floor_ns", "process_count", "round_count", "order_cycle"])
        self.assertFalse(definition["additionalProperties"])
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
        certificate = schema["$defs"]["numerical_certificate"]
        self.assertEqual(schema["$defs"]["comparison"]["properties"]["certificate"],
                         {"$ref": "#/$defs/numerical_certificate"})
        comparison_rule = schema["$defs"]["comparison"]["allOf"][0]
        self.assertEqual(comparison_rule["if"], case_rule["if"])
        self.assertEqual(comparison_rule["then"]["required"], ["certificate"])
        self.assertEqual(set(certificate["required"]), {"policy_sha256", "bindings", "method_id",
                         "bootstrap_multiplicities_sha256", "bootstrap_multiplicities_encoding",
                         "common_root_degree", "precision", "relations", "proof", "quantile_ranks",
                         "width_policy_rational", "bounds", "bounding_contributors", "rank_enclosures",
                         "exact_order_statistics", "work_cumulative", "peak_cache_payload_bytes", "display"})
        self.assertEqual(schema["$defs"]["certificate_decimal"]["maxLength"], 672)
        self.assertEqual(certificate["properties"]["precision"], {"enum": [80, 160, 320, 640]})
        self.assertEqual(certificate["properties"]["width_policy_rational"]["properties"]["numerator"]["maxLength"], 2467)
        self.assertEqual(schema["$defs"]["certificate_exact_ranks"]["required"], ["124", "125", "4874", "4875"])
        self.assertEqual(len(schema["allOf"]), 4)
        self.assertEqual(schema["allOf"][3]["then"]["properties"]["methodology"]["required"],
                         ['analysis_identity', 'arithmetic', 'arithmetic_policy_sha256', 'bootstrap_replicates', 'comparison_rng', 'coverage', 'interval', 'limits', 'outliers', 'ratio_estimator', 'resampling_unit', 'seed', 'policy', 'exact_width_policy', 'arithmetic_work_cumulative'])
        self.assertIn("qualification_contract_sha256", certificate["properties"]["bindings"]["required"])
        self.assertEqual(certificate["properties"]["bindings"]["properties"]["qualification_contract_sha256"]["$ref"],
                         "manifest.schema.json#/$defs/sha256")
        self.assertEqual(len(item["allOf"]), 4)
        self.assertEqual(item["allOf"][1]["then"]["required"], ["provenance"])
        self.assertEqual(item["properties"]["provenance"], {"type": "object"})
        self.assertEqual(item["allOf"][2], {
            "if": {"properties": {"role": {"const": "unchanged_control"}}, "required": ["role"]},
            "then": {"required": ["provenance"], "properties": {"provenance": {"type": "object", "minProperties": 1}}}})
        observed = item["allOf"][3]
        self.assertEqual(observed["if"], {"required": ["comparisons"], "properties": {"comparisons": {
            "anyOf": [{"required": [name], "properties": {name: {"required": ["status"],
                "properties": {"status": {"const": "PASS"}}}}}
                for name in ("cpp_current", "cpp_optimized", "rust_current")]}}})
        self.assertEqual(observed["then"]["properties"], {
            "complete": {"const": True},
            "collection_design": {"$ref": "manifest.schema.json#/$defs/campaign_collection_design"},
            "process_count": {"minimum": 1}, "raw_count": {"minimum": 1},
            "round_counts": {"minProperties": 1, "maxProperties": 128,
                "additionalProperties": {"type": "integer", "minimum": 1, "maximum": 50000}},
            "required_variants": {"allOf": [{"contains": {"const": name}}
                for name in ("cpp_current", "cpp_optimized", "rust_candidate")]},
            "comparisons": {"required": ["cpp_current", "cpp_optimized"]}})
        self.assertEqual(observed["then"]["allOf"], [
            {"if": {"properties": {"scope": {"const": "complete_caller"}}, "required": ["scope"]},
             "then": {"properties": {"rust_preservation_applicability": {"enum": ["required", "not_applicable"]}}}},
            {"if": {"properties": {"rust_preservation_applicability": {"const": "required"}},
                    "required": ["rust_preservation_applicability"]},
             "then": {"properties": {"required_variants": {"contains": {"const": "rust_current"}},
                                      "comparisons": {"required": ["rust_current"]}}},
             "else": {"properties": {"comparisons": {"not": {"required": ["rust_current"]}}}}}])
        for reason_rule in (schema["allOf"][0], item["allOf"][0],
                            schema["$defs"]["comparison"]["allOf"][0]):
            self.assertEqual(reason_rule["then"]["properties"]["reasons"], {"maxItems": 0})
        self.assertIn("retained manifest bytes", schema["$defs"]["exact_width_provenance"]["$comment"])
        self.assertEqual(schema["$defs"]["campaign_qualification_policy"]["required"],
                         ["min_processes", "min_rounds", "min_each_order", "max_relative_ci_width"])
        for index, preservation, names in ((1, False, ["cpp_current", "cpp_optimized", "rust_candidate"]),
                                           (2, True, ["rust_current"])):
            properties = {"status": {"const": "PASS"}}
            required = ["status"]
            if preservation:
                properties["rust_preservation_applicability"] = {"const": "required"}
                required.append("rust_preservation_applicability")
            self.assertEqual(schema["allOf"][index], {
                "if": {"properties": {"cases": {"contains": {"properties": properties, "required": required}}},
                       "required": ["cases"]},
                "then": {"properties": {"qualification_profile": {"properties": {
                    "variant_bindings": {"required": names}}}}}})


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
        def synthetic_certificate(identity, fixture_sha, baseline, control):
            # Authored metadata SHAPE only: dummy hash/counter assertions below
            # are not executed numerical proof, RNG output or actual lineage.
            ratio = "1" if control or baseline == "rust_current" else "0.25"
            log = "0" if ratio == "1" else "-1.3862943611198906"
            relation = "EQ" if ratio == "1" else "LT"
            keys = ("upper_vs_limit", "lower_vs_one", "upper_vs_one", "width_vs_policy")
            return {
                "policy_sha256": "4fe3e8086c88da789540bdbed6825e65f8adc18c41c73840a3aaaf7895092d39",
                "bindings": {"analysis_sha256": "1" * 64,
                             "input_hashes": {"manifest_sha256": "2" * 64, "samples_sha256": "3" * 64},
                             "plan_sha256": "d" * 64, "fixture_sha256": fixture_sha,
                             "case": identity, "baseline": baseline, "candidate": "rust_candidate",
                             "qualification_contract_sha256": "6" * 64},
                "method_id": "campaign-exact-threshold-source-design-20261014-v2",
                "bootstrap_multiplicities_sha256": "4" * 64,
                "bootstrap_multiplicities_encoding": "5000 rows in replicate order; decimal process counts comma-separated plus LF",
                "common_root_degree": 8, "precision": 80,
                "relations": {**{key: relation for key in keys}, "width_vs_policy": "LT"},
                "proof": {key: "uniform_exact_process_product" for key in keys},
                "quantile_ranks": {"lower": [[124, 1, 40], [125, 39, 40]],
                                   "upper": [[4874, 39, 40], [4875, 1, 40]]},
                "width_policy_rational": {"numerator": "1", "denominator": "100"},
                "bounds": {name: [ratio, ratio] for name in ("lower", "upper", "estimate")},
                "bounding_contributors": None,
                "rank_enclosures": {"route": "uniform_exact_process_product",
                                    "uniform": {"log": [log, log], "ratio": [ratio, ratio]}, "selected": None},
                "exact_order_statistics": {str(rank): {"replicate_id": rank, "process_multiplicities": [2, 0]}
                                           for rank in (124, 125, 4874, 4875)},
                "work_cumulative": {"exp_calls": 2}, "peak_cache_payload_bytes": 0,
                "display": "approximate only; certified relations decide eligibility"}
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
                                  "status": "PASS", "reasons": [],
                                  "certificate": synthetic_certificate(fixture["id"], fixture["sha256"], name, control)}
                           for name in ("cpp_current", "cpp_optimized")}
            cases.append({"case": fixture["id"], "scope": "complete_caller", "role": fixture["role"],
                          "fixture_sha256": fixture["sha256"], "required_variants": variants,
                          "rust_preservation_applicability": "not_applicable",
                          "collection_design": profile["collection_design"][fixture["id"]],
                          "raw_count": 24, "process_count": 2, "round_counts": {"0": 4, "1": 4},
                          "complete": True, "comparisons": comparisons, "status": "PASS", "reasons": [],
                          "provenance": {"rust_preservation_rationale": "Authored schema-only rationale; no actual review attestation"}})
        base = {"schema_version": 1, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
                "testbed": "synthetic-schema-only-no-numerical-runtime-evidence",
                "qualification_profile": profile, "analysis_sha256": "1" * 64,
                "input_hashes": {"manifest_sha256": "2" * 64, "samples_sha256": "3" * 64},
                "eligibility_scope": "numerical_only", "status": "PASS", "reasons": [],
                "methodology": {'analysis_identity': 'invocation source snapshot sampled for stability; not loaded-code or pre-load race authentication','arithmetic': 'campaign directed enclosures with bounded exact equality certification; floats display only','comparison_rng': 'each named comparison resets the fixed seed','coverage': 'per-case intervals; no simultaneous family coverage guarantee','interval': '95% percentile bootstrap; linear quantiles at 0.025 and 0.975','limits': 'numerical eligibility only; declarations do not attest caller/domain/ABI, native execution, build lineage, independence, reviewed applicability, retirement or hold release','outliers': 'all retained; no trimming or independent round resampling','ratio_estimator': 'exp(mean(process mean(log(paired candidate/baseline ns/op))))','resampling_unit': 'whole process cluster; every paired round retained', "arithmetic_work_cumulative": {},
                    "seed": 20261011, "bootstrap_replicates": 5000, "policy": copy.deepcopy(manifest["qualification_policy"]),
                    "arithmetic_policy_sha256": "4fe3e8086c88da789540bdbed6825e65f8adc18c41c73840a3aaaf7895092d39",
                    "exact_width_policy": {"source": "retained_manifest_json_number_token",
                        "manifest_sha256": "2" * 64, "token_sha256": "5" * 64, "token_bytes": 4,
                        "default_decimal": None, "numerator": "1", "denominator": "100",
                        "display_policy_width": "approximate binary float only; exact rational is authoritative"}}, "cases": cases}
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
                "status": "PASS", "reasons": [],
                "certificate": synthetic_certificate(case["case"], case["fixture_sha256"], "rust_current",
                                                     case["role"] == "unchanged_control")}
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
        partial_hold = copy.deepcopy(incomplete)
        partial_hold["cases"][0]["collection_design"] = {}
        two_bindings_hold = copy.deepcopy(incomplete)
        del two_bindings_hold["qualification_profile"]["variant_bindings"]["rust_candidate"]
        valid.extend((("valid_hold_partial_case_design", partial_hold),
                      ("valid_hold_two_profile_bindings", two_bindings_hold)))
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
        for identifier in ("pass_missing_binding_cpp_current", "pass_missing_binding_cpp_optimized",
                           "pass_missing_binding_rust_candidate", "pass_missing_binding_rust_current",
                           "mixed_hold_with_pass_missing_candidate_binding",
                           "pass_design_missing_elapsed_floor_ns", "pass_design_missing_process_count",
                           "pass_design_missing_round_count", "pass_design_missing_order_cycle",
                           "pass_design_zero_floor", "pass_design_unknown_field", "pass_design_malformed_cycle"):
            artifact = copy.deepcopy(required if identifier == "pass_missing_binding_rust_current" else
                                     mixed if identifier == "mixed_hold_with_pass_missing_candidate_binding" else base)
            artifact["status"] = "HOLD"  # Root checks must still bind its PASS case.
            case = artifact["cases"][0]
            if identifier.startswith("pass_missing_binding_"):
                del artifact["qualification_profile"]["variant_bindings"][identifier.removeprefix("pass_missing_binding_")]
            elif identifier == "mixed_hold_with_pass_missing_candidate_binding":
                del artifact["qualification_profile"]["variant_bindings"]["rust_candidate"]
            else:
                # Break the authored case/profile alias: only the case design
                # is malformed, proving the PASS-case shape rule independently.
                case["collection_design"] = copy.deepcopy(case["collection_design"])
                design = case["collection_design"]
                if identifier.startswith("pass_design_missing_"):
                    del design[identifier.removeprefix("pass_design_missing_")]
                elif identifier == "pass_design_zero_floor":
                    design["elapsed_floor_ns"] = 0
                elif identifier == "pass_design_unknown_field":
                    design["extra"] = 1
                else:
                    design["order_cycle"][0] = ["cpp_current", "cpp_current"]
            invalid.append((identifier, artifact))
        self.assertEqual((len(invalid), len(valid)), (42, 9))
        self.assertEqual(len({identifier for identifier, _ in invalid + valid}), 51)
        for identifier, artifact in valid:
            with self.subTest(scenario=identifier):
                validator.validate(artifact)
        for identifier, artifact in invalid:
            with self.subTest(scenario=identifier):
                with self.assertRaises(SchemaValidationError):
                    validator.validate(artifact)
        self.assertEqual(retrieval_attempts, [], "schema references escaped the fixed offline registry")


    def test_campaign_artifact_associations_use_actual_production_validator(self):
        # Call the actual production application check, not a duplicate schema
        # evaluator. The CLI seed is synthetic and confers no native proof.
        import runpy
        loaded = runpy.run_path(str(SCRIPT), run_name="campaign_association_source_fixture")
        actual_validate = loaded["validate_campaign_artifact_associations"]
        retained_manifest = json.dumps(campaign_manifest()).encode()
        retained_samples = None
        preimages = {hashlib.sha256(retained_manifest).hexdigest(): retained_manifest}
        def attach(artifact, declaration):
            raw = json.dumps(declaration).encode()
            key = hashlib.sha256(raw).hexdigest()
            preimages[key] = raw
            artifact["input_hashes"]["manifest_sha256"] = key
            artifact["methodology"]["exact_width_policy"]["manifest_sha256"] = key
            for item in artifact["cases"]:
                for check in item["comparisons"].values():
                    if isinstance(check.get("certificate"), dict):
                        check["certificate"]["bindings"]["input_hashes"]["manifest_sha256"] = key
        def validate(artifact):
            return actual_validate(artifact, manifest_bytes=preimages[
                artifact["input_hashes"]["manifest_sha256"].lower()], sample_bytes=retained_samples)
        error = loaded["ValidationError"]
        def rebind(artifact):
            profile = artifact["qualification_profile"]
            for item in artifact["cases"]:
                for baseline, check in item["comparisons"].items():
                    if (item["case"] in profile["collection_design"] and
                            {baseline, "rust_candidate"} <= profile["variant_bindings"].keys() and
                            isinstance(check.get("certificate"), dict)):
                        check["certificate"]["bindings"]["qualification_contract_sha256"] = loaded[
                            "campaign_qualification_contract_sha256"](artifact["methodology"]["policy"],
                                profile["variant_bindings"], item, profile["collection_design"][item["case"]], baseline)
        seed, seed_output = self.valid()
        retained_samples = (seed_output.parent / "samples.jsonl").read_bytes()
        self.assertLessEqual(len(retained_samples), 65536)
        no_current = copy.deepcopy(seed)
        del no_current["qualification_profile"]["variant_bindings"]["rust_current"]
        for case in no_current["cases"]:
            case["required_variants"].remove("rust_current")
            case["raw_count"] = 24
            case["rust_preservation_applicability"] = "not_applicable"
            case["provenance"] = {"rust_preservation_rationale": "Authored metadata only; independent reviewed applicability remains unknown"}
            del case["comparisons"]["rust_current"]
            design = no_current["qualification_profile"]["collection_design"][case["case"]]
            design["order_cycle"] = [[v for v in order if v != "rust_current"] for order in design["order_cycle"]]
            case["collection_design"] = copy.deepcopy(design)
        mixed = copy.deepcopy(seed)
        mixed["status"] = "HOLD"
        mixed["cases"][1] = copy.deepcopy(no_current["cases"][1])
        mixed["cases"][1]["status"] = "HOLD"
        mixed["qualification_profile"]["collection_design"][mixed["cases"][1]["case"]] = copy.deepcopy(
            mixed["cases"][1]["collection_design"])
        held = copy.deepcopy(no_current)
        held["status"] = "HOLD"
        del held["qualification_profile"]["variant_bindings"]["cpp_optimized"]
        for case in held["cases"]:
            case.update(status="HOLD", scope="kernel", comparisons={}, rust_preservation_applicability=None)
            case["required_variants"].remove("cpp_optimized")
            design = held["qualification_profile"]["collection_design"][case["case"]]
            design["order_cycle"] = [[v for v in order if v != "cpp_optimized"] for order in design["order_cycle"]]
            case["collection_design"] = copy.deepcopy(design)
        # Independent prospective declarations for the authored NA/mixed
        # positives; never construct a preimage from a mutated artifact.
        na_source = campaign_manifest()
        for fixture in na_source["fixtures"]:
            fixture["required_variants"].remove("rust_current")
            fixture["rust_preservation_applicability"] = "not_applicable"
            fixture["provenance"] = {"rust_preservation_rationale": "Authored metadata only; independent reviewed applicability remains unknown"}
            design = na_source["qualification_profile"]["collection_design"][fixture["id"]]
            design["order_cycle"] = [[v for v in order if v != "rust_current"] for order in design["order_cycle"]]
        del na_source["qualification_profile"]["variant_bindings"]["rust_current"]
        mixed_source = campaign_manifest()
        mixed_source["fixtures"][1] = copy.deepcopy(na_source["fixtures"][1])
        mixed_source["qualification_profile"]["collection_design"]["unchanged"] = copy.deepcopy(
            na_source["qualification_profile"]["collection_design"]["unchanged"])
        for artifact, declaration in ((seed, campaign_manifest()), (no_current, na_source), (mixed, mixed_source)):
            attach(artifact, declaration)
        for artifact in (seed, no_current, mixed, held):
            rebind(artifact)
        for identifier, artifact in (("unchanged_required_producer", seed),
                                     ("mixed_required_not_applicable_and_hold_union", mixed),
                                     ("all_hold_no_main_variant_gate", held)):
            with self.subTest(valid=identifier):
                before = json.dumps(artifact, sort_keys=True)
                if identifier == "all_hold_no_main_variant_gate":
                    # Existing no-witness HOLD positive also proves the retained
                    # preimage exemption; no extra direct scenario/call added.
                    self.assertIsNone(actual_validate(artifact))
                else:
                    self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), before)
        identifiers = ("duplicate_case_id", "missing_case", "extra_profile_design_id", "missing_profile_design_id",
                       "renamed_case_without_design", "different_case_floor", "different_case_order_cycle",
                       "missing_binding_union_member", "extra_binding_union_member", "mixed_union_missing_current_rust",
                       "nonobject_case_design", "nonobject_profile_design", "global_hold_pass_missing_cpp_current",
                       "global_hold_pass_missing_cpp_optimized", "global_hold_pass_missing_rust_candidate",
                       "global_hold_pass_required_missing_rust_declaration", "global_hold_pass_required_missing_rust_comparison",
                       "global_hold_pass_na_declared_rust", "global_hold_pass_na_compared_rust",
                       "global_hold_pass_unknown_applicability")
        self.assertEqual((len(identifiers), len(set(identifiers))), (20, 20))
        for identifier in identifiers:
            artifact = copy.deepcopy(no_current if identifier == "extra_binding_union_member" else
                                     mixed if identifier == "mixed_union_missing_current_rust" else seed)
            case = artifact["cases"][0]
            profile = artifact["qualification_profile"]
            if identifier == "duplicate_case_id":
                artifact["cases"].append(copy.deepcopy(case))
            elif identifier == "missing_case":
                artifact["cases"].pop()
            elif identifier == "extra_profile_design_id":
                profile["collection_design"]["extra"] = copy.deepcopy(case["collection_design"])
            elif identifier == "missing_profile_design_id":
                del profile["collection_design"][case["case"]]
            elif identifier == "renamed_case_without_design":
                case["case"] = "renamed"
            elif identifier == "different_case_floor":
                case["collection_design"]["elapsed_floor_ns"] += 1
            elif identifier == "different_case_order_cycle":
                case["collection_design"]["order_cycle"].reverse()
            elif identifier == "missing_binding_union_member":
                del profile["variant_bindings"]["cpp_optimized"]
            elif identifier == "extra_binding_union_member":
                profile["variant_bindings"]["rust_current"] = copy.deepcopy(
                    seed["qualification_profile"]["variant_bindings"]["rust_current"])
            elif identifier == "mixed_union_missing_current_rust":
                del profile["variant_bindings"]["rust_current"]
            elif identifier == "nonobject_case_design":
                case["collection_design"] = []
            elif identifier == "nonobject_profile_design":
                profile["collection_design"][case["case"]] = []
            else:
                artifact["status"] = "HOLD"
                artifact["cases"][1]["status"] = "HOLD"
                # The second case still declares all four variants, keeping
                # union/bindings equal and isolating the first PASS case check.
                if identifier.startswith("global_hold_pass_missing_"):
                    case["required_variants"].remove(identifier.removeprefix("global_hold_pass_missing_"))
                elif identifier == "global_hold_pass_required_missing_rust_declaration":
                    case["required_variants"].remove("rust_current")
                elif identifier == "global_hold_pass_required_missing_rust_comparison":
                    del case["comparisons"]["rust_current"]
                elif identifier == "global_hold_pass_na_declared_rust":
                    case["rust_preservation_applicability"] = "not_applicable"
                    del case["comparisons"]["rust_current"]
                elif identifier == "global_hold_pass_na_compared_rust":
                    case["rust_preservation_applicability"] = "not_applicable"
                    case["required_variants"].remove("rust_current")
                else:
                    case["rust_preservation_applicability"] = None
                # Preserve the prior isolated membership/applicability oracle:
                # update both matching designs after changing declarations, so
                # the new shared permutation check is not a confounding failure.
                design = profile["collection_design"][case["case"]]
                design["order_cycle"] = [[v for v in order if v in case["required_variants"]]
                                         for order in design["order_cycle"]]
                case["collection_design"] = copy.deepcopy(design)
                case["raw_count"] = design["process_count"] * design["round_count"] * len(case["required_variants"])
            rebind(artifact)
            original = json.dumps(artifact, sort_keys=True)
            with self.subTest(invalid=identifier):
                with self.assertRaises(error):
                    validate(artifact)
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)

    def test_campaign_artifact_association_failure_blocks_real_generation(self):
        historical = {name: b"historical generic evidence" for name in GENERIC_ARTIFACTS}
        def prepare(manifest_path, sample_path, output):
            output.mkdir()
            for name, raw in historical.items():
                (output / name).write_bytes(raw)
            for name in ARTIFACTS:
                (output / name).write_bytes(b"stale campaign PASS")
        wrapper = (
            "import runpy,sys\n"
            "main=runpy.run_path(sys.argv[1],run_name='campaign_generation_fixture')['main']\n"
            "def reject(artifact, *, manifest_bytes=None, sample_bytes=None):\n"
            " raise main.__globals__['ValidationError']('synthetic association boundary rejected')\n"
            "main.__globals__['validate_campaign_artifact_associations']=reject\n"
            "sys.exit(main(sys.argv[2:]))\n")
        result, output = self.invoke(wrapper_source=wrapper, prepare=prepare)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("synthetic association boundary rejected", result.stderr)
        self.assertTrue(all(not (output / name).exists() for name in ARTIFACTS))
        self.assertEqual({name: (output / name).read_bytes() for name in GENERIC_ARTIFACTS}, historical)


    def test_campaign_artifact_certificates_and_consumer_invariants(self):
        # One actual uniform and one nonuniform SYNTHETIC CLI seed; mutations
        # exercise the production consumer checks without replaying any math.
        import runpy
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import ValidationError as SchemaValidationError
        from referencing import Registry, Resource
        from referencing.exceptions import NoSuchResource
        loaded = runpy.run_path(str(SCRIPT), run_name="campaign_certificate_source_fixture")
        actual_validate, error = loaded["validate_campaign_artifact_associations"], loaded["ValidationError"]
        base_manifest_bytes = json.dumps(campaign_manifest()).encode()
        retained_preimages = {hashlib.sha256(base_manifest_bytes).hexdigest(): base_manifest_bytes,
                              hashlib.sha256(b"{}").hexdigest(): b"{}"}
        sample_preimages = {}
        default_sample_bytes = None
        missing_sample = object()
        def validate(artifact, *, sample_bytes=missing_sample):
            # Predeclared source-fixture bytes only, never a duplicate validator
            # or a synthesized preimage from the artifact's asserted rational.
            key = artifact["input_hashes"]["manifest_sha256"].lower()
            raw = retained_preimages.get(key, base_manifest_bytes)
            if sample_bytes is missing_sample:
                sample_bytes = sample_preimages.get(artifact["input_hashes"]["samples_sha256"].lower(), default_sample_bytes)
            return actual_validate(artifact, manifest_bytes=raw, sample_bytes=sample_bytes)
        def rebind(artifact):
            profile = artifact["qualification_profile"]
            for item in artifact["cases"]:
                for baseline, check in item["comparisons"].items():
                    check["certificate"]["bindings"]["qualification_contract_sha256"] = loaded[
                        "campaign_qualification_contract_sha256"](artifact["methodology"]["policy"],
                            profile["variant_bindings"], item, profile["collection_design"][item["case"]], baseline)
        def retain(artifact, declaration, token=None):
            # Source fixture declarations are selected independently below.
            # This changes raw identity references only, never contract digests.
            raw = json.dumps(declaration).encode()
            declared_token = json.dumps(declaration["qualification_policy"]["max_relative_ci_width"]).encode()
            if token is not None:
                needle = b'"max_relative_ci_width": ' + declared_token
                self.assertEqual(raw.count(needle), 1)
                raw = raw.replace(needle, b'"max_relative_ci_width": ' + token)
                declared_token = token
            key = hashlib.sha256(raw).hexdigest()
            retained_preimages[key] = raw
            artifact["input_hashes"]["manifest_sha256"] = key
            artifact["methodology"]["exact_width_policy"].update(
                manifest_sha256=key, token_sha256=hashlib.sha256(declared_token).hexdigest(),
                token_bytes=len(declared_token))
            for item in artifact["cases"]:
                for check in item["comparisons"].values():
                    if isinstance(check.get("certificate"), dict) and "bindings" in check["certificate"]:
                        check["certificate"]["bindings"]["input_hashes"]["manifest_sha256"] = key
        rationale = "Authored source-bound metadata rationale only; no external review attestation"
        def source_fixture(label):
            # Literal source variants for existing diagnostic oracles. The
            # artifact under validation is never an input to this constructor.
            m = campaign_manifest()
            f, d = m["fixtures"][0], m["qualification_profile"]["collection_design"]["changed"]
            if label in ("optimized_CPP_distinct_imported_sha", "artifact_cpp_optimized_source_sha_changed"):
                m["qualification_profile"]["variant_bindings"]["cpp_optimized"]["source_sha"] = "e" * 40
            if label in ("kernel_PASS_comparison_witness_under_HOLD", "complete_kernel_PASS_diagnostic",
                         "entry_kernel_null_optional_rust_no_preservation_comparison",
                         "entry_kernel_NA_optional_rust_no_preservation_comparison", "kernel_NA_mixed_HOLD_preserved",
                         "entry_kernel_required_rust_full_keys", "entry_kernel_null_extra_rust_comparison",
                         "entry_kernel_NA_extra_rust_comparison"):
                f["scope"] = "kernel"
                if label in ("entry_kernel_NA_optional_rust_no_preservation_comparison", "kernel_NA_mixed_HOLD_preserved",
                             "entry_kernel_NA_extra_rust_comparison"):
                    f["rust_preservation_applicability"] = "not_applicable"
                elif label != "entry_kernel_required_rust_full_keys":
                    f.pop("rust_preservation_applicability")
            if label in ("actual_one_process_HOLD", "entry_actual_undersized_all_HOLD",
                         "actual_undersized_comparisons_HOLD", "one_process_relabelled_PASS",
                         "PASS_comparison_under_HOLD_one_process"):
                for design in m["qualification_profile"]["collection_design"].values():
                    design["process_count"] = 1
            if label in ("minimum_each_order_exact_bound",):
                m["qualification_policy"]["min_each_order"] = 2
            if label in ("HOLD_rounds_below_policy", "policy_min_rounds_above_design"):
                m["qualification_policy"]["min_rounds"] = 6
            if label == "HOLD_processes_below_policy8":
                m["qualification_policy"]["min_processes"] = 8
            if label == "policy_min_each_order_above_repetitions":
                m["qualification_policy"].update(min_rounds=6, min_each_order=3)
            if label == "lowered_min_rounds4_to2_stale_contract":
                m["qualification_policy"]["min_rounds"] = 2
            if label in ("single_order_cycle_PASS", "unequal_order_cycle_PASS", "PASS_comparison_under_HOLD_single_order"):
                forward, reverse = copy.deepcopy(d["order_cycle"])
                d["order_cycle"] = [forward, forward, forward, reverse] if label == "unequal_order_cycle_PASS" else [forward]
            if label.startswith("NA_") or label in ("authored_NA_valid_rationale", "entry_complete_caller_NA_CPP_keys"):
                f["required_variants"].remove("rust_current")
                f["rust_preservation_applicability"] = "not_applicable"
                f["provenance"] = {"rust_preservation_rationale": rationale}
                d["order_cycle"] = [[v for v in order if v != "rust_current"] for order in d["order_cycle"]]
                if label == "NA_changed_rationale_stale_contract":
                    f["provenance"]["rust_preservation_rationale"] = "Another bounded printable rationale assertion"
            omissions = {"entry_missing_" + v: v for v in ("cpp_current", "cpp_optimized", "rust_candidate")}
            if label in omissions or label.startswith("entry_required_rust_undeclared_"):
                v = omissions.get(label, "rust_current")
                f["required_variants"].remove(v)
                d["order_cycle"] = [[x for x in order if x != v] for order in d["order_cycle"]]
                if v == "cpp_optimized":
                    m["comparison"]["baseline"] = "cpp_current"
                if label.endswith("_kernel"):
                    f["scope"] = "kernel"
            if label == "entry_complete_caller_null_applicability":
                f.pop("rust_preservation_applicability")
            if label.startswith("artifact_") and label != "artifact_cpp_optimized_source_sha_changed":
                name = label.removeprefix("artifact_").removesuffix("_changed")
                v = next(v for v in VARIANTS if name.startswith(v + "_"))
                m["qualification_profile"]["variant_bindings"][v][name.removeprefix(v + "_")] = "0" * 64
            return m
        retrieval_attempts = []
        def reject_retrieval(uri):
            retrieval_attempts.append(uri)
            raise NoSuchResource(ref=uri)
        prefix = "https://nzbget.invalid/offline-certificate-schema/"
        schemas = {}
        for name in ("campaign-qualification.schema.json", "manifest.schema.json"):
            raw = (SCRIPT.parent / "schema" / name).read_bytes()
            self.assertLessEqual(len(raw), 1024 * 1024)
            schemas[name] = json.loads(raw)
        registry = Registry(retrieve=reject_retrieval).with_resources(
            (prefix + name, Resource.from_contents(schema)) for name, schema in schemas.items())
        validator = Draft202012Validator({"$ref": prefix + "campaign-qualification.schema.json"}, registry=registry)
        uniform, uniform_output = self.valid()
        default_sample_bytes = (uniform_output.parent / "samples.jsonl").read_bytes()
        self.assertLessEqual(len(default_sample_bytes), 65536)
        sample_preimages[hashlib.sha256(default_sample_bytes).hexdigest()] = default_sample_bytes
        rows = campaign_rows()
        for row in rows:
            if row["case"] == "changed":
                if row["variant"] == "rust_candidate":
                    row["elapsed_ns"] = 250000 if row["process"] == 0 else 400000
                elif row["variant"] == "rust_current" and row["process"] == 0:
                    row["elapsed_ns"] = 250000
        nonuniform, nonuniform_output = self.valid("HOLD", rows=rows)
        nonuniform_sample_bytes = (nonuniform_output.parent / "samples.jsonl").read_bytes()
        self.assertLessEqual(len(nonuniform_sample_bytes), 65536)
        sample_preimages[hashlib.sha256(nonuniform_sample_bytes).hexdigest()] = nonuniform_sample_bytes
        insensitive = copy.deepcopy(uniform)
        insensitive["base_sha"] = insensitive["base_sha"].upper()
        insensitive["candidate_sha"] = insensitive["candidate_sha"].upper()
        optimized = copy.deepcopy(uniform)
        optimized["qualification_profile"]["variant_bindings"]["cpp_optimized"]["source_sha"] = "e" * 40
        partial = copy.deepcopy(uniform)
        partial["status"] = partial["cases"][0]["status"] = "HOLD"
        partial["cases"][0]["comparisons"]["cpp_current"]["status"] = "HOLD"
        del partial["cases"][0]["comparisons"]["cpp_current"]["certificate"]
        kernel = copy.deepcopy(uniform)
        kernel["status"] = kernel["cases"][0]["status"] = "HOLD"
        kernel["cases"][0].update(scope="kernel", rust_preservation_applicability=None)
        del kernel["cases"][0]["comparisons"]["rust_current"]
        default_shape = copy.deepcopy(uniform)
        # Authored matched DEFAULT provenance shape, not a successful CLI
        # qualification with a missing width (campaign_design requires all4).
        width = default_shape["methodology"]["exact_width_policy"]
        width.update(source="exact_default_decimal_declaration", token_sha256=None, token_bytes=0,
                     default_decimal="0.10", numerator="1", denominator="10")
        default_shape["methodology"]["policy"]["max_relative_ci_width"] = 0.1
        default_hash = hashlib.sha256(b"{}").hexdigest()
        default_shape["input_hashes"]["manifest_sha256"] = default_hash
        width["manifest_sha256"] = default_hash
        for item in default_shape["cases"]:
            for check in item["comparisons"].values():
                check["certificate"]["width_policy_rational"] = {"numerator": "1", "denominator": "10"}
                check["certificate"]["bindings"]["input_hashes"]["manifest_sha256"] = default_hash
        # These two positives intentionally change declared metadata; bind it
        # explicitly rather than silently accepting a stale witness label.
        rebind(optimized)
        rebind(default_shape)
        rebind(kernel)
        declared_width = copy.deepcopy(default_shape)
        declared_width["methodology"]["exact_width_policy"].update(
            source="retained_manifest_json_number_token", default_decimal=None)
        declared_source = campaign_manifest()
        declared_source["qualification_policy"]["max_relative_ci_width"] = 0.1
        retain(declared_width, declared_source, b"0.10")
        rebind(declared_width)
        self.assertEqual((declared_width["methodology"]["exact_width_policy"]["numerator"],
                          declared_width["methodology"]["exact_width_policy"]["denominator"]), ("1", "10"))
        self.assertEqual((declared_width["methodology"]["exact_width_policy"]["token_bytes"],
                          declared_width["methodology"]["exact_width_policy"]["token_sha256"]),
                         (4, hashlib.sha256(b"0.10").hexdigest()))
        valid = (("actual_uniform_required_PASS", uniform), ("actual_nonuniform_comparisons_outer_HOLD", nonuniform),
                 ("case_insensitive_imported_source_sha", insensitive), ("optimized_CPP_distinct_imported_sha", optimized),
                 ("partial_HOLD_without_certificate", partial), ("kernel_PASS_comparison_witness_under_HOLD", kernel),
                 ("coherent_complete_manifest_declared_0_10", declared_width))
        for identifier, artifact in valid:
            if identifier in ("optimized_CPP_distinct_imported_sha", "kernel_PASS_comparison_witness_under_HOLD"):
                retain(artifact, source_fixture(identifier))
            with self.subTest(valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        # Actual main validates the producer object before JSON turns its
        # draw tuples into arrays. Reconstruct just that representation from
        # the two existing seeds and call the production check directly.
        self.assertEqual(schemas["campaign-qualification.schema.json"]["$defs"]["certificate_counts"]["type"], "array")
        tuple_artifacts = []
        for identifier, source in (("internal_uniform_tuple_vectors", uniform),
                                   ("internal_nonuniform_tuple_vectors", nonuniform)):
            artifact = copy.deepcopy(source)
            converted = 0
            for item in artifact["cases"]:
                for check in item["comparisons"].values():
                    witness = check["certificate"]
                    for record in (witness["bounding_contributors"] or {}).values():
                        for side in ("lower", "upper"):
                            name = side + "_process_multiplicities"
                            record[name] = tuple(record[name])
                            converted += 1
                    for record in (witness["exact_order_statistics"] or {}).values():
                        record["process_multiplicities"] = tuple(record["process_multiplicities"])
                        converted += 1
            with self.subTest(internal_valid=identifier):
                self.assertGreater(converted, 0)
                original = json.dumps(artifact, sort_keys=True)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
            tuple_artifacts.append(artifact)
        self.assertEqual(len(tuple_artifacts), 2)
        malformed_tuple = copy.deepcopy(tuple_artifacts[0])
        malformed_tuple["cases"][0]["comparisons"]["cpp_current"]["certificate"]["exact_order_statistics"]["124"]["process_multiplicities"] = (True, 1)
        with self.subTest(internal_invalid="internal_tuple_boolean_multiplicity"):
            original = json.dumps(malformed_tuple, sort_keys=True)
            with self.assertRaises(error) as caught:
                validate(malformed_tuple)
            self.assertIn("multiplicities differ", str(caught.exception))
            self.assertEqual(json.dumps(malformed_tuple, sort_keys=True), original)
        identifiers = (
            "source_cpp_current_mismatch", "source_rust_current_mismatch", "source_rust_candidate_mismatch",
            "matched_design_omits_required_variant", "matched_design_repeats_variant", "matched_design_unknown_variant",
            "matched_design_incomplete_cycle", "matched_design_invalid_floor", "matched_design_invalid_process",
            "matched_design_invalid_rounds", "matched_design_planned_rows_over_cap", "matched_design_bootstrap_over_cap",
            "PASS_observed_process_count_mismatch", "PASS_round_counts_grid_mismatch", "PASS_raw_count_mismatch",
            "PASS_missing_cpp_comparison", "PASS_comparison_status_HOLD", "PASS_comparison_missing_certificate",
            "PASS_comparison_certificate_empty", "PASS_under_HOLD_missing_certificate", "certificate_missing_relations",
            "certificate_invalid_proof", "certificate_policy_mismatch", "certificate_analysis_binding_mismatch",
            "certificate_input_binding_mismatch", "certificate_plan_binding_mismatch", "certificate_fixture_binding_mismatch",
            "certificate_case_binding_mismatch", "certificate_baseline_binding_mismatch", "certificate_candidate_binding_mismatch",
            "certificate_degree_mismatch", "certificate_precision_invalid", "certificate_decimal_too_long",
            "certificate_nonfinite_decimal", "certificate_rational_too_long", "certificate_vector_length_mismatch",
            "certificate_vector_sum_mismatch", "certificate_replica_out_of_range", "certificate_work_over_cap",
            "certificate_unknown_work_counter", "certificate_payload_over_cap", "PASS_relation_width_GT",
            "PASS_changed_upper_relation_GT", "PASS_control_lower_relation_GT", "PASS_control_upper_relation_LT",
            "PASS_wrong_role_rule", "PASS_wrong_limit", "PASS_wrong_named_baseline",
            "HOLD_comparison_undeclared_baseline", "certificate_width_policy_mismatch", "root_seed_mismatch",
            "root_replicates_mismatch", "root_arithmetic_policy_mismatch", "width_provenance_manifest_mismatch",
            "uniform_nonuniform_proof_method", "uniform_late_precision", "nonuniform_exact_without_selected",
            "nonuniform_uniform_proof_method")
        schema_valid_mutations = {
            "source_cpp_current_mismatch", "source_rust_current_mismatch", "source_rust_candidate_mismatch",
            "matched_design_omits_required_variant", "matched_design_incomplete_cycle",
            "matched_design_planned_rows_over_cap", "matched_design_bootstrap_over_cap",
            "PASS_observed_process_count_mismatch", "PASS_round_counts_grid_mismatch", "PASS_raw_count_mismatch",
            "certificate_analysis_binding_mismatch", "certificate_input_binding_mismatch", "certificate_plan_binding_mismatch",
            "certificate_fixture_binding_mismatch", "certificate_case_binding_mismatch", "certificate_baseline_binding_mismatch",
            "certificate_degree_mismatch", "certificate_vector_length_mismatch", "certificate_vector_sum_mismatch",
            "certificate_width_policy_mismatch", "width_provenance_manifest_mismatch"}
        self.assertEqual((len(valid), len(identifiers), len(set(identifiers))), (7, 58, 58))
        self.assertEqual(len({name for name, _ in valid} | set(identifiers)), 65)
        for identifier in identifiers:
            artifact = copy.deepcopy(nonuniform if identifier.startswith("nonuniform_") else uniform)
            artifact["status"] = "HOLD"  # A PASS child is never excused by root HOLD.
            case = artifact["cases"][1 if identifier.startswith("PASS_control_") else 0]
            comparison = case["comparisons"]["cpp_current"]
            certificate = comparison["certificate"]
            profile = artifact["qualification_profile"]
            if identifier.startswith("source_"):
                name = identifier.removeprefix("source_").removesuffix("_mismatch")
                profile["variant_bindings"][name]["source_sha"] = "0" * 40
            elif identifier.startswith("matched_design_"):
                design = profile["collection_design"][case["case"]]
                if identifier == "matched_design_omits_required_variant":
                    design["order_cycle"] = [[v for v in order if v != "cpp_optimized"] for order in design["order_cycle"]]
                elif identifier == "matched_design_repeats_variant":
                    design["order_cycle"][0][1] = design["order_cycle"][0][0]
                elif identifier == "matched_design_unknown_variant":
                    design["order_cycle"][0][1] = "unknown"
                elif identifier == "matched_design_incomplete_cycle":
                    design["round_count"] = 5
                elif identifier == "matched_design_invalid_floor":
                    design["elapsed_floor_ns"] = 0
                elif identifier == "matched_design_invalid_process":
                    design["process_count"] = 0
                elif identifier == "matched_design_invalid_rounds":
                    design["round_count"] = 0
                else:
                    # HOLD declarations still obey the original source work
                    # caps; no certificate/grid mismatch masks these guards.
                    for item in artifact["cases"]:
                        item.update(status="HOLD", comparisons={})
                        declared = profile["collection_design"][item["case"]]
                        declared["process_count"] = 128
                        declared["round_count"] = 100000 if identifier == "matched_design_planned_rows_over_cap" else 2
                        item["collection_design"] = copy.deepcopy(declared)
                    if identifier == "matched_design_bootstrap_over_cap":
                        extra = copy.deepcopy(artifact["cases"][0])
                        extra["case"] = "extra"
                        artifact["cases"].append(extra)
                        profile["collection_design"]["extra"] = copy.deepcopy(extra["collection_design"])
                case["collection_design"] = copy.deepcopy(design)
            elif identifier == "PASS_observed_process_count_mismatch":
                case["process_count"] = 1
            elif identifier == "PASS_round_counts_grid_mismatch":
                case["round_counts"]["0"] = 3
            elif identifier == "PASS_raw_count_mismatch":
                case["raw_count"] = 31
            elif identifier == "PASS_missing_cpp_comparison":
                del case["comparisons"]["cpp_optimized"]
            elif identifier == "PASS_comparison_status_HOLD":
                comparison["status"] = "HOLD"
            elif identifier in ("PASS_comparison_missing_certificate", "PASS_under_HOLD_missing_certificate"):
                if identifier == "PASS_under_HOLD_missing_certificate":
                    case["status"] = "HOLD"
                del comparison["certificate"]
            elif identifier == "PASS_comparison_certificate_empty":
                comparison["certificate"] = {}
            elif identifier == "certificate_missing_relations":
                del certificate["relations"]
            elif identifier == "certificate_invalid_proof":
                certificate["proof"]["upper_vs_limit"] = "asserted"
            elif identifier == "certificate_policy_mismatch":
                certificate["policy_sha256"] = "0" * 64
            elif identifier == "certificate_analysis_binding_mismatch":
                certificate["bindings"]["analysis_sha256"] = "0" * 64
            elif identifier == "certificate_input_binding_mismatch":
                certificate["bindings"]["input_hashes"]["samples_sha256"] = "0" * 64
            elif identifier == "certificate_plan_binding_mismatch":
                certificate["bindings"]["plan_sha256"] = "0" * 64
            elif identifier == "certificate_fixture_binding_mismatch":
                certificate["bindings"]["fixture_sha256"] = "0" * 64
            elif identifier == "certificate_case_binding_mismatch":
                certificate["bindings"]["case"] = "other"
            elif identifier == "certificate_baseline_binding_mismatch":
                certificate["bindings"]["baseline"] = "cpp_optimized"
            elif identifier == "certificate_candidate_binding_mismatch":
                certificate["bindings"]["candidate"] = "cpp_current"
            elif identifier == "certificate_degree_mismatch":
                certificate["common_root_degree"] += 1
            elif identifier == "certificate_precision_invalid":
                certificate["precision"] = 81
            elif identifier == "certificate_decimal_too_long":
                certificate["bounds"]["lower"][0] = "1" * 673
            elif identifier == "certificate_nonfinite_decimal":
                certificate["bounds"]["lower"][0] = "NaN"
            elif identifier == "certificate_rational_too_long":
                certificate["width_policy_rational"]["denominator"] = "1" * 2468
            elif identifier == "certificate_vector_length_mismatch":
                certificate["exact_order_statistics"]["124"]["process_multiplicities"] = [1, 1, 0]
            elif identifier == "certificate_vector_sum_mismatch":
                certificate["exact_order_statistics"]["124"]["process_multiplicities"] = [0, 0]
            elif identifier == "certificate_replica_out_of_range":
                certificate["exact_order_statistics"]["124"]["replicate_id"] = 5000
            elif identifier == "certificate_work_over_cap":
                certificate["work_cumulative"]["exp_calls"] = 7681
            elif identifier == "certificate_unknown_work_counter":
                certificate["work_cumulative"]["unknown"] = 0
            elif identifier == "certificate_payload_over_cap":
                # A deliberately malformed private witness isolates the actual
                # serialized-byte guard, asserted by its specific error below.
                certificate["extra"] = "X" * 32768
            elif identifier == "PASS_relation_width_GT":
                certificate["relations"]["width_vs_policy"] = "GT"
            elif identifier == "PASS_changed_upper_relation_GT":
                certificate["relations"]["upper_vs_limit"] = "GT"
            elif identifier == "PASS_control_lower_relation_GT":
                certificate["relations"]["lower_vs_one"] = "GT"
            elif identifier == "PASS_control_upper_relation_LT":
                certificate["relations"]["upper_vs_one"] = "LT"
            elif identifier == "PASS_wrong_role_rule":
                comparison["rule"] = "interval_contains_one"
            elif identifier == "PASS_wrong_limit":
                comparison["upper_bound_limit"] = 1
            elif identifier == "PASS_wrong_named_baseline":
                comparison["baseline"] = "cpp_optimized"
            elif identifier == "HOLD_comparison_undeclared_baseline":
                case["status"] = comparison["status"] = "HOLD"
                case["required_variants"].remove("cpp_current")
                design = profile["collection_design"][case["case"]]
                design["order_cycle"] = [[v for v in order if v != "cpp_current"] for order in design["order_cycle"]]
                case["collection_design"] = copy.deepcopy(design)
            elif identifier == "certificate_width_policy_mismatch":
                certificate["width_policy_rational"] = {"numerator": "1", "denominator": "2"}
            elif identifier == "root_seed_mismatch":
                artifact["methodology"]["seed"] += 1
            elif identifier == "root_replicates_mismatch":
                artifact["methodology"]["bootstrap_replicates"] += 1
            elif identifier == "root_arithmetic_policy_mismatch":
                artifact["methodology"]["arithmetic_policy_sha256"] = "0" * 64
            elif identifier == "width_provenance_manifest_mismatch":
                artifact["methodology"]["exact_width_policy"]["manifest_sha256"] = "0" * 64
            elif identifier == "uniform_nonuniform_proof_method":
                certificate["proof"]["upper_vs_limit"] = "directed_decimal_enclosure"
            elif identifier == "uniform_late_precision":
                certificate["precision"] = 160
            elif identifier == "nonuniform_exact_without_selected":
                certificate["proof"]["upper_vs_limit"] = "exact_rational_root_quantile"
                certificate["relations"]["upper_vs_limit"] = "EQ"
                certificate["precision"] = 640
                certificate["exact_order_statistics"] = None
            elif identifier == "nonuniform_uniform_proof_method":
                certificate["proof"]["upper_vs_limit"] = "uniform_exact_process_product"
            with self.subTest(invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                if identifier in schema_valid_mutations:
                    validator.validate(artifact)
                else:
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                if identifier == "certificate_payload_over_cap":
                    self.assertIn("serialized byte limit", str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        # One materially necessary extra actual SYNTHETIC CLI seed preserves
        # the real one-process HOLD witness for the reported relabel attack.
        one_manifest = campaign_manifest()
        for design in one_manifest["qualification_profile"]["collection_design"].values():
            design["process_count"] = 1
        one_rows = [row for row in campaign_rows() if row["process"] == 0]
        one_process, one_process_output = self.valid("HOLD", manifest=one_manifest, rows=one_rows)
        # Bind the ORIGINAL byte packet from this existing one-process run.
        # Guard the descriptor and64KiB cap BEFORE reading/hash; never rebuild
        # JSONL from rows or trust a repeated artifact digest as its preimage.
        one_sample_fd = os.open(one_process_output.parent / "samples.jsonl",
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            one_sample_before = os.fstat(one_sample_fd)
            self.assertEqual(one_sample_before.st_mode & 0o170000, 0o100000)
            self.assertLessEqual(one_sample_before.st_size, 65536)
            one_sample_bytes = os.read(one_sample_fd, one_sample_before.st_size + 1)
            self.assertEqual(len(one_sample_bytes), one_sample_before.st_size)
            self.assertEqual(os.read(one_sample_fd, 1), b"")
            one_sample_after = os.fstat(one_sample_fd)
            self.assertEqual((one_sample_before.st_dev, one_sample_before.st_ino,
                              one_sample_before.st_size, one_sample_before.st_mtime_ns,
                              one_sample_before.st_ctime_ns),
                             (one_sample_after.st_dev, one_sample_after.st_ino,
                              one_sample_after.st_size, one_sample_after.st_mtime_ns,
                              one_sample_after.st_ctime_ns))
        finally:
            os.close(one_sample_fd)
        one_sample_hash = hashlib.sha256(one_sample_bytes).hexdigest()
        self.assertEqual(one_sample_hash, one_process["input_hashes"]["samples_sha256"].lower())
        self.assertNotEqual(one_sample_bytes, default_sample_bytes)
        sample_preimages[one_sample_hash] = one_sample_bytes
        one_manifest_bytes = json.dumps(one_manifest).encode()
        retained_preimages[hashlib.sha256(one_manifest_bytes).hexdigest()] = one_manifest_bytes
        exact_each = copy.deepcopy(uniform)
        exact_each["methodology"]["policy"]["min_each_order"] = 2
        rebind(exact_each)
        held_rounds = copy.deepcopy(uniform)
        held_rounds["methodology"]["policy"]["min_rounds"] = 6
        held_processes = copy.deepcopy(uniform)
        held_processes["methodology"]["policy"]["min_processes"] = 8
        for artifact in (held_rounds, held_processes):
            artifact["status"] = "HOLD"
            for item in artifact["cases"]:
                item["status"] = "HOLD"
                for check in item["comparisons"].values():
                    check["status"] = "HOLD"
            rebind(artifact)
        hex_casing = copy.deepcopy(uniform)
        hex_casing["base_sha"] = hex_casing["base_sha"].upper()
        hex_casing["candidate_sha"] = hex_casing["candidate_sha"].upper()
        for binding in hex_casing["qualification_profile"]["variant_bindings"].values():
            for field in binding:
                binding[field] = binding[field].upper()
        for item in hex_casing["cases"]:
            item["fixture_sha256"] = item["fixture_sha256"].upper()
        # Do not rebind: validated hex casing must preserve the old digest.
        na = copy.deepcopy(uniform)
        item = na["cases"][0]
        item["rust_preservation_applicability"] = "not_applicable"
        item["required_variants"].remove("rust_current")
        del item["comparisons"]["rust_current"]
        item["provenance"] = {"rust_preservation_rationale": "Authored source-bound metadata rationale only; no external review attestation"}
        design = na["qualification_profile"]["collection_design"][item["case"]]
        design["order_cycle"] = [[v for v in order if v != "rust_current"] for order in design["order_cycle"]]
        item["collection_design"] = copy.deepcopy(design)
        item["raw_count"] = 24
        rebind(na)
        additional_valid = (("actual_one_process_HOLD", one_process),
                            ("minimum_each_order_exact_bound", exact_each),
                            ("HOLD_rounds_below_policy", held_rounds),
                            ("HOLD_processes_below_policy8", held_processes),
                            ("validated_hex_casing_preserved", hex_casing),
                            ("authored_NA_valid_rationale", na))
        for identifier, artifact in additional_valid:
            retain(artifact, source_fixture(identifier))
            with self.subTest(contract_valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        additional_invalid = ["single_order_cycle_PASS", "unequal_order_cycle_PASS",
            "PASS_comparison_under_HOLD_single_order", "one_process_relabelled_PASS",
            "PASS_comparison_under_HOLD_one_process", "policy_min_rounds_above_design",
            "policy_min_each_order_above_repetitions", "lowered_min_processes8_to2_stale_contract",
            "lowered_min_rounds4_to2_stale_contract", "incomplete_import_policy", "invalid_import_policy_bounds",
            "invalid_import_policy_order_feasibility", "NA_missing_provenance", "NA_missing_rationale",
            "NA_empty_rationale", "NA_blank_rationale", "NA_nontext_rationale", "NA_control_rationale",
            "NA_overlong_rationale", "NA_changed_rationale_stale_contract",
            "NA_PASS_comparison_under_HOLD_missing_rationale", "contract_digest_missing", "contract_digest_wrong"]
        additional_invalid += ["artifact_" + variant + "_" + field + "_changed"
            for variant in ("cpp_current", "cpp_optimized", "rust_current", "rust_candidate")
            for field in (("source_content_sha256", "executable_sha256", "rust_archive_sha256")
                          if variant.startswith("rust_") else ("source_content_sha256", "executable_sha256"))]
        additional_invalid.append("artifact_cpp_optimized_source_sha_changed")
        schema_valid_contract_mutations = {
            "single_order_cycle_PASS", "unequal_order_cycle_PASS", "PASS_comparison_under_HOLD_single_order",
            "one_process_relabelled_PASS", "PASS_comparison_under_HOLD_one_process", "policy_min_rounds_above_design",
            "policy_min_each_order_above_repetitions", "lowered_min_processes8_to2_stale_contract",
            "lowered_min_rounds4_to2_stale_contract", "invalid_import_policy_order_feasibility",
            "NA_changed_rationale_stale_contract", "contract_digest_wrong"}
        schema_valid_contract_mutations.update(n for n in additional_invalid if n.startswith("artifact_"))
        self.assertEqual((len(additional_valid), len(additional_invalid), len(set(additional_invalid))), (6, 34, 34))
        self.assertEqual(len({n for n, _ in additional_valid} | set(additional_invalid)), 40)
        self.assertEqual(len(schema_valid_contract_mutations), 23)
        for identifier in additional_invalid:
            source = (na if identifier.startswith("NA_") else one_process if "one_process" in identifier else
                      held_processes if identifier == "lowered_min_processes8_to2_stale_contract" else uniform)
            artifact = copy.deepcopy(source)
            artifact["status"] = "HOLD"
            item = artifact["cases"][0]
            comparison = item["comparisons"]["cpp_current"]
            policy = artifact["methodology"]["policy"]
            design = artifact["qualification_profile"]["collection_design"][item["case"]]
            fresh_binding = False
            if identifier in ("single_order_cycle_PASS", "unequal_order_cycle_PASS", "PASS_comparison_under_HOLD_single_order"):
                forward, reverse = copy.deepcopy(design["order_cycle"])
                design["order_cycle"] = [forward, forward, forward, reverse] if identifier == "unequal_order_cycle_PASS" else [forward]
                item["collection_design"] = copy.deepcopy(design)
                if identifier == "PASS_comparison_under_HOLD_single_order":
                    item["status"] = "HOLD"
                    for check in item["comparisons"].values():
                        check["status"] = "HOLD"
                    comparison["status"] = "PASS"
                fresh_binding = True
            elif identifier in ("one_process_relabelled_PASS", "PASS_comparison_under_HOLD_one_process"):
                if identifier == "one_process_relabelled_PASS":
                    item["status"], item["reasons"] = "PASS", []
                    for check in item["comparisons"].values():
                        check["status"], check["reasons"] = "PASS", []
                else:
                    comparison["status"], comparison["reasons"] = "PASS", []
            elif identifier == "policy_min_rounds_above_design":
                policy["min_rounds"] = 6
                fresh_binding = True
            elif identifier == "policy_min_each_order_above_repetitions":
                policy.update(min_rounds=6, min_each_order=3)
                fresh_binding = True
            elif identifier == "lowered_min_processes8_to2_stale_contract":
                policy["min_processes"] = 2
                comparison["status"] = "PASS"
            elif identifier == "lowered_min_rounds4_to2_stale_contract":
                policy["min_rounds"] = 2
            elif identifier == "incomplete_import_policy":
                del policy["min_rounds"]
            elif identifier == "invalid_import_policy_bounds":
                policy["min_processes"] = 1
            elif identifier == "invalid_import_policy_order_feasibility":
                policy["min_each_order"] = 3
            elif identifier.startswith("NA_"):
                if identifier == "NA_missing_provenance":
                    del item["provenance"]
                elif identifier in ("NA_missing_rationale", "NA_PASS_comparison_under_HOLD_missing_rationale"):
                    item["provenance"] = {}
                    if identifier == "NA_PASS_comparison_under_HOLD_missing_rationale":
                        item["status"] = "HOLD"
                        for check in item["comparisons"].values():
                            check["status"] = "HOLD"
                        comparison["status"] = "PASS"
                else:
                    values = {"NA_empty_rationale": "", "NA_blank_rationale": "   ", "NA_nontext_rationale": 17,
                              "NA_control_rationale": "x\ny", "NA_overlong_rationale": "x" * 4097,
                              "NA_changed_rationale_stale_contract": "Another bounded printable rationale assertion"}
                    item["provenance"]["rust_preservation_rationale"] = values[identifier]
                fresh_binding = identifier != "NA_changed_rationale_stale_contract"
            elif identifier == "contract_digest_missing":
                del comparison["certificate"]["bindings"]["qualification_contract_sha256"]
            elif identifier == "contract_digest_wrong":
                comparison["certificate"]["bindings"]["qualification_contract_sha256"] = "0" * 64
            else:
                name = identifier.removeprefix("artifact_").removesuffix("_changed")
                variant = next(v for v in ("cpp_current", "cpp_optimized", "rust_current", "rust_candidate") if name.startswith(v + "_"))
                field = name.removeprefix(variant + "_")
                artifact["qualification_profile"]["variant_bindings"][variant][field] = "e" * 40 if field == "source_sha" else "0" * 64
            if fresh_binding:
                # Recompute only assertion binding with the real source helper;
                # no numeric witness, RNG draw, product or sample is replaced.
                rebind(artifact)
            if identifier in schema_valid_contract_mutations and identifier not in (
                    "invalid_import_policy_order_feasibility", "contract_digest_wrong"):
                retain(artifact, source_fixture(identifier))
            with self.subTest(contract_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                if identifier in schema_valid_contract_mutations:
                    validator.validate(artifact)
                else:
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                if identifier in ("single_order_cycle_PASS", "unequal_order_cycle_PASS", "PASS_comparison_under_HOLD_single_order"):
                    self.assertIn("unbalanced_pair_order", str(caught.exception))
                if identifier in ("one_process_relabelled_PASS", "PASS_comparison_under_HOLD_one_process"):
                    self.assertIn("insufficient_processes", str(caught.exception))
                if identifier in ("policy_min_rounds_above_design", "policy_min_each_order_above_repetitions"):
                    self.assertIn("insufficient_rounds", str(caught.exception))
                if identifier == "policy_min_each_order_above_repetitions":
                    self.assertIn("unbalanced_pair_order", str(caught.exception))
                if identifier in ("lowered_min_processes8_to2_stale_contract", "lowered_min_rounds4_to2_stale_contract", "NA_changed_rationale_stale_contract") or identifier.startswith("artifact_"):
                    self.assertIn("qualification contract differs", str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        # Reuse existing real synthetic seeds: no added CLI/bootstrap work.
        # Every observed-grid negative changes one field under case/root HOLD
        # (plus the exact reported combined-empty case); certificates stay put.
        grid_mutations = (
            ("grid_complete_false", {"complete": False}),
            ("grid_process_count_zero", {"process_count": 0}),
            ("grid_process_count_mismatch", {"process_count": 1}),
            ("grid_process_count_boolean", {"process_count": True}),
            ("grid_raw_count_zero", {"raw_count": 0}),
            ("grid_raw_count_mismatch", {"raw_count": 31}),
            ("grid_raw_count_boolean", {"raw_count": True}),
            ("grid_round_counts_empty", {"round_counts": {}}),
            ("grid_round_counts_missing_process", {"round_counts": {"0": 4}}),
            ("grid_round_counts_extra_process", {"round_counts": {"0": 4, "1": 4, "2": 4}}),
            ("grid_round_counts_wrong_count", {"round_counts": {"0": 3, "1": 4}}),
            ("grid_round_counts_boolean_count", {"round_counts": {"0": True, "1": 4}}),
            ("grid_reported_combined_empty", {"complete": False, "process_count": 0, "raw_count": 0, "round_counts": {}}))
        schema_valid_grid = {"grid_process_count_mismatch", "grid_raw_count_mismatch",
                             "grid_round_counts_missing_process", "grid_round_counts_extra_process",
                             "grid_round_counts_wrong_count"}
        for identifier, mutation in grid_mutations:
            artifact = copy.deepcopy(uniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            case = artifact["cases"][0]
            original_comparisons = json.dumps(case["comparisons"], sort_keys=True)
            case.update(copy.deepcopy(mutation))
            with self.subTest(observed_grid_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                if identifier in schema_valid_grid:
                    validator.validate(artifact)
                else:
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn("PASS observed grid differs", str(caught.exception))
                self.assertEqual(json.dumps(case["comparisons"], sort_keys=True), original_comparisons)
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        provenance_invalid = ("control_provenance_missing", "control_provenance_empty", "control_provenance_nonobject",
                              "changed_supplied_provenance_nonobject", "control_under_HOLD_provenance_missing",
                              "control_under_HOLD_provenance_empty")
        for identifier in provenance_invalid:
            artifact = copy.deepcopy(uniform)
            case = artifact["cases"][0 if identifier.startswith("changed_") else 1]
            if "under_HOLD" in identifier:
                artifact["status"] = case["status"] = "HOLD"
            if identifier.endswith("missing"):
                del case["provenance"]
            elif identifier.endswith("empty"):
                case["provenance"] = {}
            else:
                case["provenance"] = None if identifier.startswith("changed_") else []
            # Coherent metadata digest cannot replace the independent producer
            # type/role predicate. No numerical certificate values are changed.
            rebind(artifact)
            with self.subTest(provenance_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                with self.assertRaises(SchemaValidationError):
                    validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn("provenance", str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        incomplete_no_pass = copy.deepcopy(uniform)
        incomplete_no_pass["status"] = "HOLD"
        incomplete_no_pass["cases"][0].update(status="HOLD", complete=False, process_count=0,
                                             raw_count=0, round_counts={}, comparisons={})
        optional_missing = copy.deepcopy(uniform)
        del optional_missing["cases"][0]["provenance"]
        optional_empty = copy.deepcopy(uniform)
        optional_empty["cases"][0]["provenance"] = {}
        rebind(optional_missing)
        rebind(optional_empty)
        grid_provenance_valid = (("complete_kernel_PASS_diagnostic", kernel),
                                ("actual_undersized_comparisons_HOLD", one_process),
                                ("incomplete_HOLD_without_comparisons", incomplete_no_pass),
                                ("populated_required_Rust_control", uniform),
                                ("omitted_source_provenance_emits_explicit_empty_object", copy.deepcopy(uniform)),
                                ("changed_empty_optional_provenance", optional_empty))
        self.assertEqual(uniform["cases"][1]["rust_preservation_applicability"], "required")
        self.assertTrue(uniform["cases"][1]["provenance"])
        self.assertNotIn("provenance", campaign_manifest()["fixtures"][0])
        self.assertEqual(uniform["cases"][0]["provenance"], {})
        for identifier, artifact in grid_provenance_valid:
            if identifier in ("complete_kernel_PASS_diagnostic", "actual_undersized_comparisons_HOLD"):
                retain(artifact, source_fixture(identifier))
            with self.subTest(grid_provenance_valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        labels = [name for name, _ in grid_mutations] + list(provenance_invalid) + [name for name, _ in grid_provenance_valid]
        self.assertEqual((len(grid_mutations), len(provenance_invalid), len(grid_provenance_valid)), (13, 6, 6))
        self.assertEqual((len(labels), len(set(labels)), len(schema_valid_grid)), (25, 25, 5))
        # Producer entry and exact comparison-label prerequisites apply to
        # any PASS child. Reuse existing seeds; no new CLI or numerical work.
        entry_invalid = ("entry_missing_cpp_current", "entry_missing_cpp_optimized", "entry_missing_rust_candidate",
                         "entry_complete_caller_null_applicability", "entry_required_rust_undeclared_complete_caller",
                         "entry_required_rust_undeclared_kernel", "entry_missing_comparison_cpp_current",
                         "entry_missing_comparison_cpp_optimized", "entry_missing_comparison_rust_current",
                         "entry_kernel_null_extra_rust_comparison", "entry_kernel_NA_extra_rust_comparison")
        main_omissions = {"entry_missing_" + name: name for name in ("cpp_current", "cpp_optimized", "rust_candidate")}
        for identifier in entry_invalid:
            artifact = copy.deepcopy(uniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            case = artifact["cases"][0]
            original_map = copy.deepcopy(case["comparisons"])
            expected_error, removed_comparison = None, None
            if identifier in main_omissions or identifier.startswith("entry_required_rust_undeclared_"):
                omitted = main_omissions.get(identifier, "rust_current")
                case["required_variants"].remove(omitted)
                case["comparisons"].pop(omitted, None)
                design = artifact["qualification_profile"]["collection_design"][case["case"]]
                design["order_cycle"] = [[v for v in order if v != omitted] for order in design["order_cycle"]]
                case["collection_design"] = copy.deepcopy(design)
                case["raw_count"] = design["process_count"] * design["round_count"] * len(case["required_variants"])
                if identifier.endswith("_kernel"):
                    case["scope"] = "kernel"
                expected_error = ("missing main variants" if identifier in main_omissions else
                                  "missing required current Rust declaration")
                rebind(artifact)
            elif identifier == "entry_complete_caller_null_applicability":
                case["rust_preservation_applicability"] = None
                expected_error = "complete_caller needs preservation applicability"
                rebind(artifact)
            elif identifier.startswith("entry_missing_comparison_"):
                removed_comparison = identifier.removeprefix("entry_missing_comparison_")
                del case["comparisons"][removed_comparison]
                expected_error = "comparison keys differ from applicability"
                # The declared contract excludes this map; original surviving
                # certificates/digests stay byte-identical without rebinding.
            else:
                case.update(scope="kernel", rust_preservation_applicability=(
                    None if identifier == "entry_kernel_null_extra_rust_comparison" else "not_applicable"))
                expected_error = "comparison keys differ from applicability"
                rebind(artifact)
            if identifier in main_omissions or identifier.startswith("entry_required_rust_undeclared_") or identifier in (
                    "entry_complete_caller_null_applicability", "entry_kernel_null_extra_rust_comparison", "entry_kernel_NA_extra_rust_comparison"):
                retain(artifact, source_fixture(identifier))
                if identifier == "entry_missing_rust_candidate":
                    # No valid campaign manifest can omit its comparison candidate.
                    expected_error = "including the comparison pair"
            with self.subTest(entry_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                with self.assertRaises(SchemaValidationError):
                    validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn(expected_error, str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
                if removed_comparison is not None:
                    self.assertEqual(case["comparisons"], {k: v for k, v in original_map.items() if k != removed_comparison})
        kernel_NA = copy.deepcopy(kernel)
        kernel_NA["cases"][0]["rust_preservation_applicability"] = "not_applicable"
        rebind(kernel_NA)
        kernel_required = copy.deepcopy(uniform)
        kernel_required["status"] = kernel_required["cases"][0]["status"] = "HOLD"
        kernel_required["cases"][0]["scope"] = "kernel"
        rebind(kernel_required)
        mixed_keys = copy.deepcopy(uniform)
        mixed_keys["status"] = mixed_keys["cases"][0]["status"] = "HOLD"
        mixed_keys["cases"][0]["comparisons"]["rust_current"]["status"] = "HOLD"
        mixed_missing_certificate = copy.deepcopy(mixed_keys)
        del mixed_missing_certificate["cases"][0]["comparisons"]["rust_current"]["certificate"]
        entry_valid = (("entry_kernel_null_optional_rust_no_preservation_comparison", kernel),
                       ("entry_kernel_NA_optional_rust_no_preservation_comparison", kernel_NA),
                       ("entry_kernel_required_rust_full_keys", kernel_required),
                       ("entry_mixed_PASS_HOLD_full_keys", mixed_keys),
                       ("entry_HOLD_sibling_missing_certificate_full_keys", mixed_missing_certificate),
                       ("entry_actual_undersized_all_HOLD", one_process),
                       ("entry_incomplete_no_PASS_HOLD", incomplete_no_pass),
                       ("entry_complete_caller_NA_CPP_keys", na),
                       ("entry_actual_nonuniform_mixed_diagnostic", nonuniform))
        for artifact in (kernel, kernel_NA):
            self.assertIn("rust_current", artifact["cases"][0]["required_variants"])
            self.assertNotIn("rust_current", artifact["cases"][0]["comparisons"])
        for identifier, artifact in entry_valid:
            retain(artifact, source_fixture(identifier))
            with self.subTest(entry_valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        entry_labels = list(entry_invalid) + [name for name, _ in entry_valid]
        self.assertEqual((len(entry_invalid), len(entry_valid), len(entry_labels), len(set(entry_labels))), (11, 9, 20, 20))
        # Exact original preimages are external API inputs, not mathematical
        # witness replay. Preserve both reported mutations independently.
        width_reason_invalid = (
            "width_rational_widened_9_10_original_preimage", "width_token_hash_mismatch_original_preimage",
            "width_token_length_mismatch_original_preimage", "width_manifest_hash_mismatch_original_preimage",
            "width_default_claim_for_declared_manifest", "root_PASS_nonempty_reasons",
            "case_PASS_under_HOLD_nonempty_reasons", "comparison_PASS_under_HOLD_nonempty_reasons",
            "root_PASS_missing_reasons", "case_PASS_under_HOLD_missing_reasons",
            "comparison_PASS_under_HOLD_missing_reasons")
        for identifier in width_reason_invalid:
            artifact = copy.deepcopy(uniform)
            width = artifact["methodology"]["exact_width_policy"]
            if identifier.startswith("width_"):
                if identifier == "width_rational_widened_9_10_original_preimage":
                    width.update(numerator="9", denominator="10")
                    for item in artifact["cases"]:
                        for check in item["comparisons"].values():
                            check["certificate"]["width_policy_rational"] = {"numerator": "9", "denominator": "10"}
                elif identifier == "width_token_hash_mismatch_original_preimage":
                    width["token_sha256"] = "0" * 64
                elif identifier == "width_token_length_mismatch_original_preimage":
                    width["token_bytes"] += 1
                elif identifier == "width_manifest_hash_mismatch_original_preimage":
                    width["manifest_sha256"] = "0" * 64
                else:
                    width.update(source="exact_default_decimal_declaration", token_sha256=None, token_bytes=0,
                                 default_decimal="0.10", numerator="1", denominator="10")
                    for item in artifact["cases"]:
                        for check in item["comparisons"].values():
                            check["certificate"]["width_policy_rational"] = {"numerator": "1", "denominator": "10"}
            else:
                target = artifact
                if identifier.startswith(("case_", "comparison_")):
                    artifact["status"] = "HOLD"
                    target = artifact["cases"][0]
                if identifier.startswith("comparison_"):
                    target["status"] = "HOLD"
                    target = target["comparisons"]["cpp_current"]
                if identifier.endswith("missing_reasons"):
                    del target["reasons"]
                else:
                    target["reasons"] = ["below_twofold_cpp_gate"]
            with self.subTest(width_reason_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                if identifier.startswith("width_"):
                    validator.validate(artifact)
                else:
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn("retained width preimage association" if identifier.startswith("width_") else
                              "PASS reasons must be an empty list", str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        root_hold_reasons = copy.deepcopy(uniform)
        root_hold_reasons.update(status="HOLD", reasons=["source_diagnostic_hold"])
        case_hold_reasons = copy.deepcopy(root_hold_reasons)
        case_hold_reasons["cases"][0].update(status="HOLD", reasons=["source_diagnostic_hold"])
        comparison_hold_reasons = copy.deepcopy(case_hold_reasons)
        comparison_hold_reasons["cases"][0]["comparisons"]["rust_current"].update(
            status="HOLD", reasons=["source_diagnostic_hold"])
        width_reason_valid = [("all_PASS_empty_reasons", uniform),
            ("root_HOLD_nonempty_reasons_with_PASS_cases", root_hold_reasons),
            ("case_HOLD_nonempty_reasons_with_PASS_comparisons", case_hold_reasons),
            ("comparison_HOLD_nonempty_reasons_mixed_full_keys", comparison_hold_reasons),
            ("kernel_NA_mixed_HOLD_preserved", kernel_NA)]
        # Expected exact rationals are independent literals, never copied from
        # the production parser's returned value. Uniform witnesses have exact
        # zero interval width; these remain authored association fixtures only.
        exact_token_cases = (
            ("retained_token_0_1", b"0.1", "1", "10", 0.1),
            ("retained_token_1e_minus1", b"1e-1", "1", "10", 0.1),
            ("retained_token_long_same_float_exact_one_tenth", b"0.10000000000000000", "1", "10", 0.1),
            ("retained_token_long_same_float_above_one_tenth", b"0.10000000000000001",
                "10000000000000001", "100000000000000000", 0.1),
            ("retained_token_underflow_1e_minus324", b"1e-324", "1", "1" + "0" * 324, 0.0))
        token_pairs, token_hashes, token_displays = {}, {}, {}
        needle = b'"max_relative_ci_width": 0.01'
        self.assertEqual(base_manifest_bytes.count(needle), 1)
        for identifier, token, numerator, denominator, display in exact_token_cases:
            raw = base_manifest_bytes.replace(needle, b'"max_relative_ci_width": ' + token)
            raw_hash, token_hash = hashlib.sha256(raw).hexdigest(), hashlib.sha256(token).hexdigest()
            retained_preimages[raw_hash] = raw
            artifact = copy.deepcopy(uniform)
            artifact["input_hashes"]["manifest_sha256"] = raw_hash
            artifact["methodology"]["policy"]["max_relative_ci_width"] = display
            artifact["methodology"]["exact_width_policy"].update(
                source="retained_manifest_json_number_token", manifest_sha256=raw_hash,
                token_sha256=token_hash, token_bytes=len(token), default_decimal=None,
                numerator=numerator, denominator=denominator)
            for item in artifact["cases"]:
                for check in item["comparisons"].values():
                    check["certificate"]["bindings"]["input_hashes"]["manifest_sha256"] = raw_hash
                    check["certificate"]["width_policy_rational"] = {"numerator": numerator, "denominator": denominator}
            rebind(artifact)
            exact = artifact["methodology"]["exact_width_policy"]
            self.assertEqual((exact["numerator"], exact["denominator"]), (numerator, denominator))
            self.assertEqual((exact["manifest_sha256"], exact["token_sha256"], exact["token_bytes"]),
                             (hashlib.sha256(raw).hexdigest(), hashlib.sha256(token).hexdigest(), len(token)))
            self.assertEqual(json.loads(raw)["qualification_policy"]["max_relative_ci_width"], display)
            token_pairs[identifier], token_hashes[identifier], token_displays[identifier] = (
                (numerator, denominator), token_hash, display)
            width_reason_valid.append((identifier, artifact))
        self.assertEqual(token_pairs["retained_token_0_1"], token_pairs["retained_token_1e_minus1"])
        self.assertNotEqual(token_hashes["retained_token_0_1"], token_hashes["retained_token_1e_minus1"])
        left, right = "retained_token_long_same_float_exact_one_tenth", "retained_token_long_same_float_above_one_tenth"
        self.assertEqual(token_displays[left], token_displays[right])
        self.assertNotEqual(token_pairs[left], token_pairs[right])
        for identifier, artifact in width_reason_valid:
            with self.subTest(width_reason_valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        preimage_invalid = (("retained_manifest_missing_for_witness", None),
            ("retained_manifest_nonbytes_for_witness", {}),
            ("retained_manifest_over_1MiB_for_witness", b" " * (1024 * 1024 + 1)),
            ("retained_manifest_different_bytes_same_token", base_manifest_bytes + b" "),
            ("retained_manifest_malformed_JSON_with_coherent_hash", b"{"))
        for identifier, retained in preimage_invalid:
            artifact = copy.deepcopy(uniform)
            if identifier.endswith("coherent_hash"):
                malformed_hash = hashlib.sha256(retained).hexdigest()
                artifact["input_hashes"]["manifest_sha256"] = malformed_hash
                artifact["methodology"]["exact_width_policy"]["manifest_sha256"] = malformed_hash
                for item in artifact["cases"]:
                    for check in item["comparisons"].values():
                        check["certificate"]["bindings"]["input_hashes"]["manifest_sha256"] = malformed_hash
            with self.subTest(preimage_argument_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                with self.assertRaises(error) as caught:
                    if retained is None:
                        actual_validate(artifact)
                    else:
                        actual_validate(artifact, manifest_bytes=retained)
                expected = ("malformed JSON input" if identifier.endswith("coherent_hash") else
                            "retained manifest hash differs" if identifier.endswith("same_token") else
                            "retained manifest bytes limited to 1 MiB")
                self.assertIn(expected, str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        self.assertEqual((len(width_reason_invalid), len(width_reason_valid), len(preimage_invalid)), (11, 10, 5))
        new_labels = list(width_reason_invalid) + [n for n, _ in width_reason_valid] + [n for n, _ in preimage_invalid]
        self.assertEqual((len(new_labels), len(set(new_labels))), (26, 26))
        self.assertEqual(retrieval_attempts, [], "schema references escaped fixed offline registry")

        # Retain both impossible historical positive labels explicitly: schema
        # remains diagnostic-flexible, while the real consumer rejects imports
        # that no complete campaign producer can emit. No new numerical seed.
        for identifier, artifact, reason in (
                ("authored_matched_default_width_provenance_shape", default_shape, "manifest"),
                ("changed_missing_optional_provenance", optional_missing, "provenance")):
            with self.subTest(reclassified_source_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                validator.validate(artifact)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn(reason, str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)

        # Frozen retained-source projection catalog:42 new direct rejections
        # and4 positives, ADDITIONAL to the two coherent replacements above.
        # Metadata only: unchanged actual uniform/nonuniform seeds, no draws.
        binding_fields = {
            "cpp_current": ("source_sha", "source_content_sha256", "executable_sha256"),
            "cpp_optimized": ("source_sha", "source_content_sha256", "executable_sha256"),
            "rust_current": ("source_sha", "source_content_sha256", "executable_sha256", "rust_archive_sha256"),
            "rust_candidate": ("source_sha", "source_content_sha256", "executable_sha256", "rust_archive_sha256")}
        retained_labels = ["retained_identity_" + n for n in ("schema_version", "testbed", "base_sha", "candidate_sha")]
        retained_labels += ["retained_policy_" + n for n in ("min_processes", "min_rounds", "min_each_order", "max_relative_ci_width")]
        retained_labels += ["retained_profile_" + n for n in ("id", "version", "plan_id", "plan_sha256")]
        retained_labels += ["retained_binding_" + v + "_" + n for v, names in binding_fields.items() for n in names]
        retained_labels += ["retained_design_" + n for n in ("elapsed_floor_ns", "process_count", "round_count", "order_cycle")]
        retained_labels += ["retained_case_" + n for n in ("case_id", "fixture_sha256", "scope", "role", "required_variants_order", "applicability", "provenance", "case_sequence")]
        retained_labels += ["retained_type_" + n for n in ("bool_to_integer", "integer_to_float", "negative_zero_to_positive_zero", "ordinary_string_case")]
        typed = {"values": [True, 1, 1.0, -0.0, None, ["Case", {"value": "ABCDEF"}]]}
        def typed_source_artifact():
            declaration = campaign_manifest()
            declaration["fixtures"][0]["provenance"] = copy.deepcopy(typed)
            artifact = copy.deepcopy(uniform)
            artifact["cases"][0]["provenance"] = copy.deepcopy(typed)
            retain(artifact, declaration)
            rebind(artifact)
            return artifact
        for identifier in retained_labels:
            artifact = typed_source_artifact() if identifier.startswith("retained_type_") else copy.deepcopy(uniform)
            item = artifact["cases"][0]
            profile = artifact["qualification_profile"]
            design = profile["collection_design"]["changed"]
            original_preimage = retained_preimages[artifact["input_hashes"]["manifest_sha256"]]
            if identifier.startswith("retained_identity_"):
                name = identifier.removeprefix("retained_identity_")
                artifact[name] = 2 if name == "schema_version" else "another-testbed" if name == "testbed" else "0" * 40
                if name == "base_sha":
                    for v in ("cpp_current", "rust_current"):
                        profile["variant_bindings"][v]["source_sha"] = "0" * 40
                if name == "candidate_sha":
                    profile["variant_bindings"]["rust_candidate"]["source_sha"] = "0" * 40
            elif identifier.startswith("retained_policy_"):
                name = identifier.removeprefix("retained_policy_")
                artifact["methodology"]["policy"][name] = {"min_processes": 8, "min_rounds": 6, "min_each_order": 2, "max_relative_ci_width": 0.2}[name]
                artifact["status"] = "HOLD"
                for c in artifact["cases"]:
                    c["status"] = "HOLD"
                    for check in c["comparisons"].values():
                        check["status"] = "HOLD"
            elif identifier.startswith("retained_profile_"):
                name = identifier.removeprefix("retained_profile_")
                profile[name] = 2 if name == "version" else "0" * 64 if name == "plan_sha256" else "other-" + profile[name]
                if name == "plan_sha256":
                    for c in artifact["cases"]:
                        for check in c["comparisons"].values():
                            check["certificate"]["bindings"]["plan_sha256"] = profile[name]
            elif identifier.startswith("retained_binding_"):
                name = identifier.removeprefix("retained_binding_")
                v = next(v for v in VARIANTS if name.startswith(v + "_"))
                field = name.removeprefix(v + "_")
                profile["variant_bindings"][v][field] = "0" * (40 if field == "source_sha" else 64)
                if field == "source_sha" and v in ("cpp_current", "rust_current"):
                    artifact["base_sha"] = "0" * 40
                    for current in ("cpp_current", "rust_current"):
                        profile["variant_bindings"][current]["source_sha"] = "0" * 40
                if field == "source_sha" and v == "rust_candidate":
                    artifact["candidate_sha"] = "0" * 40
            elif identifier.startswith("retained_design_"):
                name = identifier.removeprefix("retained_design_")
                if name == "order_cycle":
                    design[name].reverse()
                else:
                    design[name] += 2 if name == "round_count" else 1
                    artifact["status"] = "HOLD"
                    item.update(status="HOLD", complete=False, comparisons={}, process_count=0, raw_count=0, round_counts={})
                item["collection_design"] = copy.deepcopy(design)
            elif identifier.startswith("retained_case_"):
                name = identifier.removeprefix("retained_case_")
                if name == "case_id":
                    item["case"] = "renamed"
                    profile["collection_design"]["renamed"] = profile["collection_design"].pop("changed")
                    for check in item["comparisons"].values():
                        check["certificate"]["bindings"]["case"] = "renamed"
                elif name == "fixture_sha256":
                    item[name] = "0" * 64
                    for check in item["comparisons"].values():
                        check["certificate"]["bindings"][name] = item[name]
                elif name == "scope":
                    artifact["status"] = item["status"] = "HOLD"
                    item[name] = "kernel"
                elif name == "role":
                    artifact["status"] = "HOLD"
                    item.update(status="HOLD", role="unchanged_control", provenance={"attribution": "another declaration"}, comparisons={})
                elif name == "required_variants_order":
                    item["required_variants"].reverse()
                elif name == "applicability":
                    artifact["status"] = item["status"] = "HOLD"
                    item["rust_preservation_applicability"] = "not_applicable"
                    item["required_variants"].remove("rust_current")
                    del item["comparisons"]["rust_current"]
                    item["provenance"] = {"rust_preservation_rationale": rationale}
                    design["order_cycle"] = [[v for v in order if v != "rust_current"] for order in design["order_cycle"]]
                    item["collection_design"] = copy.deepcopy(design)
                    item["raw_count"] = 24
                elif name == "provenance":
                    item[name] = {"source": "different assertion"}
                else:
                    artifact["cases"].reverse()
            else:
                values = item["provenance"]["values"]
                if identifier.endswith("bool_to_integer"):
                    values[0] = 1
                elif identifier.endswith("integer_to_float"):
                    values[1] = 1.0
                elif identifier.endswith("negative_zero_to_positive_zero"):
                    values[3] = 0.0
                else:
                    values[5][1]["value"] = "abcdef"
            rebind(artifact)
            with self.subTest(retained_source_invalid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                self.assertEqual(retained_preimages[artifact["input_hashes"]["manifest_sha256"]], original_preimage)
                with self.assertRaises(error) as caught:
                    validate(artifact)
                # Specific new predicate, even where an external structural
                # validator or later internal rule could independently reject.
                self.assertIn("retained declaration", str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        key_order = json.loads(json.dumps(uniform), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
        typed_equal = typed_source_artifact()
        self.assertEqual([type(v) for v in typed_equal["cases"][0]["provenance"]["values"][:5]],
                         [bool, int, float, float, type(None)])
        self.assertEqual(typed_equal["cases"][0]["provenance"]["values"][3].hex(), "-0x0.0p+0")
        all_hex = copy.deepcopy(hex_casing)
        all_hex["qualification_profile"]["plan_sha256"] = all_hex["qualification_profile"]["plan_sha256"].upper()
        for c in all_hex["cases"]:
            for check in c["comparisons"].values():
                check["certificate"]["bindings"]["plan_sha256"] = check["certificate"]["bindings"]["plan_sha256"].upper()
        nonemitted = copy.deepcopy(uniform)
        nonemitted_source = campaign_manifest()
        nonemitted_source["toolchain"]["compiler"] = "another-declared-toolchain"
        nonemitted_source["provenance"] = {"arbitrary": [True, 1, 1.0]}
        nonemitted_source["fixtures"][0]["extra"] = {"not_emitted": "preserved in raw hash"}
        retain(nonemitted, nonemitted_source)
        direct_valid = (("retained_object_key_order_only", key_order),
                        ("retained_typed_provenance_identical", typed_equal),
                        ("retained_all_identified_SHA_case_normalization", all_hex),
                        ("retained_valid_nonemitted_metadata_change", nonemitted))
        for identifier, artifact in direct_valid:
            with self.subTest(retained_source_valid=identifier):
                original = json.dumps(artifact, sort_keys=True)
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), original)
        self.assertEqual((len(retained_labels), len(set(retained_labels)), len(direct_valid)), (42, 42, 4))

        # Imported interval/projection consistency:36 negative and12 positive
        # direct-only scenarios. These reuse the same two CLI seeds and exact
        # retained preimages; authored enclosures are NOT proof replay.
        def project(check):
            bounds = check["certificate"]["bounds"]
            check["ratio"] = {"estimate": float(bounds["estimate"][0]),
                              "lower": float(bounds["lower"][0]), "upper": float(bounds["upper"][1])}
        def uniform_metadata(pair, relation="LT", one="LT", baseline="cpp_current"):
            artifact = copy.deepcopy(uniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            check = artifact["cases"][0]["comparisons"][baseline]
            cert = check["certificate"]
            for name in ("lower", "upper", "estimate"):
                cert["bounds"][name] = list(pair)
            cert["rank_enclosures"]["uniform"]["ratio"] = list(pair)
            cert["relations"].update(upper_vs_limit=relation, lower_vs_one=one, upper_vs_one=one, width_vs_policy="LT")
            check["status"] = "HOLD" if relation == "GT" else "PASS"
            project(check)
            return artifact, check
        def nonuniform_metadata(lower, upper, estimate, exact=()):
            artifact = copy.deepcopy(nonuniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            check = artifact["cases"][0]["comparisons"]["cpp_current"]
            check["status"] = "HOLD"
            cert = check["certificate"]
            cert["precision"] = 640 if exact else 80
            cert["bounds"] = {"lower": list(lower), "upper": list(upper), "estimate": list(estimate)}
            # Equal pairs within each selected quantile make the fixed linear
            # projections literal, independently expected endpoints. No math
            # helper or float estimator manufactures these fixture values.
            for rank in ("124", "125"):
                cert["rank_enclosures"]["selected"][rank]["ratio"] = list(lower)
            for rank in ("4874", "4875"):
                cert["rank_enclosures"]["selected"][rank]["ratio"] = list(upper)
            cert["relations"] = {"upper_vs_limit": "LT", "lower_vs_one": "LT",
                                 "upper_vs_one": "LT", "width_vs_policy": "GT"}
            cert["proof"] = {key: "directed_decimal_enclosure" for key in cert["relations"]}
            cert["exact_order_statistics"] = None
            if exact:
                cert["exact_order_statistics"] = {str(rank): {"replicate_id": rank, "process_multiplicities": [1, 1]}
                                                    for rank in (124, 125, 4874, 4875)}
                for key in exact:
                    cert["relations"][key] = "EQ"
                    cert["proof"][key] = ("exact_radical_quotient_classes" if key == "width_vs_policy" else
                                           "exact_rational_root_quantile")
            project(check)
            return artifact, check
        projection_invalid = (
            "reported_upper_two_arbitrary_ratio", "display_estimate_mismatch", "display_lower_mismatch",
            "display_upper_mismatch", "display_ratio_missing", "display_estimate_key_missing",
            "display_extra_ratio_key", "display_boolean_endpoint", "display_nonfinite_endpoint",
            "bounds_interval_reversed", "bounds_ratio_nonpositive", "selected_log_interval_reversed",
            "selected_ratio_nonpositive", "uniform_lower_disagrees", "uniform_upper_disagrees",
            "uniform_estimate_disagrees", "uniform_LT_impossible_at_two", "uniform_GT_impossible_at_quarter",
            "uniform_EQ_threshold_excluded", "uniform_singleton_equality_cannot_be_LT",
            "uniform_one_relation_disagreement", "uniform_Rust_limit_one_relation_disagreement",
            "uniform_wide_CPP_joint_contradiction", "nonuniform_weighted_lower_mismatch",
            "nonuniform_weighted_upper_mismatch", "directed_upper_relation_opposite",
            "directed_lower_one_relation_opposite", "directed_upper_one_relation_opposite",
            "directed_width_relation_opposite", "directed_unresolved_straddle_claim",
            "exact_quantile_EQ_excludes_threshold", "exact_width_EQ_excludes_zero",
            "nonuniform_upper_joint_EQ_contradiction", "bounded_context_overflow",
            "bounded_context_subnormal", "display_projection_underflows_to_zero")
        for identifier in projection_invalid:
            artifact = copy.deepcopy(nonuniform if identifier.startswith(("selected_", "directed_", "nonuniform_", "bounded_"))
                                     else uniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            check = artifact["cases"][0]["comparisons"]["cpp_current"]
            cert = check["certificate"]
            expected_error = "certificate"
            if identifier == "reported_upper_two_arbitrary_ratio":
                cert["bounds"]["upper"] = ["2", "2"]
                check["ratio"] = dict(estimate=3, lower=3, upper=3)
            elif identifier in ("display_estimate_mismatch", "display_lower_mismatch", "display_upper_mismatch"):
                check["ratio"][identifier.removeprefix("display_").removesuffix("_mismatch")] = 3
                expected_error = "display projection"
            elif identifier == "display_ratio_missing":
                del check["ratio"]
                expected_error = "display projection"
            elif identifier == "display_estimate_key_missing":
                del check["ratio"]["estimate"]
                expected_error = "display projection"
            elif identifier == "display_extra_ratio_key":
                check["ratio"]["extra"] = 1
                expected_error = "display projection"
            elif identifier in ("display_boolean_endpoint", "display_nonfinite_endpoint"):
                check["ratio"]["estimate"] = True if identifier == "display_boolean_endpoint" else float("inf")
                expected_error = "display projection"
            elif identifier == "bounds_interval_reversed":
                cert["bounds"]["lower"] = ["2", "1"]
                expected_error = "interval order"
            elif identifier == "bounds_ratio_nonpositive":
                cert["bounds"]["estimate"] = ["0", "0"]
                expected_error = "positive ratio"
            elif identifier == "selected_log_interval_reversed":
                cert["rank_enclosures"]["selected"]["124"]["log"] = ["2", "1"]
                expected_error = "interval order"
            elif identifier == "selected_ratio_nonpositive":
                cert["rank_enclosures"]["selected"]["124"]["ratio"] = ["0", "0"]
                expected_error = "positive ratio"
            elif identifier.startswith("uniform_") and identifier.endswith("_disagrees"):
                name = identifier.removeprefix("uniform_").removesuffix("_disagrees")
                cert["bounds"][name] = ["0.3", "0.3"]
                project(check)
                expected_error = "uniform SAME"
            elif identifier == "uniform_LT_impossible_at_two":
                artifact, check = uniform_metadata(("2", "2"), "LT", "GT")
                expected_error = "relation feasibility"
            elif identifier == "uniform_GT_impossible_at_quarter":
                artifact, check = uniform_metadata(("0.25", "0.25"), "GT")
                expected_error = "relation feasibility"
            elif identifier == "uniform_EQ_threshold_excluded":
                artifact, check = uniform_metadata(("0.25", "0.25"), "EQ")
                expected_error = "relation feasibility"
            elif identifier == "uniform_singleton_equality_cannot_be_LT":
                artifact, check = uniform_metadata(("0.5", "0.5"), "LT")
                expected_error = "relation feasibility"
            elif identifier == "uniform_one_relation_disagreement":
                artifact, check = uniform_metadata(("0.4", "1.1"))
                check["certificate"]["relations"]["upper_vs_one"] = "GT"
                expected_error = "uniform SAME relation"
            elif identifier == "uniform_Rust_limit_one_relation_disagreement":
                artifact, check = uniform_metadata(("0.9", "1.1"), "EQ", "LT", "rust_current")
                expected_error = "uniform SAME relation"
            elif identifier == "uniform_wide_CPP_joint_contradiction":
                artifact, check = uniform_metadata(("0.4", "1.1"), "LT", "GT")
                expected_error = "joint relation feasibility"
            elif identifier.startswith("nonuniform_weighted_"):
                name = identifier.removeprefix("nonuniform_weighted_").removesuffix("_mismatch")
                cert["bounds"][name] = ["0.3", "0.3"]
                project(check)
                expected_error = "weighted projection"
            elif identifier.startswith("directed_") and identifier.endswith("_opposite"):
                key = {"directed_upper_relation_opposite": "upper_vs_limit",
                       "directed_lower_one_relation_opposite": "lower_vs_one",
                       "directed_upper_one_relation_opposite": "upper_vs_one",
                       "directed_width_relation_opposite": "width_vs_policy"}[identifier]
                self.assertEqual(cert["proof"][key], "directed_decimal_enclosure")
                cert["relations"][key] = "GT" if cert["relations"][key] == "LT" else "LT"
                check["status"] = "HOLD"
                expected_error = "directed relation"
            elif identifier == "directed_unresolved_straddle_claim":
                artifact, check = nonuniform_metadata(("0.25", "0.25"), ("0.49", "0.51"), ("0.4", "0.4"))
                expected_error = "directed relation"
            elif identifier == "exact_quantile_EQ_excludes_threshold":
                artifact, check = nonuniform_metadata(("0.1", "0.1"), ("0.25", "0.3"), ("0.2", "0.2"), ("upper_vs_limit",))
                expected_error = "relation feasibility"
            elif identifier == "exact_width_EQ_excludes_zero":
                artifact, check = nonuniform_metadata(("0.25", "0.25"), ("0.4", "0.4"), ("0.3", "0.3"), ("width_vs_policy",))
                expected_error = "relation feasibility"
            elif identifier == "nonuniform_upper_joint_EQ_contradiction":
                artifact, check = nonuniform_metadata(("0.25", "0.25"), ("0.4", "1.1"), ("0.4", "0.4"),
                                                       ("upper_vs_limit", "upper_vs_one"))
                expected_error = "joint relation feasibility"
            elif identifier in ("bounded_context_overflow", "bounded_context_subnormal"):
                literal = "1E+999999" if identifier.endswith("overflow") else "0.1E-999999"
                for rank in ("4874", "4875"):
                    cert["rank_enclosures"]["selected"][rank]["ratio"] = [literal, literal]
                expected_error = "metadata decimal arithmetic"
            else:
                artifact, check = uniform_metadata(("1E-999999", "1E-999999"))
                expected_error = "display projection range"
            before = json.dumps(artifact, sort_keys=True)
            with self.subTest(projection_invalid=identifier):
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn(expected_error, str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), before)
        # Coherent projection fixtures: unchanged helpers construct inputs, but
        # literal zero, float, threshold and interval assertions are independent.
        def metadata_intervals(precision=80):
            return loaded["CampaignIntervals"](precision, loaded["CampaignArithmetic"]())
        def decimals(pair):
            return tuple(loaded["Decimal"](v) for v in pair)
        def coherent_uniform(log_pair, relation="LT", one="LT"):
            intervals = metadata_intervals()
            ratio = intervals.exp(decimals(log_pair))
            artifact, check = uniform_metadata(tuple(str(v) for v in ratio), relation, one)
            check["certificate"]["rank_enclosures"]["uniform"]["log"] = list(log_pair)
            return artifact, check
        def project_selected(artifact, check):
            cert = check["certificate"]
            intervals = metadata_intervals(cert["precision"])
            ranks = {rank: decimals(value["ratio"]) for rank, value in cert["rank_enclosures"]["selected"].items()}
            lower = intervals.scale(intervals.add(ranks["124"], intervals.scale(ranks["125"], 39)), 1, 40)
            upper = intervals.scale(intervals.add(intervals.scale(ranks["4874"], 39), ranks["4875"]), 1, 40)
            cert["bounds"].update(lower=[str(v) for v in lower], upper=[str(v) for v in upper])
            project(check)
            return lower, upper
        def coherent_nonuniform(log_pairs, estimate=("0.5", "0.5"), exact=()):
            artifact = copy.deepcopy(nonuniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            check = artifact["cases"][0]["comparisons"]["cpp_current"]
            check["status"] = "HOLD"
            cert = check["certificate"]
            cert["precision"] = 640 if exact else 80
            intervals = metadata_intervals(cert["precision"])
            for rank, pair in zip(("124", "125", "4874", "4875"), log_pairs):
                cert["rank_enclosures"]["selected"][rank] = {
                    "log": list(pair), "ratio": [str(v) for v in intervals.exp(decimals(pair))]}
            cert["bounds"]["estimate"] = list(estimate)
            lower, upper = project_selected(artifact, check)
            one = decimals(("1", "1"))
            width = intervals.rational((cert["width_policy_rational"]["numerator"],
                                        cert["width_policy_rational"]["denominator"]))
            expressions = {"upper_vs_limit": intervals.subtract(upper, decimals(("0.5", "0.5"))),
                           "lower_vs_one": intervals.subtract(lower, one),
                           "upper_vs_one": intervals.subtract(upper, one),
                           "width_vs_policy": intervals.subtract(intervals.subtract(upper, lower),
                               intervals.product(width, decimals(estimate)))}
            cert["relations"] = {key: "EQ" if key in exact else loaded["campaign_relation"](value)
                                 for key, value in expressions.items()}
            self.assertTrue(all(v in ("LT", "EQ", "GT") for v in cert["relations"].values()))
            cert["proof"] = {key: ("exact_radical_quotient_classes" if key == "width_vs_policy" else
                                   "exact_rational_root_quantile") if key in exact else "directed_decimal_enclosure"
                             for key in expressions}
            cert["exact_order_statistics"] = ({str(rank): {"replicate_id": rank, "process_multiplicities": [1, 1]}
                                               for rank in (124, 125, 4874, 4875)} if exact else None)
            return artifact, check
        straddle_lt, straddle_check = coherent_uniform(("-0.7", "-0.69"), "LT")
        straddle_gt, _ = coherent_uniform(("-0.7", "-0.69"), "GT")
        straddle_eq, _ = coherent_uniform(("-0.7", "-0.69"), "EQ")
        self.assertEqual(straddle_check["ratio"]["lower"], 0.4965853037914095)
        self.assertEqual(straddle_check["ratio"]["upper"], 0.5015760690660556)
        self.assertLess(straddle_check["ratio"]["lower"], 0.5)
        self.assertGreater(straddle_check["ratio"]["upper"], 0.5)
        tiny_width = next(artifact for label, artifact in width_reason_valid if label == "retained_token_underflow_1e_minus324")
        subnormal, subnormal_check = coherent_uniform(("-745", "-744.5"))
        self.assertEqual(subnormal_check["ratio"], dict(estimate=5e-324, lower=5e-324, upper=5e-324))
        quantile_eq, quantile_check = coherent_nonuniform((("-0.7", "-0.69"),) * 4,
                                                         exact=("upper_vs_limit",))
        self.assertLess(quantile_check["ratio"]["lower"], 0.5)
        self.assertGreater(quantile_check["ratio"]["upper"], 0.5)
        width_eq, width_check = coherent_nonuniform((("-0.701", "-0.689"),) * 4,
                                                     exact=("upper_vs_limit", "width_vs_policy"))
        width_check.update(status="PASS", reasons=[])
        self.assertLess(width_check["ratio"]["lower"], 0.5)
        self.assertGreater(width_check["ratio"]["upper"], 0.5)
        outside, outside_check = coherent_nonuniform((("-1", "-1"),) * 4)
        self.assertGreater(outside_check["ratio"]["estimate"], outside_check["ratio"]["upper"])
        one_number = copy.deepcopy(uniform)
        for check in one_number["cases"][1]["comparisons"].values():
            check["ratio"] = dict(estimate=1, lower=1, upper=1)
        projection_valid = (("unchanged_actual_uniform", uniform), ("unchanged_actual_nonuniform", nonuniform),
                            ("uniform_straddling_LT", straddle_lt), ("uniform_straddling_GT_HOLD", straddle_gt),
                            ("uniform_straddling_EQ", straddle_eq), ("uniform_tiny_width_zero_true_width", tiny_width),
                            ("uniform_positive_subnormal_display", subnormal),
                            ("nonuniform_exact_quantile_EQ_straddle", quantile_eq),
                            ("nonuniform_exact_width_EQ_straddle", width_eq),
                            ("estimate_outside_percentile_interval", outside),
                            ("ambient_decimal_context_independent", uniform), ("numeric_integer_one_display", one_number))
        for identifier, artifact in projection_valid:
            before = json.dumps(artifact, sort_keys=True)
            with self.subTest(projection_valid=identifier):
                if identifier == "ambient_decimal_context_independent":
                    import decimal
                    with decimal.localcontext() as ambient:
                        ambient.prec = 2
                        ambient.rounding = decimal.ROUND_DOWN
                        for signal in ambient.traps:
                            ambient.traps[signal] = True
                        prior = (str(ambient), dict(ambient.flags))
                        self.assertIsNone(validate(artifact))
                        self.assertEqual((str(ambient), dict(ambient.flags)), prior)
                else:
                    self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), before)
        projection_labels = list(projection_invalid) + [label for label, _ in projection_valid]
        self.assertEqual((len(projection_invalid), len(projection_valid), len(projection_labels), len(set(projection_labels))),
                         (36, 12, 48, 48))

        # Joint nondecreasing selected ranks: four negative/four positive direct
        # metadata cases. Existing CLI seeds/raw declarations remain unchanged.
        # Literal weighted endpoints below are independent expected projections;
        # no sample/log-exp/bootstrap proof or additional model is constructed.
        def rank_metadata(domain, pairs, bounds=None):
            artifact = copy.deepcopy(nonuniform)
            artifact["status"] = artifact["cases"][0]["status"] = "HOLD"
            check = artifact["cases"][0]["comparisons"]["cpp_current"]
            cert = check["certificate"]
            for rank, pair in zip(("124", "125", "4874", "4875"), pairs):
                cert["rank_enclosures"]["selected"][rank][domain] = list(pair)
            if domain == "ratio":
                cert["precision"] = 80
                cert["bounds"] = copy.deepcopy(bounds)
                cert["relations"] = {key: "LT" for key in cert["relations"]}
                cert["proof"] = {key: "directed_decimal_enclosure" for key in cert["relations"]}
                cert["exact_order_statistics"] = None
                check["status"], check["reasons"] = "PASS", []
                project(check)
            return artifact
        rank_invalid = (
            ("selected_log_inversion", "log", (("2", "2"), ("1", "1"), ("3", "3"), ("4", "4")), None),
            ("selected_log_nonlocal_overlap_contradiction", "log",
             (("1.5", "2"), ("0.25", "2"), ("0.25", "1"), ("1", "3")), None),
            ("selected_ratio_inversion", "ratio", (("2", "2"), ("0.4", "0.4"), ("0.444", "0.444"), ("0.444", "0.444")),
             {"lower": ["0.44", "0.44"], "upper": ["0.444", "0.444"], "estimate": ["0.444", "0.444"]}),
            ("selected_ratio_nonlocal_overlap_contradiction", "ratio",
             (("0.31", "0.32"), ("0.30", "0.32"), ("0.30", "0.305"), ("0.305", "0.32")),
             {"lower": ["0.30025", "0.32"], "upper": ["0.300125", "0.305375"], "estimate": ["3", "3"]}))
        for label, domain, pairs, bounds in rank_invalid:
            artifact = rank_metadata(domain, pairs, bounds)
            before = json.dumps(artifact, sort_keys=True)
            with self.subTest(selected_rank_invalid=label):
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn("selected rank feasibility differs: " + domain, str(caught.exception))
                self.assertEqual(json.dumps(artifact, sort_keys=True), before)
        rank_valid = (
            ("selected_log_feasible_overlap", "log", (("1", "3"), ("2", "4"), ("3", "5"), ("4", "6")), None),
            ("selected_log_ties", "log", (("2", "2"),) * 4, None),
            ("selected_ratio_feasible_overlap", "ratio",
             (("0.30", "0.32"), ("0.31", "0.33"), ("0.32", "0.34"), ("0.33", "0.35")),
             {"lower": ["0.30975", "0.32975"], "upper": ["0.32025", "0.34025"], "estimate": ["4", "4"]}),
            ("selected_ratio_ties", "ratio", (("0.4", "0.4"),) * 4,
             {"lower": ["0.4", "0.4"], "upper": ["0.4", "0.4"], "estimate": ["0.4", "0.4"]}))
        coherent_rank_logs = {
            "selected_log_feasible_overlap": (("1", "1.0001"), ("1.00005", "1.00015"),
                                              ("1.0001", "1.0002"), ("1.00015", "1.00025")),
            "selected_log_ties": (("2", "2"),) * 4,
            "selected_ratio_feasible_overlap": (("-1.2", "-1.1"), ("-1.19", "-1.09"),
                                                  ("-1.18", "-1.08"), ("-1.17", "-1.07")),
            "selected_ratio_ties": (("-1", "-1"),) * 4}
        for label, domain, pairs, bounds in rank_valid:
            artifact, check = coherent_nonuniform(coherent_rank_logs[label], estimate=("4", "4"))
            if label.endswith("ties"):
                records = check["certificate"]["rank_enclosures"]["selected"]
                self.assertTrue(all(records[rank][domain] == records["124"][domain]
                                    for rank in ("125", "4874", "4875")))
            else:
                records = check["certificate"]["rank_enclosures"]["selected"]
                self.assertLess(decimals(records["124"][domain])[0], decimals(records["125"][domain])[0])
                self.assertGreater(decimals(records["124"][domain])[1], decimals(records["125"][domain])[0])
            before = json.dumps(artifact, sort_keys=True)
            with self.subTest(selected_rank_valid=label):
                self.assertIsNone(validate(artifact))
                self.assertEqual(json.dumps(artifact, sort_keys=True), before)
        rank_labels = [record[0] for record in rank_invalid + rank_valid]
        self.assertEqual((len(rank_invalid), len(rank_valid), len(rank_labels), len(set(rank_labels))), (4, 4, 8, 8))

        # Root-selected three-P2 contract expansion. These are Source-only until
        # a separate admitted run; builders construct inputs, not expected gates.
        exp_invalid = []
        a = copy.deepcopy(uniform)
        a["cases"][0]["comparisons"]["cpp_current"]["certificate"]["rank_enclosures"]["uniform"]["log"] = ["100", "100"]
        exp_invalid.append(("uniform_log_100", a))
        for index, rank in enumerate(("124", "125", "4874", "4875")):
            a = copy.deepcopy(nonuniform)
            records = a["cases"][0]["comparisons"]["cpp_current"]["certificate"]["rank_enclosures"]["selected"]
            # Preserve rank feasibility; first altered rank determines new guard.
            for later in ("124", "125", "4874", "4875")[index:]:
                records[later]["log"] = ["100", "100"]
            exp_invalid.append(("selected_" + rank + "_log_100", a))
        for side, position in (("lower", 0), ("upper", 1)):
            a = copy.deepcopy(uniform)
            c = a["cases"][0]["comparisons"]["cpp_current"]
            cert = c["certificate"]
            pair = decimals(cert["rank_enclosures"]["uniform"]["ratio"])
            intervals = metadata_intervals(cert["precision"])
            changed = intervals.near.next_minus(pair[position]) if position == 0 else intervals.near.next_plus(pair[position])
            replacement = [str(v) for v in pair]
            replacement[position] = str(changed)
            cert["rank_enclosures"]["uniform"]["ratio"] = replacement
            cert["bounds"] = {name: list(replacement) for name in ("lower", "upper", "estimate")}
            project(c)
            exp_invalid.append(("uniform_ratio_" + side + "_ulp", a))
        for rank in ("124", "125", "4874", "4875"):
            for side, position in (("lower", 0), ("upper", 1)):
                a = copy.deepcopy(nonuniform)
                c = a["cases"][0]["comparisons"]["cpp_current"]
                cert = c["certificate"]
                pair = decimals(cert["rank_enclosures"]["selected"][rank]["ratio"])
                intervals = metadata_intervals(cert["precision"])
                changed = intervals.near.next_minus(pair[position]) if position == 0 else intervals.near.next_plus(pair[position])
                cert["rank_enclosures"]["selected"][rank]["ratio"][position] = str(changed)
                project_selected(a, c)
                exp_invalid.append(("selected_" + rank + "_ratio_" + side + "_ulp", a))
        zero, zero_check = coherent_uniform(("0", "0"), "GT", "EQ")
        self.assertEqual(zero_check["certificate"]["rank_enclosures"]["uniform"],
                         {"log": ["0", "0"], "ratio": ["1", "1"]})
        bad_zero = copy.deepcopy(zero)
        c = bad_zero["cases"][0]["comparisons"]["cpp_current"]
        c["certificate"]["rank_enclosures"]["uniform"]["ratio"] = ["0.99", "1.01"]
        c["certificate"]["bounds"] = {name: ["0.99", "1.01"] for name in ("lower", "upper", "estimate")}
        project(c)
        exp_invalid.append(("zero_log_ratio_not_one", bad_zero))
        for label, artifact in exp_invalid:
            with self.subTest(exp_invalid=label):
                with self.assertRaises(error) as caught:
                    validate(artifact)
                self.assertIn("log-to-ratio projection", str(caught.exception))
        negative, negative_check = coherent_uniform(("-1", "-1"))
        positive, positive_check = coherent_uniform(("1", "1"), "GT", "GT")
        self.assertEqual(negative_check["ratio"]["estimate"], 0.36787944117144233)
        self.assertEqual(positive_check["ratio"]["estimate"], 2.718281828459045)
        exp_valid = (("actual_uniform_unchanged", uniform), ("actual_nonuniform_unchanged", nonuniform),
                     ("zero_log_exact_one", zero), ("negative_log_producer_projection", negative),
                     ("positive_log_producer_projection", positive), ("straddling_exact_relations_preserved", straddle_eq),
                     ("coherent_tiny_positive_float_display", subnormal), ("ambient_context_unchanged", uniform))
        for label, artifact in exp_valid:
            with self.subTest(exp_valid=label):
                if label == "ambient_context_unchanged":
                    import decimal
                    with decimal.localcontext() as ambient:
                        ambient.prec = 2
                        for signal in ambient.traps:
                            ambient.traps[signal] = True
                        original = (str(ambient), dict(ambient.flags))
                        self.assertIsNone(validate(artifact))
                        self.assertEqual((str(ambient), dict(ambient.flags)), original)
                else:
                    self.assertIsNone(validate(artifact))
        expected_methodology = {'analysis_identity': 'invocation source snapshot sampled for stability; not loaded-code or pre-load race authentication', 'arithmetic': 'campaign directed enclosures with bounded exact equality certification; floats display only', 'arithmetic_policy_sha256': '4fe3e8086c88da789540bdbed6825e65f8adc18c41c73840a3aaaf7895092d39', 'bootstrap_replicates': 5000, 'comparison_rng': 'each named comparison resets the fixed seed', 'coverage': 'per-case intervals; no simultaneous family coverage guarantee', 'interval': '95% percentile bootstrap; linear quantiles at 0.025 and 0.975', 'limits': 'numerical eligibility only; declarations do not attest caller/domain/ABI, native execution, build lineage, independence, reviewed applicability, retirement or hold release', 'outliers': 'all retained; no trimming or independent round resampling', 'ratio_estimator': 'exp(mean(process mean(log(paired candidate/baseline ns/op))))', 'resampling_unit': 'whole process cluster; every paired round retained', 'seed': 20261011}
        self.assertEqual(len(uniform["methodology"]), 15)
        for key, literal in expected_methodology.items():
            self.assertIs(type(uniform["methodology"][key]), type(literal))
            self.assertEqual(uniform["methodology"][key], literal)
        methodology_invalid = []
        for key in tuple(expected_methodology) + ("policy", "exact_width_policy", "arithmetic_work_cumulative"):
            a = copy.deepcopy(uniform)
            del a["methodology"][key]
            methodology_invalid.append(("missing_" + key, a, True))
        for key, literal in expected_methodology.items():
            a = copy.deepcopy(uniform)
            a["methodology"][key] = literal + 1 if type(literal) is int else literal + "; changed"
            methodology_invalid.append(("wrong_" + key, a, True))
        for label in ("unknown_methodology_key", "boolean_seed", "unknown_work_counter", "overcap_work_counter",
                      "boolean_work_counter", "final_work_below_witness"):
            a = copy.deepcopy(uniform)
            work = a["methodology"]["arithmetic_work_cumulative"]
            if label == "unknown_methodology_key":
                a["methodology"]["unexpected"] = "not emitted"
            elif label == "boolean_seed":
                a["methodology"]["seed"] = True
            elif label == "unknown_work_counter":
                work["not_emitted"] = 0
            elif label == "overcap_work_counter":
                work["exp_calls"] = 7681
            elif label == "boolean_work_counter":
                work["exp_calls"] = True
            else:
                witness_work = a["cases"][0]["comparisons"]["cpp_current"]["certificate"]["work_cumulative"]
                key = next(k for k, value in witness_work.items() if value > 0)
                work[key] = witness_work[key] - 1
            methodology_invalid.append((label, a, label != "final_work_below_witness"))
        for label, artifact, schema_rejects in methodology_invalid:
            with self.subTest(methodology_invalid=label):
                with self.assertRaises(error):
                    validate(artifact)
                if schema_rejects:
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(artifact)
                else:
                    validator.validate(artifact)
        later_work = copy.deepcopy(uniform)
        later_work["methodology"]["arithmetic_work_cumulative"]["exp_calls"] += 1
        sparse_work = copy.deepcopy(uniform)
        unused = next(k for k in loaded["CAMPAIGN_ARITHMETIC_LIMITS"]
                      if k not in sparse_work["methodology"]["arithmetic_work_cumulative"])
        sparse_work["methodology"]["arithmetic_work_cumulative"][unused] = 0
        methodology_valid = (("actual_fifteen_fields", uniform), ("valid_cumulative_later_work", later_work),
                             ("valid_sparse_unused_zero_work", sparse_work))
        for label, artifact in methodology_valid:
            with self.subTest(methodology_valid=label):
                validator.validate(artifact)
                self.assertIsNone(validate(artifact))
        sample_invalid = []
        for label in ("missing_sample_bytes", "sample_not_bytes", "sample_over_32MiB",
                      "artifact_and_all_certificates_relabelled", "wrong_original_sample_bytes",
                      "whitespace_changed_original_bytes", "final_newline_changed_original_bytes",
                      "contained_PASS_under_outer_HOLD_relabelled"):
            a = copy.deepcopy(uniform)
            supplied = default_sample_bytes
            if label == "missing_sample_bytes":
                supplied = None
            elif label == "sample_not_bytes":
                supplied = bytearray(default_sample_bytes)
            elif label == "sample_over_32MiB":
                supplied = b"x" * (32 * 1024 * 1024 + 1)
            elif "relabelled" in label:
                a["input_hashes"]["samples_sha256"] = "0" * 64
                for item in a["cases"]:
                    for c in item["comparisons"].values():
                        c["certificate"]["bindings"]["input_hashes"]["samples_sha256"] = "0" * 64
                if label.startswith("contained_PASS"):
                    a["status"] = a["cases"][0]["status"] = "HOLD"
            elif label == "wrong_original_sample_bytes":
                supplied = nonuniform_sample_bytes
            elif label == "whitespace_changed_original_bytes":
                supplied += b" "
            else:
                self.assertTrue(supplied.endswith(b"\n"))
                supplied = supplied[:-1]
            sample_invalid.append((label, a, supplied))
        for label, artifact, supplied in sample_invalid:
            with self.subTest(sample_invalid=label):
                with self.assertRaises(error) as caught:
                    validate(artifact, sample_bytes=supplied)
                self.assertIn("retained sample", str(caught.exception))
        upper_hash = copy.deepcopy(uniform)
        upper_hash["input_hashes"]["samples_sha256"] = upper_hash["input_hashes"]["samples_sha256"].upper()
        for item in upper_hash["cases"]:
            for c in item["comparisons"].values():
                c["certificate"]["bindings"]["input_hashes"]["samples_sha256"] = upper_hash["input_hashes"]["samples_sha256"]
        diagnostic = copy.deepcopy(uniform)
        diagnostic["status"] = "HOLD"
        for item in diagnostic["cases"]:
            item.update(status="HOLD", comparisons={})
        sample_valid = (("actual_uniform_preimage", uniform, default_sample_bytes),
                        ("actual_nonuniform_preimage", nonuniform, nonuniform_sample_bytes),
                        ("upper_case_sample_digest", upper_hash, default_sample_bytes),
                        ("no_witness_HOLD_without_preimage", diagnostic, None))
        for label, artifact, supplied in sample_valid:
            with self.subTest(sample_valid=label):
                self.assertIsNone(validate(artifact, sample_bytes=supplied))
        new_labels = ([label for label, _ in exp_invalid + list(exp_valid)] +
                      [label for label, _, _ in methodology_invalid] + [label for label, _ in methodology_valid] +
                      [label for label, _, _ in sample_invalid + list(sample_valid)])
        self.assertEqual((len(exp_invalid), len(exp_valid), len(methodology_invalid), len(methodology_valid),
                          len(sample_invalid), len(sample_valid), len(new_labels), len(set(new_labels))),
                         (16, 8, 33, 3, 8, 4, 72, 72))


if __name__ == "__main__":
    unittest.main()
