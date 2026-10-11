"""Synthetic controls test statistics and proof validation, never product speed."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "summarize.py"


def manifest(scope="complete_caller"):
    return {"schema_version": 1, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
            "testbed": "synthetic-testbed", "toolchain": {"cxx": "synthetic", "rustc": "synthetic"},
            "fixtures": [{"id": "tiny-control", "sha256": "c" * 64, "scope": scope}],
            "comparison": {"baseline": "cpp_current", "candidate": "rust_candidate"}}


def samples(ratios=None, processes=8, rounds=10):
    ratios = ratios or [0.8] * processes
    rows = []
    for p in range(processes):
        for r in range(rounds):
            for variant, factor, order in [("cpp_current", 1, r % 2),
                                            ("rust_candidate", ratios[p], 1 - r % 2)]:
                rows.append({"case": "tiny-control", "variant": variant, "process": p,
                             "round": r, "order": order, "elapsed_ns": 10000 * factor,
                             "iterations": 10, "observable_digest": "d" * 64})
    return rows


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("bench_summarize", SCRIPT)
            cls.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.mod)

    def run_summary(self, m=None, rows=None):
        self.assertTrue(SCRIPT.exists(), "summary implementation not written yet")
        return self.mod.summarize(m or manifest(), samples() if rows is None else rows)

    def test_known_equal_faster_slower_controls(self):
        for ratio, want, statistical in [(1, "HOLD", "inconclusive"),
                                          (0.8, "PASS", "faster"), (1.2, "HOLD", "slower")]:
            with self.subTest(ratio=ratio):
                summary, bmf, qualification = self.run_summary(rows=samples([ratio] * 8))
                case = summary["cases"][0]
                self.assertEqual(qualification["status"], want)
                self.assertEqual(case["statistical_status"], statistical)
                self.assertAlmostEqual(case["ratio"]["estimate"], ratio)
                self.assertEqual(case["raw_count"], 160)
                self.assertAlmostEqual(bmf["tiny-control/rust_candidate"]["latency"]["value"], 1000 * ratio)

    def test_cluster_uncertainty_keeps_noisy_result_on_hold(self):
        summary, _, qualification = self.run_summary(rows=samples([0.2, 0.3, 0.4, 0.5, 0.7, 1.3, 2, 4]))
        case = summary["cases"][0]
        self.assertEqual(qualification["status"], "HOLD")
        self.assertLess(case["ratio"]["lower"], 1)
        self.assertGreater(case["ratio"]["upper"], 1)
        self.assertIn("noisy_ratio_interval", case["reasons"])

    def test_repeated_rounds_do_not_fake_independent_process_precision(self):
        ratios = [0.5, 0.5, 0.5, 0.5, 1.5, 1.5, 1.5, 1.5]
        short = self.run_summary(rows=samples(ratios))[0]["cases"][0]["ratio"]
        long = self.run_summary(rows=samples(ratios, rounds=100))[0]["cases"][0]["ratio"]
        self.assertAlmostEqual(short["lower"], long["lower"])
        self.assertAlmostEqual(short["upper"], long["upper"])

    def test_kernel_only_is_never_runtime_qualification(self):
        summary, _, qualification = self.run_summary(manifest("kernel"))
        self.assertEqual(summary["cases"][0]["statistical_status"], "faster")
        self.assertEqual(qualification["status"], "HOLD")
        self.assertIn("no_changed_complete_caller_evidence", qualification["reasons"])

    def test_genuine_unchanged_control_checks_drift_without_speed_claim(self):
        m = manifest()
        m["fixtures"][0].update(role="unchanged_control", provenance={"attribution": "synthetic same caller"})
        for ratio, want in [(1, "PASS"), (0.8, "HOLD"), (1.2, "HOLD")]:
            summary, _, qualification = self.run_summary(m, samples([ratio] * 8))
            self.assertEqual(summary["cases"][0]["status"], want)
            self.assertEqual(qualification["status"], "HOLD")
        m["fixtures"][0].pop("provenance")
        with self.assertRaises(ValueError):
            self.run_summary(m)

    def test_changed_and_kernel_fixture_provenance_must_be_object(self):
        for scope in ("complete_caller", "kernel"):
            for invalid in ("not-an-object", [], None, 42, True):
                with self.subTest(scope=scope, provenance=invalid):
                    m = manifest(scope)
                    m["fixtures"][0]["provenance"] = invalid
                    with self.assertRaises(ValueError):
                        self.run_summary(m)
            m = manifest(scope)
            m["fixtures"][0]["provenance"] = {}
            summary, _, _ = self.run_summary(m)
            self.assertEqual(summary["cases"][0]["provenance"], {})

    def test_prospective_policy_configuration_is_recorded_and_validated(self):
        m = manifest()
        m["qualification_policy"] = {"min_processes": 2, "min_rounds": 4, "min_each_order": 1,
                                     "max_relative_ci_width": 0.05}
        summary, _, q = self.run_summary(m, samples(processes=2, rounds=4))
        self.assertEqual(q["status"], "PASS")
        self.assertEqual(summary["methodology"]["policy"], m["qualification_policy"])
        for key, value in [("min_processes", 1), ("min_rounds", True),
                           ("min_each_order", 0), ("max_relative_ci_width", float("nan")),
                           ("unexpected", 1)]:
            bad = copy.deepcopy(m)
            bad["qualification_policy"][key] = value
            with self.assertRaises(ValueError):
                self.run_summary(bad)

    def test_report_escapes_printable_ids_and_rejects_control_characters(self):
        m = manifest()
        m["fixtures"][0]["id"] = "tiny|<control>`"
        rows = samples()
        for row in rows:
            row["case"] = "tiny|<control>`"
        summary, _, q = self.run_summary(m, rows)
        report = self.mod.render_report(summary, q)
        self.assertIn("tiny\\|&lt;control&gt;", report)
        m["fixtures"][0]["id"] = "bad\ncontrol"
        with self.assertRaises(ValueError):
            self.run_summary(m, [])

    def test_published_synthetic_fixture_and_schemas_are_parseable(self):
        fixtures = SCRIPT.parent / "tests" / "fixtures"
        m = json.loads((fixtures / "synthetic-manifest.json").read_text())
        rows = [json.loads(line) for line in (fixtures / "synthetic-samples.jsonl").read_text().splitlines()]
        _, _, qualification = self.run_summary(m, rows)
        self.assertEqual(qualification["status"], "HOLD")
        self.assertIn("insufficient_processes", qualification["cases"][0]["reasons"])
        for path in (SCRIPT.parent / "schema").glob("*.schema.json"):
            json.loads(path.read_text())

    def test_insufficient_process_rounds_and_order_balance_hold(self):
        for rows in [samples(processes=1), samples(rounds=2), samples()]:
            if len(rows) == 160:
                for row in rows:
                    row["order"] = int(row["variant"] == "rust_candidate")
            summary, _, qualification = self.run_summary(rows=rows)
            self.assertEqual(qualification["status"], "HOLD")
            self.assertTrue(summary["cases"][0]["reasons"])

    def test_entirely_missing_variants_and_fixtures_hold(self):
        for rows in [[], [r for r in samples() if r["variant"] == "cpp_current"]]:
            summary, _, qualification = self.run_summary(rows=rows)
            self.assertEqual(qualification["status"], "HOLD")
            self.assertEqual(summary["cases"][0]["statistical_status"], "missing")

    def test_duplicate_unmatched_wrong_digest_unknown_fixture_rejected(self):
        variations = []
        variations.append(samples() + [samples()[0]])
        variations.append(samples()[:-1])
        for field, value in [("observable_digest", "e" * 64), ("case", "unknown"), ("order", 3)]:
            rows = samples()
            rows[0][field] = value
            variations.append(rows)
        for rows in variations:
            with self.subTest(rows=rows[:1]):
                with self.assertRaises(ValueError):
                    self.run_summary(rows=rows)

    def test_invalid_numbers_and_missing_fields_rejected(self):
        for field, value in [("elapsed_ns", float("nan")), ("elapsed_ns", float("inf")),
                             ("elapsed_ns", 0), ("elapsed_ns", True), ("iterations", 0),
                             ("iterations", 1.5), ("process", True), ("round", -1)]:
            rows = samples()
            rows[0][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.run_summary(rows=rows)
        rows = samples()
        del rows[0]["observable_digest"]
        with self.assertRaises(ValueError):
            self.run_summary(rows=rows)

    def test_invalid_manifest_identity_and_variants_rejected(self):
        for key, value in [("schema_version", 2), ("schema_version", True), ("base_sha", "abc"),
                           ("candidate_sha", "z" * 40), ("toolchain", {}),
                           ("toolchain", {"rustc": 99}), ("testbed", "")]:
            m = manifest()
            m[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.run_summary(m)
        m = manifest()
        m["comparison"]["candidate"] = "invented"
        with self.assertRaises(ValueError):
            self.run_summary(m)

    def test_numeric_extremes_reject_underflow_and_nonfinite_ratios(self):
        for elapsed, iterations in [(5e-324, 2), (10**500, 1)]:
            rows = samples()
            rows[0].update(elapsed_ns=elapsed, iterations=iterations)
            with self.assertRaises(ValueError):
                self.run_summary(rows=rows)
        rows = samples()
        for row in rows:
            row.update(elapsed_ns=5e-324 if row["variant"] == "cpp_current" else 1e308, iterations=1)
        with self.assertRaises(ValueError):
            self.run_summary(rows=rows)

    def test_large_finite_latencies_have_finite_history_medians(self):
        rows = samples()
        for row in rows:
            row.update(elapsed_ns=1e308 if row["variant"] == "cpp_current" else 8e307, iterations=1)
        _, bmf, q = self.run_summary(rows=rows)
        self.assertEqual(q["status"], "PASS")
        self.assertEqual(bmf["tiny-control/cpp_current"]["latency"]["value"], 1e308)
        json.dumps(bmf, allow_nan=False)

    def test_resource_bounds_and_non_json_extensions_rejected(self):
        m = manifest()
        m["fixtures"] *= 65
        with self.assertRaises(ValueError):
            self.run_summary(m, [])
        with self.assertRaises(ValueError):
            self.run_summary(rows=samples(processes=129))
        m = manifest()
        m["provenance"] = {"claimed_number": float("inf")}
        with self.assertRaises(ValueError):
            self.run_summary(m)

    def test_budget_counts_latency_and_ratio_bootstraps(self):
        m = manifest()
        rows = []
        m["fixtures"] = []
        for index in range(5):
            fixture = {"id": f"control-{index}", "sha256": "c" * 64, "scope": "complete_caller"}
            m["fixtures"].append(fixture)
            for row in samples(processes=64, rounds=2):
                row["case"] = fixture["id"]
                rows.append(row)
        # 5*64*5000*(2 variant histories + 1 ratio) > four million.
        with self.assertRaises(ValueError):
            self.run_summary(m, rows)

    def test_noncomparison_required_variant_remains_in_complete_blocks(self):
        m = manifest()
        m["fixtures"][0]["required_variants"] = ["cpp_current", "rust_candidate", "rust_current"]
        rows = samples()
        for row in rows:
            row["order"] = (0 if row["variant"] == "cpp_current" else 2) if row["round"] % 2 == 0 else (2 if row["variant"] == "cpp_current" else 0)
        for p in range(8):
            for r in range(10):
                rows.append({"case": "tiny-control", "variant": "rust_current", "process": p,
                             "round": r, "order": 1, "elapsed_ns": 9000, "iterations": 10,
                             "observable_digest": "d" * 64})
        summary, bmf, q = self.run_summary(m, rows)
        self.assertEqual(q["status"], "PASS")
        self.assertEqual(summary["cases"][0]["raw_count"], 240)
        self.assertIn("tiny-control/rust_current", bmf)
        with self.assertRaises(ValueError):
            self.run_summary(m, rows[:-1])

    def test_cpp_gain_does_not_hide_existing_rust_regression(self):
        m = manifest()
        m["fixtures"][0]["required_variants"] = ["cpp_current", "rust_current", "rust_candidate"]
        for current_ns, want in [(5000, "HOLD"), (8000, "PASS"), (9000, "PASS")]:
            rows = samples()
            for p in range(8):
                for r in range(10):
                    # Whole-block reversal balances both comparison pairs.
                    for row in rows:
                        if row["process"] == p and row["round"] == r:
                            row["order"] = (0 if row["variant"] == "cpp_current" else 2) if r % 2 == 0 else (2 if row["variant"] == "cpp_current" else 0)
                    rows.append({"case": "tiny-control", "variant": "rust_current", "process": p,
                                 "round": r, "order": 1, "elapsed_ns": current_ns, "iterations": 10,
                                 "observable_digest": "d" * 64})
            with self.subTest(current_ns=current_ns):
                summary, _, q = self.run_summary(m, rows)
                self.assertEqual(q["status"], want)
                case = summary["cases"][0]
                self.assertAlmostEqual(case["ratio"]["estimate"], 0.8)
                self.assertAlmostEqual(case["rust_preservation"]["ratio"]["estimate"], 8000 / current_ns)
                self.assertEqual(case["rust_preservation"]["status"], want)
                self.assertEqual(q["cases"][0]["rust_preservation"], case["rust_preservation"])

    def test_optimized_cpp_tie_stays_hold_when_current_rust_is_preserved(self):
        m = manifest()
        m["comparison"]["baseline"] = "cpp_optimized"
        m["fixtures"][0]["required_variants"] = ["cpp_optimized", "rust_current", "rust_candidate"]
        rows = samples()
        for row in rows:
            if row["variant"] == "cpp_current":
                row.update(variant="cpp_optimized", elapsed_ns=8000)
            row["order"] = (0 if row["variant"] == "cpp_optimized" else 2) if row["round"] % 2 == 0 else (2 if row["variant"] == "cpp_optimized" else 0)
        for p in range(8):
            for r in range(10):
                rows.append({"case": "tiny-control", "variant": "rust_current", "process": p,
                             "round": r, "order": 1, "elapsed_ns": 9000, "iterations": 10,
                             "observable_digest": "d" * 64})
        summary, _, q = self.run_summary(m, rows)
        self.assertEqual(q["status"], "HOLD")
        self.assertIn("not_confidently_faster", summary["cases"][0]["reasons"])
        self.assertEqual(summary["cases"][0]["rust_preservation"]["status"], "PASS")

    def test_current_rust_gate_applies_to_cpp_candidate(self):
        m = manifest()
        m["comparison"]["candidate"] = "cpp_optimized"
        m["fixtures"][0]["required_variants"] = ["cpp_current", "rust_current", "cpp_optimized"]
        rows = self.rust_three_way_rows([5000] * 8)
        for row in rows:
            if row["variant"] == "rust_candidate":
                row["variant"] = "cpp_optimized"
        summary, _, q = self.run_summary(m, rows)
        self.assertEqual(q["status"], "HOLD")
        check = summary["cases"][0]["rust_preservation"]
        self.assertEqual(check["candidate"], "cpp_optimized")
        self.assertAlmostEqual(check["ratio"]["estimate"], 1.6)

    @staticmethod
    def rust_three_way_rows(current_elapsed, candidate_elapsed=8000):
        rows = samples()
        for row in rows:
            if row["variant"] == "rust_candidate":
                row["elapsed_ns"] = candidate_elapsed
            row["order"] = (0 if row["variant"] == "cpp_current" else 2) if row["round"] % 2 == 0 else (2 if row["variant"] == "cpp_current" else 0)
        for p in range(8):
            for r in range(10):
                rows.append({"case": "tiny-control", "variant": "rust_current", "process": p,
                             "round": r, "order": 1, "elapsed_ns": current_elapsed[p], "iterations": 10,
                             "observable_digest": "d" * 64})
        return rows

    def test_current_rust_overlap_above_one_holds_changed_case(self):
        m = manifest()
        m["fixtures"][0]["required_variants"] = ["cpp_current", "rust_current", "rust_candidate"]
        summary, _, q = self.run_summary(m, self.rust_three_way_rows([7920] * 4 + [8080] * 4))
        check = summary["cases"][0]["rust_preservation"]
        self.assertLess(check["ratio"]["lower"], 1)
        self.assertGreater(check["ratio"]["upper"], 1)
        self.assertEqual(q["status"], "HOLD")
        self.assertIn("not_preserved", check["reasons"])

    def test_unchanged_rust_controls_include_one_and_hold_either_drift(self):
        m = manifest()
        m["fixtures"][0].update(role="unchanged_control", provenance={"attribution": "synthetic unchanged caller"},
                                 required_variants=["cpp_current", "rust_current", "rust_candidate"])
        for current, want in [([9900] * 4 + [10100] * 4, "PASS"), ([5000] * 8, "HOLD"), ([20000] * 8, "HOLD")]:
            with self.subTest(current=current):
                summary, _, q = self.run_summary(m, self.rust_three_way_rows(current, 10000))
                case = summary["cases"][0]
                self.assertEqual(case["status"], want)
                self.assertEqual(case["rust_preservation"]["status"], want)
                self.assertEqual(q["status"], "HOLD")  # controls never establish a changed caller's speedup
                if want == "HOLD":
                    self.assertIn("unchanged_control_drift", case["rust_preservation"]["reasons"])
                report = self.mod.render_report(summary, q)
                self.assertIn("Candidate / current Rust", report)

    def test_extra_rust_comparison_counts_against_bootstrap_budget(self):
        m = manifest()
        m["fixtures"] = []
        rows = []
        for index in range(3):
            case = f"rust-budget-{index}"
            m["fixtures"].append({"id": case, "sha256": "c" * 64, "scope": "complete_caller",
                                  "required_variants": ["cpp_current", "rust_current", "rust_candidate"]})
            for row in samples(processes=64, rounds=2):
                row["case"] = case
                rows.append(row)
            for p in range(64):
                for r in range(2):
                    rows.append({"case": case, "variant": "rust_current", "process": p, "round": r,
                                 "order": 2, "elapsed_ns": 9000, "iterations": 10,
                                 "observable_digest": "d" * 64})
        # Three variant histories + selected CPP ratio are 3.84 million
        # selections; the required current-Rust ratio raises it to 4.8 million.
        with self.assertRaises(ValueError):
            self.run_summary(m, rows)

    def test_all_outliers_and_controls_retained(self):
        m = manifest()
        m["fixtures"].append({"id": "normal-control", "sha256": "f" * 64, "scope": "complete_caller"})
        rows = samples()
        second = copy.deepcopy(rows)
        for row in second:
            row["case"] = "normal-control"
        rows[0]["elapsed_ns"] = 10**12
        snapshot = copy.deepcopy(rows + second)
        summary, _, _ = self.run_summary(m, rows + second)
        self.assertEqual(rows + second, snapshot)
        self.assertEqual([c["raw_count"] for c in summary["cases"]], [160, 160])
        self.assertEqual([c["case"] for c in summary["cases"]], ["tiny-control", "normal-control"])

    def test_cli_outputs_hashes_deterministic_artifacts_and_never_overwrites_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mf, sf = tmp / "manifest.json", tmp / "samples.jsonl"
            mf.write_text(json.dumps(manifest()))
            sf.write_text("\n".join(json.dumps(r) for r in samples()) + "\n")
            before = (mf.read_bytes(), sf.read_bytes())
            cmd = [sys.executable, str(SCRIPT), "--manifest", str(mf), "--samples", str(sf)]
            first = subprocess.run(cmd + ["--output-dir", str(tmp / "out")], capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            artifacts = {p.name: p.read_bytes() for p in (tmp / "out").iterdir()}
            self.assertEqual(set(artifacts), {"summary.json", "bencher.json", "qualification.json", "report.md"})
            self.assertIn("input_hashes", json.loads(artifacts["summary.json"]))
            second = subprocess.run(cmd + ["--output-dir", str(tmp / "again")], capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(artifacts, {p.name: p.read_bytes() for p in (tmp / "again").iterdir()})
            self.assertEqual(before, (mf.read_bytes(), sf.read_bytes()))
            # An input named like an output must never be replaced.
            collision = tmp / "summary.json"
            collision.write_bytes(sf.read_bytes())
            bad = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(mf),
                                  "--samples", str(collision), "--output-dir", str(tmp)], capture_output=True)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(collision.read_bytes(), before[1])

    def test_cli_rejects_duplicate_json_keys_and_malformed_json_without_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mf, sf = tmp / "manifest.json", tmp / "samples.jsonl"
            sf.write_text(json.dumps(samples()[0]) + "\n")
            for body in ['{"schema_version":1,"schema_version":1}', '{broken']:
                mf.write_text(body)
                out = tmp / "out"
                result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(mf),
                                         "--samples", str(sf), "--output-dir", str(out)], capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(out.exists())

    def test_invalid_reimport_removes_stale_pass_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mf, sf, out = tmp / "manifest.json", tmp / "samples.jsonl", tmp / "out"
            mf.write_text(json.dumps(manifest()))
            sf.write_text("\n".join(json.dumps(r) for r in samples()) + "\n")
            cmd = [sys.executable, str(SCRIPT), "--manifest", str(mf), "--samples", str(sf), "--output-dir", str(out)]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(json.loads((out / "qualification.json").read_text())["status"], "PASS")
            sf.write_text('{"process":0,"process":0}\n')
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
            self.assertEqual(list(out.iterdir()), [])

    def test_hardlinked_output_alias_rejected_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mf, sf, out = tmp / "manifest.json", tmp / "samples.jsonl", tmp / "out"
            mf.write_text(json.dumps(manifest()))
            sf.write_text("\n".join(json.dumps(r) for r in samples()) + "\n")
            out.mkdir()
            alias = out / "summary.json"
            os.link(sf, alias)
            before = sf.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(mf),
                                     "--samples", str(sf), "--output-dir", str(out)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(alias.samefile(sf))
            self.assertEqual(before, sf.read_bytes())

    def test_input_traversal_ancestor_symlink_is_never_unlinked(self):
        for use_parent in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                real, out = tmp / "real", tmp / "out"
                real.mkdir()
                out.mkdir()
                alias = out / "summary.json"
                alias.symlink_to(real, target_is_directory=True)
                mf, sf = real / "manifest.json", real / "samples.jsonl"
                mf.write_text(json.dumps(manifest()))
                sf.write_text("\n".join(json.dumps(r) for r in samples()) + "\n")
                # Even a later '..' does not undo traversal through the symlink.
                supplied = alias / "manifest.json"
                if use_parent:
                    supplied = alias / ".." / "real" / "manifest.json"
                before = (mf.read_bytes(), sf.read_bytes())
                result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(supplied),
                                         "--samples", str(sf), "--output-dir", str(out)], capture_output=True)
                with self.subTest(use_parent=use_parent):
                    self.assertEqual(result.returncode, 2)
                    self.assertTrue(alias.is_symlink())
                    self.assertEqual(before, (mf.read_bytes(), sf.read_bytes()))


if __name__ == "__main__":
    unittest.main()
