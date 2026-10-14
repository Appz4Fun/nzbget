# Assessing supplied Rust coverage evidence

`scripts/coverage/assess.py` is an offline assessor. It reads supplied LLVM JSON,
checks declared source bytes and file/function mappings, and emits a separate
coverage report. It performs no collection, compilation, tests, installation,
network requests, publication or deployment. It does not change the existing
paired benchmark qualification or shared reports.

## Scope and inputs

Create a scope JSON matching
`scripts/coverage/schema/scope.schema.json`. Required fields are:

| Field | Meaning |
| --- | --- |
| `schema_version`, `scope_id` | Version 1 and the frozen scope identifier |
| `source_files` | Every expected replacement Rust file with path/hash, original C++ metadata, production symbols, activation predicate and reviewed applicability relationship |
| `caller_files` | The C++ caller files, with the same path/hash contract |
| `capture` | Mode, production/test configuration assertions, successful producer completion, and export/binary/profile SHA256 identities |
| `required_boundaries` | Unique IDs mapping exact Rust and C++ function names from the export to their declared source files |
| `exclusions` | Explicit nonproduction exclusions with source hash, category, reason and review-receipt hash; an expected replacement/caller file cannot be excluded |

Each replacement additionally requires `cpp_origin` (path, original symbols,
source SHA256 and applicability `baseline_metadata_only`), `production_symbols`
(the complete expected Rust symbol names), `activation_predicate` and
`applicability`. The latter contains `variant`, `kind` (`direct_boundary` or
`helper`), nonempty `boundary_ids`, `review_sha256` and `source_sha256`; the last
must equal the replacement source digest. Every referenced boundary must exist
in the production caller inventory. Direct files must map their own active
boundary; helper files need a declared reviewed relationship to an active
boundary. Each production symbol must have an unambiguous export mapping in both production
and unit modes, even if its count is zero. Zero nonboundary functions are uncovered; only required
active boundaries demand positive counts. These declarations and review hashes
remain unverified, and the tool does not parse Rust to infer hidden helpers.

`capture.variant` is `rust_candidate` or `rust_current`, and each replacement's
applicability variant must match it. Original C++ implementations are separate
baseline metadata and may be retired or inactive in a Rust candidate. Their
hashes are declared identities, not checked bytes in this source root. The
surviving external C++ caller wrapper is specified separately in `caller_files`
and `required_boundaries`; its counter is not an original-implementation counter.
No simultaneous old-C++/Rust implementation execution is required by this tool.

`capture.mode` is `production_caller` or `unit_diagnostic`. Other capture fields
are `production_only`, `test_cfg_enabled`, `completion` (state `EXITED`, integer
exit code 0), `export_sha256`, `binary_sha256` and `profile_sha256`.
The export digest is checked against actual input bytes. Binary/profile identities
and producer completion are supplied assertions; the assessor does not read the
binary/profile or authenticate their producer. An asserted review hash does not
prove that review happened or covered this scope.

A boundary contains `id`, `rust_file`, `rust_function`, `caller_file` and
`caller_function`. Function names must match the raw LLVM export records exactly;
the tool does not guess mangled/demangled matches. The matched records must each
have a positive integer execution count in production caller mode. The Rust and
caller sides must come from distinct original function records; their zero-based
`rust_record_id` and `caller_record_id` identify records within the one dataset. A
legitimate multi-file function record is supported, but its counter cannot serve
both sides of one boundary. These IDs are not build/profile authentication. Missing or
ambiguous records produce HOLD. Counters are observations in submitted data;
they do not authenticate execution or causal dispatch between those functions.

The assessor supports LLVM JSON export type `llvm.coverage.json.export`, versions
`2.0.1` and `3.1.0`, with one `data` dataset, file line summaries and full function records.
Summary-only exports cannot establish boundary counter presence. It refuses
multiple datasets rather than inventing a merge/instantiation counting rule.
Expected mappings must exist even when the linker omitted a function. A missing
mapping is unknown/HOLD, not 100% covered.

