//! Exact durable parser-input custody, independent of normal work admission.
//! The trusted C++ SAX adapter supplies its complete observed declaration map;
//! Rust owns bounded framing, reservations, replay and returned authority.
use super::*;

pub(super) const RAW_CAPTURE_TAG: u32 = 10;
pub(super) const INTAKE_TAG: u32 = 11;
const MAX_DECLARATIONS: usize = 1_000_000;
const MAX_ATTRIBUTES: usize = 1024;
// Complete held-path label bound: actual prefix, 16 domain bytes rendered as
// hexadecimal, separator, maximum u64 decimal width (including 20-digit IDs).
const HELD_POSTING_LABEL_BYTES: usize = b"NZBINTAKE1:".len() + 16 * 2 + 1 + 20;

#[cfg(test)]
mod tests {
    use super::*;
    fn raw(r: &subjects::IdReservation) -> RawCapture {
        let descriptor = Descriptor { device: 1, inode: 2, byte_length: 6,
            mode: 0o100600, owner: 1, links: 1, modified_seconds: 1,
            modified_nanoseconds: 0, changed_seconds: 1, changed_nanoseconds: 0 };
        RawCapture { schema_version: 1, domain: [1;16], publication_sequence: 0,
            request: [5;16], collection_id: 42, reservation_request: r.request,
            reservation_sequence: r.publication_sequence, incarnation: r.first,
            descriptor_identity: wire(&CapturedDescriptor {version:1,before:copy(&descriptor).unwrap(),after:descriptor}).unwrap(),
            parser_contract_version: 1, raw_nzb_bytes: b"<nzb/>".to_vec() }
    }
    #[test]
    fn raw_commit_precedes_parser_authority_exact_replay_survives_restart() {
        let mut h=subjects::tests::host();
        let mut r=Registry::initialize_with_high_water([1;16],0,&mut h).unwrap();
        let ids=r.reserve_ids(1,[4;16],1,&mut h).unwrap();
        let captured=r.store_intake_capture(raw(&ids),&mut h).unwrap();
        let binding=MemberBinding{collection_id:42,file_id:None,incarnation:ids.first,
            posting_source:r.intake_identity_before_commit(captured.request).unwrap().2};
        assert!(r.intake_subject_authority(captured.publication_sequence,&binding,None).is_err());
        let frames=h.frames.len();
        let replay=r.store_intake_capture(raw(&ids),&mut h).unwrap();
        assert_eq!(captured,replay);assert_eq!(h.frames.len(),frames);
        let mut changed=raw(&ids);changed.raw_nzb_bytes[1]=b'N';
        assert_eq!(r.store_intake_capture(changed,&mut h),Err(PurgeError::Conflict));
        let recovered=Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames).unwrap();
        assert_eq!(recovered.load_intake_capture([5;16],&h).unwrap(),captured);
        assert_eq!(recovered.load_intake_association([5;16],&h),Err(PurgeError::InvalidInput));
        assert_eq!(captured.raw_nzb_bytes,b"<nzb/>");
    }
    #[test]
    fn raw_capture_change_or_partial_publish_never_issues_authority() {
        let mut h=subjects::tests::host();
        let mut r=Registry::initialize_with_high_water([1;16],0,&mut h).unwrap();
        let ids=r.reserve_ids(1,[4;16],1,&mut h).unwrap();
        let mut changed=raw(&ids);let mut observation:CapturedDescriptor=unwire(&changed.descriptor_identity).unwrap();observation.after.inode+=1;changed.descriptor_identity=wire(&observation).unwrap();
        let before=h.frames.len();
        assert_eq!(r.store_intake_capture(changed,&mut h),Err(PurgeError::InvalidInput));
        assert_eq!(h.frames.len(),before);
        h.fail_at=Some(r.sequence+2);
        assert_eq!(r.store_intake_capture(raw(&ids),&mut h),Err(PurgeError::Persistence));
        assert_eq!(r.store_intake_capture(raw(&ids),&mut h),Err(PurgeError::RecoveryRequired));
    }
    #[test]
    fn uncertain_association_commit_never_returns_subject_authority(){
        let mut h=subjects::tests::host();let mut r=Registry::initialize([1;16],&mut h).unwrap();
        let ids=r.reserve_ids(1,[4;16],1,&mut h).unwrap();let captured=r.store_intake_capture(raw(&ids),&mut h).unwrap();
        let file=r.reserve_ids(1,[6;16],1,&mut h).unwrap();
        let binding=MemberBinding{collection_id:42,file_id:None,incarnation:ids.first,
            posting_source:r.intake_identity_before_commit(captured.request).unwrap().2};
        h.fail_at=Some(r.sequence+2);
        assert_eq!(r.store_intake_association(association(&captured,&file),&mut h),Err(PurgeError::Persistence));
        assert_eq!(r.intake_subject_authority(r.sequence+1,&binding,None),Err(PurgeError::RecoveryRequired));
    }
    fn association(c:&RawCapture,f:&subjects::IdReservation)->IntakeAssociation {
        IntakeAssociation { schema_version:1, domain:c.domain, publication_sequence:0,
            request:c.request, capture_publication_sequence:c.publication_sequence,
            capture_payload_identity:payload_identity(&wire(c).unwrap()), parser_contract_version:1,
            files:vec![EffectiveFile { declaration_ordinal:1,file_id:6,incarnation:f.first,
                reservation_request:f.request,reservation_sequence:f.publication_sequence,
                subject:b"a yEnc (1/1)".to_vec(),date:1,groups:vec![Group { bytes:b"alt.test".to_vec() }],
                articles:vec![EffectiveArticle { declaration_ordinal:1,part:1,bytes:7,message_id:b"<a>".to_vec() }] }],
            declarations:vec![Declaration { kind:1,file_ordinal:1,ordinal:1,
                attributes:vec![],characters:vec![],disposition:1,effective_file:1,effective_article:0,replacement_ordinal:0 },
                Declaration {kind:2,file_ordinal:1,ordinal:1,attributes:vec![],characters:b"a".to_vec(),
                    disposition:1,effective_file:1,effective_article:1,replacement_ordinal:0},
                Declaration {kind:3,file_ordinal:1,ordinal:1,attributes:vec![],characters:b"alt.test".to_vec(),
                    disposition:1,effective_file:1,effective_article:1,replacement_ordinal:0}] }
    }
    #[test]
    fn association_requires_complete_map_and_replays_original_label_receipt() {
        let mut h=subjects::tests::host();let mut r=Registry::initialize_with_high_water([1;16],0,&mut h).unwrap();
        let ids=r.reserve_ids(1,[4;16],1,&mut h).unwrap();let captured=r.store_intake_capture(raw(&ids),&mut h).unwrap();
        let f=r.reserve_ids(1,[6;16],1,&mut h).unwrap();
        let mut missing=association(&captured,&f);missing.declarations.pop();
        assert_eq!(r.store_intake_association(missing,&mut h),Err(PurgeError::InvalidInput));
        let committed=r.store_intake_association(association(&captured,&f),&mut h).unwrap();
        let label=r.intake_posting_source(&committed).unwrap();assert!(label.starts_with(b"NZBINTAKE1:"));
        let before=h.frames.len();assert_eq!(r.store_intake_association(association(&captured,&f),&mut h).unwrap(),committed);assert_eq!(before,h.frames.len());
        let binding=MemberBinding {collection_id:42,file_id:Some(6),incarnation:f.first,posting_source:label};
        r.validate_intake_binding(&binding).unwrap();
        let mut wrong=binding;wrong.incarnation=ids.first;assert_eq!(r.validate_intake_binding(&wrong),Err(PurgeError::InvalidInput));
        let recovered=Registry::recover([1;16],h.journal_identity().unwrap(),&h.frames).unwrap();
        assert_eq!(recovered.load_intake_association([5;16],&h).unwrap(),committed);
    }
