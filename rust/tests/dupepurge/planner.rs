//! Task 2 RED-stage contract tests. No filesystem access and no purge stub.
//! Comparison outcomes are captured mechanical strcasecmp results; prepare
//! applies the real anchored family/ownership policy to these owned records.
use nzbget_rs::dupepurge::{
    prepare, Action, AnchorComparison, ComparisonContext, CustodyReceipt, DirectBinding, EntryKind,
    InventoryEntry, MemberBinding, MemberKind, MemberRecord, NamespaceProof, OutsideClaim,
    OwnershipReceipt, ParentMembership, Phase, PurgeError, RootRecord, Snapshot, SourceValidation,
};

fn binding(id: i32) -> MemberBinding {
    MemberBinding {
        collection_id: id,
        file_id: None,
        incarnation: 100 + id as u64,
        posting_source: format!("source-v1:{id}").into_bytes(),
    }
}
fn member(id: i32, name: &[u8], key: &[u8], kind: MemberKind) -> MemberRecord {
    MemberRecord {
        binding: binding(id),
        name: name.to_vec(),
        key: key.to_vec(),
        kind,
        complete_inventory: true,
        source_validation_id: id as u64,
    }
}
fn source(id: i32) -> SourceValidation {
    SourceValidation {
        id: id as u64,
        version: 1,
        validator_version: 1,
        source_record_id: [id as u8; 32],
        source_bytes_digest: [id as u8 + 10; 32],
        binding: binding(id),
        parent_collection: None,
        custody_receipt_id: [id as u8 + 20; 32],
    }
}
fn custody(id: i32) -> CustodyReceipt {
    CustodyReceipt {
        id: [id as u8 + 20; 32],
        validator_version: 1,
        source_record_id: [id as u8; 32],
        source_bytes_digest: [id as u8 + 10; 32],
    }
}
fn entry(id: u64, owner: i32, path: &[u8], kind: EntryKind) -> InventoryEntry {
    InventoryEntry {
        id,
        root_id: 10,
        relative_path: path.to_vec(),
        kind,
        object_identity: format!("posix-v1:entry:{id}").into_bytes(),
        member: binding(owner),
        namespace_proof_id: [1; 32],
        ownership_receipt_id: [id as u8 + 40; 32],
        inventory_revision: 7,
    }
}
fn ownership(e: &InventoryEntry) -> OwnershipReceipt {
    OwnershipReceipt {
        id: e.ownership_receipt_id,
        member: e.member.clone(),
        root_id: e.root_id,
        relative_path: e.relative_path.clone(),
        kind: e.kind,
        object_identity: e.object_identity.clone(),
        namespace_proof_id: e.namespace_proof_id,
        inventory_revision: e.inventory_revision,
    }
}
fn snapshot(members: Vec<MemberRecord>, comparisons: Vec<AnchorComparison>) -> Snapshot {
    let sources = members
        .iter()
        .map(|m| source(m.binding.collection_id))
        .collect();
    let receipts = members
        .iter()
        .map(|m| custody(m.binding.collection_id))
        .collect();
    Snapshot {
        version: 1,
        revision: 7,
        generation: 8,
        seeds: vec![binding(1)],
        members,
        source_validations: sources,
        custody_receipts: receipts,
        parents: vec![],
        comparison_context: ComparisonContext {
            captured: b"posix:C:ctype-v1".to_vec(),
            current: b"posix:C:ctype-v1".to_vec(),
        },
        comparisons,
        direct_bindings: vec![],
        roots: vec![RootRecord {
            id: 10,
            descriptor_identity: b"posix-v1:root:10".to_vec(),
            configured_container: false,
        }],
        namespace_proofs: vec![NamespaceProof {
            id: [1; 32],
            root_id: 10,
            relative_path: vec![],
            root_identity: b"posix-v1:root:10".to_vec(),
            ancestor_identity: b"posix-v1:ancestors:10".to_vec(),
            mount_identity: b"mount-v1:10".to_vec(),
            exclusive: false,
        }],
        entries: vec![],
        ownership_receipts: vec![],
        outside_claims: vec![],
    }
}
fn cmp(seed: i32, candidate: i32, name_equal: bool, key_equal: bool) -> AnchorComparison {
    AnchorComparison {
        seed: binding(seed),
        candidate: binding(candidate),
        name_equal,
        key_equal,
    }
}
fn one() -> Snapshot {
    snapshot(
        vec![member(1, b"Release", b"A", MemberKind::Queue)],
        vec![cmp(1, 1, true, true)],
    )
}
fn add_entry(s: &mut Snapshot, e: InventoryEntry) {
    s.ownership_receipts.push(ownership(&e));
    s.entries.push(e);
}
fn leaf(id: u64, path: &[u8], kind: EntryKind) -> Action {
    Action::RemoveEntry {
        entry_id: id,
        root_id: 10,
        relative_path: path.to_vec(),
        kind,
        object_identity: format!("posix-v1:entry:{id}").into_bytes(),
    }
}
fn expect_error(s: Snapshot, want: PurgeError) {
    // Result::Err exposes no Plan, executable actions, or usable handle.
    assert_eq!(prepare(s, [0; 16]).unwrap_err(), want);
}

