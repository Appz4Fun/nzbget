//! NEW UNRUN contract-test Source for the missing PRIVATE Registry-owned core.
//! Intended private runtime_core/Create API is not implemented or composed. These tests are
//! NOT an executed RED; do not run before the existing fixture controls pass.
//! Scope is owned preparation + fail-closed pending admission. Actual C++
//! locks/lifetime, C2 work/WorkView/revoke/finalACK still need further tests.
use super::runtime_fixture::{issued_fixture, IssuedFixture};
use super::runtime_core::{ExactReference, ProducerReservationKey, InstallMode,
    RecoveryPrepareRequest, DependencyRequest, DependencyRole, RegisterOutcome};
use crate::dupepurge::PurgeError;

// Pure-Rust test setup only. This explicit intended private Create is distinct
// from the actual C++ shared Store owner and its independently required proof.
// No lazy creation from prepare/register and no caller-supplied coverage flag.
fn issued_runtime_fixture() -> IssuedFixture {
    let mut f = issued_fixture();
    assert!(!f.registry.runtime_observation().runtime_present);
    f.registry.create_common_runtime(&f.host).unwrap();
    assert!(f.registry.runtime_observation().runtime_present);
    assert!(!f.registry.runtime_observation().coverage_known);
    f
}

fn bytes(out: &mut Vec<u8>, s: &[u8]) {
    out.extend((s.len() as u32).to_le_bytes()); out.extend(s);
}
fn preimage() -> Vec<u8> {
    let mut b = b"RCPRE1\0\0".to_vec();
    b.extend(1u32.to_le_bytes()); b.extend(1u32.to_le_bytes());
    b.extend([0, 1]); // completed=false, still needs article hydration
    bytes(&mut b, b"fixture"); bytes(&mut b, b"file");
    b.push(0); // absent original name, distinct from a present empty string
    bytes(&mut b, b""); b.push(0); // output name, filename confirmed
    for n in [1i64, 20, 0] { b.extend(n.to_le_bytes()); }
    b.push(0); b.extend(2i32.to_le_bytes()); b.extend(0i32.to_le_bytes());
    b.extend(0u32.to_le_bytes()); b.extend(0u32.to_le_bytes()); // groups/articles
    b
}
fn desired() -> Vec<u8> {
    // Proposed private selected-write encoding: schema1/mode1, exact ordered
    // article identities only. Not a journal schema, never completion evidence.
    let mut b = b"RCWRITE1".to_vec();
    for n in [1u32, 1, 2] { b.extend(n.to_le_bytes()); }
    for (part, id) in [(1i32, b"<article1>".as_slice()), (2i32, b"<article2>".as_slice())] {
        b.extend(part.to_le_bytes()); b.extend(10i32.to_le_bytes()); bytes(&mut b, id);
    }
    b
}
fn request(f: &IssuedFixture) -> RecoveryPrepareRequest {
    RecoveryPrepareRequest {
        producer: ProducerReservationKey { request: f.producers.request,
            publication_sequence: f.producers.publication_sequence, id: f.producers.first },
        owner_kind: 0x46420001, work_kind: 0x00020001,
        mode: InstallMode::ArticlesOnly, schema: 1, parent_ticket: None,
        target: ExactReference::from_record(&f.file),
        dependencies: vec![
            DependencyRequest { reference: ExactReference::from_record(&f.file), role: DependencyRole::InstallTarget, current_preimage: Some(preimage()) },
            DependencyRequest { reference: ExactReference::from_record(&f.collection), role: DependencyRole::ImmutableParent, current_preimage: None },
        ],
        desired_writes: desired(),
    }
}

