//! NEW SOURCE-ONLY fixture controls: actual existing Rust issuer/resolver with
//! MemoryHost publication callbacks. No filesystem/SAX/daemon/work permission.
use super::{Registry, subjects::{IdReservation, SubjectRecord}};
use super::subjects::tests::{host, capture, template, admit_fixture, MemoryHost};

pub(super) struct IssuedFixture {
    pub registry: Registry,
    pub host: MemoryHost,
    pub producers: IdReservation,
    pub collection: SubjectRecord,
    pub file: SubjectRecord,
}

pub(super) fn issued_fixture() -> IssuedFixture {
    let mut host = host();
    let mut registry = Registry::initialize([1; 16], &mut host).unwrap();
    let subjects = registry.reserve_ids(1, [2; 16], 1, &mut host).unwrap();
    let producers = registry.reserve_ids(2, [3; 16], 2, &mut host).unwrap();
    admit_fixture(&mut registry, &subjects, &mut host);
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
    let mut file_capture = b"PURGE-SOURCE-BYTES1".to_vec();
    for n in [1u32, 2, 7, body.len() as u32] { file_capture.extend(n.to_le_bytes()); }
    file_capture.extend(body); file_capture.push(0); // no progress body
    let mut prepared = registry.prepare_subject(file_template, &file_capture, &host).unwrap();
    let file = registry.store_prepared_subject(&mut prepared, &mut host).unwrap();
    IssuedFixture { registry, host, producers, collection, file }
}

#[test]
fn runtime_fixture_commits_real_file_parent_and_producer_reservation() {
    let f = issued_fixture();
    assert_eq!(f.producers.id_namespace, 2);
    assert_eq!(f.producers.count, 2);
    assert_eq!(f.file.schema_version, 2);
    assert_eq!(f.file.source_kind, 2);
    assert_eq!(f.file.parent.as_ref(), Some(&f.collection.binding));
    assert_eq!(f.file.source.parent_collection.as_ref(), Some(&f.collection.binding));
    let loaded = f.registry.load_subject_reference(f.file.domain, &f.file.binding,
        f.file.subject_revision, f.file.publication_sequence,
        f.file.source.source_record_id, &f.host).unwrap();
    assert_eq!(loaded, f.file);
    assert_eq!(f.file.custody.id, f.file.source.custody_receipt_id);
}

#[test]
fn runtime_fixture_replays_actual_producer_reservation_without_new_frames() {
    let mut f = issued_fixture();
    let before = f.host.frames.len();
    let replay = f.registry.reserve_ids(2, f.producers.request, 2, &mut f.host).unwrap();
    assert_eq!(replay, f.producers);
    assert_eq!(f.host.frames.len(), before);
}
