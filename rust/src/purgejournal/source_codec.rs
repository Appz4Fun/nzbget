//! Policy1 for the actual DiskState SaveNzbInfo64/SaveDupeExtras66 and
//! SaveFileInfo7/SaveFileState7 bodies. Mutable values are checked, not
//! historically authenticated. No caller-authored masks/projections.
use super::*;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn truncated_actual_stats_count_rejects_before_heap_allocation(){
        let mut lines=Lines::new(b"4096\n").unwrap();
        let (result,allocations)=crate::allocation_probe::measure(||stats(&mut lines));
        assert_eq!(result,Err(PurgeError::InvalidInput));
        assert_eq!(allocations.calls,0,"truncated declared stats allocated: {allocations:?}");
    }
    fn envelope(summary:&[u8],state:Option<&[u8]>)->Vec<u8>{
        let mut b=b"PURGE-SOURCE-BYTES1".to_vec();
        for n in [1u32,2,7,summary.len() as u32]{b.extend(n.to_le_bytes());}b.extend(summary);
        b.push(u8::from(state.is_some()));
        if let Some(s)=state{b.extend(7u32.to_le_bytes());b.push(0);b.extend((s.len()as u32).to_le_bytes());b.extend(s);}b
    }
    fn summary()->Vec<u8>{b"subject|literal\nfile\noriginal\noutput\n1,7\n0,20\n0,0\n0\n2,0\n1\nalt.test\n2\n1,10\n<first>\n2,10\n<second>\n".to_vec()}
    fn state()->Vec<u8>{b"0,0\n0,20,0,0,0,0\nfile\n\n\n0\n0\n2\n0,0,0,0,0\n0,0,0,0,0\n#decoded 0,20\n".to_vec()}
    #[test]
    fn actual_file_mutable_progress_keeps_projection_but_identity_changes_do_not(){
        let a=envelope(&summary(),Some(&state()));let first=project(2,&a).unwrap();
        let changed=state().strip_prefix(b"0,0").map(|tail|[b"1,0".as_slice(),tail].concat()).unwrap();
        assert_eq!(first,project(2,&envelope(&summary(),Some(&changed))).unwrap());
        let altered=summary().replace_bytes(b"<second>",b"<donor!>");
        assert_ne!(first,project(2,&envelope(&altered,Some(&state()))).unwrap());
    }
    trait ReplaceBytes{fn replace_bytes(&self,old:&[u8],new:&[u8])->Vec<u8>;}
    impl ReplaceBytes for Vec<u8>{fn replace_bytes(&self,old:&[u8],new:&[u8])->Vec<u8>{let i=self.windows(old.len()).position(|v|v==old).unwrap();[&self[..i],new,&self[i+old.len()..]].concat()}}
    #[test]
    fn actual_file_mutable_unknown_enum_count_truncation_reject(){
        // Delimit the article row: the undelimited substring also occurs in
        // the preceding size pair and would mutate remaining bytes 20 to 29.
        for (case,invalid) in [
            ("article status 9",state().replace_bytes(b"\n0,0,0,0,0\n",b"\n9,0,0,0,0\n")),
            ("article count mismatch",state().replace_bytes(b"\n2\n",b"\n3\n")),
            ("missing final LF",state()[..state().len()-1].to_vec()),
        ]{
            assert!(project(2,&envelope(&summary(),Some(&invalid))).is_err(),"case: {case}");
        }
        let mut a=envelope(&summary(),None);a.push(0);assert!(project(2,&a).is_err());
    }
    #[test]
    fn actual_file_mutable_size_accounting_rejects_inconsistent_totals(){
        // SaveFileState writes remaining/success/failed. NzbFile initializes
        // their sum to size-missed; completion, demotion and reset preserve it.
        // This is current-body consistency, not historical authentication.
        for (case,row) in [
            ("remaining exceeds available",b"0,29,0,0,0,0".as_slice()),
            ("success exceeds available",b"0,0,0,21,0,0".as_slice()),
            ("failed exceeds available",b"0,0,0,0,0,21".as_slice()),
            ("combined counters exceed available",b"0,10,0,10,0,10".as_slice()),
            ("unaccounted bytes",b"0,19,0,0,0,0".as_slice()),
        ]{
            let invalid=state().replace_bytes(b"0,20,0,0,0,0",row);
            assert!(project(2,&envelope(&summary(),Some(&invalid))).is_err(),"case: {case}");
        }
    }
    #[test]
    fn identity_65535_bytes_is_retained_without_utf8_or_delimiter_splitting(){
        let mut s=vec![0xff;65535];s.extend(&summary()[b"subject|literal".len()..]);
        let p=project(2,&envelope(&s,None)).unwrap();assert!(p.windows(65535).any(|v|v.iter().all(|b|*b==0xff)));
        s.insert(0,0xff);assert!(project(2,&envelope(&s,None)).is_err());
    }
    #[test]
    fn projection_size_pass_has_no_heap_and_matches_emitted_length(){
        let raw=envelope(&summary(),Some(&state()));
        let (length,allocations)=crate::allocation_probe::measure(||project_size(2,&raw));
        assert_eq!(allocations.calls,0,"sizing allocated: {allocations:?}");
        assert_eq!(length.unwrap(),project(2,&raw).unwrap().len());
    }
    #[test]
    fn stats_complete_rows_keep_duplicate_validation(){
        let mut valid=Lines::new(b"2\n2,1,0\n1,0,1\n").unwrap();
        assert_eq!(stats(&mut valid),Ok(()));assert_eq!(valid.done(),Ok(()));
        let mut duplicate=Lines::new(b"2\n1,1,0\n1,0,1\n").unwrap();
        assert_eq!(stats(&mut duplicate),Err(PurgeError::InvalidInput));
    }
    #[test]
    fn actual_writer_completion_demotion_reset_and_missed_bytes_stay_valid(){
        let baseline=project(2,&envelope(&summary(),None)).unwrap();
        // QueueCoordinator moves each article's advertised bytes from
        // remaining to success/failed; demotion transfers success to failed;
        // DiscardDownloadedArticles resets the same available byte total.
        for (case,counts,sizes,articles) in [
            ("initial/reset",b"0,0".as_slice(),b"0,20,0,0,0,0".as_slice(),b"0,0,0,0,0\n0,0,0,0,0\n".as_slice()),
            ("partial success",b"1,0".as_slice(),b"0,10,0,10,0,0".as_slice(),b"2,0,10,0,0\n0,0,0,0,0\n".as_slice()),
            ("success and failure",b"1,1".as_slice(),b"0,0,0,10,0,10".as_slice(),b"2,0,10,0,0\n3,0,0,0,0\n".as_slice()),
            ("all success",b"2,0".as_slice(),b"0,0,0,20,0,0".as_slice(),b"2,0,10,0,0\n2,10,10,0,0\n".as_slice()),
            ("demoted/failed",b"0,2".as_slice(),b"0,0,0,0,0,20".as_slice(),b"3,0,0,0,0\n3,0,0,0,0\n".as_slice()),
        ]{
            let current=state().replace_bytes(b"0,20,0,0,0,0",sizes).replace_bytes(b"0,0\n",&[counts,b"\n"].concat()).replace_bytes(b"0,0,0,0,0\n0,0,0,0,0\n",articles);
            assert_eq!(project(2,&envelope(&summary(),Some(&current))).unwrap(),baseline,"case: {case}");
        }
        // NzbFile records missing segments in summary size/missed, not in
        // mutable FailedSize. Only the two present ten-byte articles remain.
        let missing=summary().replace_bytes(b"0,20\n0,0\n",b"0,30\n0,10\n").replace_bytes(b"2,0\n",b"3,1\n").replace_bytes(b"\n2,10\n",b"\n3,10\n");
        assert_eq!(project(2,&envelope(&missing,Some(&state()))).unwrap(),project(2,&envelope(&missing,None)).unwrap());
    }
}

