//! Activated exact input custody ABI. No capture-only source/admission label.
use super::*;
use super::purge_subjects::{self as owned_abi,DurableReceiptC};
use journal::intake::{Committed,RawCapture};
use purge::PurgeError;

#[repr(C)]
#[derive(Clone,Copy)]
pub struct CaptureC {
    pub version:u32,pub struct_size:u32,pub request:[u8;16],pub collection_id:i32,pub reserved:u32,
    pub reservation_request:[u8;16],pub reservation_sequence:u64,pub incarnation:u64,
    pub descriptor_identity:PurgeBytesC,pub raw_nzb_bytes:PurgeBytesC,
    pub parser_contract_version:u32,pub reserved_parser:u32,
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct KeyC {pub version:u32,pub struct_size:u32,pub domain:[u8;16],pub request:[u8;16]}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct CaptureViewC {pub version:u32,pub struct_size:u32,pub capture:CaptureC,pub durable:DurableReceiptC}
pub struct CapturedInput {committed:Committed<RawCapture>,identity:[u8;32]}

/// # Safety
/// All counted immutable input spans stay valid for the synchronous call. Registry
/// access is exclusive and callbacks do not reenter. Outputs cannot alias inputs.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_capture_store(input:*const CaptureC,
    ops:*const PurgeHostOpsC,out:*mut *mut CapturedInput,error:*mut i32)->i32
{
    let input=purge_versioned(input).copied();let ops=purge_host_ops(ops);
    owned_abi::owned(out,error,||{
        let c=input?;let ops=ops?;
        if c.reserved!=0||c.reserved_parser!=0{return Err(PurgeError::InvalidInput);}
        let mut budget=purge::Budget::new();budget.table::<RawCapture>(1)?;
        let descriptor=purge_raw_bytes(c.descriptor_identity,1024,&mut budget)?;
        let raw=purge_raw_bytes(c.raw_nzb_bytes,purge::MAX_PAYLOAD,&mut budget)?;
        // Preflight complete recursive owned memory before copying raw bytes.
        let registry=ops.registry.as_mut().ok_or(PurgeError::RecoveryRequired)?;
        let identity=journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let record=RawCapture {schema_version:1,domain:registry.inner.journal_domain(),publication_sequence:0,
            request:c.request,collection_id:c.collection_id,reservation_request:c.reservation_request,
            reservation_sequence:c.reservation_sequence,incarnation:c.incarnation,
            descriptor_identity:purge::copy_bytes(descriptor)?,parser_contract_version:c.parser_contract_version,
            raw_nzb_bytes:purge::copy_bytes(raw)?};
        let committed=registry.inner.store_intake_capture(record,&mut PurgeHostAdapter(&ops))?;
        Ok(CapturedInput {committed,identity})
    })
}
/// # Safety
/// Key/ops/output are aligned and alive; exclusive registry access as above.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_capture_load(input:*const KeyC,
    ops:*const PurgeHostOpsC,out:*mut *mut CapturedInput,error:*mut i32)->i32
{
    let input=purge_versioned(input).copied();let ops=purge_host_ops(ops);
    owned_abi::owned(out,error,||{
        let key=input?;let ops=ops?;let registry=purge_record(ops.registry)?;
        if key.domain!=registry.inner.journal_domain(){return Err(PurgeError::Conflict);}
        let identity=journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let committed=registry.inner.load_intake_capture(key.request,&PurgeHostAdapter(&ops))?;
        Ok(CapturedInput {committed,identity})
    })
}
/// # Safety
/// Owner remains alive throughout view consumption. Raw parser bytes are immutable.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_capture_view(input:*const CapturedInput,
    out:*mut CaptureViewC,error:*mut i32)->i32
{
    owned_abi::view(out,error,||{
        let owned=purge_record(input)?;let r=&owned.committed.record;
        Ok(CaptureViewC {version:1,struct_size:std::mem::size_of::<CaptureViewC>() as u32,
            capture:CaptureC {version:1,struct_size:std::mem::size_of::<CaptureC>() as u32,
                request:r.request,collection_id:r.collection_id,reserved:0,reservation_request:r.reservation_request,
                reservation_sequence:r.reservation_sequence,incarnation:r.incarnation,
                descriptor_identity:purge_view(&r.descriptor_identity),raw_nzb_bytes:purge_view(&r.raw_nzb_bytes),
                parser_contract_version:r.parser_contract_version,reserved_parser:0},
            durable:owned_abi::receipt(r.domain,r.publication_sequence,&owned.identity,owned.committed.payload_identity)})
    })
}
/// # Safety
/// Null or an unconsumed owned handle from capture_store/load, destroyed once.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_capture_destroy(input:*mut CapturedInput){owned_abi::destroy(input);}

