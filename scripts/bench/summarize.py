#!/usr/bin/env python3
"""Validate v1 matched measurements and compute conservative numerical eligibility.

CLI: --manifest MANIFEST --samples SAMPLES --output-dir OUTPUT
Opt-in: --qualification-profile rust-replacement-campaign-v1 writes separate
campaign artifacts; the default selected-baseline v1 contract is retained.
Exit 0 includes HOLD; exit 2 rejects invalid proof and clears old owned artifacts.
This tool cannot independently verify git/build identity, output correctness,
hardware stability, process independence, or unchanged-control attribution.
Those assertions require trusted evidence before a runtime replacement is approved.
"""
import argparse
from collections import defaultdict, deque
import hashlib
import html
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import stat
import sys
import tempfile

VARIANTS = {"cpp_current", "cpp_optimized", "rust_current", "rust_candidate"}
OUTPUTS = ("summary.json", "bencher.json", "qualification.json", "report.md")
CAMPAIGN_OUTPUTS = ("campaign-qualification.json", "campaign-report.md")
CAMPAIGN_SELECTOR = "rust-replacement-campaign-v1"
CAMPAIGN_ID = "rust-replacement-campaign"
DEFAULT_POLICY = {"min_processes": 8, "min_rounds": 10, "min_each_order": 2,
                  "max_relative_ci_width": 0.10}
REPLICATES = 5000
SEED = 20261011
MAX_FIXTURES = 64
MAX_ROWS = 100000
MAX_PROCESSES = 128
MAX_BOOTSTRAP_SELECTIONS = 4000000


