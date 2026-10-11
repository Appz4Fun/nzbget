#!/usr/bin/env python3
"""Validate signed, reviewed collection data; publish without running its code.

Only trusted default-branch code invokes this controller. Evidence signatures
bind transport, not execution: the bounded collection receipt records the
operator's review of source/build/runner provenance. No evidence code executes.
"""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ACTOR = "xbmc4lyfe"
BRANCH = "dupe-article-fallback"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FILES = {"benchmark-results/manifest.json": 1024 * 1024,
         "benchmark-results/samples.jsonl": 32 * 1024 * 1024,
         "benchmark-results/collection-receipt.json": 1024 * 1024}
OUTPUT_FILES = ("manifest.json", "samples.jsonl", "collection-receipt.json", "summary.json", "bencher.json",
                "qualification.json", "report.md", "selected-bencher.json")


class PublicationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PublicationError(message)


def digest(value, pattern=SHA256):
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def json_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result
    def nonfinite(_):
        raise PublicationError("nonfinite JSON number")
    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PublicationError("invalid JSON data") from exc
    require(isinstance(value, dict), "expected JSON object")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Fixed-origin API requests; never forward a credential through redirects."""
    def __init__(self, token):
        require(bool(token), "BENCH_GITHUB_TOKEN is unavailable")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, endpoint, payload=None, limit=48 * 1024 * 1024):
        require(endpoint.startswith("/") and not endpoint.startswith("//"), "invalid API endpoint")
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request("https://api.github.com" + endpoint, data=data,
                    headers={"Authorization": "Bearer " + self.token,
                             "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                             "User-Agent": "nzbget-benchmark-publisher", "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(limit + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            # Response bodies, URLs, exception text and tokens are never printed.
            raise PublicationError("GitHub API request failed") from exc
        require(len(raw) <= limit, "GitHub API response exceeds limit")
        return json_object(raw)

    def get(self, endpoint):
        return self.request(endpoint)

    def post(self, endpoint, payload):
        return self.request(endpoint, payload)


def verified_github_actor(api):
    require(api.get("/user").get("login") == ACTOR, "GitHub credential must authenticate as xbmc4lyfe")
    return ACTOR


def archive_guard(api, repository, number):
    require(repository == "Appz4Fun/nzbget" and type(number) is int and number > 0, "invalid archive repository or PR number")
    actor = verified_github_actor(api)
    pr = api.get(f"/repos/{repository}/pulls/{number}")
    require(pr.get("number") == number and pr.get("base", {}).get("repo", {}).get("full_name") == repository and
            pr.get("head", {}).get("repo", {}).get("full_name") == repository and pr.get("base", {}).get("ref") == BRANCH,
            "archive pull request repository or branch mismatch")
    require(pr.get("state") in ("open", "closed"), "invalid archive pull request state")
    ready = pr["state"] == "closed"
    return {"status": "ready" if ready else "skip_reopened", "ready": ready, "actor": actor}


def validate_evidence_commit(commit, expected_sha):
    require(SHA.fullmatch(expected_sha) and commit.get("sha") == expected_sha, "evidence commit SHA mismatch")
    require(commit.get("author", {}).get("login") == ACTOR and commit.get("committer", {}).get("login") == ACTOR,
            "evidence author and committer must resolve to xbmc4lyfe")
    body = commit.get("commit", {})
    require(body.get("author", {}).get("name") == ACTOR and body.get("committer", {}).get("name") == ACTOR,
            "evidence author and committer names must be xbmc4lyfe")
    verification = body.get("verification", {})
    require(verification.get("verified") is True and verification.get("reason") == "valid", "evidence signature is not GitHub-verified")
    files = commit.get("files")
    require(isinstance(files, list) and 0 < len(files) <= len(FILES), "evidence commit must change only bounded collection data")
    for file in files:
        require(file.get("filename") in FILES and file.get("status") in ("added", "modified"),
                "evidence commit changes non-allowlisted data or executable code")
        require("previous_filename" not in file, "renamed evidence files are not accepted")
    require(SHA.fullmatch(body.get("tree", {}).get("sha", "")), "missing evidence tree SHA")


def data_tree(tree):
    require(tree.get("truncated") is False and isinstance(tree.get("tree"), list), "incomplete evidence tree")
    result = {}
    for entry in tree["tree"]:
        path = entry.get("path")
        if path in FILES:
            require(path not in result, "duplicate evidence path")
            require(entry.get("mode") == "100644" and entry.get("type") == "blob" and SHA.fullmatch(entry.get("sha", "")),
                    "evidence path must be a nonexecutable regular blob")
            require(type(entry.get("size", 0)) is int and 0 <= entry.get("size", 0) <= FILES[path], "evidence blob exceeds limit")
            result[path] = entry["sha"]
    return result


def verify_blob(raw, expected_sha, limit):
    require(len(raw) <= limit, "evidence file exceeds limit")
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(actual == expected_sha, "evidence blob content hash mismatch")


def acquire_evidence(api, repository, evidence_sha):
    commit = api.get(f"/repos/{repository}/commits/{evidence_sha}")
    validate_evidence_commit(commit, evidence_sha)
    tree_sha = commit["commit"]["tree"]["sha"]
    entries = data_tree(api.get(f"/repos/{repository}/git/trees/{tree_sha}?recursive=1"))
    require(all(path in entries for path in tuple(FILES)[:2]), "evidence is missing manifest or samples")
    contents = {}
    for path, blob_sha in entries.items():
        blob = api.get(f"/repos/{repository}/git/blobs/{blob_sha}")
        require(blob.get("encoding") == "base64" and blob.get("sha") == blob_sha, "unsupported evidence blob")
        try:
            raw = base64.b64decode("".join(blob["content"].split()), validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationError("invalid evidence blob encoding") from exc
        verify_blob(raw, blob_sha, FILES[path])
        contents[Path(path).name] = raw
    return contents


def validate_pr(pr, repository, number, base_sha, head_sha):
    require(pr.get("number") == number and pr.get("state") == "open", "pull request is no longer open")
    base = pr.get("base", {})
    require(base.get("repo", {}).get("full_name") == repository and base.get("ref") == BRANCH, "pull request targets a different repository or branch")
    require(base.get("sha") == base_sha and pr.get("head", {}).get("sha") == head_sha, "pull request base/head SHA is stale")


def validate_current(api, repository, mode, base_sha, head_sha, number, controller_sha):
    repo = api.get(f"/repos/{repository}")
    require(repo.get("default_branch") == BRANCH, "trusted controller must use the canonical default branch")
    branch = api.get(f"/repos/{repository}/branches/{BRANCH}")
    current_sha = branch.get("commit", {}).get("sha")
    require(current_sha == controller_sha, "trusted controller default-branch SHA is stale")
    require(current_sha == base_sha, "canonical baseline SHA is stale")
    if mode == "pr":
        validate_pr(api.get(f"/repos/{repository}/pulls/{number}"), repository, number, base_sha, head_sha)
    return bool(branch.get("protected"))


def receipt_reasons(receipt, manifest, manifest_raw, samples_raw):
    if receipt is None:
        return ["missing operator-reviewed collection receipt"]
    reasons = []
    def check(condition, message):
        if not condition:
            reasons.append(message)
    if not isinstance(receipt, dict) or not isinstance(manifest, dict):
        return ["invalid collection receipt or manifest shape"]
    check(type(receipt.get("schema_version")) is int and receipt.get("schema_version") == 1 and receipt.get("review") == {"actor": ACTOR, "status": "reviewed"}, "collection receipt is not operator-reviewed v1")
    check(receipt.get("manifest_sha256") == hashlib.sha256(manifest_raw).hexdigest() and receipt.get("samples_sha256") == hashlib.sha256(samples_raw).hexdigest(), "collection receipt input hashes differ")
    for key in ("base_sha", "candidate_sha", "testbed"):
        check(receipt.get(key) == manifest.get(key), "collection receipt " + key + " differs")
    comparison = manifest.get("comparison", {})
    if not isinstance(comparison, dict):
        return ["invalid collection comparison shape"]
    sources, binaries = receipt.get("source_hashes", {}), receipt.get("binary_hashes", {})
    check(isinstance(sources, dict) and isinstance(binaries, dict), "missing source/binary hashes")
    if isinstance(sources, dict) and isinstance(binaries, dict):
        for kind, sha_key in (("baseline", "base_sha"), ("candidate", "candidate_sha")):
            variant = comparison.get(kind)
            check(sources.get(variant) == manifest.get(sha_key), "collection receipt source SHA differs")
            check(digest(binaries.get(variant)), "missing compared binary hash")
    compilers = receipt.get("compiler_hashes")
    check(isinstance(compilers, dict) and bool(compilers) and all(isinstance(v, str) and SHA256.fullmatch(v) for v in compilers.values()), "missing compiler hashes")
    input_hashes = receipt.get("input_hashes", {})
    check(isinstance(input_hashes, dict), "missing fixture input hashes")
    fixtures = manifest.get("fixtures", [])
    if not isinstance(fixtures, list) or any(not isinstance(f, dict) or "id" not in f or "sha256" not in f for f in fixtures):
        return ["invalid collection fixture shape"]
    controls = receipt.get("control_attribution", {})
    for fixture in fixtures:
        check(isinstance(input_hashes, dict) and input_hashes.get(fixture["id"]) == fixture["sha256"], "collection receipt fixture hash differs")
        required = fixture.get("required_variants", [comparison.get("baseline"), comparison.get("candidate")])
        check(isinstance(required, list) and all(isinstance(v, str) for v in required), "invalid required variant provenance")
        if isinstance(required, list) and isinstance(sources, dict) and isinstance(binaries, dict):
            for variant in required:
                if not isinstance(variant, str):
                    continue
                check(digest(sources.get(variant), SHA) and digest(binaries.get(variant)), "missing required variant source or binary hash")
                if variant in ("cpp_current", "rust_current"):
                    check(sources.get(variant) == manifest.get("base_sha"), "current variant source differs from canonical baseline")
                elif variant == "rust_candidate":
                    check(sources.get(variant) == manifest.get("candidate_sha"), "candidate variant source differs from candidate SHA")
                elif variant == "cpp_optimized":
                    variants = receipt.get("variant_source_attribution", {})
                    attribution = variants.get(variant, {}) if isinstance(variants, dict) else {}
                    check(isinstance(attribution, dict) and attribution.get("source_sha") == sources.get(variant) and
                          isinstance(attribution.get("reason"), str) and 0 < len(attribution["reason"]) <= 1000,
                          "optimized C++ source lacks reviewed code attribution")
        if fixture.get("role") == "unchanged_control":
            attribution = controls.get(fixture["id"], {}) if isinstance(controls, dict) else {}
            check(isinstance(attribution, dict) and digest(attribution.get("source_sha256")) and isinstance(attribution.get("reason"), str) and 0 < len(attribution["reason"]) <= 1000, "unchanged control lacks reviewed source attribution")
    commands = receipt.get("commands", {})
    for phase in ("build", "time"):
        records = commands.get(phase) if isinstance(commands, dict) else None
        check(isinstance(records, list) and 0 < len(records) <= 64 and all(isinstance(record, dict) and
              isinstance(record.get("name"), str) and bool(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", record["name"])) and
              digest(record.get("sha256")) and digest(record.get("argv_sha256")) and
              set(record) == {"name", "sha256", "argv_sha256"} for record in records),
              "missing bounded reviewed " + phase + " command hash provenance")
    runner = receipt.get("runner", {})
    check(isinstance(runner, dict), "missing runner provenance")
    if isinstance(runner, dict):
        check(digest(runner.get("implementation_sha256")), "missing runner implementation hash")
        check(type(runner.get("build_jobs")) is int and 1 <= runner["build_jobs"] <= 3, "runner build jobs exceed contract")
        check(runner.get("build_locks") == ["i7-heavy.lock:exclusive", "nzbget-rust-benchmark.lock:shared"] and runner.get("time_locks") == ["nzbget-rust-benchmark.lock:exclusive"] and runner.get("time_prebuilt") is True, "runner lock or prebuilt timing provenance differs")
    # If the manifest independently records a receipt-controlled digest, bind it.
    provenance = manifest.get("provenance", {})
    check(isinstance(provenance, dict), "invalid manifest provenance shape")
    for key in ("source_hashes", "compiler_hashes", "binary_hashes", "input_hashes", "runner", "commands", "control_attribution", "variant_source_attribution"):
        recorded = provenance.get(key) if isinstance(provenance, dict) else None
        if recorded is not None:
            check(recorded == receipt.get(key), "manifest and receipt " + key + " differ")
    return sorted(set(reasons))


def selected_bmf(bmf, manifest, mode):
    selected = manifest["comparison"]["baseline" if mode == "base" else "candidate"]
    result = {}
    for fixture in manifest["fixtures"]:
        case = fixture["id"]
        metric = bmf.get(case + "/" + selected)
        if metric is None:
            continue
        latency = metric.get("latency", {})
        value = latency.get("value")
        require(type(value) in (int, float) and math.isfinite(value) and value > 0, "invalid selected Bencher latency")
        for name in ("lower_value", "upper_value"):
            bound = latency.get(name)
            require(type(bound) in (int, float) and math.isfinite(bound) and bound > 0, "invalid selected Bencher interval")
        require(latency["lower_value"] <= value <= latency["upper_value"], "invalid selected Bencher interval order")
        result[case] = {"latency": dict(latency)}
    require(bool(result), "selected variant has no measured metrics")
    return result


def bencher_environment(environment, key):
    # BENCHER_CMD would execute a payload even with --file. Other ambient
    # credentials, GITHUB_ACTIONS integration, preload and shell variables drop.
    result = {name: environment[name] for name in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE") if name in environment}
    result.update(CI="true", BENCHER_API_KEY=key)
    return result


def bencher_command(project, branch, base_sha, head_sha, testbed, bmf, host):
    command = ["bencher", "run", "--project", project, "--branch", branch, "--hash", head_sha,
               "--testbed", testbed, "--adapter", "json", "--file", str(bmf), "--error-on-alert", "--attempts", "2", "--timeout", "15"]
    if branch != BRANCH:
        command += ["--start-point", BRANCH, "--start-point-hash", base_sha,
                    "--start-point-clone-thresholds", "--start-point-reset"]
    else:
        command += ["--threshold-measure", "latency", "--threshold-test", "percentage",
                    "--threshold-max-sample-size", "16", "--threshold-upper-boundary", "0.10", "--thresholds-reset"]
    if host:
        command += ["--host", host]
    return command


def write_outputs(path, values):
    if path:
        with Path(path).open("a", encoding="utf-8") as output:
            for key, value in values.items():
                require(re.fullmatch(r"[a-z_]+", key) and "\n" not in str(value) and "\r" not in str(value), "invalid workflow output")
                output.write(f"{key}={value}\n")


def clear_owned_outputs(output_dir):
    if output_dir is None:
        return
    root = Path(__file__).resolve().parents[2]
    resolved = output_dir.resolve()
    require(resolved != root and resolved not in Path(__file__).resolve().parents and
            not output_dir.is_symlink(), "output directory collides with trusted controller inputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        path = output_dir / name
        if path.exists() or path.is_symlink():
            require(not path.is_dir(), "owned output path is a directory")
            path.unlink()


def controlled_summary(contents, manifest, output_dir):
    summary_script = Path(__file__).with_name("summarize.py")
    require(summary_script.is_file(), "trusted summarize.py dependency is unavailable")
    with tempfile.TemporaryDirectory(prefix="paired-proof-") as temp:
        inputs = Path(temp)
        for name in ("manifest.json", "samples.jsonl"):
            (inputs / name).write_bytes(contents[name])
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
        result = subprocess.run([sys.executable, "-I", str(summary_script), "--manifest", str(inputs / "manifest.json"),
                                 "--samples", str(inputs / "samples.jsonl"), "--output-dir", str(output_dir)],
                                env=env, capture_output=True, timeout=120, check=False)
        require(result.returncode == 0, "paired collection proof failed trusted summary validation")
    summary = json_object((output_dir / "summary.json").read_bytes())
    qualification = json_object((output_dir / "qualification.json").read_bytes())
    bmf = json_object((output_dir / "bencher.json").read_bytes())
    for document in (summary, qualification):
        require(document.get("schema_version") == 1, "summary schema mismatch")
        for key in ("base_sha", "candidate_sha", "testbed"):
            require(document.get(key) == manifest[key], "summary identity differs from evidence")
    expected_hashes = {"manifest_sha256": hashlib.sha256(contents["manifest.json"]).hexdigest(),
                       "samples_sha256": hashlib.sha256(contents["samples.jsonl"]).hexdigest()}
    require(summary.get("input_hashes") == expected_hashes, "summary raw input hashes differ")
    require(qualification.get("status") in ("PASS", "HOLD"), "invalid qualification status")
    return summary, bmf, qualification


def publish_results(api, args, manifest, qualification, receipt_ok):
    key = os.environ.get("BENCHER_KEY", "")
    project = os.environ.get("BENCHER_PROJECT", "")
    require(key and project, "Bencher publication configuration is unavailable")
    require(receipt_ok, "HOLD: collection provenance is not reviewed and consistent")
    require(args.mode == "base" or qualification["status"] == "PASS", "HOLD: complete-caller qualification prevents PR publication")
    validate_current(api, args.repository, args.mode, args.expected_base_sha, manifest["candidate_sha"], args.pr, args.controller_sha)
    verified_github_actor(api)
    command = bencher_command(project, BRANCH if args.mode == "base" else f"pr-{args.pr}", manifest["base_sha"],
                             manifest["base_sha"] if args.mode == "base" else manifest["candidate_sha"], args.testbed,
                             args.output_dir / "selected-bencher.json", os.environ.get("BENCHER_HOST_URL", ""))
    # No measured command; the only subprocess with Bencher credentials reads
    # freshly validated BMF data. Capture output to avoid upstream secret leaks.
    result = subprocess.run(command, env=bencher_environment(os.environ, key), capture_output=True, timeout=180, check=False)
    require(result.returncode == 0, "Bencher data-only publication failed or reported an alert")
    if args.mode == "pr":
        validate_current(api, args.repository, "pr", manifest["base_sha"], manifest["candidate_sha"], args.pr, args.controller_sha)
        verified_github_actor(api)
        api.post(f"/repos/{args.repository}/statuses/{manifest['candidate_sha']}", {
            "state": "success", "context": "paired caller qualification", "description": "Reviewed paired complete-caller evidence: PASS"})
        validate_current(api, args.repository, "pr", manifest["base_sha"], manifest["candidate_sha"], args.pr, args.controller_sha)
        verified_github_actor(api)
        # The report contains fixed controller prose and hashes, never receipt
        # argv arrays, raw input/provider contents, absolute paths or secrets.
        api.post(f"/repos/{args.repository}/issues/{args.pr}/comments", {"body":
                 f"Paired caller qualification: **PASS**. Base `{manifest['base_sha']}`, candidate `{manifest['candidate_sha']}`. "
                 f"Signed reviewed collection evidence: `{args.evidence_sha}`. "
                 "The collection receipt records operator review; its signature binds the evidence and does not attest timing execution."})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-identity-only", action="store_true")
    parser.add_argument("--verify-archive-only", action="store_true")
    parser.add_argument("--github-output")
    parser.add_argument("--mode", choices=("base", "pr"))
    parser.add_argument("--repository", default="Appz4Fun/nzbget")
    parser.add_argument("--evidence-sha")
    parser.add_argument("--expected-base-sha")
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--controller-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--testbed")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    outputs_cleared = False
    try:
        if not args.verify_identity_only and not args.verify_archive_only:
            clear_owned_outputs(args.output_dir)
            outputs_cleared = args.output_dir is not None
        api = GitHub(os.environ.get("BENCH_GITHUB_TOKEN", ""))
        if args.verify_archive_only:
            guard = archive_guard(api, args.repository, args.pr_number)
            write_outputs(args.github_output, {"ready": str(guard["ready"]).lower(), "actor": guard["actor"]})
            print(json.dumps(guard))
            return 0
        if args.verify_identity_only:
            write_outputs(args.github_output, {"actor": verified_github_actor(api), "ready": "true"})
            print("GitHub identity verified: xbmc4lyfe")
            return 0
        require(args.repository == "Appz4Fun/nzbget", "evidence must belong to Appz4Fun/nzbget")
        require(args.mode and args.output_dir and args.testbed, "mode, output directory and stable testbed are required")
        for value in (args.evidence_sha, args.expected_base_sha, args.controller_sha):
            require(isinstance(value, str) and SHA.fullmatch(value), "full immutable evidence/base/controller SHAs are required")
        if args.mode == "pr":
            require(type(args.pr) is int and args.pr > 0 and isinstance(args.expected_head_sha, str) and SHA.fullmatch(args.expected_head_sha), "PR number and full head SHA are required")
        require(0 < len(args.testbed) <= 200 and not any(ord(c) < 32 for c in args.testbed) and args.testbed not in ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"), "stable existing testbed is required")
        contents = acquire_evidence(api, args.repository, args.evidence_sha)
        manifest = json_object(contents["manifest.json"])
        require(manifest.get("base_sha") == args.expected_base_sha and manifest.get("testbed") == args.testbed, "evidence baseline or testbed mismatch")
        require(isinstance(manifest.get("candidate_sha"), str) and SHA.fullmatch(manifest["candidate_sha"]), "missing full candidate SHA")
        if args.expected_head_sha:
            require(manifest["candidate_sha"] == args.expected_head_sha, "evidence candidate SHA mismatch")
        protected = validate_current(api, args.repository, args.mode, args.expected_base_sha, manifest["candidate_sha"], args.pr, args.controller_sha)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, raw in contents.items():
            (args.output_dir / name).write_bytes(raw)
        _, bmf, qualification = controlled_summary(contents, manifest, args.output_dir)
        receipt = json_object(contents["collection-receipt.json"]) if "collection-receipt.json" in contents else None
        reasons = receipt_reasons(receipt, manifest, contents["manifest.json"], contents["samples.jsonl"])
        qualification["collection_provenance"] = {"kind": "operator-reviewed signed collection evidence", "evidence_sha": args.evidence_sha,
                                                  "receipt_valid": not reasons, "reasons": reasons, "canonical_branch_protected": protected,
                                                  "signature_attests_execution": False}
        if reasons:
            qualification["status"] = "HOLD"
            qualification["reasons"] = qualification.get("reasons", []) + reasons
        (args.output_dir / "qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
        report = args.output_dir / "report.md"
        report.write_text(f"Publisher qualification: **{qualification['status']}**. Signed transport records operator-reviewed collection evidence; signature does not attest timing execution.\n\n" + report.read_text())
        selected = selected_bmf(bmf, manifest, args.mode)
        (args.output_dir / "selected-bencher.json").write_text(json.dumps(selected, indent=2) + "\n")
        ready = not reasons and (args.mode == "base" or qualification["status"] == "PASS")
        write_outputs(args.github_output, {"status": qualification["status"], "ready": str(ready).lower(),
                      "base_sha": manifest["base_sha"], "candidate_sha": manifest["candidate_sha"]})
        print(f"Collection validation: {qualification['status']}; publication ready: {str(ready).lower()}; canonical branch protected: {str(protected).lower()}")
        if args.publish:
            publish_results(api, args, manifest, qualification, not reasons)
            print("Validated data published" + (" for baseline monitoring" if args.mode == "base" else " with paired caller qualification"))
        return 0
    except (PublicationError, OSError, subprocess.TimeoutExpired, TypeError, KeyError, AttributeError, RecursionError) as exc:
        # Type/shape/filesystem failures use a fixed diagnostic; known errors
        # are controlled strings, never API response or upstream process text.
        message = str(exc) if isinstance(exc, PublicationError) else "publisher validation failed"
        print("HOLD: " + message, file=sys.stderr)
        if outputs_cleared:
            # Never leave yesterday's PASS behind after invalid/stale proof.
            for name in OUTPUT_FILES:
                path = args.output_dir / name
                if path.exists() or path.is_symlink():
                    path.unlink()
            (args.output_dir / "qualification.json").write_text(json.dumps({"schema_version": 1, "status": "HOLD", "reasons": [message]}) + "\n")
            (args.output_dir / "report.md").write_text("Publisher qualification: **HOLD**. " + message + "\n")
        write_outputs(args.github_output, {"status": "HOLD", "ready": "false"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