// Mechanical formatting only; no invented association/custody/producer authority.
#[test]
fn held_label_twenty_digit_format_has_no_hidden_growth() {
    let c=subjects::HeldCapacity::new(19).unwrap();
    let (r,a)=crate::allocation_probe::measure(||posting_label_accounted([1;16],u64::MAX-1,Some(&c)));
    let r=r.unwrap();assert_eq!(r,b"NZBINTAKE1:01010101010101010101010101010101:18446744073709551614");
    assert_eq!(a.calls,1);assert_eq!(c.bytes(),19+r.capacity());c.drop_scratch(r).unwrap();assert_eq!(c.bytes(),19);
}
#[test]
fn held_label_sixty_three_remaining_rejects_before_allocation() {
    let c=subjects::HeldCapacity::new(MAX_PAYLOAD-63).unwrap();let before=c.bytes();
    let (r,a)=crate::allocation_probe::measure(||posting_label_accounted([1;16],u64::MAX-1,Some(&c)));
    assert!(matches!(r,Err(PurgeError::LimitExceeded)));assert_eq!(a.calls,0);assert_eq!(c.bytes(),before);
}
#[test]
fn held_label_boundary_keeps_ordinary_bytes() {
    for n in [9_999_999_999_999_999_999u64,10_000_000_000_000_000_000,u64::MAX-1] {
        let expected=format!("NZBINTAKE1:{}:{n}","01".repeat(16)).into_bytes();let c=subjects::HeldCapacity::new(0).unwrap();
        assert_eq!(posting_label_accounted([1;16],n,None).unwrap(),expected);
        let held=posting_label_accounted([1;16],n,Some(&c)).unwrap();assert_eq!(held,expected);assert_eq!(c.bytes(),held.capacity());
    }
}

}

#[derive(Debug,PartialEq,Eq)]
pub struct Descriptor {
    pub device:u64,pub inode:u64,pub byte_length:u64,pub mode:u32,pub owner:u32,pub links:u64,
    pub modified_seconds:i64,pub modified_nanoseconds:u32,pub changed_seconds:i64,pub changed_nanoseconds:u32,
}
fields!(Descriptor; device,inode,byte_length,mode,owner,links,modified_seconds,modified_nanoseconds,changed_seconds,changed_nanoseconds);
#[derive(Debug,PartialEq,Eq)]
pub struct CapturedDescriptor {pub version:u32,pub before:Descriptor,pub after:Descriptor}
fields!(CapturedDescriptor;version,before,after);
#[derive(Debug,PartialEq,Eq)]
pub struct RawCapture {
    pub schema_version:u32,pub domain:[u8;16],pub publication_sequence:u64,pub request:[u8;16],
    pub collection_id:i32,pub reservation_request:[u8;16],pub reservation_sequence:u64,pub incarnation:u64,
    pub descriptor_identity:Vec<u8>,pub parser_contract_version:u32,pub raw_nzb_bytes:Vec<u8>,
}
fields!(RawCapture, MAX_PAYLOAD; schema_version,domain,publication_sequence,request,collection_id,reservation_request,reservation_sequence,incarnation,
    descriptor_identity=>1024,parser_contract_version,raw_nzb_bytes=>MAX_PAYLOAD);
