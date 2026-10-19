//! Structured inventory snapshots and original per-producer durable receipts.
//! A later publication never substitutes its receipt for an earlier final ACK.
use super::*;
pub(super) const CAPTURE_TAG: u32 = 9;

#[derive(Debug, PartialEq, Eq)]
pub struct Capture {
    pub binding: MemberBinding,
    pub source_revision: u64,
    pub inventory_revision: u64,
    pub complete: bool,
    pub sources: Vec<SourceValidation>,
    pub custodies: Vec<CustodyReceipt>,
    pub parents: Vec<ParentMembership>,
    pub roots: Vec<RootRecord>,
    pub namespaces: Vec<NamespaceProof>,
    pub entries: Vec<InventoryEntry>,
    pub ownership: Vec<OwnershipReceipt>,
    pub outside: Vec<OutsideClaim>,
}
fields!(Capture, MAX_PAYLOAD; binding, source_revision, inventory_revision, complete,
    sources => MAX_MEMBERS, custodies => MAX_MEMBERS, parents => MAX_MEMBERS,
    roots => MAX_ENTRIES, namespaces => MAX_ENTRIES, entries => MAX_ENTRIES,
    ownership => MAX_ENTRIES, outside => MAX_ENTRIES);

#[derive(Debug, PartialEq, Eq)]
pub struct CaptureRecord {
    pub schema_version: u32,
    pub domain: [u8; 16],
    pub publication_sequence: u64,
    pub binding: MemberBinding,
    pub source_revision: u64,
    pub prior_inventory_revision: u64,
    pub inventory_revision: u64,
    pub complete: bool,
    pub sources: Vec<SourceValidation>,
    pub custodies: Vec<CustodyReceipt>,
    pub parents: Vec<ParentMembership>,
    pub roots: Vec<RootRecord>,
    pub namespaces: Vec<NamespaceProof>,
    pub entries: Vec<InventoryEntry>,
    pub ownership: Vec<OwnershipReceipt>,
    pub outside: Vec<OutsideClaim>,
    pub delta: OutputDelta,
}
fields!(CaptureRecord, MAX_PAYLOAD; schema_version, domain, publication_sequence,
    binding, source_revision, prior_inventory_revision, inventory_revision, complete,
    sources => MAX_MEMBERS, custodies => MAX_MEMBERS, parents => MAX_MEMBERS,
    roots => MAX_ENTRIES, namespaces => MAX_ENTRIES, entries => MAX_ENTRIES,
    ownership => MAX_ENTRIES, outside => MAX_ENTRIES, delta);

