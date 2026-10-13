//! Recovery owner contracts. Implementation follows source-bound RED execution.

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
}