#[derive(Clone, Copy)]
struct Lines<'a>{bytes:&'a[u8],at:usize}
impl<'a> Lines<'a>{
    fn new(bytes:&'a[u8])->Result<Self,PurgeError>{
        if bytes.is_empty()||bytes.len()>MAX_PAYLOAD||bytes.last()!=Some(&b'\n')||bytes.contains(&0)||bytes.contains(&b'\r'){return Err(PurgeError::InvalidInput);}
        Ok(Self{bytes,at:0})
    }
    fn line(&mut self)->Result<&'a[u8],PurgeError>{
        let rest=self.bytes.get(self.at..).ok_or(PurgeError::InvalidInput)?;
        let n=rest.iter().position(|b|*b==b'\n').ok_or(PurgeError::InvalidInput)?;
        self.at=self.at.checked_add(n+1).ok_or(PurgeError::LimitExceeded)?;Ok(&rest[..n])
    }
    fn string(&mut self)->Result<&'a[u8],PurgeError>{let s=self.line()?;if s.len()>MAX_IDENTITY{return Err(PurgeError::LimitExceeded);}Ok(s)}
    // Held-file view is deliberately unsupported for overlong loader text.
    // Keep raw authority unchanged; do not truncate or alter ordinary policy.
    fn file_string(&mut self,policy:FileProgressPolicy)->Result<&'a[u8],PurgeError>{
        let value=self.string()?;
        if policy==FileProgressPolicy::HeldRecovery && value.len()>1022{return Err(PurgeError::LimitExceeded);}
        Ok(value)
    }
    fn numbers<const N:usize>(&mut self)->Result<[i64;N],PurgeError>{numbers(self.line()?)}
    fn count(&mut self,maximum:usize)->Result<usize,PurgeError>{let [n]=self.numbers()?;range(n,0,maximum as i64)?;Ok(n as usize)}
    fn done(&self)->Result<(),PurgeError>{if self.at==self.bytes.len(){Ok(())}else{Err(PurgeError::InvalidInput)}}
}
fn number(b:&[u8])->Result<i64,PurgeError>{
    let digits=b.strip_prefix(b"-").unwrap_or(b);
    if digits.is_empty()||!digits.iter().all(u8::is_ascii_digit){return Err(PurgeError::InvalidInput);}
    std::str::from_utf8(b).map_err(|_|PurgeError::InvalidInput)?.parse().map_err(|_|PurgeError::InvalidInput)
}
fn numbers<const N:usize>(b:&[u8])->Result<[i64;N],PurgeError>{
    let mut out=[0;N];let mut fields=b.split(|c|*c==b',');
    for value in &mut out{*value=number(fields.next().ok_or(PurgeError::InvalidInput)?)?;}
    if fields.next().is_some(){return Err(PurgeError::InvalidInput);}Ok(out)
}
fn range(n:i64,min:i64,max:i64)->Result<(),PurgeError>{if n<min||n>max{Err(PurgeError::InvalidInput)}else{Ok(())}}
fn i32n(n:i64)->Result<i32,PurgeError>{i32::try_from(n).map_err(|_|PurgeError::InvalidInput)}
fn u32n(n:i64)->Result<u32,PurgeError>{u32::try_from(n).map_err(|_|PurgeError::InvalidInput)}
fn nonnegative(n:i64)->Result<(),PurgeError>{range(n,0,i32::MAX as i64)}
fn boolean(n:i64)->Result<(),PurgeError>{range(n,0,1)}
fn pair(hi:i64,lo:i64)->Result<u64,PurgeError>{let n=(u64::from(u32n(hi)?)<<32)|u64::from(u32n(lo)?);if n>i64::MAX as u64{return Err(PurgeError::InvalidInput);}Ok(n)}
struct Projection { bytes: Vec<u8>, length: usize, counting: bool, fixed_limit:Option<usize> }
impl Projection {
    fn append(&mut self,b:&[u8])->Result<(),PurgeError>{
        let length=self.length.checked_add(b.len()).ok_or(PurgeError::LimitExceeded)?;
        if length>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}
        if !self.counting {
            if let Some(limit)=self.fixed_limit {
                if length>limit||length>self.bytes.capacity(){return Err(PurgeError::LimitExceeded);}
            }else{self.bytes.try_reserve(b.len()).map_err(|_|PurgeError::AllocationFailure)?;}
            self.bytes.extend_from_slice(b);
        }
        self.length=length;Ok(())
    }
    fn u32(&mut self,n:u32)->Result<(),PurgeError>{self.append(&n.to_le_bytes())}
    fn i32(&mut self,n:i64)->Result<(),PurgeError>{self.append(&i32n(n)?.to_le_bytes())}
    fn u64(&mut self,n:u64)->Result<(),PurgeError>{self.append(&n.to_le_bytes())}
    fn boolean(&mut self,n:i64)->Result<(),PurgeError>{boolean(n)?;self.append(&[n as u8])}
    fn text(&mut self,b:&[u8])->Result<(),PurgeError>{if b.len()>MAX_IDENTITY{return Err(PurgeError::LimitExceeded);}self.u32(b.len()as u32)?;self.append(b)}
}
fn stats(lines:&mut Lines<'_>)->Result<(),PurgeError>{stats_mode(lines,false)}
fn stats_mode(lines:&mut Lines<'_>,counting:bool)->Result<(),PurgeError>{
    stats_output(lines,counting,None,None,FileProgressPolicy::Strict)
}
// Raw-row scratch, not the public effective stat view. Preflight uses the
// actual type size; the ordinal fits because raw rows are bounded by MAX_MEMBERS.
#[derive(Clone,Copy)]
pub(super) struct HeldStatScratch {id:i32,first_ordinal:u32,success:i32,failed:i32}
fn stats_output(lines:&mut Lines<'_>,counting:bool,output:Option<&mut FileOutput<'_>>,capacity:Option<&subjects::HeldCapacity>,policy:FileProgressPolicy)->Result<(),PurgeError>{
    let operation=||stats_output_inner(lines,counting,output,capacity,policy);
    match capacity{Some(c)=>c.scratch(operation),None=>operation()}
}
fn stats_output_inner(lines:&mut Lines<'_>,counting:bool,mut output:Option<&mut FileOutput<'_>>,capacity:Option<&subjects::HeldCapacity>,policy:FileProgressPolicy)->Result<(),PurgeError>{
    let n=lines.count(MAX_MEMBERS)?;
    let rows=*lines;
    // Validate EVERY row before allocation, including overwritten rows. Shape
    // counts RAW rows; the eventual unique length never discounts capacity.
    for _ in 0..n{
        let [id,success,failed]=lines.numbers()?;range(id,1,i32::MAX as i64)?;nonnegative(success)?;nonnegative(failed)?;
        if let Some(out)=output.as_deref_mut(){
            out.shape.stats=out.shape.stats.checked_add(1).ok_or(PurgeError::LimitExceeded)?;
            if out.emitting && policy==FileProgressPolicy::Strict {held_push(&mut out.stats,subjects::HeldServerStat{persisted_state_id:id as i32,success_articles:success as i32,failed_articles:failed as i32})?;}
        }
    }
    if counting{return Ok(());}
    if policy==FileProgressPolicy::HeldRecovery {
        // Held projections validate the same rows but expose no stat output.
        // They must not fall back to Strict merely because output is None.
        let Some(out)=output.as_deref_mut() else{return Ok(());};
        if !out.emitting{return Ok(());}
        let mut rows=rows;let mut scratch=reserved_accounted::<HeldStatScratch>(n,capacity)?;
        for ordinal in 0..n{
            let [id,success,failed]=rows.numbers()?;
            scratch.push(HeldStatScratch{id:id as i32,first_ordinal:u32::try_from(ordinal).map_err(|_|PurgeError::LimitExceeded)?,success:success as i32,failed:failed as i32});
        }
        // Both sorts are in-place and allocate no backing. Preserve first
        // occurrence position, but use the final row's counters per ID.
        scratch.sort_unstable_by_key(|row|(row.id,row.first_ordinal));
        let (mut read,mut unique)=(0,0);
        while read<scratch.len(){
            let mut row=scratch[read];read+=1;
            while read<scratch.len() && scratch[read].id==row.id {
                row.success=scratch[read].success;row.failed=scratch[read].failed;read+=1;
            }
            scratch[unique]=row;unique+=1;
        }
        scratch[..unique].sort_unstable_by_key(|row|row.first_ordinal);
        for row in &scratch[..unique]{held_push(&mut out.stats,subjects::HeldServerStat{persisted_state_id:row.id,success_articles:row.success,failed_articles:row.failed})?;}
        // The enclosing scratch scope releases its charge only after this
        // backing is dropped; all pre-reserved output backing remains charged.
        return Ok(());
    }
    let mut rows=rows;let mut ids=reserved_accounted(n,capacity)?;
    for _ in 0..n{let [id,_,_]=rows.numbers()?;ids.push(id);}
    ids.sort_unstable();if ids.windows(2).any(|w|w[0]==w[1]){return Err(PurgeError::InvalidInput);}Ok(())
}
// Ordinary bodies stay strict. Held recovery is an explicit opt-in policy.
#[derive(Clone,Copy,PartialEq,Eq)]
enum FileProgressPolicy { Strict, HeldRecovery }
struct FileFacts<'a>{name:&'a[u8],par:i64,total:i64,articles:usize,available:u64}
fn file_summary<'a>(body:&'a[u8],p:&mut Projection)->Result<FileFacts<'a>,PurgeError>{file_summary_output(body,p,None,FileProgressPolicy::Strict)}
fn file_summary_output<'a>(body:&'a[u8],p:&mut Projection,mut output:Option<&mut FileOutput<'_>>,policy:FileProgressPolicy)->Result<FileFacts<'a>,PurgeError>{
    let mut l=Lines::new(body)?;
    let subject=l.file_string(policy)?;p.text(subject)?;let name=l.file_string(policy)?;p.text(name)?;
    let original=l.file_string(policy)?;p.text(original)?;let filename=l.file_string(policy)?;p.text(filename)?;
    let [confirmed,date]=l.numbers()?;p.boolean(confirmed)?;p.i32(date)?;
    let [hi,lo]=l.numbers()?;let size=pair(hi,lo)?;p.u64(size)?;
    let [hi,lo]=l.numbers()?;let missed_size=pair(hi,lo)?;if missed_size>size{return Err(PurgeError::InvalidInput);}p.u64(missed_size)?;let available=size-missed_size;
    let [par]=l.numbers()?;p.boolean(par)?;
    let [total,missed]=l.numbers()?;nonnegative(total)?;range(missed,0,total)?;p.i32(total)?;p.i32(missed)?;
    if let Some(out)=output.as_deref_mut(){
        out.summary=Some(subjects::HeldFileSummary{subject:out.span(subject)?,filename:out.span(name)?,original_name_disk:out.span(original)?,output_filename:out.span(filename)?,filename_confirmed:confirmed==1,time:date as i32,size:size as i64,missed_size:missed_size as i64,par_file:par==1,total_articles:total as i32,missed_articles:missed as i32,groups:Vec::new()});
    }
    let groups=l.count(MAX_MEMBERS)?;p.u32(groups as u32)?;
    for _ in 0..groups{let group=l.file_string(policy)?;p.text(group)?;if let Some(out)=output.as_deref_mut(){let span=out.span(group)?;if out.emitting{held_push(&mut out.groups,span)?;}}}
    let articles=l.count(1_000_000)?;if articles as i64+missed!=total{return Err(PurgeError::InvalidInput);}p.u32(articles as u32)?;
    if let Some(out)=output.as_deref_mut(){out.shape.groups=groups;out.shape.articles=articles;}
    let mut previous=0;
    for _ in 0..articles{
        let [part,size]=l.numbers()?;range(part,previous+1,i32::MAX as i64)?;previous=part;p.i32(part)?;p.i32(size)?;
        let id=l.file_string(policy)?;if id.is_empty(){return Err(PurgeError::InvalidInput);}p.text(id)?;
        if let Some(out)=output.as_deref_mut(){let span=out.span(id)?;if out.emitting{held_push(&mut out.articles,subjects::HeldArticle{part_number:part as i32,advertised_size:size as i32,message_id:span,progress:None})?;}}
    }
    l.done()?;Ok(FileFacts{name,par,total,articles,available})
}
fn file_state(body:&[u8],f:&FileFacts<'_>,completed:bool,counting:bool)->Result<(),PurgeError>{file_state_output(body,f,completed,counting,None,None,FileProgressPolicy::Strict)}
fn file_state_output(body:&[u8],f:&FileFacts<'_>,completed:bool,counting:bool,mut output:Option<&mut FileOutput<'_>>,capacity:Option<&subjects::HeldCapacity>,policy:FileProgressPolicy)->Result<(),PurgeError>{
    let mut l=Lines::new(body)?;let [success,failed]=l.numbers()?;range(success,0,f.total)?;range(failed,0,f.total-success)?;
    let sizes:[i64;6]=l.numbers()?;
    let remaining=pair(sizes[0],sizes[1])?;let success_bytes=pair(sizes[2],sizes[3])?;let failed_bytes=pair(sizes[4],sizes[5])?;
    // Same size-minus-missed current-body consistency as the existing writer.
    if remaining>f.available||success_bytes>f.available-remaining||failed_bytes!=f.available-remaining-success_bytes{return Err(PurgeError::InvalidInput);}
    let saved_name=l.file_string(policy)?;
    if policy==FileProgressPolicy::Strict && saved_name!=f.name{return Err(PurgeError::Conflict);}
    let effective_name=if saved_name.is_empty(){f.name}else{saved_name};
    let hash=l.file_string(policy)?;let parset=l.file_string(policy)?;
    let [par]=l.numbers()?;boolean(par)?;
    if policy==FileProgressPolicy::Strict && par!=f.par{return Err(PurgeError::Conflict);}stats_output(&mut l,counting,output.as_deref_mut(),capacity,policy)?;
    let persisted_articles=l.count(1_000_000)?;
    if persisted_articles>f.articles || policy==FileProgressPolicy::Strict && persisted_articles!=f.articles{return Err(PurgeError::InvalidInput);}
    let mut completed_articles=0i32;
    for index in 0..persisted_articles{
        let row=l.line()?;
        // Upstream format7 omits the local staged marker. Only held recovery
        // accepts that exact four-field shape; a present fifth stays boolean.
        let [status,offset,size,crc,staged]=if policy==FileProgressPolicy::HeldRecovery && row.split(|b|*b==b',').count()==4 {
            let [status,offset,size,crc]=numbers::<4>(row)?;[status,offset,size,crc,0]
        }else{numbers::<5>(row)?};
        range(status,0,3)?;range(offset,0,i64::MAX)?;nonnegative(size)?;u32n(crc)?;boolean(staged)?;
        if offset.checked_add(size).is_none()||staged==1&&(completed||status!=0){return Err(PurgeError::InvalidInput);}
        // Deterministic LoadFileState ordering, using PERSISTED row count.
        // Entering this loop proves count > 0. Completed selections bypass
        // only the sentinel; Running is always normalized in the held view.
        let mut semantic_status=status;
        let (mut semantic_offset,mut semantic_size)=(offset,size);
        if policy==FileProgressPolicy::HeldRecovery {
            // LoadFileState resets damaged incomplete ranges BEFORE Running
            // normalization and the sequential persisted-row sentinel.
            // Negative ranges remain explicitly unsupported by this codec.
            if !completed && size>1024*1024*1024 {
                semantic_status=0;semantic_offset=0;semantic_size=0;
            }
            if semantic_status==1{semantic_status=0;}
            if !completed && completed_articles as usize==persisted_articles-1{semantic_status=0;}
        }
        if semantic_status!=0{completed_articles=completed_articles.checked_add(1).ok_or(PurgeError::LimitExceeded)?;}
        // The saved staged marker stays RAW; it is not a filesystem witness.
        if let Some(out)=output.as_deref_mut(){if out.emitting{out.articles.get_mut(index).ok_or(PurgeError::InvalidInput)?.progress=Some(subjects::HeldArticleProgress{status:semantic_status as u32,segment_offset:semantic_offset,segment_size:semantic_size as i32,crc:crc as u32,staged_fallback:staged==1});}}
    }
    // Format7's decoded trailer is optional for held recovery. Exact EOF
    // means the fresh owned view's default zero, never a live object mutation.
    // Any PRESENT malformed/trailing record remains rejected.
    let decoded=if policy==FileProgressPolicy::HeldRecovery && l.at==l.bytes.len(){0}else{
        let tail=l.line()?.strip_prefix(b"#decoded ").ok_or(PurgeError::InvalidInput)?;
        let [hi,lo]=numbers(tail)?;pair(hi,lo)?
    };l.done()?;
    if let Some(out)=output.as_deref_mut(){
        out.progress=Some(subjects::HeldFileProgress{effective_filename:out.span(effective_name)?,effective_par_file:par==1,completed_selection:completed,success_articles:success as i32,failed_articles:failed as i32,remaining_size:remaining as i64,success_size:success_bytes as i64,failed_size:failed_bytes as i64,completed_articles,decoded_file_size:decoded as i64,hash16k:if hash.is_empty(){None}else{Some(out.span(hash)?)},par_set_id:if parset.is_empty(){None}else{Some(out.span(parset)?)}});
    }Ok(())
}

// An optional sink on the SAME existing field traversal; no second grammar.
#[derive(Clone,Copy,Debug,Default,PartialEq,Eq)]
// stats is RAW row count/reservation capacity, not effective unique output length.
pub(super) struct HeldFileShape {pub groups:usize,pub articles:usize,pub stats:usize}
pub(super) struct DecodedHeldFile {
    pub summary:subjects::HeldFileSummary,pub articles:Vec<subjects::HeldArticle>,
    pub progress:subjects::HeldFileProgress,pub stats:Vec<subjects::HeldServerStat>,
}
fn held_push<T>(rows:&mut Vec<T>,value:T)->Result<(),PurgeError>{
    if rows.len()==rows.capacity(){return Err(PurgeError::LimitExceeded);}
    rows.push(value);Ok(())
}
struct FileOutput<'a>{
    envelope:&'a[u8],capacity:Option<&'a subjects::HeldCapacity>,emitting:bool,shape:HeldFileShape,summary:Option<subjects::HeldFileSummary>,
    groups:Vec<subjects::EnvelopeSpan>,articles:Vec<subjects::HeldArticle>,progress:Option<subjects::HeldFileProgress>,stats:Vec<subjects::HeldServerStat>,
}
impl FileOutput<'_>{
    fn span(&self,bytes:&[u8])->Result<subjects::EnvelopeSpan,PurgeError>{
        let begin=(bytes.as_ptr() as usize).checked_sub(self.envelope.as_ptr() as usize).ok_or(PurgeError::InvalidInput)?;
        let end=begin.checked_add(bytes.len()).ok_or(PurgeError::LimitExceeded)?;
        if end>self.envelope.len(){return Err(PurgeError::InvalidInput);}Ok(subjects::EnvelopeSpan{begin,len:bytes.len()})
    }
}
fn walk_held_file(out:&mut FileOutput<'_>)->Result<(),PurgeError>{
    let e=Envelope::parse(2,out.envelope)?;let state=e.second.ok_or(PurgeError::InvalidInput)?;
    let mut p=Projection{bytes:Vec::new(),length:0,counting:true,fixed_limit:None};
    let facts=file_summary_output(e.body,&mut p,Some(out),FileProgressPolicy::HeldRecovery)?;
    let capacity=out.capacity;
    file_state_output(state,&facts,e.completed,!out.emitting,Some(out),capacity,FileProgressPolicy::HeldRecovery)
}
pub(super) fn held_file_shape(bytes:&[u8])->Result<HeldFileShape,PurgeError>{
    let mut out=FileOutput{envelope:bytes,capacity:None,emitting:false,shape:HeldFileShape::default(),summary:None,groups:Vec::new(),articles:Vec::new(),progress:None,stats:Vec::new()};
    walk_held_file(&mut out)?;Ok(out.shape)
}
pub(super) fn decode_held_file(bytes:&[u8],shape:HeldFileShape)->Result<DecodedHeldFile,PurgeError>{
    decode_held_file_accounted(bytes,shape,None)
}
pub(super) fn decode_held_file_accounted(bytes:&[u8],shape:HeldFileShape,capacity:Option<&subjects::HeldCapacity>)->Result<DecodedHeldFile,PurgeError>{
    let operation=||{
        let mut out=FileOutput{envelope:bytes,capacity,emitting:true,shape:HeldFileShape::default(),summary:None,
            groups:reserved_accounted(shape.groups,capacity)?,articles:reserved_accounted(shape.articles,capacity)?,progress:None,stats:reserved_accounted(shape.stats,capacity)?};
        walk_held_file(&mut out)?;if out.shape!=shape{return Err(PurgeError::InvalidInput);}
        let mut summary=out.summary.ok_or(PurgeError::InvalidInput)?;summary.groups=out.groups;
        Ok(DecodedHeldFile{summary,articles:out.articles,progress:out.progress.ok_or(PurgeError::InvalidInput)?,stats:out.stats})
    };
    match capacity{Some(c)=>c.retained(operation),None=>operation()}
}

