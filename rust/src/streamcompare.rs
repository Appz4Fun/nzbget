//! Stream-repair identity comparison floor; borrowed C++ ranges keep their ownership.

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Range {
    pub offset: i64,
    pub size: i64,
}

impl Range {
    fn end(self) -> i64 { self.offset.wrapping_add(self.size) }
}

/// Matches the defined C++ arithmetic domain. Every probe index must identify a donor.
/// Overflowing C++ arithmetic is outside the port's parity contract.
pub fn required_compare_floor(decoded: i64, holes: &[Range], donors: &[Range], probes: &[i32]) -> i64 {
    let mut total = 0i64;
    let mut ordered = true;
    let mut positive = true;
    let mut previous_end = i64::MIN;
    for &hole in holes {
        total = total.wrapping_add(hole.size);
        positive &= hole.size >= 0;
        // Endpoints can overflow in input yet remain unevaluated in defined C++.
        // Exact subtraction keeps that evaluation order; never binary-search them.
        positive &= hole.end() >= hole.offset;
        ordered &= hole.offset >= previous_end;
        previous_end = hole.end();
    }
    let base = decoded.wrapping_sub(total).clamp(64, 16 * 1024);
    if probes.is_empty() { return base; }
    if holes.is_empty() {
        // With no subtraction, even reversed donor sizes contribute their raw size.
        let achievable = probes.iter().fold(0i64, |sum, &index| sum.wrapping_add(donors[index as usize].size));
        return if achievable >= 64 { base.min(achievable) } else { base };
    }
    for &index in probes {
        // Bounds checking also rejects negative indexes before the FFI can read a donor.
        let donor = donors[index as usize];
        positive &= donor.size >= 0;
        positive &= donor.end() >= donor.offset;
    }
    let achievable = if !positive {
        subtract_exact(holes, donors, probes)
    } else if ordered {
        available(holes, donors, probes)
    } else {
        let mut merged = holes.to_vec();
        merged.sort_unstable_by_key(|r| r.offset);
        let mut count = 0;
        for i in 0..merged.len() {
            let hole = merged[i];
            if count > 0 && hole.offset <= merged[count - 1].end() {
                let last = &mut merged[count - 1];
                last.size = last.end().max(hole.end()).wrapping_sub(last.offset);
            } else {
                merged[count] = hole;
                count += 1;
            }
        }
        available(&merged[..count], donors, probes)
    };
    if achievable >= 64 { base.min(achievable) } else { base }
}

fn available(holes: &[Range], donors: &[Range], probes: &[i32]) -> i64 {
    let mut total = 0i64;
    for &index in probes {
        let donor = donors[index as usize];
        let end = donor.end();
        let mut bytes = donor.size;
        // A linear scan avoids a binary-search setup on the usual handful of holes.
        let first = if holes.len() <= 8 { 0 } else { holes.partition_point(|hole| hole.end() <= donor.offset) };
        for &hole in &holes[first..] {
            if hole.offset >= end { break; }
            if hole.end() <= donor.offset { continue; }
            let overlap = end.min(hole.end()).wrapping_sub(donor.offset.max(hole.offset));
            bytes = bytes.wrapping_sub(overlap.max(0));
        }
        total = total.wrapping_add(bytes);
    }
    total
}

// Reversed holes have split/expansion quirks. Unevaluated overflowing endpoints
// also require the original subtraction order; a precomputed union is not equivalent.
fn subtract_exact(holes: &[Range], donors: &[Range], probes: &[i32]) -> i64 {
    let mut total = 0i64;
    for &index in probes {
        let mut present = vec![donors[index as usize]];
        let mut remaining = Vec::new();
        for &hole in holes {
            remaining.clear();
            for &range in &present {
                if !(range.offset < hole.end() && hole.offset < range.end()) {
                    remaining.push(range);
                } else {
                    if range.offset < hole.offset {
                        remaining.push(Range { offset: range.offset, size: hole.offset.wrapping_sub(range.offset) });
                    }
                    if hole.end() < range.end() {
                        remaining.push(Range { offset: hole.end(), size: range.end().wrapping_sub(hole.end()) });
                    }
                }
            }
            std::mem::swap(&mut present, &mut remaining);
        }
        for range in present { total = total.wrapping_add(range.size); }
    }
    total
}

