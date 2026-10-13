# Duplicate-family purge source contract, version 1 proposal

## Status and authority

This document and [source-map.json](../rust/tests/dupepurge/source-map.json)
are Task 1's source-bound declaration proposal. **No purge API is wired.**
The controller reported on 2026-10-13 that Root and the fallback owner each
explicitly SOURCE-ONLY ACKed the exact declarations/schema in signed commit
`644106564387539f6ccaeba65b6b989f6f4eb290`. Root required the barrier-identity
interpretation below to be documented before wiring. These ACKs apply to that
immutable source contract; this clarification and custody correction are
recorded separately for the controller's fresh task review. They establish no
implemented behavior, legacy ownership resolution, runtime validation,
qualification, integration or deployment.

The approved [design](superpowers/specs/2026-10-13-duplicate-family-purge-design.md)
is commit `345097648e26f4758b1b9aad69261dc30dfa621f`. Inspected source is
`d4842b182efdc13cde1031d6ac8f0b5ba165effc`. On 2026-10-13 the authenticated
remote HEAD and fetched `dupe-article-fallback` were both
`7d3d6412f93cd43452f1b390b4ed705c7691df54`. Runtime sources are unchanged
between that base and the inspected design/plan commits. The source map
records bounded file hashes, exact source anchors, baseline applicability
and required registration/publication/release changes. It is a finite source
inventory, not proof that a future executable reaches every boundary.

Confirmed success means the selected downloads, every directly associated
family member, all their proven owned files, and queue/history entries are
removed with acknowledged persistence. Safe preflight rejection is not that
outcome. Cancel before confirmation sends no mutation. Full-goal delivery
remains held for the legacy ownership GAP described below.

## Bounded identity declarations

These are semantic declarations to be translated into reviewed C++ records
and a version-1 flat C ABI; they are not present in current headers:

```text
RequestToken = [u8;16]
Generation = u64                         // zero invalid
MemberBinding {
  collection_id: i32,
  file_id: Option<i32>,
  incarnation: u64,
  posting_source: Vec<u8>
}
PurgeToken {
  request: RequestToken,
  generation: Generation,
  members: Vec<MemberBinding>
}
```

Collection/file IDs stay signed `i32`; reject nonpositive record IDs and
out-of-range conversions instead of reinterpreting them as unsigned.
A collection binding has no file ID and carries its collection incarnation.
A file binding carries its own file incarnation and MUST reference an included
collection binding through an independently validated parent-membership table.
The table records both incarnations and source bindings. Reparent/merge/split
cannot silently reuse an old file binding. This explicit interpretation of the
single `incarnation` field is part of the owner declaration review.

Create a **new daemon-persisted monotonic allocator** for purge generations,
separate from `NzbInfo::m_idGen`, `FileInfo::m_idGen`, and `DiskState`'s current
integer ID floor. Create an independently persisted monotonic incarnation
allocator for admitted collection/file identities. Zero is never assigned;
allocation at an exhausted `UINT64_MAX` boundary fails before admission, with
no wrap, time-based substitute or reset. Conservatively reserve `UINT64_MAX`
as exhaustion: no successful allocation publishes that value. Persist and
acknowledge the new high-water mark before exposing the allocated identity;
crash may consume an unused value but cannot reuse one. Corrupt/missing
allocator state after prior adoption blocks admission pending reviewed
recovery; deriving a counter from just currently live records is insufficient.

New records receive new incarnations before worker admission. Valid versioned
loads restore their persisted incarnation; startup does not reassign them.
For pre-adoption full records, assign and persist an incarnation plus validated
source/ownership binding before exposing the migrated row. This creates no
historical ownership evidence. Compact history keeps the original collection
incarnation when a full record becomes `hkDup`; absent legacy ownership stays
unknown. A fresh download reusing an integer ID receives a new incarnation.
Startup loads allocator, bindings and retained intents and installs all fences
before normal queue/URL/post/Scanner/discovery/script admission. Recovery
cross-checks counters, tokens, rows and inventories and fails closed on conflict.

