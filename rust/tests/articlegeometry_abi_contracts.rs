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

#[test]
fn abi_initializes_every_result_in_uninitialized_output() {
    let input = [RawArticle { part: 1, size: 110, offset: 0, segment_size: 100, finished: 1, borrowed: 0 }];
    let mut output = std::mem::MaybeUninit::<GeometryResult>::uninit();
    assert_eq!(unsafe { nzbget_rs_article_geometry(input.as_ptr(), 1, 100, output.as_mut_ptr(), 1) }, -1);
    // SAFETY: valid successful call initializes the complete result fields.
    let result = unsafe { output.assume_init() };
    assert_eq!((result.expected_offset, result.expected_end, result.aligned), (0,100,1));
}

#[test]
fn abi_rejects_address_endpoint_overflow_without_touching_output() {
    let pointer = (usize::MAX & !(std::mem::align_of::<RawArticle>() - 1)) as *const RawArticle;
    let mut output = GeometryResult { expected_offset: 123, expected_end: 456, aligned: 789 };
    assert_eq!(unsafe { nzbget_rs_article_geometry(pointer, 1, 100, &mut output, 1) }, -2);
    assert_eq!((output.expected_offset, output.expected_end, output.aligned), (123,456,789));
}

#[test]
fn abi_accepts_exactly_adjacent_input_and_output_spans() {
    #[repr(C)]
    struct Adjacent { input: RawArticle, output: std::mem::MaybeUninit<GeometryResult> }
    let mut buffer = Adjacent {
        input: RawArticle { part: 1, size: 110, offset: 0, segment_size: 100, finished: 1, borrowed: 0 },
        output: std::mem::MaybeUninit::uninit(),
    };
    let input = &buffer.input as *const RawArticle;
    let output = buffer.output.as_mut_ptr();
    assert_eq!(input as usize + std::mem::size_of::<RawArticle>(), output as usize);
    assert_eq!(unsafe { nzbget_rs_article_geometry(input, 1, 100, output, 1) }, -1);
    let result = unsafe { buffer.output.assume_init() };
    assert_eq!((result.expected_offset, result.expected_end, result.aligned), (0,100,1));
}
