// Additional local Codex contract findings, authored before implementation.
// Include inside articlegeometry's test module after the initial RED receipt.
#[test]
fn preserve_computed_negative_boundaries_and_exact_unknown_sentinel() {
    let mut a = [article(2, -102, 100), article(3, 123, 100), article(4, -2, 100)];
    assert_eq!(expected_offset(&a, 1), Some(-2));
    assert_eq!(expected_end(&a, 1, 500), Some(-2));
    assert!(segment_aligned(&a, 1, 500));
    a[0].offset = -101;
    a[2].offset = -1;
    assert_eq!(expected_offset(&a, 1), None);
    assert_eq!(expected_end(&a, 1, 500), None);
    assert!(segment_aligned(&a, 1, 500));
}

#[test]
fn overflow_at_alignment_end_is_conservatively_rejected() {
    let mut a = [article(1, 0, 100), article(2, i64::MAX, 100)];
    a[0].finished = false;
    assert_eq!(expected_offset(&a, 1), None);
    assert!(!segment_aligned(&a, 1, i64::MAX));
}

#[test]
fn part_number_extremes_use_checked_neighbor_arithmetic() {
    let a = [article(0, 0, 100), article(i32::MIN, 100, 100), article(i32::MAX, 200, 100), article(0, 300, 100)];
    assert_eq!(expected_offset(&a, 1), None);
    assert_eq!(expected_end(&a, 2, 400), None);
}

#[test]
fn borrowed_overlap_prefers_previous_before_later_incomplete_state() {
    let mut a = [article(1, 0, 100), article(2, 90, 100), article(3, 190, 100)];
    a[0].borrowed = true;
    a[2].finished = false;
    assert_eq!(first_untiled(&a, 290), Some(0));
    a[1].borrowed = true;
    assert_eq!(first_untiled(&a, 290), Some(1));
}

#[test]
fn borrower_preference_precedes_overflowing_seam_endpoint() {
    let mut a = [article(1, 0, 100), article(2, i64::MAX, 100)];
    a[0].borrowed = true;
    assert_eq!(first_untiled(&a, i64::MAX), Some(0));
    a[0].borrowed = false;
    a[1].borrowed = true;
    assert_eq!(first_untiled(&a, i64::MAX), Some(1));
}

#[test]
fn representable_near_limit_boundaries_keep_defined_behavior() {
    let a = [article(2, i64::MAX - 100, 100), article(3, i64::MAX, 0)];
    assert_eq!(expected_offset(&a, 1), Some(i64::MAX));
    assert_eq!(expected_end(&a, 0, i64::MAX), None); // next has no placement
    assert!(segment_aligned(&a, 0, i64::MAX));
}
