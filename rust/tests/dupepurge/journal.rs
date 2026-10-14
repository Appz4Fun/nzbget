//! Durable-state regression tests; fake hosts record real engine boundaries.
//! No daemon, providers, or production paths are accessed.
use nzbget_rs::dupepurge::*;
use nzbget_rs::purgejournal::{decode, encode};

fn binding(id: i32) -> MemberBinding {
    MemberBinding {
        collection_id: id,
        file_id: None,
        incarnation: 100 + id as u64,
        posting_source: format!("source:{id}").into_bytes(),
    }
}
fn fixture(id: i32, path: &[u8]) -> Snapshot {
    let b = binding(id);
    let entry = InventoryEntry {
        id: 1,
        root_id: 1,
        relative_path: path.to_vec(),
        kind: EntryKind::Regular,
        object_identity: b"object-v1:original".to_vec(),
        member: b.clone(),
        namespace_proof_id: [4; 32],
        ownership_receipt_id: [5; 32],
        inventory_revision: 7,
    };
    Snapshot {
        version: 1,
        revision: 7,
        generation: 8,
        seeds: vec![b.clone()],
        members: vec![MemberRecord {
            binding: b.clone(),
            name: b"release".to_vec(),
            key: b"key".to_vec(),
            kind: MemberKind::Queue,
            complete_inventory: true,
            source_validation_id: 1,
        }],
        source_validations: vec![SourceValidation {
            id: 1,
            version: 1,
            validator_version: 1,
            source_record_id: [1; 32],
            source_bytes_digest: [2; 32],
            binding: b.clone(),
            parent_collection: None,
            custody_receipt_id: [3; 32],
        }],
        custody_receipts: vec![CustodyReceipt {
            id: [3; 32],
            validator_version: 1,
            source_record_id: [1; 32],
            source_bytes_digest: [2; 32],
        }],
        parents: vec![],
        comparison_context: ComparisonContext {
            captured: b"C".to_vec(),
            current: b"C".to_vec(),
        },
        comparisons: vec![AnchorComparison {
            seed: b.clone(),
            candidate: b.clone(),
            name_equal: true,
            key_equal: true,
        }],
        direct_bindings: vec![],
        pair_memberships: vec![],
        pair_custody_receipts: vec![],
        roots: vec![RootRecord {
            id: 1,
            descriptor_identity: b"root-v1:one".to_vec(),
            configured_container: false,
        }],
        namespace_proofs: vec![NamespaceProof {
            id: [4; 32],
            root_id: 1,
            relative_path: vec![],
            root_identity: b"root-v1:one".to_vec(),
            ancestor_identity: b"ancestor-v1:one".to_vec(),
            mount_identity: b"mount-v1:one".to_vec(),
            exclusive: false,
        }],
        ownership_receipts: vec![OwnershipReceipt {
            id: entry.ownership_receipt_id,
            member: b,
            root_id: 1,
            relative_path: entry.relative_path.clone(),
            kind: entry.kind,
            object_identity: entry.object_identity.clone(),
            namespace_proof_id: entry.namespace_proof_id,
            inventory_revision: 7,
        }],
        entries: vec![entry],
        outside_claims: vec![],
    }
}
fn plan() -> Plan {
    prepare(fixture(1, b"release/file\xff"), [9; 16]).unwrap()
}

#[test]
fn frame_roundtrip_preserves_raw_inventory_and_request() {
    // Catches losing raw bytes, object identities, or any owned snapshot table.
    let p = plan();
    let bytes = encode(&p).unwrap();
    let recovered = decode(&bytes).unwrap();
    assert_eq!(recovered, p);
    assert_eq!(
        recovered.snapshot.entries[0].relative_path,
        b"release/file\xff"
    );
    assert_eq!(
        recovered.snapshot.entries[0].object_identity,
        b"object-v1:original"
    );
    assert_eq!(recovered.token.request, [9; 16]);
}
#[test]
fn truncated_frame_retained_failure() {
    // No truncated prefix may yield a usable operation or consume the original.
    let bytes = encode(&plan()).unwrap();
    let retained = bytes.clone();
    for n in 0..bytes.len() {
        assert!(decode(&bytes[..n]).is_err(), "accepted prefix {n}");
    }
    assert_eq!(bytes, retained);
    assert!(decode(&bytes).is_ok());
}
#[test]
fn corrupt_or_trailing_frame_never_authorizes_work() {
    let bytes = encode(&plan()).unwrap();
    for n in 0..bytes.len() {
        let mut corrupt = bytes.clone();
        corrupt[n] ^= 0x40;
        assert!(decode(&corrupt).is_err(), "accepted changed byte {n}");
    }
    let mut trailing = bytes;
    trailing.push(0);
    assert!(decode(&trailing).is_err());
}
#[test]
fn frame_payload_bounds_precede_allocation() {
    let mut p = plan();
    p.snapshot.entries[0].relative_path = vec![b'a'; MAX_PATH + 1];
    assert!(encode(&p).is_err());
    let mut p = plan();
    p.token.members[0].posting_source = vec![b'a'; MAX_IDENTITY + 1];
    assert!(encode(&p).is_err());
    assert!(decode(&[255; 64]).is_err());
}