fn collection(body:&[u8],extras:&[u8],p:&mut Projection)->Result<(i32,Vec<i64>),PurgeError>{
    let mut l=Lines::new(body)?;
    let [id]=l.numbers()?;range(id,1,i32::MAX as i64)?;p.i32(id)?;
    let [kind]=l.numbers()?;range(kind,0,1)?;p.i32(kind)?;
    // URL, filename, dest, final, hardlink, meta, queued filename, name, category.
    for _ in 0..9{p.text(l.string()?)?;}
    let [priority,stage,delete_paused,many_dupe,feed]=l.numbers()?;
    i32n(priority)?;range(stage,0,15)?;boolean(delete_paused)?;boolean(many_dupe)?;nonnegative(feed)?;p.i32(feed)?;
    let statuses:[i64;9]=l.numbers()?;
    for (value,maximum) in statuses.into_iter().zip([5,5,2,3,3,3,7,3,6]){range(value,0,maximum)?;}
    for flag in l.numbers::<3>()?{boolean(flag)?;}
    for count in l.numbers::<3>()?{nonnegative(count)?;}
    let [min,max]=l.numbers()?;i32n(min)?;i32n(max)?;if min>max{return Err(PurgeError::InvalidInput);}p.i32(min)?;p.i32(max)?;
    let [full,force_full,force_repair,extra]=l.numbers()?;boolean(full)?;boolean(force_full)?;boolean(force_repair)?;nonnegative(extra)?;
    for hash in l.numbers::<2>()?{p.u32(u32n(hash)?)?;}
    for _ in 0..2{
        let values:[i64;6]=l.numbers()?;let total=pair(values[0],values[1])?;
        let successful=pair(values[2],values[3])?;let failed=pair(values[4],values[5])?;
        if successful>total||failed>total-successful{return Err(PurgeError::InvalidInput);}p.u64(total)?;
    }
    let [total,success,failed]=l.numbers()?;nonnegative(total)?;range(success,0,total)?;range(failed,0,total-success)?;p.i32(total)?;
    p.text(l.string()?)?;let [mode,score,hint]=l.numbers()?;range(mode,0,2)?;range(hint,0,2)?;p.i32(mode)?;p.i32(score)?;p.i32(hint)?;
    let elapsed:[i64;7]=l.numbers()?;pair(elapsed[0],elapsed[1])?;for seconds in &elapsed[2..]{nonnegative(*seconds)?;}
    let completed=l.count(MAX_MEMBERS)?;p.u32(completed as u32)?;let mut file_ids=if p.counting{Vec::new()}else{reserved(completed)?};
    for _ in 0..completed{
        let row=l.line()?;let mut fields=row.splitn(6,|b|*b==b',');
        let file_id=number(fields.next().ok_or(PurgeError::InvalidInput)?)?;range(file_id,1,i32::MAX as i64)?;p.i32(file_id)?;if !p.counting{file_ids.push(file_id);}
        let status=number(fields.next().ok_or(PurgeError::InvalidInput)?)?;range(status,0,3)?;p.i32(status)?;
        p.u32(u32n(number(fields.next().ok_or(PurgeError::InvalidInput)?)?)?)?;
        p.boolean(number(fields.next().ok_or(PurgeError::InvalidInput)?)?)?;
        p.text(fields.next().ok_or(PurgeError::InvalidInput)?)?;let parset=fields.next().ok_or(PurgeError::InvalidInput)?;
        if parset.contains(&b','){return Err(PurgeError::InvalidInput);}p.text(parset)?;p.text(l.string()?)?;p.text(l.string()?)?;
    }
    let [parameters,skip_scripts,skip_disk,desired_server]=l.numbers()?;range(parameters,0,MAX_MEMBERS as i64)?;
    p.u32(parameters as u32)?;p.boolean(skip_scripts)?;p.boolean(skip_disk)?;p.i32(desired_server)?;
    for _ in 0..parameters{
        let row=l.string()?;let at=row.iter().position(|b|*b==b'=').ok_or(PurgeError::InvalidInput)?;
        if at==0{return Err(PurgeError::InvalidInput);}p.text(&row[..at])?;p.text(&row[at+1..])?;
    }
    let scripts=l.count(MAX_MEMBERS)?;
    for _ in 0..scripts{
        let row=l.line()?;let at=row.iter().position(|b|*b==b',').ok_or(PurgeError::InvalidInput)?;
        range(number(&row[..at])?,0,2)?;if row.len()-at-1>MAX_IDENTITY{return Err(PurgeError::LimitExceeded);}
    }
    stats_mode(&mut l,p.counting)?;
    let active=l.count(MAX_MEMBERS)?;p.u32(active as u32)?;
    if !p.counting{file_ids.try_reserve_exact(active).map_err(|_|PurgeError::AllocationFailure)?;}
    for _ in 0..active{let [file_id,paused,extra]=l.numbers()?;range(file_id,1,i32::MAX as i64)?;boolean(paused)?;boolean(extra)?;p.i32(file_id)?;if !p.counting{file_ids.push(file_id);}}
    l.done()?;file_ids.sort_unstable();if file_ids.windows(2).any(|w|w[0]==w[1]){return Err(PurgeError::InvalidInput);}
    let mut e=Lines::new(extras)?;let [recovered,hi,lo,holes]=e.numbers()?;nonnegative(recovered)?;pair(hi,lo)?;nonnegative(holes)?;
    let repairs=e.count(100000)?;let mut repair_ids=if p.counting{Vec::new()}else{reserved(repairs)?};
    for _ in 0..repairs{
        let row:[i64;11]=e.numbers()?;range(row[0],1,i32::MAX as i64)?;
        if !p.counting{if file_ids.binary_search(&row[0]).is_err(){return Err(PurgeError::InvalidInput);}repair_ids.push(row[0]);}
        let decoded=pair(row[1],row[2])?;pair(row[3],row[4])?;pair(row[5],row[6])?;boolean(row[7])?;nonnegative(row[8])?;
        // StepsHash is uint64 cast through SplitInt64; its high bit is valid.
        u32n(row[9])?;u32n(row[10])?;e.string()?;
        let count=e.count(1_000_000)?;
        for _ in 0..count{let [oh,ol,sh,sl]=e.numbers()?;let offset=pair(oh,ol)?;let size=pair(sh,sl)?;
            if size==0||offset>decoded||size>decoded-offset{return Err(PurgeError::InvalidInput);}}
    }
    e.done()?;repair_ids.sort_unstable();if repair_ids.windows(2).any(|w|w[0]==w[1]){return Err(PurgeError::InvalidInput);}Ok((id as i32,file_ids))
}

