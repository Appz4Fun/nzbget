# Rust duplicate-family deletion

## Approved outcome and current state

The maintainer approved the proposed Rust purge design on 2026-10-13. The
required result is a Downloads deletion flow with exactly Delete and Cancel.
On confirmed success, the selected download, every associated duplicate,
their owned files on disk, and their queue/history entries are gone. Cancel
starts no purge and sends no mutating RPC. The Rust operation must qualify
faster than behavior-equivalent, equally optimized C++. C++ business logic
actually replaced by the port is removed from production after qualification.
The final candidate needs independent review, explicit final-head Codex
signoff, resolved discussions, and integration into `dupe-article-fallback`.

The source base is `7d3d6412f93cd43452f1b390b4ed705c7691df54`. It includes
toolbar PR #99 and Settings PR #98. Neither PR implements family deletion.
The earlier `GroupDupeDelete` UI patch was withdrawn: that action retains a
duplicate history record and does not gather or erase a duplicate family.
No implementation, correctness result, speed result, or deletion PR exists
for this design yet. This document is the written design review artifact.

## Acceptance contract

1. Toolbar and per-item Delete use the same Rust-owned operation. There is no
   park, retain-history, mark-as-duplicate, or keep-files choice in this flow.
2. Resolve the selected IDs and family identities against one guarded source
   snapshot. Include associated queued, postprocessing, ordinary-history, and
   compact-history entries. Repeated IDs and overlapping selected families
   are deduplicated. Missing or changed seeds fail before mutation.
3. Match existing, directly anchored duplicate identities and verified bindings.
   Do not compute a title/key transitive closure or use similar titles, equal
   sizes, or bare twin labels as deletion authority. Conflicting or ambiguous
   ownership must fail explicitly before cleanup.
4. Prevent affected writers and in-flight donor submissions from recreating
   the family. Observe actual quiescence before deleting payloads or objects.
5. Cover recorded destination/final output, unpack output in owned namespaces,
   intermediate/article/repair state, kept and merged NZB inputs, per-file
   queue state and logs, and scoped search/twin artifacts. Shared queue/temp
   roots are never recursively removed.
6. Preserve unrelated downloads, shared payload references, configured roots,
   unrelated files in shared directories, symlink targets, and other hardlink
   names. A directory may be recursively cleaned only with exclusive ownership
   evidence. Otherwise remove only specifically owned entries.
7. Complete means cleanup outcomes are confirmed, final entry removal is
   durably acknowledged, and late affected callbacks cannot resurrect state.
   Admission, `Stop()`, a void save call, or an empty UI table is insufficient.
8. Partial failures remain explicit. Retain durable intent, ownership inventory,
   and per-action outcomes until recovery or a deliberate retry completes.
   Never report success when directory reads, unlinks, identity checks, or
   persistence failed. A genuinely absent inventoried file is idempotent
   cleanup success; an unknown path or failed read is not evidence of absence.
9. Preserve existing Rust callers and their behavior independently. Validate
   the actual FFI and daemon route, not just an isolated Rust helper.
10. Speed requires native complete-operation evidence against fair C++ controls,
    with all attempts and samples retained. Inconclusive intervals or regression
    are HOLD, and do not permit integration of the replacement.
11. The final reviewed head is locally signed as `xbmc4lyfe`, GitHub verified,
    composed on a fresh default sole parent, and approved by the designated
    integration owner. No production deletion or deployment follows from this
    source task.

## Source constraints that shape the design

`DupeCoordinator::SameNameOrKey` compares nonempty keys case-insensitively;
otherwise it compares names. The relation is not transitive. An unkeyed
same-name entry can connect two different nonempty keys if used as a closure
bridge. The purge works from each selected anchor and owner-approved bindings,
without redesigning the program's general duplicate policy. Byte and locale
comparison semantics must remain consistent with the real caller.

`TwinCheck::Identity` is bound to `fingerprint#posting`. `DupeKind=twin` alone
is not globally authoritative; `DupeSampledOf`, reused numeric IDs, and stale
samples need their actual source identity validated by the fallback owner.

