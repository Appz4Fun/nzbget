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
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(os.environ.get("BENCH_PIPELINE_ROOT", Path(__file__).resolve().parents[3]))
PUBLISHER_ROOT = Path(os.environ.get("BENCH_PUBLISHER_ROOT", ROOT))
BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
INPUT_DIGEST = hashlib.sha256(b"controlled integration input").hexdigest()
OUTPUT_DIGEST = hashlib.sha256(b"controlled equivalent output").hexdigest()
VARIANTS = ("cpp_current", "cpp_optimized", "rust_current", "rust_candidate")
ARTIFACTS = ("summary.json", "bencher.json", "qualification.json", "report.md")

# Replace only external HTTP transport. The actual publisher CLI, parsing,
# signature/blob checks, identity binding and failure outputs still execute.
# Unknown endpoints and every write are refused; this process cannot network.
PUBLISHER_TRANSPORT = r'''
import io, json, pathlib, runpy, sys, urllib.parse, urllib.request
script, fixture, journal, *arguments = sys.argv[1:]
responses = json.loads(pathlib.Path(fixture).read_text())
def controlled_open(self, request, *args, **kwargs):
    parsed = urllib.parse.urlsplit(request.full_url)
    endpoint = parsed.path + ("?" + parsed.query if parsed.query else "")
    method = request.get_method()
    with pathlib.Path(journal).open("a") as output:
        output.write(json.dumps({"method": method, "endpoint": endpoint}) + "\n")
    if parsed.scheme != "https" or parsed.netloc != "api.github.com" or method != "GET":
        raise AssertionError("unexpected network origin or authenticated write")
    if endpoint not in responses:
        raise AssertionError("unexpected external API endpoint: " + endpoint)
    class Response(io.BytesIO):
        pass
    return Response(json.dumps(responses[endpoint]).encode())
urllib.request.OpenerDirector.open = controlled_open
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
                      "scope": scope, "role": "changed", "required_variants": list(VARIANTS)}],
        "comparison": {"baseline": "cpp_optimized", "candidate": "rust_candidate"},
    }


def controlled_rows(candidate_ns=800, processes=8, rounds=10, case="controlled/caller"):
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
        script = ROOT / "scripts/bench/summarize.py"
        self.assertTrue(script.is_file(), f"Shared CLI dependency missing: {script}")
        result = subprocess.run([sys.executable, str(script), "--manifest", str(self.manifest),
                                 "--samples", str(self.samples), "--output-dir", str(self.output)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(before, (self.manifest.read_bytes(), self.samples.read_bytes()),
                         "The shared CLI must preserve immutable raw inputs")
        return result

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
        rows = controlled_rows() + controlled_rows(candidate_ns=1000, case=control["id"])
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


class PublisherIdentityContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nzbget-publisher-contract-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.output = self.work / "validated"
        self.journal = self.work / "api-calls.jsonl"
        self.github_output = self.work / "github-output"

    def invoke(self, manifest=None, current_base=BASE_SHA, current_head=CANDIDATE_SHA,
               actor="xbmc4lyfe", identity_only=False):
        import base64
        evidence_sha, tree_sha = "3" * 40, "4" * 40
        manifest = controlled_manifest() if manifest is None else manifest
        raw_files = {"manifest.json": json.dumps(manifest).encode(),
                     "samples.jsonl": b""}
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
                "head": {"sha": current_head}},
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
        fixture = self.work / "api-responses.json"
        fixture.write_text(json.dumps(responses), encoding="utf-8")
        script = PUBLISHER_ROOT / "scripts/bench/publish.py"
        self.assertTrue(script.is_file(), f"Publisher dependency missing: {script}")
        arguments = ["--github-output", str(self.github_output)]
        if identity_only:
            arguments += ["--verify-identity-only"]
        else:
            arguments += ["--mode", "pr", "--repository", "Appz4Fun/nzbget", "--pr", "7",
                          "--evidence-sha", evidence_sha, "--expected-base-sha", BASE_SHA,
                          "--expected-head-sha", CANDIDATE_SHA, "--controller-sha", BASE_SHA,
                          "--testbed", manifest["testbed"], "--output-dir", str(self.output)]
        env = {"PATH": os.environ.get("PATH", ""), "BENCH_GITHUB_TOKEN": "controlled-no-network-canary",
               "BENCH_GITHUB_ACTOR": "xbmc4lyfe", "GITHUB_ACTOR": "xbmc4lyfe"}
        result = subprocess.run([sys.executable, "-I", "-c", PUBLISHER_TRANSPORT,
                                 str(script), str(fixture), str(self.journal), *arguments],
                                env=env, capture_output=True, text=True, timeout=30)
        calls = [json.loads(line) for line in self.journal.read_text().splitlines()]
        self.assertTrue(all(call["method"] == "GET" for call in calls),
                        "Rejected artifacts/identity must never trigger authenticated writes")
        self.assertNotIn("controlled-no-network-canary", result.stdout + result.stderr)
        return result

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


if __name__ == "__main__":
    unittest.main()
