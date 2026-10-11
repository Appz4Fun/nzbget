//! The analyzer is called for every downloaded piece of each first article.
use nzbget_rs::renameanalyzer::Analyzer;
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

thread_local! {
    static ALLOCATIONS: Cell<Option<usize>> = const { Cell::new(None) };
}

struct CountingAllocator;

fn count() {
    let _ = ALLOCATIONS.try_with(|n| {
        if let Some(value) = n.get() { n.set(Some(value + 1)); }
    });
}

// Each operation delegates ownership and layout unchanged to System.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        count();
        System.alloc(layout)
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        count();
        System.alloc_zeroed(layout)
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        count();
        System.realloc(ptr, layout, size)
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        System.dealloc(ptr, layout)
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

#[test]
fn no_allocations_in_append_reset_or_finish() {
    let mut analyzer = Analyzer::default();
    let mut header = [0u8; 64];
    header[..8].copy_from_slice(b"PAR2\0PKT");
    ALLOCATIONS.with(|n| n.set(Some(0)));
    for _ in 0..100 {
        analyzer.reset();
        std::hint::black_box(analyzer.append(std::hint::black_box(&header)));
        std::hint::black_box(analyzer.append(b""));
        std::hint::black_box(analyzer.finish());
    }
    let allocations = ALLOCATIONS.with(|n| n.replace(None).unwrap());
    assert_eq!(allocations, 0);
}
