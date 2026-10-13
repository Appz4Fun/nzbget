//! Article placement contracts for the staged fallback owner.
//! Foundation only: no production caller is switched by this module.

#[cfg(test)]
mod tests {
    use super::*;

    fn article(part: i32, offset: i64, size: i32) -> Article {
        Article { part, size: size + 10, offset, segment_size: size, finished: true, borrowed: false }
    }

    #[test]
    fn contiguous_geometry_is_aligned_and_tiled() {
        let a = [article(1, 0, 100), article(2, 100, 100), article(3, 200, 50)];
        assert_eq!(expected_offset(&a, 0), Some(0));
        assert_eq!(expected_offset(&a, 1), Some(100));
        assert_eq!(expected_end(&a, 1, 250), Some(200));
        assert_eq!(expected_end(&a, 2, 250), Some(250));
        assert!((0..a.len()).all(|i| segment_aligned(&a, i, 250)));
        assert_eq!(first_untiled(&a, 250), None);
    }

    #[test]
    fn absent_previous_or_next_part_keeps_neighbor_unknown() {
        let a = [article(2, 100, 100), article(4, 300, 100)];
        assert_eq!(expected_offset(&a, 0), None);
        assert_eq!(expected_offset(&a, 1), None);
        assert_eq!(expected_end(&a, 0, 400), None);
        assert_eq!(expected_end(&a, 1, 400), Some(400));
    }

    #[test]
    fn last_list_article_uses_decoded_size_even_with_missing_parts() {
        let a = [article(3, 100, 100)];
        assert_eq!(expected_end(&a, 0, 200), Some(200));
        assert_eq!(expected_end(&a, 0, 0), None);
        assert_eq!(expected_end(&a, 0, -1), None);
    }

    #[test]
    fn unknown_size_and_empty_list_do_not_judge_tiling() {
        let a = [article(1, 10, 100)];
        assert_eq!(first_untiled(&a, 0), None);
        assert_eq!(first_untiled(&a, -1), None);
        assert_eq!(first_untiled(&[], 100), None);
    }

    #[test]
    fn incomplete_prefix_returns_before_a_later_bad_seam() {
        let mut a = [article(1, 0, 100), article(2, 500, 100)];
        a[0].finished = false;
        assert_eq!(first_untiled(&a, 600), None);
        assert_eq!(expected_offset(&a, 1), None);
        a[0].finished = true;
        a[0].segment_size = 0;
        assert_eq!(first_untiled(&a, 600), None);
    }

    #[test]
    fn broken_seam_is_reported_before_later_incomplete_state() {
        let mut a = [article(1, 0, 100), article(2, 90, 100), article(3, 190, 100)];
        a[2].finished = false;
        assert_eq!(first_untiled(&a, 290), Some(1));
    }

    #[test]
    fn seam_prefers_the_borrowed_neighbor() {
        let mut a = [article(1, 0, 100), article(2, 110, 100)];
        a[0].borrowed = true;
        assert_eq!(first_untiled(&a, 210), Some(0));
        a[0].borrowed = false;
        a[1].borrowed = true;
        assert_eq!(first_untiled(&a, 210), Some(1));
    }

    #[test]
    fn gap_with_correctly_placed_later_article_blames_short_previous() {
        let a = [article(1, 0, 90), article(2, 100, 100), article(3, 200, 100)];
        assert_eq!(first_untiled(&a, 300), Some(0));
    }

    #[test]
    fn overlap_and_final_length_mismatch_are_detected() {
        let a = [article(1, 0, 100), article(2, 90, 100)];
        assert_eq!(first_untiled(&a, 190), Some(1));
        let b = [article(1, 0, 100), article(2, 100, 100)];
        assert_eq!(first_untiled(&b, 201), Some(1));
        assert!(!segment_aligned(&b, 1, 201));
    }

    #[test]
    fn no_decoded_placement_is_vacuously_aligned() {
        let a = [article(1, 123, 0)];
        assert!(segment_aligned(&a, 0, 200));
    }

    #[test]
    fn alignment_checks_available_neighbor_boundaries() {
        let a = [article(1, 0, 100), article(2, 101, 99), article(3, 200, 50)];
        assert!(!segment_aligned(&a, 1, 250));
        assert!(!segment_aligned(&a, 0, 250));
        assert!(segment_aligned(&a, 2, 250));
    }

    #[test]
    fn invalid_index_does_not_address_an_article() {
        let a = [article(1, 0, 100)];
        assert_eq!(expected_offset(&a, 1), None);
        assert_eq!(expected_end(&a, usize::MAX, 100), None);
        assert!(!segment_aligned(&a, usize::MAX, 100));
    }

    #[test]
    fn overflowing_endpoints_are_rejected_conservatively() {
        let a = [article(1, i64::MAX, 100), article(2, 0, 100)];
        assert_eq!(expected_offset(&a, 1), None);
        assert!(!segment_aligned(&a, 0, 100));
        assert_eq!(first_untiled(&a, 100), Some(0));
    }
}