`posting_source` is nonempty bounded immutable opaque identity material with
an owner-defined version and an independently validated binding to the actual
retained posting/source. Hash equality or an untrusted supplied label cannot
establish that binding. No raw provider credentials enter this record. Source
custody/verification receipts retain the source identity and validation method;
replacing source bytes invalidates the binding even if integer IDs match.
`TwinCheck::Identity` currently returns `fingerprint#posting`, and `Posting`
uses `GetFullContentHash`; this is a current matching input, not by itself the
independent immutable authority required here. `DupeKind=twin`,
`DupeSampledOf`, content hash, size and NZB filenames alone cannot authorize
family/path deletion. Missing validation is an explicit preflight error.

Limits are 4,096 seeds, 65,536 member bindings, 1,000,000 inventory entries,
64 MiB total snapshot or frame payload, 1,023 bytes per path and 65,535 bytes
per identity. Parent/claim/delta/ticket records and bytes count against the
bounded payload; do not allow an unbounded secondary array. Validate total
sizes and checked arithmetic before allocation/mutation. Reject embedded NUL
in names, keys, identity/path text fields, truncation, unsupported objects,
invalid encodings of structured fields, duplicate/conflicting records and
allocation failure. Non-UTF8 path/name bytes remain bytes. Opaque request and
digest arrays are binary and may contain zero bytes.

The ABI uses explicit `uint32_t` version, sizes/counts, signed `int32_t` IDs,
`uint64_t` generation/incarnation and a `has_file` tag (0/1, file ID zero when
absent), plus counted byte slices. No Rust `Vec`, C++ pointer to a daemon
object, enum with unspecified layout or retained borrowed callback storage
crosses the ABI. Snapshot ownership transfers to an opaque Rust plan with an
explicit destroy operation. Fallible bounded allocations report failure;
aborting panic does not become a recoverable exception contract. C++ catches
exceptions before crossing the ABI and returns a retained host failure.

## Anchored family selection and inventory

`DupeCoordinator::SameNameOrKey` chooses nonempty keys when **both** keys are
nonempty; otherwise it compares names. It calls `strcasecmp`, or the Windows
`stricmp` mapping. `nzbget.cpp` calls `setlocale(LC_CTYPE, "")`, so do not replace
this with Unicode case folding or unconditional ASCII lowercase. Capture raw
bytes and direct seed-to-candidate comparison outcomes under the real daemon
comparison environment; snapshot the locale/platform comparison provenance.
The C++ comparator is a mechanical callback; Rust owns family policy. Reject
changed comparison context before revalidation. Retain non-UTF8 and locale
fixtures for eventual caller tests.

Match each selected anchor directly and union those results after validating
bindings. Never traverse matches as a title/key transitive closure: an unkeyed
same-name row can bridge two distinct nonempty keys. Repeated selected IDs and
overlapping seeds deduplicate; absent/reused/changed seeds fail. Snapshot
queued, post, ordinary history and compact history plus all outside ownership
claims under the queue guard. Discovery ancestry does not replace validated
posting membership. Ambiguous family/source/path claims reject before cleanup.

The inventory contains bounded stable entry IDs, exact member/parent binding,
validated root and relative entry bytes, entry kind, actual object identity,
namespace/ancestor/mount evidence, outside claims, ownership provenance and
revision. Capture recorded destination AND final output, completed old/current
names, unpack/repair outputs, `FileInfo` output/hardlink names, article result
and temp files, queue file state and collection log, and every kept/merged
queued NZB input. `GetQueuedFilename` currently encodes merged inputs separated
by `|`; a delimiter-ambiguous legacy value needs independently validated
entries, not guessed splitting. Numeric `<file-id>`, `<file-id>s`, `<file-id>c`
queue names and collection log names are admitted only after parent/incarnation
validation beneath the captured queue root. No private path is supplied by
this document or source map.