#[derive(Debug,PartialEq,Eq)]
pub struct Attribute {pub name:Vec<u8>,pub value:Vec<u8>}
fields!(Attribute,MAX_PAYLOAD;name=>MAX_IDENTITY,value=>MAX_PAYLOAD);
#[derive(Debug,PartialEq,Eq)]
pub struct EffectiveArticle {pub declaration_ordinal:u32,pub part:i32,pub bytes:i32,pub message_id:Vec<u8>}
fields!(EffectiveArticle,MAX_PAYLOAD;declaration_ordinal,part,bytes,message_id=>MAX_IDENTITY);
#[derive(Debug,PartialEq,Eq)]
pub struct Group { pub bytes:Vec<u8> }
fields!(Group,MAX_PAYLOAD;bytes=>MAX_IDENTITY);
#[derive(Debug,PartialEq,Eq)]
pub struct EffectiveFile {
    pub declaration_ordinal:u32,pub file_id:i32,pub incarnation:u64,pub reservation_request:[u8;16],pub reservation_sequence:u64,
    pub subject:Vec<u8>,pub date:i64,pub groups:Vec<Group>,pub articles:Vec<EffectiveArticle>,
}
fields!(EffectiveFile,MAX_PAYLOAD;declaration_ordinal,file_id,incarnation,reservation_request,reservation_sequence,subject=>MAX_IDENTITY,date,
    groups=>MAX_MEMBERS,articles=>MAX_DECLARATIONS);
// kind1 file, kind2 segment, kind3 group. Ordinals are per-kind one based.
// effective_article is the one-based article/group index for kinds2/3.
// Dispositions1 accepted,2 replaced by later segment,3 invalid,4 orphan,
// 5 discarded with file. No unresolved zero value is accepted.
#[derive(Debug,PartialEq,Eq)]
pub struct Declaration {
    pub kind:u32,pub file_ordinal:u32,pub ordinal:u32,pub attributes:Vec<Attribute>,pub characters:Vec<u8>,pub disposition:u32,
    pub effective_file:u32,pub effective_article:u32,pub replacement_ordinal:u32,
}
fields!(Declaration,MAX_PAYLOAD;kind,file_ordinal,ordinal,attributes=>MAX_ATTRIBUTES,characters=>MAX_PAYLOAD,disposition,effective_file,effective_article,replacement_ordinal);
#[derive(Debug,PartialEq,Eq)]
pub struct IntakeAssociation {
    pub schema_version:u32,pub domain:[u8;16],pub publication_sequence:u64,pub request:[u8;16],
    pub capture_publication_sequence:u64,pub capture_payload_identity:[u8;32],pub parser_contract_version:u32,
    pub files:Vec<EffectiveFile>,pub declarations:Vec<Declaration>,
}
fields!(IntakeAssociation,MAX_PAYLOAD;schema_version,domain,publication_sequence,request,capture_publication_sequence,capture_payload_identity,parser_contract_version,
    files=>MAX_MEMBERS,declarations=>MAX_DECLARATIONS);

// Return backing and payload identity are prepared BEFORE durable publication.
// No fallible digest/handle allocation remains after a successful commit.
#[derive(Debug,PartialEq,Eq)]
pub struct Committed<T> { pub record:T, pub payload_identity:[u8;32] }
impl<T> std::ops::Deref for Committed<T> { type Target=T;fn deref(&self)->&T{&self.record} }
fn committed<T:Wire>(record:&T)->Result<Committed<T>,PurgeError>{
    Ok(Committed {record:copy(record)?,payload_identity:payload_identity(&wire(record)?)})
}

