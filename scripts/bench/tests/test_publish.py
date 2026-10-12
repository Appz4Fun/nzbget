"""Publisher trust-boundary tests; no credentials, API writes, or benchmarks."""
import copy
import argparse
import contextlib
import hashlib
import importlib.util
import json
import io
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "publish.py"
spec = importlib.util.spec_from_file_location("publish", SCRIPT) if SCRIPT.exists() else None
publish = importlib.util.module_from_spec(spec) if spec else None
if spec:
    spec.loader.exec_module(publish)

BASE, HEAD, EVIDENCE = "1" * 40, "2" * 40, "3" * 40


class StatusAPI:
    """Controlled GitHub transport with an existing green head status."""
    def __init__(self, base=BASE, head=HEAD, actor="xbmc4lyfe", state="open", head_repo="Appz4Fun/nzbget", ref="dupe-article-fallback"):
        self.base, self.head, self.actor = base, head, actor
        self.state, self.head_repo, self.ref = state, head_repo, ref
        self.writes = []
        self.statuses = [{"context": "paired caller qualification", "state": "success",
                          "description": "PASS base:" + BASE, "creator": {"login": "xbmc4lyfe"}}]

    def get(self, endpoint):
        if endpoint == "/user":
            return {"login": self.actor}
        if "/branches/" in endpoint:
            return {"commit": {"sha": self.base}, "protected": False}
        if "/pulls/" in endpoint:
            return {"number": 7, "state": self.state, "base": {"sha": self.base, "ref": self.ref, "repo": {"full_name": "Appz4Fun/nzbget"}},
                    "head": {"sha": self.head, "repo": {"full_name": self.head_repo}}}
        if "/commits/" in endpoint:
            return {"sha": EVIDENCE, "author": {"login": "xbmc4lyfe"}, "committer": {"login": "xbmc4lyfe"},
                    "commit": {"author": {"name": "xbmc4lyfe"}, "committer": {"name": "xbmc4lyfe"},
                               "verification": {"verified": False, "reason": "unsigned"}, "tree": {"sha": "4" * 40}},
                    "files": [{"filename": "benchmark-results/manifest.json", "status": "added"}]}
        return {"default_branch": "dupe-article-fallback"}

    def get_list(self, endpoint):
        return self.statuses if "/statuses?" in endpoint else []

    def post(self, endpoint, payload):
        self.writes.append((endpoint, payload))
        if "/statuses/" in endpoint:
            self.statuses.insert(0, dict(payload, creator={"login": self.actor}))
        return {}