Actual exclusive namespace proof permits recursion. Shared/nested roots
require exact owned child entries and outside-claim checks. Configured roots,
queue/temp containers, unrelated files/hardlink names and symlink targets stay
intact. Unknown script-created output or unrecorded unpack/repair output is
missing inventory, not permission to omit files. Future workers must retain
all such outputs through acknowledged inventory deltas.

Every ancestor is traversed descriptor-relatively without following links.
Directory EOF, read failure, unsupported object, absence and changed identity
are different outcomes. Namespace capture/quarantine intent and recovery
locations must be durable before movement. A checked inode followed by unlink
is insufficient against replacement races. The reviewed platform algorithm
must preserve mismatched captures, handle occupied restoration names, external
writers and mount boundaries, and recover interrupted restoration. Unsupported
platforms reject before mutation. These mechanics remain future implementation
and review work, not a claim of present filesystem safety.

## Proposed host declarations and acknowledgment schema

Keep these four shared owner entry points exactly aligned across the lanes:

```text
FenceAndCancel(const PurgeToken&) -> FenceReply
PollPurgeQuiescence(const PurgeToken&) -> DrainReply
RemovePurgeArtifacts(const PurgeToken&) -> CleanupReply
ReleasePurgeFence(const PurgeToken&) -> ReleaseReply
```

The following supporting operations specify responsibilities and proposed
names for joint review. None permits an implementation lane to invent a
parallel registry or wire an alternative API:

```text
ReservePurge(snapshot, request) -> Reservation | Existing | Conflict | Error
PersistPurgeIntent(reservation, inventory) -> IntentAck | Error
RegisterPurgeWork(bindings, kind, parent_ticket?) -> WorkTicket | Fenced | Error
BeginPurgePublication(ticket, delta) -> PublicationTicket | Fenced | Error
AppendPurgeInventory(token, delta) -> InventoryAck | Error
FinishPurgeWork(ticket, final_delta_ack, outcome) -> ReleaseReceipt | Error
PersistPurgeRemoval(token, action_receipts, artifact_ack) -> PersistenceAck | Error
```

The supporting records have this proposed semantic shape. Counted vectors
below are owned internally; the ABI flattens them using the bounds above.
All integer fields are fixed-width and reserved fields must be zero.

```text
SourceValidation {
  version: u32, validator_version: u32,
  source_record_id: [u8;32], source_bytes_digest: [u8;32],
  binding: MemberBinding, parent_collection: Option<MemberBinding>,
  custody_receipt_id: [u8;32]
}
WorkTicket {
  id: u64, kind: u32, admission_epoch: u64,
  dependencies: Vec<MemberBinding>, parent_id: Option<u64>
}
OutputDelta {
  producer_ticket: u64, sequence: u64, prior_inventory_revision: u64,
  changes: Vec<InventoryChange>, final_for_producer: bool
}
InventoryChange {
  entry_id: u64, member: MemberBinding,
  action: add | rename | retire_binding,
  before: Option<OwnedEntry>, after: Option<OwnedEntry>,
  ownership_receipt_id: [u8;32]
}
OwnedEntry {
  root_id: u64, relative_path: Vec<u8>, kind: u32,
  object_identity: Vec<u8>, namespace_proof_id: [u8;32],
  outside_claim_ids: Vec<u64>
}
AckIdentity {
  version: u32, token: PurgeToken, state_revision: u64,
  receipt_sequence: u64, payload_digest: [u8;32]
}
DrainCounts { queued: u64, active: u64, pinned: u64,
              publication: u64, unacknowledged_deltas: u64 }
QuiescedAck { identity: AckIdentity, inventory_revision: u64,
              owner_barriers: Vec<OwnerBarrier> }
OwnerBarrier { owner_kind: u32, barrier_revision: u64, counts: DrainCounts }
```

