//! Durable subject identities. Operation generations never allocate these IDs.
//! Inputs are owned adapter captures; checksums do not grant filesystem custody.
use super::*;

pub(super) const IDS_TAG: u32 = 7;
pub(super) const SUBJECT_TAG: u32 = 8;

#[derive(Debug, PartialEq, Eq)]
pub struct IdReservation {
    pub schema_version: u32,
    pub domain: [u8; 16],
    pub publication_sequence: u64,
    pub id_namespace: u32,
    pub request: [u8; 16],
    pub first: u64,
    pub last: u64,
    pub high_water: u64,
    pub count: u32,
}
fields!(IdReservation; schema_version, domain, publication_sequence,
    id_namespace, request, first, last, high_water, count);

#[derive(Debug, PartialEq, Eq)]
pub struct SubjectRecord {
    pub schema_version: u32,
    pub domain: [u8; 16],
    pub publication_sequence: u64,
    pub transition: u32,
    pub binding: MemberBinding,
    pub prior: Option<MemberBinding>,
    pub source: SourceValidation,
    pub custody: CustodyReceipt,
    pub parent: Option<MemberBinding>,
    pub reservation_request: [u8; 16],
    pub reservation_sequence: u64,
    pub subject_revision: u64,
    pub source_kind: u32,
    pub original_source_byte_length: u64,
    pub original_source_bytes_digest: [u8; 32],
    pub expected_prior_subject_revision: u64,
    pub expected_prior_publication_sequence: u64,
    pub original_source_bytes: Vec<u8>,
    pub immutable_capture_version: u32,
    pub immutable_source_bytes: Vec<u8>,
}
// Schema1 remains readable as an explicitly capture-missing historical record.
// Only schema2 can validate a current disk body.
impl Wire for SubjectRecord {
    const MIN:usize=1;
    fn heap_size(&self)->Result<usize,PurgeError>{
        let mut n=0usize;
        n=n.checked_add(self.schema_version.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.domain.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.publication_sequence.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.transition.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.binding.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.prior.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.source.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.custody.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.parent.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.reservation_request.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.reservation_sequence.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.subject_revision.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.source_kind.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.original_source_byte_length.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.original_source_bytes_digest.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.expected_prior_subject_revision.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.expected_prior_publication_sequence.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.original_source_bytes.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        n=n.checked_add(self.immutable_source_bytes.heap_size()?).ok_or(PurgeError::LimitExceeded)?;
        Ok(n)
    }
    fn put(&self,w:&mut Writer)->Result<(),PurgeError>{
        self.schema_version.put(w)?;
        self.domain.put(w)?;
        self.publication_sequence.put(w)?;
        self.transition.put(w)?;
        self.binding.put(w)?;
        self.prior.put(w)?;
        self.source.put(w)?;
        self.custody.put(w)?;
        self.parent.put(w)?;
        self.reservation_request.put(w)?;
        self.reservation_sequence.put(w)?;
        self.subject_revision.put(w)?;
        self.source_kind.put(w)?;
        self.original_source_byte_length.put(w)?;
        self.original_source_bytes_digest.put(w)?;
        self.expected_prior_subject_revision.put(w)?;
        self.expected_prior_publication_sequence.put(w)?;
        if self.schema_version==2 {self.original_source_bytes.put(w)?;self.immutable_capture_version.put(w)?;self.immutable_source_bytes.put(w)?;}
        else if self.schema_version!=1{return Err(PurgeError::InvalidInput);}Ok(())
    }
    fn get(r:&mut Reader<'_>)->Result<Self,PurgeError>{
        r.within_heap(MAX_PAYLOAD,|r|{
            let schema_version=u32::get(r)?;if !matches!(schema_version,1|2){return Err(PurgeError::CorruptJournal);}
            let mut value=Self {
                schema_version,
                domain:Wire::get(r)?,
                publication_sequence:Wire::get(r)?,
                transition:Wire::get(r)?,
                binding:Wire::get(r)?,
                prior:Wire::get(r)?,
                source:Wire::get(r)?,
                custody:Wire::get(r)?,
                parent:Wire::get(r)?,
                reservation_request:Wire::get(r)?,
                reservation_sequence:Wire::get(r)?,
                subject_revision:Wire::get(r)?,
                source_kind:Wire::get(r)?,
                original_source_byte_length:Wire::get(r)?,
                original_source_bytes_digest:Wire::get(r)?,
                expected_prior_subject_revision:Wire::get(r)?,
                expected_prior_publication_sequence:Wire::get(r)?,
                original_source_bytes:Vec::new(),immutable_capture_version:0,immutable_source_bytes:Vec::new(),
            };
            if schema_version==2 {
                value.original_source_bytes=BoundedWire::get_bounded(r,MAX_PAYLOAD)?;
                value.immutable_capture_version=u32::get(r)?;
                value.immutable_source_bytes=BoundedWire::get_bounded(r,MAX_PAYLOAD)?;
            }Ok(value)
        })
    }
}

#[derive(Debug)]
pub struct PreparedSubject {
    record: SubjectRecord,
    journal_identity: [u8; 32],
    consumed: bool,
    committed_digest: Option<[u8; 32]>,
    expected_prior: Option<SubjectRecord>,
}
impl PreparedSubject {
    pub fn committed_digest(&self) -> Option<[u8; 32]> { self.committed_digest }
}

pub(super) fn check_binding(b: &MemberBinding) -> Result<(), PurgeError> {
    if b.collection_id <= 0 || b.file_id.is_some_and(|id| id <= 0)
        || b.incarnation == 0 || b.incarnation == u64::MAX || b.posting_source.is_empty()
        || b.posting_source.contains(&0)
        || b.posting_source.len() > MAX_IDENTITY
    {
        return Err(PurgeError::InvalidInput);
    }
    Ok(())
}

fn source_key(record: &SubjectRecord) -> Result<[u8; 32], PurgeError> {
    source_key_accounted(record,None)
}
fn source_key_accounted(record: &SubjectRecord, capacity:Option<&HeldCapacity>) -> Result<[u8;32],PurgeError> {
    let operation=||source_key_body(record,capacity);
    match capacity{Some(c)=>c.scratch(operation),None=>operation()}
}
fn source_key_body(record:&SubjectRecord,capacity:Option<&HeldCapacity>)->Result<[u8;32],PurgeError>{
    // Exact F4 K framing; publication sequence deliberately is not a key input.
    let binding = wire_accounted(&record.binding,capacity)?;
    let parent = wire_accounted(&record.parent,capacity)?;
    let n = 17usize.checked_add(16).and_then(|n| n.checked_add(binding.len()))
        .and_then(|n| n.checked_add(parent.len())).and_then(|n| n.checked_add(52))
        .ok_or(PurgeError::LimitExceeded)?;
    if n > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
    let mut bytes = reserved_accounted(n,capacity)?;
    bytes.extend_from_slice(b"PURGE-SOURCE-KEY1");
    bytes.extend_from_slice(&record.domain);
    bytes.extend_from_slice(&binding);
    bytes.extend_from_slice(&parent);
    bytes.extend_from_slice(&record.subject_revision.to_le_bytes());
    bytes.extend_from_slice(&record.source_kind.to_le_bytes());
    bytes.extend_from_slice(&record.original_source_byte_length.to_le_bytes());
    bytes.extend_from_slice(&record.original_source_bytes_digest);
    Ok(payload_identity(&bytes))
}

// Mechanical envelope checking happens before any copy. Source validators and
// held descriptor custody must independently authenticate the captured bodies.
fn check_capture(kind: u32, bytes: &[u8]) -> Result<(), PurgeError> {
    if bytes.len() > MAX_PAYLOAD || !bytes.starts_with(b"PURGE-SOURCE-BYTES1") {
        return Err(PurgeError::InvalidInput);
    }
    struct Capture<'a> { bytes: &'a [u8], pos: usize }
    impl Capture<'_> {
        fn take(&mut self, n: usize) -> Result<&[u8], PurgeError> {
            let end = self.pos.checked_add(n).ok_or(PurgeError::LimitExceeded)?;
            let part = self.bytes.get(self.pos..end).ok_or(PurgeError::InvalidInput)?;
            self.pos = end;
            Ok(part)
        }
        fn number(&mut self) -> Result<u32, PurgeError> {
            Ok(u32::from_le_bytes(self.take(4)?.try_into().map_err(|_| PurgeError::InvalidInput)?))
        }
        fn body(&mut self, required: bool) -> Result<(), PurgeError> {
            let n = self.number()? as usize;
            let b = self.take(n)?;
            if required && b.is_empty() || !b.is_empty() && (b.last() != Some(&b'\n') || b.contains(&0)) {
                return Err(PurgeError::InvalidInput);
            }
            Ok(())
        }
    }
    let mut r = Capture { bytes, pos: 19 };
    if r.number()? != 1 || r.number()? != kind { return Err(PurgeError::InvalidInput); }
    match kind {
        1 => {
            let format = r.number()?;
            if !(47..=66).contains(&format) { return Err(PurgeError::InvalidInput); }
            r.body(true)?;
            let extras = r.number()?;
            if !matches!(extras, 0 | 66) || format == 64 && extras != 66
                || matches!(format, 65 | 66) && extras != 0
            { return Err(PurgeError::InvalidInput); }
            let before = r.pos;
            r.body(extras != 0)?;
            if extras == 0 && r.pos != before + 4 { return Err(PurgeError::InvalidInput); }
        }
        2 => {
            if !(1..=9).contains(&r.number()?) { return Err(PurgeError::InvalidInput); }
            r.body(true)?;
            match r.take(1)?[0] {
                0 => (),
                1 => {
                    if !(1..=9).contains(&r.number()?) || r.take(1)?[0] > 1 {
                        return Err(PurgeError::InvalidInput);
                    }
                    r.body(true)?;
                }
                _ => return Err(PurgeError::InvalidInput),
            }
        }
        _ => return Err(PurgeError::InvalidInput),
    }
    if r.pos != bytes.len() { return Err(PurgeError::InvalidInput); }
    Ok(())
}