use nzbget_rs::purgejournal::{
    Ack, ArtifactCoverage, ArtifactReceipt, Call, CleanupReceipt, FenceReceipt, Host, Operation,
    Outcome, OwnerBarrier, OwnerCoverage, PersistenceReceipt, PublicationAck, Registry, Request,
    Reservation, StopDisposition, StoreReceipt,
};
#[derive(Default)]
struct TestHost {
    frames: Vec<Vec<u8>>,
    calls: Vec<Operation>,
    fail_publish: bool,
    lose_ack: bool,
    lose_at: Option<usize>,
    stale_barrier: bool,
    substitute: bool,
    fail_step: bool,
    unsupported: bool,
    changed_domain: bool,
    omit_receipt: bool,
    artifact_failed: bool,
    artifact_changed: bool,
    bad_persistence: bool,
    bad_store: bool,
    bad_action_count: bool,
    artifact_wrong_binding: bool,
    last_receipt_budget: usize,
}
fn test_journal_identity() -> [u8; 32] {
    let mut b = [0; 32];
    b[..8].copy_from_slice(b"NZBPJID1");
    b[8] = 1;
    b[16] = 2;
    b[24] = 3;
    b
}
impl Host for TestHost {
    fn journal_identity(&self) -> Result<[u8; 32], PurgeError> {
        let mut b = test_journal_identity();
        if self.changed_domain {
            b[16] ^= 1;
        }
        Ok(b)
    }
    fn supported(&self) -> bool {
        !self.unsupported
    }
    fn publish(&mut self, sequence: u64, frame: &[u8]) -> Result<PublicationAck, PurgeError> {
        let _suspend = SuspendAllocationFailure::new();
        if self.fail_publish {
            return Err(PurgeError::Persistence);
        }
        self.frames.push(frame.to_vec());
        if self.lose_ack || self.lose_at == Some(self.frames.len()) {
            return Err(PurgeError::Persistence);
        }
        Ok(PublicationAck {
            sequence,
            frame: frame.to_vec(),
            file_synced: true,
            published: true,
            directory_synced: true,
        })
    }
    fn execute(&mut self, call: &Call<'_>) -> Result<Ack, PurgeError> {
        let _suspend = SuspendAllocationFailure::new();
        self.calls.push(call.operation);
        self.last_receipt_budget = call.receipt_budget;
        if self.fail_step {
            return Err(PurgeError::HostFailure);
        }
        let owners = call
            .required_owners
            .iter()
            .map(|kind| OwnerBarrier {
                owner_kind: *kind,
                barrier_revision: if self.stale_barrier {
                    call.barrier_revision + 1
                } else {
                    call.barrier_revision
                },
                queued: 0,
                active: 0,
                pinned: 0,
                publication: 0,
                unacknowledged_deltas: 0,
            })
            .collect();
        let outcome = match call.operation {
            Operation::Remove | Operation::Reconcile => {
                if self.substitute {
                    Outcome::IdentityMismatch
                } else {
                    Outcome::Removed
                }
            }
            _ => Outcome::Acknowledged,
        };
        let fence = if call.operation == Operation::Fence && !self.omit_receipt {
            Some(FenceReceipt {
                already_fenced: false,
                dispositions: call
                    .required_owners
                    .iter()
                    .map(|kind| StopDisposition {
                        owner_kind: *kind,
                        barrier_revision: call.barrier_revision,
                        disposition: 1,
                    })
                    .collect(),
            })
        } else {
            None
        };
        let coverage = || {
            call.required_owners
                .iter()
                .map(|kind| OwnerCoverage {
                    owner_kind: *kind,
                    barrier_revision: call.barrier_revision,
                    complete: true,
                })
                .collect()
        };
        let store = || StoreReceipt {
            identity: b"checked-shared-store".to_vec(),
            revision: 1,
            file_synced: true,
            published: true,
            directory_synced: !self.bad_store,
        };
        let cleanup = if call.operation == Operation::Cleanup && !self.omit_receipt {
            Some(CleanupReceipt {
                owners: coverage(),
                coverage: (1..=7)
                    .map(|kind| ArtifactCoverage {
                        kind,
                        count: u32::from(kind == 1),
                        complete: true,
                    })
                    .collect(),
                artifacts: vec![ArtifactReceipt {
                    kind: 1,
                    member: {
                        let mut b = call.identity.token.members[0].clone();
                        if self.artifact_wrong_binding {
                            b.incarnation += 1;
                        }
                        b
                    },
                    identity: if self.artifact_changed {
                        b"replacement".to_vec()
                    } else {
                        b"parsed-cache-original".to_vec()
                    },
                    entry_id: None,
                    outcome: if self.artifact_failed {
                        Outcome::Failed
                    } else {
                        Outcome::Removed
                    },
                    error: if self.artifact_failed {
                        Some(PurgeError::Persistence)
                    } else {
                        None
                    },
                    retained_store: Some(b"checked-shared-store".to_vec()),
                }],
                stores: vec![store()],
            })
        } else {
            None
        };
        let persistence = if call.operation == Operation::PersistRemoval && !self.omit_receipt {
            let j = call.plan.journal.as_ref().unwrap();
            Some(PersistenceReceipt {
                completed_actions: call.plan.actions.len() as u64
                    + u64::from(self.bad_action_count),
                action_receipt_high_water: j
                    .actions
                    .iter()
                    .map(|a| a.receipt_sequence)
                    .max()
                    .unwrap_or(0),
                cleanup_receipt_sequence: j
                    .receipts
                    .iter()
                    .rev()
                    .find(|r| {
                        r.operation == Operation::Cleanup && r.outcome == Outcome::Acknowledged
                    })
                    .unwrap()
                    .receipt_sequence
                    + u64::from(self.bad_persistence),
                owners: coverage(),
                stores: vec![store()],
            })
        } else {
            None
        };
        let outcome =
            if call.operation == Operation::Cleanup && (self.artifact_failed || self.bad_store) {
                Outcome::Failed
            } else {
                outcome
            };
        Ok(Ack {
            identity: call.identity.clone(),
            outcome,
            inventory_revision: call.inventory_revision,
            owners: if call.operation == Operation::Drain {
                owners
            } else {
                Vec::new()
            },
            fence,
            cleanup,
            persistence,
        })
    }
}
fn request(token: u8, id: i32) -> Request {
    Request {
        token: [token; 16],
        seeds: vec![binding(id)],
        policy: 1,
    }
}
fn enroll(host: &mut TestHost) -> (Registry, usize) {
    let mut r = Registry::initialize([8; 16], host).unwrap();
    let Reservation::New(i) = r
        .reserve(request(9, 1), fixture(1, b"release/file"), &[1, 2], host)
        .unwrap()
    else {
        panic!("new operation expected")
    };
    (r, i)
}
fn drive(r: &mut Registry, i: usize, host: &mut TestHost, phase: Phase) {
    for _ in 0..32 {
        if r.plan(i).unwrap().phase == phase {
            return;
        }
        r.advance(i, host).unwrap();
    }
    panic!("phase {phase:?} was not reached");
}
#[test]
fn lost_response_same_token_same_operation() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    let generation = r.plan(i).unwrap().token.generation;
    // A retry is resolved from immutable request before inspecting fresh/reused IDs.
    let mut changed = fixture(1, b"replacement");
    changed.members.clear();
    assert_eq!(
        r.reserve(request(9, 1), changed, &[1, 2], &mut host)
            .unwrap(),
        Reservation::Existing(i)
    );
    assert_eq!(r.plan(i).unwrap().token.generation, generation);
    let mut recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert_eq!(
        recovered
            .reserve(
                request(9, 1),
                fixture(1, b"replacement"),
                &[1, 2],
                &mut host
            )
            .unwrap(),
        Reservation::Existing(i)
    );
    assert_eq!(
        recovered.plan(i).unwrap().snapshot.entries[0].relative_path,
        b"release/file"
    );
}
#[test]
fn changed_request_token_conflict() {
    let mut host = TestHost::default();
    let (mut r, _) = enroll(&mut host);
    let n = host.frames.len();
    assert_eq!(
        r.reserve(request(9, 2), fixture(2, b"other"), &[1, 2], &mut host)
            .unwrap(),
        Reservation::Conflict
    );
    assert_eq!(host.frames.len(), n);
}
#[test]
fn overlapping_namespaces_one_lease() {
    let mut exclusive_host = TestHost::default();
    let mut exclusive = Registry::initialize([8; 16], &mut exclusive_host).unwrap();
    let mut scope = fixture(1, b"release/file");
    scope.namespace_proofs[0].relative_path = b"release".to_vec();
    scope.namespace_proofs[0].exclusive = true;
    assert_eq!(
        exclusive
            .reserve(request(9, 1), scope, &[1, 2], &mut exclusive_host)
            .unwrap(),
        Reservation::New(0)
    );
    assert_eq!(
        exclusive
            .reserve(
                request(10, 2),
                fixture(2, b"release/another"),
                &[1, 2],
                &mut exclusive_host
            )
            .unwrap(),
        Reservation::Conflict
    );
    let mut empty_host = TestHost::default();
    let mut empty_registry = Registry::initialize([8; 16], &mut empty_host).unwrap();
    let mut empty_scope = fixture(1, b"release/file");
    empty_scope.entries.clear();
    empty_scope.ownership_receipts.clear();
    empty_scope.namespace_proofs[0].relative_path.clear();
    empty_scope.namespace_proofs[0].exclusive = true;
    empty_registry
        .reserve(request(9, 1), empty_scope, &[1, 2], &mut empty_host)
        .unwrap();
    assert!(empty_registry.plan(0).unwrap().actions.is_empty());
    let mut alias_scope = fixture(2, b"release/sibling");
    alias_scope.roots[0].id = 99;
    alias_scope.namespace_proofs[0].root_id = 99;
    alias_scope.entries[0].root_id = 99;
    alias_scope.ownership_receipts[0].root_id = 99;
    assert_eq!(
        empty_registry
            .reserve(request(10, 2), alias_scope, &[1, 2], &mut empty_host)
            .unwrap(),
        Reservation::Conflict
    );
    let mut host = TestHost::default();
    let (mut r, _) = enroll(&mut host);
    assert_eq!(
        r.reserve(
            request(10, 2),
            fixture(2, b"release/file/child"),
            &[1, 2],
            &mut host
        )
        .unwrap(),
        Reservation::Conflict
    );
    assert_eq!(
        r.reserve(
            request(11, 2),
            fixture(2, b"unrelated/file"),
            &[1, 2],
            &mut host
        )
        .unwrap(),
        Reservation::New(1)
    );
    let mut alias = fixture(3, b"release/file/child");
    alias.roots[0].id = 99;
    alias.namespace_proofs[0].root_id = 99;
    alias.entries[0].root_id = 99;
    alias.ownership_receipts[0].root_id = 99;
    assert_eq!(
        r.reserve(request(12, 3), alias, &[1, 2], &mut host)
            .unwrap(),
        Reservation::Conflict
    );
    // Unequal opaque root identities do not prove physically disjoint roots.
    let mut unproved = fixture(3, b"different/path");
    unproved.roots[0].descriptor_identity = b"root-v1:possibly-nested".to_vec();
    unproved.namespace_proofs[0].root_identity = b"root-v1:possibly-nested".to_vec();
    assert_eq!(
        r.reserve(request(13, 3), unproved, &[1, 2], &mut host)
            .unwrap(),
        Reservation::Conflict
    );
    let mut recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert_eq!(
        recovered
            .reserve(request(14, 3), fixture(3, b"release"), &[1, 2], &mut host)
            .unwrap(),
        Reservation::Conflict
    );
}
#[test]
fn generation_overflow_no_mutation() {
    // Imported high-water is explicit validated adoption state, never a live-ID scan.
    let mut host = TestHost::default();
    let mut r = Registry::initialize_with_high_water([8; 16], u64::MAX - 1, &mut host).unwrap();
    let n = host.frames.len();
    assert_eq!(
        r.reserve(request(9, 1), fixture(1, b"file"), &[1, 2], &mut host),
        Err(PurgeError::LimitExceeded)
    );
    assert_eq!(host.frames.len(), n);
    assert!(host.calls.is_empty());
}
#[test]
fn intent_failure_never_cancels_or_frees_ambiguous_lease() {
    for lost in [false, true] {
        let mut host = TestHost::default();
        let mut r = Registry::initialize([8; 16], &mut host).unwrap();
        host.fail_publish = !lost;
        host.lose_ack = lost;
        assert!(r
            .reserve(request(9, 1), fixture(1, b"file"), &[1, 2], &mut host)
            .is_err());
        host.fail_publish = false;
        host.lose_ack = false;
        assert!(r
            .reserve(request(10, 1), fixture(1, b"file"), &[1, 2], &mut host)
            .is_err());
        assert!(host.calls.is_empty());
        if lost {
            assert!(matches!(
                Registry::recover([8; 16], test_journal_identity(), &host.frames),
                Err(PurgeError::RecoveryRequired)
            ));
        }
    }
}
#[test]
fn unsupported_host_never_mutates() {
    let mut host = TestHost {
        unsupported: true,
        ..Default::default()
    };
    assert!(Registry::initialize([8; 16], &mut host).is_err());
    assert!(host.frames.is_empty());
    assert!(host.calls.is_empty());
}
#[test]
fn stale_coordinator_barrier_cannot_acknowledge_drain() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    host.stale_barrier = true;
    for _ in 0..8 {
        if r.advance(i, &mut host).is_err() {
            break;
        }
    }
    assert_eq!(r.plan(i).unwrap().phase, Phase::Failed);
    assert!(!host.calls.contains(&Operation::Remove));
    assert!(!host.calls.contains(&Operation::PersistRemoval));
}
#[test]
fn restart_all_seven_phases_preserves_fences_and_identity() {
    for phase in [
        Phase::Prepared,
        Phase::Stopping,
        Phase::Quiescent,
        Phase::Cleaning,
        Phase::Persisting,
        Phase::Complete,
        Phase::Failed,
    ] {
        let mut host = TestHost::default();
        let (mut r, i) = enroll(&mut host);
        if phase == Phase::Failed {
            host.fail_step = true;
            assert!(r.advance(i, &mut host).is_err());
        } else {
            drive(&mut r, i, &mut host, phase);
        }
        let before = encode(r.plan(i).unwrap()).unwrap();
        let recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
        assert_eq!(
            encode(recovered.plan(i).unwrap()).unwrap(),
            before,
            "phase {phase:?}"
        );
        assert_eq!(recovered.plan(i).unwrap().phase, phase);
        assert!(recovered.is_reserved(i)); // complete still needs explicit successful release
    }
}
#[test]
fn pending_action_durable_before_mutation_and_completion_after() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Cleaning);
    host.fail_publish = true;
    assert!(r.advance(i, &mut host).is_err());
    assert!(!host.calls.contains(&Operation::Remove));
}
#[test]
fn old_completed_receipt_never_deletes_replacement() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Persisting);
    let removed = host
        .calls
        .iter()
        .filter(|x| **x == Operation::Remove)
        .count();
    assert_eq!(removed, 1);
    let mut recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    host.substitute = true;
    drive(&mut recovered, i, &mut host, Phase::Complete);
    assert_eq!(
        host.calls
            .iter()
            .filter(|x| **x == Operation::Remove)
            .count(),
        1
    );
    // Receipt only finishes old operation; it never authorizes another unlink.
}
#[test]
fn pending_action_recovery_reconciles_and_retains_substitution() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Cleaning);
    // Persist pending+perform action, then drop the completion ACK response.
    host.lose_ack = true;
    assert!(r.advance(i, &mut host).is_err());
    host.lose_ack = false;
    host.substitute = true;
    let mut recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert!(recovered.advance(i, &mut host).is_err());
    assert_eq!(recovered.plan(i).unwrap().phase, Phase::Failed);
    assert!(recovered.is_reserved(i));
    assert!(!host.calls.contains(&Operation::PersistRemoval));
}
#[test]
fn truncated_or_missing_global_frame_blocks_recovery() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Stopping);
    let mut truncated = host.frames.clone();
    truncated.last_mut().unwrap().pop();
    assert!(Registry::recover([8; 16], test_journal_identity(), &truncated).is_err());
    assert!(Registry::recover([8; 16], test_journal_identity(), &host.frames[1..]).is_err());
    assert!(Registry::recover([7; 16], test_journal_identity(), &host.frames).is_err());
}
#[test]
fn release_requires_durable_complete_and_new_request_incarnation() {
    for lost_ack in [false, true] {
        let mut h = TestHost::default();
        let (mut pending, index) = enroll(&mut h);
        drive(&mut pending, index, &mut h, Phase::Complete);
        h.lose_ack = lost_ack;
        h.fail_publish = !lost_ack;
        assert_eq!(pending.advance(index, &mut h), Err(PurgeError::Persistence));
        assert!(pending.requires_recovery() && pending.is_reserved(index));
        let recovered = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
        assert_eq!(recovered.is_reserved(index), !lost_ack);
    }
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Complete);
    assert!(r.is_reserved(i));
    r.advance(i, &mut host).unwrap();
    assert!(!r.is_reserved(i));
    let mut recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert!(!recovered.is_reserved(i));
    assert_eq!(
        recovered
            .reserve(
                request(9, 1),
                fixture(1, b"replacement"),
                &[1, 2],
                &mut host
            )
            .unwrap(),
        Reservation::Existing(i)
    );
}
#[test]
fn retained_registry_bounds_reject_before_publication() {
    let mut host = TestHost::default();
    let mut r = Registry::initialize([8; 16], &mut host).unwrap();
    let count = host.frames.len();
    let owners: Vec<u32> = (1..=MAX_MEMBERS as u32 + 1).collect();
    assert_eq!(
        r.reserve(request(9, 1), fixture(1, b"file"), &owners, &mut host),
        Err(PurgeError::LimitExceeded)
    );
    assert_eq!(host.frames.len(), count);
    // The complete retained journal is bounded, including duplicate frames.
    let huge: Vec<Vec<u8>> = (0..=nzbget_rs::purgejournal::MAX_FRAMES)
        .map(|_| vec![])
        .collect();
    assert!(Registry::recover([8; 16], test_journal_identity(), &huge).is_err());
}
use nzbget_rs::purgejournal::{InventoryChange, OutputDelta};
fn output_delta() -> OutputDelta {
    let mut e = fixture(1, b"release/new").entries.remove(0);
    e.id = 2;
    e.inventory_revision = 8;
    e.ownership_receipt_id = [6; 32];
    let ownership = OwnershipReceipt {
        id: e.ownership_receipt_id,
        member: e.member.clone(),
        root_id: e.root_id,
        relative_path: e.relative_path.clone(),
        kind: e.kind,
        object_identity: e.object_identity.clone(),
        namespace_proof_id: e.namespace_proof_id,
        inventory_revision: e.inventory_revision,
    };
    OutputDelta {
        producer_ticket: 1,
        sequence: 1,
        prior_inventory_revision: 7,
        changes: vec![InventoryChange {
            entry_id: 2,
            before: None,
            after: Some(e),
            ownership: Some(ownership),
            prior_absent: false,
        }],
        final_for_producer: true,
    }
}
#[test]
fn output_inventory_is_durable_and_tagged_before_cleanup() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    r.store_inventory(binding(1), output_delta(), &mut host)
        .unwrap();
    assert_eq!(&host.frames.last().unwrap()[12..16], &3u32.to_le_bytes());
    assert_eq!(r.plan(i).unwrap().actions.len(), 2);
    // The aggregate revision advances; original receipt provenance does not.
    let stored = r.plan(i).unwrap();
    assert_eq!(stored.snapshot.revision, 8);
    assert_eq!(stored.snapshot.entries[0].inventory_revision, 7);
    assert_eq!(stored.snapshot.ownership_receipts[0].inventory_revision, 7);
    assert_eq!(stored.snapshot.entries[1].inventory_revision, 8);
    let mut roundtrip = decode(&encode(stored).unwrap()).unwrap();
    assert_eq!(&roundtrip, stored);
    // Rewriting both old revision fields cannot invent a new capture receipt.
    roundtrip.snapshot.entries[0].inventory_revision = 8;
    roundtrip.snapshot.ownership_receipts[0].inventory_revision = 8;
    assert!(encode(&roundtrip).is_err());
    let recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert_eq!(recovered.plan(i).unwrap().snapshot.entries.len(), 2);
    assert_eq!(
        recovered
            .plan(i)
            .unwrap()
            .journal
            .as_ref()
            .unwrap()
            .deltas
            .len(),
        1
    );
    drive(&mut r, i, &mut host, Phase::Complete);
    assert_eq!(
        host.calls
            .iter()
            .filter(|x| **x == Operation::Remove)
            .count(),
        2
    );
}
#[test]
fn inventory_replay_is_exact_and_failed_append_fences_destruction() {
    let mut host = TestHost::default();
    let (mut r, _i) = enroll(&mut host);
    r.store_inventory(binding(1), output_delta(), &mut host)
        .unwrap();
    let n = host.frames.len();
    r.store_inventory(binding(1), output_delta(), &mut host)
        .unwrap();
    assert_eq!(host.frames.len(), n);
    let mut changed = output_delta();
    changed.final_for_producer = false;
    assert!(r.store_inventory(binding(1), changed, &mut host).is_err());
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    host.lose_ack = true;
    assert!(r
        .store_inventory(binding(1), output_delta(), &mut host)
        .is_err());
    host.lose_ack = false;
    assert!(r.advance(i, &mut host).is_err());
    assert!(host.calls.is_empty());
    assert!(matches!(
        Registry::recover([8; 16], test_journal_identity(), &host.frames),
        Err(PurgeError::RecoveryRequired)
    ));
}
#[test]
fn inventory_changes_after_quiescence_are_rejected() {
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    drive(&mut r, i, &mut host, Phase::Quiescent);
    let n = host.frames.len();
    assert!(r
        .store_inventory(binding(1), output_delta(), &mut host)
        .is_err());
    assert_eq!(host.frames.len(), n);
}