The purge coordinator issues `OwnerBarrier.barrier_revision`. Together with
`QuiescedAck.identity.token.request` and `.generation`, it identifies the
**same coordinator-issued purge/fence barrier** that every owner must echo.
The coordinator retains that expected identity in its durable purge/fence
state before dispatching the fence; owners cannot allocate, advance or replace
it with their own counters. `QuiescedAck` validates every required owner's
barrier against this retained identity, with each required owner present once.
A stale, missing, mixed or differently issued barrier cannot acknowledge drain.
If the coordinator supersedes a barrier, earlier acknowledgments no longer
satisfy the new barrier, even within the same operation.

Owner-local counters may be diagnostic observations and may differ across
owners. Equality of those counters is neither required nor sufficient for
`QuiescedAck`; they never substitute for the coordinator's barrier identity.
`AckIdentity.state_revision` continues to describe the operation's state
revision and is not an owner-local counter or an implicit replacement barrier.
This is Root's required interpretation of the existing records, not an added
entry point or a claim that the barrier is implemented.

`OwnedEntry.object_identity` is a versioned bounded platform descriptor
identity, never just an unvalidated inode string; its root/namespace proof and
outside claim IDs resolve to retained snapshot records. A rename retains both
bindings and the actual checked move outcome. `retire_binding` records loss
of the old binding after a proven outcome, not permission to forget an unknown
file. Source/custody/ownership receipt IDs reference retained validated records;
a digest of invented input cannot satisfy a receipt. New work-ticket IDs,
epochs, delta sequences and receipt sequences reject overflow before state
change. Their uniqueness lives at least as long as any associated callback or
retained recovery record; restart invalidates process tickets and reconstructs
durable producer obligations before any new ticket can be confused with them.

Canonical token members sort by signed collection ID, absent/present file ID,
signed file ID, incarnation and counted source bytes; duplicates with different
bindings conflict. Persist canonical request bytes (version, sorted unique
selected seed bindings and fixed policy) separately from the mutable inventory.
An identical retry looks up its retained token before taking a new snapshot;
it does not resolve reused numeric IDs into a fresh operation. Any framing
change requires a new schema version and reviewed load behavior.

`RegisterPurgeWork` is a proposed universal lifecycle registration name: it
registers ordinary affected work before any purge exists, not just purge work.
`WorkTicket` owns a unique never-reused ticket ID, work kind, exact validated
member/dependency bindings and parent ticket, and the admission/reservation
epoch. Its dependencies include every donor and publication target, even if
outside the deletion member set. Adding a dependency requires fresh admission
before its first use. Existing tickets are enrolled into the exact purge
lease when any dependency overlaps. Ticket/subticket creation is bounded;
launch failure produces a release receipt instead of a leaked count.

All acknowledgments contain schema version, exact request/generation and
canonical member-set identity, operation state revision, receipt sequence,
result/error and the acknowledged payload identity. Full retained token bytes
are authoritative; a digest is an integrity/index aid, not a replacement for
binding validation. Reject stale, duplicate-with-different-content,
out-of-order and cross-incarnation acknowledgments. An idempotent exact replay
returns the already retained receipt. Error/status payloads are bounded and
private details are excluded from public exports.

- `IntentAck`: durable request bytes, exclusive reservations, immutable token,
  initial inventory and generation allocation acknowledgment. No cancellation
  or destructive lifecycle transition precedes this ACK.
- `FenceReply`: `accepted`, `already_fenced`, `conflict`, or `error`, with
  nonblocking per-work-kind stop dispositions. `no_work` differs from
  `cancel_requested`; `unsupported` or stop failure remains an error. Neither
  accepted cancellation nor a detached worker pointer is a drain result.
- `DrainReply`: `pending`, exact-token `QuiescedAck`, or `error`. Pending counts
  distinguish queued, active, pinned and publication uses by owner/kind, plus
  unacknowledged output deltas. ACK requires all zero with admission still
  fenced and all required owners echoing the same coordinator-issued
  purge/fence barrier identity defined above. Owner-local counter equality
  cannot satisfy this condition. Counts are evidence from registrations, not
  estimates from flags or aggregate threads.
- `InventoryAck`: monotonic inventory revision, covered delta sequence,
  exact member/entry changes and durable receipt. A worker's final empty delta
  is explicit. A path/rename binding supersession preserves old history.