#[test]
fn anchors_do_not_bridge_conflicting_keys() {
    // A closure would wrongly pull keyed B through the matching unkeyed row.
    let mut s = snapshot(
        vec![
            member(3, b"Release", b"B", MemberKind::History),
            member(2, b"Release", b"", MemberKind::History),
            member(1, b"Release", b"A", MemberKind::Queue),
        ],
        vec![
            cmp(1, 3, true, false),
            cmp(1, 2, true, false),
            cmp(1, 1, true, true),
        ],
    );
    add_entry(&mut s, entry(3, 3, b"B.mkv", EntryKind::Regular));
    add_entry(&mut s, entry(2, 2, b"unkeyed.mkv", EntryKind::Regular));
    add_entry(&mut s, entry(1, 1, b"A.mkv", EntryKind::Regular));
    let p = prepare(s, [0; 16]).unwrap();
    assert_eq!(p.token.members, vec![binding(1), binding(2)]);
    assert_eq!(
        p.actions,
        vec![
            leaf(1, b"A.mkv", EntryKind::Regular),
            leaf(2, b"unkeyed.mkv", EntryKind::Regular)
        ]
    );
    assert_eq!(p.phase, Phase::Prepared);
    assert_eq!(p.token.generation, 8);
    assert_eq!(p.token.request, [0; 16]); // Binary request tokens may contain NUL.
}

#[test]
fn direct_bindings_include_queue_post_history_compact() {
    // Independent validated posting edges can join unlike names/keys, without
    // promoting an unselected intermediate into a new anchor.
    let mut s = snapshot(
        vec![
            member(4, b"D", b"D", MemberKind::CompactHistory),
            member(2, b"B", b"B", MemberKind::Post),
            member(1, b"A", b"A", MemberKind::Queue),
            member(3, b"C", b"C", MemberKind::History),
            member(5, b"E", b"E", MemberKind::History),
        ],
        vec![
            cmp(1, 1, true, true),
            cmp(1, 2, false, false),
            cmp(1, 3, false, false),
            cmp(1, 4, false, false),
            cmp(1, 5, false, false),
        ],
    );
    for id in [4, 2, 3] {
        s.direct_bindings.push(DirectBinding {
            seed: binding(1),
            candidate: binding(id),
            seed_source_validation_id: 1,
            candidate_source_validation_id: id as u64,
        });
    }
    for (id, path) in [
        (4, b"compact".as_slice()),
        (2, b"post"),
        (1, b"queue"),
        (3, b"history"),
        (5, b"outside"),
    ] {
        add_entry(&mut s, entry(id as u64, id, path, EntryKind::Regular));
    }
    let p = prepare(s, [1; 16]).unwrap();
    assert_eq!(
        p.token.members,
        vec![binding(1), binding(2), binding(3), binding(4)]
    );
    assert_eq!(
        p.actions,
        vec![
            leaf(4, b"compact", EntryKind::Regular),
            leaf(3, b"history", EntryKind::Regular),
            leaf(2, b"post", EntryKind::Regular),
            leaf(1, b"queue", EntryKind::Regular)
        ]
    );
}

#[test]
fn repeated_and_overlapping_seeds_deduplicate_members_and_actions() {
    let mut s = snapshot(
        vec![
            member(2, b"release", b"a", MemberKind::History),
            member(1, b"Release", b"A", MemberKind::Queue),
        ],
        vec![
            cmp(1, 1, true, true),
            cmp(1, 2, true, true),
            cmp(2, 1, true, true),
            cmp(2, 2, true, true),
        ],
    );
    s.seeds = vec![binding(2), binding(1), binding(2)];
    add_entry(&mut s, entry(2, 2, b"z", EntryKind::Regular));
    add_entry(&mut s, entry(1, 1, b"a", EntryKind::Regular));
    let p = prepare(s, [1; 16]).unwrap();
    assert_eq!(p.token.members, vec![binding(1), binding(2)]);
    assert_eq!(
        p.actions,
        vec![
            leaf(1, b"a", EntryKind::Regular),
            leaf(2, b"z", EntryKind::Regular)
        ]
    );
}

