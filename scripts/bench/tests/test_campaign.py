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
               raw_manifest=None, raw_samples=None, output=None, prepare=None):
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
        argv = [sys.executable, "-B", str(SCRIPT), "--manifest", str(manifest_path),
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


if __name__ == "__main__":
    unittest.main()