#[test]
fn every_initial_chunk_cut_is_nonadmitting_and_commit_ack_loss_is_idempotent() {
    let mut input = fixture(1, b"release/file");
    input.members[0].name = vec![b'n'; MAX_IDENTITY];
    input.members[0].key = vec![b'k'; MAX_IDENTITY];
    let mut host = TestHost::default();
    let mut r = Registry::initialize([8; 16], &mut host).unwrap();
    r.reserve(request(9, 1), input, &[1, 2], &mut host).unwrap();
    let total = host.frames.len();
    assert!(total > 4);
    for cut in 2..total {
        assert!(
            matches!(
                Registry::recover([8; 16], test_journal_identity(), &host.frames[..cut]),
                Err(PurgeError::RecoveryRequired)
            ),
            "cut {cut}"
        );
    }
    for cut in 2..=total {
        let mut input = fixture(1, b"release/file");
        input.members[0].name = vec![b'n'; MAX_IDENTITY];
        input.members[0].key = vec![b'k'; MAX_IDENTITY];
        let mut h = TestHost {
            lose_at: Some(cut),
            ..Default::default()
        };
        let mut r = Registry::initialize([8; 16], &mut h).unwrap();
        assert!(r.reserve(request(9, 1), input, &[1, 2], &mut h).is_err());
        assert!(r.requires_recovery());
        assert!(h.calls.is_empty());
        assert_eq!(
            r.reserve(request(9, 1), fixture(1, b"substitute"), &[1, 2], &mut h),
            Err(PurgeError::RecoveryRequired)
        );
        if cut == total {
            let mut recovered =
                Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
            h.lose_at = None;
            assert_eq!(
                recovered
                    .reserve(request(9, 1), fixture(1, b"substitute"), &[1, 2], &mut h)
                    .unwrap(),
                Reservation::Existing(0)
            );
            assert_eq!(recovered.plan(0).unwrap().phase, Phase::Prepared);
        } else {
            assert!(matches!(
                Registry::recover([8; 16], test_journal_identity(), &h.frames),
                Err(PurgeError::RecoveryRequired)
            ));
        }
    }
}
fn many_entries(n: usize) -> Snapshot {
    let mut s = fixture(1, b"release/0");
    let base = s.entries[0].clone();
    let owner = s.ownership_receipts[0].clone();
    s.entries.clear();
    s.ownership_receipts.clear();
    for i in 0..n {
        let mut e = base.clone();
        e.id = i as u64 + 1;
        e.relative_path = format!("release/{i:08}").into_bytes();
        e.ownership_receipt_id = [0; 32];
        e.ownership_receipt_id[..8].copy_from_slice(&e.id.to_le_bytes());
        let mut o = owner.clone();
        o.id = e.ownership_receipt_id;
        o.relative_path = e.relative_path.clone();
        s.entries.push(e);
        s.ownership_receipts.push(o);
    }
    s
}
#[test]
fn batches_preserve_every_identity_across_pending_and_completion_cuts() {
    let mut h = TestHost::default();
    let mut r = Registry::initialize([8; 16], &mut h).unwrap();
    let Reservation::New(i) = r
        .reserve(request(9, 1), many_entries(513), &[1, 2], &mut h)
        .unwrap()
    else {
        panic!()
    };
    drive(&mut r, i, &mut h, Phase::Cleaning);
    let start = h.frames.len();
    h.lose_at = Some(start + 1);
    assert!(r.advance(i, &mut h).is_err());
    assert!(!h.calls.contains(&Operation::Remove));
    let mut r = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
    h.lose_at = None;
    r.advance(i, &mut h).unwrap();
    assert_eq!(
        h.calls
            .iter()
            .filter(|x| **x == Operation::Reconcile)
            .count(),
        256
    );
    let completed = h.frames.len();
    let recovered = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
    assert_eq!(
        recovered
            .plan(i)
            .unwrap()
            .journal
            .as_ref()
            .unwrap()
            .actions
            .iter()
            .filter(|a| a.outcome.is_some())
            .count(),
        256
    );
    h.lose_at = Some(completed + 2);
    assert!(r.advance(i, &mut h).is_err());
    let mut r = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
    h.lose_at = None;
    drive(&mut r, i, &mut h, Phase::Complete);
    assert_eq!(
        h.calls
            .iter()
            .filter(|x| matches!(x, Operation::Remove | Operation::Reconcile))
            .count(),
        513
    );
    assert_eq!(
        r.plan(i)
            .unwrap()
            .journal
            .as_ref()
            .unwrap()
            .actions
            .iter()
            .filter(|a| a.outcome.is_some())
            .count(),
        513
    );
    assert!(h.frames.len() - start < 12);
}

