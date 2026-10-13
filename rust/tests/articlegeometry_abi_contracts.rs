// ABI contracts authored before the ABI implementation, correctness only.
#[test]
fn abi_empty_null_is_valid_and_bad_capacity_writes_nothing() {
    assert_eq!(unsafe { nzbget_rs_article_geometry(std::ptr::null(), 0, 100, std::ptr::null_mut(), 0) }, -1);
    let input = [RawArticle { part: 1, size: 110, offset: 0, segment_size: 100, finished: 1, borrowed: 0 }];
    let mut out = GeometryResult { expected_offset: 123, expected_end: 456, aligned: 789 };
    assert_eq!(unsafe { nzbget_rs_article_geometry(input.as_ptr(), 1, 100, &mut out, 0) }, -2);
    assert_eq!((out.expected_offset, out.expected_end, out.aligned), (123,456,789));
    assert_eq!(unsafe { nzbget_rs_article_geometry(std::ptr::null(), 1, 100, &mut out, 1) }, -2);
    assert_eq!((out.expected_offset, out.expected_end, out.aligned), (123,456,789));
}

#[test]
fn abi_canaries_and_nonzero_flags_keep_layout_contract() {
    let input = [RawArticle { part: 1, size: 110, offset: 0, segment_size: 100, finished: 255, borrowed: 2 }];
    let mut out = [GeometryResult { expected_offset: 123, expected_end: 456, aligned: 789 }; 3];
    assert_eq!(unsafe { nzbget_rs_article_geometry(input.as_ptr(), 1, 100, out.as_mut_ptr().add(1), 1) }, -1);
    assert_eq!((out[1].expected_offset,out[1].expected_end,out[1].aligned), (0,100,1));
    for i in [0,2] { assert_eq!((out[i].expected_offset,out[i].expected_end,out[i].aligned), (123,456,789)); }
}

#[test]
fn abi_rejects_overlap_misalignment_and_span_overflow_before_borrow() {
    let mut input = [RawArticle { part: 1, size: 110, offset: 0, segment_size: 100, finished: 1, borrowed: 0 }];
    let mut out = GeometryResult { expected_offset: 123, expected_end: 456, aligned: 789 };
    assert_eq!(unsafe { nzbget_rs_article_geometry(input.as_ptr(), 1, 100, input.as_mut_ptr().cast(), 1) }, -2);
    assert_eq!(input[0].part,1);
    assert_eq!(unsafe { nzbget_rs_article_geometry(3_usize as *const RawArticle, 1, 100, &mut out, 1) }, -2);
    assert_eq!(unsafe { nzbget_rs_article_geometry(input.as_ptr(), usize::MAX, 100, &mut out, usize::MAX) }, -2);
    assert_eq!((out.expected_offset,out.expected_end,out.aligned), (123,456,789));
}
