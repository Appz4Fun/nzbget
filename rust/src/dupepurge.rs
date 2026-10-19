//! Owned preflight planning only. No filesystem or daemon mutation occurs here.
//!
//! Records come from guarded, independently validated host capture. Cross-table
//! agreement detects substitution; it does not authenticate client assertions.
//! Actual owner relation/custody capture must be supplied and reviewed by its
//! owner before a daemon caller is wired to this interface.
use std::cmp::Ordering;

pub const MAX_SEEDS: usize = 4096;
pub const MAX_MEMBERS: usize = 65536;
pub const MAX_ENTRIES: usize = 1_000_000;
pub const MAX_PAYLOAD: usize = 64 * 1024 * 1024;
pub const MAX_PATH: usize = 1023;
pub const MAX_IDENTITY: usize = 65535;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct MemberBinding {
    pub collection_id: i32,
    pub file_id: Option<i32>,
    pub incarnation: u64,
    pub posting_source: Vec<u8>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemberKind {
    Queue,
    Post,
    History,
    CompactHistory,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntryKind {
    Regular,
    Directory,
    Symlink,
    Unsupported,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Prepared,
    Stopping,
    Quiescent,
    Cleaning,
    Persisting,
    Complete,
    Failed,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PurgeError {
    InvalidInput,
    MissingSeed,
    MissingInventory,
    Conflict,
    LimitExceeded,
    Unsupported,
    AllocationFailure,
    Persistence,
    HostFailure,
    CorruptJournal,
    RecoveryRequired,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemberRecord {
    pub binding: MemberBinding,
    pub name: Vec<u8>,
    pub key: Vec<u8>,
    pub kind: MemberKind,
    pub complete_inventory: bool,
    pub source_validation_id: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceValidation {
    pub id: u64,
    pub version: u32,
    pub validator_version: u32,
    pub source_record_id: [u8; 32],
    pub source_bytes_digest: [u8; 32],
    pub binding: MemberBinding,
    pub parent_collection: Option<MemberBinding>,
    pub custody_receipt_id: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CustodyReceipt {
    pub id: [u8; 32],
    pub validator_version: u32,
    pub source_record_id: [u8; 32],
    pub source_bytes_digest: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParentMembership {
    pub file: MemberBinding,
    pub collection: MemberBinding,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ComparisonContext {
    pub captured: Vec<u8>,
    pub current: Vec<u8>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AnchorComparison {
    pub seed: MemberBinding,
    pub candidate: MemberBinding,
    pub name_equal: bool,
    pub key_equal: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DirectBinding {
    pub seed: MemberBinding,
    pub candidate: MemberBinding,
    pub seed_source_validation_id: u64,
    pub candidate_source_validation_id: u64,
    pub pair_membership_receipt_id: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairMembershipReceipt {
    pub id: [u8; 32],
    pub version: u32,
    pub validator_version: u32,
    pub owner_kind: u32,
    pub seed: MemberBinding,
    pub candidate: MemberBinding,
    pub seed_source_record_id: [u8; 32],
    pub seed_source_bytes_digest: [u8; 32],
    pub candidate_source_record_id: [u8; 32],
    pub candidate_source_bytes_digest: [u8; 32],
    pub relation_id: Vec<u8>,
    pub evidence_version: u32,
    pub evidence_id: [u8; 32],
    pub evidence_bytes: Vec<u8>,
    pub custody_receipt_id: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairCustodyReceipt {
    pub id: [u8; 32],
    pub version: u32,
    pub validator_version: u32,
    pub owner_kind: u32,
    pub relation_id: Vec<u8>,
    pub evidence_version: u32,
    pub evidence_id: [u8; 32],
    pub evidence_bytes: Vec<u8>,
    pub seed: MemberBinding,
    pub candidate: MemberBinding,
    pub seed_source_record_id: [u8; 32],
    pub seed_source_bytes_digest: [u8; 32],
    pub candidate_source_record_id: [u8; 32],
    pub candidate_source_bytes_digest: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RootRecord {
    pub id: u64,
    pub descriptor_identity: Vec<u8>,
    pub configured_container: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamespaceProof {
    pub id: [u8; 32],
    pub root_id: u64,
    pub relative_path: Vec<u8>,
    pub root_identity: Vec<u8>,
    pub ancestor_identity: Vec<u8>,
    pub mount_identity: Vec<u8>,
    pub exclusive: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InventoryEntry {
    pub id: u64,
    pub root_id: u64,
    pub relative_path: Vec<u8>,
    pub kind: EntryKind,
    pub object_identity: Vec<u8>,
    pub member: MemberBinding,
    pub namespace_proof_id: [u8; 32],
    pub ownership_receipt_id: [u8; 32],
    pub inventory_revision: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnershipReceipt {
    pub id: [u8; 32],
    pub member: MemberBinding,
    pub root_id: u64,
    pub relative_path: Vec<u8>,
    pub kind: EntryKind,
    pub object_identity: Vec<u8>,
    pub namespace_proof_id: [u8; 32],
    pub inventory_revision: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutsideClaim {
    pub id: u64,
    pub root_id: u64,
    pub relative_path: Vec<u8>,
    pub claimant: MemberBinding,
    pub object_identity: Vec<u8>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub version: u32,
    pub revision: u64,
    pub generation: u64,
    pub seeds: Vec<MemberBinding>,
    pub members: Vec<MemberRecord>,
    pub source_validations: Vec<SourceValidation>,
    pub custody_receipts: Vec<CustodyReceipt>,
    pub parents: Vec<ParentMembership>,
    pub comparison_context: ComparisonContext,
    pub comparisons: Vec<AnchorComparison>,
    pub direct_bindings: Vec<DirectBinding>,
    pub pair_memberships: Vec<PairMembershipReceipt>,
    pub pair_custody_receipts: Vec<PairCustodyReceipt>,
    pub roots: Vec<RootRecord>,
    pub namespace_proofs: Vec<NamespaceProof>,
    pub entries: Vec<InventoryEntry>,
    pub ownership_receipts: Vec<OwnershipReceipt>,
    pub outside_claims: Vec<OutsideClaim>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PurgeToken {
    pub request: [u8; 16],
    pub generation: u64,
    pub members: Vec<MemberBinding>,
}
#[derive(Debug, PartialEq, Eq)]
pub enum Action {
    RemoveEntry {
        entry_id: u64,
        root_id: u64,
        relative_path: Vec<u8>,
        kind: EntryKind,
        object_identity: Vec<u8>,
    },
    RemoveTree {
        entry_id: u64,
        root_id: u64,
        relative_path: Vec<u8>,
        object_identity: Vec<u8>,
    },
}
#[derive(Debug, PartialEq, Eq)]
pub struct Plan {
    pub snapshot: Snapshot,
    pub token: PurgeToken,
    pub phase: Phase,
    pub actions: Vec<Action>,
    pub journal: Option<crate::purgejournal::JournalState>,
}

pub(crate) fn reserved<T>(n: usize) -> Result<Vec<T>, PurgeError> {
    let mut v = Vec::new();
    v.try_reserve_exact(n)
        .map_err(|_| PurgeError::AllocationFailure)?;
    Ok(v)
}
pub(crate) fn copy_bytes(b: &[u8]) -> Result<Vec<u8>, PurgeError> {
    let mut v = reserved(b.len())?;
    v.extend_from_slice(b);
    Ok(v)
}
fn copy_binding(b: &MemberBinding) -> Result<MemberBinding, PurgeError> {
    Ok(MemberBinding {
        collection_id: b.collection_id,
        file_id: b.file_id,
        incarnation: b.incarnation,
        posting_source: copy_bytes(&b.posting_source)?,
    })
}
/// Charge fixed owned record storage and every variable byte, including all
/// secondary tables. The ABI also bounds its flat records before copying them.
pub(crate) struct Budget(usize);
impl Budget {
    pub(crate) fn new() -> Self {
        Self(0)
    }
    pub(crate) fn add(&mut self, n: usize) -> Result<(), PurgeError> {
        self.0 = self.0.checked_add(n).ok_or(PurgeError::LimitExceeded)?;
        if self.0 > MAX_PAYLOAD {
            return Err(PurgeError::LimitExceeded);
        }
        Ok(())
    }
    pub(crate) fn table<T>(&mut self, n: usize) -> Result<(), PurgeError> {
        self.add(
            n.checked_mul(std::mem::size_of::<T>())
                .ok_or(PurgeError::LimitExceeded)?,
        )
    }
    pub(crate) fn bytes(&mut self, b: &[u8], cap: usize) -> Result<(), PurgeError> {
        if b.len() > cap {
            return Err(PurgeError::LimitExceeded);
        }
        self.add(b.len())
    }
    fn binding(&mut self, b: &MemberBinding) -> Result<(), PurgeError> {
        self.bytes(&b.posting_source, MAX_IDENTITY)
    }
}
fn payload(s: &Snapshot) -> Result<(), PurgeError> {
    if s.seeds.len() > MAX_SEEDS || s.members.len() > MAX_MEMBERS || s.entries.len() > MAX_ENTRIES {
        return Err(PurgeError::LimitExceeded);
    }
    let mut b = Budget::new();
    macro_rules! table {
        ($field:ident,$typ:ty) => {
            b.table::<$typ>(s.$field.len())?;
        };
    }
    table!(seeds, MemberBinding);
    table!(members, MemberRecord);
    table!(source_validations, SourceValidation);
    table!(custody_receipts, CustodyReceipt);
    table!(parents, ParentMembership);
    table!(comparisons, AnchorComparison);
    table!(direct_bindings, DirectBinding);
    table!(pair_memberships, PairMembershipReceipt);
    table!(pair_custody_receipts, PairCustodyReceipt);
    table!(roots, RootRecord);
    table!(namespace_proofs, NamespaceProof);
    table!(entries, InventoryEntry);
    table!(ownership_receipts, OwnershipReceipt);
    table!(outside_claims, OutsideClaim);
    b.bytes(&s.comparison_context.captured, MAX_IDENTITY)?;
    b.bytes(&s.comparison_context.current, MAX_IDENTITY)?;
    for x in &s.seeds {
        b.binding(x)?;
    }
    for x in &s.members {
        b.binding(&x.binding)?;
        b.bytes(&x.name, MAX_IDENTITY)?;
        b.bytes(&x.key, MAX_IDENTITY)?;
    }
    for x in &s.source_validations {
        b.binding(&x.binding)?;
        if let Some(p) = &x.parent_collection {
            b.binding(p)?;
        }
    }
    for x in &s.parents {
        b.binding(&x.file)?;
        b.binding(&x.collection)?;
    }
    for x in &s.comparisons {
        b.binding(&x.seed)?;
        b.binding(&x.candidate)?;
    }
    for x in &s.direct_bindings {
        b.binding(&x.seed)?;
        b.binding(&x.candidate)?;
    }
    for x in &s.pair_memberships {
        b.binding(&x.seed)?;
        b.binding(&x.candidate)?;
        b.bytes(&x.relation_id, MAX_IDENTITY)?;
        b.bytes(&x.evidence_bytes, MAX_IDENTITY)?;
    }
    for x in &s.pair_custody_receipts {
        b.binding(&x.seed)?;
        b.binding(&x.candidate)?;
        b.bytes(&x.relation_id, MAX_IDENTITY)?;
        b.bytes(&x.evidence_bytes, MAX_IDENTITY)?;
    }
    for x in &s.roots {
        b.bytes(&x.descriptor_identity, MAX_IDENTITY)?;
    }
    for x in &s.namespace_proofs {
        b.bytes(&x.relative_path, MAX_PATH)?;
        b.bytes(&x.root_identity, MAX_IDENTITY)?;
        b.bytes(&x.ancestor_identity, MAX_IDENTITY)?;
        b.bytes(&x.mount_identity, MAX_IDENTITY)?;
    }
    for x in &s.entries {
        b.binding(&x.member)?;
        b.bytes(&x.relative_path, MAX_PATH)?;
        b.bytes(&x.object_identity, MAX_IDENTITY)?;
    }
    for x in &s.ownership_receipts {
        b.binding(&x.member)?;
        b.bytes(&x.relative_path, MAX_PATH)?;
        b.bytes(&x.object_identity, MAX_IDENTITY)?;
    }
    for x in &s.outside_claims {
        b.binding(&x.claimant)?;
        b.bytes(&x.relative_path, MAX_PATH)?;
        b.bytes(&x.object_identity, MAX_IDENTITY)?;
    }
    Ok(())
}
fn text(b: &[u8], nonempty: bool) -> Result<(), PurgeError> {
    if b.contains(&0) || (nonempty && b.is_empty()) {
        return Err(PurgeError::InvalidInput);
    }
    Ok(())
}
fn valid_binding(b: &MemberBinding) -> Result<(), PurgeError> {
    if b.collection_id <= 0
        || b.file_id.is_some_and(|x| x <= 0)
        || b.incarnation == 0
        || b.incarnation == u64::MAX
    {
        return Err(PurgeError::InvalidInput);
    }
    text(&b.posting_source, true)
}
fn path(b: &[u8], allow_root: bool) -> Result<(), PurgeError> {
    text(b, !allow_root)?;
    if b.is_empty() && allow_root {
        return Ok(());
    }
    if b[0] == b'/'
        || b.split(|x| *x == b'/')
            .any(|p| p.is_empty() || p == b"." || p == b"..")
    {
        return Err(PurgeError::InvalidInput);
    }
    Ok(())
}
fn key(b: &MemberBinding) -> (i32, Option<i32>) {
    (b.collection_id, b.file_id)
}
fn index<T: PartialEq>(
    items: &[T],
    cmp: impl Fn(&T, &T) -> Ordering,
) -> Result<Vec<&T>, PurgeError> {
    let mut out = reserved(items.len())?;
    out.extend(items.iter());
    out.sort_unstable_by(|a, b| cmp(a, b));
    for pair in out.windows(2) {
        if cmp(pair[0], pair[1]) == Ordering::Equal {
            return Err(if pair[0] == pair[1] {
                PurgeError::InvalidInput
            } else {
                PurgeError::Conflict
            });
        }
    }
    Ok(out)
}
fn find<'a, T>(items: &[&'a T], cmp: impl Fn(&T) -> Ordering) -> Option<&'a T> {
    items.binary_search_by(|x| cmp(x)).ok().map(|i| items[i])
}
fn resolve_member<'a>(
    members: &[&'a MemberRecord],
    b: &MemberBinding,
) -> Result<&'a MemberRecord, PurgeError> {
    let m = find(members, |m| key(&m.binding).cmp(&key(b))).ok_or(PurgeError::MissingInventory)?;
    if m.binding != *b {
        return Err(PurgeError::Conflict);
    }
    Ok(m)
}
fn beneath(child: &[u8], parent: &[u8]) -> bool {
    parent.is_empty()
        || child == parent
        || (child.starts_with(parent) && child.get(parent.len()) == Some(&b'/'))
}
fn pair_versions(
    version: u32,
    validator: u32,
    owner: u32,
    evidence: u32,
) -> Result<(), PurgeError> {
    if [version, validator, owner, evidence] != [1, 1, 1, 1] {
        return Err(PurgeError::Unsupported);
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct PathRef<'a> {
    root: u64,
    path: &'a [u8],
    identity: *const (),
}
fn sort_paths(paths: &mut [PathRef<'_>]) {
    paths.sort_unstable_by(|a, b| (a.root, a.path).cmp(&(b.root, b.path)));
}
fn exact_path(paths: &[PathRef<'_>], root: u64, path: &[u8], skip: Option<*const ()>) -> bool {
    let start = paths.partition_point(|x| (x.root, x.path) < (root, path));
    paths[start..]
        .iter()
        .take(2)
        .any(|x| x.root == root && x.path == path && Some(x.identity) != skip)
}
fn path_ancestor(paths: &[PathRef<'_>], root: u64, path: &[u8], skip: Option<*const ()>) -> bool {
    if exact_path(paths, root, b"", skip) {
        return true;
    }
    for end in path
        .iter()
        .enumerate()
        .filter_map(|(i, c)| if *c == b'/' { Some(i) } else { None })
        .chain(std::iter::once(path.len()))
    {
        if exact_path(paths, root, &path[..end], skip) {
            return true;
        }
    }
    false
}
fn path_descendant(
    paths: &[PathRef<'_>],
    root: u64,
    path: &[u8],
    skip: Option<*const ()>,
    include_self: bool,
) -> bool {
    if include_self && exact_path(paths, root, path, skip) {
        return true;
    }
    // Binary-search the literal path plus slash without allocating that prefix.
    let start = paths.partition_point(|x| {
        x.root < root
            || (x.root == root
                && x.path
                    .iter()
                    .copied()
                    .cmp(path.iter().copied().chain(std::iter::once(b'/')))
                    == Ordering::Less)
    });
    paths[start..].iter().take(2).any(|x| {
        x.root == root && x.path != path && beneath(x.path, path) && Some(x.identity) != skip
    })
}
fn path_overlap(paths: &[PathRef<'_>], root: u64, path: &[u8], skip: Option<*const ()>) -> bool {
    path_ancestor(paths, root, path, skip) || path_descendant(paths, root, path, skip, false)
}
fn children_first(a: &[u8], b: &[u8]) -> Ordering {
    // Component order keeps a subtree together; its directory follows children.
    // Combining raw lexical order with ad-hoc prefix reversals is not transitive
    // (a, a-foo, a/z). This comparator is a total postorder on path components.
    let mut a = a.split(|c| *c == b'/');
    let mut b = b.split(|c| *c == b'/');
    loop {
        match (a.next(), b.next()) {
            (Some(x), Some(y)) => {
                let c = x.cmp(y);
                if c != Ordering::Equal {
                    return c;
                }
            }
            (None, Some(_)) => return Ordering::Greater,
            (Some(_), None) => return Ordering::Less,
            (None, None) => return Ordering::Equal,
        }
    }
}

/// Conservative sum of every allocation made by prepare, excluding its owned
/// input. Index/path vectors and output copies are all included simultaneously;
/// unstable sorting allocates no workspace. This is a readiness bound only.
pub(crate) fn planning_allocation_bound(s: &Snapshot) -> Result<usize, PurgeError> {
    const _: () = {
        assert!(
            2 * std::mem::size_of::<&u8>()
                + 2 * std::mem::size_of::<PathRef<'static>>()
                + std::mem::size_of::<(&InventoryEntry, bool)>()
                + std::mem::size_of::<Action>()
                <= 2 * std::mem::size_of::<InventoryEntry>()
        );
        assert!(
            std::mem::size_of::<&u8>()
                + std::mem::size_of::<bool>()
                + std::mem::size_of::<MemberBinding>()
                <= 2 * std::mem::size_of::<MemberRecord>()
        );
        assert!(
            std::mem::size_of::<&u8>() + std::mem::size_of::<PathRef<'static>>()
                <= 2 * std::mem::size_of::<OutsideClaim>()
        );
        assert!(
            std::mem::size_of::<&u8>() + std::mem::size_of::<PathRef<'static>>()
                <= 2 * std::mem::size_of::<NamespaceProof>()
        );
        assert!(3 * std::mem::size_of::<&u8>() <= 2 * std::mem::size_of::<PairMembershipReceipt>());
        assert!(2 * std::mem::size_of::<&u8>() <= 2 * std::mem::size_of::<RootRecord>());
    };
    payload(s)?;
    let mut n = 0usize;
    let mut add = |count: usize, width: usize| -> Result<(), PurgeError> {
        n = n
            .checked_add(count.checked_mul(width).ok_or(PurgeError::LimitExceeded)?)
            .ok_or(PurgeError::LimitExceeded)?;
        Ok(())
    };
    let pointer = std::mem::size_of::<&u8>();
    for count in [
        s.members.len(),
        s.source_validations.len(),
        s.custody_receipts.len(),
        s.parents.len(),
        s.roots.len(),
        s.roots.len(),
        s.namespace_proofs.len(),
        s.entries.len(),
        s.entries.len(),
        s.ownership_receipts.len(),
        s.outside_claims.len(),
        s.pair_memberships.len(),
        s.pair_memberships.len(),
        s.pair_memberships.len(),
        s.pair_custody_receipts.len(),
        s.seeds.len(),
        s.comparisons.len(),
        s.direct_bindings.len(),
    ] {
        add(count, pointer)?;
    }
    add(s.members.len(), std::mem::size_of::<bool>())?;
    add(s.outside_claims.len(), std::mem::size_of::<PathRef<'_>>())?;
    add(s.entries.len(), 2 * std::mem::size_of::<PathRef<'_>>())?;
    add(s.namespace_proofs.len(), std::mem::size_of::<PathRef<'_>>())?;
    add(
        s.entries.len(),
        std::mem::size_of::<(&InventoryEntry, bool)>(),
    )?;
    add(s.entries.len(), std::mem::size_of::<Action>())?;
    add(s.members.len(), std::mem::size_of::<MemberBinding>())?;
    for e in &s.entries {
        add(e.relative_path.len(), 1)?;
        add(e.object_identity.len(), 1)?;
    }
    for m in &s.members {
        add(m.binding.posting_source.len(), 1)?;
    }
    // Fixed scratch/output per source record is <= twice its charged record;
    // copied variable bytes are a subset of the charged input bytes. Thus 3S
    // covers all input geometries, without reducing the public 64 MiB limit.
    if n > 3 * MAX_PAYLOAD {
        return Err(PurgeError::LimitExceeded);
    }
    Ok(n)
}

pub fn prepare(snapshot: Snapshot, request: [u8; 16]) -> Result<Plan, PurgeError> {
    let s = &snapshot;
    payload(s)?; // Counts/payload precede graph lookups and all planner allocations.
    if s.version != 1
        || s.revision == 0
        || s.generation == 0
        || s.generation == u64::MAX
        || s.seeds.is_empty()
    {
        return Err(PurgeError::InvalidInput);
    }
    text(&s.comparison_context.captured, true)?;
    text(&s.comparison_context.current, true)?;
    if s.comparison_context.captured != s.comparison_context.current {
        return Err(PurgeError::Conflict);
    }
    for m in &s.members {
        valid_binding(&m.binding)?;
        text(&m.name, false)?;
        text(&m.key, false)?;
        if m.source_validation_id == 0 {
            return Err(PurgeError::InvalidInput);
        }
    }
    let members = index(&s.members, |a, b| key(&a.binding).cmp(&key(&b.binding)))?;
    let sources = index(&s.source_validations, |a, b| a.id.cmp(&b.id))?;
    let custody = index(&s.custody_receipts, |a, b| a.id.cmp(&b.id))?;
    let parents = index(&s.parents, |a, b| key(&a.file).cmp(&key(&b.file)))?;
    let roots = index(&s.roots, |a, b| a.id.cmp(&b.id))?;
    let namespaces = index(&s.namespace_proofs, |a, b| a.id.cmp(&b.id))?;
    let entries = index(&s.entries, |a, b| a.id.cmp(&b.id))?;
    let ownership = index(&s.ownership_receipts, |a, b| a.id.cmp(&b.id))?;
    let _outside = index(&s.outside_claims, |a, b| a.id.cmp(&b.id))?;
    let pairs = index(&s.pair_memberships, |a, b| a.id.cmp(&b.id))?;
    let pair_custody = index(&s.pair_custody_receipts, |a, b| a.id.cmp(&b.id))?;
    // Relation/evidence reuse across different pairs is contradictory authority.
    let _relations = index(&s.pair_memberships, |a, b| {
        a.relation_id.cmp(&b.relation_id)
    })?;
    let _evidence = index(&s.pair_memberships, |a, b| {
        a.evidence_id.cmp(&b.evidence_id)
    })?;
    let mut seeds = reserved(s.seeds.len())?;
    for b in &s.seeds {
        valid_binding(b)?;
        let m = find(&members, |m| key(&m.binding).cmp(&key(b))).ok_or(PurgeError::MissingSeed)?;
        if m.binding != *b {
            return Err(PurgeError::Conflict);
        }
        seeds.push(m);
    }
    seeds.sort_unstable_by(|a, b| key(&a.binding).cmp(&key(&b.binding)));
    seeds.dedup_by(|a, b| a.binding == b.binding);
    for v in &s.source_validations {
        valid_binding(&v.binding)?;
        if v.id == 0 {
            return Err(PurgeError::InvalidInput);
        }
        if v.version != 1 || v.validator_version != 1 {
            return Err(PurgeError::Unsupported);
        }
        if let Some(parent) = &v.parent_collection {
            valid_binding(parent)?;
        }
        let c = find(&custody, |c| c.id.cmp(&v.custody_receipt_id))
            .ok_or(PurgeError::MissingInventory)?;
        if c.validator_version != v.validator_version
            || c.source_record_id != v.source_record_id
            || c.source_bytes_digest != v.source_bytes_digest
        {
            return Err(PurgeError::Conflict);
        }
    }
    for c in &s.custody_receipts {
        if c.validator_version != 1 {
            return Err(PurgeError::Unsupported);
        }
    }
    for p in &s.parents {
        valid_binding(&p.file)?;
        valid_binding(&p.collection)?;
        if p.file.file_id.is_none()
            || p.collection.file_id.is_some()
            || p.file.collection_id != p.collection.collection_id
        {
            return Err(PurgeError::InvalidInput);
        }
        resolve_member(&members, &p.file)?;
        resolve_member(&members, &p.collection)?;
    }
    for m in &s.members {
        let v = find(&sources, |v| v.id.cmp(&m.source_validation_id))
            .ok_or(PurgeError::MissingInventory)?;
        if v.binding != m.binding {
            return Err(PurgeError::Conflict);
        }
        if m.binding.file_id.is_some() {
            let p = find(&parents, |p| key(&p.file).cmp(&key(&m.binding)))
                .ok_or(PurgeError::MissingInventory)?;
            if p.file != m.binding || v.parent_collection.as_ref() != Some(&p.collection) {
                return Err(PurgeError::Conflict);
            }
            resolve_member(&members, &p.collection)?;
        } else if v.parent_collection.is_some() {
            return Err(PurgeError::Conflict);
        }
    }
    if s.namespace_proofs.is_empty() {
        return Err(PurgeError::MissingInventory);
    }
    let comparisons = index(&s.comparisons, |a, b| {
        (key(&a.seed), key(&a.candidate)).cmp(&(key(&b.seed), key(&b.candidate)))
    })?;
    for c in &s.comparisons {
        valid_binding(&c.seed)?;
        valid_binding(&c.candidate)?;
        resolve_member(&members, &c.seed)?;
        resolve_member(&members, &c.candidate)?;
        if !seeds.iter().any(|m| m.binding == c.seed) {
            return Err(PurgeError::InvalidInput);
        }
    }
    let mut selected = reserved(members.len())?;
    selected.resize(members.len(), false);
    for (i, m) in members.iter().enumerate() {
        if seeds.iter().any(|a| a.binding == m.binding) {
            selected[i] = true;
        }
        if m.binding.file_id.is_some() {
            continue;
        }
        for seed in &seeds {
            let c = find(&comparisons, |c| {
                (key(&c.seed), key(&c.candidate)).cmp(&(key(&seed.binding), key(&m.binding)))
            })
            .ok_or(PurgeError::InvalidInput)?;
            let matches = if !seed.key.is_empty() && !m.key.is_empty() {
                c.key_equal
            } else {
                c.name_equal
            };
            selected[i] |= matches;
        }
    }
    for p in &s.pair_memberships {
        pair_versions(
            p.version,
            p.validator_version,
            p.owner_kind,
            p.evidence_version,
        )?;
        text(&p.relation_id, true)?;
        text(&p.evidence_bytes, true)?;
        valid_binding(&p.seed)?;
        valid_binding(&p.candidate)?;
        let seed = resolve_member(&members, &p.seed)?;
        let candidate = resolve_member(&members, &p.candidate)?;
        let sv = find(&sources, |v| v.id.cmp(&seed.source_validation_id))
            .ok_or(PurgeError::MissingInventory)?;
        let cv = find(&sources, |v| v.id.cmp(&candidate.source_validation_id))
            .ok_or(PurgeError::MissingInventory)?;
        if (
            p.seed_source_record_id,
            p.seed_source_bytes_digest,
            p.candidate_source_record_id,
            p.candidate_source_bytes_digest,
        ) != (
            sv.source_record_id,
            sv.source_bytes_digest,
            cv.source_record_id,
            cv.source_bytes_digest,
        ) {
            return Err(PurgeError::Conflict);
        }
        let c = find(&pair_custody, |c| c.id.cmp(&p.custody_receipt_id))
            .ok_or(PurgeError::MissingInventory)?;
        pair_versions(
            c.version,
            c.validator_version,
            c.owner_kind,
            c.evidence_version,
        )?;
        if c.relation_id != p.relation_id
            || c.evidence_id != p.evidence_id
            || c.evidence_bytes != p.evidence_bytes
            || c.seed != p.seed
            || c.candidate != p.candidate
            || c.seed_source_record_id != p.seed_source_record_id
            || c.seed_source_bytes_digest != p.seed_source_bytes_digest
            || c.candidate_source_record_id != p.candidate_source_record_id
            || c.candidate_source_bytes_digest != p.candidate_source_bytes_digest
        {
            return Err(PurgeError::Conflict);
        }
    }
    for c in &s.pair_custody_receipts {
        pair_versions(
            c.version,
            c.validator_version,
            c.owner_kind,
            c.evidence_version,
        )?;
        text(&c.relation_id, true)?;
        text(&c.evidence_bytes, true)?;
        valid_binding(&c.seed)?;
        valid_binding(&c.candidate)?;
    }
    let _direct = index(&s.direct_bindings, |a, b| {
        (key(&a.seed), key(&a.candidate)).cmp(&(key(&b.seed), key(&b.candidate)))
    })?;
    for d in &s.direct_bindings {
        valid_binding(&d.seed)?;
        valid_binding(&d.candidate)?;
        if !seeds.iter().any(|m| m.binding == d.seed) {
            return Err(PurgeError::InvalidInput);
        }
        let seed = resolve_member(&members, &d.seed)?;
        let candidate = resolve_member(&members, &d.candidate)?;
        if seed.source_validation_id != d.seed_source_validation_id
            || candidate.source_validation_id != d.candidate_source_validation_id
        {
            return Err(PurgeError::Conflict);
        }
        let p = find(&pairs, |p| p.id.cmp(&d.pair_membership_receipt_id))
            .ok_or(PurgeError::MissingInventory)?;
        if p.seed != d.seed || p.candidate != d.candidate {
            return Err(PurgeError::Conflict);
        }
        let i = members
            .binary_search_by(|m| key(&m.binding).cmp(&key(&d.candidate)))
            .map_err(|_| PurgeError::MissingInventory)?;
        selected[i] = true;
    }
    // A file follows its exact selected parent, never an unrelated collection ID.
    for (i, m) in members.iter().enumerate() {
        if m.binding.file_id.is_some() {
            let p = find(&parents, |p| key(&p.file).cmp(&key(&m.binding)))
                .ok_or(PurgeError::MissingInventory)?;
            let parent = members
                .binary_search_by(|m| key(&m.binding).cmp(&key(&p.collection)))
                .map_err(|_| PurgeError::MissingInventory)?;
            if selected[i] && !selected[parent] {
                return Err(PurgeError::MissingInventory);
            }
            selected[i] |= selected[parent];
        }
        if selected[i] && !m.complete_inventory {
            return Err(PurgeError::MissingInventory);
        }
    }
    for r in &s.roots {
        if r.id == 0 {
            return Err(PurgeError::InvalidInput);
        }
        text(&r.descriptor_identity, true)?;
    }
    // Numeric-root partitions are safe only with one record per captured
    // physical descriptor identity. Aliases could otherwise hide outside
    // ownership or configured-container protection under a different root ID.
    let _root_identities = index(&s.roots, |a, b| {
        a.descriptor_identity.cmp(&b.descriptor_identity)
    })?;
    for n in &s.namespace_proofs {
        path(&n.relative_path, true)?;
        text(&n.root_identity, true)?;
        text(&n.ancestor_identity, true)?;
        text(&n.mount_identity, true)?;
        let r = find(&roots, |r| r.id.cmp(&n.root_id)).ok_or(PurgeError::MissingInventory)?;
        if r.descriptor_identity != n.root_identity {
            return Err(PurgeError::Conflict);
        }
    }
    // Distinct entry IDs may not alias one captured path, even with equal bytes.
    let _paths = index(&s.entries, |a, b| {
        (a.root_id, a.relative_path.as_slice()).cmp(&(b.root_id, b.relative_path.as_slice()))
    })?;
    for e in entries.iter().copied() {
        if e.id == 0 || e.root_id == 0 {
            return Err(PurgeError::InvalidInput);
        }
        path(&e.relative_path, false)?;
        text(&e.object_identity, true)?;
        valid_binding(&e.member)?;
        if e.kind == EntryKind::Unsupported {
            return Err(PurgeError::Unsupported);
        }
        resolve_member(&members, &e.member)?;
        if e.inventory_revision != s.revision {
            return Err(PurgeError::Conflict);
        }
        let n = find(&namespaces, |n| n.id.cmp(&e.namespace_proof_id))
            .ok_or(PurgeError::MissingInventory)?;
        if n.root_id != e.root_id || !beneath(&e.relative_path, &n.relative_path) {
            return Err(PurgeError::Conflict);
        }
        let o = find(&ownership, |o| o.id.cmp(&e.ownership_receipt_id))
            .ok_or(PurgeError::MissingInventory)?;
        if o.member != e.member
            || o.root_id != e.root_id
            || o.relative_path != e.relative_path
            || o.kind != e.kind
            || o.object_identity != e.object_identity
            || o.namespace_proof_id != e.namespace_proof_id
            || o.inventory_revision != e.inventory_revision
        {
            return Err(PurgeError::Conflict);
        }
    }
    for o in &s.ownership_receipts {
        valid_binding(&o.member)?;
        path(&o.relative_path, false)?;
        text(&o.object_identity, true)?;
        if o.kind == EntryKind::Unsupported {
            return Err(PurgeError::Unsupported);
        }
    }
    for o in &s.outside_claims {
        if o.id == 0 || o.root_id == 0 {
            return Err(PurgeError::InvalidInput);
        }
        valid_binding(&o.claimant)?;
        path(&o.relative_path, true)?;
        text(&o.object_identity, true)?;
        if find(&roots, |r| r.id.cmp(&o.root_id)).is_none() {
            return Err(PurgeError::MissingInventory);
        }
    }
    let included = |b: &MemberBinding| -> bool {
        members
            .binary_search_by(|m| key(&m.binding).cmp(&key(b)))
            .is_ok_and(|i| selected[i])
    };
    let mut claims = reserved(
        s.outside_claims
            .len()
            .checked_add(s.entries.len())
            .ok_or(PurgeError::LimitExceeded)?,
    )?;
    for o in &s.outside_claims {
        claims.push(PathRef {
            root: o.root_id,
            path: &o.relative_path,
            identity: (o as *const OutsideClaim).cast(),
        });
    }
    for e in &s.entries {
        if !included(&e.member) {
            claims.push(PathRef {
                root: e.root_id,
                path: &e.relative_path,
                identity: (e as *const InventoryEntry).cast(),
            });
        }
    }
    sort_paths(&mut claims);
    let mut namespace_paths = reserved(s.namespace_proofs.len())?;
    for n in &s.namespace_proofs {
        namespace_paths.push(PathRef {
            root: n.root_id,
            path: &n.relative_path,
            identity: (n as *const NamespaceProof).cast(),
        });
    }
    sort_paths(&mut namespace_paths);
    let mut eligible = reserved(s.entries.len())?;
    let mut tree_paths = reserved(s.entries.len())?;
    for e in &s.entries {
        if !included(&e.member) {
            continue;
        }
        let conflict = path_overlap(&claims, e.root_id, &e.relative_path, None);
        // Exact independently owned leaves inside a shared namespace remain
        // removable. An exact claim, or impossible descendant of a leaf, is a
        // contradiction. An ancestor namespace alone does not own that leaf.
        if e.kind != EntryKind::Directory
            && path_descendant(&claims, e.root_id, &e.relative_path, None, true)
        {
            return Err(PurgeError::Conflict);
        }
        if e.kind == EntryKind::Directory && conflict {
            continue;
        }
        let r = find(&roots, |r| r.id.cmp(&e.root_id)).ok_or(PurgeError::MissingInventory)?;
        let n = find(&namespaces, |n| n.id.cmp(&e.namespace_proof_id))
            .ok_or(PurgeError::MissingInventory)?;
        let nested = path_overlap(
            &namespace_paths,
            e.root_id,
            &e.relative_path,
            Some((n as *const NamespaceProof).cast()),
        );
        if e.kind == EntryKind::Directory && nested {
            continue;
        }
        let tree = e.kind == EntryKind::Directory
            && n.exclusive
            && !r.configured_container
            && !nested
            && !conflict;
        eligible.push((e, tree));
        if tree {
            tree_paths.push(PathRef {
                root: e.root_id,
                path: &e.relative_path,
                identity: (e as *const InventoryEntry).cast(),
            });
        }
    }
    sort_paths(&mut tree_paths);
    let mut actions = reserved(eligible.len())?;
    for &(e, tree) in &eligible {
        if path_ancestor(
            &tree_paths,
            e.root_id,
            &e.relative_path,
            Some((e as *const InventoryEntry).cast()),
        ) {
            continue;
        }
        let relative_path = copy_bytes(&e.relative_path)?;
        let object_identity = copy_bytes(&e.object_identity)?;
        actions.push(if tree {
            Action::RemoveTree {
                entry_id: e.id,
                root_id: e.root_id,
                relative_path,
                object_identity,
            }
        } else {
            Action::RemoveEntry {
                entry_id: e.id,
                root_id: e.root_id,
                relative_path,
                kind: e.kind,
                object_identity,
            }
        });
    }
    fn action_key(a: &Action) -> (u64, &[u8]) {
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
    actions.sort_unstable_by(|a, b| {
        let (ar, ap) = action_key(a);
        let (br, bp) = action_key(b);
        ar.cmp(&br).then_with(|| children_first(ap, bp))
    });
    let mut token_members = reserved(members.len())?;
    for (i, m) in members.iter().enumerate() {
        if selected[i] {
            token_members.push(copy_binding(&m.binding)?);
        }
    }
    Ok(Plan {
        token: PurgeToken {
            request,
            generation: s.generation,
            members: token_members,
        },
        phase: Phase::Prepared,
        journal: None,
        actions,
        snapshot,
    })
}
