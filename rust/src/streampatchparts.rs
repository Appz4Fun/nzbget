//! Batched stream-repair donor selection, preserving the endpoint predicate.

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Range {
    pub offset: i64,
    pub size: i64,
}

/// Write ascending zero-based donor indices into caller-owned storage.
///
/// Like the C++ routine, endpoints and index +/- margin must be representable
/// in their signed types; endpoint/index overflow is outside the parity domain.
/// Negative margins mark no parts, including when the endpoint predicate hits.
/// Zero/negative sizes are deliberately not discarded.
pub fn select(donors: &[Range], holes: &[Range], margin: i32, output: &mut [i32]) -> usize {
    assert!(donors.len() <= i32::MAX as usize && output.len() >= donors.len());
    if donors.is_empty() || holes.is_empty() || margin < 0 {
        return 0;
    }
    // Estimated donor articles normally have monotonically increasing starts
    // and endpoints. Each hole then identifies one contiguous interval of
    // donor indices using two binary searches. Checking donor order costs one
    // pass; sparse holes avoid a separate query for every donor article.
    if donors.len() > 32
        && holes
            .len()
            .saturating_mul(2 * (donors.len().ilog2() as usize + 1))
            < donors.len()
        && donors.windows(2).all(|w| {
            w[0].offset <= w[1].offset
                && w[0].offset.wrapping_add(w[0].size) <= w[1].offset.wrapping_add(w[1].size)
        })
    {
        let mut spans = Vec::with_capacity(holes.len());
        for hole in holes {
            let from = donors.partition_point(|d| d.offset.wrapping_add(d.size) <= hole.offset);
            let to = donors.partition_point(|d| d.offset < hole.offset.wrapping_add(hole.size));
            if from < to {
                spans.push((
                    from.saturating_sub(margin as usize),
                    (to - 1 + margin as usize).min(donors.len() - 1),
                ));
            }
        }
        if !spans.windows(2).all(|w| w[0].0 <= w[1].0) {
            spans.sort_unstable_by_key(|s| s.0);
        }
        let mut written = 0;
        let mut next_index = 0;
        for (from, to) in spans {
            for j in from.max(next_index)..=to {
                // SAFETY: intervals are emitted only beyond next_index, each
                // index is < donors.len(), and output has at least that length.
                unsafe {
                    *output.get_unchecked_mut(written) = j as i32;
                }
                written += 1;
            }
            next_index = next_index.max(to + 1);
        }
        return written;
    }
    // Offset-sorted holes and prefix maximum endpoints preserve the exact
    // existential predicate even for nested, repeated or reversed intervals.
    let indexed = holes.len() > 8 && donors.len() > 32;
    let mut endpoints: Vec<(i64, i64)> = if indexed {
        holes
            .iter()
            .map(|h| (h.offset, h.offset.wrapping_add(h.size)))
            .collect()
    } else {
        Vec::new()
    };
    if !endpoints.windows(2).all(|w| w[0].0 <= w[1].0) {
        endpoints.sort_unstable_by_key(|h| h.0);
    }
    let mut maximum = i64::MIN;
    for hole in &mut endpoints {
        maximum = maximum.max(hole.1);
        hole.1 = maximum;
    }
    let mut cursor = 0;
    let mut previous_end = i64::MIN;
    let mut written = 0;
    let mut next_index = 0;
    for (i, donor) in donors.iter().enumerate() {
        let end = donor.offset.wrapping_add(donor.size);
        let hit = if indexed {
            if end >= previous_end {
                while cursor < endpoints.len() && unsafe { endpoints.get_unchecked(cursor).0 } < end
                {
                    cursor += 1;
                }
            } else {
                cursor = endpoints.partition_point(|h| h.0 < end);
            }
            previous_end = end;
            // SAFETY: the guarded sweep and partition_point both keep cursor
            // within 0..=endpoints.len(); the nonzero check permits cursor-1.
            cursor != 0 && unsafe { endpoints.get_unchecked(cursor - 1).1 } > donor.offset
        } else {
            holes
                .iter()
                .any(|h| donor.offset < h.offset.wrapping_add(h.size) && h.offset < end)
        };
        if hit {
            let from = i.saturating_sub(margin as usize).max(next_index);
            let to = (i + margin as usize).min(donors.len() - 1);
            // Hit indices increase, so their expanded intervals do too. Emit
            // each marked index once instead of allocating a picked bitmap.
            for j in from..=to {
                // SAFETY: intervals are emitted only beyond next_index, each
                // index is < donors.len(), and output has at least that length.
                unsafe {
                    *output.get_unchecked_mut(written) = j as i32;
                }
                written += 1;
            }
            next_index = to + 1;
        }
    }
    written
}

