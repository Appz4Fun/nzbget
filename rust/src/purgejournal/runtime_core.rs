//! Private runtime foundation: owned preparation and explicit close/cancel/drop.
//! Source-only successor; uncompiled. No admission, install, C2, final-check or ABI API.
//! Create/prepare run outside ALL daemon guards; existing subject resolution
//! invokes Host identity callbacks and allocates. No method here grants Ready.
use super::{Host, Registry, subjects::SubjectRecord};
use crate::dupepurge::{MemberBinding, PurgeError, MAX_IDENTITY, MAX_PAYLOAD};
use std::sync::{Arc, atomic::{AtomicBool, AtomicUsize, Ordering}};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct ExactReference {
    pub domain: [u8; 16],
    pub binding: MemberBinding,
    pub parent: Option<MemberBinding>,
    pub subject_revision: u64,
    pub publication_sequence: u64,
    pub source_record_id: [u8; 32],
}
impl ExactReference {
    // Test input construction only; production preparation uses fallible copies.
    #[cfg(test)]
    pub(super) fn from_record(r: &SubjectRecord) -> Self {
        Self { domain: r.domain, binding: r.binding.clone(), parent: r.parent.clone(),
            subject_revision: r.subject_revision, publication_sequence: r.publication_sequence,
            source_record_id: r.source.source_record_id }
    }
    fn owned(&self) -> Result<Self, PurgeError> {
        Ok(Self { domain: self.domain, binding: binding_copy(&self.binding)?,
            parent: self.parent.as_ref().map(binding_copy).transpose()?,
            subject_revision: self.subject_revision, publication_sequence: self.publication_sequence,
            source_record_id: self.source_record_id })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct ProducerReservationKey {
    pub request: [u8; 16], pub publication_sequence: u64, pub id: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum InstallMode { ArticlesOnly = 1, ArticlesAndProgress = 2 }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum DependencyRole { InstallTarget, ImmutableParent }
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct DependencyRequest {
    pub reference: ExactReference, pub role: DependencyRole,
    pub current_preimage: Option<Vec<u8>>,
}
#[derive(Debug)]
pub(super) struct RecoveryPrepareRequest {
    pub producer: ProducerReservationKey, pub owner_kind: u32, pub work_kind: u32,
    pub mode: InstallMode, pub schema: u32, pub parent_ticket: Option<u64>,
    pub target: ExactReference, pub dependencies: Vec<DependencyRequest>,
    pub desired_writes: Vec<u8>,
}
#[derive(Clone, Copy, Debug)]
enum WriterCoverage { Unknown }

// This instance retains Rust ownership bookkeeping only. It is not a Store,
// descriptor, FileInfo or worker pin. Registry access remains serialized by the
// existing Store mutex. Atomics let an already-owned Prepared drop outside that
// mutex; they do not create a second registry lock or a current-visibility check.
#[derive(Debug)]
struct RuntimeInstance {
    root_alive: AtomicBool,
    closing: AtomicBool,
    prepared_slots: AtomicUsize,
}
impl RuntimeInstance {
    fn open(&self) -> Result<(), PurgeError> {
        if !self.root_alive.load(Ordering::Acquire) || self.closing.load(Ordering::Acquire) {
            Err(PurgeError::RecoveryRequired)
        } else { Ok(()) }
    }
    fn observation(&self) -> RuntimeLifetimeObservation {
        RuntimeLifetimeObservation {
            root_alive: self.root_alive.load(Ordering::Acquire),
            closing: self.closing.load(Ordering::Acquire),
            prepared_slots: self.prepared_slots.load(Ordering::Acquire),
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct RuntimeLifetimeObservation {
    pub root_alive: bool,
    pub closing: bool,
    pub prepared_slots: usize,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum DestroyOutcome { Pending { prepared_slots: usize }, Destroyed }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PreparedState { Owned, Cancelled }

// An owned preparation slot, NOT an admitted work row or a registration attempt.
// The producer is the already validated durable namespace2 reservation; this
// slot neither creates another ID nor advances an admission/C2 revision.
// Pending registration retains this same object. Cancel/drop releases only its
// unadmitted preparation obligation. An admitted work/final-ACK obligation is
// deliberately not expressible in this tranche, so drop cannot release one.
#[derive(Debug)]
struct PreparedSlot {
    instance: Arc<RuntimeInstance>,
    producer: ProducerReservationKey,
    state: PreparedState,
}
impl PreparedSlot {
    fn acquire(instance: &Arc<RuntimeInstance>, producer: ProducerReservationKey)
        -> Result<Self, PurgeError>
    {
        instance.open()?;
        instance.prepared_slots.fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
            if n < super::MAX_OPERATIONS { n.checked_add(1) } else { None }
        }).map_err(|_| PurgeError::LimitExceeded)?;
        let slot = Self { instance: Arc::clone(instance), producer, state: PreparedState::Owned };
        // If a future guarded caller races close with preparation, rollback is
        // the same RAII path as any later copy/allocation failure.
        slot.instance.open()?;
        Ok(slot)
    }
    fn release(&mut self) {
        if self.state == PreparedState::Owned {
            self.state = PreparedState::Cancelled;
            let before = self.instance.prepared_slots.fetch_sub(1, Ordering::AcqRel);
            debug_assert!(before > 0);
        }
    }
}
impl Drop for PreparedSlot { fn drop(&mut self) { self.release(); } }

#[derive(Debug)]
pub(super) struct CommonRuntimeCore {
    instance: Arc<RuntimeInstance>, coverage: WriterCoverage,
    work_tickets: u64, issued_revision: u64,
}
impl Drop for CommonRuntimeCore {
    fn drop(&mut self) {
        // Even an unconditional Rust Registry drop revokes instance presence.
        // Prepared owns its byte copies; this does not keep the actual Store alive.
        self.instance.closing.store(true, Ordering::Release);
        self.instance.root_alive.store(false, Ordering::Release);
    }
}

// Test-only refusal gates at runtime allocation sites. No allocator is replaced;
// Arc::new still has its ordinary non-recoverable OOM behavior. Resolver/copy
// allocations outside this module and OS allocator failure are not injected.
#[cfg(test)]
std::thread_local! { static ALLOCATION_FAILURE: std::cell::Cell<Option<usize>> = const { std::cell::Cell::new(None) }; }
#[cfg(test)]
pub(super) struct AllocationFailureGuard(Option<usize>);
#[cfg(test)]
impl Drop for AllocationFailureGuard {
    fn drop(&mut self) { ALLOCATION_FAILURE.with(|f| f.set(self.0)); }
}
#[cfg(test)]
pub(super) fn allocation_fail_after(n: usize) -> AllocationFailureGuard {
    AllocationFailureGuard(ALLOCATION_FAILURE.with(|f| f.replace(Some(n))))
}
fn allocation_checkpoint() -> Result<(), PurgeError> {
    #[cfg(test)]
    { return ALLOCATION_FAILURE.with(|f| match f.get() {
        None => Ok(()),
        Some(0) => Err(PurgeError::AllocationFailure),
        Some(n) => { f.set(Some(n - 1)); Ok(()) },
    }); }
    #[cfg(not(test))]
    { Ok(()) }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct RuntimeObservation {
    pub runtime_present: bool, pub coverage_known: bool,
    pub work_tickets: u64, pub issued_revision: u64,
}
#[derive(Debug)]
pub(super) struct PreparedRecoveryWork {
    slot: PreparedSlot, target: ExactReference,
    producer: ProducerReservationKey, owner_kind: u32, work_kind: u32,
    mode: InstallMode, schema: u32, dependencies: Vec<DependencyRequest>,
    desired_writes: Vec<u8>,
}
pub(super) struct PreparedView<'a> {
    pub target: &'a ExactReference, pub mode: InstallMode, pub schema: u32,
    pub producer_id: u64, pub owner_kind: u32, pub work_kind: u32,
    pub dependencies: &'a [DependencyRequest], pub desired_writes: &'a [u8],
}
impl PreparedRecoveryWork {
    pub(super) fn view(&self) -> PreparedView<'_> {
        PreparedView { target: &self.target, mode: self.mode, schema: self.schema,
            producer_id: self.producer.id, owner_kind: self.owner_kind, work_kind: self.work_kind,
            dependencies: &self.dependencies, desired_writes: &self.desired_writes }
    }
    // Only explicit cancellation consumes this unadmitted preparation. Pending
    // and all refusal paths leave it owned; inspection remains available.
    pub(super) fn consumed(&self) -> bool { self.slot.state == PreparedState::Cancelled }
    pub(super) fn runtime_root_alive(&self) -> bool {
        self.slot.instance.root_alive.load(Ordering::Acquire)
    }
}
#[derive(Debug, PartialEq, Eq)]
pub(super) enum RegisterOutcome { Pending }

fn bytes_copy(b: &[u8]) -> Result<Vec<u8>, PurgeError> {
    let mut out = Vec::new();
    allocation_checkpoint()?;
    out.try_reserve_exact(b.len()).map_err(|_| PurgeError::AllocationFailure)?;
    out.extend_from_slice(b); Ok(out)
}
fn binding_copy(b: &MemberBinding) -> Result<MemberBinding, PurgeError> {
    super::subjects::check_binding(b)?;
    Ok(MemberBinding { collection_id: b.collection_id, file_id: b.file_id,
        incarnation: b.incarnation, posting_source: bytes_copy(&b.posting_source)? })
}

impl Registry {
    pub(super) fn create_common_runtime(&mut self, host: &impl Host) -> Result<(), PurgeError> {
        if self.common_runtime.is_some() { return Err(PurgeError::Conflict); }
        self.ready(host)?; // Host callback: outside ALL daemon guards only.
        // A process-lifetime identity, never a Store/FileInfo pin or durable ID.
        // Arc's allocation is outside guards; recoverable Arc OOM/FFI behavior
        // remains unqualified, alongside the later allocation/deallocation gate.
        allocation_checkpoint()?;
        self.common_runtime = Some(CommonRuntimeCore { instance: Arc::new(RuntimeInstance {
            root_alive: AtomicBool::new(true), closing: AtomicBool::new(false),
            prepared_slots: AtomicUsize::new(0),
        }), coverage: WriterCoverage::Unknown, work_tickets: 0, issued_revision: 0 });
        Ok(())
    }
    pub(super) fn runtime_lifetime_observation(&self) -> Option<RuntimeLifetimeObservation> {
        self.common_runtime.as_ref().map(|core| core.instance.observation())
    }
    // No Host callback, I/O or wait. Successful core retirement can deallocate
    // its Rust Arc, so call outside actual daemon guards. Caller still owns
    // actual root destruction. Pending MUST retain that root until preparation
    // obligations are cancelled/dropped; this is not C++ Destroy qualification.
    pub(super) fn begin_common_runtime_destroy(&mut self) -> Result<DestroyOutcome, PurgeError> {
        let core = self.common_runtime.as_ref().ok_or(PurgeError::Unsupported)?;
        core.instance.closing.store(true, Ordering::Release);
        let count = core.instance.prepared_slots.load(Ordering::Acquire);
        if count != 0 { return Ok(DestroyOutcome::Pending { prepared_slots: count }); }
        self.common_runtime = None;
        Ok(DestroyOutcome::Destroyed)
    }
    // Release of an existing unadmitted preparation remains possible while
    // Closing or RecoveryRequired. There is no final work/Inventory ACK here.
    pub(super) fn cancel_prepared_recovery_work(&mut self, prepared: &mut PreparedRecoveryWork)
        -> Result<(), PurgeError>
    {
        let core = self.common_runtime.as_ref().ok_or(PurgeError::Unsupported)?;
        if !Arc::ptr_eq(&core.instance, &prepared.slot.instance) || prepared.consumed() {
            return Err(PurgeError::Conflict);
        }
        prepared.slot.release();
        Ok(())
    }
    pub(super) fn runtime_observation(&self) -> RuntimeObservation {
        match self.common_runtime.as_ref() {
            None => RuntimeObservation { runtime_present: false, coverage_known: false,
                work_tickets: 0, issued_revision: 0 },
            Some(core) => RuntimeObservation { runtime_present: true,
                coverage_known: match core.coverage { WriterCoverage::Unknown => false },
                work_tickets: core.work_tickets, issued_revision: core.issued_revision },
        }
    }
    fn resolved_recovery_reference(&self, r: &ExactReference, host: &impl Host)
        -> Result<SubjectRecord, PurgeError>
    {
        let record = self.load_subject_reference(r.domain, &r.binding, r.subject_revision,
            r.publication_sequence, r.source_record_id, host)?;
        if r.parent != record.parent { return Err(PurgeError::Conflict); }
        if record.schema_version != 2 || record.immutable_capture_version != 1 {
            return Err(PurgeError::Unsupported);
        }
        Ok(record)
    }
    pub(super) fn prepare_recovery_work(&self, request: &RecoveryPrepareRequest, host: &impl Host)
        -> Result<PreparedRecoveryWork, PurgeError>
    {
        let core = self.common_runtime.as_ref().ok_or(PurgeError::Unsupported)?;
        core.instance.open()?;
        if request.schema != 1 { return Err(PurgeError::Unsupported); }
        if request.owner_kind == 0 || request.work_kind == 0 || request.parent_ticket.is_some()
            || request.dependencies.len() != 2 { return Err(PurgeError::InvalidInput); }
        // The selected tranche is exactly one file target plus its collection.
        // Count/byte checks precede resolver copies and all request deep copies.
        let mut total = request.desired_writes.len();
        for d in &request.dependencies {
            total = total.checked_add(d.reference.binding.posting_source.len())
                .and_then(|n| n.checked_add(d.reference.parent.as_ref().map_or(0, |p| p.posting_source.len())))
                .and_then(|n| n.checked_add(d.current_preimage.as_ref().map_or(0, Vec::len)))
                .ok_or(PurgeError::LimitExceeded)?;
            super::subjects::check_binding(&d.reference.binding)?;
            if let Some(parent) = &d.reference.parent { super::subjects::check_binding(parent)?; }
        }
        total = total.checked_add(request.target.binding.posting_source.len())
            .and_then(|n| n.checked_add(request.target.parent.as_ref().map_or(0, |p| p.posting_source.len())))
            .ok_or(PurgeError::LimitExceeded)?;
        if total > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        self.ready(host)?;
        // Existing namespace2 reservation is authoritative; no new reservation,
        // appended journal frame or caller-selected numeric ID issues authority.
        if !self.id_reservations.iter().any(|r| r.domain == self.domain && r.id_namespace == 2
            && r.request == request.producer.request && r.publication_sequence == request.producer.publication_sequence
            && r.publication_sequence != 0 && request.producer.id >= r.first && request.producer.id <= r.last)
        { return Err(PurgeError::Conflict); }
        let target = self.resolved_recovery_reference(&request.target, host)?;
        if target.source_kind != 2 || target.binding.file_id.is_none() { return Err(PurgeError::InvalidInput); }
        let parent_binding = target.parent.as_ref().ok_or(PurgeError::Conflict)?;
        let [target_input, parent_input] = request.dependencies.as_slice() else {
            return Err(PurgeError::InvalidInput);
        };
        // Roles come from actual resolved identity/parent. The supplied labels
        // are checked for consistency and cannot waive target image validation.
        if target_input.reference != request.target || target_input.role != DependencyRole::InstallTarget
            || parent_input.reference.binding != *parent_binding
            || parent_input.role != DependencyRole::ImmutableParent || parent_input.current_preimage.is_some()
        { return Err(PurgeError::InvalidInput); }
        let parent = self.resolved_recovery_reference(&parent_input.reference, host)?;
        if parent.source_kind != 1 || parent.binding.file_id.is_some() || parent.parent.is_some()
        { return Err(PurgeError::Conflict); }
        let current = target_input.current_preimage.as_deref().ok_or(PurgeError::InvalidInput)?;
        validate_mode1_images(request.mode, current, &request.desired_writes, &target.immutable_source_bytes)?;
        // No obligation is acquired until existing issuer/reference/image checks
        // pass. Any subsequent failure drops the RAII slot, including partial
        // deep copies; neither the reservation nor journal is mutated.
        let slot = PreparedSlot::acquire(&core.instance, request.producer)?;
        let mut dependencies = Vec::new();
        allocation_checkpoint()?;
        dependencies.try_reserve_exact(2).map_err(|_| PurgeError::AllocationFailure)?;
        for d in &request.dependencies {
            dependencies.push(DependencyRequest { reference: d.reference.owned()?, role: d.role,
                current_preimage: d.current_preimage.as_deref().map(bytes_copy).transpose()? });
        }
        Ok(PreparedRecoveryWork { slot, target: request.target.owned()?,
            producer: request.producer, owner_kind: request.owner_kind, work_kind: request.work_kind,
            mode: request.mode, schema: request.schema, dependencies,
            desired_writes: bytes_copy(&request.desired_writes)? })
    }
    pub(super) fn register_prepared_recovery_work(&mut self, prepared: &mut PreparedRecoveryWork,
        current: &[DependencyRequest]) -> Result<RegisterOutcome, PurgeError>
    {
        if self.recovery_required { return Err(PurgeError::RecoveryRequired); }
        let core = self.common_runtime.as_ref().ok_or(PurgeError::Unsupported)?;
        if !Arc::ptr_eq(&core.instance, &prepared.slot.instance) || prepared.consumed()
            || prepared.slot.producer != prepared.producer
            || current != prepared.dependencies.as_slice()
        {
            return Err(PurgeError::Conflict);
        }
        core.instance.open()?;
        // Real current policy: actual producer/startup/worker coverage is unknown.
        // No admitted handle, epoch, row, journal write or consumed Prepared.
        match core.coverage { WriterCoverage::Unknown => Ok(RegisterOutcome::Pending) }
    }
}

struct Cursor<'a> { bytes: &'a [u8], at: usize }
impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Result<Self, PurgeError> {
        if bytes.len() > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        Ok(Self { bytes, at: 0 })
    }
    fn take(&mut self, n: usize) -> Result<&'a [u8], PurgeError> {
        let end = self.at.checked_add(n).ok_or(PurgeError::LimitExceeded)?;
        let b = self.bytes.get(self.at..end).ok_or(PurgeError::InvalidInput)?;
        self.at = end; Ok(b)
    }
    fn u32(&mut self) -> Result<u32, PurgeError> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().map_err(|_| PurgeError::InvalidInput)?))
    }
    fn i32(&mut self) -> Result<i32, PurgeError> {
        Ok(i32::from_le_bytes(self.take(4)?.try_into().map_err(|_| PurgeError::InvalidInput)?))
    }
    fn u64(&mut self) -> Result<u64, PurgeError> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().map_err(|_| PurgeError::InvalidInput)?))
    }
    fn i64(&mut self) -> Result<i64, PurgeError> {
        Ok(i64::from_le_bytes(self.take(8)?.try_into().map_err(|_| PurgeError::InvalidInput)?))
    }
    fn boolean(&mut self) -> Result<bool, PurgeError> {
        match self.take(1)?[0] { 0 => Ok(false), 1 => Ok(true), _ => Err(PurgeError::InvalidInput) }
    }
    fn text(&mut self) -> Result<&'a [u8], PurgeError> {
        let n = self.u32()? as usize;
        if n > MAX_IDENTITY { return Err(PurgeError::LimitExceeded); }
        self.take(n)
    }
    fn optional_text(&mut self) -> Result<Option<&'a [u8]>, PurgeError> {
        Ok(if self.boolean()? { Some(self.text()?) } else { None })
    }
    fn done(&self) -> Result<(), PurgeError> {
        if self.at == self.bytes.len() { Ok(()) } else { Err(PurgeError::InvalidInput) }
    }
}
fn equal<T: PartialEq>(a: T, b: T) -> Result<(), PurgeError> {
    if a == b { Ok(()) } else { Err(PurgeError::Conflict) }
}
fn validate_mode1_images(mode: InstallMode, current: &[u8], desired: &[u8], immutable: &[u8])
    -> Result<(), PurgeError>
{
    let mut c = Cursor::new(current)?; let mut d = Cursor::new(desired)?;
    if c.take(8)? != b"RCPRE1\0\0" || c.u32()? != 1 || c.u32()? != mode as u32
        || d.take(8)? != b"RCWRITE1" || d.u32()? != 1 || d.u32()? != mode as u32
    { return Err(PurgeError::InvalidInput); }
    if mode != InstallMode::ArticlesOnly { return Err(PurgeError::Unsupported); }
    if c.boolean()? || !c.boolean()? { return Err(PurgeError::Conflict); }
    // Read the EXISTING validated immutable projection; no second SAX or
    // SaveFileInfo text parser, no edits to the protected source codec.
    let mut s = Cursor::new(immutable)?;
    if s.take(b"PURGE-IMMUTABLE1".len())? != b"PURGE-IMMUTABLE1" || s.u32()? != 1 || s.u32()? != 2
    { return Err(PurgeError::Conflict); }
    equal(c.text()?, s.text()?)?; // Subject
    equal(c.text()?, s.text()?)?; // Filename
    equal(c.optional_text()?.unwrap_or(b""), s.text()?)?; // summary has no null bit
    equal(c.text()?, s.text()?)?; // OutputFilename, compare-only
    equal(c.boolean()?, s.boolean()?)?;
    equal(c.i64()?, i64::from(s.i32()?))?;
    let size = c.i64()?; if size < 0 { return Err(PurgeError::InvalidInput); }
    equal(size as u64, s.u64()?)?;
    let missed_size = c.i64()?; if missed_size < 0 { return Err(PurgeError::InvalidInput); }
    equal(missed_size as u64, s.u64()?)?;
    equal(c.boolean()?, s.boolean()?)?;
    equal(c.i32()?, s.i32()?)?; equal(c.i32()?, s.i32()?)?;
    let groups = c.u32()?; equal(groups, s.u32()?)?;
    if groups > 1_000_000 { return Err(PurgeError::LimitExceeded); }
    for _ in 0..groups { equal(c.text()?, s.text()?)?; }
    // Only hydration of an empty article list is selected in mode1.
    if c.u32()? != 0 { return Err(PurgeError::Conflict); } c.done()?;
    let count = d.u32()?; equal(count, s.u32()?)?;
    if count == 0 || count > 1_000_000 { return Err(PurgeError::InvalidInput); }
    // Minimum two i32 plus counted string length; reject truncated large lists
    // before loops. No allocation is performed by this validation cursor.
    if count as usize > (desired.len() - d.at) / 12 { return Err(PurgeError::InvalidInput); }
    for _ in 0..count {
        equal(d.i32()?, s.i32()?)?; equal(d.i32()?, s.i32()?)?; equal(d.text()?, s.text()?)?;
    }
    d.done()?; s.done()
}