pub(super) struct Envelope<'a>{pub kind:u32,pub body:&'a[u8],pub second:Option<&'a[u8]>,pub completed:bool}
impl<'a> Envelope<'a>{
    pub(super) fn parse(kind:u32,bytes:&'a[u8])->Result<Self,PurgeError>{
        if bytes.len()>MAX_PAYLOAD||!bytes.starts_with(b"PURGE-SOURCE-BYTES1"){return Err(PurgeError::InvalidInput);}
        let mut r=Reader{held_capacity:None,bytes,offset:19,owned:0,owned_limit:MAX_PAYLOAD};
        if u32::get(&mut r)?!=1||u32::get(&mut r)?!=kind{return Err(PurgeError::InvalidInput);}
        let version=u32::get(&mut r)?;
        // Exact original64/7 source bodies only. Old codecs never silently gain
        // source authority; explicit outer67/10 containers retain these codecs.
        if version!=if kind==1{64}else{7}{return Err(PurgeError::Unsupported);}
        let n=u32::get(&mut r)? as usize;let body=r.take(n)?;let mut completed=false;
        let second=match kind {
            1=>{if u32::get(&mut r)?!=66{return Err(PurgeError::Unsupported);}let n=u32::get(&mut r)?as usize;Some(r.take(n)?)},
            2=>match u8::get(&mut r)?{0=>None,1=>{if u32::get(&mut r)?!=7{return Err(PurgeError::Unsupported);}completed=bool::get(&mut r)?;let n=u32::get(&mut r)?as usize;Some(r.take(n)?)},_=>return Err(PurgeError::InvalidInput)},
            _=>return Err(PurgeError::InvalidInput),
        };
        if r.offset!=bytes.len(){return Err(PurgeError::InvalidInput);}Ok(Self{kind,body,second,completed})
    }
}
// Size/structure pass: no owned projection or duplicate-check scratch sets.
// Full membership/duplicate validation still runs in the emitting pass after
// the caller has included original, projection and exact retained-prior bytes.
pub(super) fn project_size(kind:u32,bytes:&[u8])->Result<usize,PurgeError>{
    project_size_policy(kind,bytes,FileProgressPolicy::Strict)
}
pub(super) fn project_size_held_file(bytes:&[u8])->Result<usize,PurgeError>{
    project_size_policy(2,bytes,FileProgressPolicy::HeldRecovery)
}
fn project_size_policy(kind:u32,bytes:&[u8],policy:FileProgressPolicy)->Result<usize,PurgeError>{
    let mut projection=Projection{bytes:Vec::new(),length:0,counting:true,fixed_limit:None};
    project_into_accounted(kind,bytes,&mut projection,None,policy)?;Ok(projection.length)
}
pub(super) fn project(kind:u32,bytes:&[u8])->Result<Vec<u8>,PurgeError>{
    let length=project_size(kind,bytes)?;
    let mut projection=Projection{bytes:reserved(length)?,length:0,counting:false,fixed_limit:None};
    project_into(kind,bytes,&mut projection)?;
    if projection.length!=length{return Err(PurgeError::InvalidInput);}Ok(projection.bytes)
}
pub(super) fn project_held_file(bytes:&[u8],capacity:&subjects::HeldCapacity)->Result<Vec<u8>,PurgeError>{
    capacity.retained(||{
        let length=project_size_held_file(bytes)?;
        let mut projection=Projection{bytes:capacity.reserved(length)?,length:0,counting:false,fixed_limit:Some(length)};
        project_into_accounted(2,bytes,&mut projection,Some(capacity),FileProgressPolicy::HeldRecovery)?;
        if projection.length!=length{return Err(PurgeError::InvalidInput);}Ok(projection.bytes)
    })
}
fn project_into(kind:u32,bytes:&[u8],projection:&mut Projection)->Result<(),PurgeError>{project_into_accounted(kind,bytes,projection,None,FileProgressPolicy::Strict)}
fn project_into_accounted(kind:u32,bytes:&[u8],projection:&mut Projection,capacity:Option<&subjects::HeldCapacity>,policy:FileProgressPolicy)->Result<(),PurgeError>{
    if capacity.is_some()&&kind!=2{return Err(PurgeError::Unsupported);}
    let e=Envelope::parse(kind,bytes)?;
    projection.append(b"PURGE-IMMUTABLE1")?;projection.u32(1)?;projection.u32(kind)?;
    match kind {
        1=>{collection(e.body,e.second.ok_or(PurgeError::InvalidInput)?,projection)?;},
        2=>{let facts=if policy==FileProgressPolicy::Strict{file_summary(e.body,projection)?}else{file_summary_output(e.body,projection,None,policy)?};if let Some(state)=e.second{file_state_output(state,&facts,e.completed,projection.counting,None,capacity,policy)?;}},
        _=>return Err(PurgeError::InvalidInput),
    }
    Ok(())
}