`DupInfo` holds identity/status/hash fields, but no output paths, queued NZB,
or completed-file inventory. Legacy compact rows therefore cannot authorize
guessed disk paths. The new path retains a bounded durable ownership inventory
before future compaction discards full metadata. Existing compact entries
without an authoritative recoverable inventory cause preflight failure for
unprovable cleanup. The operation retains them and explains the missing
ownership evidence; it never declares their historical files removed.
This limitation does not fulfill the full-family outcome for such families.
Unknown legacy ownership requires an independently reviewed authoritative
recovery mechanism or an explicitly accepted unsupported result. Removing a
compact row alone never counts as removing its historical files. Resolving
this gap remains a delivery prerequisite, rather than a passed acceptance case.

Current group deletion drains article workers asynchronously. `Thread::Stop`
sets a flag rather than proving exit. Existing post deletion can move records
to history. Existing history deletion recursively cleans only failed/deleted
destinations; successful output may remain. `DeleteDiskFiles` obeys the
ordinary `NzbCleanupDisk` option and ignores some unlink outcomes. A void
`DownloadQueue::Save` also does not prove durable completion. These primitives
cannot be chained and interpreted as a successful family purge.

Existing Rust `fsdelete` is a live POSIX baseline through C++ syscall callbacks.
Its final-component link checks do not establish safe ancestor traversal or
confinement under directory replacement. It remains independently preserved;
the dedicated purge executor uses a stronger, explicit ownership contract.

## Ownership and source lanes

| Area | Responsibility |
| --- | --- |
| Rust purge engine | Family and ownership planning, bounded owned snapshots, state transitions, action ordering, deduplication, cleanup outcomes, durable intent/recovery policy |
| C++ purge adapter | Concrete daemon locking, object lookup, lifecycle callbacks, existing logging emission, serialization and platform primitives; no duplicate full-purge policy |
| Fallback owner | Shared recovery/matching/pinned-state API writer; targeted TwinCheck, DupeProbe, direct/live repair and discovery-generation interface agreement |
| Queue/history lane | Purge-owned markers, acknowledged save/removal adapters, retention of inventory while ordinary completion is suppressed |
| RPC lane | XML/JSON dispatch and read-only progress status; BinRPC seven-field serialization is excluded |
| WebUI lane | Delete/Cancel confirmation and shared toolbar/per-item invocation; preserve merged toolbar and Settings changes |
| Twin scheduling owner | Every heavy build/test/timing admission and its assigned limits |
| Root integration owner | Qualification acceptance, final reviews and default integration |

Proposed implementation locations are `rust/src/dupepurge.rs`,
`rust/src/purgefs.rs`, and `daemon/queue/DupePurgeCoordinator.{h,cpp}` with
the existing Rust FFI/header/module registration. Existing-file changes are
limited to the required queue, history, lifecycle, persistence and RPC adapters,
plus the deletion UI. Shared recovery C++ edits wait for the fallback owner's
narrow interface agreement. Planning approval is not a worker admission.

## Rust engine and live daemon boundary

One versioned C ABI accepts a bounded snapshot of all relevant ownership
claims, selected seed IDs, validated family bindings, raw name/key/path bytes,
record generations, file IDs, and actual recorded output locations. It returns
an opaque owned Rust plan or a structured preflight error. Borrowed slices
exist only during synchronous planning. A plan surviving unlock/waits owns its
data, and never retains `NzbInfo*`, history pointers, iterators, or callback
path storage. Every owned handle has an explicit destroy operation.

Validate pointer/count consistency, count multiplication, integer conversions,
limits, duplicate IDs, malformed paths, and allocation before mutation. Use
bounded allocation with `try_reserve` for reported allocation failure. The
crate's aborting panic profile is not converted into a fictional recoverable
`catch_unwind` contract. C++ callbacks catch exceptions, record the exception
in their host context, and return an abort status; exceptions do not unwind
through Rust.

The full-purge engine has no C++ production fallback. A build unable to provide
the required Rust boundary must fail explicitly rather than silently expose an
incomplete deletion operation. Equivalent C++ implementations belong only to
reference/qualification fixtures. For each existing C++ business routine
actually migrated, the final source audit identifies its removed body and
Rust replacement symbol. C++ object/serialization/syscall adapters remain
mechanical and are not described as replaced business implementations.

