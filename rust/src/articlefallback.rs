//! Recovery owner contracts. Implementation follows source-bound RED execution.

// SPDX-License-Identifier: GPL-2.0-or-later

pub const LEAD_DEMOTE_THRESHOLD: i32 = 3;

/// Mutable file-level lead accounting, owned by the eventual recovery context.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LeadState {
    pub donor_id: i32,
    pub failures: i32,
    pub switches: i32,
}

/// Immutable snapshot of the contributors to one article's pinned source list.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PinnedLead {
    pub donor_id: i32,
    pub next_donor_id: i32,
    pub donor_count: i32,
}

fn current_lead(state: &LeadState, pinned: PinnedLead, round: i32) -> bool {
    round == 1 && pinned.donor_id != 0 && pinned.donor_id == state.donor_id
}

/// Charge a failure only to the donor that actually supplied pinned slot zero.
/// Return true only when the lead rotated. Overflow is outside the C++ parity
/// domain; leave state untouched if a counter cannot be represented.
pub fn record_failure(state: &mut LeadState, pinned: PinnedLead, round: i32) -> bool {
    if !current_lead(state, pinned, round) { return false; }
    let Some(failures) = state.failures.checked_add(1) else { return false; };
    let rotate = failures >= LEAD_DEMOTE_THRESHOLD
        && pinned.next_donor_id != 0 && state.switches < pinned.donor_count;
    if rotate {
        let Some(switches) = state.switches.checked_add(1) else { return false; };
        state.donor_id = pinned.next_donor_id;
        state.failures = 0;
        state.switches = switches;
        true
    } else {
        state.failures = failures;
        false
    }
}

/// A provisional success clears the streak but cannot rearm the rotation budget.
/// The caller supplies the historical exact-sentinel test: both expected
/// boundaries differ from -1, even if either is another negative value.
pub fn record_success(state: &mut LeadState, pinned: PinnedLead, round: i32, alignment_known: bool) {
    if !current_lead(state, pinned, round) { return; }
    state.failures = 0;
    if alignment_known { state.switches = 0; }
}

/// Candidate bytes already verified/matched by the donor selector.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    pub message_id: Vec<u8>,
    pub donor_id: i32,
}

fn c_bytes(value: &[u8]) -> &[u8] {
    &value[..value.iter().position(|&byte| byte == 0).unwrap_or(value.len())]
}

/// Collect an actual donor message ID, preserving the first contributor.
/// Empty IDs cannot be fetched and are excluded by the native donor lookup.
pub fn append_candidate(candidates: &mut Vec<Candidate>, donor_id: i32, message_id: &[u8]) {
    let bytes = c_bytes(message_id);
    if bytes.is_empty() || candidates.iter().any(|candidate| c_bytes(&candidate.message_id) == bytes) {
        return;
    }
    candidates.push(Candidate { message_id: bytes.to_vec(), donor_id });
}

/// An article owns its ordered sources and bookkeeping independently of the
/// donor cache, mutable file lead and subsequent queue/history insertions.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PinnedArticle {
    sources: Vec<Vec<u8>>,
    contributors: Vec<i32>,
    lead: PinnedLead,
}

/// Borrowed selection from an immutable pin; the bytes cannot outlive its owner.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SourceSelection<'a> {
    pub index: usize,
    pub next_round: i32,
    pub donor_id: Option<i32>,
    pub message_id: &'a [u8],
}

impl PinnedArticle {
    pub fn lead(&self) -> PinnedLead { self.lead }
    pub fn source(&self, index: usize) -> Option<&[u8]> {
        self.sources.get(index).map(Vec::as_slice)
    }
    pub fn source_count(&self) -> usize { self.sources.len() }
    pub fn donor_at(&self, index: usize) -> Option<i32> { self.contributors.get(index).copied() }

    /// Advance over blocked donor slots while keeping the pin and primary slot fixed.
    pub fn next_source(&self, round: i32, blocked: &std::collections::BTreeSet<i32>) -> Option<SourceSelection<'_>> {
        let mut index = usize::try_from(round).ok()?;
        while let Some(donor) = self.donor_at(index) {
            if !blocked.contains(&donor) { break; }
            index = index.checked_add(1)?;
        }
        let bytes = self.source(index)?;
        let next_round = i32::try_from(index.checked_add(1)?).ok()?;
        Some(SourceSelection { index, next_round, donor_id: self.donor_at(index), message_id: bytes })
    }

    #[cfg(test)]
    fn source_ids(&self) -> Vec<Vec<u8>> { self.sources.clone() }
}