// The mechanical C++ held reader supplies these observations while retaining its
// descriptors. This framing check is not independent filesystem authentication.
pub(super) fn held_read(kind:u32,current:&[u8],observations:&[u8])->Result<(),PurgeError>{
    let e=Envelope::parse(kind,current)?;
    if observations.len()>32768{return Err(PurgeError::LimitExceeded);}
    let mut r=Reader{held_capacity:None,bytes:observations,offset:0,owned:0,owned_limit:32768};
    if u32::get(&mut r)?!=1{return Err(PurgeError::InvalidInput);}
    let expected=if kind==2&&e.second.is_some(){2}else{1};
    if u32::get(&mut r)?!=expected{return Err(PurgeError::InvalidInput);}
    for index in 0..expected {
        let role=u32::get(&mut r)?;
        if role!=if kind==1{1}else{2+index}{return Err(PurgeError::InvalidInput);}
        if u64::get(&mut r)?==0||u64::get(&mut r)?==0{return Err(PurgeError::InvalidInput);}
        let n=u32::get(&mut r)? as usize;
        if n==0||n>4096{return Err(PurgeError::InvalidInput);}let leaf=r.take(n)?;
        if leaf==b"."||leaf==b".."||leaf.iter().any(|b|matches!(*b,0|b'/'|b'\\')){return Err(PurgeError::InvalidInput);}
        let before=r.take(64)?;if before!=r.take(64)?{return Err(PurgeError::Conflict);}
        let mut stat=Reader{held_capacity:None,bytes:before,offset:0,owned:0,owned_limit:0};
        let dev=u64::get(&mut stat)?;let ino=u64::get(&mut stat)?;let size=u64::get(&mut stat)?;let links=u64::get(&mut stat)?;
        let mode=u32::get(&mut stat)?;u32::get(&mut stat)?;i64::get(&mut stat)?;let mns=u32::get(&mut stat)?;i64::get(&mut stat)?;let cns=u32::get(&mut stat)?;
        if dev==0||ino==0||links==0||mode&0o170000!=0o100000||mns>=1_000_000_000||cns>=1_000_000_000{return Err(PurgeError::InvalidInput);}
        let slices=u32::get(&mut r)?;if slices!=if kind==1{2}else{1}{return Err(PurgeError::InvalidInput);}
        let mut previous_end=0;
        for slice in 0..slices{
            let offset=u64::get(&mut r)?;let length=u64::get(&mut r)?;
            let expected_length=if kind==1&&slice==1||kind==2&&index==1{e.second.ok_or(PurgeError::InvalidInput)?.len()}else{e.body.len()};
            if length!=expected_length as u64||offset<previous_end||offset>size||length>size-offset{return Err(PurgeError::InvalidInput);}previous_end=offset+length;
        }
    }
    if r.offset!=observations.len(){return Err(PurgeError::InvalidInput);}Ok(())
}