#[test]
fn prepared_owns_full_reference_mode_schema_and_selected_writes() {
    let f = issued_runtime_fixture(); let input = request(&f);
    let prepared = f.registry.prepare_recovery_work(&input, &f.host).unwrap();
    let v = prepared.view();
    assert_eq!(v.target, &input.target); assert_eq!(v.mode, InstallMode::ArticlesOnly);
    assert_eq!(v.schema, 1); assert_eq!(v.producer_id, f.producers.first);
    assert_eq!(v.desired_writes, input.desired_writes.as_slice());
    assert_eq!(v.dependencies[0].current_preimage, input.dependencies[0].current_preimage);
}
#[test]
fn prepared_deep_copies_current_and_desired_images_before_input_mutation() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    let prepared = f.registry.prepare_recovery_work(&input, &f.host).unwrap();
    let expected = input.dependencies[0].current_preimage.clone(); let writes = input.desired_writes.clone();
    input.dependencies[0].current_preimage.as_mut().unwrap().fill(0); input.desired_writes.fill(0);
    assert_eq!(prepared.view().dependencies[0].current_preimage, expected);
    assert_eq!(prepared.view().desired_writes, writes.as_slice());
}
#[test]
fn prepare_resolves_exact_subject_key_not_latest_equal_binding() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.target.source_record_id[0] ^= 1; input.dependencies[0].reference.source_record_id[0] ^= 1;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::Conflict)));
}
#[test]
fn prepare_rejects_parent_substitution() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.target.parent.as_mut().unwrap().incarnation += 1;
    input.dependencies[0].reference.parent.as_mut().unwrap().incarnation += 1;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::Conflict)));
}
#[test]
fn prepare_requires_actual_namespace_two_reservation() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.producer.request = f.file.reservation_request;
    input.producer.publication_sequence = f.file.reservation_sequence;
    input.producer.id = f.file.binding.incarnation;
    assert!(f.registry.prepare_recovery_work(&input, &f.host).is_err());
}
#[test]
fn prepare_rejects_duplicate_dependency_and_missing_parent_dependency() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.dependencies.push(input.dependencies[0].clone());
    assert!(f.registry.prepare_recovery_work(&input, &f.host).is_err());
    let mut input = request(&f); input.dependencies.pop();
    assert!(f.registry.prepare_recovery_work(&input, &f.host).is_err());
}
#[test]
fn prepare_binds_mode_and_schema_to_current_and_desired_images() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.mode = InstallMode::ArticlesAndProgress;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::InvalidInput)));
    let mut input = request(&f); input.schema = 2;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::Unsupported)));
}
#[test]
fn prepare_rejects_truncated_or_trailing_current_preimage() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.dependencies[0].current_preimage.as_mut().unwrap().pop();
    assert!(f.registry.prepare_recovery_work(&input, &f.host).is_err());
    let mut input = request(&f); input.dependencies[0].current_preimage.as_mut().unwrap().push(0);
    assert!(f.registry.prepare_recovery_work(&input, &f.host).is_err());
}
#[test]
fn prepare_checks_selected_desired_article_identity_against_real_source() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    let last = input.desired_writes.len() - 2; input.desired_writes[last] ^= 1;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::Conflict)));
}
#[test]
fn same_persistent_domain_and_numeric_ids_do_not_transfer_prepared_lifetime() {
    let f = issued_runtime_fixture(); let mut other = issued_runtime_fixture();
    assert_eq!(f.file, other.file); assert_eq!(f.producers, other.producers);
    let mut prepared = f.registry.prepare_recovery_work(&request(&f), &f.host).unwrap();
    let input = request(&other);
    assert!(matches!(other.registry.register_prepared_recovery_work(&mut prepared, &input.dependencies), Err(PurgeError::Conflict)));
}
#[test]
fn unknown_actual_writer_coverage_returns_pending_without_new_work_handle() {
    let mut f = issued_runtime_fixture(); let input = request(&f);
    let mut prepared = f.registry.prepare_recovery_work(&input, &f.host).unwrap();
    let before = f.registry.runtime_observation();
    assert!(matches!(f.registry.register_prepared_recovery_work(&mut prepared, &input.dependencies), Ok(RegisterOutcome::Pending)));
    let after = f.registry.runtime_observation();
    assert_eq!(before.work_tickets, after.work_tickets);
    assert_eq!(before.issued_revision, after.issued_revision);
    assert!(!after.coverage_known); assert!(!prepared.consumed());
}
#[test]
fn pending_retry_retains_same_prepared_and_reservation_without_journal_append() {
    let mut f = issued_runtime_fixture(); let input = request(&f);
    let mut prepared = f.registry.prepare_recovery_work(&input, &f.host).unwrap();
    let frames = f.host.frames.len();
    for _ in 0..2 {
        assert!(matches!(f.registry.register_prepared_recovery_work(&mut prepared, &input.dependencies), Ok(RegisterOutcome::Pending)));
        assert!(!prepared.consumed());
    }
    assert_eq!(f.host.frames.len(), frames);
    let replay = f.registry.reserve_ids(2, f.producers.request, 2, &mut f.host).unwrap();
    assert_eq!(replay, f.producers);
}

#[test]
fn caller_cannot_label_install_target_as_identity_only_to_skip_current_image() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    input.dependencies[0].role = DependencyRole::ImmutableParent;
    input.dependencies[0].current_preimage = None;
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::InvalidInput)));
}
#[test]
fn identity_only_parent_does_not_make_empty_target_preimage_valid() {
    let f = issued_runtime_fixture(); let mut input = request(&f);
    assert_eq!(input.dependencies[1].role, DependencyRole::ImmutableParent);
    assert!(input.dependencies[1].current_preimage.is_none());
    input.dependencies[0].current_preimage = Some(Vec::new());
    assert!(matches!(f.registry.prepare_recovery_work(&input, &f.host), Err(PurgeError::InvalidInput)));
}

#[test]
fn prepare_without_explicit_create_does_not_initialize_runtime_or_append_journal() {
    let f = issued_fixture();
    assert!(!f.registry.runtime_observation().runtime_present);
    let before = f.registry.runtime_observation();
    let frames = f.host.frames.len();
    assert!(matches!(f.registry.prepare_recovery_work(&request(&f), &f.host), Err(PurgeError::Unsupported)));
    assert_eq!(f.registry.runtime_observation(), before);
    assert!(!f.registry.runtime_observation().runtime_present);
    assert_eq!(f.host.frames.len(), frames);
}

#[test]
fn second_create_rejected_without_replacing_first_core_or_prepared_lifetime() {
    let mut f = issued_runtime_fixture();
    let input = request(&f);
    let mut prepared = f.registry.prepare_recovery_work(&input, &f.host).unwrap();
    let before = f.registry.runtime_observation();
    let frames = f.host.frames.len();
    assert!(matches!(f.registry.create_common_runtime(&f.host), Err(PurgeError::Conflict)));
    assert_eq!(f.registry.runtime_observation(), before);
    assert_eq!(f.host.frames.len(), frames);
    // This remains Pending, rather than failing cross-instance correlation:
    // the original Prepared is still bound to the unchanged first core.
    assert!(matches!(f.registry.register_prepared_recovery_work(&mut prepared, &input.dependencies), Ok(RegisterOutcome::Pending)));
    assert!(!prepared.consumed());
    assert_eq!(f.registry.runtime_observation(), before);
}