use nzbget_rs::ffi::*;
#[derive(Default)]
struct AbiHost {
    frames: Vec<Vec<u8>>,
    calls: Vec<u32>,
    owners: Vec<PurgeOwnerBarrierC>,
    dispositions: Vec<PurgeStopDispositionC>,
    coverage: Vec<PurgeOwnerCoverageC>,
    kinds: Vec<PurgeArtifactCoverageC>,
    stores: Vec<PurgeStoreReceiptC>,
    fence: Option<PurgeFenceReceiptC>,
    cleanup: Option<PurgeCleanupReceiptC>,
    persistence: Option<PurgePersistenceReceiptC>,
    roots: Vec<Vec<u8>>,
    changed_domain: bool,
    corrupt_ack: bool,
    lose_ack: bool,
}
unsafe extern "C" fn abi_identity(ctx: *mut std::ffi::c_void, out: *mut u8) -> i32 {
    let h = &*ctx.cast::<AbiHost>();
    let mut bytes = test_journal_identity();
    if h.changed_domain {
        bytes[16] ^= 1;
    }
    std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, 32);
    0
}
unsafe extern "C" fn abi_publish(
    ctx: *mut std::ffi::c_void,
    sequence: u64,
    bytes: PurgeBytesC,
    out: *mut PurgePublicationAckC,
) -> i32 {
    let _suspend = SuspendAllocationFailure::new();
    let h = &mut *ctx.cast::<AbiHost>();
    h.frames
        .push(std::slice::from_raw_parts(bytes.data, bytes.len as usize).to_vec());
    if h.lose_ack {
        return 8;
    }
    out.write(PurgePublicationAckC {
        version: 1,
        struct_size: std::mem::size_of::<PurgePublicationAckC>() as u32,
        sequence,
        frame: bytes,
        file_synced: 1,
        published: 1,
        directory_synced: 1,
    });
    0
}
unsafe extern "C" fn abi_execute(
    ctx: *mut std::ffi::c_void,
    call: *const PurgeCallC,
    out: *mut PurgeAckC,
) -> i32 {
    let _suspend = SuspendAllocationFailure::new();
    let h = &mut *ctx.cast::<AbiHost>();
    let c = &*call;
    h.calls.push(c.operation);
    h.owners.clear();
    for kind in std::slice::from_raw_parts(c.required_owners, c.required_owners_count as usize) {
        h.owners.push(PurgeOwnerBarrierC {
            owner_kind: *kind,
            barrier_revision: c.barrier_revision,
            queued: 0,
            active: 0,
            pinned: 0,
            publication: 0,
            unacknowledged_deltas: 0,
        });
    }
    h.dispositions.clear();
    h.coverage.clear();
    h.kinds.clear();
    h.stores.clear();
    h.fence = None;
    h.cleanup = None;
    h.persistence = None;
    for o in &h.owners {
        h.dispositions.push(PurgeStopDispositionC {
            owner_kind: o.owner_kind,
            barrier_revision: o.barrier_revision,
            disposition: 1,
        });
        h.coverage.push(PurgeOwnerCoverageC {
            owner_kind: o.owner_kind,
            barrier_revision: o.barrier_revision,
            complete: 1,
        });
    }
    for kind in 1..=7 {
        h.kinds.push(PurgeArtifactCoverageC {
            kind,
            count: 0,
            complete: 1,
        });
    }
    h.stores.push(PurgeStoreReceiptC {
        identity: PurgeBytesC {
            data: b"queue-history".as_ptr(),
            len: 13,
        },
        revision: 1,
        file_synced: 1,
        published: 1,
        directory_synced: 1,
    });
    if c.operation == 1 {
        h.fence = Some(PurgeFenceReceiptC {
            already_fenced: 0,
            dispositions: h.dispositions.as_ptr(),
            dispositions_count: h.dispositions.len() as u32,
        });
    }
    if c.operation == 6 {
        h.cleanup = Some(PurgeCleanupReceiptC {
            owners: h.coverage.as_ptr(),
            owners_count: h.coverage.len() as u32,
            coverage: h.kinds.as_ptr(),
            coverage_count: h.kinds.len() as u32,
            artifacts: std::ptr::null(),
            artifacts_count: 0,
            stores: h.stores.as_ptr(),
            stores_count: 1,
        });
    }
    if c.operation == 7 {
        h.persistence = Some(PurgePersistenceReceiptC {
            completed_actions: c.completed_actions,
            action_receipt_high_water: c.action_receipt_high_water,
            cleanup_receipt_sequence: c.cleanup_receipt_sequence,
            owners: h.coverage.as_ptr(),
            owners_count: h.coverage.len() as u32,
            stores: h.stores.as_ptr(),
            stores_count: 1,
        });
    }
    if c.action.present == 1 {
        if c.root_descriptor_identity.len == 0 || c.root_descriptor_identity.data.is_null() {
            return 9;
        }
        h.roots.push(
            std::slice::from_raw_parts(
                c.root_descriptor_identity.data,
                c.root_descriptor_identity.len as usize,
            )
            .to_vec(),
        );
    }
    let mut identity = c.identity;
    if h.corrupt_ack {
        identity.generation += 1;
    }
    out.write(PurgeAckC {
        version: 1,
        struct_size: std::mem::size_of::<PurgeAckC>() as u32,
        identity,
        outcome: if matches!(c.operation, 4 | 5) { 1 } else { 0 },
        inventory_revision: c.inventory_revision,
        owners: h.owners.as_ptr(),
        owners_count: if c.operation == 2 {
            h.owners.len() as u32
        } else {
            0
        },
        fence: h
            .fence
            .as_ref()
            .map(|v| v as *const _)
            .unwrap_or(std::ptr::null()),
        cleanup: h
            .cleanup
            .as_ref()
            .map(|v| v as *const _)
            .unwrap_or(std::ptr::null()),
        persistence: h
            .persistence
            .as_ref()
            .map(|v| v as *const _)
            .unwrap_or(std::ptr::null()),
    });
    0
}
fn abi_ops(h: &mut AbiHost, owners: &[u32]) -> PurgeHostOpsC {
    PurgeHostOpsC {
        version: 1,
        struct_size: std::mem::size_of::<PurgeHostOpsC>() as u32,
        registry: std::ptr::null_mut(),
        context: (h as *mut AbiHost).cast(),
        capabilities: 1,
        journal_identity: Some(abi_identity),
        publish: Some(abi_publish),
        execute: Some(abi_execute),
        required_owners: owners.as_ptr(),
        required_owners_count: owners.len() as u32,
    }
}
#[test]
fn abi_missing_registry_or_publication_cannot_cancel() {
    unsafe {
        let mut h = AbiHost::default();
        let owners = [1, 2];
        let mut ops = abi_ops(&mut h, &owners);
        let p = plan();
        let mut status: PurgeStatusC = std::mem::zeroed();
        let mut error = 0;
        assert_eq!(
            nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
            11
        );
        assert!(h.calls.is_empty());
        assert!(h.frames.is_empty());
        ops.publish = None;
        let mut registry = std::ptr::null_mut();
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut registry),
            6
        );
        assert!(registry.is_null());
        ops.publish = Some(abi_publish);
        ops.journal_identity = None;
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut registry),
            6
        );
        assert!(registry.is_null());
        assert!(h.frames.is_empty());
        ops.journal_identity = Some(abi_identity);
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut registry),
            0
        );
        ops.registry = registry;
        ops.publish = None;
        assert_eq!(
            nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
            6
        );
        assert!(h.calls.is_empty());
        assert_eq!(h.frames.len(), 1);
        nzbget_rs_purge_registry_destroy(registry);
    }
}
#[test]
fn abi_tick_retains_full_ack_identity_and_release_status() {
    unsafe {
        let mut h = AbiHost::default();
        let owners = [1, 2];
        let mut ops = abi_ops(&mut h, &owners);
        let p = plan();
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut ops.registry),
            0
        );
        let mut status: PurgeStatusC = std::mem::zeroed();
        let mut error = 0;
        for _ in 0..16 {
            assert_eq!(
                nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
                0
            );
            if status.phase == 5 {
                break;
            }
        }
        assert_eq!(status.phase, 5);
        assert_eq!(h.roots, vec![b"root-v1:one".to_vec()]);
        assert_eq!(status.released, 0);
        assert_eq!(status.generation, 1);
        assert_eq!(
            nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
            0
        );
        assert_eq!(status.released, 1);
        let frames: Vec<PurgeBytesC> = h
            .frames
            .iter()
            .map(|b| PurgeBytesC {
                data: b.as_ptr(),
                len: b.len() as u32,
            })
            .collect();
        let mut recovered = std::ptr::null_mut();
        assert_eq!(
            nzbget_rs_purge_registry_recover(
                [8; 16].as_ptr(),
                frames.as_ptr(),
                frames.len() as u32,
                0,
                &ops,
                &mut recovered
            ),
            1
        );
        let previous_registry = ops.registry;
        assert_eq!(
            nzbget_rs_purge_registry_recover(
                [8; 16].as_ptr(),
                frames.as_ptr(),
                frames.len() as u32,
                1,
                &ops,
                &mut ops.registry
            ),
            0
        );
        nzbget_rs_purge_registry_destroy(previous_registry);
        let n = h.calls.len();
        assert_eq!(
            nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
            0
        );
        assert_eq!(status.released, 1);
        assert_eq!(h.calls.len(), n);
        nzbget_rs_purge_registry_destroy(ops.registry);
    }
}
#[test]
fn abi_lost_publication_and_stale_identity_never_start_cleanup() {
    unsafe {
        for corrupt in [false, true] {
            let mut h = AbiHost::default();
            let owners = [1, 2];
            let mut ops = abi_ops(&mut h, &owners);
            let p = plan();
            assert_eq!(
                nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut ops.registry),
                0
            );
            h.lose_ack = !corrupt;
            h.corrupt_ack = corrupt;
            let mut status: PurgeStatusC = std::mem::zeroed();
            let mut error = 0;
            assert_ne!(
                nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
                0
            );
            assert!(!h.calls.iter().any(|op| matches!(op, 4 | 5 | 6 | 7 | 8)));
            if !corrupt {
                assert!(h.calls.is_empty());
                assert_eq!(status.recovery_required, 1);
            } else {
                assert_eq!(status.phase, 6);
                assert_eq!(status.error, 4);
            }
            nzbget_rs_purge_registry_destroy(ops.registry);
        }
    }
}
#[test]
fn abi_inventory_validates_bounds_and_requires_durable_publication() {
    unsafe {
        let mut h = AbiHost::default();
        let owners = [1, 2];
        let mut ops = abi_ops(&mut h, &owners);
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut ops.registry),
            0
        );
        let b = binding(1);
        let binding = PurgeBindingC {
            collection_id: b.collection_id,
            file_id: 0,
            has_file: 0,
            incarnation: b.incarnation,
            posting_source: PurgeBytesC {
                data: b.posting_source.as_ptr(),
                len: b.posting_source.len() as u32,
            },
        };
        let mut delta = PurgeOutputDeltaC {
            version: 1,
            struct_size: std::mem::size_of::<PurgeOutputDeltaC>() as u32,
            producer_ticket: 1,
            sequence: 1,
            prior_inventory_revision: 7,
            changes: std::ptr::null(),
            changes_count: MAX_ENTRIES as u32 + 1,
            final_for_producer: 1,
        };
        let mut error = 0;
        assert_eq!(
            nzbget_rs_purge_inventory_store(&binding, &delta, &ops, &mut error),
            5
        );
        assert_eq!(h.frames.len(), 1);
        delta.changes_count = 0;
        h.lose_ack = true;
        assert_eq!(
            nzbget_rs_purge_inventory_store(&binding, &delta, &ops, &mut error),
            8
        );
        h.lose_ack = false;
        assert_eq!(
            nzbget_rs_purge_inventory_store(&binding, &delta, &ops, &mut error),
            11
        );
        nzbget_rs_purge_registry_destroy(ops.registry);
    }
}