- `CleanupReply`: `pending`, exact-token `CleanupAck`, or `error`. Enumerate
  each scoped cache/pending artifact and actual absent/removed/failed outcome,
  plus acknowledged persistence for retained shared stores. Drain does not
  imply cleanup, and cleanup cannot authorize a later uncounted publisher.
- `PersistenceAck`: all action outcomes and scoped cleanup ACK are retained;
  queue/history publication excludes the family with checked writes and
  recovery receipts. In-memory source objects remain until this acknowledgment.
- `ReleaseReply`: retained failure/pending fence, or exact terminal release
  acknowledged after `complete` is durable. Release of a successful operation
  permits a new intentional download with fresh incarnation; stale worker
  tickets remain invalid forever. Timeout/error never silently releases a fence.

## Lock contract and admission order

Use the queue guard as the single linearization point for the proposed
reservation/binding/admission registry. Do not introduce a registry protected
by an unrelated lock with a check-then-register race. Register a ticket under
that guard **before** enqueueing into an owner registry or dropping the guard
to schedule work. The queued ticket counts while local vectors, handoffs,
thread startup and provider waits occur. Transition queued to active/pinned/
publication without an uncounted interval; transfer rather than erase/re-add.
Owner-local work handles use lifetime-safe cancel references, never raw
pointers copied beyond their owning lock.

1. Under the queue guard, validate snapshot, identity and complete inventory;
   atomically reserve member bindings, family/source bindings and overlapping
   cleanup namespaces. Same request plus identical canonical request bytes
   returns the retained operation; changed inputs conflict. A compatible
   overlap may return the existing operation without replacing its token;
   incompatible overlap conflicts. Hold non-destructive provisional admission
   barriers and snapshot custody while writing intent outside the guard.
2. Persist allocator/intent and revalidate snapshot/revision under the guard
   before publishing purge-owned markers. Admission during this interval sees
   the provisional reservation and cannot start affected work or erase its
   metadata. An intent write failure with no durable intent unwinds only the
   provisional reservation after reconciliation; uncertain persistence remains
   held. This is not cancellation or permission for cleanup before IntentAck.
3. Drop the queue guard. Invoke `FenceAndCancel` for each owner using immutable
   token/receipt state. Each owner snapshots its scoped cancel handles under
   its own lock, then requests nonblocking cancellation without network/provider
   or cross-owner waits. Cancellation must cover queued local handoffs as well
   as active handles. Never acquire queue/provider/fallback locks while holding
   another such lock for a wait; coordinator calls hold no other owner lock.
4. Poll through bounded service ticks outside queue, provider, fallback, Scanner,
   article-cache and network locks. No global `StopAll/WaitAll`, thread join,
   condition wait, `FileBusy` sleep, provider I/O, fsync or journal wait is
   nested in the queue guard or another owner's lock. Current lock-nesting
   behavior is not permission to reuse it for the new route.
5. A finishing worker keeps its ticket/pin and source custody. Capture its final
   output changes under the appropriate short guard; release the guard, append
   the durable delta, then generation-check under the guard and attach the ACK.
   Only afterward may it publish permitted cancellation/final-output state,
   close final publication use, release pins and destroy the source object.
   If acknowledgment fails, retain custody/error and report pending/failed drain.
   Cancellation does not skip final partial outputs. Admission of a normal
   late result is fenced; retaining its owned output evidence is still required.
6. After real drain ACK, revalidate members/paths and all acknowledged deltas.
   Perform separate scoped artifact cleanup under the same fence, with durable
   pending/completed receipts. Rust chooses filesystem cleanup and ordering;
   mechanical host adapters report actual results. Partial cleanup keeps
   logical records, ownership inventory and fences. No source object is erased
   merely because the active worker pointer has been cleared.
7. Acknowledge final multi-file persistence, finalize logical object removal,
   durably record `complete`, then release reservation. Restart replays receipts
   before admission. Old completed receipts cannot delete substituted objects.
   Shutdown stops progress with durable failed/pending custody, never fake success.