fn text(v:&[u8],max:usize,empty:bool)->Result<(),PurgeError>{
    if v.len()>max || !empty&&v.is_empty() || v.contains(&0){Err(PurgeError::InvalidInput)}else{Ok(())}
}
impl Registry {
    fn intake_reservation(&self,request:[u8;16],sequence:u64,id:u64)->Result<(),PurgeError>{
        if id==0||id==u64::MAX{return Err(PurgeError::InvalidInput);}
        if self.id_reservations.iter().any(|r|r.id_namespace==1&&r.request==request&&r.publication_sequence==sequence&&r.first<=id&&id<=r.last){Ok(())}else{Err(PurgeError::InvalidInput)}
    }
    fn check_raw_capture(&self,c:&RawCapture)->Result<(),PurgeError>{
        if c.descriptor_identity.len()>1024{return Err(PurgeError::InvalidInput);}
        let observation:CapturedDescriptor=unwire(&c.descriptor_identity)?;let before=&observation.before;
        if c.schema_version!=1||c.domain!=self.domain||c.request==[0;16]||c.collection_id<=0||c.parser_contract_version!=1||c.raw_nzb_bytes.is_empty()
            ||c.raw_nzb_bytes.len()>MAX_PAYLOAD||observation.version!=1||observation.before!=observation.after||before.byte_length!=c.raw_nzb_bytes.len() as u64
            ||before.mode&0o170000!=0o100000||before.links==0||before.inode==0
            ||before.modified_nanoseconds>=1_000_000_000||before.changed_nanoseconds>=1_000_000_000 {return Err(PurgeError::InvalidInput);}
        self.intake_reservation(c.reservation_request,c.reservation_sequence,c.incarnation)?;
        if self.intake_captures.iter().any(|old|!std::ptr::eq(old,c)&&(old.request==c.request||old.incarnation==c.incarnation)){return Err(PurgeError::Conflict);}
        Ok(())
    }
    pub fn store_intake_capture(&mut self,mut c:RawCapture,host:&mut impl Host)->Result<Committed<RawCapture>,PurgeError>{
        self.ready(host)?;
        if c.publication_sequence!=0{return Err(PurgeError::InvalidInput);}
        if let Some(old)=self.intake_captures.iter().find(|old|old.request==c.request){
            c.publication_sequence=old.publication_sequence;
            return if &c==old{committed(old)}else{Err(PurgeError::Conflict)};
        }
        self.check_raw_capture(&c)?;
        c.publication_sequence=self.sequence.checked_add(wire(&c)?.len().div_ceil(CHUNK_BYTES) as u64+1).ok_or(PurgeError::LimitExceeded)?;
        let image=wire(&c)?;let output=Committed {record:copy(&c)?,payload_identity:payload_identity(&image)};
        self.resources(None,None,owned_size(&c)?,image.len().div_ceil(CHUNK_BYTES)+1)?;
        self.intake_captures.try_reserve_exact(1).map_err(|_|PurgeError::AllocationFailure)?;
        self.publish_image(RAW_CAPTURE_TAG,[0;16],0,&image,host)?;
        self.intake_captures.push(c);Ok(output)
    }
    pub fn load_intake_capture(&self,request:[u8;16],host:&impl Host)->Result<Committed<RawCapture>,PurgeError>{
        self.ready(host)?;
        committed(self.intake_captures.iter().find(|r|r.request==request).ok_or(PurgeError::InvalidInput)?)
    }
    fn check_association(&self,a:&IntakeAssociation)->Result<(),PurgeError>{self.check_association_accounted(a,None)}
    fn check_association_accounted(&self,a:&IntakeAssociation,capacity:Option<&subjects::HeldCapacity>)->Result<(),PurgeError>{
        let operation=||self.check_association_body(a,capacity);
        match capacity{Some(c)=>c.scratch(operation),None=>operation()}
    }
    fn check_association_body(&self,a:&IntakeAssociation,capacity:Option<&subjects::HeldCapacity>)->Result<(),PurgeError>{
        if a.schema_version!=1||a.domain!=self.domain||a.request==[0;16]||a.parser_contract_version!=1||a.files.is_empty()
            ||a.files.len()>MAX_MEMBERS||a.declarations.len()>MAX_DECLARATIONS {return Err(PurgeError::InvalidInput);}
        let c=self.intake_captures.iter().find(|c|c.request==a.request&&c.publication_sequence==a.capture_publication_sequence).ok_or(PurgeError::InvalidInput)?;
        if wire_identity_accounted(c,capacity)?!=a.capture_payload_identity||c.parser_contract_version!=a.parser_contract_version{return Err(PurgeError::InvalidInput);}
        if wire_length_accounted(a,capacity)?.checked_add(c.raw_nzb_bytes.len()).ok_or(PurgeError::LimitExceeded)?>MAX_PAYLOAD{return Err(PurgeError::LimitExceeded);}
        self.check_raw_capture(c)?;
        if self.intake_associations.iter().any(|old|!std::ptr::eq(old,a)&&old.request==a.request){return Err(PurgeError::Conflict);}
        let mut file_ids=reserved_accounted(a.files.len(),capacity)?;let mut incarnations=reserved_accounted(a.files.len(),capacity)?;
        let mut accepted_files=reserved_accounted(a.files.len(),capacity)?;accepted_files.resize(a.files.len(),false);
        let mut accepted_articles=reserved_accounted(a.files.len(),capacity)?;let mut accepted_groups=reserved_accounted(a.files.len(),capacity)?;
        for f in &a.files {
            if f.file_id<=0||f.incarnation==c.incarnation||f.declaration_ordinal==0||f.articles.is_empty()||f.articles.len()>MAX_DECLARATIONS||f.groups.len()>MAX_MEMBERS{return Err(PurgeError::InvalidInput);}
            self.intake_reservation(f.reservation_request,f.reservation_sequence,f.incarnation)?;
            text(&f.subject,MAX_IDENTITY,false)?;for g in &f.groups{text(&g.bytes,MAX_IDENTITY,false)?;}
            if self.intake_captures.iter().any(|raw|raw.incarnation==f.incarnation)||self.intake_associations.iter().any(|old|!std::ptr::eq(old,a)&&old.files.iter().any(|prior|prior.incarnation==f.incarnation)){return Err(PurgeError::Conflict);}
            file_ids.push(f.file_id);incarnations.push(f.incarnation);
            let mut seen=reserved_accounted(f.articles.len(),capacity)?;seen.resize(f.articles.len(),false);accepted_articles.push(seen);
            let mut seen_groups=reserved_accounted(f.groups.len(),capacity)?;seen_groups.resize(f.groups.len(),false);accepted_groups.push(seen_groups);
            let mut last=0;
            for article in &f.articles {
                if article.declaration_ordinal==0||article.part<=last{return Err(PurgeError::InvalidInput);}last=article.part;
                // Negative declared byte values are retained if the original parser accepted them.
                text(&article.message_id,MAX_IDENTITY,false)?;
            }
        }
        file_ids.sort_unstable();incarnations.sort_unstable();
        if file_ids.windows(2).any(|w|w[0]==w[1])||incarnations.windows(2).any(|w|w[0]==w[1]){return Err(PurgeError::InvalidInput);}
        let mut file_ordinal=0u32;let mut segment_ordinal=0u32;let mut group_ordinal=0u32;
        let mut segment_index=reserved_accounted(a.declarations.len(),capacity)?;
        for (index,d) in a.declarations.iter().enumerate(){if d.kind==2{segment_index.push((d.ordinal,index));}}
        segment_index.sort_unstable_by_key(|row|row.0);
        if segment_index.windows(2).any(|w|w[0].0==w[1].0){return Err(PurgeError::InvalidInput);}
        for d in &a.declarations {
            if !matches!(d.kind,1|2|3)||!matches!(d.disposition,1..=5)||d.attributes.len()>MAX_ATTRIBUTES{return Err(PurgeError::InvalidInput);}
            for attr in &d.attributes{text(&attr.name,MAX_IDENTITY,false)?;text(&attr.value,MAX_PAYLOAD,true)?;}
            text(&d.characters,MAX_PAYLOAD,true)?;
            if d.kind==1 {file_ordinal=file_ordinal.checked_add(1).ok_or(PurgeError::LimitExceeded)?;if d.ordinal!=file_ordinal||d.file_ordinal!=file_ordinal{return Err(PurgeError::InvalidInput);}}
            else {let ordinal=if d.kind==2{&mut segment_ordinal}else{&mut group_ordinal};*ordinal=ordinal.checked_add(1).ok_or(PurgeError::LimitExceeded)?;if d.ordinal!=*ordinal||d.file_ordinal>file_ordinal{return Err(PurgeError::InvalidInput);}}
            if d.disposition==1 {
                let fi=d.effective_file.checked_sub(1).ok_or(PurgeError::InvalidInput)? as usize;
                let f=a.files.get(fi).ok_or(PurgeError::InvalidInput)?;
                if d.file_ordinal!=f.declaration_ordinal||d.replacement_ordinal!=0{return Err(PurgeError::InvalidInput);}
                if d.kind==1 {
                    if d.effective_article!=0||accepted_files[fi]{return Err(PurgeError::InvalidInput);}accepted_files[fi]=true;
                }else if d.kind==2{
                    let ai=d.effective_article.checked_sub(1).ok_or(PurgeError::InvalidInput)? as usize;
                    if f.articles.get(ai).is_none_or(|article|article.declaration_ordinal!=d.ordinal)||*accepted_articles[fi].get(ai).ok_or(PurgeError::InvalidInput)?{return Err(PurgeError::InvalidInput);}
                    accepted_articles[fi][ai]=true;
                }else{
                    let gi=d.effective_article.checked_sub(1).ok_or(PurgeError::InvalidInput)? as usize;
                    if f.groups.get(gi).is_none_or(|group|group.bytes!=d.characters)||*accepted_groups[fi].get(gi).ok_or(PurgeError::InvalidInput)?{return Err(PurgeError::InvalidInput);}
                    accepted_groups[fi][gi]=true;
                }
            }else{
                if d.effective_file!=0||d.effective_article!=0{return Err(PurgeError::InvalidInput);}
                if d.disposition==2 {
                    if d.kind!=2||d.replacement_ordinal<=d.ordinal{return Err(PurgeError::InvalidInput);}
                    let index=segment_index.binary_search_by_key(&d.replacement_ordinal,|row|row.0).map_err(|_|PurgeError::InvalidInput)?;
                    let winner=&a.declarations[segment_index[index].1];
                    if winner.file_ordinal!=d.file_ordinal||winner.disposition!=1{return Err(PurgeError::InvalidInput);}
                }else if d.replacement_ordinal!=0{return Err(PurgeError::InvalidInput);}
                if d.disposition==4 && (d.kind==1||d.file_ordinal!=0){return Err(PurgeError::InvalidInput);}
            }
        }
        if accepted_files.contains(&false)||accepted_articles.iter().any(|rows|rows.contains(&false))||accepted_groups.iter().any(|rows|rows.contains(&false)){return Err(PurgeError::InvalidInput);}
        Ok(())
    }
    pub fn store_intake_association(&mut self,mut a:IntakeAssociation,host:&mut impl Host)->Result<Committed<IntakeAssociation>,PurgeError>{
        self.ready(host)?;
        if a.publication_sequence!=0{return Err(PurgeError::InvalidInput);}
        if let Some(old)=self.intake_associations.iter().find(|old|old.request==a.request){a.publication_sequence=old.publication_sequence;return if &a==old{committed(old)}else{Err(PurgeError::Conflict)};}
        self.check_association(&a)?;
        a.publication_sequence=self.sequence.checked_add(wire(&a)?.len().div_ceil(CHUNK_BYTES) as u64+1).ok_or(PurgeError::LimitExceeded)?;
        let image=wire(&a)?;let output=Committed {record:copy(&a)?,payload_identity:payload_identity(&image)};
        self.resources(None,None,owned_size(&a)?,image.len().div_ceil(CHUNK_BYTES)+1)?;
        self.intake_associations.try_reserve_exact(1).map_err(|_|PurgeError::AllocationFailure)?;
        self.publish_image(INTAKE_TAG,[0;16],0,&image,host)?;self.intake_associations.push(a);Ok(output)
    }
    pub fn load_intake_association(&self,request:[u8;16],host:&impl Host)->Result<Committed<IntakeAssociation>,PurgeError>{
        self.ready(host)?;
        let association=self.intake_associations.iter().find(|a|a.request==request).ok_or(PurgeError::InvalidInput)?;
        self.resolve_intake_custody(association.publication_sequence)?;
        committed(association)
    }
    fn resolve_intake_custody(&self,sequence:u64)->Result<(&IntakeAssociation,&RawCapture),PurgeError>{self.resolve_intake_custody_accounted(sequence,None)}
    fn resolve_intake_custody_accounted(&self,sequence:u64,capacity:Option<&subjects::HeldCapacity>)->Result<(&IntakeAssociation,&RawCapture),PurgeError>{
        if self.recovery_required{return Err(PurgeError::RecoveryRequired);}
        if sequence==0{return Err(PurgeError::InvalidInput);}
        let association=self.intake_associations.iter().find(|a|a.publication_sequence==sequence).ok_or(PurgeError::MissingInventory)?;
        let raw=self.intake_captures.iter().find(|c|c.request==association.request&&c.publication_sequence==association.capture_publication_sequence).ok_or(PurgeError::MissingInventory)?;
        // Both retained records, their exact link, complete map and namespace
        // reservations must remain valid. A nonzero reference is insufficient.
        self.check_association_accounted(association,capacity)?;
        Ok((association,raw))
    }
    pub(crate) fn validate_intake_owner(&self,a:&IntakeAssociation)->Result<(),PurgeError>{
        let (retained,_)=self.resolve_intake_custody(a.publication_sequence)?;
        if retained!=a{return Err(PurgeError::Conflict);}Ok(())
    }
    pub fn intake_subject_authority(&self,sequence:u64,binding:&MemberBinding,parent:Option<&MemberBinding>)->Result<(u64,[u8;32]),PurgeError>{
        self.intake_subject_authority_accounted(sequence,binding,parent,None)
    }
    fn intake_subject_authority_accounted(&self,sequence:u64,binding:&MemberBinding,parent:Option<&MemberBinding>,capacity:Option<&subjects::HeldCapacity>)->Result<(u64,[u8;32]),PurgeError>{
        let operation=||self.intake_subject_authority_body(sequence,binding,parent,capacity);
        match capacity{Some(c)=>c.scratch(operation),None=>operation()}
    }
    fn intake_subject_authority_body(&self,sequence:u64,binding:&MemberBinding,parent:Option<&MemberBinding>,capacity:Option<&subjects::HeldCapacity>)->Result<(u64,[u8;32]),PurgeError>{
        subjects::check_binding(binding)?;
        let (association,raw)=self.resolve_intake_custody_accounted(sequence,capacity)?;
        let (_,_,label)=self.intake_identity_before_commit_accounted(raw.request,capacity)?;
        if binding.collection_id!=raw.collection_id||binding.posting_source!=label{return Err(PurgeError::Conflict);}
        match (binding.file_id,parent){
            (None,None) if binding.incarnation==raw.incarnation=>(),
            (Some(file_id),Some(parent)) if parent.collection_id==raw.collection_id&&parent.file_id.is_none()
                &&parent.incarnation==raw.incarnation&&parent.posting_source==label
                &&association.files.iter().any(|file|file.file_id==file_id&&file.incarnation==binding.incarnation)=>(),
            _=>return Err(PurgeError::Conflict),
        }
        let mut reference=[0;32];reference[..16].copy_from_slice(&self.domain);
        reference[16..24].copy_from_slice(&association.publication_sequence.to_le_bytes());
        reference[24..].copy_from_slice(&binding.incarnation.to_le_bytes());
        Ok((binding.incarnation,reference))
    }
    pub(crate) fn validate_subject_custody(&self,record:&subjects::SubjectRecord)->Result<(),PurgeError>{self.validate_subject_custody_accounted(record,None)}
    pub(super) fn validate_subject_custody_accounted(&self,record:&subjects::SubjectRecord,capacity:Option<&subjects::HeldCapacity>)->Result<(),PurgeError>{
        let reference=record.custody.id;
        if reference[..16]!=self.domain||record.source.custody_receipt_id!=reference||record.source.id!=record.binding.incarnation
            ||record.source.binding!=record.binding||record.source.parent_collection!=record.parent{return Err(PurgeError::Conflict);}
        let sequence=u64::from_le_bytes(reference[16..24].try_into().map_err(|_|PurgeError::InvalidInput)?);
        let expected=self.intake_subject_authority_accounted(sequence,&record.binding,record.parent.as_ref(),capacity)?;
        if expected!=(record.source.id,reference){return Err(PurgeError::Conflict);}Ok(())
    }
    pub fn intake_posting_source(&self,a:&IntakeAssociation)->Result<Vec<u8>,PurgeError>{
        if self.recovery_required{return Err(PurgeError::RecoveryRequired);}
        if !self.intake_associations.iter().any(|old|old==a){return Err(PurgeError::InvalidInput);}
        let c=self.intake_captures.iter().find(|c|c.request==a.request).ok_or(PurgeError::InvalidInput)?;
        self.intake_identity_before_commit(c.request).map(|(_,_,label)|label)
    }
    // Only the ABI's private preallocation path uses this before association
    // publication. The label is never exported until a committed owner exists.
    pub(crate) fn intake_identity_before_commit(&self,request:[u8;16])->Result<(i32,u64,Vec<u8>),PurgeError>{self.intake_identity_before_commit_accounted(request,None)}
    fn intake_identity_before_commit_accounted(&self,request:[u8;16],capacity:Option<&subjects::HeldCapacity>)->Result<(i32,u64,Vec<u8>),PurgeError>{
        let c=self.intake_captures.iter().find(|c|c.request==request).ok_or(PurgeError::InvalidInput)?;
        let label=posting_label_accounted(c.domain,c.incarnation,capacity)?;
        Ok((c.collection_id,c.incarnation,label))
    }
    pub fn validate_intake_binding(&self,b:&MemberBinding)->Result<(),PurgeError>{
        subjects::check_binding(b)?;
        for a in &self.intake_associations {
            let c=self.intake_captures.iter().find(|c|c.request==a.request).ok_or(PurgeError::CorruptJournal)?;
            if c.collection_id!=b.collection_id||self.intake_posting_source(a)?!=b.posting_source{continue;}
            return match b.file_id {None if b.incarnation==c.incarnation=>Ok(()),Some(id) if a.files.iter().any(|f|f.file_id==id&&f.incarnation==b.incarnation)=>Ok(()),_=>Err(PurgeError::InvalidInput)};
        }
        Err(PurgeError::InvalidInput)
    }
    pub(crate) fn validate_intake_source(&self,binding:&MemberBinding,kind:u32,bytes:&[u8])->Result<(),PurgeError>{
        self.validate_intake_binding(binding)?;
        for association in &self.intake_associations {
            if self.intake_posting_source(association)?==binding.posting_source {
                return source_codec::matches_intake(kind,bytes,binding,&association.files);
            }
        }
        Err(PurgeError::InvalidInput)
    }
    pub(super) fn recover_intake(&mut self,kind:u32,sequence:u64,bytes:&[u8])->Result<(),PurgeError>{
        match kind {
            RAW_CAPTURE_TAG=>{let c:RawCapture=unwire(bytes)?;if c.publication_sequence!=sequence{return Err(PurgeError::CorruptJournal);}self.check_raw_capture(&c)?;self.resources(None,None,owned_size(&c)?,0)?;append(&mut self.intake_captures,c)?;}
            INTAKE_TAG=>{let a:IntakeAssociation=unwire(bytes)?;if a.publication_sequence!=sequence{return Err(PurgeError::CorruptJournal);}self.check_association(&a)?;self.resources(None,None,owned_size(&a)?,0)?;append(&mut self.intake_associations,a)?;}
            _=>return Err(PurgeError::CorruptJournal),
        }Ok(())
    }
}