// Genuine allocator failures, scoped to this test thread. Host fixture storage
// is outside the Rust engine allocation contract and is explicitly suspended.
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
thread_local! {
    static ALLOC_FAIL:Cell<usize>=const{Cell::new(usize::MAX)};
    static ALLOC_COUNT:Cell<usize>=const{Cell::new(0)};
}
struct CheckedAllocator;
fn fail_allocation() -> bool {
    ALLOC_FAIL.with(|limit| {
        if limit.get() == usize::MAX {
            return false;
        }
        ALLOC_COUNT.with(|count| {
            let n = count.get();
            count.set(n + 1);
            n == limit.get()
        })
    })
}
unsafe impl GlobalAlloc for CheckedAllocator {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        if fail_allocation() {
            std::ptr::null_mut()
        } else {
            System.alloc(l)
        }
    }
    unsafe fn alloc_zeroed(&self, l: Layout) -> *mut u8 {
        if fail_allocation() {
            std::ptr::null_mut()
        } else {
            System.alloc_zeroed(l)
        }
    }
    unsafe fn realloc(&self, p: *mut u8, l: Layout, n: usize) -> *mut u8 {
        if fail_allocation() {
            std::ptr::null_mut()
        } else {
            System.realloc(p, l, n)
        }
    }
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        System.dealloc(p, l)
    }
}
#[global_allocator]
static ALLOCATOR: CheckedAllocator = CheckedAllocator;
struct SuspendAllocationFailure(usize);
impl SuspendAllocationFailure {
    fn new() -> Self {
        Self(ALLOC_FAIL.with(|v| v.replace(usize::MAX)))
    }
}
impl Drop for SuspendAllocationFailure {
    fn drop(&mut self) {
        ALLOC_FAIL.with(|v| v.set(self.0));
    }
}
fn allocation_probe<T>(nth: usize, f: impl FnOnce() -> T) -> (T, usize) {
    ALLOC_COUNT.with(|v| v.set(0));
    ALLOC_FAIL.with(|v| v.set(nth));
    let result = f();
    ALLOC_FAIL.with(|v| v.set(usize::MAX));
    (result, ALLOC_COUNT.with(Cell::get))
}
#[test]
fn genuine_allocation_failures_are_errors_in_codec_registry_recovery_and_tick() {
    for stage in 0..6 {
        let run = |nth| {
            let mut h = TestHost::default();
            let p = plan();
            let bytes = encode(&p).unwrap();
            let (mut r, i) = enroll(&mut h);
            let input = fixture(2, b"other/file");
            let req = request(10, 2);
            let delta = output_delta();
            let b = binding(1);
            allocation_probe(nth, || match stage {
                0 => encode(&p).map(|_| ()),
                1 => decode(&bytes).map(|_| ()),
                2 => r.reserve(req, input, &[1, 2], &mut h).map(|_| ()),
                3 => Registry::recover([8; 16], test_journal_identity(), &h.frames).map(|_| ()),
                4 => r.advance(i, &mut h).map(|_| ()),
                _ => r.store_inventory(b, delta, &mut h),
            })
        };
        let (baseline, count) = run(usize::MAX - 1);
        assert!(baseline.is_ok(), "stage {stage}: {baseline:?}");
        assert!(count > 0);
        for nth in 0..count {
            let (result, _) = run(nth);
            assert!(
                matches!(result, Err(PurgeError::AllocationFailure)),
                "stage {stage}, allocation {nth}: {result:?}"
            );
        }
    }
}