impl Registry {
    pub fn subject_high_water(&self) -> Result<u64, PurgeError> { self.id_high_water(1) }
    pub fn journal_domain(&self) -> [u8; 16] { self.domain }
    fn id_high_water(&self, namespace: u32) -> Result<u64, PurgeError> {
        if !matches!(namespace, 1 | 2) { return Err(PurgeError::InvalidInput); }
        Ok(self.id_reservations.iter().rev().find(|r| r.id_namespace == namespace)
            .map_or(0, |r| r.high_water))
    }
    fn check_reservation(&self, r: &IdReservation) -> Result<(), PurgeError> {
        if r.schema_version != 1 || r.domain != self.domain || r.request == [0; 16]
            || r.count == 0 || r.count as usize > MAX_MEMBERS
            || r.first != next(self.id_high_water(r.id_namespace)?)?
            || r.last != r.first.checked_add(u64::from(r.count) - 1).ok_or(PurgeError::LimitExceeded)?
            || r.high_water != r.last
            || self.id_reservations.iter().any(|old| old.id_namespace == r.id_namespace && old.request == r.request)
        { return Err(PurgeError::Conflict); }
        Ok(())
    }
    pub fn reserve_ids(&mut self, namespace: u32, request: [u8; 16], count: u32,
        host: &mut impl Host) -> Result<IdReservation, PurgeError>
    {
        self.ready(host)?;
        if let Some(old) = self.id_reservations.iter().find(|r| r.id_namespace == namespace && r.request == request) {
            return if old.count == count { copy(old) } else { Err(PurgeError::Conflict) };
        }
        let first = next(self.id_high_water(namespace)?)?;
        let last = first.checked_add(u64::from(count).checked_sub(1).ok_or(PurgeError::InvalidInput)?)
            .ok_or(PurgeError::LimitExceeded)?;
        let mut r = IdReservation { schema_version: 1, domain: self.domain, publication_sequence: 0,
            id_namespace: namespace, request, first, last, high_water: last, count };
        self.check_reservation(&r)?;
        r.publication_sequence = self.extension_sequence(&r)?;
        let output = copy(&r)?;
        let image = wire(&r)?;
        self.resources(None, None, owned_size(&r)?, image.len().div_ceil(CHUNK_BYTES) + 1)?;
        self.id_reservations.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        // On partial publication the registry is poisoned; recovery cannot skip
        // orphan chunks, so no uncertain reservation can be recycled.
        self.publish_image(IDS_TAG, [0; 16], 0, &image, host)?;
        self.id_reservations.push(r);
        Ok(output)
    }
    fn extension_sequence<T: Wire>(&self, value: &T) -> Result<u64, PurgeError> {
        let n = wire(value)?.len();
        if n > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        self.sequence.checked_add(n.div_ceil(CHUNK_BYTES) as u64 + 1).ok_or(PurgeError::LimitExceeded)
    }
    fn current_subject(&self, binding: &MemberBinding) -> Option<&SubjectRecord> {
        self.subjects.iter().rev().find(|s| &s.binding == binding)
    }
    fn expected_prior<'a>(&'a self, r: &SubjectRecord) -> Result<Option<&'a SubjectRecord>, PurgeError> {
        // Historical exact references remain loadable, but only the latest
        // subject for this numeric key can authorize a replacement/update.
        let current = self.subjects.iter().rev().find(|s|
            s.binding.collection_id == r.binding.collection_id && s.binding.file_id == r.binding.file_id);
        match (&r.prior, r.transition) {
            (None, 1 | 2) if r.expected_prior_subject_revision == 0
                && r.expected_prior_publication_sequence == 0 && current.is_none() => Ok(None),
            (Some(binding), 3 | 4) => {
                let prior = self.current_subject(binding).ok_or(PurgeError::Conflict)?;
                if current != Some(prior)
                    || binding.collection_id != r.binding.collection_id || binding.file_id != r.binding.file_id
                    || r.expected_prior_subject_revision == 0 || r.expected_prior_publication_sequence == 0
                    || prior.subject_revision != r.expected_prior_subject_revision
                    || prior.publication_sequence != r.expected_prior_publication_sequence
                    || (r.transition == 3 && (binding == &r.binding || binding.incarnation == r.binding.incarnation))
                    || (r.transition == 4 && (binding != &r.binding || prior.parent != r.parent
                        || prior.reservation_request != r.reservation_request
                        || prior.reservation_sequence != r.reservation_sequence))
                { return Err(PurgeError::Conflict); }
                Ok(Some(prior))
            }
            _ => Err(PurgeError::Conflict),
        }
    }
    fn check_subject(&self, r: &SubjectRecord) -> Result<(), PurgeError> {
        check_binding(&r.binding)?;
        let reserved = self.id_reservations.iter().any(|v| v.id_namespace == 1
            && v.request == r.reservation_request && v.publication_sequence == r.reservation_sequence
            && (v.first..=v.last).contains(&r.binding.incarnation));
        let prior = self.expected_prior(r)?;
        let expected_revision = if r.transition == 4 {
            prior.ok_or(PurgeError::Conflict)?.subject_revision.checked_add(1).ok_or(PurgeError::LimitExceeded)?
        } else { 1 };
        if !reserved || !matches!(r.schema_version,1|2) || r.domain != self.domain || r.subject_revision != expected_revision
            || !matches!(r.transition, 1..=4) || !matches!(r.source_kind, 1 | 2)
            || (r.source_kind == 2) != r.binding.file_id.is_some()
            || r.original_source_byte_length == 0 || r.original_source_byte_length > MAX_PAYLOAD as u64
            || r.source.version != 1 || r.source.validator_version != 1 || r.source.id == 0
            || r.custody.validator_version != 1 || r.custody.id == [0; 32]
            || r.source.binding != r.binding || r.source.parent_collection != r.parent
            || r.source.custody_receipt_id != r.custody.id
            || r.source.source_record_id != source_key(r)?
            || r.custody.source_record_id != r.source.source_record_id
            || r.source.source_bytes_digest != r.original_source_bytes_digest
            || r.custody.source_bytes_digest != r.original_source_bytes_digest
            || r.transition != 4 && self.subjects.iter().any(|s| s.binding.incarnation == r.binding.incarnation)
        { return Err(PurgeError::Conflict); }
        if r.schema_version==2 {
            self.validate_subject_custody(r)?;
            self.validate_intake_source(&r.binding,r.source_kind,&r.original_source_bytes)?;
            if r.immutable_capture_version!=1||r.original_source_bytes.len() as u64!=r.original_source_byte_length
                ||payload_identity(&r.original_source_bytes)!=r.original_source_bytes_digest
                ||source_codec::project(r.source_kind,&r.original_source_bytes)?!=r.immutable_source_bytes {
                return Err(PurgeError::Conflict);
            }
        }else if !r.original_source_bytes.is_empty()||r.immutable_capture_version!=0||!r.immutable_source_bytes.is_empty(){return Err(PurgeError::CorruptJournal);}
        match (&r.binding.file_id, &r.parent) {
            (Some(_), Some(parent)) if parent.file_id.is_none()
                && parent.collection_id == r.binding.collection_id
                && self.subjects.iter().any(|s| &s.binding == parent) => (),
            (None, None) => (),
            _ => return Err(PurgeError::Conflict),
        }
        Ok(())
    }
    pub fn prepare_subject(&self, mut record: SubjectRecord, original: &[u8],
        host: &impl Host) -> Result<PreparedSubject, PurgeError>
    {
        self.ready(host)?;
        if record.source.source_record_id != [0; 32] || record.source.source_bytes_digest != [0; 32]
            || record.custody.source_record_id != [0; 32] || record.custody.source_bytes_digest != [0; 32]
            || record.original_source_byte_length != 0
        { return Err(PurgeError::InvalidInput); }
        check_capture(record.source_kind, original)?;
        record.original_source_bytes=Vec::new();record.immutable_source_bytes=Vec::new();
        record.schema_version = 2;
        record.domain = self.domain;
        record.publication_sequence = 0;
        let prior=self.expected_prior(&record)?;
        let base_bytes=owned_size(&record)?.checked_add(prior.map(owned_size).transpose()?.unwrap_or(0))
            .and_then(|n|n.checked_add(original.len())).ok_or(PurgeError::LimitExceeded)?;
        if base_bytes>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}
        let projection_bytes=source_codec::project_size(record.source_kind,original)?;
        if base_bytes.checked_add(projection_bytes).ok_or(PurgeError::LimitExceeded)?>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}
        // No original/projection/prior copy or validation scratch allocation
        // precedes the complete prepared-object logical64MiB bound above.
        self.validate_subject_custody(&record)?;
        self.validate_intake_source(&record.binding,record.source_kind,original)?;
        let immutable=source_codec::project(record.source_kind,original)?;
        record.original_source_bytes=copy_bytes(original)?;
        record.immutable_capture_version=1;record.immutable_source_bytes=immutable;
        let expected_prior=prior.map(copy).transpose()?;
        record.subject_revision = if record.transition == 4 {
            expected_prior.as_ref().ok_or(PurgeError::Conflict)?.subject_revision.checked_add(1).ok_or(PurgeError::LimitExceeded)?
        } else { 1 };
        record.original_source_byte_length = original.len() as u64;
        record.original_source_bytes_digest = payload_identity(original);
        record.source.source_bytes_digest = record.original_source_bytes_digest;
        record.custody.source_bytes_digest = record.original_source_bytes_digest;
        record.source.source_record_id = source_key(&record)?;
        record.custody.source_record_id = record.source.source_record_id;
        self.check_subject(&record)?;
        Ok(PreparedSubject { record, journal_identity: self.journal_identity,
            consumed: false, committed_digest: None, expected_prior })
    }
    pub fn store_prepared_subject(&mut self, prepared: &mut PreparedSubject,
        host: &mut impl Host) -> Result<SubjectRecord, PurgeError>
    {
        self.ready(host)?;
        if prepared.consumed || prepared.journal_identity != self.journal_identity
            || payload_identity(&prepared.record.original_source_bytes) != prepared.record.original_source_bytes_digest
        { return Err(PurgeError::Conflict); }
        if self.expected_prior(&prepared.record)? != prepared.expected_prior.as_ref() {
            return Err(PurgeError::Conflict);
        }
        self.check_subject(&prepared.record)?;
        let mut record = copy(&prepared.record)?;
        record.publication_sequence = self.extension_sequence(&record)?;
        let output = copy(&record)?;
        let image = wire(&record)?;
        let digest = payload_identity(&image);
        self.resources(None, None, owned_size(&record)?, image.len().div_ceil(CHUNK_BYTES) + 1)?;
        self.subjects.try_reserve_exact(1).map_err(|_| PurgeError::AllocationFailure)?;
        prepared.consumed = true;
        self.publish_image(SUBJECT_TAG, [0; 16], 0, &image, host)?;
        self.subjects.push(record);
        prepared.committed_digest = Some(digest);
        Ok(output)
    }
    pub fn load_subject(&self, binding: &MemberBinding, host: &impl Host) -> Result<SubjectRecord, PurgeError> {
        self.ready(host)?;
        check_binding(binding)?;
        let record=self.current_subject(binding).ok_or(PurgeError::MissingInventory)?;
        if record.schema_version==2{self.validate_subject_custody(record)?;}
        copy(record)
    }
    pub fn load_subject_reference(&self, domain: [u8; 16], binding: &MemberBinding,
        revision: u64, sequence: u64, key: [u8; 32], host: &impl Host) -> Result<SubjectRecord, PurgeError>
    {
        self.ready(host)?;
        check_binding(binding)?;
        if domain != self.domain || revision == 0 || sequence == 0 { return Err(PurgeError::Conflict); }
        let record = self.subjects.iter().find(|s| &s.binding == binding
            && s.subject_revision == revision && s.publication_sequence == sequence)
            .ok_or(PurgeError::MissingInventory)?;
        if record.source.source_record_id != key || source_key(record)? != key {
            return Err(PurgeError::Conflict);
        }
        if record.schema_version==2{self.validate_subject_custody(record)?;}
        copy(record)
    }
    pub fn validate_subject_body(&self,record:&SubjectRecord,kind:u32,parent:&Option<MemberBinding>,custody:&CustodyReceipt,
        current:&[u8],observations:&[u8])->Result<(),PurgeError>{
        if self.recovery_required{return Err(PurgeError::RecoveryRequired);}
        if record.schema_version!=2||record.immutable_capture_version!=1{return Err(PurgeError::Unsupported);}
        if kind!=record.source_kind||parent!=&record.parent||custody!=&record.custody{return Err(PurgeError::Conflict);}
        if !self.subjects.iter().any(|retained|retained==record){return Err(PurgeError::Conflict);}
        self.validate_subject_custody(record)?;
        self.validate_intake_source(&record.binding,kind,current)?;
        source_codec::held_read(kind,current,observations)?;
        if source_codec::project(kind,current)?!=record.immutable_source_bytes{return Err(PurgeError::Conflict);}
        Ok(())
    }
    pub(super) fn recover_subject_extension(&mut self, kind: u32, sequence: u64,
        bytes: &[u8]) -> Result<(), PurgeError>
    {
        if bytes.len() > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
        match kind {
            IDS_TAG => {
                let r: IdReservation = unwire(bytes)?;
                if r.publication_sequence != sequence { return Err(PurgeError::CorruptJournal); }
                self.check_reservation(&r)?;
                self.resources(None, None, owned_size(&r)?, 0)?;
                append(&mut self.id_reservations, r)?;
            }
            SUBJECT_TAG => {
                let r: SubjectRecord = unwire(bytes)?;
                if r.publication_sequence != sequence { return Err(PurgeError::CorruptJournal); }
                self.check_subject(&r)?;
                self.resources(None, None, owned_size(&r)?, 0)?;
                append(&mut self.subjects, r)?;
            }
            _ => return Err(PurgeError::CorruptJournal),
        }
        Ok(())
    }
}

pub fn reservation_digest(r: &IdReservation) -> Result<[u8; 32], PurgeError> {
    // The canonical reservation is entirely fixed width: no allocation after
    // successful publication is necessary to return its receipt identity.
    let mut bytes = [0u8; 76];
    let mut pos = 0;
    for part in [r.schema_version.to_le_bytes().as_slice(), r.domain.as_slice(),
        r.publication_sequence.to_le_bytes().as_slice(), r.id_namespace.to_le_bytes().as_slice(),
        r.request.as_slice(), r.first.to_le_bytes().as_slice(), r.last.to_le_bytes().as_slice(),
        r.high_water.to_le_bytes().as_slice(), r.count.to_le_bytes().as_slice()]
    {
        bytes[pos..pos + part.len()].copy_from_slice(part); pos += part.len();
    }
    Ok(payload_identity(&bytes))
}
pub fn subject_digest(r: &SubjectRecord) -> Result<[u8; 32], PurgeError> {
    Ok(payload_identity(&wire(r)?))
}

