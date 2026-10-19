//! Structured durable inventory ACKs; never manufacture a receipt from status0.
use super::*;
use super::purge_subjects::{self as owned_abi, DurableReceiptC};
use journal::inventory::{Capture, InventoryAck};
use purge::PurgeError;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct CaptureC {
    pub version: u32, pub struct_size: u32, pub binding: PurgeBindingC,
    pub source_revision: u64, pub inventory_revision: u64,
    pub sources: *const PurgeSourceC, pub sources_count: u32,
    pub custodies: *const PurgeCustodyC, pub custodies_count: u32,
    pub parents: *const PurgeParentC, pub parents_count: u32,
    pub roots: *const PurgeRootC, pub roots_count: u32,
    pub namespaces: *const PurgeNamespaceC, pub namespaces_count: u32,
    pub entries: *const PurgeEntryC, pub entries_count: u32,
    pub ownership: *const PurgeOwnershipC, pub ownership_count: u32,
    pub outside: *const PurgeOutsideC, pub outside_count: u32,
    pub complete: u32, pub reserved: u32,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct AckViewC {
    pub version: u32, pub struct_size: u32, pub binding: PurgeBindingC,
    pub producer_ticket: u64, pub delta_sequence: u64, pub prior_inventory_revision: u64,
    pub inventory_revision: u64, pub subject_revision: u64,
    pub final_for_producer: u32, pub reserved: u32, pub delta_digest: [u8;32],
    pub durable: DurableReceiptC,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct AckKeyC {
    pub version: u32, pub struct_size: u32, pub binding: PurgeBindingC,
    pub producer_ticket: u64, pub delta_sequence: u64, pub delta_digest: [u8;32],
}

unsafe fn check_delta<'a>(c: &'a PurgeOutputDeltaC, b: &mut purge::Budget)
    -> Result<&'a [PurgeInventoryChangeC], PurgeError>
{
    purge_bool(c.final_for_producer)?;
    let changes = purge_slice(c.changes, c.changes_count, purge::MAX_ENTRIES, b)?;
    b.add(changes.len().checked_mul(std::mem::size_of::<journal::InventoryChange>()
        .saturating_sub(std::mem::size_of::<PurgeInventoryChangeC>())).ok_or(PurgeError::LimitExceeded)?)?;
    for v in changes {
        purge_bool(v.prior_absent)?;
        if !v.before.is_null() { purge_check_entry(purge_record(v.before)?, b)?; }
        if !v.after.is_null() { purge_check_entry(purge_record(v.after)?, b)?; }
        if !v.ownership.is_null() { purge_check_ownership(purge_record(v.ownership)?, b)?; }
    }
    Ok(changes)
}
unsafe fn delta_owned(c: &PurgeOutputDeltaC, values: &[PurgeInventoryChangeC]) -> Result<journal::OutputDelta, PurgeError> {
    let mut changes = purge::reserved(values.len())?;
    for v in values {
        changes.push(journal::InventoryChange { entry_id: v.entry_id,
            before: if v.before.is_null() { None } else { Some(purge_owned_entry(&*v.before)?) },
            after: if v.after.is_null() { None } else { Some(purge_owned_entry(&*v.after)?) },
            ownership: if v.ownership.is_null() { None } else { Some(purge_owned_ownership(&*v.ownership)?) },
            prior_absent: v.prior_absent == 1 });
    }
    Ok(journal::OutputDelta { producer_ticket: c.producer_ticket, sequence: c.sequence,
        prior_inventory_revision: c.prior_inventory_revision, changes, final_for_producer: c.final_for_producer == 1 })
}
unsafe fn map<T,U>(slice: &[T], f: unsafe fn(&T) -> Result<U, PurgeError>) -> Result<Vec<U>,PurgeError> {
    let mut output = purge::reserved(slice.len())?;
    for v in slice { output.push(f(v)?); }
    Ok(output)
}
unsafe fn capture_and_delta(c: &CaptureC, delta: &PurgeOutputDeltaC) -> Result<(Capture,journal::OutputDelta),PurgeError> {
    if c.reserved != 0 { return Err(PurgeError::InvalidInput); }
    let complete = purge_bool(c.complete)?;
    let mut b = purge::Budget::new();
    b.table::<Capture>(1)?; b.table::<journal::OutputDelta>(1)?;
    purge_check_binding(&c.binding, &mut b)?;
    // Bound every flat table and every nested field before the first owned copy.
    let sources = purge_slice(c.sources,c.sources_count,purge::MAX_MEMBERS,&mut b)?;
    let custodies = purge_slice(c.custodies,c.custodies_count,purge::MAX_MEMBERS,&mut b)?;
    let parents = purge_slice(c.parents,c.parents_count,purge::MAX_MEMBERS,&mut b)?;
    let roots = purge_slice(c.roots,c.roots_count,purge::MAX_ENTRIES,&mut b)?;
    let namespaces = purge_slice(c.namespaces,c.namespaces_count,purge::MAX_ENTRIES,&mut b)?;
    let entries = purge_slice(c.entries,c.entries_count,purge::MAX_ENTRIES,&mut b)?;
    let ownership = purge_slice(c.ownership,c.ownership_count,purge::MAX_ENTRIES,&mut b)?;
    let outside = purge_slice(c.outside,c.outside_count,purge::MAX_ENTRIES,&mut b)?;
    macro_rules! owned_overhead { ($values:expr,$owned:ty,$pod:ty) => {
        b.add($values.len().checked_mul(std::mem::size_of::<$owned>().saturating_sub(std::mem::size_of::<$pod>()))
            .ok_or(PurgeError::LimitExceeded)?)?;
    }; }
    owned_overhead!(sources,purge::SourceValidation,PurgeSourceC);
    owned_overhead!(custodies,purge::CustodyReceipt,PurgeCustodyC);
    owned_overhead!(parents,purge::ParentMembership,PurgeParentC);
    owned_overhead!(roots,purge::RootRecord,PurgeRootC);
    owned_overhead!(namespaces,purge::NamespaceProof,PurgeNamespaceC);
    owned_overhead!(entries,purge::InventoryEntry,PurgeEntryC);
    owned_overhead!(ownership,purge::OwnershipReceipt,PurgeOwnershipC);
    owned_overhead!(outside,purge::OutsideClaim,PurgeOutsideC);
    for v in sources { purge_check_source(v,&mut b)?; }
    for v in custodies { purge_check_custody(v,&mut b)?; }
    for v in parents { purge_check_parent(v,&mut b)?; }
    for v in roots { purge_check_root(v,&mut b)?; }
    for v in namespaces { purge_check_namespace(v,&mut b)?; }
    for v in entries { purge_check_entry(v,&mut b)?; }
    for v in ownership { purge_check_ownership(v,&mut b)?; }
    for v in outside { purge_check_outside(v,&mut b)?; }
    let changes = check_delta(delta,&mut b)?;
    Ok((Capture { binding: purge_owned_binding(&c.binding)?, source_revision:c.source_revision,
        inventory_revision:c.inventory_revision, complete, sources:map(sources,purge_owned_source)?,
        custodies:map(custodies,purge_owned_custody)?, parents:map(parents,purge_owned_parent)?,
        roots:map(roots,purge_owned_root)?, namespaces:map(namespaces,purge_owned_namespace)?,
        entries:map(entries,purge_owned_entry)?, ownership:map(ownership,purge_owned_ownership)?,
        outside:map(outside,purge_owned_outside)? },delta_owned(delta,changes)?))
}
/// # Safety
/// Inputs are recursively immutable/aligned until return. Registry/host access
/// is exclusive; callbacks cannot retain POD or reenter this registry.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_store_ack(c: *const CaptureC,
    delta: *const PurgeOutputDeltaC, ops: *const PurgeHostOpsC,
    out: *mut *mut InventoryAck, error: *mut i32) -> i32
{
    let ops = purge_host_ops(ops);
    owned_abi::owned(out,error,|| {
        let c = purge_versioned(c)?; let delta = purge_versioned(delta)?;
        let (capture,delta) = capture_and_delta(c,delta)?;
        let ops = ops?;
        let registry = ops.registry.as_mut().ok_or(PurgeError::RecoveryRequired)?;
        registry.inner.store_capture(capture,delta,&mut PurgeHostAdapter(&ops))
    })
}
/// # Safety
/// Live owned ACK and initialized version/size output. The borrowed binding and
/// identity remain valid only until that owned ACK is destroyed.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_ack_view(p: *const InventoryAck,
    out: *mut AckViewC,error: *mut i32) -> i32
{
    owned_abi::view(out,error,|| {
        let a = purge_record(p)?;
        Ok(AckViewC { version:1,struct_size:std::mem::size_of::<AckViewC>() as u32,
            binding:purge_binding_view(&a.binding),producer_ticket:a.producer_ticket,delta_sequence:a.delta_sequence,
            prior_inventory_revision:a.prior_inventory_revision,inventory_revision:a.inventory_revision,
            subject_revision:a.subject_revision,final_for_producer:u32::from(a.final_for_producer),reserved:0,
            delta_digest:a.delta_digest,durable:owned_abi::receipt(a.domain,a.publication_sequence,&a.journal_identity,a.payload_digest) })
    })
}
/// # Safety
/// Null or a live exclusive ACK; destroying it never releases producer work.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_ack_destroy(p:*mut InventoryAck) { owned_abi::destroy(p); }
/// # Safety
/// Exact immutable historical key and verified held journal context. No latest
/// snapshot receipt can substitute for the requested original publication.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_ack_lookup(key:*const AckKeyC,
    ops:*const PurgeHostOpsC,out:*mut *mut InventoryAck,error:*mut i32) -> i32
{
    let ops = purge_host_ops(ops);
    owned_abi::owned(out,error,|| {
        let key = purge_versioned(key)?; let mut budget=purge::Budget::new();
        purge_check_binding(&key.binding,&mut budget)?;
        let binding=purge_owned_binding(&key.binding)?;
        let ops=ops?; let registry=purge_record(ops.registry)?;
        registry.inner.lookup_inventory_ack(&binding,key.producer_ticket,key.delta_sequence,key.delta_digest,&PurgeHostAdapter(&ops))
    })
}