#[repr(C)]
#[derive(Clone,Copy)]
pub struct AttributeC {pub name:PurgeBytesC,pub value:PurgeBytesC}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct ArticleC {pub declaration_ordinal:u32,pub part:i32,pub bytes:i32,pub message_id:PurgeBytesC}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct FileC {
    pub declaration_ordinal:u32,pub file_id:i32,pub incarnation:u64,pub reservation_request:[u8;16],
    pub reservation_sequence:u64,pub subject:PurgeBytesC,pub date:i64,
    pub groups:*const PurgeBytesC,pub groups_count:u32,pub articles:*const ArticleC,pub articles_count:u32,
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct DeclarationC {
    pub kind:u32,pub file_ordinal:u32,pub ordinal:u32,pub attributes:*const AttributeC,pub attributes_count:u32,
    pub characters:PurgeBytesC,pub disposition:u32,pub effective_file:u32,pub effective_article:u32,pub replacement_ordinal:u32,
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct AssociationC {
    pub version:u32,pub struct_size:u32,pub key:KeyC,pub capture_publication_sequence:u64,
    pub capture_payload_identity:[u8;32],pub parser_contract_version:u32,pub reserved:u32,
    pub files:*const FileC,pub files_count:u32,pub declarations:*const DeclarationC,pub declarations_count:u32,
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct AuthorityC {pub source_id:u64,pub custody_reference:[u8;32]}
// Called only from a validated, committed owned association, never from a raw
// capture or caller-provided arbitrary sequence/incarnation.
fn authority_view(o:&IntakeOwned,incarnation:u64)->AuthorityC{
    let mut reference=[0;32];reference[..16].copy_from_slice(&o.committed.domain);
    reference[16..24].copy_from_slice(&o.committed.publication_sequence.to_le_bytes());
    reference[24..].copy_from_slice(&incarnation.to_le_bytes());
    AuthorityC {source_id:incarnation,custody_reference:reference}
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct IntakeViewC {
    pub version:u32,pub struct_size:u32,pub key:KeyC,pub collection:PurgeBindingC,
    pub capture_publication_sequence:u64,pub files_count:u32,pub reserved:u32,pub durable:DurableReceiptC,
    pub subject_authority:AuthorityC,
}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct FileViewC {
    pub version:u32,pub struct_size:u32,pub binding:PurgeBindingC,pub reservation_request:[u8;16],
    pub reservation_sequence:u64,pub declaration_ordinal:u32,pub reserved:u32,
    pub subject_authority:AuthorityC,
}
pub struct IntakeOwned {
    committed:Committed<journal::intake::IntakeAssociation>,identity:[u8;32],
    collection_id:i32,incarnation:u64,posting_source:Vec<u8>,
}

// Test the preallocation boundary itself, before a durable host is available.
#[cfg(test)]
mod tests {
    use super::*;
    fn empty()->AssociationC {
        AssociationC {version:1,struct_size:std::mem::size_of::<AssociationC>() as u32,
            key:KeyC {version:1,struct_size:std::mem::size_of::<KeyC>() as u32,domain:[1;16],request:[2;16]},
            capture_publication_sequence:1,capture_payload_identity:[3;32],parser_contract_version:1,reserved:0,
            files:std::ptr::null(),files_count:0,declarations:std::ptr::null(),declarations_count:0}
    }
    #[test]
    fn intake_count_bounds_precede_pointer_access_and_owned_allocation() {
        let mut c=empty();c.declarations_count=1_000_001;
        assert_eq!(unsafe{association_owned(&c)},Err(PurgeError::LimitExceeded));
        c=empty();let mut file:FileC=unsafe{std::mem::zeroed()};file.subject.len=65536;
        c.files=&file;c.files_count=1;
        assert_eq!(unsafe{association_owned(&c)},Err(PurgeError::LimitExceeded));
        file.subject.len=0;file.articles_count=1_000_001;
        assert_eq!(unsafe{association_owned(&c)},Err(PurgeError::LimitExceeded));
    }
    #[test]
    fn intake_association_copies_borrowed_declared_and_effective_bytes() {
        let mut subject=b"source".to_vec();let mut message=b"<article>".to_vec();let mut declared=b"article".to_vec();
        let article=ArticleC {declaration_ordinal:1,part:1,bytes:2,message_id:purge_view(&message)};
        let file=FileC {declaration_ordinal:1,file_id:42,incarnation:2,reservation_request:[3;16],reservation_sequence:1,
            subject:purge_view(&subject),date:2,groups:std::ptr::null(),groups_count:0,articles:&article,articles_count:1};
        let declaration=DeclarationC {kind:2,file_ordinal:1,ordinal:1,attributes:std::ptr::null(),attributes_count:0,
            characters:purge_view(&declared),disposition:1,effective_file:1,effective_article:1,replacement_ordinal:0};
        let mut c=empty();c.files=&file;c.files_count=1;c.declarations=&declaration;c.declarations_count=1;
        let owned=unsafe{association_owned(&c)}.unwrap();subject.fill(b'x');message.fill(b'x');declared.fill(b'x');
        assert_eq!(owned.files[0].subject,b"source");assert_eq!(owned.files[0].articles[0].message_id,b"<article>");
        assert_eq!(owned.declarations[0].characters,b"article");
    }
}

unsafe fn intake_table<'a,C,T>(p:*const C,n:u32,cap:usize,b:&mut purge::Budget)->Result<&'a[C],PurgeError>{
    let rows=purge_slice(p,n,cap,b)?;
    b.add(rows.len().checked_mul(std::mem::size_of::<T>().saturating_sub(std::mem::size_of::<C>())).ok_or(PurgeError::LimitExceeded)?)?;
    Ok(rows)
}
unsafe fn association_owned(c:&AssociationC)->Result<journal::intake::IntakeAssociation,PurgeError>{
    use journal::intake::{Attribute,Declaration,EffectiveArticle,EffectiveFile,Group,IntakeAssociation};
    purge_versioned(&c.key)?;
    if c.reserved!=0{return Err(PurgeError::InvalidInput);}
    let mut budget=purge::Budget::new();budget.table::<IntakeAssociation>(1)?;
    let files=intake_table::<FileC,EffectiveFile>(c.files,c.files_count,purge::MAX_MEMBERS,&mut budget)?;
    let declarations=intake_table::<DeclarationC,Declaration>(c.declarations,c.declarations_count,1_000_000,&mut budget)?;
    // Complete recursive preflight, including all final owned table overhead,
    // before any string/table is copied or anything is durably published.
    for f in files {
        purge_raw_bytes(f.subject,65535,&mut budget)?;
        let groups=intake_table::<PurgeBytesC,Group>(f.groups,f.groups_count,purge::MAX_MEMBERS,&mut budget)?;
        let articles=intake_table::<ArticleC,EffectiveArticle>(f.articles,f.articles_count,1_000_000,&mut budget)?;
        for g in groups{purge_raw_bytes(*g,65535,&mut budget)?;}
        for a in articles{purge_raw_bytes(a.message_id,65535,&mut budget)?;}
    }
    for d in declarations {
        let attributes=intake_table::<AttributeC,Attribute>(d.attributes,d.attributes_count,1024,&mut budget)?;
        for a in attributes{purge_raw_bytes(a.name,65535,&mut budget)?;purge_raw_bytes(a.value,purge::MAX_PAYLOAD,&mut budget)?;}
        purge_raw_bytes(d.characters,purge::MAX_PAYLOAD,&mut budget)?;
    }
    // Zero-length spans may have null pointers; never call from_raw_parts(null,0).
    unsafe fn span<'a,T>(p:*const T,n:u32)->&'a[T]{if n==0{&[]}else{std::slice::from_raw_parts(p,n as usize)}}
    let mut owned_files=purge::reserved(files.len())?;
    for f in files {
        let mut groups=purge::reserved(f.groups_count as usize)?;
        for g in span(f.groups,f.groups_count){groups.push(Group {bytes:purge_owned_bytes(*g)?});}
        let mut articles=purge::reserved(f.articles_count as usize)?;
        for a in span(f.articles,f.articles_count){articles.push(EffectiveArticle {declaration_ordinal:a.declaration_ordinal,
            part:a.part,bytes:a.bytes,message_id:purge_owned_bytes(a.message_id)?});}
        owned_files.push(EffectiveFile {declaration_ordinal:f.declaration_ordinal,file_id:f.file_id,incarnation:f.incarnation,
            reservation_request:f.reservation_request,reservation_sequence:f.reservation_sequence,
            subject:purge_owned_bytes(f.subject)?,date:f.date,groups,articles});
    }
    let mut owned_declarations=purge::reserved(declarations.len())?;
    for d in declarations {
        let mut attributes=purge::reserved(d.attributes_count as usize)?;
        for a in span(d.attributes,d.attributes_count){attributes.push(Attribute {name:purge_owned_bytes(a.name)?,value:purge_owned_bytes(a.value)?});}
        owned_declarations.push(Declaration {kind:d.kind,file_ordinal:d.file_ordinal,ordinal:d.ordinal,attributes,
            characters:purge_owned_bytes(d.characters)?,disposition:d.disposition,effective_file:d.effective_file,
            effective_article:d.effective_article,replacement_ordinal:d.replacement_ordinal});
    }
    Ok(IntakeAssociation {schema_version:1,domain:c.key.domain,publication_sequence:0,request:c.key.request,
        capture_publication_sequence:c.capture_publication_sequence,capture_payload_identity:c.capture_payload_identity,
        parser_contract_version:c.parser_contract_version,files:owned_files,declarations:owned_declarations})
}
/// # Safety
/// Every nested counted span is immutable/aligned for this call, without output
/// aliasing. Host access is exclusive. No borrowed pointer survives return.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_store(input:*const AssociationC,
    ops:*const PurgeHostOpsC,out:*mut *mut IntakeOwned,error:*mut i32)->i32
{
    let input=purge_versioned(input);let ops=purge_host_ops(ops);
    owned_abi::owned(out,error,||{
        let record=association_owned(input?)?;let ops=ops?;
        let registry=ops.registry.as_mut().ok_or(PurgeError::RecoveryRequired)?;
        let identity=journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let (collection_id,incarnation,posting_source)=registry.inner.intake_identity_before_commit(record.request)?;
        let committed=registry.inner.store_intake_association(record,&mut PurgeHostAdapter(&ops))?;
        registry.inner.validate_intake_owner(&committed)?;
        // All returned backing was allocated before publication. An error in
        // exact retained validation still returns no authority and keeps custody.
        Ok(IntakeOwned {committed,identity,collection_id,incarnation,posting_source})
    })
}
/// # Safety
/// Exact key and exclusive verified registry/host access, as for store.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_load(input:*const KeyC,
    ops:*const PurgeHostOpsC,out:*mut *mut IntakeOwned,error:*mut i32)->i32
{
    let input=purge_versioned(input).copied();let ops=purge_host_ops(ops);
    owned_abi::owned(out,error,||{
        let key=input?;let ops=ops?;let registry=purge_record(ops.registry)?;
        if key.domain!=registry.inner.journal_domain(){return Err(PurgeError::Conflict);}
        let identity=journal::Host::journal_identity(&PurgeHostAdapter(&ops))?;
        let committed=registry.inner.load_intake_association(key.request,&PurgeHostAdapter(&ops))?;
        let (collection_id,incarnation,posting_source)=registry.inner.intake_identity_before_commit(key.request)?;
        Ok(IntakeOwned {committed,identity,collection_id,incarnation,posting_source})
    })
}
/// # Safety
/// Owner remains live while the returned immutable spans are consumed.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_view(input:*const IntakeOwned,out:*mut IntakeViewC,error:*mut i32)->i32{
    owned_abi::view(out,error,||{
        let o=purge_record(input)?;let r=&o.committed.record;
        Ok(IntakeViewC {version:1,struct_size:std::mem::size_of::<IntakeViewC>() as u32,
            key:KeyC {version:1,struct_size:std::mem::size_of::<KeyC>() as u32,domain:r.domain,request:r.request},
            collection:PurgeBindingC {collection_id:o.collection_id,file_id:0,has_file:0,incarnation:o.incarnation,posting_source:purge_view(&o.posting_source)},
            capture_publication_sequence:r.capture_publication_sequence,files_count:r.files.len() as u32,reserved:0,
            durable:owned_abi::receipt(r.domain,r.publication_sequence,&o.identity,o.committed.payload_identity),
            subject_authority:authority_view(o,o.incarnation)})
    })
}
/// # Safety
/// Same borrowed lifetime as view; index is zero-based and checked.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_file_view(input:*const IntakeOwned,index:u32,out:*mut FileViewC,error:*mut i32)->i32{
    owned_abi::view(out,error,||{
        let o=purge_record(input)?;let f=o.committed.files.get(index as usize).ok_or(PurgeError::InvalidInput)?;
        Ok(FileViewC {version:1,struct_size:std::mem::size_of::<FileViewC>() as u32,
            binding:PurgeBindingC {collection_id:o.collection_id,file_id:f.file_id,has_file:1,incarnation:f.incarnation,posting_source:purge_view(&o.posting_source)},
            reservation_request:f.reservation_request,reservation_sequence:f.reservation_sequence,declaration_ordinal:f.declaration_ordinal,reserved:0,
            subject_authority:authority_view(o,f.incarnation)})
    })
}
/// # Safety
/// Null or a live owner returned by store/load, destroyed exactly once.
#[no_mangle]
pub unsafe extern "C" fn nzbget_rs_purge_intake_destroy(input:*mut IntakeOwned){owned_abi::destroy(input);}