#[cfg(test)]
pub(super) mod tests {
    use super::*;
    // Journal-unit host only. This does not claim actual daemon custody/factory.
    pub(in crate::purgejournal) struct MemoryHost { pub(in crate::purgejournal) frames: Vec<Vec<u8>>, pub(in crate::purgejournal) fail_at: Option<u64> }
    impl Host for MemoryHost {
        fn supported(&self) -> bool { true }
        fn journal_identity(&self) -> Result<[u8; 32], PurgeError> {
            let mut id = [7; 32]; id[..8].copy_from_slice(b"NZBPJID1"); Ok(id)
        }
        fn publish(&mut self, sequence: u64, frame: &[u8]) -> Result<PublicationAck, PurgeError> {
            if self.fail_at == Some(sequence) { return Err(PurgeError::Persistence); }
            self.frames.push(frame.to_vec());
            Ok(PublicationAck { sequence, frame: frame.to_vec(), file_synced: true, published: true, directory_synced: true })
        }
        fn execute(&mut self, _: &Call<'_>) -> Result<Ack, PurgeError> { Err(PurgeError::Unsupported) }
    }
    pub(in crate::purgejournal) fn host() -> MemoryHost { MemoryHost { frames: vec![], fail_at: None } }
    pub(in crate::purgejournal) fn capture() -> Vec<u8> {
        // Actual SaveNzbInfo64/SaveDupeExtras66 grammar, not opaque toy bodies.
        let body=b"42\n0\n\nfixture.nzb\n/queue/in\n/final\n\n\nfixture.nzb\nfixture\n\n0,0,0,0,0\n0,0,0,0,0,0,0,0,0\n0,0,0\n1,0,0\n1,1\n0,0,0,0\n0,0\n0,20,0,0,0,0\n0,0,0,0,0,0\n2,0,0\ndupe\n0,0,0\n0,0,0,0,0,0,0\n0\n0,0,0,0\n0\n0\n1\n6,0,0\n";
        let extras=b"0,0,0,0\n0\n";
        let mut b=b"PURGE-SOURCE-BYTES1".to_vec();
        for n in [1u32,1,64,body.len() as u32]{b.extend(n.to_le_bytes());}b.extend(body);
        b.extend(66u32.to_le_bytes());b.extend((extras.len()as u32).to_le_bytes());b.extend(extras);b
    }
    pub(in crate::purgejournal) fn template(registry: &Registry, r: &IdReservation) -> SubjectRecord {
        let binding = MemberBinding { collection_id: 42, file_id: None, incarnation: r.first, posting_source: format!("NZBINTAKE1:{}:{}", "01".repeat(16), r.first).into_bytes() };
        let request=registry.intake_captures.iter().find(|c|c.incarnation==r.first).unwrap().request;
        let association=registry.intake_associations.iter().find(|a|a.request==request).unwrap();
        let (source_id,custody)=registry.intake_subject_authority(association.publication_sequence,&binding,None).unwrap();
        SubjectRecord { schema_version: 0, domain: [0; 16], publication_sequence: 0,
            transition: 1, binding: binding.clone(), prior: None,
            source: SourceValidation { id: source_id, version: 1, validator_version: 1, source_record_id: [0; 32],
                source_bytes_digest: [0; 32], binding, parent_collection: None, custody_receipt_id: custody },
            custody: CustodyReceipt { id: custody, validator_version: 1, source_record_id: [0; 32], source_bytes_digest: [0; 32] },
            parent: None, reservation_request: r.request, reservation_sequence: r.publication_sequence,
            subject_revision: 0, source_kind: 1, original_source_byte_length: 0, original_source_bytes_digest: [0; 32], expected_prior_subject_revision: 0, expected_prior_publication_sequence: 0, original_source_bytes:Vec::new(),immutable_capture_version:0,immutable_source_bytes:Vec::new() }
    }
    // Unit-host source custody fixture only, never actual parser/daemon proof.
    pub(in crate::purgejournal) fn admit_fixture(r:&mut Registry,ids:&IdReservation,h:&mut MemoryHost){
        use super::super::intake::*;
        let mut request=[41;16];request[8..].copy_from_slice(&ids.first.to_le_bytes());
        let descriptor=Descriptor {device:1,inode:2,byte_length:6,mode:0o100600,owner:1,links:1,
            modified_seconds:1,modified_nanoseconds:0,changed_seconds:1,changed_nanoseconds:0};
        let captured=r.store_intake_capture(RawCapture {schema_version:1,domain:r.domain,publication_sequence:0,request,
            collection_id:42,reservation_request:ids.request,reservation_sequence:ids.publication_sequence,incarnation:ids.first,
            descriptor_identity:wire(&CapturedDescriptor {version:1,before:copy(&descriptor).unwrap(),after:descriptor}).unwrap(),
            parser_contract_version:1,raw_nzb_bytes:b"<nzb/>".to_vec()},h).unwrap();
        let mut file_request=[42;16];file_request[8..].copy_from_slice(&ids.first.to_le_bytes());
        let file=r.reserve_ids(1,file_request,1,h).unwrap();
        let mut declarations=vec![Declaration {kind:1,file_ordinal:1,ordinal:1,attributes:vec![],characters:vec![],
            disposition:1,effective_file:1,effective_article:0,replacement_ordinal:0}];
        let mut articles=Vec::new();
        for ordinal in 1..=2{let text=format!("article{ordinal}").into_bytes();
            articles.push(EffectiveArticle {declaration_ordinal:ordinal,part:ordinal as i32,bytes:10,message_id:[b"<".as_slice(),&text,b">".as_slice()].concat()});
            declarations.push(Declaration {kind:2,file_ordinal:1,ordinal,attributes:vec![],characters:text,disposition:1,
                effective_file:1,effective_article:ordinal,replacement_ordinal:0});}
        let a=r.store_intake_association(IntakeAssociation {schema_version:1,domain:r.domain,publication_sequence:0,request,
            capture_publication_sequence:captured.publication_sequence,capture_payload_identity:captured.payload_identity,parser_contract_version:1,
            files:vec![EffectiveFile {declaration_ordinal:1,file_id:6,incarnation:file.first,reservation_request:file.request,
                reservation_sequence:file.publication_sequence,subject:b"fixture".to_vec(),date:1,groups:vec![],articles}],declarations},h).unwrap();
        assert_eq!(r.intake_posting_source(&a).unwrap(),template(r,ids).binding.posting_source);
    }
    #[test]
    fn namespaces_replay_and_restart_are_independent_of_operation_generation() {
        let mut h = host(); let mut r = Registry::initialize_with_high_water([1; 16], 100, &mut h).unwrap();
        let a = r.reserve_ids(1, [1; 16], 2, &mut h).unwrap();
        let producer = r.reserve_ids(2, [1; 16], 1, &mut h).unwrap();
        assert_eq!((a.first, a.last, producer.first, r.high_water), (1, 2, 1, 100));
        let count = h.frames.len(); assert_eq!(r.reserve_ids(1, [1; 16], 2, &mut h).unwrap(), a);
        assert_eq!(h.frames.len(), count);
        assert_eq!(r.reserve_ids(1, [1; 16], 3, &mut h), Err(PurgeError::Conflict));
        let mut loaded = Registry::recover([1; 16], h.journal_identity().unwrap(), &h.frames).unwrap();
        assert_eq!(loaded.reserve_ids(1, [2; 16], 1, &mut h).unwrap().first, 3);
        assert_eq!(loaded.reserve_ids(2, [2; 16], 1, &mut h).unwrap().first, 2);
    }
    #[test]
    fn prepared_subject_owns_original_and_returns_authoritative_revision() {
        let mut h = host(); let mut r = Registry::initialize([1; 16], &mut h).unwrap();
        let ids = r.reserve_ids(1, [2; 16], 1, &mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let mut raw = capture();
        let mut prepared = r.prepare_subject(template(&r,&ids), &raw, &h).unwrap();
        raw.fill(0);
        let subject = r.store_prepared_subject(&mut prepared, &mut h).unwrap();
        assert_eq!(subject.subject_revision, 1);
        assert_eq!(subject.source.source_record_id, source_key(&subject).unwrap());
        assert_eq!(subject.binding.posting_source,template(&r,&ids).binding.posting_source);
        assert_eq!(subject.original_source_bytes_digest, payload_identity(&capture()));
        assert_eq!(r.store_prepared_subject(&mut prepared, &mut h), Err(PurgeError::Conflict));
        let recovered = Registry::recover([1; 16], h.journal_identity().unwrap(), &h.frames).unwrap();
        assert_eq!(recovered.load_subject(&subject.binding, &h).unwrap(), subject);
        let mut wrong = subject.binding.clone(); wrong.incarnation += 1;
        assert_eq!(recovered.load_subject(&wrong, &h), Err(PurgeError::MissingInventory));
    }
    fn update_template(prior: &SubjectRecord) -> SubjectRecord {
        let mut r = copy(prior).unwrap();
        r.transition = 4; r.prior = Some(prior.binding.clone());
        r.expected_prior_subject_revision = prior.subject_revision;
        r.expected_prior_publication_sequence = prior.publication_sequence;
        r.source.source_record_id = [0; 32]; r.source.source_bytes_digest = [0; 32];
        r.custody.source_record_id = [0; 32]; r.custody.source_bytes_digest = [0; 32];
        r.original_source_byte_length = 0;
        r
    }
    #[test]
    fn issued_collection_and_file_custody_binds_exact_association_and_parent(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let collection=template(&r,&ids);let a=r.intake_associations.last().unwrap();let f=&a.files[0];
        let binding=MemberBinding{collection_id:42,file_id:Some(f.file_id),incarnation:f.incarnation,posting_source:collection.binding.posting_source.clone()};
        for (b,parent) in [(&collection.binding,None),(&binding,Some(&collection.binding))]{
            let (id,reference)=r.intake_subject_authority(a.publication_sequence,b,parent).unwrap();
            assert_eq!(id,b.incarnation);assert_eq!(&reference[..16],&r.domain);
            assert_eq!(&reference[16..24],&a.publication_sequence.to_le_bytes());
            assert_eq!(&reference[24..],&b.incarnation.to_le_bytes());
        }
        assert!(r.intake_subject_authority(a.publication_sequence,&binding,None).is_err());
        let mut wrong_parent=collection.binding.clone();wrong_parent.incarnation=f.incarnation;
        assert!(r.intake_subject_authority(a.publication_sequence,&binding,Some(&wrong_parent)).is_err());
        let mut sibling=binding.clone();sibling.file_id=Some(f.file_id+1);
        assert!(r.intake_subject_authority(a.publication_sequence,&sibling,Some(&collection.binding)).is_err());
    }
    #[test]
    fn subject_prepare_rejects_forged_custody_without_publication(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let producer=r.reserve_ids(2,[9;16],1,&mut h).unwrap();
        let before=h.frames.len();
        for case in 0..8{
            let mut candidate=template(&r,&ids);
            match case{
                0=>candidate.custody.id=[3;32],
                1=>candidate.custody.id=[8;32],
                2=>candidate.custody.id[0]^=1,
                3=>candidate.custody.id[16..24].copy_from_slice(&u64::MAX.to_le_bytes()),
                4=>candidate.source.id+=1,
                5=>candidate.custody.id[24..].copy_from_slice(&u64::MAX.to_le_bytes()),
                6=>{candidate.reservation_request=producer.request;candidate.reservation_sequence=producer.publication_sequence;},
                7=>{candidate.binding.collection_id+=1;candidate.source.binding=candidate.binding.clone();},
                _=>unreachable!(),
            }
            if case<=3||case==5{candidate.source.custody_receipt_id=candidate.custody.id;}
            assert!(r.prepare_subject(candidate,&capture(),&h).is_err(),"case {case}");
            assert_eq!(h.frames.len(),before,"case {case}");
        }
    }
    #[test]
    fn prepared_store_rechecks_retained_raw_and_complete_map(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let mut prepared=r.prepare_subject(template(&r,&ids),&capture(),&h).unwrap();let before=h.frames.len();
        // Deliberate in-memory corruption injection, not a claimed crash path.
        let raw=r.intake_captures.pop().unwrap();
        assert!(r.store_prepared_subject(&mut prepared,&mut h).is_err());assert_eq!(h.frames.len(),before);
        r.intake_captures.push(raw);
        let declaration=r.intake_associations.last_mut().unwrap().declarations.pop().unwrap();
        assert!(r.store_prepared_subject(&mut prepared,&mut h).is_err());assert_eq!(h.frames.len(),before);
        r.intake_associations.last_mut().unwrap().declarations.push(declaration);
        assert!(r.store_prepared_subject(&mut prepared,&mut h).is_ok());
    }
    #[test]
    fn custody_replay_and_historical_subject_survive_unrelated_association_restart(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let input=template(&r,&ids);let reference=input.custody.id;
        let mut p=r.prepare_subject(input,&capture(),&h).unwrap();let original=r.store_prepared_subject(&mut p,&mut h).unwrap();
        let request=r.intake_associations[0].request;
        let mut replay=copy(&r.intake_associations[0]).unwrap();replay.publication_sequence=0;
        let other=r.reserve_ids(1,[7;16],1,&mut h).unwrap();admit_fixture(&mut r,&other,&mut h);
        let before=h.frames.len();let ack=r.store_intake_association(replay,&mut h).unwrap();assert_eq!(h.frames.len(),before);
        let recovered=Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames).unwrap();
        let loaded=recovered.load_intake_association(request,&h).unwrap();assert_eq!(loaded,ack);
        assert_eq!(recovered.intake_subject_authority(loaded.publication_sequence,&original.binding,None).unwrap().1,reference);
        assert_eq!(recovered.load_subject_reference(original.domain,&original.binding,original.subject_revision,original.publication_sequence,original.source.source_record_id,&h).unwrap(),original);
    }
    #[test]
    fn framed_schema2_forged_custody_rejects_staged_recovery(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let p=r.prepare_subject(template(&r,&ids),&capture(),&h).unwrap();let mut forged=copy(&p.record).unwrap();
        forged.custody.id=[3;32];forged.source.custody_receipt_id=[3;32];
        forged.source.source_record_id=source_key(&forged).unwrap();forged.custody.source_record_id=forged.source.source_record_id;
        forged.publication_sequence=r.extension_sequence(&forged).unwrap();
        // Real journal framing/checksums, deliberately bypassing normal store
        // validation to exercise the staged recovery validator itself.
        r.publish_image(SUBJECT_TAG,[0;16],0,&wire(&forged).unwrap(),&mut h).unwrap();
        assert!(Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames).is_err());
    }
    #[test]
    fn subject_reads_reject_forged_custody_even_with_recomputed_source_key(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let current=capture();let observations=current_observations(&current);
        let mut p=r.prepare_subject(template(&r,&ids),&current,&h).unwrap();let valid=r.store_prepared_subject(&mut p,&mut h).unwrap();
        r.validate_subject_body(&valid,valid.source_kind,&valid.parent,&valid.custody,&current,&observations).unwrap();
        let retained=r.subjects.last_mut().unwrap();retained.custody.id=[3;32];retained.source.custody_receipt_id=[3;32];
        retained.source.source_record_id=source_key(retained).unwrap();retained.custody.source_record_id=retained.source.source_record_id;
        let forged=copy(retained).unwrap();
        assert!(r.load_subject(&forged.binding,&h).is_err());
        assert!(r.load_subject_reference(forged.domain,&forged.binding,forged.subject_revision,forged.publication_sequence,forged.source.source_record_id,&h).is_err());
        assert!(r.validate_subject_body(&forged,forged.source_kind,&forged.parent,&forged.custody,&current,&observations).is_err());
    }
    #[test]
    fn update_compare_and_swap_retains_exact_old_reference_across_restart() {
        let mut h = host(); let mut r = Registry::initialize([1; 16], &mut h).unwrap();
        let ids = r.reserve_ids(1, [2; 16], 1, &mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let mut p = r.prepare_subject(template(&r,&ids), &capture(), &h).unwrap();
        let original = r.store_prepared_subject(&mut p, &mut h).unwrap();
        let mut first = r.prepare_subject(update_template(&original), &capture(), &h).unwrap();
        let mut stale = r.prepare_subject(update_template(&original), &capture(), &h).unwrap();
        let updated = r.store_prepared_subject(&mut first, &mut h).unwrap();
        assert_eq!(updated.subject_revision, 2);
        assert_eq!(updated.binding, original.binding);
        assert_ne!(updated.source.source_record_id, original.source.source_record_id);
        let before = h.frames.len();
        assert_eq!(r.store_prepared_subject(&mut stale, &mut h), Err(PurgeError::Conflict));
        assert_eq!(h.frames.len(), before);
        assert!(matches!(r.prepare_subject(update_template(&original), &capture(), &h), Err(PurgeError::Conflict)));
        // The journal update committed while the disk reference still names 1.
        let recovered = Registry::recover([1; 16], h.journal_identity().unwrap(), &h.frames).unwrap();
        assert_eq!(recovered.load_subject(&original.binding, &h).unwrap(), updated);
        assert_eq!(recovered.load_subject_reference(original.domain, &original.binding,
            original.subject_revision, original.publication_sequence, original.source.source_record_id, &h).unwrap(), original);
        for (domain, revision, sequence, key) in [
            ([2;16], original.subject_revision, original.publication_sequence, original.source.source_record_id),
            (original.domain, 99, original.publication_sequence, original.source.source_record_id),
            (original.domain, original.subject_revision, updated.publication_sequence, original.source.source_record_id),
            (original.domain, original.subject_revision, original.publication_sequence, updated.source.source_record_id),
        ] {
            assert!(recovered.load_subject_reference(domain, &original.binding, revision, sequence, key, &h).is_err());
        }
    }
    #[test]
    fn source_revision_overflow_and_rebind_stale_prior_reject_before_publication() {
        let mut h = host(); let mut r = Registry::initialize([1; 16], &mut h).unwrap();
        let ids = r.reserve_ids(1, [2; 16], 2, &mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let mut p = r.prepare_subject(template(&r,&ids), &capture(), &h).unwrap();
        let original = r.store_prepared_subject(&mut p, &mut h).unwrap();
        let mut second_ids=copy(&ids).unwrap();second_ids.first=ids.last;
        admit_fixture(&mut r,&second_ids,&mut h);
        let mut rebind = template(&r,&second_ids); rebind.transition = 3;
        rebind.binding.incarnation = ids.last; rebind.source.binding = rebind.binding.clone();
        rebind.prior = Some(original.binding.clone());
        rebind.expected_prior_subject_revision = original.subject_revision;
        rebind.expected_prior_publication_sequence = original.publication_sequence;
        let mut prepared_rebind = r.prepare_subject(rebind, &capture(), &h).unwrap();
        let mut update = r.prepare_subject(update_template(&original), &capture(), &h).unwrap();
        r.store_prepared_subject(&mut update, &mut h).unwrap();
        assert_eq!(r.store_prepared_subject(&mut prepared_rebind, &mut h), Err(PurgeError::Conflict));
        // Direct unit-state boundary injection only; no fabricated recovery proof.
        let last = r.subjects.last_mut().unwrap(); last.subject_revision = u64::MAX;
        let candidate = update_template(last); let before = h.frames.len();
        assert!(matches!(r.prepare_subject(candidate, &capture(), &h), Err(PurgeError::LimitExceeded)));
        assert_eq!(h.frames.len(), before);
    }
    #[test]
    fn reservation_partial_publication_retains_recovery_hold() {
        let mut h = host(); let mut r = Registry::initialize([1; 16], &mut h).unwrap();
        h.fail_at = Some(3); // reservation chunk persisted, commit publication fails
        assert_eq!(r.reserve_ids(1, [2; 16], 1, &mut h), Err(PurgeError::Persistence));
        assert!(r.requires_recovery());
        h.fail_at = None;
        assert_eq!(r.reserve_ids(1, [3; 16], 1, &mut h), Err(PurgeError::RecoveryRequired));
        assert!(matches!(Registry::recover([1; 16], h.journal_identity().unwrap(), &h.frames), Err(PurgeError::RecoveryRequired)));
    }
    #[test]
    fn capture_truncation_suffix_and_caller_hashes_reject() {
        let mut h = host(); let mut r = Registry::initialize([1; 16], &mut h).unwrap();
        let ids = r.reserve_ids(1, [2; 16], 1, &mut h).unwrap();
        admit_fixture(&mut r,&ids,&mut h);
        let raw = capture();
        for end in 0..raw.len() { assert!(r.prepare_subject(template(&r,&ids), &raw[..end], &h).is_err()); }
        let mut suffix = raw.clone(); suffix.push(0); assert!(r.prepare_subject(template(&r,&ids), &suffix, &h).is_err());
        let mut wrong = template(&r,&ids); wrong.source.source_record_id = [8; 32];
        assert!(r.prepare_subject(wrong, &raw, &h).is_err());
    }
    fn current_observations(bytes:&[u8])->Vec<u8>{
        let e=source_codec::Envelope::parse(1,bytes).unwrap();let second=e.second.unwrap();
        let size=(e.body.len()+second.len()+32)as u64;let mut b=Vec::new();
        for n in [1u32,1,1]{b.extend(n.to_le_bytes());}
        for n in [1u64,2]{b.extend(n.to_le_bytes());}b.extend(5u32.to_le_bytes());b.extend(b"queue");
        let mut stat=Vec::new();for n in [1u64,3,size,1]{stat.extend(n.to_le_bytes());}
        stat.extend(0o100600u32.to_le_bytes());stat.extend(1u32.to_le_bytes());
        for _ in 0..2{stat.extend(1i64.to_le_bytes());stat.extend(0u32.to_le_bytes());}
        b.extend(&stat);b.extend(&stat);b.extend(2u32.to_le_bytes());
        for n in [16u64,e.body.len()as u64,16+e.body.len()as u64,second.len()as u64]{b.extend(n.to_le_bytes());}b
    }
    fn parameter_capture(count:usize)->Vec<u8>{
        let original=capture();let envelope=source_codec::Envelope::parse(1,&original).unwrap();
        let tail=b"0,0,0,0\n0\n0\n1\n6,0,0\n";
        let at=envelope.body.windows(tail.len()).rposition(|w|w==tail).unwrap();
        let mut body=envelope.body[..at].to_vec();body.extend(format!("{count},0,0,0\n").bytes());
        for i in 0..count{body.extend(format!("key{i}=").bytes());body.extend(std::iter::repeat_n(b'x',60000));body.push(b'\n');}
        body.extend(b"0\n0\n1\n6,0,0\n");let extras=envelope.second.unwrap();
        let mut out=b"PURGE-SOURCE-BYTES1".to_vec();
        for n in [1u32,1,64,body.len()as u32]{out.extend(n.to_le_bytes());}out.extend(body);
        out.extend(66u32.to_le_bytes());out.extend((extras.len()as u32).to_le_bytes());out.extend(extras);out
    }
    #[test]
    fn combined_capture_projection_limit_precedes_large_owned_allocation(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let original=parameter_capture(600);let record=template(&r,&ids);let before=h.frames.len();
        let (result,allocations)=crate::allocation_probe::measure(||r.prepare_subject(record,&original,&h));
        assert!(matches!(result,Err(PurgeError::LimitExceeded)),"fixture must reach combined capacity rejection");
        assert_eq!(h.frames.len(),before);
        assert!(allocations.largest<1024*1024,"oversized prepare allocated snapshot before whole bound: {allocations:?}");
    }
    #[test]
    fn retained_prior_limit_precedes_update_capture_copy(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let old=parameter_capture(250);let mut prepared=r.prepare_subject(template(&r,&ids),&old,&h).unwrap();
        let prior=r.store_prepared_subject(&mut prepared,&mut h).unwrap();drop(prepared);drop(old);
        let next=parameter_capture(400);let update=update_template(&prior);let before=h.frames.len();
        let (result,allocations)=crate::allocation_probe::measure(||r.prepare_subject(update,&next,&h));
        assert!(matches!(result,Err(PurgeError::LimitExceeded)),"fixture must reach retained-prior capacity rejection");
        assert_eq!(h.frames.len(),before);
        assert!(allocations.largest<1024*1024,"prior budget checked after update snapshot allocation: {allocations:?}");
    }
    #[test]
    fn schema2_current_mutable_body_keeps_original_receipt_without_append(){
        let mut h=host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[2;16],1,&mut h).unwrap();admit_fixture(&mut r,&ids,&mut h);
        let original=capture();let mut prepared=r.prepare_subject(template(&r,&ids),&original,&h).unwrap();
        let retained=r.store_prepared_subject(&mut prepared,&mut h).unwrap();let frames=h.frames.len();
        let mut current=original.clone();let at=current.windows(b"0,20,0,0,0,0\n".len()).position(|v|v==b"0,20,0,0,0,0\n").unwrap();
        // Same-width success bytes update, no source change or journal append.
        current[at+7]=b'1';
        r.validate_subject_body(&retained,1,&None,&retained.custody,&current,&current_observations(&current)).unwrap();
        assert_eq!(h.frames.len(),frames);assert_eq!(retained.original_source_bytes,original);
        assert_eq!(r.load_subject_reference(retained.domain,&retained.binding,retained.subject_revision,
            retained.publication_sequence,retained.source.source_record_id,&h).unwrap(),retained);
        let mut changed=current.clone();let at=changed.windows(11).position(|v|v==b"fixture.nzb").unwrap();changed[at]=b'X';
        assert!(r.validate_subject_body(&retained,1,&None,&retained.custody,&changed,&current_observations(&changed)).is_err());
        let mut observations=current_observations(&current);let last=observations.len()-1;observations[last]=1;
        assert!(r.validate_subject_body(&retained,1,&None,&retained.custody,&current,&observations).is_err());
        let mut legacy=copy(&retained).unwrap();legacy.schema_version=1;
        assert_eq!(r.validate_subject_body(&legacy,1,&None,&legacy.custody,&current,&current_observations(&current)),Err(PurgeError::Unsupported));
    }


    fn six_reserved(r: &mut Registry, h: &mut MemoryHost, request: u8) -> IdReservation {
        let ids = r.reserve_ids(1, [request;16], 1, h).unwrap();
        admit_fixture(r, &ids, h); ids
    }
    fn six_commit(r: &mut Registry, h: &mut MemoryHost, ids: &IdReservation) -> SubjectRecord {
        let mut p = r.prepare_subject(template(r, ids), &capture(), h).unwrap();
        r.store_prepared_subject(&mut p, h).unwrap()
    }
    fn six_rebind(r: &Registry, ids: &IdReservation, prior: &SubjectRecord) -> SubjectRecord {
        let mut value = template(r, ids); value.transition = 3; value.prior = Some(prior.binding.clone());
        value.expected_prior_subject_revision = prior.subject_revision;
        value.expected_prior_publication_sequence = prior.publication_sequence; value
    }
    #[test]
    fn six_fresh_numeric_subject_reuse_rejects_at_prepare() {
        for transition in [1,2] {
            let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
            let first = six_reserved(&mut r, &mut h, 81); six_commit(&mut r, &mut h, &first);
            let second = six_reserved(&mut r, &mut h, 82); let mut value = template(&r, &second); value.transition = transition;
            let frames = h.frames.clone(); let seq = r.sequence; let retained = wire(&r.subjects).unwrap();
            assert_eq!(r.prepare_subject(value, &capture(), &h).map(|_| ()), Err(PurgeError::Conflict), "PR108_SIX_FRESH_NUMERIC_PREPARE transition={transition}");
            assert_eq!(h.frames, frames); assert_eq!(r.sequence, seq); assert_eq!(wire(&r.subjects).unwrap(), retained);
        }
    }
    #[test]
    fn six_two_fresh_prepares_recheck_numeric_subject_at_store() {
        for transition in [1,2] {
            let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
            let first = six_reserved(&mut r, &mut h, 81); let second = six_reserved(&mut r, &mut h, 82);
            let mut p = r.prepare_subject(template(&r, &first), &capture(), &h).unwrap();
            let mut value = template(&r, &second); value.transition = transition;
            let mut q = r.prepare_subject(value, &capture(), &h).unwrap();
            r.store_prepared_subject(&mut p, &mut h).unwrap();
            let frames = h.frames.clone(); let seq = r.sequence; let retained = wire(&r.subjects).unwrap();
            assert_eq!(r.store_prepared_subject(&mut q, &mut h), Err(PurgeError::Conflict), "PR108_SIX_FRESH_NUMERIC_STORE transition={transition}");
            assert!(!q.consumed); assert_eq!(h.frames, frames); assert_eq!(r.sequence, seq); assert_eq!(wire(&r.subjects).unwrap(), retained);
        }
    }
    #[test]
    fn six_duplicate_numeric_subject_recovery_rejects() {
        for transition in [1,2] {
            let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
            let first = six_reserved(&mut r, &mut h, 81); let second = six_reserved(&mut r, &mut h, 82);
            let mut value = template(&r, &second); value.transition = transition;
            let q = r.prepare_subject(value, &capture(), &h).unwrap();
            six_commit(&mut r, &mut h, &first);
            let mut record = q.record;
            record.publication_sequence = r.extension_sequence(&record).unwrap();
            r.publish_image(SUBJECT_TAG, [0;16], 0, &wire(&record).unwrap(), &mut h).unwrap();
            assert!(Registry::recover([1;16], h.journal_identity().unwrap(), &h.frames).is_err(), "PR108_SIX_NUMERIC_REPLAY transition={transition}");
        }
    }
    #[test]
    fn six_rebind_stale_numeric_predecessor_rejects() {
        let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
        let first = six_reserved(&mut r, &mut h, 81); let old = six_commit(&mut r, &mut h, &first);
        let second = six_reserved(&mut r, &mut h, 82);
        let mut p = r.prepare_subject(six_rebind(&r, &second, &old), &capture(), &h).unwrap();
        let current = r.store_prepared_subject(&mut p, &mut h).unwrap();
        assert_eq!(r.load_subject_reference(old.domain, &old.binding, old.subject_revision, old.publication_sequence, old.source.source_record_id, &h).unwrap(), old);
        let third = six_reserved(&mut r, &mut h, 83); let frames = h.frames.clone(); let seq = r.sequence;
        assert_eq!(r.prepare_subject(six_rebind(&r, &third, &old), &capture(), &h).map(|_| ()), Err(PurgeError::Conflict), "PR108_SIX_STALE_REBIND");
        assert_eq!(h.frames, frames); assert_eq!(r.sequence, seq);
        let recovered = Registry::recover([1;16], h.journal_identity().unwrap(), &h.frames).unwrap();
        assert_eq!(recovered.load_subject_reference(current.domain, &current.binding, current.subject_revision, current.publication_sequence, current.source.source_record_id, &h).unwrap(), current);
    }
    #[test]
    fn six_rebind_two_prepares_require_current_numeric_cas() {
        let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
        let first = six_reserved(&mut r, &mut h, 81); let old = six_commit(&mut r, &mut h, &first);
        let second = six_reserved(&mut r, &mut h, 82); let third = six_reserved(&mut r, &mut h, 83);
        let mut p = r.prepare_subject(six_rebind(&r, &second, &old), &capture(), &h).unwrap();
        let mut q = r.prepare_subject(six_rebind(&r, &third, &old), &capture(), &h).unwrap();
        r.store_prepared_subject(&mut p, &mut h).unwrap();
        let frames = h.frames.clone(); let seq = r.sequence;
        assert_eq!(r.store_prepared_subject(&mut q, &mut h), Err(PurgeError::Conflict), "PR108_SIX_REBIND_CAS_STORE");
        assert!(!q.consumed); assert_eq!(h.frames, frames); assert_eq!(r.sequence, seq);
    }
    #[test]
    fn six_rebind_cannot_change_numeric_key_using_real_file_authority() {
        let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
        let ids = six_reserved(&mut r, &mut h, 81); let collection = six_commit(&mut r, &mut h, &ids);
        let association = r.intake_associations.last().unwrap(); let effective = &association.files[0];
        let binding = MemberBinding { collection_id:collection.binding.collection_id, file_id:Some(effective.file_id),
            incarnation:effective.incarnation, posting_source:collection.binding.posting_source.clone() };
        let (source_id, custody) = r.intake_subject_authority(association.publication_sequence, &binding, Some(&collection.binding)).unwrap();
        let mut value = six_rebind(&r, &ids, &collection);
        value.binding = binding.clone(); value.parent = Some(collection.binding.clone());
        value.source.id = source_id; value.source.binding = binding; value.source.parent_collection = Some(collection.binding.clone());
        value.source.custody_receipt_id = custody; value.custody.id = custody;
        value.reservation_request = effective.reservation_request; value.reservation_sequence = effective.reservation_sequence; value.source_kind = 2;
        let body = b"fixture\nfile\n\n\n0,1\n0,20\n0,0\n0\n2,0\n0\n2\n1,10\n<article1>\n2,10\n<article2>\n";
        let mut original = b"PURGE-SOURCE-BYTES1".to_vec();
        for n in [1u32,2,7,body.len() as u32] { original.extend(n.to_le_bytes()); } original.extend(body); original.push(0);
        let frames = h.frames.clone(); let seq = r.sequence;
        assert_eq!(r.prepare_subject(value, &original, &h).map(|_| ()), Err(PurgeError::Conflict), "PR108_SIX_REBIND_NUMERIC_KEY");
        assert_eq!(h.frames, frames); assert_eq!(r.sequence, seq);
    }
    #[test]
    fn six_same_key_rebind_and_exact_current_update_remain_recoverable() {
        let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
        let first = six_reserved(&mut r, &mut h, 81); let old = six_commit(&mut r, &mut h, &first);
        let second = six_reserved(&mut r, &mut h, 82);
        let mut p = r.prepare_subject(six_rebind(&r, &second, &old), &capture(), &h).unwrap();
        let rebound = r.store_prepared_subject(&mut p, &mut h).unwrap();
        let mut p = r.prepare_subject(update_template(&rebound), &capture(), &h).unwrap();
        let updated = r.store_prepared_subject(&mut p, &mut h).unwrap();
        assert_eq!(updated.subject_revision, 2); assert_eq!(updated.binding, rebound.binding);
        let recovered = Registry::recover([1;16], h.journal_identity().unwrap(), &h.frames).unwrap();
        for record in [&old, &rebound, &updated] {
            assert_eq!(recovered.load_subject_reference(record.domain, &record.binding, record.subject_revision, record.publication_sequence, record.source.source_record_id, &h).unwrap(), *record);
        }
    }
    #[test]
    fn six_stale_rebind_journal_recovery_rejects() {
        let mut h = host(); let mut r = Registry::initialize([1;16], &mut h).unwrap();
        let first = six_reserved(&mut r, &mut h, 81); let old = six_commit(&mut r, &mut h, &first);
        let second = six_reserved(&mut r, &mut h, 82); let third = six_reserved(&mut r, &mut h, 83);
        let mut p = r.prepare_subject(six_rebind(&r, &second, &old), &capture(), &h).unwrap();
        let q = r.prepare_subject(six_rebind(&r, &third, &old), &capture(), &h).unwrap();
        r.store_prepared_subject(&mut p, &mut h).unwrap();
        let mut record = q.record; record.publication_sequence = r.extension_sequence(&record).unwrap();
        r.publish_image(SUBJECT_TAG, [0;16], 0, &wire(&record).unwrap(), &mut h).unwrap();
        assert!(Registry::recover([1;16], h.journal_identity().unwrap(), &h.frames).is_err(), "PR108_SIX_STALE_REBIND_REPLAY");
    }
    fn held_admit_group_fixture(r:&mut Registry,ids:&IdReservation,h:&mut MemoryHost){
        use super::super::intake::*;
        let mut request=[41;16];request[8..].copy_from_slice(&ids.first.to_le_bytes());
        let descriptor=Descriptor {device:1,inode:2,byte_length:6,mode:0o100600,owner:1,links:1,
            modified_seconds:1,modified_nanoseconds:0,changed_seconds:1,changed_nanoseconds:0};
        let captured=r.store_intake_capture(RawCapture {schema_version:1,domain:r.domain,publication_sequence:0,request,
            collection_id:42,reservation_request:ids.request,reservation_sequence:ids.publication_sequence,incarnation:ids.first,
            descriptor_identity:wire(&CapturedDescriptor {version:1,before:copy(&descriptor).unwrap(),after:descriptor}).unwrap(),
            parser_contract_version:1,raw_nzb_bytes:b"<nzb/>".to_vec()},h).unwrap();
        let mut file_request=[42;16];file_request[8..].copy_from_slice(&ids.first.to_le_bytes());
        let file=r.reserve_ids(1,file_request,1,h).unwrap();
        let mut declarations=vec![Declaration {kind:1,file_ordinal:1,ordinal:1,attributes:vec![],characters:vec![],
            disposition:1,effective_file:1,effective_article:0,replacement_ordinal:0}];
        let mut articles=Vec::new();
        for ordinal in 1..=2{let text=format!("article{ordinal}").into_bytes();
            articles.push(EffectiveArticle {declaration_ordinal:ordinal,part:ordinal as i32,bytes:10,message_id:[b"<".as_slice(),&text,b">".as_slice()].concat()});
            declarations.push(Declaration {kind:2,file_ordinal:1,ordinal,attributes:vec![],characters:text,disposition:1,
                effective_file:1,effective_article:ordinal,replacement_ordinal:0});}
        declarations.push(Declaration {kind:3,file_ordinal:1,ordinal:1,attributes:vec![],characters:b"alt.valid".to_vec(),disposition:1,effective_file:1,effective_article:1,replacement_ordinal:0});
        let a=r.store_intake_association(IntakeAssociation {schema_version:1,domain:r.domain,publication_sequence:0,request,
            capture_publication_sequence:captured.publication_sequence,capture_payload_identity:captured.payload_identity,parser_contract_version:1,
            files:vec![EffectiveFile {declaration_ordinal:1,file_id:6,incarnation:file.first,reservation_request:file.request,
                reservation_sequence:file.publication_sequence,subject:b"fixture".to_vec(),date:1,groups:vec![Group {bytes:b"alt.valid".to_vec()}],articles}],declarations},h).unwrap();
        assert_eq!(r.intake_posting_source(&a).unwrap(),template(r,ids).binding.posting_source);
    }

// Additive held constructor controls, frozen against b01 before this implementation.
// Historical controls are re-bound to the current real issuer; all remain UNRUN here.
use super::super::runtime_core::{ExactReference, RecoveryPrepareRequest, ProducerReservationKey, DependencyRequest, DependencyRole, InstallMode};
struct HeldIssuedFixture {
    pub registry: Registry,
    pub host: MemoryHost,
    pub producers: IdReservation,
    pub collection: SubjectRecord,
    pub file: SubjectRecord,
}

fn held_issued_fixture() -> HeldIssuedFixture { held_issued_fixture_variant(false) }
fn held_issued_fixture_variant(grouped:bool) -> HeldIssuedFixture {
    let mut host = host();
    let mut registry = Registry::initialize([1; 16], &mut host).unwrap();
    let subjects = registry.reserve_ids(1, [2; 16], 1, &mut host).unwrap();
    let producers = registry.reserve_ids(2, [3; 16], 2, &mut host).unwrap();
    if grouped {held_admit_group_fixture(&mut registry,&subjects,&mut host);} else {admit_fixture(&mut registry, &subjects, &mut host);}
    let mut prepared = registry.prepare_subject(template(&registry, &subjects), &capture(), &host).unwrap();
    let collection = registry.store_prepared_subject(&mut prepared, &mut host).unwrap();

    // This file Subject commit is NEW test Source. The reviewed helper only
    // committed the collection; never relabel its capture as a file body.
    let association = registry.intake_associations.last().unwrap();
    let effective = &association.files[0];
    let binding = crate::dupepurge::MemberBinding {
        collection_id: collection.binding.collection_id,
        file_id: Some(effective.file_id), incarnation: effective.incarnation,
        posting_source: collection.binding.posting_source.clone(),
    };
    let (source_id, custody) = registry.intake_subject_authority(
        association.publication_sequence, &binding, Some(&collection.binding)).unwrap();
    let reservation_request = effective.reservation_request;
    let reservation_sequence = effective.reservation_sequence;
    let mut file_template = template(&registry, &subjects);
    file_template.binding = binding.clone();
    file_template.parent = Some(collection.binding.clone());
    file_template.source.id = source_id;
    file_template.source.binding = binding;
    file_template.source.parent_collection = Some(collection.binding.clone());
    file_template.source.custody_receipt_id = custody;
    file_template.custody.id = custody;
    file_template.reservation_request = reservation_request;
    file_template.reservation_sequence = reservation_sequence;
    file_template.source_kind = 2;
    // Exact SaveFileInfo7 body for the actual committed intake association:
    // subject=fixture/date1/groups empty/two10-byte articles from the real map.
    let body = b"fixture\nfile\n\n\n0,1\n0,20\n0,0\n0\n2,0\n0\n2\n1,10\n<article1>\n2,10\n<article2>\n";
    let grouped_body=b"fixture\nfile\n\n\n0,1\n0,20\n0,0\n0\n2,0\n1\nalt.valid\n2\n1,10\n<article1>\n2,10\n<article2>\n";
    let body:&[u8]=if grouped {grouped_body} else {body};
    let mut file_capture = b"PURGE-SOURCE-BYTES1".to_vec();
    for n in [1u32, 2, 7, body.len() as u32] { file_capture.extend(n.to_le_bytes()); }
    file_capture.extend(body); file_capture.push(0); // no progress body
    let mut prepared = registry.prepare_subject(file_template, &file_capture, &host).unwrap();
    let file = registry.store_prepared_subject(&mut prepared, &mut host).unwrap();
    HeldIssuedFixture { registry, host, producers, collection, file }
}

fn held_state() -> Vec<u8> {
    b"0,0\n0,20,0,0,0,0\nfile\n\n\n0\n2\n2,0,0\n1,0,0\n2\n1,0,0,3,0\n0,0,0,4,1\n#decoded 0,20\n".to_vec()
}
fn held_envelope(f: &HeldIssuedFixture, state: &[u8]) -> Vec<u8> {
    let mut out=f.file.original_source_bytes.clone();assert_eq!(out.pop(),Some(0));out.push(1);
    out.extend(7u32.to_le_bytes());out.push(0);out.extend((state.len() as u32).to_le_bytes());out.extend(state);out
}
fn held_observations(raw: &[u8]) -> Vec<u8> {
    let e=source_codec::Envelope::parse(2,raw).unwrap();let mut out=Vec::new();
    out.extend(1u32.to_le_bytes());out.extend(2u32.to_le_bytes());
    for (role,body) in [(2u32,e.body),(3,e.second.unwrap())] {
        out.extend(role.to_le_bytes());out.extend(1u64.to_le_bytes());out.extend(2u64.to_le_bytes());
        out.extend(1u32.to_le_bytes());out.push(b'x');
        let mut metadata=Vec::new();for n in [1u64,u64::from(role),body.len() as u64,1]{metadata.extend(n.to_le_bytes());}
        metadata.extend(0o100600u32.to_le_bytes());metadata.extend(1u32.to_le_bytes());
        for _ in 0..2{metadata.extend(1i64.to_le_bytes());metadata.extend(0u32.to_le_bytes());}
        assert_eq!(metadata.len(),64);out.extend(&metadata);out.extend(&metadata);
        out.extend(1u32.to_le_bytes());out.extend(0u64.to_le_bytes());out.extend((body.len()as u64).to_le_bytes());
    }out
}
fn held_input(f: &HeldIssuedFixture) -> HeldRecoveryInput {
    let target=ExactReference::from_record(&f.file);let parent=ExactReference::from_record(&f.collection);
    let envelope=held_envelope(f,&held_state());let observations=held_observations(&envelope);
    HeldRecoveryInput { request:RecoveryPrepareRequest {
        producer:ProducerReservationKey{request:f.producers.request,publication_sequence:f.producers.publication_sequence,id:f.producers.first},
        owner_kind:0x46420001,work_kind:0x20005,mode:InstallMode::ArticlesAndProgress,schema:1,parent_ticket:None,
        target:target.clone(),dependencies:vec![DependencyRequest{reference:target,role:DependencyRole::InstallTarget,current_preimage:Some(b"opaque-current-live-not-desired".to_vec())},
        DependencyRequest{reference:parent,role:DependencyRole::ImmutableParent,current_preimage:None}],desired_writes:Vec::new()},
        envelope,observations,server_mapping:vec![ServerIdPair{persisted_state_id:2,runtime_server_id:20},ServerIdPair{persisted_state_id:1,runtime_server_id:10}] }
}
fn held_input_fingerprint(i:&HeldRecoveryInput)->(String,Vec<usize>) {
    let mut caps=vec![i.envelope.capacity(),i.observations.capacity(),i.server_mapping.capacity(),i.request.dependencies.capacity(),i.request.desired_writes.capacity(),i.request.target.binding.posting_source.capacity()];
    if let Some(p)=&i.request.target.parent{caps.push(p.posting_source.capacity());}
    for d in &i.request.dependencies{caps.push(d.reference.binding.posting_source.capacity());if let Some(p)=&d.reference.parent{caps.push(p.posting_source.capacity());}if let Some(p)=&d.current_preimage{caps.push(p.capacity());}}
    (format!("{i:?}"),caps)
}
#[test]
fn held_output_moves_input_without_copy_and_preserves_actual_progress() {
    let f=held_issued_fixture();let input=held_input(&f);let pointers=(input.envelope.as_ptr(),input.envelope.capacity(),input.observations.as_ptr(),input.server_mapping.as_ptr());
    let mut input=Some(input);let before=f.host.frames.len();let result=f.registry.validate_held_recovery_input(&mut input,&f.host).unwrap();
    assert!(input.is_none());assert_eq!(result.envelope().as_ptr(),pointers.0);assert_eq!(result.input.envelope.capacity(),pointers.1);
    assert_eq!(result.observations().as_ptr(),pointers.2);assert_eq!(result.server_mapping().as_ptr(),pointers.3);
    let view=result.view();assert_eq!(view.subject,b"fixture");assert_eq!(view.article_count,2);assert_eq!(view.progress.unwrap().completed_articles,1);
    assert_eq!(result.article(0).unwrap().progress.unwrap().status,1);assert!(result.article(1).unwrap().progress.unwrap().staged_fallback);
    assert_eq!(result.persisted_server_stat(0).unwrap().persisted_state_id,2);assert_eq!(result.persisted_server_stat(1).unwrap().persisted_state_id,1);
    assert_eq!(result.request().dependencies[0].current_preimage.as_deref(),Some(b"opaque-current-live-not-desired".as_slice()));
    assert_eq!(f.host.frames.len(),before);assert!(!f.registry.runtime_observation().coverage_known);
    assert!(result.article(2).is_none());assert!(result.group(0).is_none());assert!(result.persisted_server_stat(2).is_none());
}
#[test]
fn held_output_equal_projection_does_not_authorize_caller_desired_bytes() {
    let f=held_issued_fixture();let mut input=held_input(&f);input.request.desired_writes=b"caller-selected".to_vec();let before=held_input_fingerprint(&input);let mut input=Some(input);
    assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);
    let mut input=held_input(&f);input.request.desired_writes=Vec::with_capacity(1);let mut input=Some(input);assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());
}
#[test]
fn held_output_disk_empty_nullable_and_non_utf8_preserved() {
    let f=held_issued_fixture();let mut input=Some(held_input(&f));let result=f.registry.validate_held_recovery_input(&mut input,&f.host).unwrap();
    let progress=result.view().progress.unwrap();assert!(progress.hash16k.is_none());assert!(progress.par_set_id.is_none());
    let mut input=held_input(&f);let state=held_state();let pos=state.windows(7).position(|v|v==b"file\n\n\n").unwrap()+5;
    let mut altered=state[..pos].to_vec();altered.extend([0xff,0xfe]);altered.extend(&state[pos..]);input.envelope=held_envelope(&f,&altered);input.observations=held_observations(&input.envelope);
    let mut input=Some(input);let result=f.registry.validate_held_recovery_input(&mut input,&f.host).unwrap();assert_eq!(result.view().progress.unwrap().hash16k,Some([0xff,0xfe].as_slice()));
}
#[test]
fn held_output_every_exact_reference_dimension_rejects_without_consuming() {
    let f=held_issued_fixture();for case in 0..8 {let mut input=held_input(&f);match case {
        0=>input.request.target.domain[0]^=1,1=>input.request.target.binding.incarnation+=1,
        2=>input.request.target.binding.posting_source.push(b'x'),3=>input.request.target.subject_revision+=1,
        4=>input.request.target.publication_sequence+=1,5=>input.request.target.source_record_id[0]^=1,
        6=>input.request.target.parent.as_mut().unwrap().incarnation+=1,_=>input.request.dependencies[1].reference.publication_sequence+=1,
    }let before=held_input_fingerprint(&input);let mut input=Some(input);assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err(),"case{case}");assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);}
}
#[test]
fn held_output_missing_map_raw_and_pending_recovery_reject() {
    for case in 0..3 {let mut f=held_issued_fixture();let mut input=Some(held_input(&f));match case{0=>f.registry.intake_associations.clear(),1=>f.registry.intake_captures.clear(),_=>f.registry.recovery_required=true};assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());assert!(input.is_some());}
}
#[test]
fn held_output_descriptor_replacement_and_truncated_counts_reject_without_allocating() {
    let f=held_issued_fixture();let mut input=held_input(&f);input.observations[40]^=1;let mut input=Some(input);assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());assert!(input.is_some());
    for count in [1_000_000,1_000_001,10_000_000] {let mut input=held_input(&f);let state=format!("0,0\n0,20,0,0,0,0\nfile\n\n\n0\n{count}\n");input.envelope=held_envelope(&f,state.as_bytes());input.observations=held_observations(&input.envelope);let mut input=Some(input);
        let (result,allocations)=crate::allocation_probe::measure(||f.registry.validate_held_recovery_input(&mut input,&f.host));assert!(result.is_err());assert_eq!(allocations.calls,0,"{count}: {allocations:?}");assert!(input.is_some());}
}
#[test]
fn held_output_empty_oversized_capacity_rejects_before_any_allocation() {
    let f=held_issued_fixture();let mut input=held_input(&f);input.observations.reserve_exact(MAX_PAYLOAD);let before=held_input_fingerprint(&input);let mut input=Some(input);
    let (result,allocations)=crate::allocation_probe::measure(||f.registry.validate_held_recovery_input(&mut input,&f.host));assert!(matches!(result,Err(PurgeError::LimitExceeded)));assert_eq!(allocations.calls,0);assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);
}
#[test]
fn held_output_retained_capacities_and_resolver_scratch_preflight() {
    let mut f=held_issued_fixture();let mut input=Some(held_input(&f));f.registry.intake_captures[0].raw_nzb_bytes.reserve_exact(MAX_PAYLOAD);
    let (result,allocations)=crate::allocation_probe::measure(||f.registry.validate_held_recovery_input(&mut input,&f.host));assert!(matches!(result,Err(PurgeError::LimitExceeded)));assert_eq!(allocations.calls,0);assert!(input.is_some());
}
#[test]
fn held_output_mapping_is_owned_ordered_external_data_not_admission() {
    let f=held_issued_fixture();let mut input=Some(held_input(&f));let result=f.registry.validate_held_recovery_input(&mut input,&f.host).unwrap();assert_eq!(result.server_mapping()[0].runtime_server_id,20);assert_eq!(result.server_mapping()[1].runtime_server_id,10);
    let mut replacement=held_input(&f);replacement.server_mapping.reverse();replacement.request.dependencies[0].current_preimage=Some(Vec::new());
    assert_eq!(result.server_mapping()[0].persisted_state_id,2);assert_eq!(result.request().dependencies[0].current_preimage.as_deref(),Some(b"opaque-current-live-not-desired".as_slice()));assert!(!f.registry.runtime_observation().coverage_known);
}
#[test]
fn held_output_same_reference_new_mutable_body_owns_distinct_desired_state() {
    let f=held_issued_fixture();let mut first=Some(held_input(&f));let a=f.registry.validate_held_recovery_input(&mut first,&f.host).unwrap();
    let mut next=held_input(&f);let state=held_state();let pos=state.windows(10).position(|v|v==b"1,0,0,3,0\n").unwrap();let mut changed=state.clone();changed[pos]=b'2';
    next.envelope=held_envelope(&f,&changed);next.observations=held_observations(&next.envelope);let mut next=Some(next);let b=f.registry.validate_held_recovery_input(&mut next,&f.host).unwrap();assert_eq!(a.target(),b.target());assert_eq!(a.article(0).unwrap().progress.unwrap().status,1);assert_eq!(b.article(0).unwrap().progress.unwrap().status,2);
}
#[test]
fn held_output_duplicate_persisted_stats_still_reject_after_dry_sizing() {
    let f=held_issued_fixture();let mut input=held_input(&f);let state=held_state();let pos=state.windows(6).position(|v|v==b"1,0,0\n").unwrap();let mut changed=state;changed[pos]=b'2';input.envelope=held_envelope(&f,&changed);input.observations=held_observations(&input.envelope);let mut input=Some(input);assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());assert!(input.is_some());
}
#[test]
fn held_output_no_option_wrong_mode_and_schema_reject_without_side_effects() {
    let f=held_issued_fixture();let mut none=None;assert!(matches!(f.registry.validate_held_recovery_input(&mut none,&f.host),Err(PurgeError::InvalidInput)));
    for case in 0..3{let mut i=held_input(&f);match case{0=>i.request.mode=InstallMode::ArticlesOnly,1=>i.request.schema=2,_=>i.request.dependencies[1].current_preimage=Some(Vec::new())};let mut i=Some(i);assert!(f.registry.validate_held_recovery_input(&mut i,&f.host).is_err());assert!(i.is_some());}
}