#[derive(Debug, PartialEq, Eq)]
pub struct InventoryAck {
    pub binding: MemberBinding,
    pub producer_ticket: u64,
    pub delta_sequence: u64,
    pub prior_inventory_revision: u64,
    pub inventory_revision: u64,
    pub subject_revision: u64,
    pub final_for_producer: bool,
    pub delta_digest: [u8; 32],
    pub domain: [u8; 16],
    pub journal_identity: [u8; 32],
    pub publication_sequence: u64,
    pub payload_digest: [u8; 32],
}
fn bytes(value: &[u8], maximum: usize, empty: bool) -> Result<(), PurgeError> {
    if value.len() > maximum || !empty && value.is_empty() || value.contains(&0) {
        return Err(PurgeError::InvalidInput);
    }
    Ok(())
}
fn path(value: &[u8], empty: bool) -> Result<(), PurgeError> {
    bytes(value, MAX_PATH, empty)?;
    if !value.is_empty() && (value[0] == b'/' || value.split(|c| *c == b'/').any(|p| p.is_empty() || p == b"." || p == b"..")) {
        return Err(PurgeError::InvalidInput);
    }
    Ok(())
}
fn unique<T>(values: &[T], compare: impl Fn(&T, &T) -> std::cmp::Ordering) -> Result<(), PurgeError> {
    let mut index = reserved(values.len())?;
    index.extend(values.iter());
    index.sort_unstable_by(|a, b| compare(a, b));
    if index.windows(2).any(|v| compare(v[0], v[1]).is_eq()) { return Err(PurgeError::Conflict); }
    Ok(())
}
impl CaptureRecord {
    pub fn output_owned_bytes(&self, deltas: &[OutputDelta]) -> Result<usize,PurgeError> {
        deltas.iter().try_fold(owned_size(self)?, |n,d| n.checked_add(owned_size(d)?).ok_or(PurgeError::LimitExceeded))
    }
    fn from_capture(domain: [u8; 16], c: Capture, delta: OutputDelta) -> Self {
        Self { schema_version: 1, domain, publication_sequence: 0,
            binding: c.binding, source_revision: c.source_revision,
            prior_inventory_revision: delta.prior_inventory_revision,
            inventory_revision: c.inventory_revision, complete: c.complete,
            sources: c.sources, custodies: c.custodies, parents: c.parents, roots: c.roots,
            namespaces: c.namespaces, entries: c.entries, ownership: c.ownership, outside: c.outside, delta }
    }
    pub fn ack(&self, identity: [u8; 32]) -> Result<InventoryAck, PurgeError> {
        Ok(InventoryAck { binding: copy(&self.binding)?, producer_ticket: self.delta.producer_ticket,
            delta_sequence: self.delta.sequence, prior_inventory_revision: self.prior_inventory_revision,
            inventory_revision: self.inventory_revision, subject_revision: self.source_revision,
            final_for_producer: self.delta.final_for_producer, delta_digest: payload_identity(&wire(&self.delta)?),
            domain: self.domain, journal_identity: identity, publication_sequence: self.publication_sequence,
            payload_digest: payload_identity(&wire(self)?) })
    }
}
impl Registry {
    fn validate_capture(&self, r: &CaptureRecord) -> Result<(), PurgeError> {
        // All counts and cumulative byte/owned bounds precede graph indices.
        if r.sources.len() > MAX_MEMBERS || r.custodies.len() > MAX_MEMBERS || r.parents.len() > MAX_MEMBERS
            || r.roots.len() > MAX_ENTRIES || r.namespaces.len() > MAX_ENTRIES
            || r.entries.len() > MAX_ENTRIES || r.ownership.len() > MAX_ENTRIES || r.outside.len() > MAX_ENTRIES
            || owned_size(r)? > MAX_PAYLOAD || wire(r)?.len() > MAX_PAYLOAD
        { return Err(PurgeError::LimitExceeded); }
        subjects::check_binding(&r.binding)?;
        validate_delta(&r.binding, &r.delta)?;
        let subject = self.subjects.iter().rev().find(|s| s.binding == r.binding).ok_or(PurgeError::MissingInventory)?;
        if r.schema_version != 1 || r.domain != self.domain || r.source_revision != subject.subject_revision
            || r.prior_inventory_revision != r.delta.prior_inventory_revision
            || r.inventory_revision != next(r.prior_inventory_revision)?
            || !self.id_reservations.iter().any(|v| v.id_namespace == 2 && (v.first..=v.last).contains(&r.delta.producer_ticket))
        { return Err(PurgeError::Conflict); }
        unique(&r.sources, |a,b| a.id.cmp(&b.id))?;
        unique(&r.custodies, |a,b| a.id.cmp(&b.id))?;
        unique(&r.parents, |a,b| a.file.cmp(&b.file))?;
        unique(&r.roots, |a,b| a.id.cmp(&b.id))?;
        unique(&r.namespaces, |a,b| a.id.cmp(&b.id))?;
        unique(&r.entries, |a,b| a.id.cmp(&b.id))?;
        unique(&r.ownership, |a,b| a.id.cmp(&b.id))?;
        unique(&r.outside, |a,b| a.id.cmp(&b.id))?;
        if !r.sources.contains(&subject.source) || !r.custodies.contains(&subject.custody) {
            return Err(PurgeError::MissingInventory);
        }
        for s in &r.sources {
            let retained = self.subjects.iter().find(|v| v.binding == s.binding && &v.source == s).ok_or(PurgeError::MissingInventory)?;
            if &retained.source != s || !r.custodies.contains(&retained.custody) { return Err(PurgeError::Conflict); }
        }
        for p in &r.parents {
            let file = self.subjects.iter().find(|s| s.binding == p.file).ok_or(PurgeError::MissingInventory)?;
            if file.parent.as_ref() != Some(&p.collection) { return Err(PurgeError::Conflict); }
        }
        if let Some(parent) = &subject.parent {
            if !r.parents.iter().any(|p| p.file == r.binding && &p.collection == parent) {
                return Err(PurgeError::MissingInventory);
            }
        }
        for root in &r.roots {
            if root.id == 0 { return Err(PurgeError::InvalidInput); }
            bytes(&root.descriptor_identity, MAX_IDENTITY, false)?;
        }
        for n in &r.namespaces {
            path(&n.relative_path, true)?;
            bytes(&n.root_identity, MAX_IDENTITY, false)?;
            bytes(&n.ancestor_identity, MAX_IDENTITY, false)?;
            bytes(&n.mount_identity, MAX_IDENTITY, false)?;
            let root = r.roots.iter().find(|v| v.id == n.root_id).ok_or(PurgeError::MissingInventory)?;
            if n.id == [0;32] || root.descriptor_identity != n.root_identity
                || root.configured_container && n.exclusive
            { return Err(PurgeError::Conflict); }
        }
        for e in &r.entries {
            path(&e.relative_path, false)?; bytes(&e.object_identity, MAX_IDENTITY, false)?;
            let n = r.namespaces.iter().find(|n| n.id == e.namespace_proof_id).ok_or(PurgeError::MissingInventory)?;
            let o = r.ownership.iter().find(|o| o.id == e.ownership_receipt_id).ok_or(PurgeError::MissingInventory)?;
            if e.id == 0 || e.member != r.binding || e.inventory_revision == 0 || e.inventory_revision > r.inventory_revision
                || e.kind == EntryKind::Unsupported || e.kind == EntryKind::Directory && !n.exclusive
                || n.root_id != e.root_id || !prefix(&n.relative_path, &e.relative_path)
                || o.member != e.member || o.root_id != e.root_id || o.relative_path != e.relative_path
                || o.kind != e.kind || o.object_identity != e.object_identity
                || o.namespace_proof_id != e.namespace_proof_id || o.inventory_revision != e.inventory_revision
            { return Err(PurgeError::Conflict); }
            for outside in &r.outside {
                if outside.root_id == e.root_id && (outside.relative_path == e.relative_path
                    || e.kind == EntryKind::Directory && prefix(&e.relative_path, &outside.relative_path))
                { return Err(PurgeError::Conflict); }
            }
        }
        for o in &r.ownership {
            subjects::check_binding(&o.member)?; path(&o.relative_path, false)?; bytes(&o.object_identity, MAX_IDENTITY, false)?;
            if o.id == [0;32] || o.member != r.binding || o.inventory_revision == 0 || o.inventory_revision > r.inventory_revision {
                return Err(PurgeError::Conflict);
            }
        }
        for o in &r.outside {
            subjects::check_binding(&o.claimant)?; path(&o.relative_path, false)?; bytes(&o.object_identity, MAX_IDENTITY, false)?;
            if o.id == 0 || o.claimant == r.binding || !r.roots.iter().any(|root| root.id == o.root_id) {
                return Err(PurgeError::Conflict);
            }
        }
        let old = self.captures.iter().rev().find(|v| v.binding == r.binding);
        let active = self.operations.iter().find(|p| p.token.members.contains(&r.binding)
            && p.journal.as_ref().is_some_and(|j| !j.released));
        let prior_revision = active.map_or_else(|| old.map_or(0, |v| v.inventory_revision), |p| p.snapshot.revision);
        if prior_revision != r.prior_inventory_revision { return Err(PurgeError::Conflict); }
        let old_entries = old.map_or(&[][..], |v| v.entries.as_slice());
        for change in &r.delta.changes {
            if old_entries.iter().find(|e| e.id == change.entry_id) != change.before.as_ref()
                || r.entries.iter().find(|e| e.id == change.entry_id) != change.after.as_ref()
            { return Err(PurgeError::Conflict); }
        }
        for e in old_entries.iter().chain(r.entries.iter()) {
            if !r.delta.changes.iter().any(|c| c.entry_id == e.id)
                && old_entries.iter().find(|v| v.id == e.id) != r.entries.iter().find(|v| v.id == e.id)
            { return Err(PurgeError::Conflict); }
        }
        if let Some(last) = self.captures.iter().rev().find(|v| v.binding == r.binding && v.delta.producer_ticket == r.delta.producer_ticket) {
            if last.delta.final_for_producer || r.delta.sequence != next(last.delta.sequence)? { return Err(PurgeError::Conflict); }
        } else if r.delta.sequence != 1 { return Err(PurgeError::Conflict); }
        Ok(())
    }
    pub fn store_capture(&mut self, capture: Capture, delta: OutputDelta, host: &mut impl Host) -> Result<InventoryAck, PurgeError> {
        self.ready(host)?;
        let mut record = CaptureRecord::from_capture(self.domain, capture, delta);
        if let Some(old) = self.captures.iter().find(|v| v.binding == record.binding
            && v.delta.producer_ticket == record.delta.producer_ticket && v.delta.sequence == record.delta.sequence)
        {
            record.publication_sequence = old.publication_sequence;
            return if old == &record { old.ack(self.journal_identity) } else { Err(PurgeError::Conflict) };
        }
        self.validate_capture(&record)?;
        let size = wire(&record)?.len();
        record.publication_sequence = self.sequence.checked_add(size.div_ceil(CHUNK_BYTES) as u64 + 1).ok_or(PurgeError::LimitExceeded)?;
        let image = wire(&record)?;
        let ack = record.ack(self.journal_identity)?;
        let (candidate, retained) = self.capture_candidate(&record, image.len().div_ceil(CHUNK_BYTES) + 1)?;
        self.captures.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        self.inventory.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        // Same existing prepared/stopping inventory transition, committed in the
        // tag9 image atomically with its structured receipt. No second tag3 ACK.
        self.publish_image(CAPTURE_TAG, [0;16], 0, &image, host)?;
        if let Some((i,p)) = candidate { self.operations[i] = p; }
        self.inventory.push(retained);
        self.captures.push(record);
        Ok(ack)
    }
    fn capture_candidate(&self, record: &CaptureRecord, frames: usize)
        -> Result<(Option<(usize, Plan)>, InventoryFrame), PurgeError>
    {
        if self.inventory.len() >= MAX_FRAMES || self.inventory_replay(&record.binding, &record.delta)? {
            return Err(PurgeError::Conflict);
        }
        let candidate = self.inventory_candidate(&record.binding, &record.delta, record.publication_sequence)?;
        let retained = InventoryFrame { domain:self.domain, sequence:record.publication_sequence,
            high_water:self.high_water, binding:copy(&record.binding)?, delta:copy(&record.delta)? };
        let size = owned_size(record)?.checked_add(owned_size(&retained)?).ok_or(PurgeError::LimitExceeded)?;
        match &candidate {
            Some((i,p)) => self.resources(Some(*i), Some(p), size, frames)?,
            None => self.resources(None, None, size, frames)?,
        }
        Ok((candidate, retained))
    }
    pub fn lookup_inventory_ack(&self, binding: &MemberBinding, producer: u64, sequence: u64,
        digest: [u8;32], host: &impl Host) -> Result<InventoryAck, PurgeError>
    {
        self.ready(host)?; subjects::check_binding(binding)?;
        let record = self.captures.iter().find(|v| &v.binding == binding
            && v.delta.producer_ticket == producer && v.delta.sequence == sequence).ok_or(PurgeError::MissingInventory)?;
        let ack = record.ack(self.journal_identity)?;
        if ack.delta_digest != digest { return Err(PurgeError::Conflict); }
        Ok(ack)
    }
    pub fn load_capture(&self, binding: &MemberBinding, host: &impl Host) -> Result<CaptureRecord, PurgeError> {
        self.ready(host)?; subjects::check_binding(binding)?;
        copy(self.captures.iter().rev().find(|v| &v.binding == binding).ok_or(PurgeError::MissingInventory)?)
    }
    pub fn load_inventory_data(&self, binding: &MemberBinding, host: &impl Host)
        -> Result<(CaptureRecord, Vec<OutputDelta>), PurgeError>
    {
        self.ready(host)?; subjects::check_binding(binding)?;
        let latest = self.captures.iter().rev().find(|v| &v.binding == binding).ok_or(PurgeError::MissingInventory)?;
        let mut budget = owned_size(latest)?;
        let mut count = 0usize;
        for r in self.inventory.iter().filter(|r| &r.binding == binding) {
            budget = budget.checked_add(owned_size(&r.delta)?).ok_or(PurgeError::LimitExceeded)?;
            count += 1;
        }
        if budget > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        let mut deltas = reserved(count)?;
        for r in self.inventory.iter().filter(|r| &r.binding == binding) { deltas.push(copy(&r.delta)?); }
        Ok((copy(latest)?, deltas))
    }
    pub(super) fn recover_capture(&mut self, sequence: u64, image: &[u8]) -> Result<(), PurgeError> {
        if image.len() > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        let record: CaptureRecord = unwire(image)?;
        if record.publication_sequence != sequence { return Err(PurgeError::CorruptJournal); }
        self.validate_capture(&record)?;
        let (candidate,retained) = self.capture_candidate(&record,0)?;
        self.captures.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        self.inventory.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        if let Some((i,p)) = candidate { self.operations[i] = p; }
        self.inventory.push(retained);
        self.captures.push(record);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::subjects::tests::{host,capture,template,admit_fixture};
    fn snapshot(subject:&subjects::SubjectRecord, revision:u64) -> Capture {
        let binding=subject.binding.clone();
        let owner=OwnershipReceipt { id:[7;32], member:binding.clone(), root_id:1,
            relative_path:b"owned.bin".to_vec(), kind:EntryKind::Regular,
            object_identity:b"held-inode".to_vec(), namespace_proof_id:[6;32], inventory_revision:1 };
        let entry=InventoryEntry { id:1, member:binding.clone(), root_id:1, relative_path:owner.relative_path.clone(),
            kind:owner.kind, object_identity:owner.object_identity.clone(), namespace_proof_id:owner.namespace_proof_id,
            ownership_receipt_id:owner.id, inventory_revision:1 };
        let mut other=binding.clone(); other.incarnation+=1;
        Capture { binding,source_revision:subject.subject_revision,inventory_revision:revision,complete:true,
            sources:vec![copy(&subject.source).unwrap()],custodies:vec![copy(&subject.custody).unwrap()],parents:vec![],
            roots:vec![RootRecord {id:1,descriptor_identity:b"root".to_vec(),configured_container:true}],
            namespaces:vec![NamespaceProof {id:[6;32],root_id:1,relative_path:vec![],root_identity:b"root".to_vec(),
                ancestor_identity:b"ancestor".to_vec(),mount_identity:b"mount".to_vec(),exclusive:false}],
            entries:vec![entry],ownership:vec![owner],
            outside:vec![OutsideClaim {id:1,root_id:1,relative_path:b"unrelated.bin".to_vec(),claimant:other,object_identity:b"sentinel".to_vec()}] }
    }
    fn first_delta(c:&Capture, producer:u64) -> OutputDelta {
        OutputDelta {producer_ticket:producer,sequence:1,prior_inventory_revision:0,final_for_producer:true,
            changes:vec![InventoryChange {entry_id:1,before:None,after:Some(copy(&c.entries[0]).unwrap()),
                ownership:Some(copy(&c.ownership[0]).unwrap()),prior_absent:true}]}
    }
    #[test]
    fn original_final_ack_survives_other_producer_handle_loss_and_restart() {
        // Journal unit evidence only; real held-descriptor/writer proof is native.
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();
        let producers=r.reserve_ids(2,[3;16],2,&mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let mut p=r.prepare_subject(template(&r,&ids),&capture(),&h).unwrap();
        let subject=r.store_prepared_subject(&mut p,&mut h).unwrap();
        let c=snapshot(&subject,1);let d=first_delta(&c,producers.first);
        let original=r.store_capture(c,d,&mut h).unwrap();
        let old_sequence=original.publication_sequence;let digest=original.delta_digest;
        let later=r.store_capture(snapshot(&subject,2),OutputDelta {producer_ticket:producers.last,
            sequence:1,prior_inventory_revision:1,changes:vec![],final_for_producer:true},&mut h).unwrap();
        assert!(later.publication_sequence>old_sequence);
        drop(original);drop(later);
        let r=Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames).unwrap();
        let restored=r.lookup_inventory_ack(&subject.binding,producers.first,1,digest,&h).unwrap();
        assert_eq!(restored.publication_sequence,old_sequence);
        assert_eq!(restored.inventory_revision,1);assert!(restored.final_for_producer);
        let (loaded,deltas)=r.load_inventory_data(&subject.binding,&h).unwrap();
        assert_eq!(loaded.inventory_revision,2);assert_eq!(deltas.len(),2);
        assert_eq!(loaded.entries.len(),1);assert_eq!(loaded.entries[0].relative_path,b"owned.bin");
        assert_eq!(loaded.outside[0].relative_path,b"unrelated.bin");
        assert!(!loaded.namespaces[0].exclusive);
        assert!(r.lookup_inventory_ack(&subject.binding,producers.first,1,[0;32],&h).is_err());
    }
    #[test]
    fn no_broad_shared_directory_or_unknown_delta_or_uncertain_ack() {
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();
        let producer=r.reserve_ids(2,[3;16],1,&mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let mut p=r.prepare_subject(template(&r,&ids),&capture(),&h).unwrap();
        let subject=r.store_prepared_subject(&mut p,&mut h).unwrap();
        let mut c=snapshot(&subject,1);c.namespaces[0].exclusive=true;
        let d=first_delta(&c,producer.first);let before=h.frames.len();
        assert_eq!(r.store_capture(c,d,&mut h),Err(PurgeError::Conflict));
        assert_eq!(h.frames.len(),before);
        let c=snapshot(&subject,1);let mut d=first_delta(&c,producer.first);d.changes.clear();
        assert_eq!(r.store_capture(c,d,&mut h),Err(PurgeError::Conflict));
        assert_eq!(h.frames.len(),before);
        let c=snapshot(&subject,1);let d=first_delta(&c,producer.first);
        h.fail_at=Some(r.sequence+2); // first chunk succeeds, final commit fails
        assert_eq!(r.store_capture(c,d,&mut h),Err(PurgeError::Persistence));
        assert!(r.requires_recovery());
        assert!(matches!(Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames),Err(PurgeError::RecoveryRequired)));
    }
}