The replacement audit follows these concrete caller boundaries:

| Current boundary | Replacement and disposition |
| --- | --- |
| `Downloads.deleteClick`, `DownloadsUI.deleteConfirm`, and per-item deletion in `webui/downloads.js` | Replace the option selection, `editqueue` group/post chaining, and unconditional success callback with one purge request/status route; remove obsolete dialog controls and associated handlers/locales |
| `QueueEditor::EditGroup` user deletion policy | The new user route bypasses its parking/history/cleanup selection. Rust `dupepurge` owns family selection and lifecycle policy; retain required internal automatic failover actions with source-bound caller evidence |
| `HistoryCoordinator::HistoryDelete` and `DeleteDiskFiles` cleanup policy reached by the replaced user route | Rust `dupepurge`/`purgefs` owns inventory, ordering and checked outcomes for that route; ordinary retention/compaction callers remain explicitly audited and separate |
| `QueueCoordinator::DeleteQueueEntry`, post/URL stop callbacks, and `DiskState` serialization/removal primitives | Keep thin object, stop, serialization and acknowledged platform adapters; move any cleanup planning/result business bodies actually replaced into Rust and remove those C++ bodies |

Before implementation is accepted, a symbol/call-site inventory names every
removed C++ body and its live Rust replacement, and explains each retained
internal caller. Adding a purge engine beside unchanged cleanup business logic
does not alone establish the requested replacement or C++ removal. The exact
removal list is source-reviewed before changing shared lifecycle code.

## Lifecycle and durable operation

The operation phases are `prepared`, `stopping`, `quiescent`, `cleaning`,
`persisting`, `complete`, and `failed`. Status exposes actual phase and error
outcomes; accepting a request never becomes a completion notification.

A caller-generated idempotency token is persisted with the operation before
admission. Repeating the same token and identical request returns the same
operation, including after a lost response or restart; token reuse with changed
inputs fails. Exclusively reserve member IDs, validated family bindings and
overlapping cleanup namespaces. A concurrent overlapping request returns the
existing compatible operation or an explicit conflict, never replaces its
generation or starts a second cleanup. A completed lease can be released for
a later intentional fresh download; retained failed intent keeps its fence.

1. Under the queue guard, capture and validate the complete family and ownership
   snapshot. Reject an incomplete inventory before changing records or files.
2. Write and acknowledge bounded durable intent before affected lifecycle work
   starts. Mark every member purge-owned under the guard using the operation's
   generation. Admission/failover/postprocessing/discovery paths respect that
   generation, including callbacks and jobs already in flight.
3. Request scoped cancellation through the owner-agreed hooks. Release the
   queue guard while workers finish. A bounded service tick polls actual active
   writers and pinned users; timeout produces explicit incomplete state.
4. Revalidate the member and path bindings under the guard after quiescence.
   Capture any worker-produced final output before destroying its source object.
   Durably acknowledge appended inventory and changed bindings before unlink,
   compaction, or object destruction can remove their only source of evidence.
   Suppress ordinary history replacement, retry, automatic donor requeue, and
   deletion-script admission for purge-owned members.
5. Execute the Rust-owned cleanup plan, recording every action's real outcome.
   Persist each action's pending receipt before its mutation and completed
   outcome afterward. Recovery reconciles absence and identity under the fence;
   an old completed receipt never authorizes deleting a substituted new object.
   Do not remove the inventory or logical entries when file cleanup is partial.
6. Acknowledged final persistence excludes all purged entries while retaining
   the in-memory ownership information until publication succeeds. Journal
   recovery bridges partial publication of the daemon's existing queue/history
   files. Only then finalize object removal and the terminal operation record.
7. On startup, validate pending intent and install its generation/admission
   fences before normal workers run. Resume idempotent cleanup/persistence from
   recorded outcomes. Changed bindings or corrupt intent fail closed with an
   explicit retained error, rather than activating stale queue rows.