#[test]
fn held_output_actually_empty_preimage_capacity_rejects_before_allocation() {
    let f=held_issued_fixture();let mut input=held_input(&f);
    input.request.dependencies[0].current_preimage=Some(Vec::with_capacity(MAX_PAYLOAD));
    assert_eq!(input.request.dependencies[0].current_preimage.as_ref().unwrap().len(),0);
    let before=held_input_fingerprint(&input);let mut input=Some(input);
    let (result,allocations)=crate::allocation_probe::measure(||f.registry.validate_held_recovery_input(&mut input,&f.host));
    assert!(matches!(result,Err(PurgeError::LimitExceeded)));assert_eq!(allocations.calls,0);
    assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);
}

#[test]
fn held_output_consistently_forged_references_reach_authoritative_lookup() {
    let f=held_issued_fixture();for case in 0..7 {let mut input=held_input(&f);match case {
        0=>input.request.target.domain[0]^=1,1=>input.request.target.binding.incarnation+=1,
        2=>input.request.target.binding.posting_source.push(b'x'),3=>input.request.target.subject_revision+=1,
        4=>input.request.target.publication_sequence+=1,5=>input.request.target.source_record_id[0]^=1,
        _=>{input.request.target.parent.as_mut().unwrap().incarnation+=1;input.request.dependencies[1].reference.binding.incarnation+=1;},
    }input.request.dependencies[0].reference=input.request.target.clone();
    assert_eq!(input.request.target,input.request.dependencies[0].reference);
    assert_eq!(input.request.target.parent.as_ref(),Some(&input.request.dependencies[1].reference.binding));
    let before=held_input_fingerprint(&input);let mut input=Some(input);
    assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err(),"consistent case{case}");
    assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);}
}

