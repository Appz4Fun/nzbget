// Test-only bridge: not exported by the production crate or a speed control.
#[path = "../src/articlefallback.rs"]
mod fallback;
use fallback::{LeadState, PinnedLead, Candidate};

#[repr(C)]
pub struct State { donor: i32, failures: i32, switches: i32 }
#[repr(C)]
pub struct Pin { donor: i32, next: i32, count: i32 }
#[repr(C)]
pub struct CandidateInput { bytes: *const u8, len: usize, donor: i32 }

fn native(state:&State)->LeadState { LeadState {donor_id:state.donor,failures:state.failures,switches:state.switches} }
fn native_pin(pin:&Pin)->PinnedLead { PinnedLead {donor_id:pin.donor,next_donor_id:pin.next,donor_count:pin.count} }
fn store(out:&mut State,state:LeadState) { out.donor=state.donor_id;out.failures=state.failures;out.switches=state.switches; }

#[no_mangle]
pub unsafe extern "C" fn test_lead_failure(state:*mut State,pin:*const Pin,round:i32)->i32 {
    let s=unsafe {&mut *state};let mut owned=native(s);
    let result=fallback::record_failure(&mut owned,native_pin(unsafe {&*pin}),round);
    store(s,owned);i32::from(result)
}

#[no_mangle]
pub unsafe extern "C" fn test_lead_success(state:*mut State,pin:*const Pin,round:i32,offset:i64,end:i64) {
    let s=unsafe {&mut *state};let mut owned=native(s);
    fallback::record_success(&mut owned,native_pin(unsafe {&*pin}),round,offset != -1 && end != -1);
    store(s,owned);
}

#[no_mangle]
pub unsafe extern "C" fn test_pin_sources(state:*mut State,input:*const CandidateInput,count:usize,
    cutover:i32,primary:*const u8,primary_len:usize,output:*mut u8,capacity:usize)->usize {
    // Fixture contract: live nonoverlapping initialized arrays, nonnull even if empty.
    let inputs=unsafe {std::slice::from_raw_parts(input,count)};
    let candidates:Vec<Candidate>=inputs.iter().map(|c| Candidate {
        message_id:unsafe {std::slice::from_raw_parts(c.bytes,c.len)}.to_vec(),donor_id:c.donor,
    }).collect();
    let s=unsafe {&mut *state};let mut owned=native(s);
    let pinned=fallback::pin_sources(&mut owned,&candidates,cutover!=0,unsafe {std::slice::from_raw_parts(primary,primary_len)});
    store(s,owned);
    let lead=pinned.lead();let mut data=Vec::new();
    for value in [lead.donor_id,lead.next_donor_id,lead.donor_count,owned.donor_id,owned.failures,owned.switches] {data.extend_from_slice(&value.to_le_bytes());}
    data.extend_from_slice(&(pinned.source_count() as u32).to_le_bytes());
    for index in 0..pinned.source_count() {
        let donor=pinned.donor_at(index);data.push(u8::from(donor.is_some()));
        data.extend_from_slice(&donor.unwrap_or(0).to_le_bytes());
        let bytes=pinned.source(index).unwrap();data.extend_from_slice(&(bytes.len() as u32).to_le_bytes());data.extend_from_slice(bytes);
    }
    assert!(capacity>=data.len());
    unsafe {std::ptr::copy_nonoverlapping(data.as_ptr(),output,data.len());}data.len()
}

#[no_mangle]
pub unsafe extern "C" fn test_next_source(input:*const CandidateInput,count:usize,cutover:i32,
    primary:*const u8,primary_len:usize,round:i32,blocked:*const i32,blocked_count:usize,next_round:*mut i32)->i64 {
    let candidates:Vec<Candidate>=unsafe {std::slice::from_raw_parts(input,count)}.iter().map(|c|Candidate {
        message_id:unsafe {std::slice::from_raw_parts(c.bytes,c.len)}.to_vec(),donor_id:c.donor,
    }).collect();
    let mut state=LeadState {donor_id:0,failures:0,switches:0};
    let pinned=fallback::pin_sources(&mut state,&candidates,cutover!=0,unsafe {std::slice::from_raw_parts(primary,primary_len)});
    let blocked=unsafe {std::slice::from_raw_parts(blocked,blocked_count)}.iter().copied().collect();
    match pinned.next_source(round,&blocked) {
        Some(selected)=>{unsafe {*next_round=selected.next_round};selected.index as i64},
        None=>-1,
    }
}