class EvidenceAPI(StatusAPI):
    """Immutable synthetic signed-transport fixture; no real network."""
    def __init__(self, contents):
        super().__init__()
        self.entries = []
        self.blobs = {}
        for name, raw in contents.items():
            sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            self.entries.append({"path": "benchmark-results/" + name, "sha": sha, "mode": "100644", "type": "blob", "size": len(raw)})
            self.blobs[sha] = {"sha": sha, "encoding": "base64", "content": __import__("base64").b64encode(raw).decode()}

    def get(self, endpoint):
        if "/commits/" in endpoint:
            return {"sha": EVIDENCE, "author": {"login": "xbmc4lyfe"}, "committer": {"login": "xbmc4lyfe"},
                    "commit": {"author": {"name": "xbmc4lyfe"}, "committer": {"name": "xbmc4lyfe"},
                               "verification": {"verified": True, "reason": "valid"}, "tree": {"sha": "4" * 40}},
                    "files": [{"filename": item["path"], "status": "added"} for item in self.entries]}
        if "/git/trees/" in endpoint:
            return {"truncated": False, "tree": self.entries}
        if "/git/blobs/" in endpoint:
            return self.blobs[endpoint.rsplit("/", 1)[1]]
        return super().get(endpoint)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(publish, "trusted data-only publisher has not been implemented")

    def commit(self):
        return {"sha": EVIDENCE, "author": {"login": "xbmc4lyfe"},
                "committer": {"login": "xbmc4lyfe"}, "commit": {
                    "author": {"name": "xbmc4lyfe"}, "committer": {"name": "xbmc4lyfe"},
                    "verification": {"verified": True, "reason": "valid"},
                    "tree": {"sha": "4" * 40}},
                "files": [{"filename": "benchmark-results/manifest.json", "status": "added"}]}

    def test_rejects_unsigned_other_actor_and_executable_evidence_commits(self):
        publish.validate_evidence_commit(self.commit(), EVIDENCE)
        for mutate in (lambda c: c["commit"]["verification"].update(verified=False),
                       lambda c: c["author"].update(login="someone"),
                       lambda c: c["committer"].update(login="github-actions[bot]"),
                       lambda c: c["commit"]["author"].update(name="Someone Else"),
                       lambda c: c["files"].append({"filename": "scripts/run.py", "status": "modified"})):
            bad = self.commit()
            mutate(bad)
            with self.assertRaises(publish.PublicationError):
                publish.validate_evidence_commit(bad, EVIDENCE)

    def test_rejects_truncated_or_symlink_tree(self):
        tree = {"truncated": False, "tree": [{"path": "benchmark-results/manifest.json", "mode": "100644", "type": "blob", "sha": "4" * 40}]}
        self.assertIn("benchmark-results/manifest.json", publish.data_tree(tree))
        for mode in ("120000", "100755", "160000"):
            bad = copy.deepcopy(tree)
            bad["tree"][0]["mode"] = mode
            with self.assertRaises(publish.PublicationError):
                publish.data_tree(bad)
        tree["truncated"] = True
        with self.assertRaises(publish.PublicationError):
            publish.data_tree(tree)

    def test_json_rejects_duplicates_nonfinite_and_nonobject(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e1000}', b'[]', b'bad'):
            with self.assertRaises(publish.PublicationError):
                publish.json_object(raw)

    def test_blob_sha_binds_downloaded_bytes(self):
        raw = b'{"a":1}'
        sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        publish.verify_blob(raw, sha, 100)
        for altered, bound in ((raw + b" ", 100), (raw, 2)):
            with self.assertRaises(publish.PublicationError):
                publish.verify_blob(altered, sha, bound)

    def test_pr_binding_rejects_stale_base_head_closed_and_wrong_repository(self):
        pr = {"number": 7, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
              "head": {"sha": HEAD, "repo": {"full_name": "Appz4Fun/nzbget"}}}
        publish.validate_pr(pr, "Appz4Fun/nzbget", 7, BASE, HEAD)
        for mutate in (lambda p: p["base"].update(sha="9" * 40), lambda p: p["head"].update(sha="9" * 40),
                       lambda p: p.update(state="closed"), lambda p: p["base"]["repo"].update(full_name="other/repo"),
                       lambda p: p["head"]["repo"].update(full_name="fork/repo"), lambda p: p["head"].update(repo=None)):
            bad = copy.deepcopy(pr)
            mutate(bad)
            with self.assertRaises(publish.PublicationError):
                publish.validate_pr(bad, "Appz4Fun/nzbget", 7, BASE, HEAD)

    def test_manual_malformed_or_stale_evidence_revokes_existing_success(self):
        for current_base in (BASE, "5" * 40):
            api = StatusAPI(base=current_base)
            with tempfile.TemporaryDirectory() as temp, patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = publish.main(["--mode", "pr", "--publish", "--repository", "Appz4Fun/nzbget", "--evidence-sha", EVIDENCE,
                                       "--expected-base-sha", BASE, "--expected-head-sha", HEAD, "--controller-sha", current_base,
                                       "--pr", "7", "--testbed", "i7-existing", "--output-dir", temp])
            self.assertEqual(result, 2)
            self.assertEqual([payload["state"] for _, payload in api.writes], ["pending", "failure"])
            self.assertEqual(api.statuses[0]["state"], "failure")

    def test_automatic_base_change_revokes_old_success_but_preserves_new_current_pass(self):
        current_base = "5" * 40
        api = StatusAPI(base=current_base)
        result = publish.update_pr_status(api, "Appz4Fun/nzbget", 7, current_base, "pending", "automatic")
        self.assertTrue(result["written"])
        self.assertEqual(api.statuses[0]["state"], "pending")
        api.statuses.insert(0, {"context": "paired caller qualification", "state": "success",
                               "description": "PASS base:" + current_base, "creator": {"login": "xbmc4lyfe"}})
        api.writes.clear()
        result = publish.update_pr_status(api, "Appz4Fun/nzbget", 7, current_base, "pending", "automatic")
        self.assertEqual(result["status"], "skip_current_pass")
        self.assertEqual(api.writes, [])
        # Manual revalidation remains independent of delayed automatic events.
        publish.update_pr_status(api, "Appz4Fun/nzbget", 7, current_base, "pending", expected_head=HEAD)
        self.assertEqual(api.statuses[0]["state"], "pending")

    def test_lifecycle_wrong_identity_closed_fork_retarget_and_moved_head_write_nothing(self):
        for api in (StatusAPI(actor="github-actions[bot]"), StatusAPI(state="closed"),
                    StatusAPI(head_repo="fork/repo"), StatusAPI(head_repo=None), StatusAPI(ref="develop"),
                    StatusAPI(head="6" * 40), StatusAPI(base="5" * 40)):
            with self.assertRaises(publish.PublicationError):
                publish.update_pr_status(api, "Appz4Fun/nzbget", 7, BASE, "failure", expected_head=HEAD)
            self.assertEqual(api.writes, [])

    def test_hold_status_does_not_require_bencher_configuration_or_execute_a_command(self):
        api = StatusAPI()
        with patch.dict("os.environ", {}, clear=True), patch.object(publish, "GitHub", return_value=api), patch.object(publish.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            result = publish.main(["--set-pr-status", "failure", "--status-intent", "manual", "--repository", "Appz4Fun/nzbget",
                                   "--controller-sha", BASE, "--pr", "7", "--expected-head-sha", HEAD])
            self.assertEqual(result, 0)
            run.assert_not_called()
        self.assertEqual(api.statuses[0]["state"], "failure")

    def test_missing_dedicated_identity_has_no_fallback_and_does_not_write(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "bot-token"}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(publish.main(["--set-pr-status", "failure", "--controller-sha", BASE, "--pr", "7", "--expected-head-sha", HEAD]), 2)

    def test_status_head_changed_after_identity_recheck_cannot_write_old_or_new_head(self):
        class Moving(StatusAPI):
            def __init__(self):
                super().__init__()
                self.identities = 0
            def get(self, endpoint):
                if endpoint == "/user":
                    self.identities += 1
                    if self.identities == 2:
                        self.head = "6" * 40
                return super().get(endpoint)
        api = Moving()
        with self.assertRaises(publish.PublicationError):
            publish.update_pr_status(api, "Appz4Fun/nzbget", 7, BASE, "pending", expected_head=HEAD)
        self.assertEqual(api.writes, [])

    def test_pr_number_aliases_cannot_bypass_archive_concurrency_group(self):
        self.assertEqual(publish.canonical_pr_number("17"), 17)
        for alias in ("017", "+17", " 17", "17 ", "0", "-17", "1\n", "1e1"):
            with self.assertRaises(publish.PublicationError):
                publish.canonical_pr_number(alias)

    def test_discovery_paginates_and_excludes_forks_and_status_history_is_paginated(self):
        class Pages(StatusAPI):
            def get_list(self, endpoint):
                if "/statuses?" in endpoint:
                    if endpoint.endswith("page=1"):
                        return [{"context": "unrelated"}] * 100
                    return self.statuses
                if endpoint.endswith("page=1"):
                    return [{"number": number, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                             "head": {"sha": HEAD, "repo": {"full_name": "Appz4Fun/nzbget"}}} for number in range(1, 101)]
                return [{"number": 101, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                         "head": {"sha": HEAD, "repo": {"full_name": "Appz4Fun/nzbget"}}},
                        {"number": 102, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                         "head": {"sha": HEAD, "repo": {"full_name": "fork/repo"}}}]
        api = Pages()
        self.assertEqual(publish.list_lifecycle_prs(api, "Appz4Fun/nzbget", BASE), list(range(1, 102)))
        self.assertEqual(publish.latest_qualification(api, "Appz4Fun/nzbget", HEAD)["state"], "success")

    def test_automatic_invalidation_does_not_trust_another_actor_or_unbound_success(self):
        for creator, description in (("github-actions[bot]", "PASS base:" + BASE), ("xbmc4lyfe", "PASS")):
            api = StatusAPI()
            api.statuses[0].update(creator={"login": creator}, description=description)
            result = publish.update_pr_status(api, "Appz4Fun/nzbget", 7, BASE, "pending", "automatic")
            self.assertTrue(result["written"])
            self.assertEqual(api.statuses[0]["state"], "pending")

    def test_discovery_exceeding_github_matrix_bound_fails_instead_of_dropping_targets(self):
        class Many(StatusAPI):
            def get_list(self, endpoint):
                page = int(endpoint.rsplit("page=", 1)[1])
                return [{"number": number, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                         "head": {"sha": HEAD, "repo": {"full_name": "Appz4Fun/nzbget"}}} for number in range((page - 1) * 100 + 1, page * 100 + 1)]
        with self.assertRaises(publish.PublicationError):
            publish.list_lifecycle_prs(Many(), "Appz4Fun/nzbget", BASE)

    def test_success_is_bound_to_latest_live_head_and_full_base_sha(self):
        api = StatusAPI()
        args = argparse.Namespace(mode="pr", repository="Appz4Fun/nzbget", pr=7, expected_base_sha=BASE,
                                  controller_sha=BASE, testbed="i7-existing", output_dir=Path("results"), evidence_sha=EVIDENCE)
        with patch.dict("os.environ", {"BENCHER_KEY": "private-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run", return_value=argparse.Namespace(returncode=0)):
            publish.publish_results(api, args, self.manifest(), {"status": "PASS"}, True)
        self.assertEqual(api.writes[0][1]["description"], "PASS base:" + BASE)
        api = StatusAPI()
        def moved(*args, **kwargs):
            api.head = "6" * 40
            return argparse.Namespace(returncode=0)
        with patch.dict("os.environ", {"BENCHER_KEY": "private-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run", side_effect=moved):
            with self.assertRaises(publish.PublicationError):
                publish.publish_results(api, args, self.manifest(), {"status": "PASS"}, True)
        self.assertEqual(api.writes, [])

    def test_bencher_write_is_blocked_when_identity_check_moves_live_head(self):
        class Moving(StatusAPI):
            def get(self, endpoint):
                response = super().get(endpoint)
                if endpoint == "/user":
                    self.head = "6" * 40
                return response
        api = Moving()
        args = argparse.Namespace(mode="pr", repository="Appz4Fun/nzbget", pr=7, expected_base_sha=BASE,
                                  controller_sha=BASE, testbed="i7-existing", output_dir=Path("results"), evidence_sha=EVIDENCE)
        with patch.dict("os.environ", {"BENCHER_KEY": "private-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run", return_value=argparse.Namespace(returncode=0)) as run:
            with self.assertRaises(publish.PublicationError):
                publish.publish_results(api, args, self.manifest(), {"status": "PASS"}, True)
            run.assert_not_called()
        self.assertEqual(api.writes, [])

    def test_zero_or_fork_only_lifecycle_targets_are_empty_without_writes(self):
        class ForkOnly(StatusAPI):
            def get_list(self, endpoint):
                return [{"number": 7, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                         "head": {"sha": HEAD, "repo": {"full_name": "fork/repo"}}}]
        for api in (StatusAPI(), ForkOnly()):
            self.assertEqual(publish.list_lifecycle_prs(api, "Appz4Fun/nzbget", BASE), [])
            self.assertEqual(api.writes, [])

    def test_identity_uses_api_not_actor_environment(self):
        class API:
            def get(self, endpoint):
                self.endpoint = endpoint
                return {"login": "github-actions[bot]"}
        with self.assertRaises(publish.PublicationError):
            publish.verified_github_actor(API())
        class User(API):
            def get(self, endpoint):
                return {"login": "xbmc4lyfe"}
        self.assertEqual(publish.verified_github_actor(User()), "xbmc4lyfe")

    def test_archive_checks_identity_live_state_and_same_repository(self):
        class API:
            def __init__(self, state="closed", actor="xbmc4lyfe", repository="Appz4Fun/nzbget"):
                self.state, self.actor, self.repository = state, actor, repository
            def get(self, endpoint):
                if endpoint == "/user":
                    return {"login": self.actor}
                return {"number": 7, "state": self.state, "base": {"ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                        "head": {"repo": {"full_name": self.repository}}}
        self.assertEqual(publish.archive_guard(API(), "Appz4Fun/nzbget", 7), {"status": "ready", "ready": True, "actor": "xbmc4lyfe"})
        self.assertEqual(publish.archive_guard(API(state="open"), "Appz4Fun/nzbget", 7)["status"], "skip_reopened")
        for api in (API(actor="bot"), API(repository="fork/repo"), API(state="unknown")):
            with self.assertRaises(publish.PublicationError):
                publish.archive_guard(api, "Appz4Fun/nzbget", 7)

    def manifest(self):
        return {"schema_version": 1, "base_sha": BASE, "candidate_sha": HEAD, "testbed": "i7-existing",
                "comparison": {"baseline": "cpp_current", "candidate": "rust_candidate"},
                "fixtures": [{"id": "caller", "sha256": "a" * 64, "scope": "complete_caller",
                              "rust_preservation_applicability": "not_applicable",
                              "provenance": {"rust_preservation_rationale": "Synthetic fixture has no existing Rust caller"}}]}

    def receipt(self, manifest_raw=b"manifest", samples_raw=b"samples"):
        content_hashes = {"cpp_current": "1" * 64, "rust_candidate": "2" * 64}
        return {"schema_version": 1, "review": {"actor": "xbmc4lyfe", "status": "reviewed",
                                              "source_content_hashes": dict(content_hashes),
                                              "rust_preservation_applicability": {"caller": "not_applicable"}},
                "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(), "samples_sha256": hashlib.sha256(samples_raw).hexdigest(),
                "base_sha": BASE, "candidate_sha": HEAD, "testbed": "i7-existing",
                "source_hashes": {"cpp_current": BASE, "rust_candidate": HEAD},
                "source_content_hashes": content_hashes,
                "compiler_hashes": {"c++": "b" * 64}, "binary_hashes": {"cpp_current": "c" * 64, "rust_candidate": "d" * 64},
                "input_hashes": {"caller": "a" * 64}, "commands": {
                    "build": [{"name": "cmake", "sha256": "6" * 64, "argv_sha256": "8" * 64}],
                    "time": [{"name": "prebuilt-caller", "sha256": "7" * 64, "argv_sha256": "9" * 64}]},
                "runner": {"implementation_sha256": "e" * 64, "build_jobs": 3,
                           "lock_scope": "worker_default",
                           "build_locks": ["i7-heavy.lock:exclusive", "nzbget-rust-benchmark.lock:shared"],
                           "time_locks": ["nzbget-rust-benchmark.lock:exclusive"], "time_prebuilt": True}}

    def proof_contents(self):
        manifest = self.manifest()
        manifest["toolchain"] = {"fixture": "synthetic controlled clock test"}
        manifest_raw = json.dumps(manifest).encode()
        rows = []
        for process in range(8):
            for round_number in range(10):
                variants = ["cpp_current", "rust_candidate"] if round_number % 2 == 0 else ["rust_candidate", "cpp_current"]
                for order, variant in enumerate(variants):
                    rows.append({"case": "caller", "variant": variant, "process": process, "round": round_number,
                                 "order": order, "elapsed_ns": 1000 if variant == "cpp_current" else 800,
                                 "iterations": 1, "observable_digest": "a" * 64})
        samples_raw = b"\n".join(json.dumps(row).encode() for row in rows) + b"\n"
        return {"manifest.json": manifest_raw, "samples.jsonl": samples_raw,
                "collection-receipt.json": json.dumps(self.receipt(manifest_raw, samples_raw)).encode()}

    def publication_arguments(self, output):
        return ["--mode", "pr", "--publish", "--repository", "Appz4Fun/nzbget", "--evidence-sha", EVIDENCE,
                "--expected-base-sha", BASE, "--expected-head-sha", HEAD, "--controller-sha", BASE,
                "--pr", "7", "--testbed", "i7-existing", "--output-dir", str(output)]

    def test_failed_bencher_preserves_acquired_raw_proof_and_clears_stale_pass(self):
        contents = self.proof_contents()
        api = EvidenceAPI(contents)
        original_run = publish.subprocess.run
        bencher_calls = []
        def run(command, **kwargs):
            if command[0] == "bencher":
                bencher_calls.append(command)
                return argparse.Namespace(returncode=1)
            return original_run(command, **kwargs)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            output.mkdir()
            (output / "qualification.json").write_text('{"status":"PASS"}')
            with patch.object(publish, "GitHub", return_value=api), patch.dict("os.environ", {"BENCHER_KEY": "fake-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = publish.main(self.publication_arguments(output))
            self.assertEqual(result, 2)
            self.assertEqual(len(bencher_calls), 1)
            for name, raw in contents.items():
                self.assertTrue((output / name).is_file(), "raw proof was deleted: " + name)
                self.assertEqual((output / name).read_bytes(), raw)
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
            self.assertFalse((output / "selected-bencher.json").exists())
            self.assertEqual(api.statuses[0]["state"], "failure")

    def test_malformed_manifest_preserves_acquired_raw_bytes_before_json_validation(self):
        contents = {"manifest.json": b'{"truncated":', "samples.jsonl": b"raw samples\n", "collection-receipt.json": b"raw receipt\n"}
        api = EvidenceAPI(contents)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(publish, "GitHub", return_value=api), patch.object(publish.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = publish.main(self.publication_arguments(temp))
                run.assert_not_called()
            self.assertEqual(result, 2)
            for name, raw in contents.items():
                self.assertTrue((Path(temp) / name).is_file(), "acquired raw proof was not retained: " + name)
                self.assertEqual((Path(temp) / name).read_bytes(), raw)
            self.assertEqual(json.loads((Path(temp) / "qualification.json").read_text())["status"], "HOLD")

    def test_each_verified_blob_is_durable_before_later_transport_or_validation_failure(self):
        contents = self.proof_contents()
        names = list(contents)
        for failure_at in (2, 3):
            for failure_kind in ("transport", "validation"):
                with self.subTest(failure_at=failure_at, failure_kind=failure_kind), tempfile.TemporaryDirectory() as temp:
                    output = Path(temp) / "results"
                    class LaterFailure(EvidenceAPI):
                        def __init__(self):
                            super().__init__(contents)
                            self.fetches = 0
                            self.before_fetch = []
                        def get(self, endpoint):
                            if "/git/blobs/" in endpoint:
                                self.fetches += 1
                                self.before_fetch.append([name for name in names if (output / name).is_file()])
                                if self.fetches == failure_at:
                                    if failure_kind == "transport":
                                        raise publish.PublicationError("controlled later transport failure")
                                    blob = dict(super().get(endpoint))
                                    blob["content"] = __import__("base64").b64encode(b"controlled wrong blob bytes").decode()
                                    return blob
                            return super().get(endpoint)
                    api = LaterFailure()
                    with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        result = publish.main(self.publication_arguments(output))
                    self.assertEqual(result, 2)
                    self.assertEqual(api.before_fetch[-1], names[:failure_at - 1])
                    for name in names[:failure_at - 1]:
                        self.assertEqual((output / name).read_bytes(), contents[name])
                    for name in names[failure_at - 1:]:
                        self.assertFalse((output / name).exists())
                    self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
                    self.assertEqual(api.statuses[0]["state"], "failure")

    def test_raw_aliases_and_hardlinks_survive_both_reuse_and_hold_cleanup(self):
        for alias in ("symlink", "chain", "hardlink", "qualification"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "results"
                output.mkdir()
                target_name = "qualification.json" if alias == "qualification" else "summary.json"
                original = b'{"status":"PASS","raw":"original proof"}'
                target = output / target_name
                target.write_bytes(original)
                raw = output / "manifest.json"
                if alias == "hardlink":
                    os.link(target, raw)
                elif alias == "chain":
                    (output / "bencher.json").symlink_to(target.name)
                    raw.symlink_to("bencher.json")
                else:
                    raw.symlink_to(target.name)
                if target_name != "qualification.json":
                    (output / "qualification.json").write_text('{"status":"PASS"}')
                workflow = Path(temp) / "workflow-output"
                api = StatusAPI()
                with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = publish.main(self.publication_arguments(output) + ["--github-output", str(workflow)])
                self.assertEqual(result, 2)
                self.assertEqual(raw.read_bytes(), original)
                self.assertEqual(target.read_bytes(), original)
                if alias == "hardlink":
                    self.assertEqual(raw.stat().st_ino, target.stat().st_ino)
                else:
                    self.assertTrue(raw.is_symlink())
                if alias == "chain":
                    self.assertTrue((output / "bencher.json").is_symlink())
                recorded = dict(line.split("=", 1) for line in workflow.read_text().splitlines())
                self.assertEqual((recorded["status"], recorded["ready"], recorded["published"]), ("HOLD", "false", "false"))
                self.assertIn("HOLD", (output / "report.md").read_text())
                self.assertEqual(api.statuses[0]["state"], "failure")

    def test_intermediate_symlink_entries_inside_raw_targets_are_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            output.mkdir()
            real = output / "real"
            real.mkdir()
            (real / "manifest.json").write_bytes(b"raw traversed proof")
            (output / "summary.json").symlink_to("real", target_is_directory=True)
            (output / "bridge").symlink_to("summary.json/manifest.json")
            (output / "manifest.json").symlink_to("bridge")
            (output / "qualification.json").write_text('{"status":"PASS"}')
            api = StatusAPI()
            with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publish.main(self.publication_arguments(output)), 2)
            self.assertEqual((output / "manifest.json").read_bytes(), b"raw traversed proof")
            self.assertTrue((output / "summary.json").is_symlink())
            self.assertTrue((output / "bridge").is_symlink())
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")

    def test_partial_acquisition_hardlink_cannot_be_deleted_by_hold_cleanup(self):
        contents = self.proof_contents()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            class LinkedFailure(EvidenceAPI):
                def __init__(self):
                    super().__init__(contents)
                    self.fetches = 0
                def get(self, endpoint):
                    if "/git/blobs/" in endpoint:
                        self.fetches += 1
                        if self.fetches == 2:
                            os.link(output / "manifest.json", output / "selected-bencher.json")
                            raise publish.PublicationError("controlled failure after raw hardlink")
                    return super().get(endpoint)
            api = LinkedFailure()
            with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publish.main(self.publication_arguments(output)), 2)
            self.assertEqual((output / "manifest.json").read_bytes(), contents["manifest.json"])
            self.assertEqual((output / "selected-bencher.json").read_bytes(), contents["manifest.json"])
            self.assertEqual(api.statuses[0]["state"], "failure")

    def test_cumulative_raw_alias_protection_keeps_targets_after_redirection(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            output.mkdir()
            (output / "summary.json").write_bytes(b"original raw target")
            (output / "bencher.json").write_bytes(b"redirected raw target")
            (output / "manifest.json").symlink_to("summary.json")
            class Redirected(StatusAPI):
                def __init__(self):
                    super().__init__()
                    self.identities = 0
                def get(self, endpoint):
                    if endpoint == "/user":
                        self.identities += 1
                        if self.identities == 3:
                            (output / "manifest.json").unlink()
                            (output / "manifest.json").symlink_to("bencher.json")
                    return super().get(endpoint)
            api = Redirected()
            with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publish.main(self.publication_arguments(output)), 2)
            self.assertEqual((output / "summary.json").read_bytes(), b"original raw target")
            self.assertEqual((output / "bencher.json").read_bytes(), b"redirected raw target")
            self.assertEqual(os.readlink(output / "manifest.json"), "bencher.json")
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")

    def test_reused_output_preserves_first_proof_rejects_new_download_and_invalidates_pass(self):
        first = {"manifest.json": b"first manifest", "samples.jsonl": b"first samples", "collection-receipt.json": b"first receipt"}
        class NoEvidence(EvidenceAPI):
            def get(self, endpoint):
                if "/commits/" in endpoint or "/git/" in endpoint:
                    raise AssertionError("reused output must be rejected before another evidence download")
                return super().get(endpoint)
        api = NoEvidence(self.proof_contents())
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for name, raw in first.items():
                (output / name).write_bytes(raw)
            (output / "qualification.json").write_text('{"status":"PASS"}')
            (output / "selected-bencher.json").write_text('{"old":"metric"}')
            with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = publish.main(self.publication_arguments(output))
            self.assertEqual(result, 2)
            for name, raw in first.items():
                self.assertEqual((output / name).read_bytes(), raw)
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
            self.assertFalse((output / "selected-bencher.json").exists())
            self.assertEqual([payload["state"] for _, payload in api.writes], ["pending", "failure"])

    def test_derived_directory_or_directory_link_preserves_proof_and_cannot_leave_pass(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "results"
                output.mkdir()
                raw = {"manifest.json": b"first manifest", "samples.jsonl": b"first samples", "collection-receipt.json": b"first receipt"}
                for name, content in raw.items():
                    (output / name).write_bytes(content)
                target = Path(temp) / "preserved-directory" if linked else output / "summary.json"
                target.mkdir()
                (target / "sentinel").write_bytes(b"directory contents preserved")
                if linked:
                    (output / "summary.json").symlink_to(target, target_is_directory=True)
                (output / "qualification.json").write_text('{"status":"PASS"}')
                (output / "selected-bencher.json").write_text('{"old":"metric"}')
                api = StatusAPI()
                with patch.object(publish, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = publish.main(self.publication_arguments(output))
                self.assertEqual(result, 2)
                self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
                self.assertIn("HOLD", (output / "report.md").read_text())
                self.assertFalse((output / "selected-bencher.json").exists())
                self.assertEqual([payload["state"] for _, payload in api.writes], ["pending", "failure"])
                for name, content in raw.items():
                    self.assertEqual((output / name).read_bytes(), content)
                self.assertEqual((target / "sentinel").read_bytes(), b"directory contents preserved")
                self.assertEqual((output / "summary.json").is_symlink(), linked)

    def test_missing_mismatched_and_unreviewed_receipt_hold_publication(self):
        self.assertEqual(publish.receipt_reasons(self.receipt(), self.manifest(), b"manifest", b"samples"), [])
        self.assertTrue(publish.receipt_reasons(None, self.manifest(), b"manifest", b"samples"))
        for mutate in (lambda r: r.update(samples_sha256="0" * 64), lambda r: r["review"].update(actor="bot"),
                       lambda r: r["source_hashes"].update(rust_candidate=BASE), lambda r: r["runner"].update(build_jobs=4),
                       lambda r: r["runner"].update(time_prebuilt=False), lambda r: r["input_hashes"].update(caller="f" * 64)):
            receipt = self.receipt()
            mutate(receipt)
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))

    def test_legacy_receipt_without_reviewed_content_hashes_and_decisions_holds(self):
        legacy = self.receipt()
        legacy.pop("source_content_hashes")
        legacy["review"] = {"actor": "xbmc4lyfe", "status": "reviewed"}
        self.assertTrue(publish.receipt_reasons(legacy, self.manifest(), b"manifest", b"samples"))

    def test_source_content_capture_and_review_must_match_exact_required_digest_keys(self):
        self.assertEqual(publish.receipt_reasons(self.receipt(), self.manifest(), b"manifest", b"samples"), [])
        for value in (None, {}, {"cpp_current": "1" * 64}, {"cpp_current": "1" * 64, "rust_candidate": int("2" * 64)},
                      {"cpp_current": "1" * 64, "rust_candidate": "2" * 64, "rust_current": "3" * 64}):
            receipt = self.receipt()
            receipt["source_content_hashes"] = value
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        receipt = self.receipt()
        receipt["source_content_hashes"]["rust_candidate"] = "9" * 64
        self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        for field in ("source_content_hashes", "rust_preservation_applicability"):
            for value in (None, []):
                receipt = self.receipt()
                receipt["review"][field] = value
                self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        receipt = self.receipt()
        receipt["review"]["extra"] = "approval"
        self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        for value in (None, {"cpp_current": "9" * 64, "rust_candidate": "2" * 64}):
            manifest = self.manifest()
            manifest["provenance"] = {"source_content_hashes": value}
            self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))

    def test_explicit_reviewed_rust_applicability_and_required_rows(self):
        manifest = self.manifest()
        receipt = self.receipt()
        self.assertEqual(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"), [])
        for decision in (None, "required", "invalid"):
            changed = copy.deepcopy(manifest)
            if decision is None:
                changed["fixtures"][0].pop("rust_preservation_applicability")
            else:
                changed["fixtures"][0]["rust_preservation_applicability"] = decision
            self.assertTrue(publish.receipt_reasons(receipt, changed, b"manifest", b"samples"))
        for decisions in ({}, {"caller": "required"}, {"caller": "not_applicable", "extra": "required"}):
            changed = self.receipt()
            changed["review"]["rust_preservation_applicability"] = decisions
            self.assertTrue(publish.receipt_reasons(changed, manifest, b"manifest", b"samples"))
        manifest["fixtures"][0].update(rust_preservation_applicability="required", required_variants=["cpp_current", "rust_current", "rust_candidate"])
        receipt["source_hashes"]["rust_current"] = BASE
        receipt["binary_hashes"]["rust_current"] = "3" * 64
        receipt["source_content_hashes"]["rust_current"] = "4" * 64
        receipt["review"]["source_content_hashes"] = dict(receipt["source_content_hashes"])
        receipt["review"]["rust_preservation_applicability"] = {"caller": "required"}
        rows = json.dumps({"case": "caller", "variant": "rust_current", "process": 0, "round": 0, "order": 0,
                           "elapsed_ns": 1000, "iterations": 1, "observable_digest": "a" * 64}).encode() + b"\n"
        receipt["samples_sha256"] = hashlib.sha256(rows).hexdigest()
        self.assertEqual(publish.receipt_reasons(receipt, manifest, b"manifest", rows), [])
        missing_rows = b""
        receipt["samples_sha256"] = hashlib.sha256(missing_rows).hexdigest()
        self.assertTrue(publish.receipt_reasons(receipt, manifest, b"manifest", missing_rows))

    def test_not_applicable_requires_rationale_and_cannot_declare_current_rust(self):
        for rationale in (None, "", " ", []):
            manifest = self.manifest()
            manifest["fixtures"][0]["provenance"]["rust_preservation_rationale"] = rationale
            self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))
        manifest = self.manifest()
        manifest["fixtures"][0]["required_variants"] = ["cpp_current", "rust_current", "rust_candidate"]
        self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))

    def test_kernel_receipts_have_explicit_empty_applicability_review(self):
        manifest = self.manifest()
        manifest["fixtures"][0]["scope"] = "kernel"
        manifest["fixtures"][0].pop("rust_preservation_applicability")
        receipt = self.receipt()
        receipt["review"]["rust_preservation_applicability"] = {}
        self.assertEqual(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"), [])
        receipt["review"]["rust_preservation_applicability"] = {"caller": "not_applicable"}
        self.assertTrue(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"))

    def test_lock_namespace_provenance_requires_canonical_worker_scope(self):
        self.assertEqual(publish.receipt_reasons(self.receipt(), self.manifest(), b"manifest", b"samples"), [])
        for scope in (None, "test_override", "custom", []):
            receipt = self.receipt()
            if scope is None:
                receipt["runner"].pop("lock_scope")
            else:
                receipt["runner"]["lock_scope"] = scope
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))

    def test_malformed_nested_receipt_shapes_hold_without_traceback(self):
        for key in ("review", "source_hashes", "binary_hashes", "compiler_hashes", "input_hashes", "commands", "runner"):
            for value in ([], None):
                bad = self.receipt()
                bad[key] = value
                self.assertTrue(publish.receipt_reasons(bad, self.manifest(), b"manifest", b"samples"))
        manifest = self.manifest()
        manifest["provenance"] = []
        self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))

    def test_hashes_are_strings_and_every_required_variant_has_reviewed_provenance(self):
        for value in (int("9" * 64), None, {}):
            receipt = self.receipt()
            receipt["binary_hashes"]["rust_candidate"] = value
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
            receipt = self.receipt()
            receipt["runner"]["implementation_sha256"] = value
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        manifest = self.manifest()
        manifest["fixtures"][0]["required_variants"] = ["cpp_current", "cpp_optimized", "rust_current", "rust_candidate"]
        receipt = self.receipt()
        self.assertTrue(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"))
        receipt["source_hashes"].update(cpp_optimized="5" * 40, rust_current=BASE)
        receipt["binary_hashes"].update(cpp_optimized="6" * 64, rust_current="7" * 64)
        self.assertTrue(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"))
        receipt["variant_source_attribution"] = {"cpp_optimized": {"source_sha": "5" * 40, "reason": "Reviewed optimized implementation commit"}}
        manifest["fixtures"][0]["rust_preservation_applicability"] = "required"
        receipt["source_content_hashes"].update(cpp_optimized="6" * 64, rust_current="7" * 64)
        receipt["review"]["source_content_hashes"] = dict(receipt["source_content_hashes"])
        receipt["review"]["rust_preservation_applicability"] = {"caller": "required"}
        rows = json.dumps({"case": "caller", "variant": "rust_current", "process": 0, "round": 0, "order": 0,
                           "elapsed_ns": 1000, "iterations": 1, "observable_digest": "a" * 64}).encode() + b"\n"
        receipt["samples_sha256"] = hashlib.sha256(rows).hexdigest()
        self.assertEqual(publish.receipt_reasons(receipt, manifest, b"manifest", rows), [])

    def test_command_provenance_rejects_raw_argv_unhashed_executables_and_manifest_mismatch(self):
        for records in ([["cmake", "private-token"]], [{"name": "cmake", "argv_sha256": "8" * 64}],
                        [{"name": "../cmake", "sha256": "6" * 64, "argv_sha256": "8" * 64}],
                        [{"name": "cmake", "sha256": "6" * 64, "argv_sha256": int("9" * 64)}]):
            receipt = self.receipt()
            receipt["commands"]["build"] = records
            self.assertTrue(publish.receipt_reasons(receipt, self.manifest(), b"manifest", b"samples"))
        manifest = self.manifest()
        manifest["provenance"] = {"commands": {"build": []}}
        self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))

    def test_controls_need_independent_receipt_attribution(self):
        manifest = self.manifest()
        manifest["fixtures"][0]["role"] = "unchanged_control"
        manifest["fixtures"][0]["provenance"]["label"] = "unchanged"
        self.assertTrue(publish.receipt_reasons(self.receipt(), manifest, b"manifest", b"samples"))
        receipt = self.receipt()
        receipt["control_attribution"] = {"caller": {"source_sha256": "a" * 64, "reason": "Identical caller fixture implementation reviewed"}}
        self.assertEqual(publish.receipt_reasons(receipt, manifest, b"manifest", b"samples"), [])

    def test_selected_metric_keeps_same_case_between_base_and_pr(self):
        bmf = {"caller/cpp_current": {"latency": {"value": 100, "lower_value": 95, "upper_value": 105}},
               "caller/rust_candidate": {"latency": {"value": 80, "lower_value": 75, "upper_value": 85}}}
        self.assertEqual(publish.selected_bmf(bmf, self.manifest(), "base"), {"caller": bmf["caller/cpp_current"]})
        self.assertEqual(publish.selected_bmf(bmf, self.manifest(), "pr"), {"caller": bmf["caller/rust_candidate"]})
        bmf["caller/rust_candidate"]["latency"]["value"] = float("nan")
        with self.assertRaises(publish.PublicationError):
            publish.selected_bmf(bmf, self.manifest(), "pr")

    def test_bencher_environment_cannot_execute_ambient_commands_or_leak_tokens(self):
        env = publish.bencher_environment({"PATH": "/bin", "BENCHER_CMD": "evil", "BENCHER_API_KEY": "wrong", "GITHUB_TOKEN": "private", "LD_PRELOAD": "evil"}, "bencher-secret")
        self.assertEqual(env, {"PATH": "/bin", "CI": "true", "BENCHER_API_KEY": "bencher-secret"})
        command = publish.bencher_command("project", "pr-7", BASE, HEAD, "i7-existing", Path("bencher.json"), "")
        self.assertIn("--file", command)
        self.assertEqual(command[command.index("--hash") + 1], HEAD)
        self.assertEqual(command[command.index("--start-point-hash") + 1], BASE)
        self.assertNotIn("--github-actions", command)
        self.assertNotIn("bencher-secret", command)

    def test_invalid_main_clears_stale_pass_and_writes_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            output.mkdir()
            (output / "qualification.json").write_text('{"status":"PASS"}')
            (output / "selected-bencher.json").write_text('{"stale":"data"}')
            with patch.dict("os.environ", {}, clear=True):
                status = publish.main(["--mode", "pr", "--output-dir", str(output), "--evidence-sha", EVIDENCE])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
            self.assertFalse((output / "selected-bencher.json").exists())

    def test_unsigned_evidence_main_clears_stale_pass_without_secret_diagnostic(self):
        bad = self.commit()
        bad["commit"]["verification"]["verified"] = False
        class API:
            def get(self, endpoint):
                return bad
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results"
            output.mkdir()
            (output / "qualification.json").write_text('{"status":"PASS"}')
            (output / "selected-bencher.json").write_text('{"stale":"data"}')
            diagnostic = io.StringIO()
            with patch.object(publish, "GitHub", return_value=API()), patch.dict("os.environ", {"BENCH_GITHUB_TOKEN": "private-token"}), contextlib.redirect_stderr(diagnostic):
                status = publish.main(["--mode", "pr", "--repository", "Appz4Fun/nzbget", "--evidence-sha", EVIDENCE,
                                       "--expected-base-sha", BASE, "--expected-head-sha", HEAD, "--controller-sha", BASE,
                                       "--pr", "7", "--testbed", "i7-existing", "--output-dir", str(output)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads((output / "qualification.json").read_text())["status"], "HOLD")
            self.assertFalse((output / "selected-bencher.json").exists())
            self.assertIn("signature", diagnostic.getvalue())
            self.assertNotIn("private-token", diagnostic.getvalue())

    def test_hold_pr_and_unreviewed_receipt_never_invoke_bencher_or_github_writes(self):
        args = argparse.Namespace(mode="pr", repository="Appz4Fun/nzbget", pr=7, expected_base_sha=BASE,
                                  controller_sha=BASE, testbed="i7-existing", output_dir=Path("results"), evidence_sha=EVIDENCE)
        class API:
            def get(self, endpoint):
                raise AssertionError("HOLD must not cross the publication boundary")
            def post(self, endpoint, payload):
                raise AssertionError("HOLD must not write")
        with patch.dict("os.environ", {"BENCHER_KEY": "private-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run") as run:
            for status, receipt_ok in (("HOLD", True), ("PASS", False)):
                with self.assertRaises(publish.PublicationError):
                    publish.publish_results(API(), args, self.manifest(), {"status": status}, receipt_ok)
            run.assert_not_called()

    def test_base_hold_is_monitoring_only_and_wrong_identity_blocks_bencher(self):
        args = argparse.Namespace(mode="base", repository="Appz4Fun/nzbget", pr=None, expected_base_sha=BASE,
                                  controller_sha=BASE, testbed="i7-existing", output_dir=Path("results"), evidence_sha=EVIDENCE)
        class API:
            def __init__(self, actor="xbmc4lyfe"):
                self.actor = actor
            def get(self, endpoint):
                if endpoint == "/user":
                    return {"login": self.actor}
                if "/branches/" in endpoint:
                    return {"commit": {"sha": BASE}, "protected": False}
                return {"default_branch": "dupe-article-fallback"}
            def post(self, endpoint, payload):
                raise AssertionError("baseline monitoring must not claim PR qualification")
        with patch.dict("os.environ", {"BENCHER_KEY": "private-key", "BENCHER_PROJECT": "existing-project"}), patch.object(publish.subprocess, "run") as run:
            with self.assertRaises(publish.PublicationError):
                publish.publish_results(API(actor="github-actions[bot]"), args, self.manifest(), {"status": "HOLD"}, True)
            run.assert_not_called()
            run.return_value = argparse.Namespace(returncode=0)
            publish.publish_results(API(), args, self.manifest(), {"status": "HOLD"}, True)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--hash") + 1], BASE)
            self.assertNotIn("--github-actions", command)

    def test_output_directory_cannot_overwrite_trusted_controller_inputs(self):
        for output in (SCRIPT.parent, SCRIPT.parent.parent, SCRIPT.parent.parent.parent):
            with self.assertRaises(publish.PublicationError):
                publish.clear_owned_outputs(output)

    def test_baseline_retains_original_history_alert_policy(self):
        command = publish.bencher_command("project", "dupe-article-fallback", BASE, BASE, "i7-existing", Path("data.json"), "")
        for flag, value in (("--threshold-measure", "latency"), ("--threshold-test", "percentage"),
                            ("--threshold-max-sample-size", "16"), ("--threshold-upper-boundary", "0.10")):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--thresholds-reset", command)

    def test_real_summary_pipeline_synthetic_pass_missing_receipt_and_stale_head(self):
        summary_source = Path(os.environ.get("BENCH_SUMMARY_SOURCE", SCRIPT.with_name("summarize.py")))
        if not summary_source.is_file():
            self.skipTest("statistics owner dependency not present; set BENCH_SUMMARY_SOURCE for temporary overlay")
        manifest = self.manifest()
        manifest["toolchain"] = {"fixture": "synthetic controlled clock test"}
        manifest_raw = json.dumps(manifest).encode()
        rows = []
        for process in range(8):
            for round_number in range(10):
                variants = ["cpp_current", "rust_candidate"] if round_number % 2 == 0 else ["rust_candidate", "cpp_current"]
                for order, variant in enumerate(variants):
                    rows.append({"case": "caller", "variant": variant, "process": process, "round": round_number,
                                 "order": order, "elapsed_ns": 1000 if variant == "cpp_current" else 800,
                                 "iterations": 1, "observable_digest": "a" * 64})
        samples_raw = b"\n".join(json.dumps(row).encode() for row in rows) + b"\n"
        receipt_raw = json.dumps(self.receipt(manifest_raw, samples_raw)).encode()
        with tempfile.TemporaryDirectory() as temp:
            overlay = Path(temp) / "trusted" / "scripts" / "bench"
            overlay.mkdir(parents=True)
            shutil.copyfile(SCRIPT, overlay / "publish.py")
            shutil.copyfile(summary_source, overlay / "summarize.py")
            overlay_spec = importlib.util.spec_from_file_location("publisher_overlay", overlay / "publish.py")
            controller = importlib.util.module_from_spec(overlay_spec)
            overlay_spec.loader.exec_module(controller)
            for missing_receipt, stale_head, expected in ((False, False, "PASS"), (True, False, "HOLD"), (False, True, "HOLD")):
                contents = {"benchmark-results/manifest.json": manifest_raw, "benchmark-results/samples.jsonl": samples_raw}
                if not missing_receipt:
                    contents["benchmark-results/collection-receipt.json"] = receipt_raw
                blobs = {}
                entries = []
                for path, raw in contents.items():
                    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                    entries.append({"path": path, "sha": sha, "mode": "100644", "type": "blob", "size": len(raw)})
                    blobs[sha] = {"sha": sha, "encoding": "base64", "content": __import__("base64").b64encode(raw).decode()}
                commit = self.commit()
                commit["files"] = [{"filename": path, "status": "added"} for path in contents]
                class API:
                    def get(self, endpoint):
                        if endpoint.endswith("/commits/" + EVIDENCE):
                            return commit
                        if "/git/trees/" in endpoint:
                            return {"truncated": False, "tree": entries}
                        if "/git/blobs/" in endpoint:
                            return blobs[endpoint.rsplit("/", 1)[1]]
                        if endpoint.endswith("/branches/dupe-article-fallback"):
                            return {"protected": False, "commit": {"sha": BASE}}
                        if endpoint.endswith("/pulls/7"):
                            return {"number": 7, "state": "open", "base": {"sha": BASE, "ref": "dupe-article-fallback", "repo": {"full_name": "Appz4Fun/nzbget"}},
                                    "head": {"sha": "9" * 40 if stale_head else HEAD, "repo": {"full_name": "Appz4Fun/nzbget"}}}
                        return {"default_branch": "dupe-article-fallback"}
                    def post(self, endpoint, payload):
                        raise AssertionError("validation must never write")
                output = Path(temp) / ("output-" + str(missing_receipt) + str(stale_head))
                diagnostic = io.StringIO()
                with patch.object(controller, "GitHub", return_value=API()), contextlib.redirect_stdout(diagnostic), contextlib.redirect_stderr(diagnostic):
                    status = controller.main(["--mode", "pr", "--repository", "Appz4Fun/nzbget", "--evidence-sha", EVIDENCE,
                                              "--expected-base-sha", BASE, "--expected-head-sha", HEAD, "--controller-sha", BASE,
                                              "--pr", "7", "--testbed", "i7-existing", "--output-dir", str(output)])
                self.assertEqual(status, 2 if stale_head else 0, diagnostic.getvalue())
                qualification = json.loads((output / "qualification.json").read_text())
                self.assertEqual(qualification["status"], expected, diagnostic.getvalue())
                if expected == "PASS":
                    self.assertEqual(json.loads((output / "selected-bencher.json").read_text())["caller"]["latency"]["value"], 800)
                    self.assertFalse(qualification["collection_provenance"]["signature_attests_execution"])


if __name__ == "__main__":
    unittest.main()