Paths must be canonical relative paths without empty, dot, parent, backslash or
control-character components or UTF-16 surrogate code points. Invalid Unicode,
including surrogateescaped filesystem bytes, is rejected before filesystem access.
Drive-absolute paths such as `C:/Users/...` are not relative scope paths. Export filenames may alternatively use the exact
absolute source-root prefix. Other POSIX or forward-slash Windows absolute export paths remain unexpected.
Their internal identities are tagged and cannot match a scope path, even if a
caller is deliberately named like the public label. Derived metadata uses
`EXTERNAL_ABSOLUTE_SHA256:<digest>` labels; raw input bytes remain private and
unchanged. Unsupported backslash export paths produce HOLD. This is parsing of
supplied names, not native Windows execution. All filesystem inputs and output ancestors are traversed
through descriptors with `O_NOFOLLOW`. Use canonical real paths: for example,
macOS `/var` may be a symlink to `/private/var`. Symlinks are rejected, including
ancestors; source/input hardlink aliases are rejected too.

## Production and unit views

The denominator is LLVM's **instrumentable lines**, using each expected whole
Rust file's line summary. It is not physical source LOC, number of tests, region
count or a lexical Rust/C++ ratio. Every file is reported separately. Unexpected
files remain visible and do not increase the aggregate or hide a low file.

A production caller view requires assertions `production_only=true` and
`test_cfg_enabled=false`. Independently review the actual source, configuration,
commands, instrumented normal Rust library archive, C++ caller objects,
executable and raw profiles to confirm that assertion. A normal library build
without `cfg(test)` leaves inline test modules outside compiled production
mappings; do not subtract guessed test line ranges from a unit-test summary.

Unit mode still requires every declared Rust production symbol mapping, allowing
zero counts and absent caller counters. It preserves parsed metrics for diagnostics but cannot satisfy the
production target and never reports caller reach. Keep its profiles separate
from external caller profiles. Partial-file/function-range scope is unsupported;
it needs a separately reviewed denominator rule. Exclusions cannot remove
expected production code. Generated production code must be included in the
replacement scope; it cannot be excluded simply because it is generated.
A reviewed inventory must establish completeness and active configuration.
The assessor cannot determine that the author declared every migrated path.

## Offline invocation and outputs

Use an existing canonical source root and a fresh output directory whose parent
already exists:

```sh
python3 -I scripts/coverage/assess.py \
  --scope /ABSOLUTE/PRIVATE/scope.json \
  --export /ABSOLUTE/PRIVATE/llvm-export.json \
  --source-root /ABSOLUTE/CANONICAL/source \
  --output-dir /ABSOLUTE/PRIVATE/new-assessment
```

Existing output directories/files are refused without modifying them. The tool
never deletes or replaces an earlier attempt. Complete bounded input bytes are
copied unchanged to `scope.raw` and `export.raw`; every successfully read replacement, caller and excluded source is copied
unchanged to an opaque `source-NNNN.raw` file, with its observed digest and path
in an exclusive receipt before the declared hash is compared. Mismatching bytes
and hashes remain retained. `source-custody.json` records all completed and
unavailable captures. Source filenames never determine evidence filenames. Reads reject nonregular inputs, incomplete/changed reads and
aliases. Exhausting the aggregate source budget produces HOLD, preserving earlier snapshots and an unavailable-source receipt. Missing or oversized inputs cannot be captured in full and remain a
reported limitation rather than fabricated raw data.

Bounds: 8 MiB per control JSON, 2 MiB per source file, **32 MiB aggregate raw source snapshots**, 4,096 items per array,
4,096 characters per label and integer counts between 0 and 2^63-1. JSON duplicate
keys, nonfinite values, booleans/floats as counts, malformed/unknown schemas,
duplicate file/function identities, missing sources, failed captures and zero
denominators produce HOLD. A too-large or incompatible packet requires a new
reviewed scope/method; do not filter it to force acceptance.

Absolute-looking strings in derived declarations/function labels are also hashed,
including malformed HOLD mapping/exclusion metadata; invalid declared scope paths
retain their row with a NULL path. Invalid surrogate text uses an
`INVALID_TEXT_SHA256:<digest>` label in derived metadata. Exact matching always
uses private original strings. This is path-label redaction, not a general secret
scrubber for arbitrary prose or source bytes. Filesystem failures have a stable
errno reason in derived metadata, with the original failure message retained in
private `failure.raw`. Raw scope/export/source receipts remain private evidence.

Outputs are `coverage-assessment.json` and `coverage-report.md`. Exit 0 means
**VALID_STRUCTURE**, including valid low coverage or a unit diagnostic. Exit 2
means HOLD, unsafe/unavailable output, or output failure. A fresh directory
retains any partial files on output failure; inspect stderr and the actual
assessment, not only the exit code. Create command metadata/raw stdout/stderr
before invoking the assessor and record completion before interpreting it.
If creating or syncing `failure.raw` itself fails, the assessor closes its output
directory descriptor, returns exit 2 and retains the partial attempt. A complete
assessment cannot be promised when its evidence sink fails; this is an output
failure, not a valid coverage report.

