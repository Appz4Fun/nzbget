//! Test-only thread-local allocation observation, matching the existing
//! renameanalyzer allocation fixture. It never changes allocation results.
use std::alloc::{GlobalAlloc,Layout,System};
use std::cell::Cell;
#[derive(Clone,Copy,Default,Debug)]
pub(crate) struct Counts {pub calls:usize,pub largest:usize,pub total:usize}
thread_local! {static ACTIVE:Cell<Option<Counts>>=const{Cell::new(None)};}
struct ObservedSystem;
fn observe(bytes:usize){let _=ACTIVE.try_with(|cell|if let Some(mut n)=cell.get(){
    n.calls=n.calls.saturating_add(1);n.largest=n.largest.max(bytes);n.total=n.total.saturating_add(bytes);cell.set(Some(n));
});}
unsafe impl GlobalAlloc for ObservedSystem {
    unsafe fn alloc(&self,l:Layout)->*mut u8{observe(l.size());System.alloc(l)}
    unsafe fn alloc_zeroed(&self,l:Layout)->*mut u8{observe(l.size());System.alloc_zeroed(l)}
    unsafe fn realloc(&self,p:*mut u8,l:Layout,n:usize)->*mut u8{observe(n);System.realloc(p,l,n)}
    unsafe fn dealloc(&self,p:*mut u8,l:Layout){System.dealloc(p,l)}
}
#[global_allocator]
static ALLOCATOR:ObservedSystem=ObservedSystem;
pub(crate) fn measure<T>(f:impl FnOnce()->T)->(T,Counts){
    ACTIVE.with(|cell|{assert!(cell.get().is_none());cell.set(Some(Counts::default()));});
    struct Reset;impl Drop for Reset{fn drop(&mut self){let _=ACTIVE.try_with(|cell|cell.set(None));}}
    let reset=Reset;let result=f();let counts=ACTIVE.with(|cell|cell.replace(None).unwrap());drop(reset);(result,counts)
}