#[test]
fn file_binding_requires_exact_parent_and_sorts_after_collection() {
    let mut s = one();
    let mut f = binding(1);
    f.file_id = Some(9);
    f.incarnation = 209;
    f.posting_source = b"file-source-v1:9".to_vec();
    let mut m = member(1, b"Release", b"A", MemberKind::Queue);
    m.binding = f.clone();
    m.source_validation_id = 9;
    s.members.push(m);
    let mut v = source(1);
    v.id = 9;
    v.binding = f.clone();
    v.parent_collection = Some(binding(1));
    s.source_validations.push(v);
    s.parents.push(ParentMembership {
        file: f.clone(),
        collection: binding(1),
    });
    let p = prepare(s.clone(), [1; 16]).unwrap();
    assert_eq!(p.token.members, vec![binding(1), f.clone()]);
    assert_eq!(p.actions, vec![]);
    s.parents[0].collection.incarnation += 1;
    expect_error(s, PurgeError::Conflict);
}

#[test]
fn outside_claim_prevents_recursive_cleanup() {
    let mut s = one();
    add_entry(&mut s, entry(2, 1, b"download", EntryKind::Directory));
    add_entry(&mut s, entry(1, 1, b"download/owned", EntryKind::Regular));
    s.outside_claims.push(OutsideClaim {
        id: 1,
        root_id: 10,
        relative_path: b"download/other".to_vec(),
        claimant: binding(99),
        object_identity: b"posix-v1:outside".to_vec(),
    });
    let p = prepare(s, [1; 16]).unwrap();
    assert_eq!(p.token.members, vec![binding(1)]);
    assert_eq!(
        p.actions,
        vec![leaf(1, b"download/owned", EntryKind::Regular)]
    );
    assert_eq!(p.snapshot.entries.len(), 2);
}

#[test]
fn configured_container_and_nested_claim_preserve_roots() {
    let mut s = one();
    s.roots[0].configured_container = true;
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.outside_claims.push(OutsideClaim {
        id: 1,
        root_id: 10,
        relative_path: b"other/nested".to_vec(),
        claimant: binding(99),
        object_identity: b"posix-v1:outside".to_vec(),
    });
    assert_eq!(
        prepare(s, [1; 16]).unwrap().actions,
        vec![leaf(1, b"owned", EntryKind::Regular)]
    );
}

#[test]
fn exact_outside_leaf_claim_rejects_before_any_action() {
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.outside_claims.push(OutsideClaim {
        id: 1,
        root_id: 10,
        relative_path: b"owned".to_vec(),
        claimant: binding(99),
        object_identity: b"posix-v1:entry:1".to_vec(),
    });
    expect_error(s, PurgeError::Conflict);
}

#[test]
fn exclusive_tree_keeps_child_inventory_but_suppresses_redundant_actions() {
    let mut s = one();
    s.namespace_proofs[0].exclusive = true;
    s.namespace_proofs[0].relative_path = b"download".to_vec();
    add_entry(&mut s, entry(2, 1, b"download", EntryKind::Directory));
    add_entry(&mut s, entry(1, 1, b"download/owned", EntryKind::Regular));
    let p = prepare(s.clone(), [1; 16]).unwrap();
    assert_eq!(
        p.actions,
        vec![Action::RemoveTree {
            entry_id: 2,
            root_id: 10,
            relative_path: b"download".to_vec(),
            object_identity: b"posix-v1:entry:2".to_vec()
        }]
    );
    assert_eq!(p.snapshot.entries, s.entries);
    s.ownership_receipts[1].object_identity = b"substituted-child".to_vec();
    expect_error(s, PurgeError::Conflict); // Child validation remains mandatory.
}

#[test]
fn exclusive_proof_with_outside_child_disables_recursion() {
    let mut s = one();
    s.namespace_proofs[0].exclusive = true;
    s.namespace_proofs[0].relative_path = b"download".to_vec();
    add_entry(&mut s, entry(2, 1, b"download", EntryKind::Directory));
    add_entry(&mut s, entry(1, 1, b"download/owned", EntryKind::Regular));
    s.outside_claims.push(OutsideClaim {
        id: 1,
        root_id: 10,
        relative_path: b"download/other".to_vec(),
        claimant: binding(99),
        object_identity: b"posix-v1:outside".to_vec(),
    });
    assert_eq!(
        prepare(s, [1; 16]).unwrap().actions,
        vec![leaf(1, b"download/owned", EntryKind::Regular)]
    );
}

