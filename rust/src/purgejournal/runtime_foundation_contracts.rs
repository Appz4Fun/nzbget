//! Foundation Source contracts frozen before implementation. UNRUN.
//! Real existing issuer fixture, no caller readiness/worker/fd/Store pin.
use super::runtime_fixture::{issued_fixture, IssuedFixture};
use super::runtime_core::{ExactReference, ProducerReservationKey, InstallMode,
    RecoveryPrepareRequest, DependencyRequest, DependencyRole, RegisterOutcome,
    DestroyOutcome, allocation_fail_after};
use crate::dupepurge::PurgeError;

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
fn foundation_create_is_explicit_open_unknown_and_has_no_work() {
    let mut f=issued_fixture(); let frames=f.host.frames.len();
    assert_eq!(f.registry.runtime_lifetime_observation(),None);
    f.registry.create_common_runtime(&f.host).unwrap();
    let l=f.registry.runtime_lifetime_observation().unwrap();
    assert!(l.root_alive); assert!(!l.closing); assert_eq!(l.prepared_slots,0);
    let o=f.registry.runtime_observation(); assert!(!o.coverage_known);
    assert_eq!(o.work_tickets,0); assert_eq!(o.issued_revision,0);
    assert_eq!(f.host.frames.len(),frames);
}
#[test]
fn foundation_second_create_preserves_prepared_obligation() {
    let mut f=issued_runtime_fixture(); let input=request(&f);
    let prepared=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let before=f.registry.runtime_lifetime_observation();
    assert_eq!(before.unwrap().prepared_slots,1);
    assert_eq!(f.registry.create_common_runtime(&f.host),Err(PurgeError::Conflict));
    assert_eq!(f.registry.runtime_lifetime_observation(),before);
    assert!(prepared.runtime_root_alive()); assert!(!prepared.consumed());
}
#[test]
fn foundation_dropped_prepared_releases_only_its_own_obligation() {
    let f=issued_runtime_fixture(); let input=request(&f); let frames=f.host.frames.len();
    let a=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let b=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,2);
    drop(a); assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,1);
    assert!(!b.consumed()); drop(b);
    assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
    assert_eq!(f.registry.runtime_observation().work_tickets,0);
    assert_eq!(f.host.frames.len(),frames);
}
#[test]
fn foundation_pending_keeps_owned_slot_without_admission_or_journal_write() {
    let mut f=issued_runtime_fixture(); let input=request(&f); let frames=f.host.frames.len();
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let before=f.registry.runtime_lifetime_observation();
    for _ in 0..3 { assert_eq!(f.registry.register_prepared_recovery_work(&mut p,&input.dependencies),Ok(RegisterOutcome::Pending)); }
    assert_eq!(f.registry.runtime_lifetime_observation(),before);assert!(!p.consumed());
    assert_eq!(f.registry.runtime_observation().work_tickets,0);
    assert_eq!(f.registry.runtime_observation().issued_revision,0);
    assert_eq!(f.host.frames.len(),frames);
}
#[test]
fn foundation_explicit_cancel_consumes_once_without_issuing_ticket_or_ack() {
    let mut f=issued_runtime_fixture();let input=request(&f);let frames=f.host.frames.len();
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let writes=p.view().desired_writes.to_vec();
    f.registry.cancel_prepared_recovery_work(&mut p).unwrap();assert!(p.consumed());
    assert_eq!(p.view().desired_writes,writes.as_slice());
    assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
    assert_eq!(f.registry.cancel_prepared_recovery_work(&mut p),Err(PurgeError::Conflict));
    assert_eq!(f.registry.register_prepared_recovery_work(&mut p,&input.dependencies),Err(PurgeError::Conflict));
    drop(p);assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
    assert_eq!(f.host.frames.len(),frames);
}
#[test]
fn foundation_wrong_instance_cannot_cancel_or_consume_prepared() {
    let f=issued_runtime_fixture();let mut other=issued_runtime_fixture();let input=request(&f);
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    assert_eq!(other.registry.cancel_prepared_recovery_work(&mut p),Err(PurgeError::Conflict));
    assert!(!p.consumed());assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,1);
    assert_eq!(other.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
}
#[test]
fn foundation_stale_current_refusal_retains_prepared_and_obligation() {
    let mut f=issued_runtime_fixture();let mut input=request(&f);
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    input.dependencies[0].current_preimage.as_mut().unwrap().push(0);
    assert_eq!(f.registry.register_prepared_recovery_work(&mut p,&input.dependencies),Err(PurgeError::Conflict));
    assert!(!p.consumed());assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,1);
}
#[test]
fn foundation_destroy_pending_closes_admission_but_retains_prepared_bytes() {
    let mut f=issued_runtime_fixture();let input=request(&f);let frames=f.host.frames.len();
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Pending{prepared_slots:1}));
    let l=f.registry.runtime_lifetime_observation().unwrap();assert!(l.root_alive&&l.closing);
    assert!(matches!(f.registry.prepare_recovery_work(&input,&f.host),Err(PurgeError::RecoveryRequired)));
    assert_eq!(f.registry.register_prepared_recovery_work(&mut p,&input.dependencies),Err(PurgeError::RecoveryRequired));
    assert_eq!(p.view().desired_writes,input.desired_writes.as_slice());assert!(!p.consumed());
    assert_eq!(f.host.frames.len(),frames);
    drop(p);assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Destroyed));
    assert_eq!(f.registry.runtime_lifetime_observation(),None);
}
#[test]
fn foundation_cancel_can_release_unadmitted_obligation_while_root_closing() {
    let mut f=issued_runtime_fixture();let input=request(&f);
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Pending{prepared_slots:1}));
    f.registry.cancel_prepared_recovery_work(&mut p).unwrap();assert!(p.consumed());
    assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Destroyed));
    assert!(!p.runtime_root_alive());assert_eq!(p.view().desired_writes,input.desired_writes.as_slice());
}
#[test]
fn foundation_multiple_obligations_prevent_early_destroy() {
    let mut f=issued_runtime_fixture();let input=request(&f);
    let a=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    let b=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Pending{prepared_slots:2}));
    drop(a);assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Pending{prepared_slots:1}));
    assert!(b.runtime_root_alive());drop(b);
    assert_eq!(f.registry.begin_common_runtime_destroy(),Ok(DestroyOutcome::Destroyed));
}
#[test]
fn foundation_registry_drop_revokes_root_presence_without_losing_owned_bytes() {
    let f=issued_runtime_fixture();let input=request(&f);
    let p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    drop(f.registry);assert!(!p.runtime_root_alive());
    assert_eq!(p.view().target,&input.target);assert_eq!(p.view().desired_writes,input.desired_writes.as_slice());
    // This proves Rust-owned bytes only, NOT Store/FileInfo/fd/worker retention.
    drop(p);
}
#[test]
fn foundation_recovery_refusal_keeps_prepared_until_explicit_cancel() {
    let mut f=issued_runtime_fixture();let input=request(&f);
    let mut p=f.registry.prepare_recovery_work(&input,&f.host).unwrap();
    f.registry.recovery_required=true;
    assert_eq!(f.registry.register_prepared_recovery_work(&mut p,&input.dependencies),Err(PurgeError::RecoveryRequired));
    assert!(!p.consumed());f.registry.cancel_prepared_recovery_work(&mut p).unwrap();
    assert!(p.consumed());assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
}
#[test]
fn foundation_create_refusal_gate_does_not_publish_or_initialize() {
    let mut f=issued_fixture();let frames=f.host.frames.len();
    let guard=allocation_fail_after(0);
    assert_eq!(f.registry.create_common_runtime(&f.host),Err(PurgeError::AllocationFailure));
    drop(guard);assert!(!f.registry.runtime_observation().runtime_present);
    assert_eq!(f.host.frames.len(),frames);
    f.registry.create_common_runtime(&f.host).unwrap();
    // Gate before Arc::new: NOT actual allocator-OOM recovery proof.
}
#[test]
fn foundation_each_runtime_allocation_refusal_drops_partial_owned_obligation() {
    let f=issued_runtime_fixture();let input=request(&f);let frames=f.host.frames.len();
    let mut rejected=0;let mut succeeded=false;
    for n in 0..32 {
        let guard=allocation_fail_after(n);
        let result=f.registry.prepare_recovery_work(&input,&f.host);
        drop(guard);
        match result {
            Err(PurgeError::AllocationFailure)=>{rejected+=1;},
            Ok(p)=>{drop(p);succeeded=true;},
            Err(other)=>panic!("unexpected refusal: {other:?}"),
        }
        assert_eq!(f.registry.runtime_lifetime_observation().unwrap().prepared_slots,0);
        assert_eq!(f.registry.runtime_observation().work_tickets,0);
        assert_eq!(f.host.frames.len(),frames);
        if succeeded {break}
    }
    assert!(rejected>=2&&succeeded);
    // Only explicit runtime allocation sites; resolver/OS allocator not injected.
}