The shared lifecycle interface must identify the immutable member set and
source binding, begin a scoped lease, request stops, report actual quiescence,
acknowledge exact pending/cache cleanup, and end or retain the lease according
to terminal outcome. It must not substitute global `StopAll/WaitAll` for
targeted cancellation. In-flight Scanner/discovery additions are generation
checked so they cannot recreate the erased family after completion. Unrelated
jobs and editions continue under the existing policies.

Persisted intents and failures remain queryable by token/operation ID after
restart, including timeouts and partial persistence failure. Shutdown can stop
progress but retains durable recovery information and admission fences. A
deliberate retry resumes the same retained operation after revalidation; it
does not silently allocate a second generation or discard prior outcomes.

## Filesystem and inventory rules

Use descriptor-relative no-follow traversal anchored beneath approved roots,
or an equivalent proven platform primitive. Validate every ancestor; never
truncate a path or rely on a string prefix and one `realpath` check. Refuse
empty paths, configured/filesystem roots, traversal components, unsafe aliases,
and changed identities. Explicitly distinguish directory EOF, read errors,
missing entries, links, regular files, and unsupported objects.

Recursion requires a proven exclusive download namespace with checked identity.
Shared or overlapping directories use specifically recorded owned child names.
Do not sweep all `.out.tmp` files in a shared directory. Symlink entries can
be removed without following their targets. Unrelated hardlink names and
outside/shared ownership claims remain intact. Namespace capture and identity
checks must prevent deleting a replacement object during a rename race; any
quarantine/capture recovery step is journaled and must preserve a mismatched
object rather than deleting it.

Descriptor traversal alone cannot atomically compare-and-unlink a mutable
child name. A reviewed capture/quarantine algorithm or enforced namespace
exclusivity is a prerequisite, covering external writers, mount boundaries,
mismatched captures, occupied restoration names, and interrupted restoration.
A pre-unlink inode check alone is prohibited as proof of replacement-object
safety. Platforms without the proven primitive fail as unsupported before
mutation. Capture intent and recovery locations are durable before movement.

Capture actual destination and final locations, not a title-derived
`BuildFinalDirName` guess. Enumerate kept/merged NZB inputs and numeric
queue/article state from validated recorded IDs. Keep queue/temp containers
and other collections' state. Future history compaction retains the inventory
needed for purge independently of compact duplicate-check metadata. Unknown
legacy ownership remains an explicit unsupported preflight result, with no
claim of cleanup and no guessed recursive deletion.

## RPC and WebUI behavior

Use a dedicated mutating family-purge request and a read-only operation-status
request under existing control authentication. Preserve existing internal
automatic delete/failover action meanings; this is the user-confirmed full
deletion path. Existing BinRPC serialization is outside this lane.

Both Downloads entry points pass selected IDs through one confirmation flow.
The confirmation states that the download, its duplicates, their disk files,
and their entries will be removed. It has only Delete and Cancel; closing or
escaping the unconfirmed dialog is Cancel. No help page or alternate deletion
radio choices remain. Use new singular/plural locale keys so existing stale
translations cannot suppress the expanded destructive warning.

Delete starts the validated operation once. Disable duplicate admission while
it is pending, poll read-only status, and notify successful deletion only for
the terminal confirmed result. Failures show the retained phase/error instead
of the ordinary unconditional deleted notification. Cancel before confirmation
sends no mutating RPC and starts no deletion. The already-confirmed operation
is not described as undoable cancellation.

The UI retains the request token before sending Delete and reconnects to its
operation after response loss or page reload. A deliberate retry uses the
same Delete/Cancel confirmation and token after displaying the retained error;
it introduces no alternate deletion mode. Server status is authoritative even
if browser state is missing; expose authenticated lookup of retained requests
for the selected IDs rather than assuming the operation never started.

## Correctness and reachability evidence

Run destructive scenarios only in private loopback fixtures with offline
providers and unrelated sentinels. Verify the actual RPC, queue, Rust ABI,
filesystem, worker and persistence boundaries are reached. Inspect final bytes,
records and acknowledged writes, including restart, rather than trusting a
summarizer or command exit alone.