#[test]
fn accepted_snapshot_terms_fit_composed_initialization_and_completion_bounds() {
    use nzbget_rs::purgejournal::{
        ActionReceipt, JournalState, Receipt, ACTION_BATCH, CHUNK_BYTES, MAX_FRAMES,
        MAX_OPERATION_BYTES,
    };
    use std::mem::size_of;
    assert!(size_of::<MemberBinding>() <= size_of::<MemberRecord>());
    assert!(size_of::<Action>() + size_of::<ActionReceipt>() <= 2 * size_of::<InventoryEntry>());
    assert!(4 + 4 + 1 + 8 + 4 <= size_of::<MemberBinding>());
    let overhead = size_of::<Plan>()
        + size_of::<JournalState>()
        + 64
        + 6 * size_of::<Receipt>()
        + MAX_MEMBERS * (size_of::<u32>() + size_of::<OwnerBarrier>());
    assert!(4 * MAX_PAYLOAD + overhead < MAX_OPERATION_BYTES);
    let records = 1
        + MAX_OPERATION_BYTES.div_ceil(CHUNK_BYTES)
        + 1
        + 2 * MAX_ENTRIES.div_ceil(ACTION_BATCH)
        + MAX_PAYLOAD.div_ceil(CHUNK_BYTES)
        + 12;
    assert!(records < MAX_FRAMES);
    assert!(decode(&vec![0; MAX_PAYLOAD + 1]).is_err());
}

