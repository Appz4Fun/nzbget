//! New UNRUN Source-only current-API controls for the next runtime contract.
//! No WorkView/C2/Mode2 admission API is invented by these tests. They pin the
//! present fail-closed boundary using actual existing issuer/resolver methods.
use super::{Registry, Host};
use super::runtime_fixture::{issued_fixture, IssuedFixture};
use super::runtime_core::{ExactReference, ProducerReservationKey, InstallMode,
    RecoveryPrepareRequest, DependencyRequest, DependencyRole, RegisterOutcome};
use crate::dupepurge::PurgeError;

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

fn envelope_with_state(f: &IssuedFixture, state: &[u8]) -> Vec<u8> {
    let original = super::source_codec::Envelope::parse(2, &f.file.original_source_bytes).unwrap();
    let mut out = b"PURGE-SOURCE-BYTES1".to_vec();
    for n in [1u32, 2, 7, original.body.len() as u32] { out.extend(n.to_le_bytes()); }
    out.extend(original.body); out.push(1);
    out.extend(7u32.to_le_bytes()); out.push(0);
    out.extend((state.len() as u32).to_le_bytes()); out.extend(state);
    out
}

#[test]
fn valid_mutable_progress_is_deliberately_not_immutable_identity_authentication() {
    let f = issued_fixture();
    let initial = envelope_with_state(&f,b"0,0\n0,20,0,0,0,0\nfile\n\n\n0\n0\n2\n0,0,0,0,0\n0,0,0,0,0\n#decoded 0,0\n");
    let changed = envelope_with_state(&f,b"1,0\n0,10,0,10,0,0\nfile\n\n\n0\n0\n2\n2,0,10,0,0\n0,0,0,0,0\n#decoded 0,10\n");
    assert_ne!(initial,changed);
    assert_eq!(super::source_codec::project(2,&initial).unwrap(),f.file.immutable_source_bytes);
    assert_eq!(super::source_codec::project(2,&changed).unwrap(),f.file.immutable_source_bytes);
    // Identity equality is intended. It cannot select either mutable image as
    // authenticated desired live progress, prove held filesystem custody, or
    // authorize C2. An owned validated-held staging boundary is still required.
}

#[test]
fn consistent_mode2_headers_without_validated_held_stage_remain_unsupported() {
    let mut f = issued_fixture(); f.registry.create_common_runtime(&f.host).unwrap();
    let mut input = request(&f); input.mode = InstallMode::ArticlesAndProgress;
    input.dependencies[0].current_preimage.as_mut().unwrap()[12..16].copy_from_slice(&2u32.to_le_bytes());
    // Fully defined schema1 CURRENT mode2 tail: zero counters, remaining20,
    // decoded0, absent hash/parset, empty stats and server mapping. This is a
    // current-view byte vector only, not a guessed desired-progress encoding.
    let current = input.dependencies[0].current_preimage.as_mut().unwrap();
    current.extend(0i32.to_le_bytes()); current.extend(0i32.to_le_bytes());
    for n in [20i64,0,0] { current.extend(n.to_le_bytes()); }
    current.extend(0i32.to_le_bytes()); current.extend(0i64.to_le_bytes());
    current.extend([0,0]); current.extend(0u32.to_le_bytes()); current.extend(0u32.to_le_bytes());
    input.desired_writes[12..16].copy_from_slice(&2u32.to_le_bytes());
    let before=f.registry.runtime_observation(); let frames=f.host.frames.len();
    assert!(matches!(f.registry.prepare_recovery_work(&input,&f.host),Err(PurgeError::Unsupported)));
    assert_eq!(f.registry.runtime_observation(),before); assert_eq!(f.host.frames.len(),frames);
    assert!(!before.coverage_known); assert_eq!(before.work_tickets,0);
}

#[test]
fn recovered_real_journal_cannot_transfer_original_prepared_runtime_lifetime() {
    let mut f=issued_fixture(); f.registry.create_common_runtime(&f.host).unwrap();
    let input=request(&f); let mut original=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let mut recovered=Registry::recover(f.file.domain,f.host.journal_identity().unwrap(),&f.host.frames).unwrap();
    assert!(!recovered.runtime_observation().runtime_present);
    let frames=f.host.frames.len(); recovered.create_common_runtime(&f.host).unwrap();
    assert!(!recovered.runtime_observation().coverage_known);
    assert_eq!(recovered.runtime_observation().work_tickets,0);
    assert!(matches!(recovered.register_prepared_recovery_work(&mut original,&input.dependencies),Err(PurgeError::Conflict)));
    assert!(!original.consumed()); assert_eq!(f.host.frames.len(),frames);
    let mut fresh=recovered.prepare_recovery_work(&input,&f.host).unwrap();
    assert!(matches!(recovered.register_prepared_recovery_work(&mut fresh,&input.dependencies),Ok(RegisterOutcome::Pending)));
    assert!(!fresh.consumed()); assert!(!recovered.runtime_observation().coverage_known);
    assert_eq!(recovered.runtime_observation().issued_revision,0);
    assert_eq!(f.host.frames.len(),frames);
}
