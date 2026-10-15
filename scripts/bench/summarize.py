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
from collections import defaultdict, deque, OrderedDict
from decimal import (Decimal, Context, DecimalException, ROUND_FLOOR, ROUND_CEILING,
                     ROUND_HALF_EVEN, InvalidOperation, DivisionByZero, Overflow,
                     Underflow, Subnormal, Clamped, FloatOperation)
from functools import cmp_to_key
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
CAMPAIGN_ARITHMETIC_POLICY_SHA256 = "4fe3e8086c88da789540bdbed6825e65f8adc18c41c73840a3aaaf7895092d39"
CAMPAIGN_PRECISIONS = (80, 160, 320, 640)
CAMPAIGN_ARITHMETIC_LIMITS = {
    "integer_bits": 16800000, "cache_bytes": 67108864, "ordering_calls": 250000,
    "materializations": 20000, "root_probes": 1024, "limb_work": 2**44,
    "coefficient_bits": 8192, "witness_bytes": 32768,
    "refinement_visits": 16000000, "exp_calls": 7680}


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


def policy_for(manifest, *, campaign_width=False):
    configured = manifest.get("qualification_policy", {})
    require(isinstance(configured, dict), "qualification_policy must be an object")
    require(not configured.keys() - DEFAULT_POLICY.keys(), "unknown qualification_policy fields")
    policy = {**DEFAULT_POLICY, **configured}
    integer(policy["min_processes"], "min_processes", 2, MAX_PROCESSES)
    integer(policy["min_rounds"], "min_rounds", 2, MAX_ROWS // 2)
    integer(policy["min_each_order"], "min_each_order", 1, MAX_ROWS // 2)
    width = policy["max_relative_ci_width"]
    # Campaign eligibility separately certifies the original JSON token. Its
    # display float may underflow to zero; generic policy semantics stay intact.
    require(finite_number(width) and (0 <= width <= 1 if campaign_width else 0 < width <= 1),
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
    policy_for(manifest, campaign_width=campaign)


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


def campaign_collection_design(design, variants):
    """The same bounded frozen design contract for producer and import."""
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


def campaign_binding_sources(bindings, base_sha, candidate_sha):
    """Validate declared source associations; this does not authenticate builds."""
    digest(base_sha, "base_sha", 40)
    digest(candidate_sha, "candidate_sha", 40)
    require(isinstance(bindings, dict) and set(bindings) <= VARIANTS,
            "campaign variant bindings must use known variants")
    for variant, binding in bindings.items():
        names = ["source_sha", "source_content_sha256", "executable_sha256"]
        if variant.startswith("rust_"):
            names.append("rust_archive_sha256")
        exact_fields(binding, names, "campaign variant binding")
        for key, value in binding.items():
            digest(value, key, 40 if key == "source_sha" else 64)
        if variant in ("cpp_current", "rust_current"):
            require(binding["source_sha"].lower() == base_sha.lower(),
                    "current variant source differs from canonical baseline")
        elif variant == "rust_candidate":
            require(binding["source_sha"].lower() == candidate_sha.lower(),
                    "candidate variant source differs from candidate SHA")


def campaign_comparison_policy_reasons(design, baseline, policy):
    """Eligibility from the validated complete frozen cycle, not new samples."""
    reasons = []
    if design["process_count"] < policy["min_processes"]:
        reasons.append("insufficient_processes")
    if design["round_count"] < policy["min_rounds"]:
        reasons.append("insufficient_rounds")
    cycle = design["order_cycle"]
    before = sum(order.index(baseline) < order.index("rust_candidate") for order in cycle)
    before *= design["round_count"] // len(cycle)
    after = design["round_count"] - before
    if min(before, after) < policy["min_each_order"] or before * 2 != design["round_count"]:
        reasons.append("unbalanced_pair_order")
    return reasons


def campaign_qualification_contract_sha256(policy, variant_bindings, case, design, baseline):
    """Bind declared eligibility metadata, not authenticity or numerical proof.

    Version1 canonical JSON uses sorted keys, compact separators, ASCII escapes
    and finite JSON. Only validated hexadecimal fields are lowercased. Arrays
    and provenance text retain their declared order/content. Semantic checks
    are separate so this function never blesses a newly hashed assertion.
    """
    relevant = {}
    for variant in (baseline, "rust_candidate"):
        require(variant in variant_bindings, "qualification contract missing variant binding")
        binding = variant_bindings[variant]
        names = ["source_sha", "source_content_sha256", "executable_sha256"]
        if variant.startswith("rust_"):
            names.append("rust_archive_sha256")
        exact_fields(binding, names, "qualification contract variant binding")
        for name, value in binding.items():
            digest(value, "qualification contract " + name, 40 if name == "source_sha" else 64)
        relevant[variant] = {name: value.lower() for name, value in binding.items()}
    names = ("case", "fixture_sha256", "scope", "role", "required_variants", "rust_preservation_applicability")
    fields(case, names, "qualification contract case")
    declaration = {name: case[name] for name in names}
    digest(declaration["fixture_sha256"], "qualification contract fixture hash")
    declaration["fixture_sha256"] = declaration["fixture_sha256"].lower()
    declaration.update(collection_design=design, provenance=case.get("provenance", {}))
    try:
        payload = json.dumps({"contract_version": 1, "qualification_policy": policy,
                              "variant_bindings": relevant, "case_declaration": declaration},
                             sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValidationError("qualification contract must be bounded finite JSON") from error
    require(len(payload) <= 4 * 1024 * 1024, "qualification contract canonical byte limit")
    return hashlib.sha256(payload).hexdigest()


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
        campaign_collection_design(design, variants)
        planned_rows += design["process_count"] * design["round_count"] * len(variants)
        comparisons = 2 + int(fixture.get("rust_preservation_applicability") == "required")
        selections += REPLICATES * design["process_count"] * comparisons
    require(planned_rows <= MAX_ROWS, "campaign planned row budget exceeded")
    require(selections <= MAX_BOOTSTRAP_SELECTIONS, "campaign bootstrap work budget exceeded")
    bindings = profile["variant_bindings"]
    require(isinstance(bindings, dict) and set(bindings) == all_variants,
            "variant_bindings must match all required variants")
    campaign_binding_sources(bindings, manifest["base_sha"], manifest["candidate_sha"])
    return profile, designs


def campaign_certificate_associations(certificate, artifact, case, baseline, comparison, design):
    """Bound witness metadata and associations, never replay or verify its math.

    The standard schema checks structure before external imports call this API.
    Scalars remain bounded lexical strings: no Decimal/int parsing of text,
    product construction, bootstrap replay or display-float gate occurs here.
    """
    try:
        payload = json.dumps(certificate, sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValidationError("campaign certificate must be bounded finite JSON") from error
    require(len(payload) <= CAMPAIGN_ARITHMETIC_LIMITS["witness_bytes"],
            "campaign certificate serialized byte limit")
    names = ("policy_sha256", "bindings", "method_id", "bootstrap_multiplicities_sha256",
             "bootstrap_multiplicities_encoding", "common_root_degree", "precision", "relations", "proof",
             "quantile_ranks", "width_policy_rational", "bounds", "bounding_contributors", "rank_enclosures",
             "exact_order_statistics", "work_cumulative", "peak_cache_payload_bytes", "display")
    exact_fields(certificate, names, "campaign certificate")
    require(certificate["policy_sha256"] == CAMPAIGN_ARITHMETIC_POLICY_SHA256 and
            certificate["method_id"] == "campaign-exact-threshold-source-design-20261014-v2" and
            certificate["display"] == "approximate only; certified relations decide eligibility" and
            certificate["bootstrap_multiplicities_encoding"] ==
            "5000 rows in replicate order; decimal process counts comma-separated plus LF",
            "campaign certificate method differs")
    digest(certificate["bootstrap_multiplicities_sha256"], "campaign draw hash")
    bound = certificate["bindings"]
    exact_fields(bound, ("analysis_sha256", "input_hashes", "plan_sha256", "fixture_sha256",
                         "case", "baseline", "candidate", "qualification_contract_sha256"), "campaign certificate bindings")
    fields(artifact, ("analysis_sha256", "input_hashes"), "campaign artifact witness identity")
    expected = {"analysis_sha256": artifact["analysis_sha256"],
                "plan_sha256": artifact["qualification_profile"]["plan_sha256"],
                "fixture_sha256": case["fixture_sha256"]}
    for name, value in expected.items():
        digest(value, "campaign artifact " + name)
        digest(bound[name], "campaign certificate " + name)
        require(bound[name].lower() == value.lower(), "campaign certificate hash association differs")
    for hashes in (artifact["input_hashes"], bound["input_hashes"]):
        exact_fields(hashes, ("manifest_sha256", "samples_sha256"), "campaign input hashes")
        for value in hashes.values():
            digest(value, "campaign input hash")
    require(all(bound["input_hashes"][name].lower() == artifact["input_hashes"][name].lower()
                for name in artifact["input_hashes"]), "campaign certificate input hashes differ")
    require((bound["case"], bound["baseline"], bound["candidate"]) ==
            (case["case"], baseline, "rust_candidate"), "campaign certificate caller association differs")
    digest(bound["qualification_contract_sha256"], "campaign qualification contract hash")
    expected_contract = campaign_qualification_contract_sha256(
        artifact["methodology"]["policy"], artifact["qualification_profile"]["variant_bindings"], case, design, baseline)
    require(bound["qualification_contract_sha256"].lower() == expected_contract,
            "campaign certificate qualification contract differs")
    degree = certificate["common_root_degree"]
    integer(degree, "campaign certificate degree", 1, MAX_ROWS)
    require(degree == design["process_count"] * design["round_count"],
            "campaign certificate degree differs from design")
    require(type(certificate["precision"]) is int and certificate["precision"] in CAMPAIGN_PRECISIONS,
            "campaign certificate precision differs")
    keys = ("upper_vs_limit", "lower_vs_one", "upper_vs_one", "width_vs_policy")
    exact_fields(certificate["relations"], keys, "campaign certificate relations")
    exact_fields(certificate["proof"], keys, "campaign certificate proof")
    proof_methods = ("uniform_exact_process_product", "directed_decimal_enclosure",
                     "exact_rational_root_quantile", "exact_radical_quotient_classes")
    require(all(value in ("LT", "EQ", "GT") for value in certificate["relations"].values()) and
            all(value in proof_methods for value in certificate["proof"].values()),
            "campaign certificate relation/proof differs")
    require(certificate["quantile_ranks"] == {"lower": [[124, 1, 40], [125, 39, 40]],
                                              "upper": [[4874, 39, 40], [4875, 1, 40]]},
            "campaign certificate quantile ranks differ")
    rational = certificate["width_policy_rational"]
    exact_fields(rational, ("numerator", "denominator"), "campaign certificate width rational")
    require(all(isinstance(v, str) and len(v) <= 2467 and re.fullmatch(r"[1-9][0-9]*", v)
                for v in rational.values()), "campaign certificate rational text exceeds bounds")
    require((len(rational["numerator"]), rational["numerator"]) <=
            (len(rational["denominator"]), rational["denominator"]),
            "campaign certificate width exceeds one")
    fields(artifact, ("methodology",), "campaign artifact methodology")
    methodology = artifact["methodology"]
    fields(methodology, ("seed", "bootstrap_replicates", "arithmetic_policy_sha256", "exact_width_policy"),
           "campaign artifact witness methodology")
    require(type(methodology["seed"]) is int and methodology["seed"] == SEED and
            type(methodology["bootstrap_replicates"]) is int and methodology["bootstrap_replicates"] == REPLICATES and
            methodology["arithmetic_policy_sha256"] == CAMPAIGN_ARITHMETIC_POLICY_SHA256,
            "campaign artifact witness methodology differs")
    provenance = methodology["exact_width_policy"]
    fields(provenance, ("source", "manifest_sha256", "token_sha256", "token_bytes", "default_decimal",
                        "numerator", "denominator", "display_policy_width"), "campaign exact width provenance")
    require(all(isinstance(provenance[n], str) and len(provenance[n]) <= 2467 and
                re.fullmatch(r"[1-9][0-9]*", provenance[n]) for n in ("numerator", "denominator")) and
            all(provenance[n] == rational[n] for n in ("numerator", "denominator")),
            "campaign certificate width policy association differs")
    digest(provenance["manifest_sha256"], "campaign width manifest hash")
    require(provenance["manifest_sha256"].lower() == artifact["input_hashes"]["manifest_sha256"].lower() and
            provenance["display_policy_width"] == "approximate binary float only; exact rational is authoritative",
            "campaign width provenance association differs")
    if provenance["source"] == "retained_manifest_json_number_token":
        digest(provenance["token_sha256"], "campaign width token hash")
        integer(provenance["token_bytes"], "campaign width token bytes", 1, 1024 * 1024)
        require(provenance["default_decimal"] is None, "campaign declared width provenance differs")
    else:
        require(provenance["source"] == "exact_default_decimal_declaration" and
                provenance["token_sha256"] is None and type(provenance["token_bytes"]) is int and
                provenance["token_bytes"] == 0 and provenance["default_decimal"] == "0.10" and
                (rational["numerator"], rational["denominator"]) == ("1", "10"),
                "campaign default width provenance differs")
    def interval(pair):
        require(isinstance(pair, list) and len(pair) == 2 and
                all(isinstance(v, str) and 0 < len(v) <= 672 and
                    re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:E[+-]?[0-9]{1,6})?", v) for v in pair),
                "campaign certificate decimal text exceeds bounds")
    def vector(counts):
        # Producer witnesses retain draw tuples before JSON encoding; external
        # consumers still provide schema-validated strict-JSON array values.
        require(isinstance(counts, (list, tuple)) and len(counts) == design["process_count"] and
                all(type(v) is int and 0 <= v <= design["process_count"] for v in counts) and
                sum(counts) == design["process_count"], "campaign certificate multiplicities differ")
    def rank_map(records, fields_):
        exact_fields(records, ("124", "125", "4874", "4875"), "campaign certificate rank map")
        for record in records.values():
            exact_fields(record, fields_, "campaign certificate rank record")
    exact_fields(certificate["bounds"], ("lower", "upper", "estimate"), "campaign certificate bounds")
    for pair in certificate["bounds"].values():
        interval(pair)
    enclosure = certificate["rank_enclosures"]
    exact_fields(enclosure, ("route", "uniform", "selected"), "campaign certificate enclosures")
    if enclosure["route"] == "uniform_exact_process_product":
        require(certificate["bounding_contributors"] is None and enclosure["selected"] is None and
                certificate["exact_order_statistics"] is not None, "campaign certificate uniform route differs")
        exact_fields(enclosure["uniform"], ("log", "ratio"), "campaign certificate uniform enclosure")
        for pair in enclosure["uniform"].values():
            interval(pair)
    else:
        require(enclosure["route"] == "log_endpoint_order_statistics" and enclosure["uniform"] is None,
                "campaign certificate nonuniform route differs")
        rank_map(enclosure["selected"], ("log", "ratio"))
        for record in enclosure["selected"].values():
            for pair in record.values():
                interval(pair)
        contributors = certificate["bounding_contributors"]
        rank_map(contributors, ("lower_id", "upper_id", "lower_process_multiplicities", "upper_process_multiplicities"))
        for record in contributors.values():
            for side in ("lower", "upper"):
                integer(record[side + "_id"], "campaign contributor id", 0, REPLICATES - 1)
                vector(record[side + "_process_multiplicities"])
    exact = certificate["exact_order_statistics"]
    if exact is not None:
        rank_map(exact, ("replicate_id", "process_multiplicities"))
        for record in exact.values():
            integer(record["replicate_id"], "campaign exact replicate id", 0, REPLICATES - 1)
            vector(record["process_multiplicities"])
    if enclosure["route"] == "uniform_exact_process_product":
        require(certificate["precision"] == CAMPAIGN_PRECISIONS[0] and
                all(p == "uniform_exact_process_product" for p in certificate["proof"].values()) and
                certificate["relations"]["width_vs_policy"] == "LT" and
                all(exact[str(rank)]["replicate_id"] == rank for rank in (124, 125, 4874, 4875)),
                "campaign uniform witness proof route differs")
    else:
        exact_proofs = {"exact_rational_root_quantile", "exact_radical_quotient_classes"}
        require(all(p in ("directed_decimal_enclosure", "exact_rational_root_quantile")
                    for k, p in certificate["proof"].items() if k != "width_vs_policy") and
                certificate["proof"]["width_vs_policy"] in ("directed_decimal_enclosure", "exact_radical_quotient_classes"),
                "campaign nonuniform witness proof route differs")
        has_exact = any(p in exact_proofs for p in certificate["proof"].values())
        require((exact is not None) == has_exact and
                (not has_exact or certificate["precision"] == CAMPAIGN_PRECISIONS[-1]) and
                all(certificate["relations"][k] == "EQ" for k, p in certificate["proof"].items() if p in exact_proofs),
                "campaign exact witness route differs")
    work = certificate["work_cumulative"]
    require(isinstance(work, dict) and set(work) <= CAMPAIGN_ARITHMETIC_LIMITS.keys(),
            "campaign certificate unknown work counter")
    for name, value in work.items():
        integer(value, "campaign cumulative work " + name, 0, CAMPAIGN_ARITHMETIC_LIMITS[name])
    integer(certificate["peak_cache_payload_bytes"], "campaign peak cache payload", 0,
            CAMPAIGN_ARITHMETIC_LIMITS["cache_bytes"])
    if comparison["status"] == "PASS":
        relations = certificate["relations"]
        require(relations["width_vs_policy"] != "GT" and
                (relations["lower_vs_one"] != "GT" and relations["upper_vs_one"] != "LT"
                 if case["role"] == "unchanged_control" else relations["upper_vs_limit"] != "GT"),
                "campaign PASS contradicts declared certificate relations")


def validate_campaign_artifact_associations(artifact, *, manifest_bytes=None):
    """Validate bounded producer/witness associations, not numerical proof.

    Future external consumers must first structurally validate bounded strict
    JSON, then call this function: static Draft202012 cannot compare arbitrary
    instance map entries. Witness-bearing imports also require the retained
    manifest bytes: exact width and complete copied declaration associations
    are checked once, without replaying samples or certificate mathematics.
    Missing evidence never falls back to a float or an internally rebound hash.
    No-witness HOLD diagnostics remain exempt from this preimage requirement.
    All producer cases retain frozen declarations even on HOLD; structurally
    partial diagnostic HOLD metadata need not pass here. Global HOLD never
    excuses inconsistent declarations in a PASS case.
    """
    fields(artifact, ("qualification_profile", "cases", "base_sha", "candidate_sha", "methodology"), "campaign artifact")
    fields(artifact["methodology"], ("policy",), "campaign artifact policy")
    exact_fields(artifact["methodology"]["policy"], DEFAULT_POLICY, "campaign artifact qualification policy")
    policy = policy_for({"qualification_policy": artifact["methodology"]["policy"]}, campaign_width=True)
    if artifact.get("status") == "PASS":
        require(isinstance(artifact.get("reasons"), list) and not artifact["reasons"],
                "campaign root PASS reasons must be an empty list")
    profile, cases = artifact["qualification_profile"], artifact["cases"]
    fields(profile, ("collection_design", "variant_bindings"), "campaign artifact profile")
    designs, bindings = profile["collection_design"], profile["variant_bindings"]
    require(isinstance(cases, list) and 0 < len(cases) <= MAX_FIXTURES,
            "campaign artifact cases must be bounded")
    # Scan only the bounded named slots; do not parse the manifest per witness.
    has_witness = any(isinstance(c, dict) and isinstance(c.get("comparisons"), dict) and
                      any(isinstance(c["comparisons"].get(name), dict) and
                          "certificate" in c["comparisons"][name]
                          for name in ("cpp_current", "cpp_optimized", "rust_current"))
                      for c in cases)
    if has_witness:
        # Reuse the exact bounded token/parser/default rules with independent
        # metadata accounting. This neither replays nor certifies witness math.
        retained, _, recovered_width = campaign_width_policy(manifest_bytes, CampaignArithmetic())
        fields(artifact, ("input_hashes",), "campaign retained manifest association")
        fields(artifact["input_hashes"], ("manifest_sha256",), "campaign retained input hash")
        actual_manifest_hash = artifact["input_hashes"]["manifest_sha256"]
        digest(actual_manifest_hash, "campaign retained manifest hash")
        require(actual_manifest_hash.lower() == recovered_width["manifest_sha256"],
                "campaign retained manifest hash differs from supplied bytes")
        fields(artifact["methodology"], ("exact_width_policy",), "campaign recovered width")
        declared_width = artifact["methodology"]["exact_width_policy"]
        fields(declared_width, recovered_width, "campaign recovered exact width provenance")
        for name, expected in recovered_width.items():
            actual = declared_width[name]
            if name.endswith("sha256") and expected is not None:
                digest(actual, "campaign recovered width " + name)
                matches = actual.lower() == expected
            else:
                matches = type(actual) is type(expected) and actual == expected
            require(matches, "campaign retained width preimage association differs: " + name)
        # Validate the actual producer declaration contract, not merely the
        # width token. Non-emitted toolchain/extensions remain raw-hashed input;
        # do not invent artifact fields for them. Numerical observations stay
        # with the existing checks below, not a sample/bootstrap replay here.
        retained_profile, retained_designs = campaign_design(retained)
        retained_policy = policy_for(retained, campaign_width=True)
        node_budget = 3 * len(manifest_bytes) + 4096
        character_budget = 6 * len(manifest_bytes) + 8192

        def charge_node():
            nonlocal node_budget
            require(node_budget > 0, "campaign retained declaration node budget")
            node_budget -= 1

        def charge_text(size):
            nonlocal character_budget
            require(size <= character_budget, "campaign retained declaration text budget")
            character_budget -= size

        # Mirror the producer's finite-JSON source requirement even in fields
        # it does not emit (e.g. an extension containing an overflowed float).
        # Lazy iterators bound pending state by nesting, never source breadth.
        pending = [iter((retained,))]
        while pending:
            try:
                value = next(pending[-1])
            except StopIteration:
                pending.pop()
                continue
            charge_node()
            kind = type(value)
            if kind is dict:
                pending.append(iter(value.keys()))
                pending.append(iter(value.values()))
            elif kind is list:
                pending.append(iter(value))
            elif kind is str:
                charge_text(len(value))
            elif kind is float:
                require(math.isfinite(value), "campaign retained declaration source must be finite JSON")
            else:
                require(kind in (int, bool, type(None)), "campaign retained declaration source must be JSON")

        def children(expected, observed, mode):
            if type(expected) is dict:
                for key, value in expected.items():
                    child_mode = ("hex" if mode == "binding" or mode == "profile" and key == "plan_sha256" else
                                  "bindings" if mode == "profile" and key == "variant_bindings" else
                                  "binding" if mode == "bindings" else "")
                    yield value, observed[key], child_mode
            else:
                for index, value in enumerate(expected):
                    yield value, observed[index], ""

        def same(expected, observed, label, mode=""):
            # Python == would collapse true/1/1.0 inside copied provenance.
            # Preserve exact JSON types and finite float identity (signedzero
            # included). Only validated, identified SHA paths normalize case.
            work = [iter(((expected, observed, mode),))]
            while work:
                try:
                    left, right, current_mode = next(work[-1])
                except StopIteration:
                    work.pop()
                    continue
                charge_node()
                kind = type(left)
                message = "campaign retained declaration differs: " + label
                require(type(right) is kind, message)
                if kind is dict:
                    require(len(left) == len(right) and
                            all(type(key) is str for key in right) and
                            all(key in right for key in left), message)
                    work.append(children(left, right, current_mode))
                elif kind is list:
                    require(len(left) == len(right), message)
                    work.append(children(left, right, current_mode))
                elif kind is str:
                    require(len(left) == len(right), message)
                    charge_text(len(left) + len(right))
                    if current_mode == "hex":
                        digest(right, "campaign retained declaration " + label, len(left))
                        require(left.lower() == right.lower(), message)
                    else:
                        require(left == right, message)
                elif kind is float:
                    require(math.isfinite(right) and left.hex() == right.hex(), message)
                else:
                    require(kind in (int, bool, type(None)) and left == right, message)

        fields(artifact, ("schema_version", "base_sha", "candidate_sha", "testbed"),
               "campaign retained declaration root")
        for name in ("schema_version", "base_sha", "candidate_sha", "testbed"):
            same(retained[name], artifact[name], name, "hex" if name.endswith("_sha") else "")
        same(retained_profile, profile, "qualification_profile", "profile")
        same(retained_policy, artifact["methodology"]["policy"], "methodology.policy")
        require(len(cases) == len(retained["fixtures"]), "campaign retained declaration case membership differs")
        # The producer appends cases in fixture sequence. Keysets alone cannot
        # preserve that copied sequence. Case/profile design equality is also
        # retained below; required_variants/order_cycle arrays stay ordered.
        for ordinal, fixture in enumerate(retained["fixtures"]):
            case = cases[ordinal]
            expected = {"case": fixture["id"], "fixture_sha256": fixture["sha256"],
                        "scope": fixture["scope"], "role": fixture["role"],
                        "required_variants": fixture["required_variants"],
                        "rust_preservation_applicability": fixture.get("rust_preservation_applicability"),
                        "provenance": fixture.get("provenance", {}),
                        "collection_design": retained_designs[fixture["id"]]}
            fields(case, expected, "campaign retained declaration case")
            for name, value in expected.items():
                same(value, case[name], "cases[" + str(ordinal) + "]." + name,
                     "hex" if name == "fixture_sha256" else "")
    require(isinstance(designs, dict) and 0 < len(designs) <= MAX_FIXTURES and
            isinstance(bindings, dict) and 0 < len(bindings) <= len(VARIANTS),
            "campaign artifact design/binding maps must be bounded")
    campaign_binding_sources(bindings, artifact["base_sha"], artifact["candidate_sha"])
    ids, variants_union = set(), set()
    planned_rows = selections = 0
    for case in cases:
        fields(case, ("case", "required_variants", "collection_design", "status",
                      "rust_preservation_applicability", "comparisons", "role", "scope"), "campaign artifact case")
        identity, variants = case["case"], case["required_variants"]
        text(identity, "campaign artifact case id")
        require(identity not in ids, "campaign artifact duplicate case id")
        ids.add(identity)
        require(isinstance(variants, list) and 2 <= len(variants) <= len(VARIANTS) and
                all(isinstance(v, str) and v in VARIANTS for v in variants) and
                len(set(variants)) == len(variants), "campaign artifact invalid required variants")
        variants_union.update(variants)
        require(identity in designs and isinstance(designs[identity], dict) and
                isinstance(case["collection_design"], dict) and
                case["collection_design"] == designs[identity],
                "campaign artifact case design differs from profile")
        # Mirror validate_manifest's declaration predicates before hashing:
        # supplied provenance is an object; every control has attribution.
        # Populated metadata remains an assertion, not authenticated evidence.
        if "provenance" in case:
            require(isinstance(case["provenance"], dict), "campaign provenance must be an object")
        if case["role"] == "unchanged_control":
            require(isinstance(case.get("provenance"), dict) and case["provenance"],
                    "unchanged_control needs externally verifiable attribution in fixture provenance")
        if case["scope"] == "complete_caller" and case["rust_preservation_applicability"] == "not_applicable":
            require("rust_current" not in variants, "not_applicable contradicts a declared current Rust baseline")
            fields(case, ("provenance",), "campaign not_applicable case")
            text(case["provenance"].get("rust_preservation_rationale"), "not_applicable rust_preservation_rationale", 4096)
        design = designs[identity]
        campaign_collection_design(design, variants)
        planned = design["process_count"] * design["round_count"] * len(variants)
        planned_rows += planned
        selections += REPLICATES * design["process_count"] * (2 + int(case["rust_preservation_applicability"] == "required"))
        if case["status"] == "PASS":
            require(isinstance(case.get("reasons"), list) and not case["reasons"],
                    "campaign case PASS reasons must be an empty list")
            require({"cpp_current", "cpp_optimized", "rust_candidate"} <= set(variants),
                    "campaign artifact PASS missing main variants")
            applicability, comparisons = case["rust_preservation_applicability"], case["comparisons"]
            require(applicability in ("required", "not_applicable") and isinstance(comparisons, dict),
                    "campaign artifact PASS needs preservation applicability")
            if applicability == "required":
                require("rust_current" in variants and "rust_current" in comparisons,
                        "campaign artifact PASS missing current Rust declaration/comparison")
            else:
                require("rust_current" not in variants and "rust_current" not in comparisons,
                        "campaign artifact PASS not_applicable contradicts current Rust")
            expected_comparisons = {"cpp_current", "cpp_optimized"} | ({"rust_current"} if applicability == "required" else set())
            require(set(comparisons) == expected_comparisons and
                    all(isinstance(c, dict) and c.get("status") == "PASS" for c in comparisons.values()),
                    "campaign artifact PASS comparison set/status differs")
            require(case["scope"] == "complete_caller", "campaign artifact PASS scope must be complete_caller")
        comparisons = case["comparisons"]
        require(isinstance(comparisons, dict) and set(comparisons) <= {"cpp_current", "cpp_optimized", "rust_current"},
                "campaign artifact invalid comparisons")
        if case["status"] == "PASS" or any(isinstance(c, dict) and c.get("status") == "PASS"
                                           for c in comparisons.values()):
            # A contained PASS exposes a decision even under outer HOLD. Scope
            # stays separate so complete kernel diagnostics remain possible.
            # These declarations are the producer's entry conditions before
            # it computes any comparisons. Numeric HOLD preserves every key;
            # key completeness must not require every sibling to be PASS.
            require({"cpp_current", "cpp_optimized", "rust_candidate"} <= set(variants),
                    "campaign PASS comparison missing main variants")
            applicability = case["rust_preservation_applicability"]
            require(applicability in ("required", "not_applicable", None),
                    "campaign PASS comparison unsupported preservation applicability")
            if case["scope"] == "complete_caller":
                require(applicability in ("required", "not_applicable"),
                        "campaign PASS comparison complete_caller needs preservation applicability")
            if applicability == "required":
                require("rust_current" in variants,
                        "campaign PASS comparison missing required current Rust declaration")
            expected_keys = {"cpp_current", "cpp_optimized"} | ({"rust_current"} if applicability == "required" else set())
            require(set(comparisons) == expected_keys, "campaign PASS comparison keys differ from applicability")
            fields(case, ("complete", "process_count", "round_counts", "raw_count"), "campaign PASS grid")
            require(case["complete"] is True and
                    type(case["process_count"]) is int and case["process_count"] == design["process_count"] and
                    type(case["raw_count"]) is int and case["raw_count"] == planned and
                    isinstance(case["round_counts"], dict) and
                    set(case["round_counts"]) == {str(p) for p in range(design["process_count"])} and
                    all(type(v) is int and v == design["round_count"] for v in case["round_counts"].values()),
                    "campaign artifact PASS observed grid differs from design")
        for baseline, comparison in comparisons.items():
            fields(comparison, ("baseline", "candidate", "upper_bound_limit", "rule", "status"), "campaign comparison")
            require(baseline in variants and "rust_candidate" in variants and
                    comparison["baseline"] == baseline and comparison["candidate"] == "rust_candidate" and
                    comparison["upper_bound_limit"] == (1 if baseline == "rust_current" else 0.5) and
                    comparison["rule"] == ("interval_contains_one" if case["role"] == "unchanged_control" else "upper_bound_limit") and
                    comparison["status"] in ("PASS", "HOLD"), "campaign comparison association differs")
            if comparison["status"] == "PASS":
                require(isinstance(comparison.get("reasons"), list) and not comparison["reasons"],
                        "campaign comparison PASS reasons must be an empty list")
                require(not campaign_comparison_policy_reasons(design, baseline, policy),
                        "campaign PASS violates qualification policy/order: " +
                        ",".join(campaign_comparison_policy_reasons(design, baseline, policy)))
                fields(comparison, ("certificate",), "campaign PASS comparison")
            if "certificate" in comparison:
                campaign_certificate_associations(comparison["certificate"], artifact, case, baseline, comparison, design)
    require(planned_rows <= MAX_ROWS, "campaign planned row budget exceeded")
    require(selections <= MAX_BOOTSTRAP_SELECTIONS, "campaign bootstrap work budget exceeded")
    require(set(designs) == ids, "campaign artifact design keys differ from case ids")
    require(set(bindings) == variants_union,
            "campaign artifact variant bindings differ from required union")


class CampaignArithmetic:
    """Campaign-local, precharged arithmetic; exhaustion is invalid analysis."""

    def __init__(self):
        self.used = defaultdict(int)
        self.peak_cache_bytes = 0

    def charge(self, name, amount=1):
        require(type(amount) is int and amount >= 0, "invalid campaign arithmetic charge")
        proposed = self.used[name] + amount
        require(proposed <= CAMPAIGN_ARITHMETIC_LIMITS[name],
                "campaign arithmetic resource limit: " + name)
        self.used[name] = proposed

    def bits(self, value, *, coefficient=False):
        limit = CAMPAIGN_ARITHMETIC_LIMITS["coefficient_bits" if coefficient else "integer_bits"]
        require(value.bit_length() <= limit, "campaign arithmetic integer size limit")
        return value

    def allocation(self, bits, *, coefficient=False):
        limit = CAMPAIGN_ARITHMETIC_LIMITS["coefficient_bits" if coefficient else "integer_bits"]
        require(bits <= limit, "campaign arithmetic preallocation size limit")

    def mul(self, x, y, *, coefficient=False):
        if not x or not y:
            return 0
        if x == 1:
            return self.bits(y, coefficient=coefficient)
        if y == 1:
            return self.bits(x, coefficient=coefficient)
        self.allocation(x.bit_length() + y.bit_length(), coefficient=coefficient)
        self.charge("limb_work", ((x.bit_length() + 29) // 30) * ((y.bit_length() + 29) // 30))
        return self.bits(x * y, coefficient=coefficient)

    def add(self, x, y, *, coefficient=False):
        self.allocation(max(x.bit_length(), y.bit_length()) + 1, coefficient=coefficient)
        self.charge("limb_work", (x.bit_length() + y.bit_length() + 59) // 30)
        return self.bits(x + y, coefficient=coefficient)

    def divide(self, x, y):
        require(y > 0, "campaign arithmetic zero divisor")
        self.charge("limb_work", 8 * (((x.bit_length() + 29) // 30) +
                                    ((y.bit_length() + 29) // 30)) ** 2)
        return x // y

    def gcd(self, x, y):
        self.charge("limb_work", 8 * (((x.bit_length() + 29) // 30) +
                                    ((y.bit_length() + 29) // 30)) ** 2)
        return math.gcd(x, y)

    def rational(self, n, d=1, *, coefficient=False):
        require(d > 0, "campaign arithmetic nonpositive denominator")
        self.bits(n, coefficient=coefficient)
        self.bits(d, coefficient=coefficient)
        common = self.gcd(abs(n), d)
        return self.divide(n, common), self.divide(d, common)

    def rmul(self, a, b, *, coefficient=False):
        g = self.gcd(abs(a[0]), b[1])
        h = self.gcd(abs(b[0]), a[1])
        n = self.mul(self.divide(a[0], g), self.divide(b[0], h), coefficient=coefficient)
        d = self.mul(self.divide(a[1], h), self.divide(b[1], g), coefficient=coefficient)
        return self.rational(n, d, coefficient=coefficient)

    def radd(self, a, b, *, coefficient=False):
        g = self.gcd(a[1], b[1])
        x, y = self.divide(a[1], g), self.divide(b[1], g)
        n = self.add(self.mul(a[0], y, coefficient=coefficient),
                     self.mul(b[0], x, coefficient=coefficient), coefficient=coefficient)
        return self.rational(n, self.mul(x, b[1], coefficient=coefficient), coefficient=coefficient)

    def rcompare(self, a, b):
        x, y = self.mul(a[0], b[1]), self.mul(b[0], a[1])
        return (x > y) - (x < y)

    def power(self, x, exponent, *, coefficient=False):
        result = 1
        while exponent:
            if exponent & 1:
                result = self.mul(result, x, coefficient=coefficient)
            exponent //= 2
            if exponent:
                x = self.mul(x, x, coefficient=coefficient)
        return result

    def rpower(self, a, exponent):
        return self.power(a[0], exponent), self.power(a[1], exponent)

    def capped_power(self, x, exponent, maximum):
        """Metered power comparison without allocating a value above maximum."""
        result = 1
        above = self.add(maximum, 1)
        while exponent:
            if exponent & 1:
                if x > maximum or result > self.divide(maximum, x):
                    return above
                result = self.mul(result, x)
            exponent //= 2
            if exponent:
                if x > maximum or x > self.divide(maximum, x):
                    x = above
                else:
                    x = self.mul(x, x)
        return result

    def root(self, value, degree):
        """Exact perfect-power probe, separately charged for each integer."""
        self.charge("root_probes")
        if value == 1 or degree == 1:
            return value
        if degree >= value.bit_length():
            return None
        # Construct the binary-search bound through charged powers, not pow().
        high = self.power(2, (value.bit_length() + degree - 1) // degree)
        low = 1
        while low <= high:
            middle = self.divide(self.add(low, high), 2)
            powered = self.capped_power(middle, degree, value)
            if powered == value:
                return middle
            if powered < value:
                low = self.add(middle, 1)
            else:
                high = self.add(middle, -1)
        return None

    def rational_root(self, value, degree):
        n = self.root(value[0], degree)
        d = self.root(value[1], degree)
        return None if n is None or d is None else self.rational(n, d, coefficient=True)


class CampaignProducts:
    """Lazy products for exact ordering; evictions release payload accounting."""

    def __init__(self, arithmetic, process_products):
        self.arithmetic = arithmetic
        self.process_products = process_products
        self.cache = OrderedDict()
        self.resident = 0

    def get(self, counts):
        if counts in self.cache:
            self.cache.move_to_end(counts)
            return self.cache[counts][0]
        a = self.arithmetic
        a.charge("materializations")
        value = (1, 1)
        for product, count in zip(self.process_products, counts):
            if count:
                value = a.rmul(value, a.rpower(product, count))
        payload = sum((v.bit_length() + 7) // 8 for v in value)
        require(payload <= CAMPAIGN_ARITHMETIC_LIMITS["cache_bytes"], "campaign exact product cache limit")
        while self.cache and (self.resident + payload > CAMPAIGN_ARITHMETIC_LIMITS["cache_bytes"] or
                              len(self.cache) >= REPLICATES):
            _, (_, released) = self.cache.popitem(last=False)
            self.resident -= released
        self.cache[counts] = value, payload
        self.resident += payload
        a.peak_cache_bytes = max(a.peak_cache_bytes, self.resident)
        return value

    def compare(self, left, right):
        self.arithmetic.charge("ordering_calls")
        return self.arithmetic.rcompare(self.get(left), self.get(right))


class CampaignIntervals:
    """Outward enclosures using explicit contexts, independent of ambient state."""

    def __init__(self, precision, arithmetic):
        traps = [InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal, Clamped, FloatOperation]
        self.down = Context(prec=precision, rounding=ROUND_FLOOR, Emin=-999999, Emax=999999, traps=traps)
        self.up = Context(prec=precision, rounding=ROUND_CEILING, Emin=-999999, Emax=999999, traps=traps)
        self.near = Context(prec=precision, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=traps)
        self.arithmetic = arithmetic

    def rational(self, value):
        n, d = (Decimal(v, context=self.near) for v in value)
        return self.down.divide(n, d), self.up.divide(n, d)

    def add(self, x, y):
        return self.down.add(x[0], y[0]), self.up.add(x[1], y[1])

    def scale(self, x, n, d=1):
        numerator, denominator = Decimal(n, context=self.near), Decimal(d, context=self.near)
        return (self.down.divide(self.down.multiply(x[0], numerator), denominator),
                self.up.divide(self.up.multiply(x[1], numerator), denominator))

    def subtract(self, x, y):
        return self.down.subtract(x[0], y[1]), self.up.subtract(x[1], y[0])

    def product(self, x, y):
        require(x[0] >= 0 and y[0] >= 0, "campaign interval product needs positive bounds")
        return self.down.multiply(x[0], y[0]), self.up.multiply(x[1], y[1])

    def log(self, value):
        if value == (1, 1):
            return Decimal(0), Decimal(0)
        bounds = self.rational(value)
        def endpoint(v, lower):
            if v == 1:
                return Decimal(0)
            rounded = self.near.ln(v)
            return self.near.next_minus(rounded) if lower else self.near.next_plus(rounded)
        return endpoint(bounds[0], True), endpoint(bounds[1], False)

    def exp(self, value):
        def endpoint(v, lower):
            self.arithmetic.charge("exp_calls")
            if v == 0:
                return Decimal(1)
            rounded = self.near.exp(v)
            return self.near.next_minus(rounded) if lower else self.near.next_plus(rounded)
        return endpoint(value[0], True), endpoint(value[1], False)


def campaign_relation(bounds):
    if bounds[1] < 0:
        return "LT"
    if bounds[0] > 0:
        return "GT"
    if bounds[0] == bounds[1] == 0:
        return "EQ"
    return None


def campaign_exact_ranks(logs, draws, products):
    """Sort only closed-overlap components containing the four needed ranks."""
    ordered = sorted(range(REPLICATES), key=lambda i: (logs[i][0], i))
    ranks = (124, 125, 4874, 4875)
    selected = {}
    start = 0
    while start < len(ordered):
        end, upper = start + 1, logs[ordered[start]][1]
        while end < len(ordered) and logs[ordered[end]][0] <= upper:
            upper = max(upper, logs[ordered[end]][1])
            end += 1
        needed = [rank for rank in ranks if start <= rank < end]
        if needed:
            def compare(i, j):
                relation = products.compare(draws[i], draws[j])
                return relation or ((i > j) - (i < j))
            component = sorted(ordered[start:end], key=cmp_to_key(compare))
            selected.update((rank, component[rank - start]) for rank in needed)
        start = end
    return selected


def campaign_quantile_equality(terms, threshold, products, degree, arithmetic):
    """A positive rational sum of two positive roots is rational only if both are."""
    total = (0, 1)
    for counts, weight in terms:
        root = arithmetic.rational_root(products.get(counts), degree)
        if root is None:
            return False
        total = arithmetic.radd(total, arithmetic.rmul(root, weight, coefficient=True), coefficient=True)
    return arithmetic.rcompare(total, threshold) == 0


def campaign_width_equality(terms, products, degree, arithmetic):
    """Group positive radicals by exact rational quotient, without factorization.

    Linear independence of distinct rational-quotient classes of positive roots
    makes a zero sum equivalent to zero rational coefficient in every class.
    """
    groups = []
    for counts, coefficient in terms:
        if not coefficient[0]:
            continue
        value = products.get(counts)
        for group in groups:
            quotient = arithmetic.rmul(value, (group[0][1], group[0][0]))
            root = arithmetic.rational_root(quotient, degree)
            if root is not None:
                group[1] = arithmetic.radd(group[1], arithmetic.rmul(coefficient, root, coefficient=True),
                                           coefficient=True)
                break
        else:
            groups.append([value, coefficient])
    return all(coefficient[0] == 0 for _, coefficient in groups)


def campaign_measurement(processes, baseline, candidate, policy, threshold, arithmetic, bindings,
                         width_rational):
    """Certify campaign predicates; displayed floats never select a disposition."""
    a = arithmetic
    process_products, balanced = [], True
    round_count = None
    for _, rounds in sorted(processes.items()):
        round_count = len(rounds) if round_count is None else round_count
        require(len(rounds) == round_count, "campaign needs equal frozen rounds")
        product, before = (1, 1), 0
        for _, block in sorted(rounds.items()):
            c, b = block[candidate], block[baseline]
            q = a.rational(a.mul(c["elapsed_ns"], b["iterations"]),
                           a.mul(b["elapsed_ns"], c["iterations"]))
            product = a.rmul(product, q)
            before += b["order"] < c["order"]
        balanced &= min(before, len(rounds) - before) >= policy["min_each_order"]
        process_products.append(product)
    count = len(process_products)
    degree = count * round_count
    rng = random.Random(SEED)
    draws = []
    for _ in range(REPLICATES):
        multiplicities = [0] * count
        for _ in range(count):
            multiplicities[rng.randrange(count)] += 1
        draws.append(tuple(multiplicities))
    draw_hash = hashlib.sha256()
    for multiplicities in draws:
        draw_hash.update((",".join(str(value) for value in multiplicities) + "\n").encode("ascii"))
    estimate_counts = (1,) * count
    target = (1, 1) if threshold == 1 else (1, 2)
    products = CampaignProducts(a, process_products)
    uniform = all(p == process_products[0] for p in process_products)
    relations, proof = {}, {}
    selected = None
    rank_contributors = None
    last_bounds = None
    try:
        for precision in CAMPAIGN_PRECISIONS:
            intervals = CampaignIntervals(precision, a)
            if uniform:
                log = intervals.scale(intervals.log(process_products[0]), 1, round_count)
                estimate = lower = upper = intervals.exp(log)
                compare_target = a.rcompare(process_products[0], a.rpower(target, round_count))
                compare_one = a.rcompare(process_products[0], (1, 1))
                word = lambda relation: "LT" if relation < 0 else "GT" if relation > 0 else "EQ"
                relations = {"upper_vs_limit": word(compare_target), "lower_vs_one": word(compare_one),
                             "upper_vs_one": word(compare_one), "width_vs_policy": "LT"}
                proof = {key: "uniform_exact_process_product" for key in relations}
                selected = {rank: rank for rank in (124, 125, 4874, 4875)}
                last_bounds = lower, upper, estimate
                break
            a.charge("refinement_visits", REPLICATES * count)
            means = [intervals.scale(intervals.log(p), 1, round_count) for p in process_products]
            def mean_log(multiplicities):
                total = (Decimal(0), Decimal(0))
                for value, weight in zip(means, multiplicities):
                    if weight:
                        total = intervals.add(total, intervals.scale(value, weight))
                return intervals.scale(total, 1, count)
            logs = [mean_log(multiplicities) for multiplicities in draws]
            lo_order = sorted(range(REPLICATES), key=lambda i: (logs[i][0], i))
            hi_order = sorted(range(REPLICATES), key=lambda i: (logs[i][1], i))
            rank_contributors = {str(rank): {"lower_id": lo_order[rank], "upper_id": hi_order[rank],
                                            "lower_process_multiplicities": draws[lo_order[rank]],
                                            "upper_process_multiplicities": draws[hi_order[rank]]}
                                 for rank in (124, 125, 4874, 4875)}
            rank_log_bounds = {rank: (logs[lo_order[rank]][0], logs[hi_order[rank]][1])
                               for rank in (124, 125, 4874, 4875)}
            rank_bounds = {rank: intervals.exp(rank_log_bounds[rank])
                           for rank in (124, 125, 4874, 4875)}
            lower = intervals.scale(intervals.add(rank_bounds[124], intervals.scale(rank_bounds[125], 39)), 1, 40)
            upper = intervals.scale(intervals.add(intervals.scale(rank_bounds[4874], 39), rank_bounds[4875]), 1, 40)
            estimate = intervals.exp(mean_log(estimate_counts))
            last_bounds = lower, upper, estimate
            width_expression = intervals.subtract(intervals.subtract(upper, lower),
                                                  intervals.product(intervals.rational(width_rational), estimate))
            relations = {"upper_vs_limit": campaign_relation(intervals.subtract(upper, intervals.rational(target))),
                         "lower_vs_one": campaign_relation(intervals.subtract(lower, (Decimal(1), Decimal(1)))),
                         "upper_vs_one": campaign_relation(intervals.subtract(upper, (Decimal(1), Decimal(1)))),
                         "width_vs_policy": campaign_relation(width_expression)}
            proof = {key: "directed_decimal_enclosure" for key, value in relations.items() if value is not None}
            if all(value is not None for value in relations.values()):
                break
            if precision == CAMPAIGN_PRECISIONS[-1]:
                selected = campaign_exact_ranks(logs, draws, products)
                lower_terms = [(draws[selected[124]], (1, 40)), (draws[selected[125]], (39, 40))]
                upper_terms = [(draws[selected[4874]], (39, 40)), (draws[selected[4875]], (1, 40))]
                for key, terms, limit in (("upper_vs_limit", upper_terms, target),
                                           ("lower_vs_one", lower_terms, (1, 1)),
                                           ("upper_vs_one", upper_terms, (1, 1))):
                    if relations[key] is None and campaign_quantile_equality(terms, limit, products, degree, a):
                        relations[key], proof[key] = "EQ", "exact_rational_root_quantile"
                if relations["width_vs_policy"] is None:
                    terms = upper_terms + [(counts, (-weight[0], weight[1])) for counts, weight in lower_terms]
                    terms.append((estimate_counts, (-width_rational[0], width_rational[1])))
                    if campaign_width_equality(terms, products, degree, a):
                        relations["width_vs_policy"], proof["width_vs_policy"] = "EQ", "exact_radical_quotient_classes"
                require(all(value is not None for value in relations.values()),
                        "campaign precision unresolved after exact equality certification")
    except DecimalException as error:
        raise ValidationError("campaign decimal arithmetic rejected") from error
    lower, upper, estimate = last_bounds
    # Floats are display-only approximations. The relation/proof fields decide.
    ratio = {"estimate": float(estimate[0]), "lower": float(lower[0]), "upper": float(upper[1])}
    require(all(math.isfinite(value) and value > 0 for value in ratio.values()), "campaign display range exceeded")
    witness = {"policy_sha256": CAMPAIGN_ARITHMETIC_POLICY_SHA256, "bindings": bindings,
               "method_id": "campaign-exact-threshold-source-design-20261014-v2",
               "bootstrap_multiplicities_sha256": draw_hash.hexdigest(),
               "bootstrap_multiplicities_encoding": "5000 rows in replicate order; decimal process counts comma-separated plus LF",
               "common_root_degree": degree, "precision": precision, "relations": relations, "proof": proof,
               "quantile_ranks": {"lower": [[124, 1, 40], [125, 39, 40]],
                                  "upper": [[4874, 39, 40], [4875, 1, 40]]},
               "width_policy_rational": {"numerator": str(width_rational[0]), "denominator": str(width_rational[1])},
               "bounds": {name: [str(v) for v in bounds] for name, bounds in
                          (("lower", lower), ("upper", upper), ("estimate", estimate))},
               "bounding_contributors": rank_contributors,
               "rank_enclosures": {
                   "route": "uniform_exact_process_product" if uniform else "log_endpoint_order_statistics",
                   "uniform": {"log": [str(v) for v in log],
                               "ratio": [str(v) for v in estimate]} if uniform else None,
                   "selected": None if uniform else {
                       str(rank): {"log": [str(v) for v in rank_log_bounds[rank]],
                                   "ratio": [str(v) for v in rank_bounds[rank]]}
                       for rank in (124, 125, 4874, 4875)}},
               "exact_order_statistics": None if selected is None else
                   {str(rank): {"replicate_id": index, "process_multiplicities": draws[index]} for rank, index in selected.items()},
               "work_cumulative": dict(a.used), "peak_cache_payload_bytes": a.peak_cache_bytes,
               "display": "approximate only; certified relations decide eligibility"}
    require(len(json.dumps(witness, sort_keys=True, allow_nan=False).encode()) <=
            CAMPAIGN_ARITHMETIC_LIMITS["witness_bytes"], "campaign arithmetic witness byte limit")
    return ratio, balanced, witness


def campaign_width_policy(manifest_bytes, arithmetic):
    """Recover one bounded exact decimal from retained bytes, never from float.

    The unreduced decimal numerator and power-of-ten denominator must fit the
    existing coefficient cap. Conservative preallocation can reject a value
    before reduction; this is an analysis compatibility limit, never HOLD/PASS.
    """
    require(type(manifest_bytes) is bytes and len(manifest_bytes) <= 1024 * 1024,
            "campaign requires retained manifest bytes limited to 1 MiB; materialized values lose numeric tokens")
    manifest = strict_json(manifest_bytes)
    tokens = strict_json(manifest_bytes, number_tokens=True)
    require(isinstance(tokens, dict), "manifest must be an object")
    configured = tokens.get("qualification_policy", {})
    require(isinstance(configured, dict), "qualification_policy must be an object")
    declared = "max_relative_ci_width" in configured
    token = configured.get("max_relative_ci_width", CampaignNumberToken("0.10"))
    require(type(token) is CampaignNumberToken, "campaign width must be a JSON number token")
    match = re.fullmatch(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?)([0-9]+))?", token)
    require(match is not None and not match[1], "campaign width must be positive")
    fraction = match[3] or ""
    digits = (match[2] + fraction).lstrip("0")
    require(bool(digits), "campaign width must be positive")
    # Exponent conversion is bounded lexically before int(), even for a token
    # containing almost 1 MiB of exponent digits or leading/trailing zeroes.
    exponent_digits = (match[5] or "0").lstrip("0") or "0"
    exponent_bound = str(len(manifest_bytes) + CAMPAIGN_ARITHMETIC_LIMITS["coefficient_bits"])
    require((len(exponent_digits), exponent_digits) <= (len(exponent_bound), exponent_bound),
            "campaign width exponent exceeds bounded coefficient compatibility")
    exponent = int(exponent_digits) * (-1 if match[4] == "-" else 1) - len(fraction)
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    digits = stripped
    require(len(digits) + exponent <= 0 or (digits == "1" and exponent == 0),
            "campaign width must be at most 1 exactly")
    denominator_exponent = max(0, -exponent)
    # 3.32193 is a rational upper bound on log2(10). Preflight both
    # unreduced allocations before constructing any large integer or power.
    arithmetic.allocation((len(digits) * 332193 + 99999) // 100000 + 1, coefficient=True)
    arithmetic.allocation((denominator_exponent * 332193 + 99999) // 100000 + 1, coefficient=True)
    numerator = 0
    small_powers = (1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000)
    for offset in range(0, len(digits), 9):
        chunk = digits[offset:offset + 9]
        numerator = arithmetic.add(arithmetic.mul(numerator, small_powers[len(chunk)], coefficient=True),
                                   int(chunk), coefficient=True)
    denominator = arithmetic.power(10, denominator_exponent, coefficient=True)
    rational = arithmetic.rational(numerator, denominator, coefficient=True)
    provenance = {"source": "retained_manifest_json_number_token" if declared else "exact_default_decimal_declaration",
                  "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                  "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest() if declared else None,
                  "token_bytes": len(token) if declared else 0, "default_decimal": None if declared else "0.10",
                  "numerator": str(rational[0]), "denominator": str(rational[1]),
                  "display_policy_width": "approximate binary float only; exact rational is authoritative"}
    return manifest, rational, provenance


def summarize_campaign(manifest_bytes, rows, analysis_sha256, input_hashes=None):
    """Campaign-v1 numerical eligibility; no execution or approval attestation."""
    arithmetic = CampaignArithmetic()
    manifest, width_rational, width_provenance = campaign_width_policy(manifest_bytes, arithmetic)
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
    policy = policy_for(manifest, campaign_width=True)
    result = {k: manifest[k] for k in ("schema_version", "base_sha", "candidate_sha", "testbed")}
    result.update(qualification_profile=profile, analysis_sha256=analysis_sha256,
                  eligibility_scope="numerical_only", status="HOLD", reasons=[], cases=[],
                  methodology={"ratio_estimator": "exp(mean(process mean(log(paired candidate/baseline ns/op))))",
                    "resampling_unit": "whole process cluster; every paired round retained",
                    "interval": "95% percentile bootstrap; linear quantiles at 0.025 and 0.975",
                    "bootstrap_replicates": REPLICATES, "seed": SEED, "policy": policy,
                    "exact_width_policy": width_provenance,
                    "comparison_rng": "each named comparison resets the fixed seed",
                    "arithmetic": "campaign directed enclosures with bounded exact equality certification; floats display only",
                    "arithmetic_policy_sha256": CAMPAIGN_ARITHMETIC_POLICY_SHA256,
                    "analysis_identity": "invocation source snapshot sampled for stability; not loaded-code or pre-load race authentication",
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
        if applicability is None and fixture["scope"] == "complete_caller":
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
                threshold = 1 if baseline == "rust_current" else 0.5
                ratio, balanced, certificate = campaign_measurement(
                    processes, baseline, "rust_candidate", policy, threshold, arithmetic,
                    {"analysis_sha256": analysis_sha256, "input_hashes": input_hashes,
                     "plan_sha256": profile["plan_sha256"], "fixture_sha256": fixture["sha256"],
                     "case": case_id, "baseline": baseline, "candidate": "rust_candidate",
                     "qualification_contract_sha256": campaign_qualification_contract_sha256(
                         policy, profile["variant_bindings"], case, design, baseline)},
                    width_rational)
                relations = certificate["relations"]
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
                # Complete grids were already checked row-by-row against this
                # cycle. Preserve actual-row reasons and assert shared import
                # eligibility agrees before the unchanged numerical gates.
                require(set(check_reasons) == set(campaign_comparison_policy_reasons(design, baseline, policy)),
                        "validated frozen design policy differs from observed rows")
                if relations["width_vs_policy"] == "GT":
                    check_reasons.append("noisy_ratio_interval")
                if fixture["role"] == "unchanged_control":
                    if relations["lower_vs_one"] == "GT" or relations["upper_vs_one"] == "LT":
                        check_reasons.append("unchanged_control_drift")
                elif relations["upper_vs_limit"] == "GT":
                    check_reasons.append("not_preserved" if baseline == "rust_current" else "below_twofold_cpp_gate")
                case["comparisons"][baseline] = {"baseline": baseline, "candidate": "rust_candidate",
                    "ratio": ratio, "certificate": certificate, "upper_bound_limit": threshold,
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
    if not any(c["scope"] == "complete_caller" and c["role"] == "unchanged_control" and
               c["status"] == "PASS" for c in result["cases"]):
        result["reasons"].append("no_passing_unchanged_complete_caller_control")
    if any(c["status"] != "PASS" for c in result["cases"]):
        result["reasons"].append("campaign_cases_on_hold")
    result["status"] = "HOLD" if result["reasons"] else "PASS"
    result["methodology"]["arithmetic_work_cumulative"] = dict(arithmetic.used)
    return result


def render_campaign_report(qualification):
    lines = [f"Campaign-v1 numerical eligibility: **{qualification['status']}**", "",
             "PASS does not attest caller/domain/ABI correctness, native execution, independent processes, "
             "build lineage, reviewed preservation applicability, retirement, or release of any hold.", "",
             "Displayed ratios are approximate; the certified relations decide numerical eligibility.", "",
             "| Case / baseline | Status | Approximate candidate/baseline [95% CI] | Rule / certificate | Reasons |",
             "| --- | --- | --- | --- | --- |"]
    for case in qualification["cases"]:
        if not case["comparisons"]:
            lines.append("| " + " | ".join(markdown(x) for x in
                         (case["case"], case["status"], "not computed: incomplete declarations/grid", "none",
                          ", ".join(case["reasons"]))) + " |")
        for baseline, check in case["comparisons"].items():
            ratio = check["ratio"]
            rule = "interval contains 1" if check["rule"] == "interval_contains_one" else f"upper <= {check['upper_bound_limit']}"
            rule += "; certified " + json.dumps(check["certificate"]["relations"], sort_keys=True)
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
                  "Analysis identity is a sampled invocation source snapshot with stability rechecks, "
                  "not authentication of loaded code or closure of a pre-load race. "
                  "Arithmetic resource exhaustion, decimal failure, or an unresolved nonzero comparison rejects "
                  "analysis (exit 2) and clears owned campaign outputs; it is not numerical HOLD or PASS.", "",
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


class CampaignNumberToken(str):
    """Distinguish JSON numeric lexemes from quoted strings in a second view."""


def strict_json(raw, *, number_tokens=False):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, f"duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def nonfinite(_):
        raise ValidationError("nonfinite JSON number")

    try:
        options = ({"parse_int": CampaignNumberToken, "parse_float": CampaignNumberToken}
                   if number_tokens else {})
        return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite, **options)
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


# This is a source snapshot taken during this invocation, including private
# runpy loads. It deliberately does not authenticate already-loaded code or
# close a race before this sample. A failed sample is rejected only after the
# campaign's input protections and owned stale-output cleanup have run.
INVOCATION_SOURCE_PATH = Path(__file__).absolute()
INVOCATION_SOURCE_SHA256 = None
INVOCATION_SOURCE_ERROR = None
try:
    INVOCATION_SOURCE_SHA256 = hashlib.sha256(
        read_bounded(INVOCATION_SOURCE_PATH, 1024 * 1024, stable=True)).hexdigest()
except (OSError, ValueError, TypeError, OverflowError) as error:
    INVOCATION_SOURCE_ERROR = str(error)


def campaign_source_guard():
    require(INVOCATION_SOURCE_SHA256 is not None and INVOCATION_SOURCE_ERROR is None,
            "campaign invocation source snapshot unavailable")
    current = hashlib.sha256(read_bounded(INVOCATION_SOURCE_PATH, 1024 * 1024, stable=True)).hexdigest()
    require(current == INVOCATION_SOURCE_SHA256, "campaign invocation source changed")
    return INVOCATION_SOURCE_SHA256


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
            inputs.extend((Path(__file__), INVOCATION_SOURCE_PATH))
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
        if campaign_attempt:
            campaign_source_guard()
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
            analysis_hash = INVOCATION_SOURCE_SHA256
            qualification = summarize_campaign(manifest_bytes, rows, analysis_hash, hashes)
            qualification["input_hashes"] = hashes
            validate_campaign_artifact_associations(qualification, manifest_bytes=manifest_bytes)
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
            if campaign:
                campaign_source_guard()
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