// Intake provides the authoritative original article/group identity. Filename,
// paths and progress cannot substitute for this committed association.
pub(super) fn matches_intake(kind:u32,bytes:&[u8],binding:&MemberBinding,files:&[intake::EffectiveFile])->Result<(),PurgeError>{
    let e=Envelope::parse(kind,bytes)?;
    if kind==1 {
        let mut p=Projection{bytes:Vec::new(),length:0,counting:false,fixed_limit:None};let (id,used)=collection(e.body,e.second.ok_or(PurgeError::InvalidInput)?,&mut p)?;
        if id!=binding.collection_id||binding.file_id.is_some(){return Err(PurgeError::Conflict);}
        let mut known=reserved(files.len())?;for file in files{known.push(i64::from(file.file_id));}known.sort_unstable();
        if used.iter().any(|id|known.binary_search(id).is_err()){return Err(PurgeError::Conflict);}
        return Ok(());
    }
    let f=files.iter().find(|f|Some(f.file_id)==binding.file_id&&f.incarnation==binding.incarnation).ok_or(PurgeError::Conflict)?;
    let mut l=Lines::new(e.body)?;
    if l.string()?!=f.subject{return Err(PurgeError::Conflict);}
    for _ in 0..3{l.string()?;}
    let [_confirmed,date]=l.numbers()?;if date!=f.date{return Err(PurgeError::Conflict);}
    l.numbers::<2>()?;l.numbers::<2>()?;l.numbers::<1>()?;l.numbers::<2>()?;
    if l.count(MAX_MEMBERS)?!=f.groups.len(){return Err(PurgeError::Conflict);}
    for group in &f.groups{if l.string()?!=group.bytes{return Err(PurgeError::Conflict);}}
    if l.count(1_000_000)?!=f.articles.len(){return Err(PurgeError::Conflict);}
    for article in &f.articles {
        let [part,size]=l.numbers()?;
        if part!=i64::from(article.part)||size!=i64::from(article.bytes)||l.string()?!=article.message_id{return Err(PurgeError::Conflict);}
    }
    l.done()
}
