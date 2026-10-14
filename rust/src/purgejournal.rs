//! Version-one durable purge registry. Callers serialize access within one
//! private journal domain. Checksums detect corruption, never authenticate
//! source custody, domain ownership, or a host acknowledgment.
//!
//! A failed/ambiguous publication poisons this registry until a checked complete
//! journal scan is recovered. No subsequent mutation or lease allocation runs.
use crate::dupepurge::*;
use md5::{Digest, Md5};

pub const MAX_FRAMES: usize = 65_536;
pub const MAX_OPERATIONS: usize = 4096;
pub const MAX_OPERATION_BYTES: usize = 5 * MAX_PAYLOAD;
// Additional owned storage inside composed validation, excluding its caller's
// retained registry/candidate. Two logical-image buffers plus two input-sized
// transient copies bound reverse reconstruction; planner input+scratch <=4S.
pub const MAX_COMPOSED_WORKSPACE: usize = 2 * MAX_OPERATION_BYTES + 2 * MAX_PAYLOAD;
pub const CHUNK_BYTES: usize = 64 * 1024;
pub const ACTION_BATCH: usize = 256;
const CHUNK_TAG: u32 = 4;
const COMMIT_TAG: u32 = 5;
const EVENT_TAG: u32 = 6;
const MAGIC: &[u8; 8] = b"NZBPJNL1";
const PLAN_TAG: u32 = 1;
const DOMAIN_TAG: u32 = 2;
const INVENTORY_TAG: u32 = 3;