Phases are exactly `prepared`, `stopping`, `quiescent`, `cleaning`, `persisting`,
`complete`, `failed`. Pending/timeout is explicit retained incomplete state.
The service tick is bounded; no admission cap or worker runtime is invented
here. Only the scheduling owner authorizes native execution.

## Required real boundaries

The source map gives exact anchors and registration, publication, release,
artifact and owning-lane obligations for each group. The following hazards
explain why each category is necessary:

| Real path | Ticket and acknowledgment obligation |
| --- | --- |
| Queue/article downloader and `ArticleWriter` | Register before `StartArticleDownload`; retain target/donor dependencies through `ArticleCompleted`, output publication, cache and `DeleteDownloader` callbacks. |
| `ArticleCache::CheckFlush`/`FlushCache` | Register `m_fileInfo` pin before leaving queue guard; active article count zero does not exclude a cache writer. `DeleteFileInfo`'s current busy wait cannot implement this purge drain. |
| Fallback source pin/cache | `PinSources`/`FinishPin` installs contributors and copied source arrays; retain all immutable contributor bindings until arrays/users release. `FinishPin` is publication, not unpin. |
| Twin jobs and Rust twin store | Count local candidate vectors, registered jobs and both sampled/primary members. Fence `Store`, `Sample`, Rust store writes and late nudges; release after final cache/publication use. |
| Probe and recheck | Register asynchronous jobs and synchronous `Check` (currently ID zero) with inherited source context; fence `Abandon`, rechecks and dead-pick state changes. |
| Search and provider work | Count `m_pending`, local `due`, prepared jobs, health walkers, NZB/NNTP fetches, batch requests/results and Scanner handoff. `PickGone` followed by compensating deletion is insufficient. |
| Scanner and URL | Cover external QueueData, archive/NZB script processing, temporary/queued filenames and final queue insertion. URL completion removes its active-list entry before Scanner finishes; publication stays registered. |
| Direct rename/unpack and post stages | Cover loader threads, process children, PAR/RAR rename, repair, unpack, cleanup, moving, post-download/post-unpack rename, script and stage transitions. Retain actual renamed/final outputs. |
| Live/post stream repair | Cover donor/target maps, batch fetch and watchdog. Detached `LiveRepairThread` and `working=false` do not prove exit; retain ticket through worker/process/library/destructor completion. |
| Queue/post/NZB scripts | Register events, children, pipe readers and publication commands. Suppress new affected deletion events; unknown or uncontrolled output ownership is a preflight/inventory gap. |
| History and persistence | Fence `HistoryHide`, retention, retry, redownload, merge/split, saves and object erasure. Retain inventory before full metadata is destroyed; void `Save` and ignored sync warnings cannot ACK. |
| Startup/shutdown | Recovery fence precedes loaded/admission signals, remote mutation and worker/service starts; shutdown retains intent and all incomplete outcomes. |

Artifact ACK covers exact incarnation/source-scoped parsed/bad donor caches,
article-source pins, twin/signature/attempt/checking entries, probe pending
state, PAR damage state, discovery pending directory/checkpoints/sent markers
and matching persisted search entries. Shared global indexer/provider budgets,
other titles/editions and unrelated queue data are preserved. A currently
ID-only or key-only cache needs a reviewed binding migration or conservative
conflict, not blind ID/title deletion. Artifact paths are validated inventory
entries, not reconstructed from current display names.

## Legacy ownership applicability: GAP

The earlier preserved source audit established an information-loss witness:
two full records with different destination/final/completed-file paths project
to identical compact `DupInfo` records. `HistoryHide` calls `DeleteDiskFiles`
and destroys full metadata; `SaveDupInfo` retains status, size, hashes, score,
mode, name/key and enclosing ID/time, without output inventory. Successful
payloads may survive. Transactional `.new` files are interrupted-write
recovery, not an assured historical ownership archive.