// Retained historical field-map controls: tests-first for this b01 additive tranche.
// Historical chronology is preserved in provenance, not relabeled as prior RED.
#[test]
fn held_output_distinct_values_cover_every_summary_progress_article_and_stat_field() {
    let mut f=held_issued_fixture();
    let summary=b"fixture\nrenamed\noriginal-name\noutput.bin\n1,1\n0,37\n0,17\n1\n3,1\n0\n2\n1,10\n<article1>\n2,10\n<article2>\n";
    let mut original=b"PURGE-SOURCE-BYTES1".to_vec();for n in [1u32,2,7,summary.len()as u32]{original.extend(n.to_le_bytes());}original.extend(summary);original.push(0);
    let mut prepared=f.registry.prepare_subject(update_template(&f.file),&original,&f.host).unwrap();f.file=f.registry.store_prepared_subject(&mut prepared,&mut f.host).unwrap();
    let state=b"1,1\n0,3,0,7,0,10\nrenamed\nHASH16\nPARSET\n1\n2\n2,4,5\n1,6,7\n2\n2,5,7,123,0\n3,17,9,456,0\n#decoded 0,1234\n";
    let mut input=held_input(&f);input.envelope=held_envelope(&f,state);
    let completed_at=19+16+summary.len()+1+4;input.envelope[completed_at]=1;
    input.observations=held_observations(&input.envelope);
    let mut input=Some(input);let value=f.registry.validate_held_recovery_input(&mut input,&f.host).unwrap();let v=value.view();
    assert_eq!(v.target,&ExactReference::from_record(&f.file));assert_eq!(v.parent,&ExactReference::from_record(&f.collection));
    assert_eq!(v.source,&f.file.source);assert_eq!(v.custody,&f.file.custody);assert_eq!(v.parent_source,&f.collection.source);assert_eq!(v.parent_custody,&f.collection.custody);
    assert_eq!(v.subject,b"fixture");assert_eq!(v.filename,b"renamed");assert_eq!(v.original_name_disk,b"original-name");assert_eq!(v.output_filename,b"output.bin");
    assert!(v.filename_confirmed);assert_eq!(v.time,1);assert_eq!(v.size,37);assert_eq!(v.missed_size,17);assert!(v.par_file);assert_eq!(v.total_articles,3);assert_eq!(v.missed_articles,1);
    assert_eq!(v.group_count,0);assert_eq!(v.article_count,2);assert_eq!(v.persisted_server_stat_count,2);
    let p=v.progress.unwrap();assert!(p.completed_selection);assert_eq!(p.success_articles,1);assert_eq!(p.failed_articles,1);assert_eq!(p.remaining_size,3);assert_eq!(p.success_size,7);assert_eq!(p.failed_size,10);assert_eq!(p.completed_articles,2);assert_eq!(p.decoded_file_size,1234);assert_eq!(p.hash16k,Some(b"HASH16".as_slice()));assert_eq!(p.par_set_id,Some(b"PARSET".as_slice()));
    for (index,part,id,status,offset,size,crc) in [(0,1,b"<article1>".as_slice(),2,5,7,123),(1,2,b"<article2>".as_slice(),3,17,9,456)]{
        let a=value.article(index).unwrap();assert_eq!(a.part_number,part);assert_eq!(a.advertised_size,10);assert_eq!(a.message_id,id);
        let p=a.progress.unwrap();assert_eq!(p.status,status);assert_eq!(p.segment_offset,offset);assert_eq!(p.segment_size,size);assert_eq!(p.crc,crc);assert!(!p.staged_fallback);
        let offset=a.message_id.as_ptr() as usize-value.envelope().as_ptr() as usize;assert_eq!(&value.envelope()[offset..offset+a.message_id.len()],id);
    }
    for (index,id,success,failed,runtime) in [(0,2,4,5,20),(1,1,6,7,10)]{
        let s=value.persisted_server_stat(index).unwrap();assert_eq!(s.persisted_state_id,id);assert_eq!(s.success_articles,success);assert_eq!(s.failed_articles,failed);
        assert_eq!(value.server_mapping()[index].persisted_state_id,id);assert_eq!(value.server_mapping()[index].runtime_server_id,runtime);
    }
    assert_eq!(value.schema_version,2);assert_eq!(value.immutable_capture_version,1);assert_eq!(value.source_kind,2);assert!(value.measured_owned_bytes<=MAX_PAYLOAD);
}
#[test]
fn held_output_exact_historical_target_parent_survive_updates_and_recovery() {
    let mut f=held_issued_fixture();let mut original=Some(held_input(&f));
    let raw=f.file.original_source_bytes.clone();let mut p=f.registry.prepare_subject(update_template(&f.file),&raw,&f.host).unwrap();let newer=f.registry.store_prepared_subject(&mut p,&mut f.host).unwrap();
    let mut p=f.registry.prepare_subject(update_template(&f.collection),&capture(),&f.host).unwrap();let newer_parent=f.registry.store_prepared_subject(&mut p,&mut f.host).unwrap();
    assert!(newer.subject_revision>f.file.subject_revision);assert!(newer_parent.subject_revision>f.collection.subject_revision);
    let recovered=Registry::recover([1;16],f.host.journal_identity().unwrap(),&f.host.frames).unwrap();
    let result=recovered.validate_held_recovery_input(&mut original,&f.host).unwrap();assert_eq!(result.target(),&ExactReference::from_record(&f.file));assert_eq!(result.parent(),&ExactReference::from_record(&f.collection));
}
#[test]
fn held_output_consistent_request_cannot_forge_retained_custody_or_effective_map() {
    for case in 0..2{
        let mut f=held_issued_fixture();let mut input=Some(held_input(&f));
        if case==0{let row=f.registry.subjects.iter_mut().find(|s|s.binding==f.file.binding).unwrap();row.custody.id=[3;32];row.source.custody_receipt_id=[3;32];}
        else{f.registry.intake_associations[0].files[0].articles[0].message_id=b"<forged>".to_vec();}
        assert_eq!(input.as_ref().unwrap().request.target,input.as_ref().unwrap().request.dependencies[0].reference);
        assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err(),"case{case}");assert!(input.is_some());
    }
}