#[test]
fn reused_seed_and_unknown_inventory_fail() {
    let mut s = one();
    s.seeds = vec![binding(2)];
    expect_error(s, PurgeError::MissingSeed);
    let mut s = one();
    s.seeds[0].incarnation += 1;
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.seeds[0].posting_source = b"different-source".to_vec();
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.members[0].kind = MemberKind::CompactHistory;
    s.members[0].complete_inventory = false;
    expect_error(s, PurgeError::MissingInventory);
}

#[test]
fn unauthenticated_source_and_ownership_receipts_fail() {
    let mut s = one();
    s.custody_receipts.clear();
    expect_error(s, PurgeError::MissingInventory);
    let mut s = one();
    s.source_validations[0].source_bytes_digest = [90; 32];
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.ownership_receipts.clear();
    expect_error(s, PurgeError::MissingInventory);
    let mut s = one();
    s.namespace_proofs.clear();
    expect_error(s, PurgeError::MissingInventory);
}

#[test]
fn unselected_direct_edges_cannot_become_closure_anchors() {
    let mut s = snapshot(
        vec![
            member(1, b"A", b"A", MemberKind::Queue),
            member(2, b"B", b"B", MemberKind::History),
            member(3, b"C", b"C", MemberKind::History),
        ],
        vec![
            cmp(1, 1, true, true),
            cmp(1, 2, false, false),
            cmp(1, 3, false, false),
        ],
    );
    s.direct_bindings.push(DirectBinding {
        seed: binding(2),
        candidate: binding(3),
        seed_source_validation_id: 2,
        candidate_source_validation_id: 3,
    });
    expect_error(s, PurgeError::InvalidInput);
}

#[test]
fn missing_conflicting_stale_comparison_or_context_fails() {
    let mut s = one();
    s.comparisons.clear();
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.comparisons.push(cmp(1, 1, false, false));
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.comparisons[0].candidate.incarnation += 1;
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.comparison_context.current = b"posix:tr_TR:ctype-v1".to_vec();
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.comparison_context.captured.clear();
    expect_error(s, PurgeError::InvalidInput);
}

#[test]
fn captured_locale_non_utf8_and_case_outcomes_remain_authoritative() {
    // Outcomes deliberately differ from ASCII/Unicode folding. They are
    // offline captured-boundary fixtures, not a claim to execute a locale.
    let mut s = snapshot(
        vec![
            member(1, b"\xffI", b"", MemberKind::Queue),
            member(2, b"\xffi", b"", MemberKind::History),
            member(3, b"\xfeI", b"", MemberKind::History),
        ],
        vec![
            cmp(1, 1, true, false),
            cmp(1, 2, false, false),
            cmp(1, 3, true, false),
        ],
    );
    s.comparison_context.captured = b"captured:locale-fixture-v1".to_vec();
    s.comparison_context.current = s.comparison_context.captured.clone();
    add_entry(&mut s, entry(3, 3, b"\xffpayload", EntryKind::Symlink));
    let p = prepare(s, [1; 16]).unwrap();
    assert_eq!(p.token.members, vec![binding(1), binding(3)]);
    assert_eq!(p.actions, vec![leaf(3, b"\xffpayload", EntryKind::Symlink)]);
    assert_eq!(p.snapshot.members[0].name, b"\xffI");
}

#[test]
fn malformed_ids_versions_and_generation_fail() {
    let mut s = one();
    s.version = 2;
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.generation = 0;
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.generation = u64::MAX;
    expect_error(s, PurgeError::InvalidInput);
    for id in [0, -1, i32::MIN] {
        let mut s = one();
        s.members[0].binding.collection_id = id;
        expect_error(s, PurgeError::InvalidInput);
    }
    let mut s = one();
    s.members[0].binding.file_id = Some(0);
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.members[0].binding.incarnation = 0;
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.members[0].binding.posting_source.clear();
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.members[0].binding.posting_source = b"bad\0source".to_vec();
    expect_error(s, PurgeError::InvalidInput);
}

#[test]
fn duplicate_conflicting_records_and_stale_inventory_fail() {
    let mut s = one();
    let mut m = s.members[0].clone();
    m.binding.incarnation += 1;
    s.members.push(m);
    expect_error(s, PurgeError::Conflict);
    let mut s = one();
    s.members.push(s.members[0].clone());
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.entries.push(s.entries[0].clone());
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.entries[0].inventory_revision = 6;
    expect_error(s, PurgeError::Conflict);
}