No independently validated historical snapshot/catalog was supplied or
located within this authorized source-only audit. The source map deliberately
uses `authoritative_input: null`. No production inventory scan or importer
execution was performed. Do not create a fictitious importer path or infer
ownership from title, size, hash alone, current category/root, internal NZB
filename or a retained log.

An import proposal must establish immutable custody and capture provenance,
original IDs/incarnations (or a separately reviewed legacy binding bridge),
independent posting/source validation, actual path/object/root ownership and
outside/shared claims, plus continuity or safe conflict handling since capture.
Freeze and independently review that evidence before import. A new checksum
of an unauthenticated assertion does not authenticate historical ownership.

Future inventory retention makes future compaction provable. It does not
recover existing legacy rows. Families containing unprovable legacy ownership
retain rows/files and return missing-inventory/unsupported state; that is safe
rejection, **not delivery of full deletion**. The full goal stays held until an
independently reviewed recovery resolution or explicit human acceptance of
unsupported scope. Task 1 can document usable contracts while that GAP remains.

## Preservation, replacement and qualification handoff

Original/current Rust `fsdelete` and `fsops` baseline hashes were recorded
with `FileSystem.cpp`, FFI/header/module registration and their existing
differential harnesses in signed commit `64410656`. The original ignored
Task 1 source packet, raw checks and bundles became unavailable when the
original worktree was removed. Its recorded hashes and custody claims remain
in that immutable commit and the map's `original_capture_claim`; they are
historical claims, not a statement that the original packet is still held.

A separately labeled retrospective packet reconstructs the 102 enumerated
source blobs from immutable Git commit `d4842b18`, matches each original
recorded digest, and rechecks the recorded source anchors. It includes a new
bounded signed-history bundle with its own hash and prerequisite. These are
retrospective reconstructions, never the original prospective evidence. The
map records the reconstruction manifest hash, scope and limitations. A bounded
availability audit found the older independent source/legacy audits, but no
independent copy of the original Task 1 packet. The legacy audit's report hash
still matches; it is source-only evidence, not an ownership catalog.

`fsops` is Unix gated; filesystem dispatch
also depends on actual build macros. These are live preservation baselines,
not new purge modules. Preserve wrapper callbacks, bytes, allocation/error,
logging/flush and embedded-NUL/non-UTF8 behavior at any touched existing caller.
This task neither runs those harnesses nor claims current build reachability.

Historical group/history delete is incomplete and must not be presented as a
full-family comparator. Retain original C++ caller boundaries separately.
A new full-contract C++ reference and an equally optimized version still need
to be implemented with the same indexing/batching/ownership/traversal work as
Rust. New purge-only boundary nonapplicability requires independent source
review and does not waive preservation of existing Rust callers. Native
whole-caller speed qualification and complete output/persistence correctness
remain held; no timings, binaries or successful runtime checks are claimed.

The new user route replaces `QueueEditor::EditGroup`'s user deletion selection
and `HistoryCoordinator::HistoryDelete`/`DeleteDiskFiles` cleanup policy for
that route, and the Downloads group/post RPC chain. Internal automatic
failover, ordinary retention/compaction and mechanical object/serialization
adapters have separate retained callers. Before shared edits, review exact
body removal versus retained internal call sites; do not claim removal merely
because a Rust module is added. No body has been removed in Task 1. The full
purge has no incomplete C++ production fallback and changes no BinRPC fields.

The controller-reported source-only ACKs cover the exact `64410656`
declarations: identity/parent semantics and immutable validation;
allocator/load rules; queue-guard reservation linearization; all four shared
entry points and exact receipt identity; ticket acquisition/transfer/release
at the mapped callers; output delta durability before destruction; distinct
cache/pending ACK; and retained failed fences. Root's coordinator-issued
barrier interpretation is now explicit in both this contract and the map.
The controller obtains fresh review of the complete Task 1 range. A later
declaration change updates both artifacts before dependent implementation;
source-only acknowledgment releases no implementation or qualification hold.