impl Registry {
    // Borrow-only candidates for the complete constructor preflight. No label,
    // wire, descriptor decode or successful authority is produced here.
    fn held_intake_candidates(&self,record:&subjects::SubjectRecord)->Result<(&IntakeAssociation,&RawCapture),PurgeError>{
        if self.recovery_required{return Err(PurgeError::RecoveryRequired);}
        let reference=record.custody.id;
        if reference[..16]!=self.domain{return Err(PurgeError::Conflict);}
        let sequence=u64::from_le_bytes(reference[16..24].try_into().map_err(|_|PurgeError::InvalidInput)?);
        if sequence==0{return Err(PurgeError::InvalidInput);}
        let association=self.intake_associations.iter().find(|a|a.publication_sequence==sequence).ok_or(PurgeError::MissingInventory)?;
        let raw=self.intake_captures.iter().find(|c|c.request==association.request&&c.publication_sequence==association.capture_publication_sequence).ok_or(PurgeError::MissingInventory)?;
        Ok((association,raw))
    }
    pub(super) fn held_intake_retained_budget<'registry>(&'registry self,record:&subjects::SubjectRecord,b:&mut subjects::HeldBudget<'registry>)->Result<(),PurgeError>{
        let (a,c)=self.held_intake_candidates(record)?;
        // Deduplicate only identical borrowed Registry objects, independently
        // for raw and association. Equal IDs/content in distinct allocations
        // do not exempt bytes. This sizing lookup is not custody validation.
        if !b.intake_raw.iter().flatten().any(|old|std::ptr::eq(*old,c)) {
            let slot=b.intake_raw.iter().position(Option::is_none).ok_or(PurgeError::InvalidInput)?;
            b.array::<RawCapture>(1)?;b.add(c.descriptor_identity.capacity())?;b.add(c.raw_nzb_bytes.capacity())?;
            b.intake_raw[slot]=Some(c);
        }
        if !b.intake_associations.iter().flatten().any(|old|std::ptr::eq(*old,a)) {
            let slot=b.intake_associations.iter().position(Option::is_none).ok_or(PurgeError::InvalidInput)?;
            b.array::<IntakeAssociation>(1)?;b.array::<EffectiveFile>(a.files.capacity())?;b.array::<Declaration>(a.declarations.capacity())?;
            for f in &a.files{
                b.add(f.subject.capacity())?;b.array::<Group>(f.groups.capacity())?;b.array::<EffectiveArticle>(f.articles.capacity())?;
                for g in &f.groups{b.add(g.bytes.capacity())?;}for article in &f.articles{b.add(article.message_id.capacity())?;}
            }
            for d in &a.declarations{b.array::<Attribute>(d.attributes.capacity())?;b.add(d.characters.capacity())?;for attr in &d.attributes{b.add(attr.name.capacity())?;b.add(attr.value.capacity())?;}}
            b.intake_associations[slot]=Some(a);
        }
        Ok(())
    }
    pub(super) fn held_intake_scratch_budget(&self,record:&subjects::SubjectRecord,b:&mut subjects::HeldBudget<'_>)->Result<(),PurgeError>{
        let (a,c)=self.held_intake_candidates(record)?;
        // Match check_association_body's actual scopes: wire identity and
        // wire length each drop BEFORE descriptor/map validation. This is
        // lifetime accounting, never raw/association identity deduplication.
        b.scratch(|phase|phase.add(subjects::held_wire_size(c)?))?;
        b.scratch(|phase|phase.add(subjects::held_wire_size(a)?))?;
        // CapturedDescriptor has no heap; fixed structs are already included
        // by the constructor. Every map validation Vec below coexists.
        b.scratch(|phase|{
            phase.array::<i32>(a.files.len())?;phase.array::<u64>(a.files.len())?;phase.array::<bool>(a.files.len())?;
            phase.array::<Vec<bool>>(a.files.len())?;phase.array::<Vec<bool>>(a.files.len())?;
            for f in &a.files{phase.array::<bool>(f.articles.len())?;phase.array::<bool>(f.groups.len())?;}
            phase.array::<(u32,usize)>(a.declarations.len())
        })?;
        // The issuer label is built only after the resolver released scratch.
        b.scratch(|phase|phase.add(HELD_POSTING_LABEL_BYTES))
    }
    pub(super) fn validate_held_intake_source(&self,record:&subjects::SubjectRecord,current:&[u8],capacity:&subjects::HeldCapacity)->Result<(),PurgeError>{
        let reference=record.custody.id;
        let sequence=u64::from_le_bytes(reference[16..24].try_into().map_err(|_|PurgeError::InvalidInput)?);
        // Share the original complete authoritative resolver, including raw
        // and every declaration/effective-map/reservation check. Do not scan
        // unrelated associations and allocate unaccounted labels.
        if record.source_kind!=2{return Err(PurgeError::Unsupported);}
        let (association,_)=self.resolve_intake_custody_accounted(sequence,Some(capacity))?;
        self.validate_subject_custody_accounted(record,Some(capacity))?;
        // The existing file-kind identity comparison uses borrowed slices only.
        source_codec::matches_intake(record.source_kind,current,&record.binding,&association.files)
    }
}

