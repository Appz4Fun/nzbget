//! Article placement contracts for the staged fallback owner.
//! Foundation only: no production caller is switched by this module.

// SPDX-License-Identifier: GPL-2.0-or-later

/// One immutable article snapshot. Encoded size is retained for donor identity.
#[derive(Clone, Copy, Debug)]
pub struct Article {
    pub part: i32,
    pub size: i32,
    pub offset: i64,
    pub segment_size: i32,
    pub finished: bool,
    pub borrowed: bool,
}

fn boundary(value: i64) -> Option<i64> {
    // Historical callers distinguish exactly -1 from other negative values.
    (value != -1).then_some(value)
}

pub fn expected_offset(articles: &[Article], index: usize) -> Option<i64> {
    let article = articles.get(index)?;
    if article.part == 1 {
        return Some(0);
    }
    let previous = articles.get(index.checked_sub(1)?)?;
    if previous.part == article.part.checked_sub(1)?
        && previous.finished && previous.segment_size > 0
    {
        boundary(previous.offset.checked_add(i64::from(previous.segment_size))?)
    } else {
        None
    }
}

pub fn expected_end(articles: &[Article], index: usize, decoded_size: i64) -> Option<i64> {
    let article = articles.get(index)?;
    if index == articles.len() - 1 {
        return (decoded_size > 0).then_some(decoded_size);
    }
    let next = &articles[index + 1];
    if next.part == article.part.checked_add(1)? && next.finished && next.segment_size > 0 {
        boundary(next.offset)
    } else {
        None
    }
}

pub fn segment_aligned(articles: &[Article], index: usize, decoded_size: i64) -> bool {
    let Some(article) = articles.get(index) else { return false; };
    if article.segment_size <= 0 {
        return true;
    }
    if let Some(offset) = expected_offset(articles, index) {
        if offset >= 0 && offset != article.offset {
            return false;
        }
    }
    if let Some(end) = expected_end(articles, index, decoded_size) {
        // Like C++, do not calculate the endpoint when this boundary is unknown.
        if end >= 0 && article.offset.checked_add(i64::from(article.segment_size)) != Some(end) {
            return false;
        }
    }
    true
}

pub fn first_untiled(articles: &[Article], decoded_size: i64) -> Option<usize> {
    if decoded_size <= 0 {
        return None;
    }
    let mut expected = 0;
    for (index, article) in articles.iter().enumerate() {
        if !article.finished || article.segment_size <= 0 {
            // This check is lazy: earlier broken seams still take precedence.
            return None;
        }
        if article.offset != expected {
            if let Some(previous_index) = index.checked_sub(1) {
                let previous = &articles[previous_index];
                if previous.borrowed != article.borrowed {
                    return Some(if previous.borrowed { previous_index } else { index });
                }
                // Borrower precedence above must not eagerly evaluate this sum.
                let Some(end) = article.offset.checked_add(i64::from(article.segment_size)) else {
                    return Some(index);
                };
                let placed_right = if let Some(next) = articles.get(index + 1) {
                    next.finished && next.segment_size > 0 && next.offset == end
                } else {
                    end == decoded_size
                };
                if article.offset > expected && placed_right {
                    return Some(previous_index);
                }
            }
            return Some(index);
        }
        let Some(end) = article.offset.checked_add(i64::from(article.segment_size)) else {
            return Some(index);
        };
        expected = end;
    }
    if expected != decoded_size { articles.len().checked_sub(1) } else { None }
}

/// Plain C snapshot: any nonzero flag means true. No Rust bool crosses the ABI.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct RawArticle {
    pub part: i32,
    pub size: i32,
    pub offset: i64,
    pub segment_size: i32,
    pub finished: u8,
    pub borrowed: u8,
}

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct GeometryResult {
    pub expected_offset: i64,
    pub expected_end: i64,
    pub aligned: i32,
}

fn span<T>(pointer: *const T, count: usize) -> Option<(usize, usize)> {
    if count == 0 { return Some((0, 0)); }
    let bytes = count.checked_mul(std::mem::size_of::<T>())?;
    let address = pointer as usize;
    if address == 0 || address % std::mem::align_of::<T>() != 0 || bytes > isize::MAX as usize {
        return None;
    }
    Some((address, address.checked_add(bytes)?))
}

/// Batch geometry in caller-owned output, -1 = no offending article, -2 = invalid span.
/// On invalid span/capacity, output is untouched. Empty input accepts null pointers.
///
/// # Safety
/// Nonempty input is initialized/readable for count RawArticle entries and output
/// is writable for count GeometryResult entries. Buffers are borrowed only for
/// this call and must be disjoint. Representable/aligned nonnull pointers must
/// still refer to live allocations; numeric validation cannot prove allocation validity.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_article_geometry(
    input: *const RawArticle, count: usize, decoded_size: i64,
    output: *mut GeometryResult, capacity: usize,
) -> i64 {
    if capacity < count || count > i64::MAX as usize { return -2; }
    let Some((input_start, input_end)) = span(input, count) else { return -2; };
    let Some((output_start, output_end)) = span(output.cast_const(), count) else { return -2; };
    if count == 0 { return -1; }
    if input_start < output_end && output_start < input_end { return -2; }
    // SAFETY: validated length/alignment and caller's live readable allocation.
    let raw = unsafe { std::slice::from_raw_parts(input, count) };
    let articles: Vec<Article> = raw.iter().map(|a| Article {
        part: a.part, size: a.size, offset: a.offset, segment_size: a.segment_size,
        finished: a.finished != 0, borrowed: a.borrowed != 0,
    }).collect();
    for index in 0..count {
        let result = GeometryResult {
            expected_offset: expected_offset(&articles, index).unwrap_or(-1),
            expected_end: expected_end(&articles, index, decoded_size).unwrap_or(-1),
            aligned: i32::from(segment_aligned(&articles, index, decoded_size)),
        };
        // SAFETY: caller provides writable storage; output may be uninitialized.
        // Use raw writes instead of forming references to uninitialized results.
        unsafe { output.add(index).write(result); }
    }
    first_untiled(&articles, decoded_size).map_or(-1, |index| index as i64)
}

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
    include!("../tests/articlegeometry_boundary_contracts.rs");
    include!("../tests/articlegeometry_abi_contracts.rs");
}
