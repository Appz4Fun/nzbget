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
    // Exact F4 K framing; publication sequence deliberately is not a key input.
    let binding = wire(&record.binding)?;
    let parent = wire(&record.parent)?;
    let n = 17usize.checked_add(16).and_then(|n| n.checked_add(binding.len()))
        .and_then(|n| n.checked_add(parent.len())).and_then(|n| n.checked_add(52))
        .ok_or(PurgeError::LimitExceeded)?;
    if n > MAX_PAYLOAD { return Err(PurgeError::LimitExceeded); }
    let mut bytes = reserved(n)?;
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
}