#[test]
fn unsafe_paths_nul_fields_unsupported_objects_and_missing_roots_fail() {
    for path in [
        b"".as_slice(),
        b"/absolute",
        b".",
        b"..",
        b"a/../b",
        b"a/./b",
        b"a//b",
        b"a/",
        b"bad\0path",
    ] {
        let mut s = one();
        add_entry(&mut s, entry(1, 1, path, EntryKind::Regular));
        expect_error(s, PurgeError::InvalidInput);
    }
    let mut s = one();
    s.members[0].name = b"bad\0name".to_vec();
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    s.members[0].key = b"bad\0key".to_vec();
    expect_error(s, PurgeError::InvalidInput);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"socket", EntryKind::Unsupported));
    expect_error(s, PurgeError::Unsupported);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"owned", EntryKind::Regular));
    s.roots.clear();
    expect_error(s, PurgeError::MissingInventory);
}

#[test]
fn path_and_identity_limits_admit_exact_bytes_and_reject_overflow() {
    let mut s = one();
    let path = vec![b'p'; 1023];
    s.members[0].name = vec![b'n'; 65535];
    add_entry(&mut s, entry(1, 1, &path, EntryKind::Regular));
    let p = prepare(s.clone(), [1; 16]).unwrap();
    assert_eq!(p.actions, vec![leaf(1, &path, EntryKind::Regular)]);
    assert_eq!(p.snapshot.members[0].name.len(), 65535);
    s.members[0].name.push(b'n');
    expect_error(s, PurgeError::LimitExceeded);
    let mut s = one();
    add_entry(&mut s, entry(1, 1, &vec![b'p'; 1024], EntryKind::Regular));
    expect_error(s, PurgeError::LimitExceeded);
}

#[test]
fn over_limit_seed_member_and_inventory_counts_reject_before_graph_validation() {
    let mut s = one();
    s.seeds = vec![binding(1); 4097];
    expect_error(s, PurgeError::LimitExceeded);
    let mut s = one();
    s.members = vec![s.members[0].clone(); 65537];
    expect_error(s, PurgeError::LimitExceeded);
    let mut s = one();
    s.entries = vec![entry(1, 1, b"owned", EntryKind::Regular); 1_000_001];
    expect_error(s, PurgeError::LimitExceeded);
}

#[test]
fn secondary_claim_payload_counts_toward_total_snapshot_limit() {
    // Each field is within its own limit; this secondary array exceeds 64 MiB.
    // Admission must fail before graph lookup or any action construction.
    let mut s = one();
    s.outside_claims = (1..=1025)
        .map(|id| OutsideClaim {
            id,
            root_id: 10,
            relative_path: vec![b'p'; 1023],
            claimant: binding(99),
            object_identity: vec![b'i'; 65535],
        })
        .collect();
    expect_error(s, PurgeError::LimitExceeded);
}

#[test]
fn exact_directory_removal_follows_children_without_recursion() {
    let mut s = one();
    add_entry(&mut s, entry(1, 1, b"a", EntryKind::Directory));
    add_entry(&mut s, entry(2, 1, b"a/z", EntryKind::Regular));
    add_entry(&mut s, entry(3, 1, b"b", EntryKind::Symlink));
    assert_eq!(
        prepare(s, [1; 16]).unwrap().actions,
        vec![
            leaf(2, b"a/z", EntryKind::Regular),
            leaf(1, b"a", EntryKind::Directory),
            leaf(3, b"b", EntryKind::Symlink),
        ]
    );
}

#[test]
fn direct_edge_must_resolve_exact_source_validation_and_parent() {
    let mut s = snapshot(
        vec![
            member(1, b"A", b"A", MemberKind::Queue),
            member(2, b"B", b"B", MemberKind::History),
        ],
        vec![cmp(1, 1, true, true), cmp(1, 2, false, false)],
    );
    s.direct_bindings.push(DirectBinding {
        seed: binding(1),
        candidate: binding(2),
        seed_source_validation_id: 1,
        candidate_source_validation_id: 1,
    });
    expect_error(s, PurgeError::Conflict);
}

#[test]
fn file_binding_without_parent_membership_fails() {
    let mut s = one();
    let mut f = binding(1);
    f.file_id = Some(9);
    f.incarnation = 209;
    let mut m = member(1, b"Release", b"A", MemberKind::Queue);
    m.binding = f.clone();
    m.source_validation_id = 9;
    s.members.push(m);
    let mut v = source(1);
    v.id = 9;
    v.binding = f;
    v.parent_collection = Some(binding(1));
    s.source_validations.push(v);
    expect_error(s, PurgeError::MissingInventory);
}
