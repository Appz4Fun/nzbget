// Correctness fixture ABI only; no production export or speed control.
#[path="../src/articleidentity.rs"] mod identity;
use identity::{EncodedPart,FileIdentity,ContentEvidence};
#[repr(C)] struct Part {part:i32,size:i32}
#[repr(C)] pub struct RawFile {name:*const u8,name_len:usize,subject:*const u8,subject_len:usize,size:i64,total:i32,par:i32,parts:*const Part,count:usize}
#[repr(C)] pub struct Outcome {index:i64,hash:u64,declared:i32,structure:i32,steps:i32}
unsafe fn bytes<'a>(p:*const u8,n:usize)->&'a [u8] {unsafe {std::slice::from_raw_parts(p,n)}}
unsafe fn file(r:&RawFile)->FileIdentity {FileIdentity {name:unsafe{bytes(r.name,r.name_len)}.to_vec(),subject:unsafe{bytes(r.subject,r.subject_len)}.to_vec(),encoded_size:r.size,total_articles:r.total,is_par:r.par!=0,parts:unsafe {std::slice::from_raw_parts(r.parts,r.count)}.iter().map(|p|EncodedPart{part:p.part,size:p.size}).collect()}}
#[no_mangle] pub unsafe extern "C" fn test_identity(target:*const RawFile,donors:*const RawFile,count:usize,alternate:*const u8,alt_len:usize,evidence:*const u8,evidence_len:usize,fold:*const u8,space:*const u8)->Outcome {
 let target=unsafe{file(&*target)};let donors:Vec<_>=unsafe{std::slice::from_raw_parts(donors,count)}.iter().map(|r|unsafe{file(r)}).collect();let name=unsafe{bytes(evidence,evidence_len)};
 let proof=ContentEvidence::KnownName(name.to_vec());let fold:&[u8;256]=unsafe{&*(fold.cast())};let raw_space=unsafe{bytes(space,256)};let space=std::array::from_fn(|i|raw_space[i]!=0);
 Outcome {index:identity::match_donor_file_with_space(&target,&donors,unsafe{bytes(alternate,alt_len)},&proof,fold,&space).map_or(-1,|i|i as i64),hash:identity::size_steps_hash(&target),declared:identity::declared_parts_with_space(&target.subject,&space),structure:i32::from(identity::structure_matches_with_space(&target,&donors[0],&space)),steps:i32::from(identity::size_steps_match(&target,&donors[0]))}
}