#[repr(C)]
#[derive(Clone,Copy)]
pub struct InventoryViewC {
    pub version:u32, pub struct_size:u32, pub inventory:CaptureC,
    pub retained_deltas:*const PurgeOutputDeltaC, pub retained_deltas_count:u32,
    pub reserved:u32, pub durable:DurableReceiptC,
}
struct DeltaViews {
    _before:Vec<PurgeEntryC>, _after:Vec<PurgeEntryC>, _ownership:Vec<PurgeOwnershipC>,
    changes:Vec<PurgeInventoryChangeC>,
}
pub struct InventoryOwned {
    record:journal::inventory::CaptureRecord, _deltas:Vec<journal::OutputDelta>,
    ack:InventoryAck, sources:Vec<PurgeSourceC>, custodies:Vec<PurgeCustodyC>, parents:Vec<PurgeParentC>,
    roots:Vec<PurgeRootC>, namespaces:Vec<PurgeNamespaceC>, entries:Vec<PurgeEntryC>,
    ownership:Vec<PurgeOwnershipC>, outside:Vec<PurgeOutsideC>,
    _delta_views:Vec<DeltaViews>, delta_pods:Vec<PurgeOutputDeltaC>,
}
fn ptr<T>(v:&[T])->*const T { if v.is_empty() { std::ptr::null() } else { v.as_ptr() } }
fn span(v:&[u8])->PurgeBytesC { PurgeBytesC { data:ptr(v),len:v.len() as u32 } }
fn kind(v:purge::EntryKind)->u32 { match v { purge::EntryKind::Regular=>0,purge::EntryKind::Directory=>1,purge::EntryKind::Symlink=>2,purge::EntryKind::Unsupported=>3 } }
fn entry_view(v:&purge::InventoryEntry)->PurgeEntryC {
    PurgeEntryC { id:v.id,root_id:v.root_id,relative_path:span(&v.relative_path),kind:kind(v.kind),
        object_identity:span(&v.object_identity),member:purge_binding_view(&v.member),namespace_proof_id:v.namespace_proof_id,
        ownership_receipt_id:v.ownership_receipt_id,inventory_revision:v.inventory_revision }
}
fn ownership_view(v:&purge::OwnershipReceipt)->PurgeOwnershipC {
    PurgeOwnershipC { id:v.id,member:purge_binding_view(&v.member),root_id:v.root_id,relative_path:span(&v.relative_path),
        kind:kind(v.kind),object_identity:span(&v.object_identity),namespace_proof_id:v.namespace_proof_id,inventory_revision:v.inventory_revision }
}
fn map_view<T,U>(input:&[T],f:impl Fn(&T)->U)->Result<Vec<U>,PurgeError> {
    let mut out=purge::reserved(input.len())?; for v in input { out.push(f(v)); } Ok(out)
}
fn delta_views(d:&journal::OutputDelta)->Result<DeltaViews,PurgeError> {
    // Zero placeholders contain raw POD only and are never exposed for None.
    let before=map_view(&d.changes,|c| c.before.as_ref().map_or_else(||unsafe{std::mem::zeroed()},entry_view))?;
    let after=map_view(&d.changes,|c| c.after.as_ref().map_or_else(||unsafe{std::mem::zeroed()},entry_view))?;
    let ownership=map_view(&d.changes,|c| c.ownership.as_ref().map_or_else(||unsafe{std::mem::zeroed()},ownership_view))?;
    let mut changes=purge::reserved(d.changes.len())?;
    for (i,c) in d.changes.iter().enumerate() {
        changes.push(PurgeInventoryChangeC { entry_id:c.entry_id,
            before:if c.before.is_some(){&before[i]}else{std::ptr::null()},
            after:if c.after.is_some(){&after[i]}else{std::ptr::null()},
            ownership:if c.ownership.is_some(){&ownership[i]}else{std::ptr::null()},prior_absent:u32::from(c.prior_absent) });
    }
    Ok(DeltaViews {_before:before,_after:after,_ownership:ownership,changes})
}
fn inventory_owned(record:journal::inventory::CaptureRecord,deltas:Vec<journal::OutputDelta>,identity:[u8;32]) -> Result<InventoryOwned,PurgeError> {
    let mut budget=purge::Budget::new(); budget.add(record.output_owned_bytes(&deltas)?)?;
    budget.table::<PurgeSourceC>(record.sources.len())?;budget.table::<PurgeCustodyC>(record.custodies.len())?;
    budget.table::<PurgeParentC>(record.parents.len())?;budget.table::<PurgeRootC>(record.roots.len())?;
    budget.table::<PurgeNamespaceC>(record.namespaces.len())?;budget.table::<PurgeEntryC>(record.entries.len())?;
    budget.table::<PurgeOwnershipC>(record.ownership.len())?;budget.table::<PurgeOutsideC>(record.outside.len())?;
    budget.table::<DeltaViews>(deltas.len())?;budget.table::<PurgeOutputDeltaC>(deltas.len())?;
    for d in &deltas {
        budget.table::<PurgeInventoryChangeC>(d.changes.len())?;
        budget.table::<PurgeEntryC>(d.changes.len().checked_mul(2).ok_or(PurgeError::LimitExceeded)?)?;
        budget.table::<PurgeOwnershipC>(d.changes.len())?;
    }
    let ack=record.ack(identity)?;
    let sources=map_view(&record.sources,owned_abi::source_view)?;
    let custodies=map_view(&record.custodies,owned_abi::custody_view)?;
    let parents=map_view(&record.parents,|v|PurgeParentC{file:purge_binding_view(&v.file),collection:purge_binding_view(&v.collection)})?;
    let roots=map_view(&record.roots,|v|PurgeRootC{id:v.id,descriptor_identity:span(&v.descriptor_identity),configured_container:u32::from(v.configured_container)})?;
    let namespaces=map_view(&record.namespaces,|v|PurgeNamespaceC{id:v.id,root_id:v.root_id,relative_path:span(&v.relative_path),root_identity:span(&v.root_identity),ancestor_identity:span(&v.ancestor_identity),mount_identity:span(&v.mount_identity),exclusive:u32::from(v.exclusive)})?;
    let entries=map_view(&record.entries,entry_view)?;
    let ownership=map_view(&record.ownership,ownership_view)?;
    let outside=map_view(&record.outside,|v|PurgeOutsideC{id:v.id,root_id:v.root_id,relative_path:span(&v.relative_path),claimant:purge_binding_view(&v.claimant),object_identity:span(&v.object_identity)})?;
    let mut views=purge::reserved(deltas.len())?;
    for d in &deltas { views.push(delta_views(d)?); }
    let mut pods=purge::reserved(deltas.len())?;
    for (d,v) in deltas.iter().zip(&views) {
        pods.push(PurgeOutputDeltaC{version:1,struct_size:std::mem::size_of::<PurgeOutputDeltaC>() as u32,
            producer_ticket:d.producer_ticket,sequence:d.sequence,prior_inventory_revision:d.prior_inventory_revision,
            changes:ptr(&v.changes),changes_count:v.changes.len() as u32,final_for_producer:u32::from(d.final_for_producer)});
    }
    Ok(InventoryOwned{record,_deltas:deltas,ack,sources,custodies,parents,roots,namespaces,entries,ownership,outside,_delta_views:views,delta_pods:pods})
}
/// # Safety
/// Binding and journal follow the subject_load lifetime/serialization rules.
/// A complete owned snapshot is returned; missing state is never an empty ACK.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_load(binding:*const PurgeBindingC,ops:*const PurgeHostOpsC,
    out:*mut *mut InventoryOwned,error:*mut i32)->i32
{
    let ops=purge_host_ops(ops);
    owned_abi::owned(out,error,||{
        let binding=purge_record(binding)?;let mut budget=purge::Budget::new();purge_check_binding(binding,&mut budget)?;
        let binding=purge_owned_binding(binding)?;let ops=ops?;let registry=purge_record(ops.registry)?;
        let host=PurgeHostAdapter(&ops);let identity=journal::Host::journal_identity(&host)?;
        let (record,deltas)=registry.inner.load_inventory_data(&binding,&host)?;
        inventory_owned(record,deltas,identity)
    })
}
/// # Safety
/// Owner is live through synchronous consumption of every nested view.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_view(p:*const InventoryOwned,out:*mut InventoryViewC,error:*mut i32)->i32 {
    owned_abi::view(out,error,||{
        let v=purge_record(p)?;let r=&v.record;
        Ok(InventoryViewC{version:1,struct_size:std::mem::size_of::<InventoryViewC>() as u32,
            inventory:CaptureC{version:1,struct_size:std::mem::size_of::<CaptureC>() as u32,binding:purge_binding_view(&r.binding),source_revision:r.source_revision,inventory_revision:r.inventory_revision,
                sources:ptr(&v.sources),sources_count:v.sources.len() as u32,custodies:ptr(&v.custodies),custodies_count:v.custodies.len() as u32,
                parents:ptr(&v.parents),parents_count:v.parents.len() as u32,roots:ptr(&v.roots),roots_count:v.roots.len() as u32,
                namespaces:ptr(&v.namespaces),namespaces_count:v.namespaces.len() as u32,entries:ptr(&v.entries),entries_count:v.entries.len() as u32,
                ownership:ptr(&v.ownership),ownership_count:v.ownership.len() as u32,outside:ptr(&v.outside),outside_count:v.outside.len() as u32,complete:u32::from(r.complete),reserved:0},
            retained_deltas:ptr(&v.delta_pods),retained_deltas_count:v.delta_pods.len() as u32,reserved:0,
            durable:owned_abi::receipt(r.domain,r.publication_sequence,&v.ack.journal_identity,v.ack.payload_digest)})
    })
}
/// # Safety
/// Null or live exclusive inventory owner; invalidates all its borrowed views.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_inventory_destroy(p:*mut InventoryOwned){owned_abi::destroy(p);}