// Mechanical formatter shared by the ordinary and opt-in accounted issuer paths.
fn posting_label_accounted(domain:[u8;16],incarnation:u64,capacity:Option<&subjects::HeldCapacity>)->Result<Vec<u8>,PurgeError>{
        // Preserve the ordinary None reservation/emission behavior. Only the held
        // path needs a complete fixed bound and aggregate capacity admission.
        let requested=if capacity.is_some(){HELD_POSTING_LABEL_BYTES}else{10+32+1+20};
        let mut label=reserved_accounted(requested,capacity)?;
        if capacity.is_some()&&label.capacity()<HELD_POSTING_LABEL_BYTES{return Err(PurgeError::LimitExceeded);}
        // Prefix + domain hex + separator occupy 44 bytes, below the admitted
        // 64-byte bound. No push here can trigger a further allocation.
        label.extend_from_slice(b"NZBINTAKE1:");
        const HEX:&[u8;16]=b"0123456789abcdef";
        for b in domain{label.push(HEX[(b>>4)as usize]);label.push(HEX[(b&15)as usize]);}label.push(b':');
        let mut digits=[0u8;20];let mut at=digits.len();let mut value=incarnation;
        loop {at-=1;digits[at]=b'0'+(value%10)as u8;value/=10;if value==0{break;}}
        if capacity.is_some(){
            let final_length=label.len().checked_add(digits.len()-at).ok_or(PurgeError::LimitExceeded)?;
            if final_length>HELD_POSTING_LABEL_BYTES||final_length>label.capacity(){return Err(PurgeError::LimitExceeded);}
        }
        label.extend_from_slice(&digits[at..]);
        Ok(label)
}