// Retained codec-only control; no actual constructor/custody authority
// is inferred from the codec-only group span check.
#[test]
fn held_output_codec_group_spans_and_dry_shape_share_existing_parser() {
    let f=held_issued_fixture();let mut input=held_input(&f);let envelope=source_codec::Envelope::parse(2,&input.envelope).unwrap();
    let old=envelope.body;let at=old.windows(b"2,0\n0\n2\n".len()).position(|v|v==b"2,0\n0\n2\n").unwrap();
    let body=[&old[..at],b"2,0\n2\nalt.one\nalt.two\n2\n",&old[at+b"2,0\n0\n2\n".len()..]].concat();
    let state=envelope.second.unwrap().to_vec();let mut bytes=b"PURGE-SOURCE-BYTES1".to_vec();for n in [1u32,2,7,body.len()as u32]{bytes.extend(n.to_le_bytes());}bytes.extend(body);bytes.push(1);bytes.extend(7u32.to_le_bytes());bytes.push(0);bytes.extend((state.len()as u32).to_le_bytes());bytes.extend(state);
    input.envelope=bytes;
    let (shape,allocations)=crate::allocation_probe::measure(||source_codec::held_file_shape(&input.envelope));assert_eq!(allocations.calls,0);let shape=shape.unwrap();assert_eq!(shape.groups,2);assert_eq!(shape.articles,2);assert_eq!(shape.stats,2);
    let decoded=source_codec::decode_held_file(&input.envelope,shape).unwrap();for (index,expected) in [b"alt.one".as_slice(),b"alt.two".as_slice()].into_iter().enumerate(){let s=decoded.summary.groups[index];assert_eq!(&input.envelope[s.begin..s.begin+s.len],expected);}
    // The map was deliberately not changed: constructor must still reject.
    input.observations=held_observations(&input.envelope);let mut input=Some(input);assert!(f.registry.validate_held_recovery_input(&mut input,&f.host).is_err());
}
#[test]
fn held_output_capacity_arithmetic_overflow_is_checked_without_heap() {
    let (result,allocations)=crate::allocation_probe::measure(||{let mut b=HeldBudget::new();b.add(1)?;b.add(usize::MAX)});assert_eq!(result,Err(PurgeError::LimitExceeded));assert_eq!(allocations.calls,0);
    let (result,allocations)=crate::allocation_probe::measure(||HeldBudget::new().array::<SourceValidation>(usize::MAX));assert_eq!(result,Err(PurgeError::LimitExceeded));assert_eq!(allocations.calls,0);
}

