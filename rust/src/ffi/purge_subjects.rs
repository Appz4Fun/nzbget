//! Additive subject ABI. Borrowed POD is checked before recursive ownership.
use super::*;
use journal::subjects::{IdReservation, PreparedSubject, SubjectRecord};
use purge::PurgeError;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct DurableReceiptC {
    pub version: u32, pub struct_size: u32, pub domain: [u8; 16],
    pub publication_sequence: u64, pub journal_identity: PurgeBytesC,
    pub payload_digest: [u8; 32], pub file_synced: u32, pub published: u32,
    pub directory_synced: u32, pub reserved: u32,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct IdsRequestC {
    pub version: u32, pub struct_size: u32, pub id_namespace: u32,
    pub count: u32, pub request: [u8; 16],
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct IdsViewC {
    pub version: u32, pub struct_size: u32, pub id_namespace: u32,
    pub count: u32, pub request: [u8; 16], pub first: u64, pub last: u64,
    pub high_water: u64, pub durable: DurableReceiptC,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SubjectWriteC {
    pub version: u32, pub struct_size: u32, pub transition: u32, pub has_prior: u32,
    pub binding: PurgeBindingC, pub prior: PurgeBindingC,
    pub source: PurgeSourceC, pub custody: PurgeCustodyC,
    pub has_parent: u32, pub reserved: u32, pub parent: PurgeBindingC,
    pub reservation_request: [u8; 16], pub reservation_sequence: u64,
    pub source_kind: u32, pub reserved_source: u32, pub original_source_byte_length: u64,
    pub expected_prior_subject_revision: u64, pub expected_prior_publication_sequence: u64,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SubjectPrepareC {
    pub version: u32, pub struct_size: u32,
    pub template_record: SubjectWriteC, pub original_source_bytes: PurgeBytesC,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SubjectViewC {
    pub version: u32, pub struct_size: u32, pub record: SubjectWriteC,
    pub subject_revision: u64, pub subject_high_water: u64, pub durable: DurableReceiptC,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SubjectReferenceC {
    pub version: u32, pub struct_size: u32, pub domain: [u8; 16],
    pub binding: PurgeBindingC, pub subject_revision: u64, pub publication_sequence: u64,
    pub source_record_id: [u8; 32],
}
pub struct IdsOwned { record: IdReservation, identity: [u8; 32], digest: [u8; 32] }
pub struct SubjectOwned { record: SubjectRecord, identity: [u8; 32], digest: [u8; 32], high_water: u64 }

// Allocate return storage before publication. If the commit succeeds there is
// no fallible return-handle allocation left that could hide its exact receipt.
pub(super) unsafe fn owned<T>(out: *mut *mut T, error: *mut i32,
    make: impl FnOnce() -> Result<T, PurgeError>) -> i32
{
    if error.is_null() || !(error as usize).is_multiple_of(std::mem::align_of::<i32>()) { return -1; }
    error.write(0);
    if out.is_null() || !(out as usize).is_multiple_of(std::mem::align_of::<*mut T>()) {
        error.write(purge_error_code(PurgeError::InvalidInput)); return -1;
    }
    out.write(std::ptr::null_mut());
    let layout = std::alloc::Layout::new::<T>();
    let ptr = std::alloc::alloc(layout).cast::<T>();
    if ptr.is_null() { error.write(purge_error_code(PurgeError::AllocationFailure)); return -1; }
    match make() {
        Ok(value) => { ptr.write(value); out.write(ptr); 0 }
        Err(e) => { std::alloc::dealloc(ptr.cast(), layout); error.write(purge_error_code(e)); -1 }
    }
}
pub(super) unsafe fn destroy<T>(ptr: *mut T) {
    if !ptr.is_null() {
        std::ptr::drop_in_place(ptr);
        std::alloc::dealloc(ptr.cast(), std::alloc::Layout::new::<T>());
    }
}
pub(super) unsafe fn view<T>(out: *mut T, error: *mut i32,
    make: impl FnOnce() -> Result<T, PurgeError>) -> i32
{
    if error.is_null() || !(error as usize).is_multiple_of(std::mem::align_of::<i32>()) { return -1; }
    error.write(0);
    if let Err(e) = purge_versioned(out) { error.write(purge_error_code(e)); return -1; }
    // Every view in this module consists only of integers/raw pointers.
    std::ptr::write_bytes(out, 0, 1);
    let header = out.cast::<u32>(); header.write(1); header.add(1).write(std::mem::size_of::<T>() as u32);
    match make() { Ok(v) => { out.write(v); 0 }, Err(e) => { error.write(purge_error_code(e)); -1 } }
}
pub(super) fn receipt(domain: [u8; 16], sequence: u64, identity: &[u8; 32], digest: [u8; 32]) -> DurableReceiptC {
    // Call only for returned/recovered records whose publication was checked.
    DurableReceiptC { version: 1, struct_size: std::mem::size_of::<DurableReceiptC>() as u32,
        domain, publication_sequence: sequence, journal_identity: purge_view(identity), payload_digest: digest,
        file_synced: 1, published: 1, directory_synced: 1, reserved: 0 }
}
fn absent_binding() -> PurgeBindingC {
    PurgeBindingC { collection_id: 0, file_id: 0, has_file: 0, incarnation: 0,
        posting_source: PurgeBytesC { data: std::ptr::null(), len: 0 } }
}
pub(super) fn source_view(v: &purge::SourceValidation) -> PurgeSourceC {
    PurgeSourceC { id: v.id, version: v.version, validator_version: v.validator_version,
        source_record_id: v.source_record_id, source_bytes_digest: v.source_bytes_digest,
        binding: purge_binding_view(&v.binding), has_parent: u32::from(v.parent_collection.is_some()),
        parent: v.parent_collection.as_ref().map_or_else(absent_binding, purge_binding_view),
        custody_receipt_id: v.custody_receipt_id }
}
pub(super) fn custody_view(v: &purge::CustodyReceipt) -> PurgeCustodyC {
    PurgeCustodyC { id: v.id, validator_version: v.validator_version,
        source_record_id: v.source_record_id, source_bytes_digest: v.source_bytes_digest }
}
fn subject_view(v: &SubjectOwned) -> SubjectViewC {
    let r = &v.record;
    SubjectViewC { version: 1, struct_size: std::mem::size_of::<SubjectViewC>() as u32,
        record: SubjectWriteC { version: 1, struct_size: std::mem::size_of::<SubjectWriteC>() as u32,
            transition: r.transition, has_prior: u32::from(r.prior.is_some()), binding: purge_binding_view(&r.binding),
            prior: r.prior.as_ref().map_or_else(absent_binding, purge_binding_view), source: source_view(&r.source),
            custody: custody_view(&r.custody), has_parent: u32::from(r.parent.is_some()), reserved: 0,
            parent: r.parent.as_ref().map_or_else(absent_binding, purge_binding_view),
            reservation_request: r.reservation_request, reservation_sequence: r.reservation_sequence,
            source_kind: r.source_kind, reserved_source: 0, original_source_byte_length: r.original_source_byte_length,
            expected_prior_subject_revision: r.expected_prior_subject_revision,
            expected_prior_publication_sequence: r.expected_prior_publication_sequence },
        subject_revision: r.subject_revision, subject_high_water: v.high_water,
        durable: receipt(r.domain, r.publication_sequence, &v.identity, v.digest) }
}

/// # Safety
/// Records are aligned and live; outputs do not overlap immutable inputs. The
/// registry is exclusively borrowed and callbacks cannot reenter or retain POD.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_ids_reserve(input: *const IdsRequestC,
    ops: *const PurgeHostOpsC, out: *mut *mut IdsOwned, error: *mut i32) -> i32
{
    let input = purge_versioned(input).copied(); let ops = purge_host_ops(ops);
    owned(out, error, || {
        let input = input?; let ops = ops?;
        let registry = ops.registry.as_mut().ok_or(PurgeError::RecoveryRequired)?;
        let identity = journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let record = registry.inner.reserve_ids(input.id_namespace, input.request, input.count, &mut PurgeHostAdapter(&ops))?;
        let digest = journal::subjects::reservation_digest(&record)?;
        Ok(IdsOwned { record, identity, digest })
    })
}
/// # Safety
/// Owner remains alive through synchronous view consumption; output is versioned.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_ids_view(input: *const IdsOwned, out: *mut IdsViewC, error: *mut i32) -> i32 {
    view(out, error, || {
        let v = purge_record(input)?; let r = &v.record;
        Ok(IdsViewC { version: 1, struct_size: std::mem::size_of::<IdsViewC>() as u32,
            id_namespace: r.id_namespace, count: r.count, request: r.request, first: r.first,
            last: r.last, high_water: r.high_water,
            durable: receipt(r.domain, r.publication_sequence, &v.identity, v.digest) })
    })
}
/// # Safety
/// Null or an exclusively owned live handle; no borrowed views remain in use.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_ids_destroy(p: *mut IdsOwned) { destroy(p); }

/// # Safety
/// Immutable nested inputs remain live through this call; original capture and
/// all binding spans are recursively owned before an opaque handle is returned.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_prepare(input: *const SubjectPrepareC,
    ops: *const PurgeHostOpsC, out: *mut *mut PreparedSubject, error: *mut i32) -> i32
{
    let input = purge_versioned(input).copied(); let ops = purge_host_ops(ops);
    owned(out, error, || {
        let input = input?; let ops = ops?; let c = purge_versioned(&input.template_record)?;
        let registry = purge_record(ops.registry)?;
        if c.reserved != 0 || c.reserved_source != 0 { return Err(PurgeError::InvalidInput); }
        let mut budget = purge::Budget::new();
        budget.table::<SubjectRecord>(1)?;
        purge_check_binding(&c.binding, &mut budget)?;
        let prior = purge_bool(c.has_prior)?; let parent = purge_bool(c.has_parent)?;
        if prior { purge_check_binding(&c.prior, &mut budget)?; }
        else if !purge_absent_parent(&c.prior) { return Err(PurgeError::InvalidInput); }
        if parent { purge_check_binding(&c.parent, &mut budget)?; }
        else if !purge_absent_parent(&c.parent) { return Err(PurgeError::InvalidInput); }
        purge_check_source(&c.source, &mut budget)?;
        purge_check_custody(&c.custody, &mut budget)?;
        let bytes = purge_raw_bytes(input.original_source_bytes, purge::MAX_PAYLOAD, &mut budget)?;
        let record = SubjectRecord { schema_version: 1, domain: registry.inner.journal_domain(), publication_sequence: 0,
            transition: c.transition, binding: purge_owned_binding(&c.binding)?,
            prior: if prior { Some(purge_owned_binding(&c.prior)?) } else { None },
            source: purge_owned_source(&c.source)?, custody: purge_owned_custody(&c.custody)?,
            parent: if parent { Some(purge_owned_binding(&c.parent)?) } else { None },
            reservation_request: c.reservation_request, reservation_sequence: c.reservation_sequence,
            subject_revision: 0, source_kind: c.source_kind, original_source_byte_length: c.original_source_byte_length,
            original_source_bytes_digest: [0; 32],
            expected_prior_subject_revision: c.expected_prior_subject_revision,
            expected_prior_publication_sequence: c.expected_prior_publication_sequence, original_source_bytes:Vec::new(),immutable_capture_version:0,immutable_source_bytes:Vec::new() };
        registry.inner.prepare_subject(record, bytes, &PurgeHostAdapter(&ops))
    })
}
/// # Safety
/// Prepared is live, exclusive and from this exact registry domain. Ownership
/// stays with the caller, including after success or ambiguous publication.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_store_prepared(prepared: *mut PreparedSubject,
    ops: *const PurgeHostOpsC, out: *mut *mut SubjectOwned, error: *mut i32) -> i32
{
    let ops = purge_host_ops(ops);
    owned(out, error, || {
        purge_record(prepared)?;
        let ops = ops?; let registry = ops.registry.as_mut().ok_or(PurgeError::RecoveryRequired)?;
        let identity = journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let high_water = registry.inner.subject_high_water()?;
        let record = registry.inner.store_prepared_subject(&mut *prepared, &mut PurgeHostAdapter(&ops))?;
        let digest = (*prepared).committed_digest().ok_or(PurgeError::RecoveryRequired)?;
        Ok(SubjectOwned { record, identity, digest, high_water })
    })
}
/// # Safety
/// Null or live exclusive preparation; frees memory, never journal reservations.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_prepared_destroy(p: *mut PreparedSubject) { destroy(p); }
/// # Safety
/// Binding is immutable through the call, registry is exclusively borrowed and
/// descriptor-backed complete recovery has finished before any admission.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_load(binding: *const PurgeBindingC,
    ops: *const PurgeHostOpsC, out: *mut *mut SubjectOwned, error: *mut i32) -> i32
{
    let ops = purge_host_ops(ops);
    owned(out, error, || {
        let binding = purge_record(binding)?; let mut budget = purge::Budget::new();
        purge_check_binding(binding, &mut budget)?;
        let binding = purge_owned_binding(binding)?;
        let ops = ops?; let registry = purge_record(ops.registry)?;
        let identity = journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let record = registry.inner.load_subject(&binding, &PurgeHostAdapter(&ops))?;
        let digest = journal::subjects::subject_digest(&record)?;
        Ok(SubjectOwned { record, identity, digest, high_water: registry.inner.subject_high_water()? })
    })
}
//// # Safety
/// Exact reference and recursive binding are immutable for this call. No latest
/// record is substituted, and successful lookup does not admit recovered work.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_load_reference(input: *const SubjectReferenceC,
    ops: *const PurgeHostOpsC, out: *mut *mut SubjectOwned, error: *mut i32) -> i32
{
    let input = purge_versioned(input).copied(); let ops = purge_host_ops(ops);
    owned(out, error, || {
        let input = input?; let mut budget = purge::Budget::new();
        purge_check_binding(&input.binding, &mut budget)?;
        let binding = purge_owned_binding(&input.binding)?;
        let ops = ops?; let registry = purge_record(ops.registry)?;
        let identity = journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let record = registry.inner.load_subject_reference(input.domain, &binding,
            input.subject_revision, input.publication_sequence, input.source_record_id, &PurgeHostAdapter(&ops))?;
        let digest = journal::subjects::subject_digest(&record)?;
        Ok(SubjectOwned { record, identity, digest, high_water: registry.inner.subject_high_water()? })
    })
}
/// # Safety
/// Live owner and versioned output; all returned views expire with their owner.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_view(p: *const SubjectOwned, out: *mut SubjectViewC, error: *mut i32) -> i32 {
    view(out, error, || Ok(subject_view(purge_record(p)?)))
}
/// # Safety
/// Null or live exclusive owner; no borrowed views remain in use.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_destroy(p: *mut SubjectOwned) { destroy(p); }