class ValidationError(ValueError):
    """Invalid, contradictory, or unbounded benchmark evidence."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def integer(value, label, minimum=0, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum,
            f"{label} must be an integer in [{minimum}, {maximum}]")


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def text(value, label, maximum=200):
    require(isinstance(value, str) and 0 < len(value) <= maximum and value.strip()
            and all(c.isprintable() for c in value), f"{label} must be bounded printable nonempty text")


def digest(value, label, width=64):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{" + str(width) + "}", value),
            f"{label} must be a full {width}-hex digest")


def fields(obj, needed, label):
    require(isinstance(obj, dict), f"{label} must be an object")
    missing = sorted(set(needed) - obj.keys())
    require(not missing, f"{label} missing fields: {', '.join(missing)}; legacy evidence cannot be inferred")


def policy_for(manifest):
    configured = manifest.get("qualification_policy", {})
    require(isinstance(configured, dict), "qualification_policy must be an object")
    require(not configured.keys() - DEFAULT_POLICY.keys(), "unknown qualification_policy fields")
    policy = {**DEFAULT_POLICY, **configured}
    integer(policy["min_processes"], "min_processes", 2, MAX_PROCESSES)
    integer(policy["min_rounds"], "min_rounds", 2, MAX_ROWS // 2)
    integer(policy["min_each_order"], "min_each_order", 1, MAX_ROWS // 2)
    width = policy["max_relative_ci_width"]
    require(finite_number(width) and 0 < width <= 1,
            "max_relative_ci_width must be finite in (0, 1]")
    require(2 * policy["min_each_order"] <= policy["min_rounds"],
            "min_rounds must allow both required order counts")
    return policy


def validate_manifest(manifest, *, campaign=False):
    fields(manifest, ("schema_version", "base_sha", "candidate_sha", "testbed", "toolchain",
                      "fixtures", "comparison"), "manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "schema_version must be 1")
    require(campaign or "qualification_profile" not in manifest,
            "qualification_profile requires explicit campaign selector; no generic fallback")
    digest(manifest["base_sha"], "base_sha", 40)
    digest(manifest["candidate_sha"], "candidate_sha", 40)
    text(manifest["testbed"], "testbed")
    toolchain = manifest["toolchain"]
    require(isinstance(toolchain, dict) and 0 < len(toolchain) <= 64,
            "toolchain must be a nonempty bounded string-valued object")
    for key, value in toolchain.items():
        text(key, "toolchain key")
        text(value, "toolchain value", 4096)
    fields(manifest["comparison"], ("baseline", "candidate"), "comparison")
    baseline, candidate = (manifest["comparison"][k] for k in ("baseline", "candidate"))
    require(isinstance(baseline, str) and isinstance(candidate, str)
            and baseline in VARIANTS and candidate in VARIANTS and baseline != candidate,
            "comparison needs distinct supported baseline and candidate variants")
    fixtures = manifest["fixtures"]
    require(isinstance(fixtures, list) and 0 < len(fixtures) <= MAX_FIXTURES,
            f"fixtures must contain 1..{MAX_FIXTURES} entries")
    ids = set()
    for fixture in fixtures:
        fields(fixture, ("id", "sha256", "scope"), "fixture")
        text(fixture["id"], "fixture id")
        require(fixture["id"] not in ids, "duplicate fixture id")
        ids.add(fixture["id"])
        digest(fixture["sha256"], "fixture sha256")
        require(fixture["scope"] in ("complete_caller", "kernel"), "unsupported fixture scope")
        role = fixture.get("role", "changed")
        require(role in ("changed", "unchanged_control"), "unsupported fixture role")
        if "provenance" in fixture:
            require(isinstance(fixture["provenance"], dict), "fixture provenance must be an object")
        if role == "unchanged_control":
            require(isinstance(fixture.get("provenance"), dict) and fixture["provenance"],
                    "unchanged_control needs externally verifiable attribution in fixture provenance")
        variants = fixture.get("required_variants", [baseline, candidate])
        require(isinstance(variants, list) and 2 <= len(variants) <= len(VARIANTS)
                and all(isinstance(v, str) and v in VARIANTS for v in variants)
                and len(set(variants)) == len(variants) and {baseline, candidate} <= set(variants),
                "required_variants must be unique supported variants including the comparison pair")
        applicability = fixture.get("rust_preservation_applicability")
        if "rust_preservation_applicability" in fixture:
            require(applicability in ("required", "not_applicable"), "unsupported rust_preservation_applicability")
        if fixture["scope"] == "complete_caller" and applicability == "not_applicable":
            require("rust_current" not in variants,
                    "not_applicable contradicts a declared current Rust baseline")
            rationale = fixture.get("provenance", {}).get("rust_preservation_rationale")
            text(rationale, "not_applicable rust_preservation_rationale", 4096)
    if "provenance" in manifest:
        require(isinstance(manifest["provenance"], dict), "provenance must be an object")
    policy_for(manifest)


def validate_rows(manifest, rows, *, campaign=False):
    require(isinstance(rows, list) and len(rows) <= MAX_ROWS, f"samples limited to {MAX_ROWS} rows")
    fixture_map = {f["id"]: f for f in manifest["fixtures"]}
    pair = [manifest["comparison"][k] for k in ("baseline", "candidate")]
    blocks = defaultdict(dict)
    seen = set()
    for index, row in enumerate(rows):
        label = f"sample row {index + 1}"
        fields(row, ("case", "variant", "process", "round", "order", "elapsed_ns", "iterations",
                     "observable_digest"), label)
        require(isinstance(row["case"], str) and row["case"] in fixture_map, f"{label} unknown fixture")
        required = fixture_map[row["case"]].get("required_variants", pair)
        require(isinstance(row["variant"], str) and row["variant"] in required,
                f"{label} variant is not required by its fixture")
        for key in ("process", "round", "order"):
            integer(row[key], f"{label} {key}")
        require(row["order"] < len(required), f"{label} order outside required block")
        integer(row["iterations"], f"{label} iterations", 1)
        elapsed = row["elapsed_ns"]
        require(finite_number(elapsed) and elapsed > 0,
                f"{label} elapsed_ns must be positive and finite")
        latency = elapsed / row["iterations"]
        require(latency > 0 and math.isfinite(latency), f"{label} derived latency must be positive and finite")
        digest(row["observable_digest"], f"{label} observable_digest")
        identity = (row["case"], row["variant"], row["process"], row["round"])
        require(identity not in seen, f"{label} duplicate sample row")
        seen.add(identity)
        blocks[(row["case"], row["process"], row["round"])][row["variant"]] = row
    grouped = defaultdict(dict)
    observed = defaultdict(set)
    for (case, process, round_id), block in blocks.items():
        grouped[case].setdefault(process, {})[round_id] = block
        observed[case].update(block)
        require(len({r["order"] for r in block.values()}) == len(block), "duplicate block order")
        require(len({r["observable_digest"].lower() for r in block.values()}) == 1,
                "observable_digest mismatch in equivalent variant block")
    for fixture in manifest["fixtures"]:
        case = fixture["id"]
        require(len(grouped[case]) <= MAX_PROCESSES, f"case {case} exceeds process limit")
        required = set(fixture.get("required_variants", pair))
        # A variant absent from the entire fixture is incomplete evidence (HOLD).
        # A variant present in any block must be present in every block; never
        # selectively discard unmatched rounds to make a favorable result.
        for rounds in grouped[case].values():
            for block in rounds.values():
                require(set(block) == observed[case], "unmatched variant block")
                if observed[case] == required:
                    require({r["order"] for r in block.values()} == set(range(len(required))),
                            "block order must cover every required position")
    planned_selections = 0
    for fixture in manifest["fixtures"]:
        case = fixture["id"]
        required = set(fixture.get("required_variants", pair))
        complete = observed[case] == required
        rust_pair = complete and "rust_current" in required and pair[1] != "rust_current"
        calls = len(observed[case]) + int(complete) + int(rust_pair)
        planned_selections += REPLICATES * len(grouped[case]) * calls
    require(campaign or planned_selections <= MAX_BOOTSTRAP_SELECTIONS,
            "bootstrap work budget exceeded; split independent fixture sets")
    return grouped, observed


def percentile(sorted_values, fraction):
    at = (len(sorted_values) - 1) * fraction
    lo, hi = math.floor(at), math.ceil(at)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (at - lo)


def median(values):
    """Positive finite median without overflowing the sum of two central values."""
    return percentile(sorted(values), 0.5)


def cluster_interval(values, statistic, rng):
    """Resample whole process summaries, retaining every original paired round."""
    count = len(values)
    draws = sorted(statistic([values[rng.randrange(count)] for _ in range(count)])
                   for _ in range(REPLICATES))
    return percentile(draws, 0.025), percentile(draws, 0.975)


def paired_measurement(processes, baseline, candidate, policy, rng, *, exact_batches=False):
    process_logs = []
    balanced = True
    for _, rounds in sorted(processes.items()):
        logs, orders = [], [0, 0]
        for _, block in sorted(rounds.items()):
            a, b = block[baseline], block[candidate]
            # Subtract logs rather than dividing first: finite positive
            # latencies may still overflow a direct ratio division.
            if exact_batches:
                # Campaign inputs are bounded integers. Products stay exact
                # before a single finite division; exact 1/2 and 1 boundaries
                # do not acquire error from subtracting two large logarithms.
                logs.append(math.log((b["elapsed_ns"] * a["iterations"]) /
                                     (a["elapsed_ns"] * b["iterations"])))
            else:
                logs.append(math.log(b["elapsed_ns"] / b["iterations"]) - math.log(a["elapsed_ns"] / a["iterations"]))
            orders[int(a["order"] > b["order"])] += 1
        process_logs.append(statistics.fmean(logs))
        balanced &= min(orders) >= policy["min_each_order"]
    try:
        estimate = math.exp(statistics.fmean(process_logs))
        low, high = cluster_interval(process_logs, lambda xs: math.exp(statistics.fmean(xs)), rng)
    except OverflowError as error:
        raise ValidationError("ratio exceeds finite output range") from error
    require(estimate > 0 and low > 0 and high > 0, "ratio underflows finite output range")
    return {"estimate": estimate, "lower": low, "upper": high}, balanced


def summarize(manifest, rows):
    """Return (summary, Bencher Metric Format, qualification), without mutation.

    Processes receive equal weight; the ratio is exp(mean(process mean log paired
    ratios)). The 95% percentile interval resamples processes, not individual
    rounds or rows. Latency history uses median(process median ns/op) with its
    own whole-process bootstrap interval. Neither interval is fastest/p90.
    """
    validate_manifest(manifest)
    grouped, observed = validate_rows(manifest, rows)
    try:
        encoded = json.dumps((manifest, rows), allow_nan=False)
        require(len(encoded) <= 40 * 1024 * 1024, "parsed evidence exceeds byte budget")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValidationError("evidence extensions must be bounded finite JSON") from error
    policy = policy_for(manifest)
    identity = {k: manifest[k] for k in ("schema_version", "base_sha", "candidate_sha", "testbed")}
    methodology = {"ratio_estimator": "exp(mean(process mean(log(paired candidate/baseline ns/op))))",
                   "latency_estimator": "median(process median ns/op)",
                   "resampling_unit": "whole process cluster; all paired rounds retained",
                   "interval": "95% percentile bootstrap; linear quantiles at 0.025 and 0.975",
                   "bootstrap_replicates": REPLICATES, "seed": SEED, "policy": policy,
                   "coverage": "per-case intervals; no simultaneous family coverage guarantee",
                   "outliers": "all retained; no trimming or independent round resampling",
                   "interpretation": "prospective conservative precision/sufficiency defaults; not statistical guarantees or a historical waiver",
                   "limits": "numerical eligibility only; independently verify git/build hashes, output correctness, testbed, process independence, control attribution, and explicit Rust-preservation applicability",
                   "migration_rule": "runtime qualification requires selected baseline cpp_current or cpp_optimized; all changed complete callers need upper selected-baseline ratio CI < 1; required current Rust needs upper preservation ratio CI <= 1; unchanged controls must include 1 against both baselines; kernels cannot qualify runtime"}
    summary = {**identity, "comparison": manifest["comparison"], "toolchain": manifest["toolchain"],
               "provenance": manifest.get("provenance", {}), "methodology": methodology, "cases": []}
    bmf = {}
    baseline, candidate = (manifest["comparison"][k] for k in ("baseline", "candidate"))
    for fixture in manifest["fixtures"]:
        case_id = fixture["id"]
        processes = grouped[case_id]
        required = fixture.get("required_variants", [baseline, candidate])
        applicability = fixture.get("rust_preservation_applicability")
        role = fixture.get("role", "changed")
        rng = random.Random(SEED)
        case = {"case": case_id, "scope": fixture["scope"], "role": role,
                "fixture_sha256": fixture["sha256"], "provenance": fixture.get("provenance", {}),
                "required_variants": required, "raw_count": sum(len(b) for p in processes.values() for b in p.values()),
                "rust_preservation_applicability": applicability,
                "process_count": len(processes), "round_counts": {str(p): len(r) for p, r in sorted(processes.items())},
                "variants": {}, "ratio": None, "rust_preservation": None,
                "statistical_status": "missing", "status": "HOLD", "reasons": []}
        for variant in sorted(observed[case_id]):
            all_ns, medians = [], []
            for _, rounds in sorted(processes.items()):
                ns = [b[variant]["elapsed_ns"] / b[variant]["iterations"] for _, b in sorted(rounds.items())]
                all_ns.extend(ns)
                medians.append(median(ns))
            low, high = cluster_interval(medians, median, rng)
            estimate = median(medians)
            case["variants"][variant] = {"count": len(all_ns), "median_ns": median(all_ns),
                                         "process_median_ns": estimate, "ci95_ns": {"lower": low, "upper": high}}
            bmf[f"{case_id}/{variant}"] = {"latency": {"value": estimate, "lower_value": low, "upper_value": high}}
        if observed[case_id] != set(required):
            case["reasons"].append("missing_required_variants")
        else:
            ratio, balanced = paired_measurement(processes, baseline, candidate, policy, rng)
            case["ratio"] = ratio
            estimate, low, high = (ratio[k] for k in ("estimate", "lower", "upper"))
            case["statistical_status"] = "faster" if high < 1 else "slower" if low > 1 else "inconclusive"
            if len(processes) < policy["min_processes"]:
                case["reasons"].append("insufficient_processes")
            if any(len(r) < policy["min_rounds"] for r in processes.values()):
                case["reasons"].append("insufficient_rounds")
            if not balanced:
                case["reasons"].append("unbalanced_pair_order")
            if (high - low) / estimate > policy["max_relative_ci_width"]:
                case["reasons"].append("noisy_ratio_interval")
            if role == "unchanged_control":
                if not low <= 1 <= high:
                    case["reasons"].append("unchanged_control_drift")
            elif high >= 1:
                case["reasons"].append("not_confidently_faster")
            if "rust_current" in required and candidate != "rust_current":
                rust_ratio, rust_balanced = paired_measurement(processes, "rust_current", candidate, policy, rng)
                rust_reasons = [r for r in case["reasons"] if r in ("insufficient_processes", "insufficient_rounds")]
                if not rust_balanced:
                    rust_reasons.append("unbalanced_pair_order")
                if (rust_ratio["upper"] - rust_ratio["lower"]) / rust_ratio["estimate"] > policy["max_relative_ci_width"]:
                    rust_reasons.append("noisy_ratio_interval")
                if role == "unchanged_control" and not rust_ratio["lower"] <= 1 <= rust_ratio["upper"]:
                    rust_reasons.append("unchanged_control_drift")
                elif role != "unchanged_control" and rust_ratio["upper"] > 1:
                    rust_reasons.append("not_preserved")
                case["rust_preservation"] = {"baseline": "rust_current", "candidate": candidate,
                                              "ratio": rust_ratio, "status": "HOLD" if rust_reasons else "PASS",
                                              "reasons": rust_reasons}
                if rust_reasons:
                    case["reasons"].append("existing_rust_not_preserved")
        if fixture["scope"] == "complete_caller":
            if baseline not in ("cpp_current", "cpp_optimized"):
                case["reasons"].append("non_cpp_runtime_baseline")
            if applicability is None:
                case["reasons"].append("missing_rust_preservation_applicability")
            elif applicability == "required":
                if "rust_current" not in required:
                    case["reasons"].append("missing_current_rust_baseline")
                elif "rust_current" not in observed[case_id]:
                    case["reasons"].append("missing_current_rust_samples")
        if fixture["scope"] == "kernel":
            case["reasons"].append("kernel_cannot_qualify_runtime")
        if not case["reasons"]:
            case["status"] = "PASS"
        summary["cases"].append(case)
    complete = [c for c in summary["cases"] if c["scope"] == "complete_caller"]
    reasons = []
    if not any(c["role"] == "changed" for c in complete):
        reasons.append("no_changed_complete_caller_evidence")
    if any(c["status"] != "PASS" for c in complete):
        reasons.append("complete_caller_cases_on_hold")
    qualification = {**identity, "status": "HOLD" if reasons else "PASS", "reasons": reasons,
                     "methodology": methodology,
                     "cases": [{k: c[k] for k in ("case", "scope", "role", "status", "reasons", "ratio", "rust_preservation", "rust_preservation_applicability")}
                               for c in summary["cases"]]}
    return summary, bmf, qualification


def exact_fields(obj, names, label):
    fields(obj, names, label)
    require(set(obj) == set(names), f"{label} has unknown fields")


def campaign_design(manifest):
    """Validate declarations and bound planned work before examining samples."""
    validate_manifest(manifest, campaign=True)
    require(manifest["comparison"]["baseline"] in ("cpp_current", "cpp_optimized") and
            manifest["comparison"]["candidate"] == "rust_candidate",
            "campaign comparison must select a C++ baseline and rust_candidate")
    exact_fields(manifest.get("qualification_policy"), DEFAULT_POLICY, "campaign qualification_policy")
    profile = manifest.get("qualification_profile")
    exact_fields(profile, ("id", "version", "plan_id", "plan_sha256", "variant_bindings", "collection_design"),
                 "qualification_profile")
    require(profile["id"] == CAMPAIGN_ID and type(profile["version"]) is int and profile["version"] == 1,
            "unsupported campaign profile id/version")
    text(profile["plan_id"], "campaign plan_id")
    digest(profile["plan_sha256"], "campaign plan_sha256")
    fixtures = {f["id"]: f for f in manifest["fixtures"]}
    designs = profile["collection_design"]
    require(isinstance(designs, dict) and set(designs) == set(fixtures),
            "collection_design must match every declared fixture")
    all_variants = set()
    planned_rows = selections = 0
    for case, fixture in fixtures.items():
        fields(fixture, ("role", "required_variants"), "campaign fixture")
        variants = fixture["required_variants"]
        all_variants.update(variants)
        design = designs[case]
        exact_fields(design, ("elapsed_floor_ns", "process_count", "round_count", "order_cycle"),
                     "collection_design entry")
        integer(design["elapsed_floor_ns"], "elapsed_floor_ns", 1)
        integer(design["process_count"], "process_count", 1, MAX_PROCESSES)
        integer(design["round_count"], "round_count", 1, MAX_ROWS)
        cycle = design["order_cycle"]
        require(isinstance(cycle, list) and 1 <= len(cycle) <= 24, "order_cycle must contain 1..24 permutations")
        for permutation in cycle:
            require(isinstance(permutation, list) and len(permutation) == len(variants) and
                    all(isinstance(v, str) for v in permutation) and set(permutation) == set(variants),
                    "order_cycle needs complete unique variant permutations")
        require(design["round_count"] % len(cycle) == 0, "round_count must complete the frozen order cycle")
        planned_rows += design["process_count"] * design["round_count"] * len(variants)
        comparisons = 2 + int(fixture.get("rust_preservation_applicability") == "required")
        selections += REPLICATES * design["process_count"] * comparisons
    require(planned_rows <= MAX_ROWS, "campaign planned row budget exceeded")
    require(selections <= MAX_BOOTSTRAP_SELECTIONS, "campaign bootstrap work budget exceeded")
    bindings = profile["variant_bindings"]
    require(isinstance(bindings, dict) and set(bindings) == all_variants,
            "variant_bindings must match all required variants")
    for variant, binding in bindings.items():
        names = ["source_sha", "source_content_sha256", "executable_sha256"]
        if variant.startswith("rust_"):
            names.append("rust_archive_sha256")
        exact_fields(binding, names, "campaign variant binding")
        for key, value in binding.items():
            digest(value, key, 40 if key == "source_sha" else 64)
    return profile, designs


def summarize_campaign(manifest, rows, analysis_sha256):
    """Campaign-v1 numerical eligibility; no execution or approval attestation."""
    profile, designs = campaign_design(manifest)
    require(isinstance(rows, list) and len(rows) <= MAX_ROWS, "campaign sample row budget exceeded")
    fixtures = {f["id"]: f for f in manifest["fixtures"]}
    for index, row in enumerate(rows):
        label = f"campaign sample row {index + 1}"
        fields(row, ("case", "variant", "process", "round", "order", "elapsed_ns"), label)
        require(isinstance(row["case"], str) and row["case"] in fixtures, f"{label} unknown fixture")
        design = designs[row["case"]]
        integer(row["elapsed_ns"], f"{label} elapsed_ns", 1)
        require(row["elapsed_ns"] >= design["elapsed_floor_ns"], f"{label} elapsed_ns is under frozen floor")
        integer(row["process"], f"{label} process", 0, design["process_count"] - 1)
        integer(row["round"], f"{label} round", 0, design["round_count"] - 1)
        permutation = design["order_cycle"][row["round"] % len(design["order_cycle"])]
        require(isinstance(row["variant"], str) and row["variant"] in permutation,
                f"{label} variant outside frozen order")
        integer(row["order"], f"{label} order", 0, len(permutation) - 1)
        require(permutation[row["order"]] == row["variant"], f"{label} differs from frozen order")
    grouped, observed = validate_rows(manifest, rows, campaign=True)
    try:
        encoded = json.dumps((manifest, rows), allow_nan=False)
        require(len(encoded) <= 40 * 1024 * 1024, "parsed evidence exceeds byte budget")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValidationError("evidence extensions must be bounded finite JSON") from error
    digest(analysis_sha256, "analysis_sha256")
    policy = policy_for(manifest)
    result = {k: manifest[k] for k in ("schema_version", "base_sha", "candidate_sha", "testbed")}
    result.update(qualification_profile=profile, analysis_sha256=analysis_sha256,
                  eligibility_scope="numerical_only", status="HOLD", reasons=[], cases=[],
                  methodology={"ratio_estimator": "exp(mean(process mean(log(paired candidate/baseline ns/op))))",
                    "resampling_unit": "whole process cluster; every paired round retained",
                    "interval": "95% percentile bootstrap; linear quantiles at 0.025 and 0.975",
                    "bootstrap_replicates": REPLICATES, "seed": SEED, "policy": policy,
                    "comparison_rng": "each named comparison resets the fixed seed",
                    "coverage": "per-case intervals; no simultaneous family coverage guarantee",
                    "outliers": "all retained; no trimming or independent round resampling",
                    "limits": "numerical eligibility only; declarations do not attest caller/domain/ABI, native execution, build lineage, independence, reviewed applicability, retirement or hold release"})
    for fixture in manifest["fixtures"]:
        case_id, required = fixture["id"], set(fixture["required_variants"])
        design, processes = designs[case_id], grouped[case_id]
        applicability = fixture.get("rust_preservation_applicability")
        reasons = []
        if not {"cpp_current", "cpp_optimized", "rust_candidate"} <= required:
            reasons.append("missing_campaign_variants")
        if applicability is None:
            reasons.append("missing_rust_preservation_applicability")
        elif applicability == "required" and "rust_current" not in required:
            reasons.append("missing_current_rust_baseline")
        if observed[case_id] != required:
            reasons.append("missing_required_variants")
        complete_grid = (set(processes) == set(range(design["process_count"])) and
                         all(set(rounds) == set(range(design["round_count"])) for rounds in processes.values()))
        if not complete_grid:
            reasons.append("incomplete_frozen_grid")
        case = {"case": case_id, "scope": fixture["scope"], "role": fixture["role"],
                "fixture_sha256": fixture["sha256"], "provenance": fixture.get("provenance", {}),
                "required_variants": fixture["required_variants"],
                "rust_preservation_applicability": applicability, "collection_design": design,
                "raw_count": sum(len(block) for rounds in processes.values() for block in rounds.values()),
                "process_count": len(processes), "round_counts": {str(p): len(r) for p, r in sorted(processes.items())},
                "complete": not reasons, "comparisons": {}, "status": "HOLD", "reasons": reasons}
        # Never compute eligibility from a surviving subset of the frozen design.
        if not reasons:
            baselines = ["cpp_current", "cpp_optimized"]
            if applicability == "required":
                baselines.append("rust_current")
            for baseline in baselines:
                ratio, balanced = paired_measurement(processes, baseline, "rust_candidate", policy,
                                                     random.Random(SEED), exact_batches=True)
                check_reasons = []
                if len(processes) < policy["min_processes"]:
                    check_reasons.append("insufficient_processes")
                if design["round_count"] < policy["min_rounds"]:
                    check_reasons.append("insufficient_rounds")
                if not balanced:
                    check_reasons.append("unbalanced_pair_order")
                # Require equal before/after counts, in addition to the minimum.
                for rounds in processes.values():
                    before = sum(b[baseline]["order"] < b["rust_candidate"]["order"] for b in rounds.values())
                    if before * 2 != len(rounds):
                        if "unbalanced_pair_order" not in check_reasons:
                            check_reasons.append("unbalanced_pair_order")
                if (ratio["upper"] - ratio["lower"]) / ratio["estimate"] > policy["max_relative_ci_width"]:
                    check_reasons.append("noisy_ratio_interval")
                threshold = 1 if baseline == "rust_current" else 0.5
                if fixture["role"] == "unchanged_control":
                    if not ratio["lower"] <= 1 <= ratio["upper"]:
                        check_reasons.append("unchanged_control_drift")
                elif ratio["upper"] > threshold:
                    check_reasons.append("not_preserved" if baseline == "rust_current" else "below_twofold_cpp_gate")
                case["comparisons"][baseline] = {"baseline": baseline, "candidate": "rust_candidate",
                    "ratio": ratio, "upper_bound_limit": threshold,
                    "rule": "interval_contains_one" if fixture["role"] == "unchanged_control" else "upper_bound_limit",
                    "status": "HOLD" if check_reasons else "PASS", "reasons": check_reasons}
                if check_reasons:
                    reasons.append(baseline + "_on_hold")
        if fixture["scope"] != "complete_caller":
            reasons.append("kernel_cannot_qualify_campaign")
        case["status"] = "HOLD" if reasons else "PASS"
        result["cases"].append(case)
    if not any(c["scope"] == "complete_caller" and c["role"] == "changed" for c in result["cases"]):
        result["reasons"].append("no_changed_complete_caller_evidence")
    if any(c["status"] != "PASS" for c in result["cases"]):
        result["reasons"].append("campaign_cases_on_hold")
    result["status"] = "HOLD" if result["reasons"] else "PASS"
    return result


def render_campaign_report(qualification):
    lines = [f"Campaign-v1 numerical eligibility: **{qualification['status']}**", "",
             "PASS does not attest caller/domain/ABI correctness, native execution, independent processes, "
             "build lineage, reviewed preservation applicability, retirement, or release of any hold.", "",
             "| Case / baseline | Status | Candidate/baseline [95% CI] | Rule | Reasons |",
             "| --- | --- | --- | --- | --- |"]
    for case in qualification["cases"]:
        if not case["comparisons"]:
            lines.append("| " + " | ".join(markdown(x) for x in
                         (case["case"], case["status"], "not computed: incomplete declarations/grid", "none",
                          ", ".join(case["reasons"]))) + " |")
        for baseline, check in case["comparisons"].items():
            ratio = check["ratio"]
            rule = "interval contains 1" if check["rule"] == "interval_contains_one" else f"upper <= {check['upper_bound_limit']}"
            lines.append("| " + " | ".join(markdown(x) for x in
                         (case["case"] + " / " + baseline, check["status"],
                          f"{ratio['estimate']:.6g} [{ratio['lower']:.6g}, {ratio['upper']:.6g}]", rule,
                          ", ".join(check["reasons"] + case["reasons"]) or "eligible numerically")) + " |")
    lines.extend(["", "Every required row uses exact integer batch elapsed nanoseconds at or above its frozen floor. "
                  "Every declared process/round/variant/order key must be complete; missing grid evidence is not analyzed as a subset. "
                  "The paired log-ratio estimator weights processes equally. The 95% percentile bootstrap resamples whole "
                  f"processes ({REPLICATES} replicates, seed {SEED} reset per comparison); every paired round and outlier is retained. "
                  "Intervals are per case, without simultaneous family coverage assurance. No fixture pooling or workload weights.", "",
                  "Explicit prospective policy: " + markdown(json.dumps(qualification["methodology"]["policy"], sort_keys=True)), "",
                  "Plan SHA256: `" + qualification["qualification_profile"]["plan_sha256"] + "`. "
                  "Analysis SHA256: `" + qualification["analysis_sha256"] + "`.", "",
                  "Manifest SHA256: `" + qualification["input_hashes"]["manifest_sha256"] + "`. "
                  "Samples SHA256: `" + qualification["input_hashes"]["samples_sha256"] + "`."])
    return "\n".join(lines) + "\n"


def markdown(value):
    escaped = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", escaped)


def render_report(summary, qualification):
    lines = [f"Numerical qualification: **{qualification['status']}**", "",
             f"Base: `{summary['base_sha']}`. Candidate: `{summary['candidate_sha']}`.",
             f"Testbed assertion: {markdown(summary['testbed'])}.", "",
             "| Case | Scope / role | Rust preservation applicability | Status | Paired ratio [95% CI] | Processes / rows | Reasons |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for case in summary["cases"]:
        ratio = case["ratio"]
        value = "missing" if ratio is None else f"{ratio['estimate']:.6g} [{ratio['lower']:.6g}, {ratio['upper']:.6g}]"
        lines.append("| " + " | ".join(markdown(x) for x in
                     (case["case"], case["scope"] + " / " + case["role"], case.get("rust_preservation_applicability") or "missing", case["status"], value,
                      f"{case['process_count']} / {case['raw_count']}", ", ".join(case["reasons"]) or "eligible numerically")) + " |")
    lines.extend(["", "| Case / variant | Median of process medians (ns/op) | Cluster 95% CI (ns/op) | Raw rows |",
                  "| --- | --- | --- | --- |"])
    for case in summary["cases"]:
        for variant, measured in sorted(case["variants"].items()):
            bounds = measured["ci95_ns"]
            lines.append("| " + " | ".join(markdown(x) for x in
                         (case["case"] + " / " + variant, f"{measured['process_median_ns']:.6g}",
                          f"[{bounds['lower']:.6g}, {bounds['upper']:.6g}]", measured["count"])) + " |")
    preserved = [c for c in summary["cases"] if c.get("rust_preservation") is not None]
    if preserved:
        lines.extend(["", "| Case | Candidate / current Rust [95% CI] | Preservation status | Reasons |",
                      "| --- | --- | --- | --- |"])
        for case in preserved:
            check = case["rust_preservation"]
            ratio = check["ratio"]
            lines.append("| " + " | ".join(markdown(x) for x in
                         (case["case"], f"{ratio['estimate']:.6g} [{ratio['lower']:.6g}, {ratio['upper']:.6g}]",
                          check["status"], ", ".join(check["reasons"]) or "preserved numerically")) + " |")
    lines.extend(["", "Each process contributes the mean log paired candidate/baseline ns/op ratio; processes receive equal weight. "
                  "The estimate exponentiates their mean. The percentile bootstrap resamples whole processes with replacement, "
                  "preserving every round in each selected cluster. Linear 2.5% and 97.5% quantiles form the interval.", "",
                  f"Bootstrap: {REPLICATES} replicates; seed {SEED}. Latency history is the median of process medians with "
                  "its own cluster bootstrap interval. All outliers and raw rows are retained. Intervals apply per case; "
                  "there is no simultaneous family coverage guarantee.", "",
                  "Prospective qualification policy: " + markdown(json.dumps(summary["methodology"]["policy"], sort_keys=True)) + ". "
                  "These conservative defaults are configurable and do not guarantee accuracy or reassess historical ports.", "",
                  "Changed complete callers need an upper ratio bound below 1. Every changed caller must pass, including tiny calls. "
                  "Runtime qualification requires the selected baseline to be cpp_current or cpp_optimized; "
                  "other comparisons remain useful numerical profiling and always hold runtime qualification. "
                  "Every complete caller needs an explicit Rust-preservation applicability decision: required needs a "
                  "declared current Rust baseline and measured samples; not_applicable needs a nonempty provenance rationale "
                  "and cannot contradict a declared current Rust baseline. The rationale and applicability decision require "
                  "independent review bound to the actual captured source hashes; these declarations do not prove approval. "
                  "A required current-Rust baseline also needs its candidate/current ratio upper bound at most 1, "
                  "with balanced order and sufficient precise evidence. This allows equality for preservation while "
                  "retaining the selected C++ baseline's strict speed gate. "
                  "This preservation check applies to any different candidate implementation, including C++ candidates. "
                  "For genuine unchanged controls, both baseline intervals must contain 1 with the same evidence quality; "
                  "significant drift in either direction holds the control. "
                  "Genuine unchanged controls require an interval containing 1; drift in either direction holds the result. "
                  "A control declaration requires external attribution. Kernel results cannot qualify a runtime replacement. "
                  "The existing 10% CI regression alert is not a migration waiver.", "",
                  "HOLD includes missing, insufficient, unbalanced, noisy, slower or inconclusive evidence. "
                  "An exit code of zero means valid artifacts, including HOLD. These results assess numerical eligibility only: "
                  "verify immutable git/build identity, toolchains, fixtures, output correctness, testbed stability, independence, "
                  "and control attribution through trusted provenance before approving a runtime replacement."])
    if "input_hashes" in summary:
        lines.extend(["", "Input SHA256: manifest `" + summary["input_hashes"]["manifest_sha256"] + "`; samples `" +
                      summary["input_hashes"]["samples_sha256"] + "`."])
    return "\n".join(lines) + "\n"


def strict_json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, f"duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def nonfinite(_):
        raise ValidationError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise ValidationError("malformed JSON input") from error


def traversed_entries(path):
    """Record entries visited during bounded POSIX symlink expansion, before '..'."""
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    pending = deque(absolute.parts[1:])
    visited = {current}
    expansions = 0
    while pending:
        part = pending.popleft()
        if part == ".":
            continue
        if part == "..":
            current = current.parent
            visited.add(current)
            continue
        entry = current / part
        visited.add(entry)
        try:
            metadata = entry.lstat()
        except (FileNotFoundError, NotADirectoryError):
            # Missing inputs are rejected by the reader after stale owned
            # artifacts are cleared; still protect each lexical component.
            current = entry
            continue
        if stat.S_ISLNK(metadata.st_mode):
            expansions += 1
            require(expansions <= 40, "input symlink expansion budget exceeded")
            target = Path(os.readlink(entry))
            if target.is_absolute():
                current = Path(target.anchor)
                visited.add(current)
                parts = target.parts[1:]
            else:
                parts = target.parts
            pending.extendleft(reversed(parts))
        else:
            current = entry
    return visited


def read_bounded(path, limit, *, stable=False):
    # Opening a FIFO normally blocks before any size check. Open nonblocking,
    # then inspect the descriptor actually opened before attempting any read.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), "evidence input must be a regular file")
        require(metadata.st_size <= limit, "input exceeds byte budget")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if stable:
            after = os.fstat(descriptor)
            identity = lambda m: (m.st_dev, m.st_ino, m.st_size, m.st_mtime_ns, m.st_ctime_ns)
            require(len(data) == metadata.st_size and identity(metadata) == identity(after),
                    "campaign evidence input changed or read was incomplete")
    finally:
        os.close(descriptor)
    require(len(data) <= limit, "input exceeds byte budget")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--qualification-profile", default=None,
                        help="explicit rust-replacement-campaign-v1; default keeps generic v1")
    args = parser.parse_args(argv)
    campaign = args.qualification_profile is not None
    # Classify ownership from the same bounded, stable bytes later consumed.
    # Keep read/parse failure pending until protected legacy targets are cleared,
    # preserving malformed generic reimport invalidation without a second read.
    manifest_bytes = manifest = None
    manifest_error = None
    try:
        manifest_bytes = read_bounded(args.manifest, 1024 * 1024, stable=True)
        manifest = strict_json(manifest_bytes)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        manifest_error = error
    campaign_attempt = campaign or (isinstance(manifest, dict) and "qualification_profile" in manifest)
    owned_outputs = CAMPAIGN_OUTPUTS if campaign_attempt else OUTPUTS
    targets = [args.output_dir / name for name in owned_outputs]
    try:
        # Preserve original traversal components before resolving: a symlink
        # traversed before a later '..' is still needed to reach the input.
        inputs = [args.manifest, args.samples]
        if campaign_attempt:
            inputs.append(Path(__file__))
        originals = [p if p.is_absolute() else Path.cwd() / p for p in inputs]
        protected = {ancestor for p in originals for ancestor in (p, *p.parents)}
        for path in originals:
            protected.update(traversed_entries(path))
        resolved = {p.resolve() for p in protected}
        aliases = any(p.resolve() in resolved or any(p.exists() and i.exists() and p.samefile(i)
                                                    for i in protected) for p in targets)
        require(not aliases, "output path collides with immutable input")
    except (OSError, ValueError) as error:
        print(f"benchmark evidence rejected: {error}", file=sys.stderr)
        return 2
    try:
        # Remove only this tool's owned artifacts, including symlinks, before
        # revalidation so a rejected import cannot leave a stale PASS behind.
        for path in targets:
            path.unlink(missing_ok=True)
        if campaign:
            require(args.qualification_profile == CAMPAIGN_SELECTOR, "unsupported qualification profile selector")
        elif campaign_attempt:
            raise ValidationError("qualification_profile requires explicit campaign selector; no generic fallback")
        if manifest_error is not None:
            raise manifest_error
        sample_bytes = read_bounded(args.samples, 32 * 1024 * 1024, stable=campaign_attempt)
        raw_lines = sample_bytes.splitlines()
        require(len(raw_lines) <= MAX_ROWS, "sample row budget exceeded")
        require(all(line.strip() for line in raw_lines), "blank JSONL sample row")
        rows = [strict_json(line) for line in raw_lines]
        hashes = {"manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                  "samples_sha256": hashlib.sha256(sample_bytes).hexdigest()}
        if campaign:
            analysis_hash = hashlib.sha256(read_bounded(Path(__file__), 1024 * 1024, stable=True)).hexdigest()
            qualification = summarize_campaign(manifest, rows, analysis_hash)
            qualification["input_hashes"] = hashes
            payloads = [json.dumps(qualification, indent=2, sort_keys=True, allow_nan=False) + "\n",
                        render_campaign_report(qualification)]
        else:
            summary, bmf, qualification = summarize(manifest, rows)
            summary["input_hashes"] = qualification["input_hashes"] = hashes
            payloads = [json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n"
                        for obj in (summary, bmf, qualification)] + [render_report(summary, qualification)]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".summary-", dir=args.output_dir) as temporary:
            for path, payload in zip(targets, payloads):
                staged = Path(temporary) / path.name
                staged.write_text(payload, encoding="utf-8")
            for path in targets:
                (Path(temporary) / path.name).replace(path)
        return 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        for path in targets:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"benchmark evidence rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