// Deterministic accounting controls frozen before this scoped implementation.
// Deterministic logical-capacity controls; no allocator behavior override.
// HeldCapacity is the proposed accounting helper used at actual allocation sites.
#[test]
fn held_capacity_returned_surplus_is_charged_from_actual_vector() {
    let mut returned=Vec::<u8>::with_capacity(4096);returned.push(7);
    let actual=returned.capacity();assert!(actual>1);
    let mut live=HeldCapacity::new(17).unwrap();
    live.admit_vec(1,&returned).unwrap();
    assert_eq!(live.bytes(),17+actual);
}
#[test]
fn held_capacity_surplus_crosses_aggregate_without_changing_some() {
    let f=held_issued_fixture();let input=Some(held_input(&f));
    let before=held_input_fingerprint(input.as_ref().unwrap());let frames=f.host.frames.len();
    let returned=Vec::<u64>::with_capacity(64);let actual=returned.capacity()*std::mem::size_of::<u64>();
    let mut live=HeldCapacity::new(MAX_PAYLOAD-actual+1).unwrap();let prior=live.bytes();
    assert!(matches!(live.admit_vec(1,&returned),Err(PurgeError::LimitExceeded)));
    assert_eq!(live.bytes(),prior); // rejected charge is transactional
    assert_eq!(held_input_fingerprint(input.as_ref().unwrap()),before);
    assert_eq!(f.host.frames.len(),frames);
}
#[test]
fn held_capacity_exact_aggregate_boundary_accepts_actual_capacity() {
    let returned=Vec::<u64>::with_capacity(64);let actual=returned.capacity()*std::mem::size_of::<u64>();
    let mut live=HeldCapacity::new(MAX_PAYLOAD-actual).unwrap();
    live.admit_vec(1,&returned).unwrap();assert_eq!(live.bytes(),MAX_PAYLOAD);
    assert_eq!(live.preflight::<u8>(1),Err(PurgeError::LimitExceeded));
}
#[test]
fn held_capacity_scratch_drop_releases_only_its_actual_backing() {
    let scratch=Vec::<u8>::with_capacity(4096);let output=Vec::<u64>::with_capacity(32);
    let retained=output.capacity()*std::mem::size_of::<u64>();let scratch_bytes=scratch.capacity();
    let mut live=HeldCapacity::new(13).unwrap();live.admit_vec(1,&scratch).unwrap();live.admit_vec(1,&output).unwrap();
    assert_eq!(live.bytes(),13+scratch_bytes+retained);
    live.drop_scratch(scratch).unwrap();assert_eq!(live.bytes(),13+retained);
    // Ownership returned by a helper remains charged until the caller drops it.
    assert_eq!(output.len(),0);live.drop_scratch(output).unwrap();assert_eq!(live.bytes(),13);
}
#[test]
fn held_capacity_nested_backings_are_simultaneous_not_just_outer_length() {
    let mut nested=Vec::<Vec<u8>>::with_capacity(2);nested.push(Vec::with_capacity(17));nested.push(Vec::with_capacity(31));
    let outer=nested.capacity()*std::mem::size_of::<Vec<u8>>();let inner=nested.iter().map(Vec::capacity).sum::<usize>();
    let mut live=HeldCapacity::new(MAX_PAYLOAD-outer-inner).unwrap();
    live.admit_vec(nested.len(),&nested).unwrap();for row in &nested{live.admit_vec(row.len(),row).unwrap();}
    assert_eq!(live.bytes(),MAX_PAYLOAD);
}

// Retained shared-helper ownership controls, UNRUN on this candidate.
#[test]
fn held_capacity_actual_wire_copy_retains_decoded_and_drops_wire_charge() {
    let f=held_issued_fixture();let capacity=HeldCapacity::new(23).unwrap();
    let copied=copy_accounted(&f.file.source,&capacity).unwrap();
    assert_eq!(copied,f.file.source);
    let actual=copied.binding.posting_source.capacity()+copied.parent_collection.as_ref().map_or(0,|p|p.posting_source.capacity());
    assert_eq!(capacity.bytes(),23+actual);
}
#[test]
fn held_capacity_partial_nested_decode_drops_scratch_before_rollback() {
    let rows=vec![vec![1u8,2,3],vec![4u8,5,6]];
    let capacity=HeldCapacity::new(11).unwrap();let mut image=wire_accounted(&rows,Some(&capacity)).unwrap();
    let image_capacity=image.capacity();image.pop();
    assert!(unwire_accounted::<Vec<Vec<u8>>>(&image,&capacity).is_err());
    assert_eq!(capacity.bytes(),11+image_capacity);
    capacity.drop_scratch(image).unwrap();assert_eq!(capacity.bytes(),11);
}
#[test]
fn held_capacity_actual_codec_returns_typed_backings_and_releases_stats_scratch() {
    let f=held_issued_fixture();let input=held_input(&f);let shape=source_codec::held_file_shape(&input.envelope).unwrap();
    let capacity=HeldCapacity::new(7).unwrap();
    let decoded=source_codec::decode_held_file_accounted(&input.envelope,shape,Some(&capacity)).unwrap();
    let actual=decoded.summary.groups.capacity()*std::mem::size_of::<EnvelopeSpan>()
        +decoded.articles.capacity()*std::mem::size_of::<HeldArticle>()
        +decoded.stats.capacity()*std::mem::size_of::<HeldServerStat>();
    assert_eq!(capacity.bytes(),7+actual);
    assert_eq!(decoded.stats.len(),2);assert_eq!(decoded.articles.len(),2);
}

// Removing producer request/sequence/namespace checks must fail this test.
#[test]
fn held_output_requires_exact_durable_producer_reservation() {
    let f=held_issued_fixture();
    for case in 0..5 {
        let mut i=held_input(&f);match case {
            0=>i.request.producer.request[0]^=1,
            1=>i.request.producer.publication_sequence+=1,
            2=>i.request.producer.id=0,
            3=>i.request.producer.id=f.producers.last+1,
            _=>{let subject=f.registry.id_reservations.iter().find(|r|r.id_namespace==1).unwrap();
                i.request.producer=ProducerReservationKey{request:subject.request,publication_sequence:subject.publication_sequence,id:subject.first};},
        }
        let fingerprint=held_input_fingerprint(&i);let frames=f.host.frames.clone();let before=f.registry.runtime_observation();let mut i=Some(i);
        assert!(matches!(f.registry.validate_held_recovery_input(&mut i,&f.host),Err(PurgeError::Conflict)),"producer case{case}");
        assert_eq!(held_input_fingerprint(i.as_ref().unwrap()),fingerprint);assert_eq!(f.host.frames,frames);assert_eq!(f.registry.runtime_observation(),before);
    }
}
// An accidental live-preimage normalization or admission side effect fails here.
#[test]
fn held_output_preserves_empty_expected_live_preimage_and_unknown_runtime() {
    let mut f=held_issued_fixture();f.registry.create_common_runtime(&f.host).unwrap();
    let before=f.registry.runtime_observation();let frames=f.host.frames.clone();
    let mut i=held_input(&f);i.request.dependencies[0].current_preimage=Some(Vec::new());let mut i=Some(i);
    let v=f.registry.validate_held_recovery_input(&mut i,&f.host).unwrap();
    assert_eq!(v.request().dependencies[0].current_preimage.as_deref(),Some(b"".as_slice()));
    assert_eq!(f.registry.runtime_observation(),before);assert_eq!(f.host.frames,frames);
    let mut absent=held_input(&f);absent.request.dependencies[0].current_preimage=None;let mut absent=Some(absent);
    assert!(matches!(f.registry.validate_held_recovery_input(&mut absent,&f.host),Err(PurgeError::InvalidInput)));assert!(absent.is_some());
}
// Skipping current field/group authority or using caller desired bytes fails here.
#[test]
fn held_output_group_span_comes_from_real_committed_effective_map() {
    let f=held_issued_fixture_variant(true);let mut i=Some(held_input(&f));
    let v=f.registry.validate_held_recovery_input(&mut i,&f.host).unwrap();
    assert_eq!(v.view().group_count,1);assert_eq!(v.group(0),Some(b"alt.valid".as_slice()));assert!(v.group(1).is_none());
}
// A callback before complete aggregate preflight fails, not merely an allocation.
struct HeldNoCallbackHost;
impl Host for HeldNoCallbackHost {
    fn supported(&self)->bool{panic!("Host callback before complete preflight")}
    fn journal_identity(&self)->Result<[u8;32],PurgeError>{panic!("Host callback before complete preflight")}
    fn publish(&mut self,_:u64,_:&[u8])->Result<PublicationAck,PurgeError>{panic!("constructor publication")}
    fn execute(&mut self,_:&Call<'_>)->Result<Ack,PurgeError>{panic!("constructor execution")}
}
#[test]
fn held_output_complete_preflight_precedes_any_host_callback() {
    let f=held_issued_fixture();let mut i=held_input(&f);i.request.dependencies[0].current_preimage=Some(Vec::with_capacity(MAX_PAYLOAD));
    let before=held_input_fingerprint(&i);let mut i=Some(i);
    let (r,alloc)=crate::allocation_probe::measure(||f.registry.validate_held_recovery_input(&mut i,&HeldNoCallbackHost));
    assert!(matches!(r,Err(PurgeError::LimitExceeded)));assert_eq!(alloc.calls,0);assert_eq!(held_input_fingerprint(i.as_ref().unwrap()),before);
}
// Bounds are retained even for small well-framed bodies and excess observations.
#[test]
fn held_output_observation_limit_and_invalid_owner_preserve_input() {
    let f=held_issued_fixture();for case in 0..2 {
        let mut i=held_input(&f);if case==0{i.observations.resize(32769,0);}else{i.request.owner_kind=0;}
        let before=held_input_fingerprint(&i);let mut i=Some(i);assert!(f.registry.validate_held_recovery_input(&mut i,&f.host).is_err());
        assert_eq!(held_input_fingerprint(i.as_ref().unwrap()),before);
    }
}
}

// Additive private held-output boundary; no admission or persisted format.
use super::runtime_core::{RecoveryPrepareRequest, ExactReference};

// Owned before entry by the actual outside-guard capture owner. No defaults.
#[derive(Debug)]
pub(super) struct HeldRecoveryInput {
    pub request: RecoveryPrepareRequest,
    pub envelope: Vec<u8>,
    pub observations: Vec<u8>,
    pub server_mapping: Vec<ServerIdPair>,
}
#[derive(Debug, PartialEq, Eq)]
pub(super) struct ServerIdPair {
    pub persisted_state_id: i32,
    pub runtime_server_id: i32,
}

// Only subjects' validated constructor can create this type. No Clone,
// Default, public fields, mutable accessors, deserializer or into_parts.
#[derive(Debug)]
pub(super) struct ValidatedHeldFile {
    input: HeldRecoveryInput,
    target_source: SourceValidation,
    target_custody: CustodyReceipt,
    parent_source: SourceValidation,
    parent_custody: CustodyReceipt,
    schema_version: u32,                 // 2: actual retained subject schema
    immutable_capture_version: u32,      // 1: unchanged protected projection
    source_kind: u32,                    // 2: file
    summary: HeldFileSummary,
    articles: Vec<HeldArticle>,
    progress: Option<HeldFileProgress>,
    persisted_server_stats: Vec<HeldServerStat>,
    measured_owned_bytes: usize,         // constructor-derived, no caller setter
}

// Offsets refer only to input.envelope, never caller or Registry storage.
// Logical bounds and span ownership are checked during the existing codec pass.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct EnvelopeSpan { pub(super) begin: usize, pub(super) len: usize }
#[derive(Debug)]
pub(super) struct HeldFileSummary {
    pub(super) subject: EnvelopeSpan, pub(super) filename: EnvelopeSpan,
    pub(super) original_name_disk: EnvelopeSpan, pub(super) output_filename: EnvelopeSpan,
    pub(super) filename_confirmed: bool, pub(super) time: i32, pub(super) size: i64, pub(super) missed_size: i64,
    pub(super) par_file: bool, pub(super) total_articles: i32, pub(super) missed_articles: i32,
    pub(super) groups: Vec<EnvelopeSpan>,
}
#[derive(Debug)]
pub(super) struct HeldArticle {
    pub(super) part_number: i32, pub(super) advertised_size: i32, pub(super) message_id: EnvelopeSpan,
    pub(super) progress: Option<HeldArticleProgress>,
}
#[derive(Debug)]
pub(super) struct HeldArticleProgress {
    pub(super) status: u32, pub(super) segment_offset: i64, pub(super) segment_size: i32, pub(super) crc: u32,
    pub(super) staged_fallback: bool,
}
#[derive(Debug)]
pub(super) struct HeldFileProgress {
    pub(super) completed_selection: bool,
    pub(super) success_articles: i32, pub(super) failed_articles: i32,
    pub(super) remaining_size: i64, pub(super) success_size: i64, pub(super) failed_size: i64,
    pub(super) completed_articles: i32, pub(super) decoded_file_size: i64,
    pub(super) hash16k: Option<EnvelopeSpan>, pub(super) par_set_id: Option<EnvelopeSpan>,
}
#[derive(Debug)]
pub(super) struct HeldServerStat { pub(super) persisted_state_id: i32, pub(super) success_articles: i32, pub(super) failed_articles: i32 }

// Read-only views are data, not constructible validation capabilities. Only
// ValidatedHeldFile can be accepted by future core preparation.
pub(super) struct HeldFileView<'a> {
    pub target: &'a ExactReference, pub parent: &'a ExactReference,
    pub source: &'a SourceValidation, pub custody: &'a CustodyReceipt,
    pub parent_source: &'a SourceValidation, pub parent_custody: &'a CustodyReceipt,
    pub subject: &'a [u8], pub filename: &'a [u8],
    pub original_name_disk: &'a [u8], pub output_filename: &'a [u8],
    pub filename_confirmed: bool, pub time: i32, pub size: i64, pub missed_size: i64,
    pub par_file: bool, pub total_articles: i32, pub missed_articles: i32,
    pub group_count: usize, pub article_count: usize,
    pub progress: Option<HeldFileProgressView<'a>>,
    pub persisted_server_stat_count: usize,
}
pub(super) struct HeldArticleView<'a> {
    pub part_number: i32, pub advertised_size: i32, pub message_id: &'a [u8],
    pub progress: Option<HeldArticleProgressView>,
}
pub(super) struct HeldArticleProgressView {
    pub status: u32, pub segment_offset: i64, pub segment_size: i32,
    pub crc: u32, pub staged_fallback: bool,
}
pub(super) struct HeldFileProgressView<'a> {
    pub completed_selection: bool, pub success_articles: i32, pub failed_articles: i32,
    pub remaining_size: i64, pub success_size: i64, pub failed_size: i64,
    pub completed_articles: i32, pub decoded_file_size: i64,
    pub hash16k: Option<&'a [u8]>, pub par_set_id: Option<&'a [u8]>,
}
pub(super) struct HeldServerStatView {
    pub persisted_state_id: i32, pub success_articles: i32, pub failed_articles: i32,
}