#[repr(C)]
#[derive(Clone,Copy)]
pub struct SubjectValidateC {
    pub version:u32,pub struct_size:u32,pub reference:SubjectReferenceC,
    pub has_parent:u32,pub source_kind:u32,pub parent:PurgeBindingC,pub source_custody:PurgeCustodyC,
    pub current_source_bytes:PurgeBytesC,pub held_read_observations:PurgeBytesC,
}
/// # Safety
/// Exact current held-read spans and all POD are aligned/immutable during the
/// call. Registry/host access is exclusive, no callbacks retain these inputs.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_validate(input:*const SubjectValidateC,
    ops:*const PurgeHostOpsC,out:*mut *mut SubjectOwned,error:*mut i32)->i32
{
    let input=purge_versioned(input);let ops=purge_host_ops(ops);
    owned(out,error,||{
        let c=input?;let reference=purge_versioned(&c.reference)?;let mut budget=purge::Budget::new();
        purge_check_binding(&reference.binding,&mut budget)?;
        let has_parent=purge_bool(c.has_parent)?;
        if has_parent{purge_check_binding(&c.parent,&mut budget)?;}else if !purge_absent_parent(&c.parent){return Err(PurgeError::InvalidInput);}
        purge_check_custody(&c.source_custody,&mut budget)?;
        let current=purge_raw_bytes(c.current_source_bytes,purge::MAX_PAYLOAD,&mut budget)?;
        let observations=purge_raw_bytes(c.held_read_observations,32768,&mut budget)?;
        let binding=purge_owned_binding(&reference.binding)?;
        let parent=if has_parent{Some(purge_owned_binding(&c.parent)?)}else{None};
        let custody=purge_owned_custody(&c.source_custody)?;
        let ops=ops?;let registry=purge_record(ops.registry)?;
        let record=registry.inner.load_subject_reference(reference.domain,&binding,reference.subject_revision,
            reference.publication_sequence,reference.source_record_id,&PurgeHostAdapter(&ops))?;
        registry.inner.validate_subject_body(&record,c.source_kind,&parent,&custody,current,observations)?;
        let identity=journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let digest=journal::subjects::subject_digest(&record)?;
        Ok(SubjectOwned {record,identity,digest,high_water:registry.inner.subject_high_water()?})
    })
}
/// # Safety
/// Owner is live throughout span use. Output is writable/aligned/nonoverlapping;
/// source_view never grants current disk admission or progress history.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_subject_source_view(input:*const SubjectOwned,
    out:*mut PurgeBytesC,error:*mut i32)->i32
{
    if error.is_null()||!(error as usize).is_multiple_of(std::mem::align_of::<i32>()){return -1;}error.write(0);
    if out.is_null()||!(out as usize).is_multiple_of(std::mem::align_of::<PurgeBytesC>()){error.write(purge_error_code(PurgeError::InvalidInput));return -1;}
    out.write(PurgeBytesC{data:std::ptr::null(),len:0});
    let result=(||{
        let o=purge_record(input)?;
        if o.record.schema_version!=2||o.record.original_source_bytes.is_empty(){return Err(PurgeError::Unsupported);}
        Ok(purge_view(&o.record.original_source_bytes))
    })();
    match result{Ok(view)=>{out.write(view);0},Err(e)=>{error.write(purge_error_code(e));-1}}
}