#[derive(Debug, PartialEq, Eq)]
pub struct Request {
    pub token: [u8; 16],
    pub seeds: Vec<MemberBinding>,
    pub policy: u32,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AckIdentity {
    pub version: u32,
    pub domain: [u8; 16],
    pub manifest_sequence: u64,
    pub token: PurgeToken,
    pub state_revision: u64,
    pub receipt_sequence: u64,
    pub payload_digest: [u8; 32],
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    Fence,
    Drain,
    Revalidate,
    Remove,
    Reconcile,
    Cleanup,
    PersistRemoval,
    Release,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Outcome {
    Acknowledged,
    Removed,
    Absent,
    IdentityMismatch,
    Pending,
    Failed,
}
#[derive(Debug, PartialEq, Eq)]
pub struct OwnerBarrier {
    pub owner_kind: u32,
    pub barrier_revision: u64,
    pub queued: u64,
    pub active: u64,
    pub pinned: u64,
    pub publication: u64,
    pub unacknowledged_deltas: u64,
}
#[derive(Debug, PartialEq, Eq)]
pub struct StopDisposition {
    pub owner_kind: u32,
    pub barrier_revision: u64,
    pub disposition: u32,
}
#[derive(Debug, PartialEq, Eq)]
pub struct FenceReceipt {
    pub already_fenced: bool,
    pub dispositions: Vec<StopDisposition>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct OwnerCoverage {
    pub owner_kind: u32,
    pub barrier_revision: u64,
    pub complete: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct ArtifactCoverage {
    pub kind: u32,
    pub count: u32,
    pub complete: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct StoreReceipt {
    pub identity: Vec<u8>,
    pub revision: u64,
    pub file_synced: bool,
    pub published: bool,
    pub directory_synced: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct ArtifactReceipt {
    pub kind: u32,
    pub member: MemberBinding,
    pub identity: Vec<u8>,
    pub entry_id: Option<u64>,
    pub outcome: Outcome,
    pub error: Option<PurgeError>,
    pub retained_store: Option<Vec<u8>>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct CleanupReceipt {
    pub owners: Vec<OwnerCoverage>,
    pub coverage: Vec<ArtifactCoverage>,
    pub artifacts: Vec<ArtifactReceipt>,
    pub stores: Vec<StoreReceipt>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct PersistenceReceipt {
    pub completed_actions: u64,
    pub action_receipt_high_water: u64,
    pub cleanup_receipt_sequence: u64,
    pub owners: Vec<OwnerCoverage>,
    pub stores: Vec<StoreReceipt>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct Ack {
    pub identity: AckIdentity,
    pub outcome: Outcome,
    pub inventory_revision: u64,
    pub owners: Vec<OwnerBarrier>,
    pub fence: Option<FenceReceipt>,
    pub cleanup: Option<CleanupReceipt>,
    pub persistence: Option<PersistenceReceipt>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct Receipt {
    pub operation: Operation,
    pub action_index: Option<u32>,
    pub state_revision: u64,
    pub receipt_sequence: u64,
    pub payload_digest: [u8; 32],
    pub outcome: Outcome,
    pub owners: Vec<OwnerBarrier>,
    pub fence: Option<FenceReceipt>,
    pub cleanup: Option<CleanupReceipt>,
    pub persistence: Option<PersistenceReceipt>,
}
#[derive(Debug, PartialEq, Eq)]
pub struct ActionReceipt {
    pub index: u32,
    pub pending_revision: u64,
    pub outcome: Option<Outcome>,
    pub receipt_sequence: u64,
    pub payload_digest: [u8; 32],
}
#[derive(Debug, PartialEq, Eq)]
pub struct JournalState {
    pub domain: [u8; 16],
    pub journal_identity: [u8; 32],
    pub global_sequence: u64,
    pub manifest_sequence: u64,
    pub high_water: u64,
    pub request: Request,
    pub request_bytes: Vec<u8>,
    pub request_fingerprint: [u8; 16],
    pub state_revision: u64,
    pub receipt_sequence: u64,
    pub barrier_revision: u64,
    pub required_owners: Vec<u32>,
    pub receipts: Vec<Receipt>,
    pub actions: Vec<ActionReceipt>,
    pub released: bool,
    pub error: Option<PurgeError>,
    pub resume_phase: Phase,
    pub deltas: Vec<BoundDelta>,
}
/// All pointers borrowed by a host expire when execute returns. Implementations
/// must return actual checked results, catch foreign exceptions, and never use
/// a pre-unlink identity check as a compare-and-delete primitive.
pub struct Call<'a> {
    pub identity: AckIdentity,
    pub operation: Operation,
    pub action: Option<&'a Action>,
    pub barrier_revision: u64,
    pub required_owners: &'a [u32],
    pub inventory_revision: u64,
    pub receipt_budget: usize,
    pub plan: &'a Plan,
}
pub struct PublicationAck {
    pub sequence: u64,
    pub frame: Vec<u8>,
    pub file_synced: bool,
    pub published: bool,
    pub directory_synced: bool,
}
pub trait Host {
    /// True only when every required checked lifecycle/platform capability is
    /// implemented. Partial implementations must return false before publication.
    fn supported(&self) -> bool;
    /// Mechanically read the actual retained private directory descriptor.
    /// This is full identity data, never a supplied label or checksum authority.
    fn journal_identity(&self) -> Result<[u8; 32], PurgeError>;
    fn publish(&mut self, sequence: u64, frame: &[u8]) -> Result<PublicationAck, PurgeError>;
    fn execute(&mut self, call: &Call<'_>) -> Result<Ack, PurgeError>;
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reservation {
    New(usize),
    Existing(usize),
    Conflict,
}
#[derive(Debug, PartialEq, Eq)]
pub struct InventoryChange {
    pub entry_id: u64,
    pub before: Option<InventoryEntry>,
    pub after: Option<InventoryEntry>,
    pub ownership: Option<OwnershipReceipt>,
    /// A rename/retirement needs a checked retained publication outcome.
    pub prior_absent: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct OutputDelta {
    pub producer_ticket: u64,
    pub sequence: u64,
    pub prior_inventory_revision: u64,
    pub changes: Vec<InventoryChange>,
    pub final_for_producer: bool,
}
#[derive(Debug, PartialEq, Eq)]
struct InventoryFrame {
    domain: [u8; 16],
    sequence: u64,
    high_water: u64,
    binding: MemberBinding,
    delta: OutputDelta,
}
#[derive(Debug, PartialEq, Eq)]
pub struct BoundDelta {
    pub binding: MemberBinding,
    pub delta: OutputDelta,
}
#[derive(Debug)]
pub struct Registry {
    domain: [u8; 16],
    journal_identity: [u8; 32],
    sequence: u64,
    high_water: u64,
    operations: Vec<Plan>,
    inventory: Vec<InventoryFrame>,
    recovery_required: bool,
}

// Explicit counted little-endian encoding. The first pass bounds the COMPLETE
// output before reserving it; the second never grows its allocation. Decoding
// charges both fixed owned storage and every variable field before allocation.
struct Writer {
    bytes: Vec<u8>,
    size: usize,
    measuring: bool,
}
impl Writer {
    fn put(&mut self, b: &[u8]) -> Result<(), PurgeError> {
        self.size = self
            .size
            .checked_add(b.len())
            .ok_or(PurgeError::LimitExceeded)?;
        if self.size > MAX_OPERATION_BYTES {
            return Err(PurgeError::LimitExceeded);
        }
        if !self.measuring {
            self.bytes.extend_from_slice(b);
        }
        Ok(())
    }
}
struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
    owned: usize,
    owned_limit: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], PurgeError> {
        let end = self
            .offset
            .checked_add(n)
            .ok_or(PurgeError::CorruptJournal)?;
        let b = self
            .bytes
            .get(self.offset..end)
            .ok_or(PurgeError::CorruptJournal)?;
        self.offset = end;
        Ok(b)
    }
    fn charge(&mut self, n: usize) -> Result<(), PurgeError> {
        self.owned = self.owned.checked_add(n).ok_or(PurgeError::LimitExceeded)?;
        if self.owned > self.owned_limit {
            return Err(PurgeError::LimitExceeded);
        }
        Ok(())
    }
    // Nested schema budgets charge the same allocations as the outer composed
    // budget. Restore the caller's limit on errors as well as successful reads.
    fn within_heap<T>(
        &mut self,
        additional: usize,
        read: impl FnOnce(&mut Self) -> Result<T, PurgeError>,
    ) -> Result<T, PurgeError> {
        let old = self.owned_limit;
        self.owned_limit = old.min(
            self.owned.checked_add(additional).ok_or(PurgeError::LimitExceeded)?,
        );
        let result = read(self);
        self.owned_limit = old;
        result
    }
}
trait Wire: Sized {
    const MIN: usize;
    fn heap_size(&self) -> Result<usize, PurgeError> {
        Ok(0)
    }
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError>;
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError>;
}
macro_rules! number {
    ($($t:ty),*) => {$ (impl Wire for $t {
        const MIN:usize=std::mem::size_of::<Self>();
        fn put(&self,w:&mut Writer)->Result<(),PurgeError>{w.put(&self.to_le_bytes())}
        fn get(r:&mut Reader<'_>)->Result<Self,PurgeError>{let mut a=[0;std::mem::size_of::<Self>()];a.copy_from_slice(r.take(<Self as Wire>::MIN)?);Ok(Self::from_le_bytes(a))}
    })*};
}
number!(u8, u32, i32, u64);
impl Wire for bool {
    const MIN: usize = 1;
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError> {
        (*self as u8).put(w)
    }
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError> {
        match u8::get(r)? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(PurgeError::CorruptJournal),
        }
    }
}
impl<const N: usize> Wire for [u8; N] {
    const MIN: usize = N;
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError> {
        w.put(self)
    }
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError> {
        let mut b = [0; N];
        b.copy_from_slice(r.take(N)?);
        Ok(b)
    }
}
impl<T: Wire> Wire for Option<T> {
    const MIN: usize = 1;
    fn heap_size(&self) -> Result<usize, PurgeError> {
        match self {
            Some(v) => v.heap_size(),
            None => Ok(0),
        }
    }
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError> {
        self.is_some().put(w)?;
        if let Some(v) = self {
            v.put(w)?;
        }
        Ok(())
    }
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError> {
        if bool::get(r)? {
            Ok(Some(T::get(r)?))
        } else {
            Ok(None)
        }
    }
}
impl<T: Wire> Wire for Vec<T> {
    const MIN: usize = 4;
    fn heap_size(&self) -> Result<usize, PurgeError> {
        let mut n = self
            .capacity()
            .checked_mul(std::mem::size_of::<T>())
            .ok_or(PurgeError::LimitExceeded)?;
        for v in self {
            n = n
                .checked_add(v.heap_size()?)
                .ok_or(PurgeError::LimitExceeded)?;
        }
        Ok(n)
    }
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError> {
        if self.len() > MAX_PAYLOAD {
            return Err(PurgeError::LimitExceeded);
        }
        u32::try_from(self.len())
            .map_err(|_| PurgeError::LimitExceeded)?
            .put(w)?;
        for v in self {
            v.put(w)?;
        }
        Ok(())
    }
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError> {
        Self::get_bounded(r, usize::MAX)
    }
}
// Bounds are declared on fields, not inferred from Vec's element type: seeds,
// members and arbitrary secondary tables have different accepted limits.
trait BoundedWire: Wire {
    fn get_bounded(r: &mut Reader<'_>, maximum: usize) -> Result<Self, PurgeError>;
}
impl<T: Wire> BoundedWire for Vec<T> {
    fn get_bounded(r: &mut Reader<'_>, maximum: usize) -> Result<Self, PurgeError> {
        let n = u32::get(r)? as usize;
        if n > maximum {
            return Err(PurgeError::LimitExceeded);
        }
        let minimum = n.checked_mul(T::MIN).ok_or(PurgeError::LimitExceeded)?;
        if minimum > r.bytes.len() - r.offset {
            return Err(PurgeError::CorruptJournal);
        }
        r.charge(
            n.checked_mul(std::mem::size_of::<T>())
                .ok_or(PurgeError::LimitExceeded)?,
        )?;
        let mut out = reserved(n)?;
        for _ in 0..n {
            out.push(T::get(r)?);
        }
        Ok(out)
    }
}
impl<T: BoundedWire> BoundedWire for Option<T> {
    fn get_bounded(r: &mut Reader<'_>, maximum: usize) -> Result<Self, PurgeError> {
        if bool::get(r)? {
            Ok(Some(T::get_bounded(r, maximum)?))
        } else {
            Ok(None)
        }
    }
}
macro_rules! read_field {
    ($r:ident, $maximum:expr) => { BoundedWire::get_bounded($r, $maximum) };
    ($r:ident) => { Wire::get($r) };
}
macro_rules! fields {
    ($t:ty; $($f:ident $(=> $cap:expr)?),+ $(,)?) => {
        fields!($t, MAX_OPERATION_BYTES; $($f $(=> $cap)?),+);
    };
    ($t:ty, $budget:expr; $($f:ident $(=> $cap:expr)?),+ $(,)?) => {impl Wire for $t {
        const MIN:usize=1;
        fn heap_size(&self)->Result<usize,PurgeError>{let mut n=0usize;$ (n=n.checked_add(self.$f.heap_size()?).ok_or(PurgeError::LimitExceeded)?;)*Ok(n)}
        fn put(&self,w:&mut Writer)->Result<(),PurgeError>{$ (self.$f.put(w)?;)* Ok(())}
        fn get(r:&mut Reader<'_>)->Result<Self,PurgeError>{
            r.within_heap($budget, |r| Ok(Self {$($f:read_field!(r $(,$cap)?)?,)*}))
        }
    }};
}
macro_rules! tags {
    ($t:ty; $($v:ident=$n:literal),+ $(,)?)=>{impl Wire for $t {
        const MIN:usize=4;
        fn put(&self,w:&mut Writer)->Result<(),PurgeError>{let n:u32=match self {$(Self::$v=>$n,)*};n.put(w)}
        fn get(r:&mut Reader<'_>)->Result<Self,PurgeError>{match u32::get(r)? {$($n=>Ok(Self::$v),)*_=>Err(PurgeError::CorruptJournal)}}
    }};
}
tags!(MemberKind;Queue=0,Post=1,History=2,CompactHistory=3);
tags!(EntryKind;Regular=0,Directory=1,Symlink=2,Unsupported=3);
tags!(Phase;Prepared=0,Stopping=1,Quiescent=2,Cleaning=3,Persisting=4,Complete=5,Failed=6);
tags!(PurgeError;InvalidInput=1,MissingSeed=2,MissingInventory=3,Conflict=4,LimitExceeded=5,Unsupported=6,AllocationFailure=7,Persistence=8,HostFailure=9,CorruptJournal=10,RecoveryRequired=11);
tags!(Operation;Fence=1,Drain=2,Revalidate=3,Remove=4,Reconcile=5,Cleanup=6,PersistRemoval=7,Release=8);
tags!(Outcome;Acknowledged=0,Removed=1,Absent=2,IdentityMismatch=3,Pending=4,Failed=5);
fields!(MemberBinding;collection_id,file_id,incarnation,posting_source => MAX_IDENTITY);
fields!(MemberRecord;binding,name => MAX_IDENTITY,key => MAX_IDENTITY,kind,complete_inventory,source_validation_id);
fields!(SourceValidation;id,version,validator_version,source_record_id,source_bytes_digest,binding,parent_collection,custody_receipt_id);
fields!(CustodyReceipt;id,validator_version,source_record_id,source_bytes_digest);
fields!(ParentMembership;file,collection);
fields!(ComparisonContext;captured => MAX_IDENTITY,current => MAX_IDENTITY);
fields!(AnchorComparison;seed,candidate,name_equal,key_equal);
fields!(DirectBinding;seed,candidate,seed_source_validation_id,candidate_source_validation_id,pair_membership_receipt_id);
fields!(PairMembershipReceipt;id,version,validator_version,owner_kind,seed,candidate,seed_source_record_id,seed_source_bytes_digest,candidate_source_record_id,candidate_source_bytes_digest,relation_id => MAX_IDENTITY,evidence_version,evidence_id,evidence_bytes => MAX_IDENTITY,custody_receipt_id);
fields!(PairCustodyReceipt;id,version,validator_version,owner_kind,relation_id => MAX_IDENTITY,evidence_version,evidence_id,evidence_bytes => MAX_IDENTITY,seed,candidate,seed_source_record_id,seed_source_bytes_digest,candidate_source_record_id,candidate_source_bytes_digest);
fields!(RootRecord;id,descriptor_identity => MAX_IDENTITY,configured_container);
fields!(NamespaceProof;id,root_id,relative_path => MAX_PATH,root_identity => MAX_IDENTITY,ancestor_identity => MAX_IDENTITY,mount_identity => MAX_IDENTITY,exclusive);
fields!(InventoryEntry;id,root_id,relative_path => MAX_PATH,kind,object_identity => MAX_IDENTITY,member,namespace_proof_id,ownership_receipt_id,inventory_revision);
fields!(OwnershipReceipt;id,member,root_id,relative_path => MAX_PATH,kind,object_identity => MAX_IDENTITY,namespace_proof_id,inventory_revision);
fields!(OutsideClaim;id,root_id,relative_path => MAX_PATH,claimant,object_identity => MAX_IDENTITY);
fields!(Snapshot, MAX_PAYLOAD;version,revision,generation,seeds => MAX_SEEDS,members => MAX_MEMBERS,source_validations,custody_receipts,parents,comparison_context,comparisons,direct_bindings,pair_memberships,pair_custody_receipts,roots,namespace_proofs,entries => MAX_ENTRIES,ownership_receipts,outside_claims);
fields!(PurgeToken;request,generation,members => MAX_MEMBERS);
fields!(Request;token,seeds => MAX_SEEDS,policy);
fields!(AckIdentity;version,domain,manifest_sequence,token,state_revision,receipt_sequence,payload_digest);
fields!(OwnerBarrier;owner_kind,barrier_revision,queued,active,pinned,publication,unacknowledged_deltas);
fields!(StopDisposition;owner_kind,barrier_revision,disposition);
fields!(FenceReceipt;already_fenced,dispositions => MAX_MEMBERS);
fields!(OwnerCoverage;owner_kind,barrier_revision,complete);
fields!(ArtifactCoverage;kind,count,complete);
fields!(StoreReceipt;identity => MAX_IDENTITY,revision,file_synced,published,directory_synced);
fields!(ArtifactReceipt;kind,member,identity => MAX_IDENTITY,entry_id,outcome,error,retained_store => MAX_IDENTITY);
fields!(CleanupReceipt;owners => MAX_MEMBERS,coverage => 7,artifacts => MAX_ENTRIES,stores => MAX_ENTRIES);
fields!(PersistenceReceipt;completed_actions,action_receipt_high_water,cleanup_receipt_sequence,owners => MAX_MEMBERS,stores => MAX_ENTRIES);
fields!(Ack;identity,outcome,inventory_revision,owners => MAX_MEMBERS,fence,cleanup,persistence);
fields!(Receipt, MAX_PAYLOAD - std::mem::size_of::<Receipt>();operation,action_index,state_revision,receipt_sequence,payload_digest,outcome,owners => MAX_MEMBERS,fence,cleanup,persistence);
fields!(ActionReceipt;index,pending_revision,outcome,receipt_sequence,payload_digest);
fields!(InventoryChange;entry_id,before,after,ownership,prior_absent);
fields!(OutputDelta, MAX_PAYLOAD - std::mem::size_of::<OutputDelta>();producer_ticket,sequence,prior_inventory_revision,changes => MAX_ENTRIES,final_for_producer);
fields!(BoundDelta;binding,delta);
fields!(InventoryFrame;domain,sequence,high_water,binding,delta);
fields!(JournalState;domain,journal_identity,global_sequence,manifest_sequence,high_water,request,request_bytes,request_fingerprint,state_revision,receipt_sequence,barrier_revision,required_owners => MAX_MEMBERS,receipts => MAX_FRAMES,actions => MAX_ENTRIES,released,error,resume_phase,deltas => MAX_FRAMES);
fields!(Plan;snapshot,token,phase,actions => MAX_ENTRIES,journal);
impl Wire for Action {
    const MIN: usize = 4;
    fn heap_size(&self) -> Result<usize, PurgeError> {
        match self {
            Self::RemoveEntry {
                relative_path,
                object_identity,
                ..
            }
            | Self::RemoveTree {
                relative_path,
                object_identity,
                ..
            } => relative_path
                .len()
                .checked_add(object_identity.len())
                .ok_or(PurgeError::LimitExceeded),
        }
    }
    fn put(&self, w: &mut Writer) -> Result<(), PurgeError> {
        match self {
            Action::RemoveEntry {
                entry_id,
                root_id,
                relative_path,
                kind,
                object_identity,
            } => {
                0u32.put(w)?;
                entry_id.put(w)?;
                root_id.put(w)?;
                relative_path.put(w)?;
                kind.put(w)?;
                object_identity.put(w)
            }
            Action::RemoveTree {
                entry_id,
                root_id,
                relative_path,
                object_identity,
            } => {
                1u32.put(w)?;
                entry_id.put(w)?;
                root_id.put(w)?;
                relative_path.put(w)?;
                object_identity.put(w)
            }
        }
    }
    fn get(r: &mut Reader<'_>) -> Result<Self, PurgeError> {
        match u32::get(r)? {
            0 => Ok(Action::RemoveEntry {
                entry_id: Wire::get(r)?,
                root_id: Wire::get(r)?,
                relative_path: BoundedWire::get_bounded(r, MAX_PATH)?,
                kind: Wire::get(r)?,
                object_identity: BoundedWire::get_bounded(r, MAX_IDENTITY)?,
            }),
            1 => Ok(Action::RemoveTree {
                entry_id: Wire::get(r)?,
                root_id: Wire::get(r)?,
                relative_path: BoundedWire::get_bounded(r, MAX_PATH)?,
                object_identity: BoundedWire::get_bounded(r, MAX_IDENTITY)?,
            }),
            _ => Err(PurgeError::CorruptJournal),
        }
    }
}
fn wire<T: Wire>(value: &T) -> Result<Vec<u8>, PurgeError> {
    let mut w = Writer {
        bytes: Vec::new(),
        size: 0,
        measuring: true,
    };
    value.put(&mut w)?;
    let mut w = Writer {
        bytes: reserved(w.size)?,
        size: 0,
        measuring: false,
    };
    value.put(&mut w)?;
    Ok(w.bytes)
}
fn unwire<T: Wire>(bytes: &[u8]) -> Result<T, PurgeError> {
    if bytes.len() > MAX_OPERATION_BYTES {
        return Err(PurgeError::LimitExceeded);
    }
    let mut r = Reader {
        bytes,
        offset: 0,
        owned: std::mem::size_of::<T>(),
        owned_limit: MAX_OPERATION_BYTES,
    };
    let v = T::get(&mut r)?;
    if r.offset != bytes.len() {
        return Err(PurgeError::CorruptJournal);
    }
    Ok(v)
}
fn owned_size<T: Wire>(value: &T) -> Result<usize, PurgeError> {
    std::mem::size_of::<T>()
        .checked_add(value.heap_size()?)
        .ok_or(PurgeError::LimitExceeded)
}
fn copy<T: Wire>(value: &T) -> Result<T, PurgeError> {
    unwire(&wire(value)?)
}
fn checksum(bytes: &[u8]) -> [u8; 16] {
    Md5::digest(bytes).into()
}
fn payload_identity(bytes: &[u8]) -> [u8; 32] {
    // Two explicitly domain-separated MD5 values: opaque corruption/index aid,
    // NEVER authentication. ACK validation also compares the full retained token.
    let mut out = [0; 32];
    let mut d = Md5::new();
    d.update(b"purge-payload-v1:a");
    d.update(bytes);
    out[..16].copy_from_slice(&d.finalize());
    let mut d = Md5::new();
    d.update(b"purge-payload-v1:b");
    d.update(bytes);
    out[16..].copy_from_slice(&d.finalize());
    out
}
fn frame<T: Wire>(tag: u32, value: &T) -> Result<Vec<u8>, PurgeError> {
    let body = wire(value)?;
    let total = body
        .len()
        .checked_add(36)
        .ok_or(PurgeError::LimitExceeded)?;
    if total > MAX_PAYLOAD {
        return Err(PurgeError::LimitExceeded);
    }
    let mut out = reserved(total)?;
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&1u32.to_le_bytes());
    out.extend_from_slice(&tag.to_le_bytes());
    out.extend_from_slice(&(body.len() as u32).to_le_bytes());
    out.extend_from_slice(&body);
    let sum = checksum(&out);
    out.extend_from_slice(&sum);
    Ok(out)
}
fn unframe(bytes: &[u8]) -> Result<(u32, &[u8]), PurgeError> {
    if bytes.len() < 36 || bytes.len() > MAX_PAYLOAD {
        return Err(PurgeError::CorruptJournal);
    }
    if &bytes[..8] != MAGIC || bytes[8..12] != 1u32.to_le_bytes() {
        return Err(PurgeError::CorruptJournal);
    }
    let mut a = [0; 4];
    a.copy_from_slice(&bytes[12..16]);
    let tag = u32::from_le_bytes(a);
    a.copy_from_slice(&bytes[16..20]);
    let n = u32::from_le_bytes(a) as usize;
    if n.checked_add(36) != Some(bytes.len())
        || checksum(&bytes[..bytes.len() - 16]) != bytes[bytes.len() - 16..]
    {
        return Err(PurgeError::CorruptJournal);
    }
    Ok((tag, &bytes[20..20 + n]))
}
fn canonical_request(request: &mut Request) -> Result<Vec<u8>, PurgeError> {
    if request.policy != 1 || request.seeds.is_empty() || request.seeds.len() > MAX_SEEDS {
        return Err(PurgeError::InvalidInput);
    }
    request.seeds.sort_unstable();
    request.seeds.dedup();
    for b in &request.seeds {
        if b.collection_id <= 0
            || b.file_id.is_some_and(|x| x <= 0)
            || b.incarnation == 0
            || b.incarnation == u64::MAX
            || b.posting_source.is_empty()
            || b.posting_source.len() > MAX_IDENTITY
            || b.posting_source.contains(&0)
        {
            return Err(PurgeError::InvalidInput);
        }
    }
    // Request token is separately authoritative; including it makes mismatched
    // tokens unambiguously distinct even when the selected bindings are equal.
    wire(request)
}
// A composed inventory retains the captured revision on each entry/receipt.
// Reconstruct and validate the original snapshot before making a temporary
// planner view. The view's revision normalization is never stored, published,
// or exposed as ownership authority; all paths/object/member bytes stay exact.
fn prepared_inventory(p: &Plan) -> Result<Plan, PurgeError> {
    let deltas = p
        .journal
        .as_ref()
        .map(|j| j.deltas.as_slice())
        .unwrap_or(&[]);
    if deltas.is_empty() {
        return prepare(copy(&p.snapshot)?, p.token.request);
    }
    if owned_size(p)? > MAX_OPERATION_BYTES || deltas.len() > MAX_FRAMES {
        return Err(PurgeError::LimitExceeded);
    }
    let snapshot_size = owned_size(&p.snapshot)?;
    let mut reverse_bound = snapshot_size;
    let mut restore_count = p.snapshot.entries.len();
    for (index, bound) in deltas.iter().enumerate() {
        let d = &bound.delta;
        if !p.token.members.contains(&bound.binding) {
            return Err(PurgeError::CorruptJournal);
        }
        validate_delta(&bound.binding, d)?;
        if let Some(prior) = deltas[..index]
            .iter()
            .rev()
            .find(|v| v.binding == bound.binding && v.delta.producer_ticket == d.producer_ticket)
        {
            if prior.delta.final_for_producer || d.sequence != next(prior.delta.sequence)? {
                return Err(PurgeError::CorruptJournal);
            }
        } else if d.sequence != 1 {
            return Err(PurgeError::CorruptJournal);
        }
        for c in &d.changes {
            if let Some(before) = &c.before {
                reverse_bound = reverse_bound
                    .checked_add(owned_size(before)?)
                    .ok_or(PurgeError::LimitExceeded)?;
                restore_count = restore_count
                    .checked_add(1)
                    .ok_or(PurgeError::LimitExceeded)?;
            }
        }
    }
    // Source snapshot plus every possible restored before-record is bounded by
    // the counted retained Plan. Pre-reserve slots once; no reverse-loop growth.
    if reverse_bound > MAX_OPERATION_BYTES
        || reverse_bound
            .checked_add(snapshot_size)
            .and_then(|v| v.checked_add(2 * MAX_PAYLOAD))
            .ok_or(PurgeError::LimitExceeded)?
            > MAX_COMPOSED_WORKSPACE
    {
        return Err(PurgeError::LimitExceeded);
    }
    let mut base = copy(&p.snapshot)?;
    base.entries
        .try_reserve_exact(restore_count - base.entries.len())
        .map_err(|_| PurgeError::AllocationFailure)?;
    for bound in deltas.iter().rev() {
        let d = &bound.delta;
        if next(d.prior_inventory_revision)? != base.revision {
            return Err(PurgeError::CorruptJournal);
        }
        for c in d.changes.iter().rev() {
            let existing = base.entries.iter().position(|e| e.id == c.entry_id);
            match (&c.after, existing) {
                (Some(after), Some(n)) if &base.entries[n] == after => {
                    let receipt = c.ownership.as_ref().ok_or(PurgeError::CorruptJournal)?;
                    if !base.ownership_receipts.contains(receipt) {
                        return Err(PurgeError::CorruptJournal);
                    }
                    base.entries.remove(n);
                }
                (None, None) => {}
                _ => return Err(PurgeError::CorruptJournal),
            }
            if let Some(before) = &c.before {
                base.entries.push(copy(before)?);
            }
        }
        base.revision = d.prior_inventory_revision;
    }
    let planner = planning_allocation_bound(&base)?;
    if owned_size(&base)?
        .checked_add(planner)
        .ok_or(PurgeError::LimitExceeded)?
        > MAX_COMPOSED_WORKSPACE
    {
        return Err(PurgeError::LimitExceeded);
    }
    let original = prepare(base, p.token.request)?;
    if original.token != p.token {
        return Err(PurgeError::CorruptJournal);
    }
    drop(original); // Do not retain base while copying/replanning the view.
    let planner = planning_allocation_bound(&p.snapshot)?;
    if snapshot_size
        .checked_add(planner)
        .ok_or(PurgeError::LimitExceeded)?
        > MAX_COMPOSED_WORKSPACE
    {
        return Err(PurgeError::LimitExceeded);
    }
    let mut view = copy(&p.snapshot)?;
    for e in &mut view.entries {
        let receipt = view
            .ownership_receipts
            .iter_mut()
            .find(|o| o.id == e.ownership_receipt_id)
            .ok_or(PurgeError::MissingInventory)?;
        if receipt.inventory_revision != e.inventory_revision {
            return Err(PurgeError::Conflict);
        }
        e.inventory_revision = view.revision;
        receipt.inventory_revision = view.revision;
    }
    prepare(view, p.token.request)
}
fn validate_plan(p: &Plan) -> Result<(), PurgeError> {
    let expected = prepared_inventory(p)?;
    if expected.token != p.token || expected.actions != p.actions {
        return Err(PurgeError::CorruptJournal);
    }
    if let Some(j) = &p.journal {
        let mut request = copy(&j.request)?;
        if canonical_request(&mut request)? != j.request_bytes
            || checksum(&j.request_bytes) != j.request_fingerprint
            || request.token != p.token.request
            || request.seeds != p.snapshot.seeds
        {
            return Err(PurgeError::CorruptJournal);
        }
        if &j.journal_identity[..8] != b"NZBPJID1"
            || j.global_sequence < 2
            || j.global_sequence >= u64::MAX
            || j.high_water < p.token.generation
            || j.high_water >= u64::MAX
            || j.state_revision == 0
            || j.barrier_revision == 0
            || j.receipt_sequence >= u64::MAX
            || j.required_owners.is_empty()
            || j.required_owners.len() > MAX_MEMBERS
            || j.required_owners.windows(2).any(|x| x[0] >= x[1])
            || j.required_owners.contains(&0)
        {
            return Err(PurgeError::CorruptJournal);
        }
        if j.released && p.phase != Phase::Complete
            || (p.phase == Phase::Failed) != j.error.is_some()
            || j.actions.len() != p.actions.len()
            || j.receipts.len() > MAX_FRAMES
        {
            return Err(PurgeError::CorruptJournal);
        }
        for (i, a) in j.actions.iter().enumerate() {
            if a.index as usize != i
                || a.pending_revision > j.state_revision
                || a.outcome
                    .is_some_and(|o| !matches!(o, Outcome::Removed | Outcome::Absent))
                || a.outcome.is_some() && a.pending_revision == 0
            {
                return Err(PurgeError::CorruptJournal);
            }
        }
        let mut sequence = 0;
        for receipt in &j.receipts {
            validate_receipt(p, receipt)?;
            if receipt.receipt_sequence <= sequence
                || receipt.receipt_sequence > j.receipt_sequence
                || receipt.state_revision > j.state_revision
                || receipt.action_index.is_some()
            {
                return Err(PurgeError::CorruptJournal);
            }
            sequence = receipt.receipt_sequence;
        }
    } else if p.phase != Phase::Prepared {
        return Err(PurgeError::CorruptJournal);
    }
    Ok(())
}
pub fn encode(plan: &Plan) -> Result<Vec<u8>, PurgeError> {
    validate_plan(plan)?;
    frame(PLAN_TAG, plan)
}
pub fn decode(bytes: &[u8]) -> Result<Plan, PurgeError> {
    let (tag, body) = unframe(bytes)?;
    if tag != PLAN_TAG {
        return Err(PurgeError::CorruptJournal);
    }
    let p = unwire(body)?;
    validate_plan(&p)?;
    Ok(p)
}

#[derive(Debug)]
struct DomainFrame {
    domain: [u8; 16],
    journal_identity: [u8; 32],
    sequence: u64,
    high_water: u64,
}
#[derive(Debug)]
struct Chunk {
    domain: [u8; 16],
    sequence: u64,
    high_water: u64,
    request: [u8; 16],
    generation: u64,
    start: u64,
    index: u32,
    count: u32,
    kind: u32,
    image_bytes: u64,
    bytes: Vec<u8>,
}
#[derive(Debug, PartialEq, Eq)]
struct ChunkId {
    sequence: u64,
    bytes: u32,
    checksum: [u8; 16],
}
#[derive(Debug)]
struct Commit {
    domain: [u8; 16],
    sequence: u64,
    high_water: u64,
    request: [u8; 16],
    generation: u64,
    start: u64,
    kind: u32,
    image_bytes: u64,
    checksum: [u8; 16],
    chunks: Vec<ChunkId>,
}
#[derive(Debug)]
struct Event {
    domain: [u8; 16],
    sequence: u64,
    high_water: u64,
    request: [u8; 16],
    generation: u64,
    manifest_sequence: u64,
    previous_revision: u64,
    state_revision: u64,
    receipt_sequence: u64,
    phase: Phase,
    barrier_revision: u64,
    released: bool,
    error: Option<PurgeError>,
    resume_phase: Phase,
    receipt: Option<Receipt>,
    updates: Vec<ActionReceipt>,
}
fields!(DomainFrame;domain,journal_identity,sequence,high_water);
fields!(Chunk;domain,sequence,high_water,request,generation,start,index,count,kind,image_bytes,bytes => CHUNK_BYTES);
fields!(ChunkId;sequence,bytes,checksum);
fields!(Commit;domain,sequence,high_water,request,generation,start,kind,image_bytes,checksum,chunks => MAX_OPERATION_BYTES.div_ceil(CHUNK_BYTES));
fields!(Event;domain,sequence,high_water,request,generation,manifest_sequence,previous_revision,state_revision,receipt_sequence,phase,barrier_revision,released,error,resume_phase,receipt,updates => ACTION_BATCH);
fn next(n: u64) -> Result<u64, PurgeError> {
    let v = n.checked_add(1).ok_or(PurgeError::LimitExceeded)?;
    if v == u64::MAX {
        return Err(PurgeError::LimitExceeded);
    }
    Ok(v)
}
fn append<T>(items: &mut Vec<T>, value: T) -> Result<(), PurgeError> {
    items
        .try_reserve_exact(1)
        .map_err(|_| PurgeError::AllocationFailure)?;
    items.push(value);
    Ok(())
}
fn state(p: &Plan) -> Result<&JournalState, PurgeError> {
    p.journal.as_ref().ok_or(PurgeError::InvalidInput)
}
fn state_mut(p: &mut Plan) -> Result<&mut JournalState, PurgeError> {
    p.journal.as_mut().ok_or(PurgeError::InvalidInput)
}
fn same_number(a: &MemberBinding, b: &MemberBinding) -> bool {
    a.collection_id == b.collection_id
        && (a.file_id.is_none() || b.file_id.is_none() || a.file_id == b.file_id)
}
fn prefix(a: &[u8], b: &[u8]) -> bool {
    a.is_empty() || a == b || (b.starts_with(a) && b.get(a.len()) == Some(&b'/'))
}
fn action_path(a: &Action) -> (u64, &[u8]) {
    match a {
        Action::RemoveEntry {
            root_id,
            relative_path,
            ..
        }
        | Action::RemoveTree {
            root_id,
            relative_path,
            ..
        } => (*root_id, relative_path),
    }
}
fn overlaps(a: &Plan, b: &Plan) -> bool {
    if a.token.members.iter().any(|x| {
        b.token
            .members
            .iter()
            .any(|y| same_number(x, y) || x.posting_source == y.posting_source)
    }) {
        return true;
    }
    for x in &a.actions {
        let (xr, xp) = action_path(x);
        let Some(xroot) = a.snapshot.roots.iter().find(|r| r.id == xr) else {
            return true;
        };
        for y in &b.actions {
            let (yr, yp) = action_path(y);
            let Some(yroot) = b.snapshot.roots.iter().find(|r| r.id == yr) else {
                return true;
            };
            if xroot.descriptor_identity != yroot.descriptor_identity
                || prefix(xp, yp)
                || prefix(yp, xp)
            {
                return true;
            }
        }
    }
    // An exclusive namespace reserves its entire proven cleanup scope, even
    // when its currently inventoried leaves are disjoint or empty. Shared
    // ancestor proofs do not themselves claim the independently owned leaves.
    for (left, right) in [(a, b), (b, a)] {
        for scope in left
            .snapshot
            .namespace_proofs
            .iter()
            .filter(|n| n.exclusive)
        {
            for action in &right.actions {
                let (root_id, path) = action_path(action);
                let Some(root) = right.snapshot.roots.iter().find(|r| r.id == root_id) else {
                    return true;
                };
                if scope.root_identity != root.descriptor_identity
                    || prefix(&scope.relative_path, path)
                    || prefix(path, &scope.relative_path)
                {
                    return true;
                }
            }
            for other in right
                .snapshot
                .namespace_proofs
                .iter()
                .filter(|n| n.exclusive)
            {
                if scope.root_identity != other.root_identity
                    || prefix(&scope.relative_path, &other.relative_path)
                    || prefix(&other.relative_path, &scope.relative_path)
                {
                    return true;
                }
            }
        }
    }
    false
}
fn empty_actions(n: usize) -> Result<Vec<ActionReceipt>, PurgeError> {
    let mut v = reserved(n)?;
    for i in 0..n {
        v.push(ActionReceipt {
            index: i as u32,
            pending_revision: 0,
            outcome: None,
            receipt_sequence: 0,
            payload_digest: [0; 32],
        });
    }
    Ok(v)
}
fn future_owned(p: &Plan) -> Result<usize, PurgeError> {
    let j = state(p)?;
    if j.released {
        return Ok(0);
    }
    let phase = if p.phase == Phase::Failed {
        j.resume_phase
    } else {
        p.phase
    };
    let count: usize = match phase {
        Phase::Prepared => 6,
        Phase::Stopping => 5,
        Phase::Quiescent => 4,
        Phase::Cleaning => 3,
        Phase::Persisting => 2,
        Phase::Complete => 1,
        Phase::Failed => return Err(PurgeError::CorruptJournal),
    };
    let retained = j.receipts.iter().try_fold(0usize, |n, r| {
        n.checked_add(owned_size(r)?)
            .ok_or(PurgeError::LimitExceeded)
    })?;
    // Includes stop dispositions, artifact/store outcomes and publication ACKs.
    let remaining = MAX_PAYLOAD.saturating_sub(retained);
    remaining
        .checked_add(
            (count + usize::from(p.phase == Phase::Failed)) * std::mem::size_of::<Receipt>(),
        )
        .ok_or(PurgeError::LimitExceeded)
}

fn remaining_frames(p: &Plan) -> Result<usize, PurgeError> {
    let j = state(p)?;
    if j.released {
        return Ok(0);
    }
    let unfinished = j.actions.iter().filter(|a| a.outcome.is_none()).count();
    let unstarted = j.actions.iter().filter(|a| a.pending_revision == 0).count();
    let phase = if p.phase == Phase::Failed {
        j.resume_phase
    } else {
        p.phase
    };
    let lifecycle = match phase {
        Phase::Prepared => 6,
        Phase::Stopping => 5,
        Phase::Quiescent => 4,
        Phase::Cleaning => 3,
        Phase::Persisting => 2,
        Phase::Complete => 1,
        Phase::Failed => return Err(PurgeError::CorruptJournal),
    };
    unfinished
        .div_ceil(ACTION_BATCH)
        .checked_add(unstarted.div_ceil(ACTION_BATCH))
        .and_then(|x| x.checked_add(lifecycle))
        .and_then(|x| {
            x.checked_add(
                if matches!(
                    phase,
                    Phase::Prepared
                        | Phase::Stopping
                        | Phase::Quiescent
                        | Phase::Cleaning
                        | Phase::Persisting
                ) {
                    MAX_PAYLOAD.div_ceil(CHUNK_BYTES) + 6
                } else {
                    0
                },
            )
        })
        .and_then(|x| x.checked_add(usize::from(p.phase == Phase::Failed)))
        .ok_or(PurgeError::LimitExceeded)
}
impl Registry {
    pub fn initialize(domain: [u8; 16], host: &mut impl Host) -> Result<Self, PurgeError> {
        Self::initialize_with_high_water(domain, 0, host)
    }
    /// Creates only an empty, exclusively owned journal domain. A checked host
    /// rejects existing sequence 1; recovery NEVER falls back to initialization.
    pub fn initialize_with_high_water(
        domain: [u8; 16],
        high_water: u64,
        host: &mut impl Host,
    ) -> Result<Self, PurgeError> {
        if !host.supported() {
            return Err(PurgeError::Unsupported);
        }
        if high_water == u64::MAX {
            return Err(PurgeError::LimitExceeded);
        }
        let journal_identity = host.journal_identity()?;
        if &journal_identity[..8] != b"NZBPJID1" {
            return Err(PurgeError::InvalidInput);
        }
        let mut r = Self {
            domain,
            journal_identity,
            sequence: 0,
            high_water,
            operations: Vec::new(),
            inventory: Vec::new(),
            recovery_required: false,
        };
        r.publish(
            &frame(
                DOMAIN_TAG,
                &DomainFrame {
                    domain,
                    journal_identity,
                    sequence: 1,
                    high_water,
                },
            )?,
            host,
        )?;
        Ok(r)
    }
    pub fn plan(&self, index: usize) -> Option<&Plan> {
        self.operations.get(index)
    }
    pub fn find(&self, request: &[u8; 16]) -> Option<usize> {
        self.operations
            .iter()
            .position(|p| &p.token.request == request)
    }
    pub fn is_reserved(&self, index: usize) -> bool {
        self.operations
            .get(index)
            .and_then(|p| p.journal.as_ref())
            .is_some_and(|j| self.recovery_required || !j.released)
    }
    pub fn requires_recovery(&self) -> bool {
        self.recovery_required
    }
    fn ready(&self, host: &impl Host) -> Result<(), PurgeError> {
        if self.recovery_required {
            return Err(PurgeError::RecoveryRequired);
        }
        if !host.supported() {
            return Err(PurgeError::Unsupported);
        }
        if host.journal_identity()? != self.journal_identity {
            return Err(PurgeError::Conflict);
        }
        Ok(())
    }
    fn publish(&mut self, bytes: &[u8], host: &mut impl Host) -> Result<(), PurgeError> {
        self.ready(host)?;
        let sequence = next(self.sequence)?;
        if sequence as usize > MAX_FRAMES {
            return Err(PurgeError::LimitExceeded);
        }
        self.recovery_required = true;
        let ack = host.publish(sequence, bytes)?;
        if ack.sequence != sequence
            || ack.frame != bytes
            || !ack.file_synced
            || !ack.published
            || !ack.directory_synced
        {
            return Err(PurgeError::Persistence);
        }
        self.sequence = sequence;
        self.recovery_required = false;
        Ok(())
    }
    fn resources(
        &self,
        replacing: Option<usize>,
        candidate: Option<&Plan>,
        new_bytes: usize,
        new_frames: usize,
    ) -> Result<(), PurgeError> {
        let mut owned = new_bytes;
        let mut frames = (self.sequence as usize)
            .checked_add(new_frames)
            .ok_or(PurgeError::LimitExceeded)?;
        for (i, p) in self.operations.iter().enumerate() {
            if Some(i) != replacing {
                owned = owned
                    .checked_add(
                        owned_size(p)?
                            .checked_add(future_owned(p)?)
                            .ok_or(PurgeError::LimitExceeded)?,
                    )
                    .ok_or(PurgeError::LimitExceeded)?;
                if !state(p)?.released {
                    frames = frames
                        .checked_add(remaining_frames(p)?)
                        .ok_or(PurgeError::LimitExceeded)?;
                }
            }
        }
        if let Some(p) = candidate {
            owned = owned
                .checked_add(
                    owned_size(p)?
                        .checked_add(future_owned(p)?)
                        .ok_or(PurgeError::LimitExceeded)?,
                )
                .ok_or(PurgeError::LimitExceeded)?;
            frames = frames
                .checked_add(remaining_frames(p)?)
                .ok_or(PurgeError::LimitExceeded)?;
        }
        for f in &self.inventory {
            owned = owned
                .checked_add(owned_size(f)?)
                .ok_or(PurgeError::LimitExceeded)?;
        }
        if owned > MAX_OPERATION_BYTES || frames > MAX_FRAMES {
            return Err(PurgeError::LimitExceeded);
        }
        Ok(())
    }
    fn publish_image(
        &mut self,
        kind: u32,
        request: [u8; 16],
        generation: u64,
        image: &[u8],
        host: &mut impl Host,
    ) -> Result<u64, PurgeError> {
        if image.is_empty() || image.len() > MAX_OPERATION_BYTES {
            return Err(PurgeError::LimitExceeded);
        }
        let count = image.len().div_ceil(CHUNK_BYTES);
        let start = next(self.sequence)?;
        let end = start
            .checked_add(count as u64)
            .ok_or(PurgeError::LimitExceeded)?;
        if end as usize > MAX_FRAMES {
            return Err(PurgeError::LimitExceeded);
        }
        let mut identities = reserved(count)?;
        // Freeze ALL output frames before the first external write. An allocation
        // failure cannot strand an initialization after publishing only a prefix.
        let mut records = reserved(count + 1)?;
        for (i, part) in image.chunks(CHUNK_BYTES).enumerate() {
            let sequence = start + i as u64;
            let chunk = Chunk {
                domain: self.domain,
                sequence,
                high_water: self.high_water,
                request,
                generation,
                start,
                index: i as u32,
                count: count as u32,
                kind,
                image_bytes: image.len() as u64,
                bytes: copy_bytes(part)?,
            };
            let bytes = frame(CHUNK_TAG, &chunk)?;
            identities.push(ChunkId {
                sequence,
                bytes: part.len() as u32,
                checksum: checksum(part),
            });
            records.push(bytes);
        }
        records.push(frame(
            if kind == INVENTORY_TAG {
                INVENTORY_TAG
            } else {
                COMMIT_TAG
            },
            &Commit {
                domain: self.domain,
                sequence: end,
                high_water: self.high_water,
                request,
                generation,
                start,
                kind,
                image_bytes: image.len() as u64,
                checksum: checksum(image),
                chunks: identities,
            },
        )?);
        for bytes in &records {
            self.publish(bytes, host)?;
        }
        Ok(end)
    }
    pub fn reserve(
        &mut self,
        mut request: Request,
        mut snapshot: Snapshot,
        owners: &[u32],
        host: &mut impl Host,
    ) -> Result<Reservation, PurgeError> {
        self.ready(host)?;
        let request_bytes = canonical_request(&mut request)?;
        if let Some(i) = self.find(&request.token) {
            return Ok(
                if state(&self.operations[i])?.request_bytes == request_bytes {
                    Reservation::Existing(i)
                } else {
                    Reservation::Conflict
                },
            );
        }
        if owners.len() > MAX_MEMBERS || self.operations.len() >= MAX_OPERATIONS {
            return Err(PurgeError::LimitExceeded);
        }
        if owners.is_empty() || owners.contains(&0) {
            return Err(PurgeError::InvalidInput);
        }
        let mut required_owners = reserved(owners.len())?;
        required_owners.extend_from_slice(owners);
        required_owners.sort_unstable();
        if required_owners.windows(2).any(|w| w[0] == w[1]) {
            return Err(PurgeError::InvalidInput);
        }
        let generation = next(self.high_water)?;
        let mut captured = Request {
            token: request.token,
            seeds: copy(&snapshot.seeds)?,
            policy: 1,
        };
        if canonical_request(&mut captured)? != request_bytes {
            return Err(PurgeError::Conflict);
        }
        snapshot.seeds = copy(&request.seeds)?;
        snapshot.generation = generation;
        let mut p = prepare(snapshot, request.token)?;
        for old in &self.operations {
            if p.token
                .members
                .iter()
                .any(|a| old.token.members.iter().any(|b| a == b))
            {
                return Ok(Reservation::Conflict);
            }
            if !state(old)?.released && overlaps(old, &p) {
                return Ok(Reservation::Conflict);
            }
        }
        let actions = empty_actions(p.actions.len())?;
        p.journal = Some(JournalState {
            domain: self.domain,
            journal_identity: self.journal_identity,
            global_sequence: 2,
            manifest_sequence: 2,
            high_water: generation,
            request,
            request_fingerprint: checksum(&request_bytes),
            request_bytes,
            state_revision: 1,
            receipt_sequence: 0,
            barrier_revision: 1,
            required_owners,
            receipts: Vec::new(),
            actions,
            released: false,
            error: None,
            resume_phase: Phase::Prepared,
            deltas: Vec::new(),
        });
        let image_size = wire(&p)?.len();
        let records = image_size.div_ceil(CHUNK_BYTES) + 1;
        let commit = self
            .sequence
            .checked_add(records as u64)
            .ok_or(PurgeError::LimitExceeded)?;
        {
            let j = state_mut(&mut p)?;
            j.global_sequence = commit;
            j.manifest_sequence = commit;
            j.barrier_revision = commit;
        }
        validate_plan(&p)?;
        self.resources(None, Some(&p), 0, records)?;
        let image = wire(&p)?;
        self.operations
            .try_reserve_exact(1)
            .map_err(|_| PurgeError::AllocationFailure)?;
        // The first durable chunk burns this generation but does NOT admit it.
        // The final commit alone makes the complete manifest usable as IntentAck.
        self.high_water = generation;
        let i = self.operations.len();
        self.operations.push(p);
        if let Err(e) = self.publish_image(
            PLAN_TAG,
            self.operations[i].token.request,
            generation,
            &image,
            host,
        ) {
            self.recovery_required = true;
            return Err(e);
        }
        Ok(Reservation::New(i))
    }
    /// A provisional handle never allocates. Replay consults retained canonical
    /// request before copying or inspecting the provisional snapshot again.
    pub fn reserve_prepared(
        &mut self,
        p: &Plan,
        owners: &[u32],
        host: &mut impl Host,
    ) -> Result<Reservation, PurgeError> {
        self.ready(host)?;
        let mut request = Request {
            token: p.token.request,
            seeds: copy(&p.snapshot.seeds)?,
            policy: 1,
        };
        let bytes = canonical_request(&mut request)?;
        if let Some(i) = self.find(&request.token) {
            return Ok(if state(&self.operations[i])?.request_bytes == bytes {
                Reservation::Existing(i)
            } else {
                Reservation::Conflict
            });
        }
        self.reserve(request, copy(&p.snapshot)?, owners, host)
    }
    fn record_event(
        &mut self,
        index: usize,
        mut e: Event,
        host: &mut impl Host,
    ) -> Result<(), PurgeError> {
        let image = wire(&e)?;
        let chunked = image
            .len()
            .checked_add(36)
            .ok_or(PurgeError::LimitExceeded)?
            > MAX_PAYLOAD;
        let records = if chunked {
            image.len().div_ceil(CHUNK_BYTES) + 1
        } else {
            1
        };
        e.sequence = self
            .sequence
            .checked_add(records as u64)
            .ok_or(PurgeError::LimitExceeded)?;
        let mut p = copy(self.operations.get(index).ok_or(PurgeError::InvalidInput)?)?;
        Self::apply_event(&mut p, &e)?;
        self.resources(Some(index), Some(&p), 0, records)?;
        let bytes = if chunked {
            wire(&e)?
        } else {
            frame(EVENT_TAG, &e)?
        };
        self.operations[index] = p;
        let result = if chunked {
            self.publish_image(EVENT_TAG, e.request, e.generation, &bytes, host)
                .map(|_| ())
        } else {
            self.publish(&bytes, host)
        };
        if let Err(error) = result {
            self.recovery_required = true;
            return Err(error);
        }
        Ok(())
    }
    fn event(&self, index: usize) -> Result<Event, PurgeError> {
        let p = self.operations.get(index).ok_or(PurgeError::InvalidInput)?;
        let j = state(p)?;
        Ok(Event {
            domain: self.domain,
            sequence: next(self.sequence)?,
            high_water: self.high_water,
            request: p.token.request,
            generation: p.token.generation,
            manifest_sequence: j.manifest_sequence,
            previous_revision: j.state_revision,
            state_revision: next(j.state_revision)?,
            receipt_sequence: j.receipt_sequence,
            phase: p.phase,
            barrier_revision: j.barrier_revision,
            released: j.released,
            error: j.error,
            resume_phase: j.resume_phase,
            receipt: None,
            updates: Vec::new(),
        })
    }
    fn apply_event(p: &mut Plan, e: &Event) -> Result<(), PurgeError> {
        if let Some(r) = &e.receipt {
            validate_receipt(p, r)?;
        }
        let j = state(p)?;
        if e.domain != j.domain
            || e.request != p.token.request
            || e.generation != p.token.generation
            || e.manifest_sequence != j.manifest_sequence
            || e.previous_revision != j.state_revision
            || e.state_revision != next(j.state_revision)?
            || e.receipt_sequence < j.receipt_sequence
            || e.barrier_revision != j.barrier_revision
            || j.released
            || e.updates.len() > ACTION_BATCH
        {
            return Err(PurgeError::CorruptJournal);
        }
        let acknowledged = e
            .receipt
            .as_ref()
            .is_some_and(|r| r.outcome == Outcome::Acknowledged);
        let operation = e.receipt.as_ref().map(|r| r.operation);
        let transition = match (p.phase, e.phase) {
            (_, Phase::Failed) => e.error.is_some(),
            (Phase::Prepared, Phase::Stopping) => {
                acknowledged && operation == Some(Operation::Fence)
            }
            (Phase::Stopping, Phase::Quiescent) => {
                acknowledged && operation == Some(Operation::Drain)
            }
            (Phase::Quiescent, Phase::Cleaning) => {
                acknowledged && operation == Some(Operation::Revalidate)
            }
            (Phase::Cleaning, Phase::Cleaning) => !e.updates.is_empty() && e.receipt.is_none(),
            (Phase::Cleaning, Phase::Persisting) => {
                acknowledged
                    && operation == Some(Operation::Cleanup)
                    && j.actions.iter().all(|a| a.outcome.is_some())
            }
            (Phase::Persisting, Phase::Complete) => {
                acknowledged && operation == Some(Operation::PersistRemoval)
            }
            (Phase::Complete, Phase::Complete) => {
                acknowledged && operation == Some(Operation::Release) && e.released
            }
            (Phase::Failed, new) => {
                new == j.resume_phase
                    && acknowledged
                    && operation == Some(Operation::Revalidate)
                    && e.error.is_none()
            }
            _ => false,
        };
        if !transition
            || e.released && e.phase != Phase::Complete
            || (e.phase == Phase::Failed) != e.error.is_some()
        {
            return Err(PurgeError::CorruptJournal);
        }
        let mut sequence = j.receipt_sequence;
        for (n, a) in e.updates.iter().enumerate() {
            if e.updates[..n].iter().any(|b| b.index == a.index) {
                return Err(PurgeError::CorruptJournal);
            }
            let old = j
                .actions
                .get(a.index as usize)
                .ok_or(PurgeError::CorruptJournal)?;
            if old.outcome.is_some()
                || a.pending_revision == 0
                || a.pending_revision > e.state_revision
            {
                return Err(PurgeError::CorruptJournal);
            }
            if let Some(outcome) = a.outcome {
                if old.pending_revision != a.pending_revision
                    || !matches!(outcome, Outcome::Removed | Outcome::Absent)
                    || a.receipt_sequence != next(sequence)?
                {
                    return Err(PurgeError::CorruptJournal);
                }
                sequence = a.receipt_sequence;
            } else if old.pending_revision != 0
                || a.pending_revision != e.state_revision
                || a.receipt_sequence != 0
            {
                return Err(PurgeError::CorruptJournal);
            }
        }
        if let Some(receipt) = &e.receipt {
            if receipt.action_index.is_some()
                || receipt.state_revision != j.state_revision
                || receipt.receipt_sequence != next(sequence)?
            {
                return Err(PurgeError::CorruptJournal);
            }
            if receipt.operation == Operation::Drain {
                validate_barriers(&receipt.owners, &j.required_owners, j.barrier_revision)?;
            } else if !receipt.owners.is_empty() {
                return Err(PurgeError::CorruptJournal);
            }
            sequence = receipt.receipt_sequence;
        }
        if e.receipt_sequence != sequence {
            return Err(PurgeError::CorruptJournal);
        }
        let j = state_mut(p)?;
        if let Some(r) = &e.receipt {
            let retained = j.receipts.iter().try_fold(owned_size(r)?, |n, v| {
                n.checked_add(owned_size(v)?)
                    .ok_or(PurgeError::LimitExceeded)
            })?;
            if retained > MAX_PAYLOAD {
                return Err(PurgeError::LimitExceeded);
            }
            append(&mut j.receipts, copy(r)?)?;
        }
        for a in &e.updates {
            j.actions[a.index as usize] = copy(a)?;
        }
        j.global_sequence = e.sequence;
        j.high_water = e.high_water;
        j.state_revision = e.state_revision;
        j.receipt_sequence = e.receipt_sequence;
        j.released = e.released;
        j.error = e.error;
        j.resume_phase = e.resume_phase;
        p.phase = e.phase;
        Ok(())
    }
    fn invoke(
        p: &Plan,
        operation: Operation,
        action_index: Option<usize>,
        sequence: u64,
        host: &mut impl Host,
    ) -> Result<Receipt, PurgeError> {
        let j = state(p)?;
        if host.journal_identity()? != j.journal_identity {
            return Err(PurgeError::Conflict);
        }
        // Compact reference resolves to full immutable token/member bytes held
        // once in the admitted manifest, plus exact action bytes when applicable.
        let mut payload = wire(&p.token)?;
        let mut extra = wire(&operation)?;
        extra
            .try_reserve(24)
            .map_err(|_| PurgeError::AllocationFailure)?;
        extra.extend_from_slice(&j.manifest_sequence.to_le_bytes());
        extra.extend_from_slice(&j.state_revision.to_le_bytes());
        extra.extend_from_slice(&(action_index.unwrap_or(usize::MAX) as u64).to_le_bytes());
        payload
            .try_reserve(extra.len())
            .map_err(|_| PurgeError::AllocationFailure)?;
        payload.extend_from_slice(&extra);
        if let Some(i) = action_index {
            let action = wire(p.actions.get(i).ok_or(PurgeError::InvalidInput)?)?;
            payload
                .try_reserve(action.len())
                .map_err(|_| PurgeError::AllocationFailure)?;
            payload.extend_from_slice(&action);
        }
        if matches!(
            operation,
            Operation::Cleanup | Operation::PersistRemoval | Operation::Release
        ) {
            let previous = wire(&j.receipts)?;
            let actions = wire(&j.actions)?;
            let extra = previous
                .len()
                .checked_add(actions.len())
                .ok_or(PurgeError::LimitExceeded)?;
            if payload
                .len()
                .checked_add(extra)
                .ok_or(PurgeError::LimitExceeded)?
                > MAX_OPERATION_BYTES
            {
                return Err(PurgeError::LimitExceeded);
            }
            payload
                .try_reserve(extra)
                .map_err(|_| PurgeError::AllocationFailure)?;
            payload.extend_from_slice(&previous);
            payload.extend_from_slice(&actions);
        }
        if let Some(a) = action_index {
            let (root, _) = action_path(&p.actions[a]);
            let root = p
                .snapshot
                .roots
                .iter()
                .find(|r| r.id == root)
                .ok_or(PurgeError::CorruptJournal)?;
            let bytes = wire(root)?;
            payload
                .try_reserve(bytes.len())
                .map_err(|_| PurgeError::AllocationFailure)?;
            payload.extend_from_slice(&bytes);
        }
        let identity = AckIdentity {
            version: 1,
            domain: j.domain,
            manifest_sequence: j.manifest_sequence,
            token: copy(&p.token)?,
            state_revision: j.state_revision,
            receipt_sequence: sequence,
            payload_digest: payload_identity(&payload),
        };
        let retained = j.receipts.iter().try_fold(0usize, |n, r| {
            n.checked_add(owned_size(r)?)
                .ok_or(PurgeError::LimitExceeded)
        })?;
        // Covers the full repeated token in both encoded ACK and C/Rust owned
        // conversion: <=128 fixed bytes per binding plus its source bytes.
        // 1024 covers the fixed ACK/receipt envelope; size assertions accompany
        // the ABI definitions. This is separate from retained receipt storage.
        let envelope = p.token.members.iter().try_fold(1024usize, |n, b| {
            n.checked_add(128)
                .and_then(|n| n.checked_add(b.posting_source.len()))
                .ok_or(PurgeError::LimitExceeded)
        })?;
        let receipt_budget = MAX_PAYLOAD
            .checked_sub(retained)
            .and_then(|remaining| {
                MAX_PAYLOAD
                    .checked_sub(envelope)
                    .map(|encoded| remaining.min(encoded))
            })
            .filter(|available| *available >= std::mem::size_of::<Receipt>())
            .ok_or(PurgeError::LimitExceeded)?;
        let call = Call {
            identity,
            operation,
            action: action_index.and_then(|i| p.actions.get(i)),
            barrier_revision: j.barrier_revision,
            required_owners: &j.required_owners,
            inventory_revision: p.snapshot.revision,
            receipt_budget,
            plan: p,
        };
        let ack = host.execute(&call)?;
        if ack.identity != call.identity
            || ack.inventory_revision != call.inventory_revision
            || ack.owners.len() > MAX_MEMBERS
            || operation != Operation::Drain && !ack.owners.is_empty()
            || wire(&ack)?.len() > MAX_PAYLOAD
        {
            return Err(PurgeError::Conflict);
        }
        if ack.outcome == Outcome::IdentityMismatch {
            return Err(PurgeError::Conflict);
        }
        if operation == Operation::Drain && ack.outcome != Outcome::Pending {
            validate_barriers(&ack.owners, &j.required_owners, j.barrier_revision)?;
        }
        if matches!(operation, Operation::Remove | Operation::Reconcile) {
            if !matches!(ack.outcome, Outcome::Removed | Outcome::Absent) {
                return Err(PurgeError::HostFailure);
            }
        } else if !matches!(ack.outcome, Outcome::Acknowledged | Outcome::Pending)
            && !(operation == Operation::Cleanup && ack.outcome == Outcome::Failed)
        {
            return Err(PurgeError::HostFailure);
        }
        let receipt = Receipt {
            operation,
            action_index: action_index.map(|i| i as u32),
            state_revision: ack.identity.state_revision,
            receipt_sequence: sequence,
            payload_digest: ack.identity.payload_digest,
            outcome: ack.outcome,
            owners: if operation == Operation::Drain {
                ack.owners
            } else {
                Vec::new()
            },
            fence: ack.fence,
            cleanup: ack.cleanup,
            persistence: ack.persistence,
        };
        if owned_size(&receipt)? > receipt_budget {
            return Err(PurgeError::LimitExceeded);
        }
        if receipt.outcome != Outcome::Pending {
            validate_receipt(p, &receipt)?;
        }
        Ok(receipt)
    }
    fn fail_event(
        &mut self,
        index: usize,
        mut e: Event,
        error: PurgeError,
        host: &mut impl Host,
    ) -> Result<Phase, PurgeError> {
        e.resume_phase = self.operations[index].phase;
        e.phase = Phase::Failed;
        e.error = Some(error);
        self.record_event(index, e, host)?;
        Err(error)
    }
    pub fn advance(&mut self, index: usize, host: &mut impl Host) -> Result<Phase, PurgeError> {
        self.ready(host)?;
        let p = self.operations.get(index).ok_or(PurgeError::InvalidInput)?;
        if p.phase == Phase::Failed {
            return Err(state(p)?.error.unwrap_or(PurgeError::HostFailure));
        }
        if state(p)?.released {
            return Ok(Phase::Complete);
        }
        self.resources(None, None, 0, 0)?;
        if p.phase == Phase::Cleaning && state(p)?.actions.iter().any(|a| a.outcome.is_none()) {
            let mut indices = reserved(ACTION_BATCH)?;
            let mut pending = self.event(index)?;
            pending.updates = reserved(ACTION_BATCH)?;
            for a in &state(p)?.actions {
                if a.outcome.is_none() {
                    indices.push(a.index as usize);
                    if a.pending_revision == 0 {
                        let mut update = copy(a)?;
                        update.pending_revision = pending.state_revision;
                        pending.updates.push(update);
                    }
                    if indices.len() == ACTION_BATCH {
                        break;
                    }
                }
            }
            // Every per-action identity is bound to its immutable manifest index.
            let newly_pending = !pending.updates.is_empty();
            if newly_pending {
                self.record_event(index, pending, host)?;
            }
            let mut complete = self.event(index)?;
            complete.updates = reserved(indices.len())?;
            for i in indices {
                let p = &self.operations[index];
                let old = &state(p)?.actions[i];
                let operation = if newly_pending && old.pending_revision == state(p)?.state_revision
                {
                    Operation::Remove
                } else {
                    Operation::Reconcile
                };
                let sequence = next(complete.receipt_sequence)?;
                let receipt = match Self::invoke(p, operation, Some(i), sequence, host) {
                    Ok(r) => r,
                    Err(e) => return self.fail_event(index, complete, e, host),
                };
                complete.receipt_sequence = sequence;
                complete.updates.push(ActionReceipt {
                    index: i as u32,
                    pending_revision: old.pending_revision,
                    outcome: Some(receipt.outcome),
                    receipt_sequence: sequence,
                    payload_digest: receipt.payload_digest,
                });
            }
            self.record_event(index, complete, host)?;
            return Ok(Phase::Cleaning);
        }
        let operation = match p.phase {
            Phase::Prepared => Operation::Fence,
            Phase::Stopping => Operation::Drain,
            Phase::Quiescent => Operation::Revalidate,
            Phase::Cleaning => Operation::Cleanup,
            Phase::Persisting => Operation::PersistRemoval,
            Phase::Complete => Operation::Release,
            Phase::Failed => return Err(PurgeError::HostFailure),
        };
        let mut e = self.event(index)?;
        let receipt = match Self::invoke(p, operation, None, next(e.receipt_sequence)?, host) {
            Ok(r) => r,
            Err(err) => return self.fail_event(index, e, err, host),
        };
        if receipt.outcome == Outcome::Pending {
            return Ok(p.phase);
        }
        let failed = receipt.outcome == Outcome::Failed;
        e.receipt_sequence = receipt.receipt_sequence;
        e.receipt = Some(receipt);
        if failed {
            return self.fail_event(index, e, PurgeError::HostFailure, host);
        }
        e.phase = match operation {
            Operation::Fence => Phase::Stopping,
            Operation::Drain => Phase::Quiescent,
            Operation::Revalidate => Phase::Cleaning,
            Operation::Cleanup => Phase::Persisting,
            Operation::PersistRemoval | Operation::Release => Phase::Complete,
            _ => return Err(PurgeError::InvalidInput),
        };
        if operation == Operation::Release {
            e.released = true;
        }
        let phase = e.phase;
        self.record_event(index, e, host)?;
        Ok(phase)
    }
    pub fn retry(&mut self, index: usize, host: &mut impl Host) -> Result<(), PurgeError> {
        self.ready(host)?;
        let p = self.operations.get(index).ok_or(PurgeError::InvalidInput)?;
        if p.phase != Phase::Failed {
            return Err(PurgeError::InvalidInput);
        }
        let mut e = self.event(index)?;
        let receipt = Self::invoke(
            p,
            Operation::Revalidate,
            None,
            next(e.receipt_sequence)?,
            host,
        )?;
        if receipt.outcome != Outcome::Acknowledged {
            return Err(PurgeError::HostFailure);
        }
        e.receipt_sequence = receipt.receipt_sequence;
        e.receipt = Some(receipt);
        e.phase = state(p)?.resume_phase;
        e.error = None;
        self.record_event(index, e, host)
    }
}
fn validate_barriers(
    owners: &[OwnerBarrier],
    required: &[u32],
    barrier: u64,
) -> Result<(), PurgeError> {
    if owners.len() != required.len() {
        return Err(PurgeError::Conflict);
    }
    for kind in required {
        let mut found = owners.iter().filter(|o| o.owner_kind == *kind);
        let o = found.next().ok_or(PurgeError::Conflict)?;
        if found.next().is_some()
            || o.barrier_revision != barrier
            || o.queued != 0
            || o.active != 0
            || o.pinned != 0
            || o.publication != 0
            || o.unacknowledged_deltas != 0
        {
            return Err(PurgeError::Conflict);
        }
    }
    Ok(())
}

struct PendingImage {
    request: [u8; 16],
    generation: u64,
    start: u64,
    kind: u32,
    image_bytes: usize,
    count: usize,
    bytes: Vec<u8>,
    ids: Vec<ChunkId>,
}
impl Registry {
    /// Call only with an exhaustive, descriptor-checked scan of the exact private
    /// domain before worker admission. Missing suffix detection belongs to that
    /// checked enumeration; checksum agreement does not authenticate the scan.
    /// Orphan chunks retain a burned generation/sequence and return explicit
    /// RecoveryRequired. They cannot be initialized around or silently ignored.
    pub fn recover<B: AsRef<[u8]>>(
        domain: [u8; 16],
        journal_identity: [u8; 32],
        frames: &[B],
    ) -> Result<Self, PurgeError> {
        if frames.is_empty() || frames.len() > MAX_FRAMES {
            return Err(PurgeError::CorruptJournal);
        }
        let (tag, body) = unframe(frames[0].as_ref())?;
        if tag != DOMAIN_TAG {
            return Err(PurgeError::CorruptJournal);
        }
        let first: DomainFrame = unwire(body)?;
        if &journal_identity[..8] != b"NZBPJID1"
            || first.domain != domain
            || first.journal_identity != journal_identity
            || first.sequence != 1
            || first.high_water == u64::MAX
        {
            return Err(PurgeError::CorruptJournal);
        }
        let mut r = Self {
            domain,
            journal_identity,
            sequence: 1,
            high_water: first.high_water,
            operations: Vec::new(),
            inventory: Vec::new(),
            recovery_required: false,
        };
        let mut pending: Option<PendingImage> = None;
        for bytes in &frames[1..] {
            let (tag, body) = unframe(bytes.as_ref())?;
            match tag {
                CHUNK_TAG => {
                    let c: Chunk = unwire(body)?;
                    if c.domain != domain
                        || c.sequence != next(r.sequence)?
                        || c.count == 0
                        || c.count as usize > MAX_OPERATION_BYTES.div_ceil(CHUNK_BYTES)
                        || c.image_bytes == 0
                        || c.image_bytes > MAX_OPERATION_BYTES as u64
                        || c.count as usize != (c.image_bytes as usize).div_ceil(CHUNK_BYTES)
                        || c.bytes.is_empty()
                        || c.bytes.len() > CHUNK_BYTES
                    {
                        return Err(PurgeError::CorruptJournal);
                    }
                    if pending.is_none() {
                        if c.index != 0 || c.start != c.sequence {
                            return Err(PurgeError::CorruptJournal);
                        }
                        match c.kind {
                            PLAN_TAG => {
                                if c.generation != next(r.high_water)?
                                    || c.high_water != c.generation
                                    || r.find(&c.request).is_some()
                                {
                                    return Err(PurgeError::CorruptJournal);
                                }
                                r.high_water = c.high_water;
                            }
                            INVENTORY_TAG | EVENT_TAG => {
                                if c.high_water != r.high_water {
                                    return Err(PurgeError::CorruptJournal);
                                }
                            }
                            _ => return Err(PurgeError::CorruptJournal),
                        }
                        pending = Some(PendingImage {
                            request: c.request,
                            generation: c.generation,
                            start: c.start,
                            kind: c.kind,
                            image_bytes: c.image_bytes as usize,
                            count: c.count as usize,
                            bytes: reserved(c.image_bytes as usize)?,
                            ids: reserved(c.count as usize)?,
                        });
                    }
                    let p = pending.as_mut().ok_or(PurgeError::CorruptJournal)?;
                    if c.request != p.request
                        || c.generation != p.generation
                        || c.start != p.start
                        || c.kind != p.kind
                        || c.high_water != r.high_water
                        || c.index as usize != p.ids.len()
                        || c.count as usize != p.count
                        || c.image_bytes as usize != p.image_bytes
                    {
                        return Err(PurgeError::CorruptJournal);
                    }
                    let remaining = p
                        .image_bytes
                        .checked_sub(p.bytes.len())
                        .ok_or(PurgeError::CorruptJournal)?;
                    if c.bytes.len() != remaining.min(CHUNK_BYTES) {
                        return Err(PurgeError::CorruptJournal);
                    }
                    p.ids.push(ChunkId {
                        sequence: c.sequence,
                        bytes: c.bytes.len() as u32,
                        checksum: checksum(&c.bytes),
                    });
                    p.bytes.extend_from_slice(&c.bytes);
                }
                COMMIT_TAG | INVENTORY_TAG => {
                    let c: Commit = unwire(body)?;
                    let p = pending.take().ok_or(PurgeError::CorruptJournal)?;
                    if c.domain != domain
                        || c.sequence != next(r.sequence)?
                        || c.high_water != r.high_water
                        || c.request != p.request
                        || c.generation != p.generation
                        || c.start != p.start
                        || c.kind != p.kind
                        || c.image_bytes as usize != p.image_bytes
                        || p.bytes.len() != p.image_bytes
                        || p.ids.len() != p.count
                        || c.chunks != p.ids
                        || c.checksum != checksum(&p.bytes)
                        || (tag == INVENTORY_TAG) != (c.kind == INVENTORY_TAG)
                    {
                        return Err(PurgeError::CorruptJournal);
                    }
                    match c.kind {
                        PLAN_TAG => {
                            let plan: Plan = unwire(&p.bytes)?;
                            validate_plan(&plan)?;
                            let j = state(&plan)?;
                            if plan.token.request != c.request
                                || plan.token.generation != c.generation
                                || j.domain != domain
                                || j.journal_identity != journal_identity
                                || j.manifest_sequence != c.sequence
                                || j.global_sequence != c.sequence
                                || j.high_water != r.high_water
                                || j.state_revision != 1
                                || plan.phase != Phase::Prepared
                                || !j.receipts.is_empty()
                                || !j.deltas.is_empty()
                                || j.actions
                                    .iter()
                                    .any(|a| a.pending_revision != 0 || a.outcome.is_some())
                                || r.operations.len() >= MAX_OPERATIONS
                            {
                                return Err(PurgeError::CorruptJournal);
                            }
                            for old in &r.operations {
                                if plan
                                    .token
                                    .members
                                    .iter()
                                    .any(|a| old.token.members.contains(a))
                                    || !state(old)?.released && overlaps(old, &plan)
                                {
                                    return Err(PurgeError::Conflict);
                                }
                            }
                            r.resources(None, Some(&plan), 0, 1)?;
                            append(&mut r.operations, plan)?;
                        }
                        INVENTORY_TAG => {
                            let f: InventoryFrame = unwire(&p.bytes)?;
                            if f.domain != domain
                                || f.sequence != c.sequence
                                || f.high_water != r.high_water
                            {
                                return Err(PurgeError::CorruptJournal);
                            }
                            let candidate =
                                r.inventory_candidate(&f.binding, &f.delta, f.sequence)?;
                            let expected = if let Some((_, p)) = &candidate {
                                (p.token.request, p.token.generation)
                            } else {
                                ([0; 16], 0)
                            };
                            if (c.request, c.generation) != expected {
                                return Err(PurgeError::CorruptJournal);
                            }
                            // Identity was checked against the complete candidate.
                            // Release it before accept_inventory rebuilds the Plan.
                            drop(candidate);
                            r.accept_inventory(f)?;
                        }
                        EVENT_TAG => {
                            let e: Event = unwire(&p.bytes)?;
                            if e.domain != domain
                                || e.sequence != c.sequence
                                || e.high_water != r.high_water
                                || e.request != c.request
                                || e.generation != c.generation
                            {
                                return Err(PurgeError::CorruptJournal);
                            }
                            let index = r.find(&e.request).ok_or(PurgeError::CorruptJournal)?;
                            let mut plan = copy(&r.operations[index])?;
                            Self::apply_event(&mut plan, &e)?;
                            r.resources(Some(index), Some(&plan), 0, 1)?;
                            r.operations[index] = plan;
                        }
                        _ => return Err(PurgeError::CorruptJournal),
                    }
                }
                EVENT_TAG => {
                    if pending.is_some() {
                        return Err(PurgeError::CorruptJournal);
                    }
                    let e: Event = unwire(body)?;
                    if e.domain != domain
                        || e.sequence != next(r.sequence)?
                        || e.high_water != r.high_water
                    {
                        return Err(PurgeError::CorruptJournal);
                    }
                    let index = r.find(&e.request).ok_or(PurgeError::CorruptJournal)?;
                    let mut plan = copy(&r.operations[index])?;
                    Self::apply_event(&mut plan, &e)?;
                    r.resources(Some(index), Some(&plan), 0, 1)?;
                    r.operations[index] = plan;
                }
                _ => return Err(PurgeError::CorruptJournal),
            }
            r.sequence = next(r.sequence)?;
        }
        if pending.is_some() {
            return Err(PurgeError::RecoveryRequired);
        }
        r.resources(None, None, 0, 0)?;
        Ok(r)
    }
}

fn validate_delta(binding: &MemberBinding, d: &OutputDelta) -> Result<(), PurgeError> {
    let mut request = Request {
        token: [0; 16],
        seeds: reserved(1)?,
        policy: 1,
    };
    request.seeds.push(copy(binding)?);
    canonical_request(&mut request)?;
    if d.producer_ticket == 0
        || d.producer_ticket == u64::MAX
        || d.sequence == 0
        || d.sequence == u64::MAX
        || d.prior_inventory_revision == u64::MAX
        || d.changes.len() > MAX_ENTRIES
    {
        return Err(PurgeError::InvalidInput);
    }
    let revision = next(d.prior_inventory_revision)?;
    for (i, c) in d.changes.iter().enumerate() {
        if c.entry_id == 0
            || d.changes[..i].iter().any(|v| v.entry_id == c.entry_id)
            || c.before.is_none() && c.after.is_none()
            || c.before.is_some() && !c.prior_absent
        {
            return Err(PurgeError::Conflict);
        }
        for e in c.before.iter().chain(c.after.iter()) {
            if e.id != c.entry_id
                || &e.member != binding
                || e.relative_path.is_empty()
                || e.relative_path.len() > MAX_PATH
                || e.relative_path.contains(&0)
                || e.relative_path.starts_with(b"/")
                || e.relative_path
                    .split(|b| *b == b'/')
                    .any(|part| part.is_empty() || part == b"." || part == b"..")
                || e.object_identity.is_empty()
                || e.object_identity.len() > MAX_IDENTITY
                || e.object_identity.contains(&0)
                || e.kind == EntryKind::Unsupported
            {
                return Err(PurgeError::InvalidInput);
            }
        }
        match (&c.after, &c.ownership) {
            (Some(e), Some(o)) => {
                if e.inventory_revision != revision
                    || e.ownership_receipt_id != o.id
                    || e.member != o.member
                    || e.root_id != o.root_id
                    || e.relative_path != o.relative_path
                    || e.kind != o.kind
                    || e.object_identity != o.object_identity
                    || e.namespace_proof_id != o.namespace_proof_id
                    || e.inventory_revision != o.inventory_revision
                {
                    return Err(PurgeError::Conflict);
                }
            }
            (None, None) => {}
            _ => return Err(PurgeError::MissingInventory),
        }
    }
    if owned_size(d)? > MAX_PAYLOAD || wire(d)?.len() > MAX_PAYLOAD {
        return Err(PurgeError::LimitExceeded);
    }
    Ok(())
}
impl Registry {
    fn inventory_replay(
        &self,
        binding: &MemberBinding,
        d: &OutputDelta,
    ) -> Result<bool, PurgeError> {
        if let Some(old) = self.inventory.iter().find(|f| {
            &f.binding == binding
                && f.delta.producer_ticket == d.producer_ticket
                && f.delta.sequence == d.sequence
        }) {
            return if old.delta == *d {
                Ok(true)
            } else {
                Err(PurgeError::Conflict)
            };
        }
        if let Some(last) = self
            .inventory
            .iter()
            .rev()
            .find(|f| &f.binding == binding && f.delta.producer_ticket == d.producer_ticket)
        {
            if last.delta.final_for_producer || d.sequence != next(last.delta.sequence)? {
                return Err(PurgeError::Conflict);
            }
        } else if d.sequence != 1 {
            return Err(PurgeError::Conflict);
        }
        // Active operations have one aggregate revision across all members.
        // inventory_candidate checks that exact revision; another member may
        // have advanced it since this producer's previous acknowledged delta.
        let active = self.operations.iter().any(|p| {
            p.token.members.contains(binding) && p.journal.as_ref().is_some_and(|j| !j.released)
        });
        if !active {
            if let Some(last) = self.inventory.iter().rev().find(|f| &f.binding == binding) {
                if d.prior_inventory_revision != next(last.delta.prior_inventory_revision)? {
                    return Err(PurgeError::Conflict);
                }
            }
        }
        Ok(false)
    }
    fn inventory_candidate(
        &self,
        binding: &MemberBinding,
        d: &OutputDelta,
        sequence: u64,
    ) -> Result<Option<(usize, Plan)>, PurgeError> {
        let Some((i, old)) = self.operations.iter().enumerate().find(|(_, p)| {
            p.token.members.contains(binding) && p.journal.as_ref().is_some_and(|j| !j.released)
        }) else {
            return Ok(None);
        };
        if !matches!(old.phase, Phase::Prepared | Phase::Stopping)
            || old.snapshot.revision != d.prior_inventory_revision
        {
            return Err(PurgeError::Conflict);
        }
        let mut p = copy(old)?;
        for c in &d.changes {
            let existing = p.snapshot.entries.iter().position(|e| e.id == c.entry_id);
            match (&c.before, existing) {
                (Some(before), Some(n)) => {
                    if &p.snapshot.entries[n] != before {
                        return Err(PurgeError::Conflict);
                    }
                    p.snapshot.entries.remove(n);
                }
                (None, None) => {}
                _ => return Err(PurgeError::Conflict),
            }
            if let Some(e) = &c.after {
                append(&mut p.snapshot.entries, copy(e)?)?;
            }
            if let Some(o) = &c.ownership {
                if p.snapshot
                    .ownership_receipts
                    .iter()
                    .any(|old| old.id == o.id && old != o)
                {
                    return Err(PurgeError::Conflict);
                }
                if !p.snapshot.ownership_receipts.contains(o) {
                    append(&mut p.snapshot.ownership_receipts, copy(o)?)?;
                }
            }
        }
        p.snapshot.revision = next(d.prior_inventory_revision)?;
        append(
            &mut state_mut(&mut p)?.deltas,
            BoundDelta {
                binding: copy(binding)?,
                delta: copy(d)?,
            },
        )?;
        let checked = prepared_inventory(&p)?;
        if checked.token != p.token {
            return Err(PurgeError::Conflict);
        }
        p.actions = checked.actions;
        for (other_index, other) in self.operations.iter().enumerate() {
            if other_index != i && !state(other)?.released && overlaps(other, &p) {
                // No ACK: the producer retains the original delta and counted
                // obligation. Neither existing lease nor inventory is replaced.
                return Err(PurgeError::Conflict);
            }
        }
        let actions = empty_actions(p.actions.len())?;
        let j = state_mut(&mut p)?;
        j.actions = actions;
        j.state_revision = next(j.state_revision)?;
        j.global_sequence = sequence;
        j.high_water = self.high_water;
        Ok(Some((i, p)))
    }
    fn accept_inventory(&mut self, f: InventoryFrame) -> Result<(), PurgeError> {
        validate_delta(&f.binding, &f.delta)?;
        if self.inventory.len() >= MAX_FRAMES || self.inventory_replay(&f.binding, &f.delta)? {
            return Err(PurgeError::CorruptJournal);
        }
        let candidate = self.inventory_candidate(&f.binding, &f.delta, f.sequence)?;
        let size = owned_size(&f)?;
        if let Some((i, p)) = &candidate {
            self.resources(Some(*i), Some(p), size, 0)?;
        } else {
            self.resources(None, None, size, 0)?;
        }
        self.inventory
            .try_reserve_exact(1)
            .map_err(|_| PurgeError::AllocationFailure)?;
        if let Some((i, p)) = candidate {
            self.operations[i] = p;
        }
        self.inventory.push(f);
        Ok(())
    }
    /// Store bounded captured output before source metadata can be discarded.
    /// Standalone retained inventory does not authenticate ownership: a future
    /// prepare must still resolve independently validated source/root receipts.
    pub fn store_inventory(
        &mut self,
        binding: MemberBinding,
        delta: OutputDelta,
        host: &mut impl Host,
    ) -> Result<(), PurgeError> {
        self.ready(host)?;
        validate_delta(&binding, &delta)?;
        if self.inventory_replay(&binding, &delta)? {
            return Ok(());
        }
        if self.inventory.len() >= MAX_FRAMES {
            return Err(PurgeError::LimitExceeded);
        }
        let mut f = InventoryFrame {
            domain: self.domain,
            sequence: 1,
            high_water: self.high_water,
            binding,
            delta,
        };
        let size = wire(&f)?.len();
        let records = size.div_ceil(CHUNK_BYTES) + 1;
        f.sequence = self
            .sequence
            .checked_add(records as u64)
            .ok_or(PurgeError::LimitExceeded)?;
        let candidate = self.inventory_candidate(&f.binding, &f.delta, f.sequence)?;
        let size = owned_size(&f)?;
        let (request, generation) = if let Some((i, p)) = &candidate {
            self.resources(Some(*i), Some(p), size, records)?;
            (p.token.request, p.token.generation)
        } else {
            self.resources(None, None, size, records)?;
            ([0; 16], 0)
        };
        let image = wire(&f)?;
        self.inventory
            .try_reserve_exact(1)
            .map_err(|_| PurgeError::AllocationFailure)?;
        // Candidate was already checked above. Do not rebuild a second Plan
        // while retaining the first candidate and its temporary planning data.
        if let Some((i, p)) = candidate {
            self.operations[i] = p;
        }
        self.inventory.push(f);
        if let Err(e) = self.publish_image(INVENTORY_TAG, request, generation, &image, host) {
            self.recovery_required = true;
            return Err(e);
        }
        Ok(())
    }
}

fn validate_coverage(p: &Plan, owners: &[OwnerCoverage]) -> Result<(), PurgeError> {
    let j = state(p)?;
    if owners.len() != j.required_owners.len() {
        return Err(PurgeError::Conflict);
    }
    for kind in &j.required_owners {
        let mut matching = owners.iter().filter(|o| o.owner_kind == *kind);
        let o = matching.next().ok_or(PurgeError::Conflict)?;
        if matching.next().is_some() || !o.complete || o.barrier_revision != j.barrier_revision {
            return Err(PurgeError::Conflict);
        }
    }
    Ok(())
}
fn store_success(s: &StoreReceipt) -> bool {
    s.file_synced && s.published && s.directory_synced
}
fn validate_stores(stores: &[StoreReceipt]) -> Result<(), PurgeError> {
    if stores.len() > MAX_ENTRIES {
        return Err(PurgeError::LimitExceeded);
    }
    for (i, s) in stores.iter().enumerate() {
        if s.identity.is_empty()
            || s.identity.len() > MAX_IDENTITY
            || s.revision == 0
            || s.revision == u64::MAX
            || stores[..i].iter().any(|old| old.identity == s.identity)
        {
            return Err(PurgeError::Conflict);
        }
    }
    Ok(())
}
fn validate_receipt(p: &Plan, r: &Receipt) -> Result<(), PurgeError> {
    let j = state(p)?;
    if owned_size(r)? > MAX_PAYLOAD {
        return Err(PurgeError::LimitExceeded);
    }
    if r.fence.is_some() != (r.operation == Operation::Fence)
        || r.cleanup.is_some() != (r.operation == Operation::Cleanup)
        || r.persistence.is_some() != (r.operation == Operation::PersistRemoval)
    {
        return Err(PurgeError::Conflict);
    }
    if let Some(f) = &r.fence {
        if f.dispositions.len() != j.required_owners.len() {
            return Err(PurgeError::Conflict);
        }
        for kind in &j.required_owners {
            let mut found = f.dispositions.iter().filter(|s| s.owner_kind == *kind);
            let d = found.next().ok_or(PurgeError::Conflict)?;
            if found.next().is_some()
                || d.barrier_revision != j.barrier_revision
                || d.disposition > 2
            {
                return Err(PurgeError::Conflict);
            }
        }
    }
    if let Some(c) = &r.cleanup {
        validate_coverage(p, &c.owners)?;
        validate_stores(&c.stores)?;
        if c.coverage.len() != 7 || c.artifacts.len() > MAX_ENTRIES {
            return Err(PurgeError::Conflict);
        }
        for kind in 1..=7 {
            let mut found = c.coverage.iter().filter(|v| v.kind == kind);
            let coverage = found.next().ok_or(PurgeError::Conflict)?;
            if found.next().is_some()
                || !coverage.complete
                || coverage.count as usize != c.artifacts.iter().filter(|a| a.kind == kind).count()
            {
                return Err(PurgeError::Conflict);
            }
        }
        for (i, a) in c.artifacts.iter().enumerate() {
            if !(1..=7).contains(&a.kind)
                || !p.token.members.contains(&a.member)
                || a.identity.is_empty()
                || a.identity.len() > MAX_IDENTITY
                || !matches!(
                    a.outcome,
                    Outcome::Removed | Outcome::Absent | Outcome::Failed
                )
                || (a.outcome == Outcome::Failed) != a.error.is_some()
                || c.artifacts[..i].iter().any(|old| {
                    old.kind == a.kind && old.member == a.member && old.identity == a.identity
                })
            {
                return Err(PurgeError::Conflict);
            }
            if let Some(id) = a.entry_id {
                if !p
                    .snapshot
                    .entries
                    .iter()
                    .any(|e| e.id == id && e.member == a.member && e.object_identity == a.identity)
                {
                    return Err(PurgeError::Conflict);
                }
            }
            if let Some(store) = &a.retained_store {
                if !c.stores.iter().any(|s| &s.identity == store) {
                    return Err(PurgeError::Conflict);
                }
            }
        }
        // A complete earlier enumeration cannot be replaced with a new object
        // set on retry. Outcomes may advance; the exact artifact bindings stay.
        if let Some(previous) = j.receipts.iter().rev().find_map(|v| v.cleanup.as_ref()) {
            if previous.artifacts.len() != c.artifacts.len()
                || previous.artifacts.iter().any(|a| {
                    !c.artifacts.iter().any(|b| {
                        a.kind == b.kind
                            && a.member == b.member
                            && a.identity == b.identity
                            && a.entry_id == b.entry_id
                            && a.retained_store == b.retained_store
                    })
                })
            {
                return Err(PurgeError::Conflict);
            }
        }
        let success = c
            .artifacts
            .iter()
            .all(|a| matches!(a.outcome, Outcome::Removed | Outcome::Absent))
            && c.stores.iter().all(store_success);
        if r.outcome
            != if success {
                Outcome::Acknowledged
            } else {
                Outcome::Failed
            }
        {
            return Err(PurgeError::Conflict);
        }
    }
    if let Some(a) = &r.persistence {
        validate_coverage(p, &a.owners)?;
        validate_stores(&a.stores)?;
        let cleanup = j
            .receipts
            .iter()
            .rev()
            .find(|v| v.operation == Operation::Cleanup && v.outcome == Outcome::Acknowledged)
            .ok_or(PurgeError::Conflict)?;
        let high = j
            .actions
            .iter()
            .map(|v| v.receipt_sequence)
            .max()
            .unwrap_or(0);
        if r.outcome != Outcome::Acknowledged
            || a.completed_actions != p.actions.len() as u64
            || j.actions.iter().any(|v| v.outcome.is_none())
            || a.action_receipt_high_water != high
            || a.cleanup_receipt_sequence != cleanup.receipt_sequence
            || a.stores.is_empty()
            || !a.stores.iter().all(store_success)
        {
            return Err(PurgeError::Conflict);
        }
    }
    Ok(())
}