#[test]
fn missing_stop_dispositions_or_scoped_cleanup_never_acknowledges_progress() {
    let mut h = TestHost::default();
    let (mut r, i) = enroll(&mut h);
    h.omit_receipt = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert_eq!(r.plan(i).unwrap().phase, Phase::Failed);
    assert!(!h.calls.contains(&Operation::Drain));
    let mut h = TestHost::default();
    let (mut r, i) = enroll(&mut h);
    drive(&mut r, i, &mut h, Phase::Cleaning);
    r.advance(i, &mut h).unwrap();
    h.omit_receipt = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert!(!h.calls.contains(&Operation::PersistRemoval));
}
#[test]
fn failed_artifact_outcomes_survive_restart_and_reject_substitution_on_retry() {
    let mut h = TestHost::default();
    let (mut r, i) = enroll(&mut h);
    drive(&mut r, i, &mut h, Phase::Cleaning);
    r.advance(i, &mut h).unwrap();
    h.artifact_failed = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::HostFailure));
    let mut r = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
    let j = r.plan(i).unwrap().journal.as_ref().unwrap();
    let receipt = j.receipts.iter().find_map(|v| v.cleanup.as_ref()).unwrap();
    assert_eq!(receipt.artifacts[0].outcome, Outcome::Failed);
    assert_eq!(receipt.artifacts[0].identity, b"parsed-cache-original");
    assert!(r.is_reserved(i));
    h.artifact_failed = false;
    r.retry(i, &mut h).unwrap();
    h.artifact_changed = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert!(!h.calls.contains(&Operation::PersistRemoval));
}
#[test]
fn persistence_must_bind_completed_actions_and_exact_durable_cleanup_receipt() {
    let mut h = TestHost::default();
    let (mut r, i) = enroll(&mut h);
    drive(&mut r, i, &mut h, Phase::Persisting);
    h.bad_persistence = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert!(r.is_reserved(i));
    assert!(!h.calls.contains(&Operation::Release));
    let recovered = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
    assert_eq!(recovered.plan(i).unwrap().phase, Phase::Failed);
}

#[test]
fn registry_handle_allocation_failure_precedes_any_publication() {
    unsafe {
        let mut h = AbiHost::default();
        let owners = [1, 2];
        let ops = abi_ops(&mut h, &owners);
        let mut out = std::ptr::null_mut();
        let (code, _) = allocation_probe(0, || {
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut out)
        });
        assert_eq!(code, 7);
        assert!(out.is_null());
        assert!(h.frames.is_empty());
        assert!(h.calls.is_empty());
    }
}

#[test]
fn cleanup_retains_failed_shared_store_publication_and_rejects_new_incarnation() {
    for wrong_binding in [false, true] {
        let mut h = TestHost::default();
        let (mut r, i) = enroll(&mut h);
        drive(&mut r, i, &mut h, Phase::Cleaning);
        r.advance(i, &mut h).unwrap();
        h.bad_store = !wrong_binding;
        h.artifact_wrong_binding = wrong_binding;
        assert_eq!(
            r.advance(i, &mut h),
            Err(if wrong_binding {
                PurgeError::Conflict
            } else {
                PurgeError::HostFailure
            })
        );
        assert!(!h.calls.contains(&Operation::PersistRemoval));
        let r = Registry::recover([8; 16], test_journal_identity(), &h.frames).unwrap();
        assert!(r.is_reserved(i));
        if !wrong_binding {
            assert!(
                !r.plan(i)
                    .unwrap()
                    .journal
                    .as_ref()
                    .unwrap()
                    .receipts
                    .iter()
                    .find_map(|r| r.cleanup.as_ref())
                    .unwrap()
                    .stores[0]
                    .directory_synced
            );
        }
    }
}
#[test]
fn persistence_rejects_wrong_action_count_and_unsynced_queue_publication() {
    for wrong_count in [false, true] {
        let mut h = TestHost::default();
        let (mut r, i) = enroll(&mut h);
        drive(&mut r, i, &mut h, Phase::Persisting);
        h.bad_store = !wrong_count;
        h.bad_action_count = wrong_count;
        assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
        assert!(!h.calls.contains(&Operation::Release));
        assert!(r.is_reserved(i));
    }
}

#[test]
fn actual_journal_descriptor_identity_binds_admission_recovery_and_every_host_boundary() {
    let mut h = TestHost::default();
    let (mut r, i) = enroll(&mut h);
    let frames = h.frames.len();
    h.changed_domain = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert!(h.calls.is_empty());
    assert_eq!(h.frames.len(), frames);
    let mut other = test_journal_identity();
    other[16] ^= 1;
    assert!(matches!(
        Registry::recover([8; 16], other, &h.frames),
        Err(PurgeError::CorruptJournal)
    ));
    h.changed_domain = false;
    r.advance(i, &mut h).unwrap();
    h.changed_domain = true;
    assert_eq!(r.advance(i, &mut h), Err(PurgeError::Conflict));
    assert_eq!(h.calls, vec![Operation::Fence]);
}
#[test]
fn abi_rejects_actual_descriptor_context_change_before_cancel_or_publication() {
    unsafe {
        let mut h = AbiHost::default();
        let owners = [1, 2];
        let mut ops = abi_ops(&mut h, &owners);
        let p = plan();
        assert_eq!(
            nzbget_rs_purge_registry_create([8; 16].as_ptr(), &ops, &mut ops.registry),
            0
        );
        h.changed_domain = true;
        let mut status: PurgeStatusC = std::mem::zeroed();
        let mut error = 0;
        assert_eq!(
            nzbget_rs_purge_tick((&p as *const Plan).cast(), &ops, 0, &mut status, &mut error),
            4
        );
        assert!(h.calls.is_empty());
        assert_eq!(h.frames.len(), 1);
        nzbget_rs_purge_registry_destroy(ops.registry);
    }
}

#[test]
fn late_inventory_cannot_acquire_another_operations_lease() {
    let mut host = TestHost::default();
    let (mut registry, first) = enroll(&mut host);
    assert_eq!(
        registry
            .reserve(
                request(10, 2),
                fixture(2, b"release/new"),
                &[1, 2],
                &mut host
            )
            .unwrap(),
        Reservation::New(1)
    );
    let frames = host.frames.len();
    assert_eq!(
        registry.store_inventory(binding(1), output_delta(), &mut host),
        Err(PurgeError::Conflict)
    );
    assert_eq!(host.frames.len(), frames);
    assert!(host.calls.is_empty());
    assert!(registry.is_reserved(first) && registry.is_reserved(1));
    assert_eq!(registry.plan(first).unwrap().snapshot.entries.len(), 1);
    let recovered = Registry::recover([8; 16], test_journal_identity(), &host.frames).unwrap();
    assert!(recovered.is_reserved(first) && recovered.is_reserved(1));
    let mut valid = output_delta();
    valid.changes[0].after.as_mut().unwrap().relative_path = b"release/safe".to_vec();
    valid.changes[0].ownership.as_mut().unwrap().relative_path = b"release/safe".to_vec();
    registry
        .store_inventory(binding(1), valid, &mut host)
        .unwrap();
    assert_eq!(registry.plan(first).unwrap().snapshot.entries.len(), 2);
}