/// # Safety
/// Nonempty arrays point to initialized, aligned contiguous Range/i32 values
/// readable for their counts and borrowed for this call. Counts fit isize::MAX
/// bytes. Empty arrays may be null. All probe indexes are valid donor indexes.
/// Panics abort with the production profile; none may unwind into C++.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_stream_compare_floor(
    decoded: i64, holes: *const Range, hole_count: usize,
    donors: *const Range, donor_count: usize, probes: *const i32, probe_count: usize,
) -> i64 {
    let holes = if hole_count == 0 { &[] } else { unsafe { std::slice::from_raw_parts(holes, hole_count) } };
    let donors = if donor_count == 0 { &[] } else { unsafe { std::slice::from_raw_parts(donors, donor_count) } };
    let probes = if probe_count == 0 { &[] } else { unsafe { std::slice::from_raw_parts(probes, probe_count) } };
    required_compare_floor(decoded, holes, donors, probes)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn r(offset: i64, size: i64) -> Range { Range { offset, size } }
    #[test]
    fn thresholds_and_base_use_raw_hole_sum() {
        for size in [0, 63, 64, 65, 16384, 20000] {
            let want = if size < 64 { 16384 } else { size.min(16384) };
            assert_eq!(required_compare_floor(100000, &[], &[r(0, size)], &[0]), want);
        }
        assert_eq!(required_compare_floor(100, &[r(0, 30), r(0, 30)], &[], &[]), 64);
        assert_eq!(required_compare_floor(-10, &[], &[], &[]), 64);
    }
    #[test]
    fn duplicates_unsorted_nested_adjacent_and_all_covered() {
        let donors = [r(0, 300), r(900, 100)];
        let holes = [r(100, 50), r(0, 100), r(125, 50), r(175, 25)];
        assert_eq!(required_compare_floor(100000, &holes, &donors, &[0, 0]), 200);
        assert_eq!(required_compare_floor(100000, &[r(-1, 302)], &donors, &[0]), 16384);
        assert_eq!(required_compare_floor(100000, &[r(300, 0)], &donors, &[0]), 300);
    }
    #[test]
    fn reversed_holes_preserve_the_cpp_expansion_quirk() {
        assert_eq!(required_compare_floor(100000, &[r(200, -100)], &[r(0, 300)], &[0]), 400);
        assert_eq!(required_compare_floor(100000, &[], &[r(100, -20), r(0, 100)], &[0, 1]), 80);
        assert_eq!(required_compare_floor(100000, &[r(50, 0)], &[r(0, 100)], &[0]), 100);
    }
    #[test]
    fn abi_borrows_inputs_and_accepts_null_empty_arrays() {
        let donors = [r(0, 100)];
        let probes = [0, 0];
        unsafe {
            assert_eq!(nzbget_rs_stream_compare_floor(100000, std::ptr::null(), 0,
                donors.as_ptr(), donors.len(), probes.as_ptr(), probes.len()), 200);
            assert_eq!(nzbget_rs_stream_compare_floor(100000, std::ptr::null(), 0,
                std::ptr::null(), 0, std::ptr::null(), 0), 16384);
        }
        assert_eq!(donors[0].size, 100);
        assert_eq!(std::mem::size_of::<Range>(), 16);
    }
    #[test]
    #[should_panic]
    fn invalid_probe_is_rejected_before_access() {
        required_compare_floor(100000, &[], &[r(0, 100)], &[-1]);
    }
    #[test]
    fn unused_overflowing_holes_keep_the_original_evaluation_order() {
        let mut holes = vec![r(0, 200)];
        holes.extend((0..8).map(|_| r(i64::MAX, 1)));
        assert_eq!(required_compare_floor(100000, &holes, &[r(0, 100)], &[0]), 16384);
    }
    #[test]
    fn defined_int64_boundaries() {
        assert_eq!(required_compare_floor(i64::MAX, &[r(i64::MAX - 20, 20)], &[r(i64::MAX - 100, 100)], &[0]), 80);
        assert_eq!(required_compare_floor(100000, &[r(i64::MIN, 20)], &[r(i64::MIN, 100)], &[0]), 80);
    }
}