`execution_verified` is always false; `lineage_status` and
`scope_completeness_review` remain UNVERIFIED. Even positive caller/Rust counters
report only `COUNTERS_PRESENT_REVIEW_REQUIRED`. A unit view reports UNKNOWN.
These outputs cannot be promoted to authenticated production coverage by
asserted metadata. Independent exact-source/build/profile/route review is a
separate responsibility. An extracted caller harness must be labelled as such;
it does not establish live-daemon coverage. A direct ABI test cannot establish
that the enabled production C++ dispatch reaches the same Rust boundary.

## Advisory target and independent speed gate

The strictly-above-70% target uses exact integer arithmetic per expected file:
`100 * covered_lines > 70 * line_count`. Exactly 70% is LOW. Rounded percentages
and a high weighted aggregate never override a low individual file. The target
is advisory, as requested; it is not a new automatic integration/release gate.

A malformed/failed packet reports NOT_MEASURED with an unknown aggregate. Safe scope inventory is extracted immediately after readable scope capture, before export reads or source-root checks. Missing, symlinked, nonregular, oversized or aliased exports retain that untrusted inventory. A malformed scope never fabricates declarations and does not prevent readable export bytes being captured before rejection. All safely parsed declared expected rows remain visible with UNKNOWN status and NULL metrics; caller/exclusion inventory, missing mapping identities, observed source custody and reasons remain retained. No completed low or invalid row is filtered away. Valid low results retain all counts. Unit results retain
counts but always report the production target as NOT_MEASURED. Any displayed
counts remain **parsed, unverified metrics**, even when the structure is valid.

`speed_qualification` is always NOT_ASSESSED. Coverage builds must remain separate
from uninstrumented native timing. This tool proves neither faster Rust, C++
retirement, integration, deployment, branch coverage nor cross-platform execution.
Existing complete-caller C++/optimized-C++/Rust comparisons and performance holds
remain in force.

## Future collection and validation

Collection is outside this tool's scope. Coordinate native work with the sole
worker owner, fixed global locks and bounded jobs/admission. Use isolated targets
and preserve held archives; do not clean/reuse another owner's target. Observe
Rust's actual pinned toolchain/overrides and compatible LLVM versions before
execution. The existing admitted runner deliberately clears arbitrary inherited
instrumentation variables; a reviewed collector must set explicit flags inside
its admitted child.

Rust is consumed as a static library by the C++ executable. A Cargo unit coverage
command or `--include-ffi` does not automatically instrument the external CMake
caller. Capture actual instrumented Rust archive and C++ executable mappings,
raw per-process profiles, successful terminal outcomes and all failure attempts.
No collection or tool installation is authorized merely by reading this guide.

Pure synthetic assessor regression tests:

```sh
python3 -I -m unittest discover -s scripts/coverage/tests -v
```

The producer-shaped synthetic fixture follows the official LLVM20.1.8 and
LLVM22.1.0 JSON exporter source for file summaries, segments, regions, functions,
branches, MC/DC and totals. The assessor uses only the declared line/function
fields, not branch/MC/DC semantics. It records the original export version and
never rewrites it. Synthetic format acceptance does not establish compatibility
with the repository's actual pinned Rust compiler or installed LLVM tools;
those producer versions remain unobserved until admitted native work.

These tests establish parser/output behavior only. They contain synthetic source,
counts and identities, and are not measured NZBGet production coverage.

## Official references

- [cargo-llvm-cov v0.9.1: external tests and FFI prerequisites](https://github.com/taiki-e/cargo-llvm-cov/blob/v0.9.1/README.md)
- [rustc instrumentation and matching LLVM tooling](https://doc.rust-lang.org/rustc/instrument-coverage.html)
- [Clang source coverage](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html)
- [LLVM JSON export and object identities](https://llvm.org/docs/CommandGuide/llvm-cov.html#export-command)

- [LLVM20.1.8 JSON exporter](https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-20.1.8/llvm/tools/llvm-cov/CoverageExporterJson.cpp)
- [LLVM22.1.0 JSON exporter](https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-22.1.0/llvm/tools/llvm-cov/CoverageExporterJson.cpp)