Required cases cover active/paused queue members; every relevant post stage;
article, direct rename/unpack, live repair, twin/probe and discovery activity;
active/inactive URLs; successful/failed/compact history; repeated IDs and
overlapping seeds; absent/reused/changed IDs; case and non-UTF8 identities;
conflicting-key bridges; stale content bindings; shared/nested outputs;
merged NZB inputs; unrelated sentinels; roots, ancestor/child links and swaps;
hardlinks; malformed/overlong paths; missing files versus failed reads;
unlink/permission/persistence failure; allocation and callback exception;
restart at each phase; response-loss retries, conflicting tokens, overlapping clients, shutdown;
new output after intent, namespace capture/restore failures and mount points;
and concurrent completion/append/discovery. Cancel and
dialog close must leave files and entries unchanged with zero mutating calls.

Validate preserved existing Rust filesystem callers with their real wrappers,
callbacks, error text and emission behavior. A C++ sanitizer harness linked to
an ordinary Rust archive does not establish Rust sanitizer coverage. State
native platform coverage and unsupported platform evidence explicitly.

## Performance comparison and stopping rule

There is no historical full-family deletion at this base. An incomplete
historical single-item delete cannot be timed as an equivalent full purge.
Retain and measure actual original C++ boundaries where migrated. Also build
a clearly labeled new full-contract C++ reference assembled from production
rules, and an equally optimized C++ full-contract implementation with every
indexing, batching, ownership and traversal improvement used by Rust.

Compare complete live caller work: snapshot creation, relevant identity/cache
and crypto work, allocations/copies, ABI, callbacks, scoped worker drain,
real offline filesystem cleanup, logging and acknowledged persistence. Use
the same inputs and observable behavior across variants. Helper-only matching
speed is diagnostic and cannot satisfy the full-operation speed requirement.

Existing Rust filesystem callers are real preservation baselines and remain
independent. A genuinely new planner/descriptor boundary can be declared
`not_applicable` only with source-bound independent review. Do not relabel a
new full purge as an existing Rust operation. Any touched existing Rust caller
requires its declared current baseline and complete-caller preservation check.

Before timing, freeze source and build lineage, compiler flags, actual archives,
caller/fixture hashes, route-hit checks, process/build hierarchy, balanced
variant/round keys, exact integer elapsed-duration floors, unchanged controls,
effect bounds, analyzer, storage/runtime limits and finite stopping rule in
the repository benchmark schema. Preserve every calibration and unsuccessful
attempt; a changed method or optimization gets a new identified plan.

Each changed compared caller requires the paired Rust/C++ ratio's upper
confidence bound below 1 against the fair optimized comparator. Applicable
Rust preservation requires an upper bound at most 1. Control drift, failure,
under-floor or invalid rows, missing evidence, and an interval admitting
regression produce HOLD. Retain raw rows; do not filter, replay, adaptively
replace samples, or pool nested measurements as independent executions.
Inspect the qualification artifact itself before accepting any speed claim.

## Execution, reviews and integration

Only Twin admits heavy work. Honor the existing Root priority queue and the
assigned NVMe destination, storage budget, admission/payload timeout and job
cap. Fixed worker-global locks are `/tmp/i7-heavy.lock` exclusive followed by
`/tmp/nzbget-rust-benchmark.lock` shared for builds/tests. Prebuilt bounded
timing holds only the benchmark lock exclusively and releases it after each
process. Per-job temporary/output folders cannot change lock identity. No
stage exceeds the assigned cap or three jobs.

Use isolated Cargo targets or prove archive recompilation after discarding
preserved source timestamps. Keep failed artifacts and raw output. Source
inspection and reference tests do not establish native speed or qualification.

Root integrates only the fresh signed canonical composition after independent
whole-change review and exact-head GitHub Codex signoff. Fix actionable issues,
answer and resolve every discussion, and request a supported fresh review
until Codex acknowledges the actual final head as clean. A resolved thread,
an older head's approval, or a synthetic review-environment commit is not that
signoff. Verify the canonical GitHub object and signature directly. Preserve
signed history before a source-equivalent squash; do not use a GitHub-generated
merge/squash object. Record generic pending CI and qualification statuses
accurately, and do not release any separate backend deployment hold.