/// The pure FinishPin operation. Candidate order is preserved exactly; this
/// boundary does not deduplicate an already-built list or overwrite a decided
/// file lead. All message bytes are copied before the caller can evict donors.
pub fn pin_sources(state: &mut LeadState, candidates: &[Candidate], cutover: bool, primary: &[u8]) -> PinnedArticle {
    let mut donor_ids = Vec::new();
    for candidate in candidates {
        if !donor_ids.contains(&candidate.donor_id) { donor_ids.push(candidate.donor_id); }
    }
    let lead = PinnedLead {
        donor_id: donor_ids.first().copied().unwrap_or(0),
        next_donor_id: donor_ids.get(1).copied().unwrap_or(0),
        donor_count: i32::try_from(donor_ids.len()).expect("donor count exceeds native signed domain"),
    };
    if state.donor_id == 0 && !donor_ids.is_empty() { state.donor_id = donor_ids[0]; }
    let mut sources: Vec<Vec<u8>> = candidates.iter().map(|candidate| c_bytes(&candidate.message_id).to_vec()).collect();
    if cutover && !candidates.is_empty() { sources.push(c_bytes(primary).to_vec()); }
    PinnedArticle { sources, contributors: candidates.iter().map(|candidate| candidate.donor_id).collect(), lead }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> LeadState { LeadState { donor_id: 10, failures: 0, switches: 0 } }
    fn pin() -> PinnedLead { PinnedLead { donor_id: 10, next_donor_id: 20, donor_count: 2 } }

    #[test]
    fn three_current_lead_failures_rotate_once() {
        let mut s=state();
        assert!(!record_failure(&mut s,pin(),1)); assert_eq!(s.failures,1);
        assert!(!record_failure(&mut s,pin(),1)); assert_eq!(s.failures,2);
        assert!(record_failure(&mut s,pin(),1));
        assert_eq!((s.donor_id,s.failures,s.switches),(20,0,1));
    }

    #[test]
    fn stale_pinned_results_cannot_charge_the_new_lead() {
        let mut s=LeadState { donor_id:20, failures:1, switches:1 };
        assert!(!record_failure(&mut s,pin(),1));
        record_success(&mut s,pin(),1,true);
        assert_eq!((s.donor_id,s.failures,s.switches),(20,1,1));
    }

    #[test]
    fn only_first_pinned_round_and_nonzero_lead_count() {
        for round in [0,2,3] {
            let mut s=state(); assert!(!record_failure(&mut s,pin(),round));
            assert_eq!(s.failures,0);
        }
        let mut s=state(); let mut p=pin(); p.donor_id=0;
        assert!(!record_failure(&mut s,p,1)); assert_eq!(s.failures,0);
    }

    #[test]
    fn single_donor_or_exhausted_budget_does_not_rotate() {
        let mut s=state(); let mut p=pin(); p.next_donor_id=0;
        for _ in 0..5 { assert!(!record_failure(&mut s,p,1)); }
        assert_eq!((s.donor_id,s.failures,s.switches),(10,5,0));
        let mut s=LeadState { donor_id:10, failures:2, switches:2 };
        assert!(!record_failure(&mut s,pin(),1));
        assert_eq!((s.donor_id,s.failures,s.switches),(10,3,2));
    }

    #[test]
    fn provisional_success_resets_streak_but_not_rotation_budget() {
        let mut s=LeadState { donor_id:10, failures:2, switches:2 };
        record_success(&mut s,pin(),1,false);
        assert_eq!((s.donor_id,s.failures,s.switches),(10,0,2));
        record_success(&mut s,pin(),1,true);
        assert_eq!((s.donor_id,s.failures,s.switches),(10,0,0));
    }
    #[test]
    fn pin_preserves_candidate_order_and_first_contributor_bookkeeping() {
        let mut s=LeadState { donor_id:0, failures:0, switches:0 };
        let candidates=vec![candidate(b"a",11),candidate(b"b",21),candidate(b"c",11)];
        let pinned=pin_sources(&mut s,&candidates,false,b"primary");
        assert_eq!(pinned.lead(),PinnedLead {donor_id:11,next_donor_id:21,donor_count:2});
        assert_eq!(pinned.source_ids(),vec![b"a".to_vec(),b"b".to_vec(),b"c".to_vec()]);
        assert_eq!(s.donor_id,11);
    }

    #[test]
    fn cutover_primary_is_last_and_has_no_donor_owner() {
        let mut s=state();
        let pinned=pin_sources(&mut s,&[candidate(b"a",21),candidate(b"b",31)],true,b"primary");
        assert_eq!(pinned.source_ids(),vec![b"a".to_vec(),b"b".to_vec(),b"primary".to_vec()]);
        assert_eq!(pinned.donor_at(0),Some(21));
        assert_eq!(pinned.donor_at(2),None);
        assert_eq!(s.donor_id,10); // existing lead is never overwritten by pinning
    }

    #[test]
    fn empty_donors_do_not_offer_primary_after_cutover() {
        let mut s=state();let pinned=pin_sources(&mut s,&[],true,b"primary");
        assert!(pinned.source_ids().is_empty());
        assert_eq!(pinned.lead(),PinnedLead {donor_id:0,next_donor_id:0,donor_count:0});
        assert_eq!(s.donor_id,10);
    }

    #[test]
    fn pinned_sources_own_bytes_and_ignore_later_candidates() {
        let mut s=state();let mut candidates=vec![candidate(b"original",10)];
        let pinned=pin_sources(&mut s,&candidates,false,b"primary");
        candidates[0].message_id[0]=b'X'; candidates.push(candidate(b"new",20));
        s.donor_id=20;
        assert_eq!(s.donor_id,20);
        assert_eq!(pinned.source_ids(),vec![b"original".to_vec()]);
        assert_eq!(pinned.lead().donor_id,10);
    }

    #[test]
    fn donor_collection_dedup_keeps_first_contributor_with_c_string_bytes() {
        let mut candidates=Vec::new();
        append_candidate(&mut candidates,10,b"id\0suffix");
        append_candidate(&mut candidates,20,b"id");
        append_candidate(&mut candidates,30,b"\xffnonutf8");
        assert_eq!(candidates.len(),2);
        assert_eq!(candidates[0],candidate(b"id",10));
        assert_eq!(candidates[1],candidate(b"\xffnonutf8",30));
    }

    fn candidate(id:&[u8],donor_id:i32)->Candidate {
        Candidate {message_id:id.to_vec(),donor_id}
    }

    #[test]
    fn blocked_donors_skip_slots_without_reordering_the_pin() {
        let mut s=state();
        let pinned=pin_sources(&mut s,&[candidate(b"a",10),candidate(b"b",20),candidate(b"c",30)],false,b"primary");
        let blocked=std::collections::BTreeSet::from([10,20]);
        let selected=pinned.next_source(0,&blocked).unwrap();
        assert_eq!((selected.index,selected.next_round,selected.donor_id),(2,3,Some(30)));
        assert_eq!(selected.message_id,b"c");
        assert_eq!(pinned.source_ids(),vec![b"a".to_vec(),b"b".to_vec(),b"c".to_vec()]);
    }

    #[test]
    fn primary_revert_is_not_blocked_by_a_donor_identifier() {
        let mut s=state();let pinned=pin_sources(&mut s,&[candidate(b"a",10)],true,b"primary");
        let blocked=std::collections::BTreeSet::from([10]);
        let selected=pinned.next_source(0,&blocked).unwrap();
        assert_eq!((selected.index,selected.next_round,selected.donor_id),(1,2,None));
        assert_eq!(selected.message_id,b"primary");
        assert!(pinned.next_source(2,&blocked).is_none());
    }

    #[test]
    fn exhausted_and_negative_rounds_do_not_address_a_source() {
        let mut s=state();let pinned=pin_sources(&mut s,&[candidate(b"a",10)],false,b"primary");
        let blocked=std::collections::BTreeSet::new();
        assert!(pinned.next_source(-1,&blocked).is_none());
        assert!(pinned.next_source(1,&blocked).is_none());
        assert!(pinned.next_source(i32::MAX,&blocked).is_none());
    }

}