/// # Safety
/// `donors` and `holes` contain `donor_count`/`hole_count` contiguous aligned
/// Range representations; `output` is writable for `donor_count` i32 values.
/// They must not overlap. NULL is permitted only for an empty corresponding
/// slice. Counts must fit Rust slices, donor_count must fit i32, and the
/// arithmetic parity domain documented on `select` applies.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_stream_patch_parts(
    donors: *const Range,
    donor_count: usize,
    holes: *const Range,
    hole_count: usize,
    margin: i32,
    output: *mut i32,
) -> usize {
    if donor_count == 0 || hole_count == 0 || margin < 0 {
        return 0;
    }
    select(
        std::slice::from_raw_parts(donors, donor_count),
        std::slice::from_raw_parts(holes, hole_count),
        margin,
        std::slice::from_raw_parts_mut(output, donor_count),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn r(offset: i64, size: i64) -> Range {
        Range { offset, size }
    }
    fn picked(donors: &[Range], holes: &[Range], margin: i32) -> Vec<i32> {
        let mut output = vec![-1; donors.len()];
        let len = select(donors, holes, margin, &mut output);
        output.truncate(len);
        output
    }
    #[test]
    fn strict_boundaries_and_zero_size() {
        let donors = [r(0, 10), r(10, 10), r(20, 0), r(20, 10)];
        assert_eq!(picked(&donors, &[r(9, 11)], 0), [0, 1]);
        assert_eq!(picked(&donors, &[r(19, 2)], 0), [1, 2, 3]);
        assert_eq!(picked(&donors, &[r(20, 0)], 0), []);
    }
    #[test]
    fn negative_size_and_negative_margin() {
        assert_eq!(picked(&[r(10, -2)], &[r(7, 4)], 0), [0]);
        assert_eq!(picked(&[r(10, 2)], &[r(11, -2)], 0), []);
        assert_eq!(picked(&[r(0, 20)], &[r(2, 5)], -1), []);
    }
    #[test]
    fn shuffled_nested_duplicate_holes_preserve_indices() {
        let donors = [r(30, 10), r(0, 10), r(20, 10), r(0, 10), r(10, 10)];
        let holes = [
            r(35, 2),
            r(1, 1),
            r(1, 1),
            r(0, 3),
            r(100, 1),
            r(1, 0),
            r(-10, 1),
            r(5, -2),
            r(1, 1),
        ];
        assert_eq!(picked(&donors, &holes, 0), [0, 1, 3]);
        assert_eq!(picked(&donors, &holes, 1), [0, 1, 2, 3, 4]);
    }
    #[test]
    fn empty_and_extreme_defined_endpoints() {
        assert_eq!(picked(&[], &[r(0, 1)], 2), []);
        assert_eq!(picked(&[r(0, 1)], &[], 2), []);
        assert_eq!(
            picked(
                &[r(i64::MIN, 1), r(i64::MAX - 2, 2)],
                &[r(i64::MAX - 1, 1)],
                0
            ),
            [1]
        );
    }
    #[test]
    fn indexed_nested_holes_keep_maximum_endpoint() {
        let mut donors = vec![r(50, 1); 40];
        donors[1] = r(45, 1);
        let mut holes = vec![r(0, 100)];
        holes.extend((20..40).map(|offset| r(offset, 1)));
        assert_eq!(picked(&donors, &holes, 0), (0..40).collect::<Vec<i32>>());
    }
    #[test]
    fn ffi_empty_slices_allow_null() {
        let result = unsafe {
            nzbget_rs_stream_patch_parts(
                std::ptr::null(),
                0,
                std::ptr::null(),
                0,
                2,
                std::ptr::null_mut(),
            )
        };
        assert_eq!(result, 0);
    }
    #[test]
    fn sorted_fast_path_strict_and_reversed_hole_boundaries() {
        let donors: Vec<_> = (0..40).map(|i| r(i * 10, 10)).collect();
        assert_eq!(picked(&donors, &[r(100, 10)], 0), [10]);
        assert_eq!(picked(&donors, &[r(100, 0)], 0), []);
        let nested: Vec<_> = (0..40).map(|i| r(i * 100, 1000)).collect();
        assert_eq!(picked(&nested, &[r(400, -10)], 0), [0, 1, 2, 3]);
        assert_eq!(
            picked(&donors, &[r(300, 10), r(100, 10), r(100, 10)], 1),
            [9, 10, 11, 29, 30, 31]
        );
    }
    #[test]
    fn sorted_sparse_and_dense() {
        let donors: Vec<_> = (0..1000).map(|i| r(i * 100, 100)).collect();
        let sparse: Vec<_> = (0..10).map(|i| r(i * 10000 + 50, 1)).collect();
        let out = picked(&donors, &sparse, 2);
        assert_eq!(out.len(), 48);
        let dense: Vec<_> = (0..1000).map(|i| r(i * 100 + 50, 1)).collect();
        assert_eq!(picked(&donors, &dense, 2), (0..1000).collect::<Vec<i32>>());
    }
}