#[test]
fn readiness_budget_includes_complete_acknowledgment_token_envelope() {
    assert!(std::mem::size_of::<PurgeBindingC>() <= 128);
    assert!(std::mem::size_of::<MemberBinding>() <= 128);
    assert!(std::mem::size_of::<PurgeAckC>() <= 1024);
    assert!(std::mem::size_of::<Ack>() <= 1024);
    let mut host = TestHost::default();
    let mut snapshot = fixture(1, b"release/file");
    let mut large = binding(1);
    large.posting_source = vec![b'x'; MAX_IDENTITY];
    snapshot.seeds[0] = large.clone();
    snapshot.members[0].binding = large.clone();
    snapshot.source_validations[0].binding = large.clone();
    snapshot.comparisons[0].seed = large.clone();
    snapshot.comparisons[0].candidate = large.clone();
    snapshot.entries[0].member = large.clone();
    snapshot.ownership_receipts[0].member = large.clone();
    for id in 2..=64 {
        let mut b = large.clone();
        b.collection_id = id;
        b.incarnation = 100 + id as u64;
        let mut member = snapshot.members[0].clone();
        member.binding = b.clone();
        member.source_validation_id = id as u64;
        let mut validation = snapshot.source_validations[0].clone();
        validation.id = id as u64;
        validation.binding = b.clone();
        validation.source_record_id = [id as u8; 32];
        validation.custody_receipt_id = [128 + id as u8; 32];
        let mut custody = snapshot.custody_receipts[0].clone();
        custody.id = validation.custody_receipt_id;
        custody.source_record_id = validation.source_record_id;
        snapshot.members.push(member);
        snapshot.source_validations.push(validation);
        snapshot.custody_receipts.push(custody);
        snapshot.comparisons.push(AnchorComparison {
            seed: large.clone(),
            candidate: b,
            name_equal: true,
            key_equal: true,
        });
    }
    let mut registry = Registry::initialize([8; 16], &mut host).unwrap();
    assert_eq!(
        registry
            .reserve(
                Request {
                    token: [9; 16],
                    seeds: vec![large],
                    policy: 1
                },
                snapshot,
                &[1, 2],
                &mut host
            )
            .unwrap(),
        Reservation::New(0)
    );
    let i = 0;

    drive(&mut registry, i, &mut host, Phase::Cleaning);
    let members = &registry.plan(i).unwrap().token.members;
    let envelope = 1024
        + members
            .iter()
            .map(|b| 128 + b.posting_source.len())
            .sum::<usize>();
    assert_eq!(members.len(), 64);
    assert!(envelope > 4 * 1024 * 1024);
    assert!(host.last_receipt_budget <= MAX_PAYLOAD - envelope);
    let worst_envelope = 1024 + 128 * MAX_MEMBERS + MAX_PAYLOAD / 2;
    let mandatory = MAX_MEMBERS
        * (std::mem::size_of::<StopDisposition>()
            + std::mem::size_of::<OwnerBarrier>()
            + 2 * std::mem::size_of::<OwnerCoverage>())
        + 4096;
    assert!(mandatory < MAX_PAYLOAD - worst_envelope);
    drive(&mut registry, i, &mut host, Phase::Complete);
    registry.advance(i, &mut host).unwrap();
    assert!(!registry.is_reserved(i));
}

#[test]
fn composed_inventory_preserves_receipt_lineage_across_rename_empty_and_retire() {
    use nzbget_rs::purgejournal::{MAX_COMPOSED_WORKSPACE, MAX_OPERATION_BYTES};
    let mut host = TestHost::default();
    let (mut r, i) = enroll(&mut host);
    r.store_inventory(binding(1), output_delta(), &mut host)
        .unwrap();
    let before = r
        .plan(i)
        .unwrap()
        .snapshot
        .entries
        .iter()
        .find(|e| e.id == 2)
        .unwrap()
        .clone();
    let mut after = before.clone();
    after.relative_path = b"release/renamed".to_vec();
    after.inventory_revision = 9;
    after.ownership_receipt_id = [7; 32];
    let ownership = OwnershipReceipt {
        id: after.ownership_receipt_id,
        member: after.member.clone(),
        root_id: after.root_id,
        relative_path: after.relative_path.clone(),
        kind: after.kind,
        object_identity: after.object_identity.clone(),
        namespace_proof_id: after.namespace_proof_id,
        inventory_revision: after.inventory_revision,
    };
    r.store_inventory(
        binding(1),
        OutputDelta {
            producer_ticket: 2,
            sequence: 1,
            prior_inventory_revision: 8,
            changes: vec![InventoryChange {
                entry_id: 2,
                before: Some(before),
                after: Some(after),
                ownership: Some(ownership),
                prior_absent: true,
            }],
            final_for_producer: false,
        },
        &mut host,
    )
    .unwrap();
    r.store_inventory(
        binding(1),
        OutputDelta {
            producer_ticket: 2,
            sequence: 2,
            prior_inventory_revision: 9,
            changes: vec![],
            final_for_producer: true,
        },
        &mut host,
    )
    .unwrap();
    let before = r
        .plan(i)
        .unwrap()
        .snapshot
        .entries
        .iter()
        .find(|e| e.id == 1)
        .unwrap()
        .clone();
    assert_eq!(before.inventory_revision, 7);
    r.store_inventory(
        binding(1),
        OutputDelta {
            producer_ticket: 3,
            sequence: 1,
            prior_inventory_revision: 10,
            changes: vec![InventoryChange {
                entry_id: 1,
                before: Some(before),
                after: None,
                ownership: None,
                prior_absent: true,
            }],
            final_for_producer: true,
        },
        &mut host,
    )
    .unwrap();
    let p = r.plan(i).unwrap();
    assert_eq!(p.snapshot.revision, 11);
    assert_eq!(p.snapshot.entries.len(), 1);
    assert_eq!(p.snapshot.entries[0].inventory_revision, 9);
    assert_eq!(p.actions.len(), 1);
    let bytes = encode(p).unwrap();
    assert_eq!(decode(&bytes).unwrap(), *p);
    assert_eq!(
        Registry::recover([8; 16], test_journal_identity(), &host.frames)
            .unwrap()
            .plan(i),
        Some(p)
    );
    for damage in 0..5 {
        let mut broken = decode(&bytes).unwrap();
        let deltas = &mut broken.journal.as_mut().unwrap().deltas;
        match damage {
            0 => deltas[1].delta.prior_inventory_revision -= 1,
            1 => deltas[2].delta.sequence += 1,
            2 => deltas[1].delta.final_for_producer = true,
            3 => deltas[1].delta.changes[0]
                .after
                .as_mut()
                .unwrap()
                .object_identity
                .push(b'x'),
            _ => deltas[1].delta.changes[0]
                .ownership
                .as_mut()
                .unwrap()
                .object_identity
                .push(b'x'),
        }
        assert!(encode(&broken).is_err(), "composed lineage damage {damage}");
    }
    assert_eq!(
        MAX_COMPOSED_WORKSPACE,
        2 * MAX_OPERATION_BYTES + 2 * MAX_PAYLOAD
    );
}

#[test]
fn composed_inventory_revision_is_global_across_interleaved_members() {
    let mut snapshot = fixture(1, b"release/first");
    let mut second = fixture(2, b"release/second");
    second.members[0].source_validation_id = 2;
    second.source_validations[0].id = 2;
    second.source_validations[0].source_record_id = [8; 32];
    second.source_validations[0].custody_receipt_id = [9; 32];
    second.custody_receipts[0].id = [9; 32];
    second.custody_receipts[0].source_record_id = [8; 32];
    second.entries[0].id = 3;
    second.entries[0].ownership_receipt_id = [8; 32];
    second.ownership_receipts[0].id = [8; 32];
    snapshot.members.extend(second.members);
    snapshot
        .source_validations
        .extend(second.source_validations);
    snapshot.custody_receipts.extend(second.custody_receipts);
    snapshot.entries.extend(second.entries);
    snapshot
        .ownership_receipts
        .extend(second.ownership_receipts);
    snapshot.comparisons.push(AnchorComparison {
        seed: binding(1),
        candidate: binding(2),
        name_equal: false,
        key_equal: true,
    });
    let mut host = TestHost::default();
    let mut r = Registry::initialize([8; 16], &mut host).unwrap();
    assert_eq!(
        r.reserve(request(9, 1), snapshot, &[1, 2], &mut host)
            .unwrap(),
        Reservation::New(0)
    );
    r.store_inventory(binding(1), output_delta(), &mut host)
        .unwrap();
    r.store_inventory(
        binding(2),
        OutputDelta {
            producer_ticket: 1,
            sequence: 1,
            prior_inventory_revision: 8,
            changes: vec![],
            final_for_producer: true,
        },
        &mut host,
    )
    .unwrap();
    r.store_inventory(
        binding(1),
        OutputDelta {
            producer_ticket: 2,
            sequence: 1,
            prior_inventory_revision: 9,
            changes: vec![],
            final_for_producer: true,
        },
        &mut host,
    )
    .unwrap();
    assert_eq!(r.plan(0).unwrap().snapshot.revision, 10);
    assert_eq!(
        decode(&encode(r.plan(0).unwrap()).unwrap()).unwrap(),
        *r.plan(0).unwrap()
    );
    assert_eq!(
        Registry::recover([8; 16], test_journal_identity(), &host.frames)
            .unwrap()
            .plan(0),
        r.plan(0)
    );
    let n = host.frames.len();
    assert!(r
        .store_inventory(
            binding(2),
            OutputDelta {
                producer_ticket: 2,
                sequence: 1,
                prior_inventory_revision: 9,
                changes: vec![],
                final_for_producer: true,
            },
            &mut host
        )
        .is_err());
    assert_eq!(host.frames.len(), n);
}