// Dynamic logical-capacity accounting for the already-preflighted held path.
// No allocator exactness assumption: admit every actual Vec capacity before use.
// A just-returned rejected allocation can transiently exist; this is not RSS.
pub(super) struct HeldCapacity { bytes:std::cell::Cell<usize> }
impl HeldCapacity {
    pub(super) fn new(bytes:usize)->Result<Self,PurgeError>{
        if bytes>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}Ok(Self{bytes:std::cell::Cell::new(bytes)})
    }
    pub(super) fn bytes(&self)->usize{self.bytes.get()}
    pub(super) fn preflight<T>(&self,n:usize)->Result<(),PurgeError>{
        let bytes=n.checked_mul(std::mem::size_of::<T>()).and_then(|n|self.bytes().checked_add(n)).ok_or(PurgeError::LimitExceeded)?;
        if bytes>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}Ok(())
    }
    pub(super) fn admit_vec<T>(&self,requested:usize,value:&Vec<T>)->Result<(),PurgeError>{
        if value.capacity()<requested{return Err(PurgeError::LimitExceeded);}
        self.preflight::<T>(value.capacity())?;
        let bytes=value.capacity().checked_mul(std::mem::size_of::<T>()).and_then(|n|self.bytes().checked_add(n)).ok_or(PurgeError::LimitExceeded)?;
        self.bytes.set(bytes);Ok(())
    }
    pub(super) fn reserved<T>(&self,n:usize)->Result<Vec<T>,PurgeError>{
        self.preflight::<T>(n)?;let value=reserved(n)?;self.admit_vec(n,&value)?;Ok(value)
    }
    pub(super) fn drop_scratch<T:Copy>(&self,value:Vec<T>)->Result<(),PurgeError>{
        let bytes=value.capacity().checked_mul(std::mem::size_of::<T>()).ok_or(PurgeError::LimitExceeded)?;
        drop(value); // release logical charge only AFTER backing destruction
        self.bytes.set(self.bytes().checked_sub(bytes).ok_or(PurgeError::InvalidInput)?);Ok(())
    }
    // Copy results cannot own Vec backing. Locals are dropped before returning;
    // borrowed references and fixed scalar validation results may escape.
    pub(super) fn scratch<T:Copy>(&self,operation:impl FnOnce()->Result<T,PurgeError>)->Result<T,PurgeError>{
        let before=self.bytes();let result=operation();self.bytes.set(before);result
    }
    // Decoded ownership stays charged on success. On failure all closure locals
    // have already dropped, including partially decoded nested vectors.
    pub(super) fn retained<T>(&self,operation:impl FnOnce()->Result<T,PurgeError>)->Result<T,PurgeError>{
        let before=self.bytes();let result=operation();if result.is_err(){self.bytes.set(before);}result
    }
}

// One checked logical-capacity sum. This does not measure allocator overhead or
// Host implementations; no caller-supplied budget can bypass the accounting.
pub(super) struct HeldBudget { bytes:usize }
impl HeldBudget {
    pub(super) fn new()->Self{Self{bytes:0}}
    pub(super) fn add(&mut self,n:usize)->Result<(),PurgeError>{
        self.bytes=self.bytes.checked_add(n).ok_or(PurgeError::LimitExceeded)?;
        if self.bytes>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}Ok(())
    }
    pub(super) fn array<T>(&mut self,n:usize)->Result<(),PurgeError>{self.add(n.checked_mul(std::mem::size_of::<T>()).ok_or(PurgeError::LimitExceeded)?)}
    fn binding(&mut self,b:&MemberBinding)->Result<(),PurgeError>{self.add(b.posting_source.capacity())}
    fn optional_binding(&mut self,b:&Option<MemberBinding>)->Result<(),PurgeError>{if let Some(b)=b{self.binding(b)?;}Ok(())}
    fn source(&mut self,s:&SourceValidation)->Result<(),PurgeError>{self.binding(&s.binding)?;self.optional_binding(&s.parent_collection)}
    fn record(&mut self,r:&SubjectRecord)->Result<(),PurgeError>{
        self.array::<SubjectRecord>(1)?;self.binding(&r.binding)?;self.optional_binding(&r.prior)?;
        self.source(&r.source)?;self.optional_binding(&r.parent)?;
        self.add(r.original_source_bytes.capacity())?;self.add(r.immutable_source_bytes.capacity())
    }
    fn reference(&mut self,r:&ExactReference)->Result<(),PurgeError>{self.binding(&r.binding)?;self.optional_binding(&r.parent)}
}
pub(super) fn held_wire_size<T:Wire>(v:&T)->Result<usize,PurgeError>{
    let mut writer=Writer{bytes:Vec::new(),size:0,measuring:true,fixed_limit:None};v.put(&mut writer)?;Ok(writer.size)
}
fn held_source_scratch(b:&mut HeldBudget,r:&SubjectRecord)->Result<(),PurgeError>{
    let binding=held_wire_size(&r.binding)?;let parent=held_wire_size(&r.parent)?;
    b.add(binding)?;b.add(parent)?;
    // source_key owns both wires and its framed key at the same time.
    b.add(17usize.checked_add(16).and_then(|n|n.checked_add(binding)).and_then(|n|n.checked_add(parent)).and_then(|n|n.checked_add(52)).ok_or(PurgeError::LimitExceeded)?)?;
    // Only SourceValidation is copied, never SubjectRecord. Generic copy has
    // wire plus decoded ownership simultaneously, included here explicitly.
    b.add(held_wire_size(&r.source)?)?;b.array::<SourceValidation>(1)?;b.add(r.source.heap_size()?)?;Ok(())
}
impl Registry {
    // Candidate selection by borrow is NOT validation authority. The complete
    // resolver/custody/key checks run after ALL allocation sizing succeeds.
    fn held_reference_candidate(&self,r:&ExactReference)->Result<&SubjectRecord,PurgeError>{
        if self.recovery_required{return Err(PurgeError::RecoveryRequired);}
        check_binding(&r.binding)?;if let Some(parent)=&r.parent{check_binding(parent)?;}
        if r.domain!=self.domain||r.subject_revision==0||r.publication_sequence==0{return Err(PurgeError::Conflict);}
        let record=self.subjects.iter().find(|v|v.domain==r.domain&&v.binding==r.binding&&v.subject_revision==r.subject_revision&&v.publication_sequence==r.publication_sequence).ok_or(PurgeError::MissingInventory)?;
        if record.parent!=r.parent||record.source.source_record_id!=r.source_record_id{return Err(PurgeError::Conflict);}
        if record.schema_version!=2||record.immutable_capture_version!=1{return Err(PurgeError::Unsupported);}Ok(record)
    }
    pub(super) fn validate_held_recovery_input(&self,input:&mut Option<HeldRecoveryInput>,host:&impl Host)->Result<ValidatedHeldFile,PurgeError>{
        use super::runtime_core::{DependencyRole,InstallMode};
        let captured=input.as_ref().ok_or(PurgeError::InvalidInput)?;
        let request=&captured.request;
        let mut budget=HeldBudget::new();budget.array::<ValidatedHeldFile>(1)?;
        budget.add(captured.envelope.capacity())?;budget.add(captured.observations.capacity())?;
        budget.array::<ServerIdPair>(captured.server_mapping.capacity())?;
        budget.array::<super::runtime_core::DependencyRequest>(request.dependencies.capacity())?;
        budget.add(request.desired_writes.capacity())?;budget.reference(&request.target)?;
        for d in &request.dependencies{budget.reference(&d.reference)?;if let Some(p)=&d.current_preimage{budget.add(p.capacity())?;}}
        if request.mode!=InstallMode::ArticlesAndProgress||request.schema!=1{return Err(PurgeError::Unsupported);}
        if request.desired_writes.len()!=0||request.desired_writes.capacity()!=0||request.owner_kind==0||request.work_kind==0||request.parent_ticket.is_some(){return Err(PurgeError::InvalidInput);}
        let [target_input,parent_input]=request.dependencies.as_slice() else{return Err(PurgeError::InvalidInput);};
        if target_input.reference!=request.target||target_input.role!=DependencyRole::InstallTarget||target_input.current_preimage.is_none()
            ||parent_input.role!=DependencyRole::ImmutableParent||parent_input.current_preimage.is_some(){return Err(PurgeError::InvalidInput);}
        let target=self.held_reference_candidate(&request.target)?;let parent=self.held_reference_candidate(&parent_input.reference)?;
        if target.source_kind!=2||target.binding.file_id.is_none()||target.parent.as_ref()!=Some(&parent.binding)
            ||parent.source_kind!=1||parent.binding.file_id.is_some()||parent.parent.is_some(){return Err(PurgeError::Conflict);}
        budget.record(target)?;budget.record(parent)?;
        self.held_intake_retained_budget(target,&mut budget)?;self.held_intake_retained_budget(parent,&mut budget)?;
        let retained_bytes=budget.bytes;
        // Conservative fixed temporary ownership counted throughout; these same
        // terms are included below in the complete requested preflight.
        let fixed_temporary=std::mem::size_of::<SourceValidation>().checked_mul(2)
            .and_then(|n|n.checked_add(std::mem::size_of::<source_codec::DecodedHeldFile>()))
            .and_then(|n|n.checked_add(std::mem::size_of::<intake::CapturedDescriptor>().checked_mul(2)?))
            .ok_or(PurgeError::LimitExceeded)?;
        held_source_scratch(&mut budget,target)?;held_source_scratch(&mut budget,parent)?;
        self.held_intake_scratch_budget(target,&mut budget)?;self.held_intake_scratch_budget(parent,&mut budget)?;
        // These two passes share the existing codec and allocate nothing.
        let shape=source_codec::held_file_shape(&captured.envelope)?;
        source_codec::held_read(2,&captured.envelope,&captured.observations)?;
        budget.add(source_codec::project_size(2,&captured.envelope)?)?;
        budget.array::<EnvelopeSpan>(shape.groups)?;budget.array::<HeldArticle>(shape.articles)?;
        budget.array::<HeldServerStat>(shape.stats)?;budget.array::<i64>(shape.stats)?;
        budget.array::<source_codec::DecodedHeldFile>(1)?;
        let capacity=HeldCapacity::new(retained_bytes.checked_add(fixed_temporary).ok_or(PurgeError::LimitExceeded)?)?;
        // No allocation/resolver/copy/Host callback appears above this point.
        self.ready(host)?;
        if request.producer.id==0 || !self.id_reservations.iter().any(|r|
            r.id_namespace==2 && r.request==request.producer.request
            && r.publication_sequence==request.producer.publication_sequence
            && r.publication_sequence!=0 && r.first<=request.producer.id && request.producer.id<=r.last)
        {return Err(PurgeError::Conflict);}
        if source_key_accounted(target,Some(&capacity))?!=request.target.source_record_id||source_key_accounted(parent,Some(&capacity))?!=parent_input.reference.source_record_id{return Err(PurgeError::Conflict);}
        self.validate_subject_custody_accounted(target,Some(&capacity))?;self.validate_subject_custody_accounted(parent,Some(&capacity))?;
        self.validate_held_intake_source(target,&captured.envelope,&capacity)?;
        capacity.scratch(||{
            let projection=source_codec::project_held_file(&captured.envelope,&capacity)?;
            if projection!=target.immutable_source_bytes{return Err(PurgeError::Conflict);}Ok(())
        })?;
        let decoded=source_codec::decode_held_file_accounted(&captured.envelope,shape,Some(&capacity))?;
        let target_source=copy_accounted(&target.source,&capacity)?;let target_custody=target.custody.clone();
        let parent_source=copy_accounted(&parent.source,&capacity)?;let parent_custody=parent.custody.clone();
        let measured_owned_bytes=capacity.bytes();
        // The last operation is an infallible ownership transfer. Any prior
        // error drops temporary storage outside guards and preserves Some.
        let owned=input.take().expect("borrowed Some retained through validation");
        Ok(ValidatedHeldFile{input:owned,target_source,target_custody,parent_source,parent_custody,schema_version:2,immutable_capture_version:1,source_kind:2,
            summary:decoded.summary,articles:decoded.articles,progress:Some(decoded.progress),persisted_server_stats:decoded.stats,measured_owned_bytes})
    }
}
impl ValidatedHeldFile {
    pub(super) fn target(&self)->&ExactReference{&self.input.request.target}
    pub(super) fn parent(&self)->&ExactReference{&self.input.request.dependencies[1].reference}
    pub(super) fn request(&self)->&RecoveryPrepareRequest{&self.input.request}
    pub(super) fn envelope(&self)->&[u8]{&self.input.envelope}
    pub(super) fn observations(&self)->&[u8]{&self.input.observations}
    pub(super) fn server_mapping(&self)->&[ServerIdPair]{&self.input.server_mapping}
    pub(super) fn source_validation(&self)->(&SourceValidation,&CustodyReceipt){(&self.target_source,&self.target_custody)}
    pub(super) fn parent_validation(&self)->(&SourceValidation,&CustodyReceipt){(&self.parent_source,&self.parent_custody)}
    fn span(&self,s:EnvelopeSpan)->&[u8]{&self.input.envelope[s.begin..s.begin+s.len]}
    pub(super) fn view(&self)->HeldFileView<'_>{
        let s=&self.summary;HeldFileView{target:self.target(),parent:self.parent(),source:&self.target_source,custody:&self.target_custody,parent_source:&self.parent_source,parent_custody:&self.parent_custody,
            subject:self.span(s.subject),filename:self.span(s.filename),original_name_disk:self.span(s.original_name_disk),output_filename:self.span(s.output_filename),
            filename_confirmed:s.filename_confirmed,time:s.time,size:s.size,missed_size:s.missed_size,par_file:s.par_file,total_articles:s.total_articles,missed_articles:s.missed_articles,
            group_count:s.groups.len(),article_count:self.articles.len(),persisted_server_stat_count:self.persisted_server_stats.len(),progress:self.progress.as_ref().map(|p|HeldFileProgressView{
                completed_selection:p.completed_selection,success_articles:p.success_articles,failed_articles:p.failed_articles,remaining_size:p.remaining_size,success_size:p.success_size,failed_size:p.failed_size,
                completed_articles:p.completed_articles,decoded_file_size:p.decoded_file_size,hash16k:p.hash16k.map(|s|self.span(s)),par_set_id:p.par_set_id.map(|s|self.span(s))})}
    }
    pub(super) fn group(&self,index:usize)->Option<&[u8]>{self.summary.groups.get(index).map(|s|self.span(*s))}
    pub(super) fn article(&self,index:usize)->Option<HeldArticleView<'_>>{self.articles.get(index).map(|a|HeldArticleView{
        part_number:a.part_number,advertised_size:a.advertised_size,message_id:self.span(a.message_id),progress:a.progress.as_ref().map(|p|HeldArticleProgressView{status:p.status,segment_offset:p.segment_offset,segment_size:p.segment_size,crc:p.crc,staged_fallback:p.staged_fallback})})}
    pub(super) fn persisted_server_stat(&self,index:usize)->Option<HeldServerStatView>{self.persisted_server_stats.get(index).map(|s|HeldServerStatView{persisted_state_id:s.persisted_state_id,success_articles:s.success_articles,failed_articles:s.failed_articles})}
}
