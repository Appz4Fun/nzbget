//! RarVolume's header parsing (RarReader.cpp): the RAR3 and RAR5 block
//! structure of one volume - its version, naming and volume flags, and the
//! files it holds with their sizes, times, split flags, methods, data offsets
//! and encryption records - read from an untrusted content source exactly as
//! the C++ did, including the decryption of encrypted headers block by block.
//! The source and the cipher (OpenSSL, key derivation) stay C++: the parser
//! reads through `Source` and decrypts through `Cipher`.

/// The content a volume is read from (ContentSource).
pub trait Source {
    fn size(&mut self) -> i64;
    /// `buf.len()` bytes at `offset`, or false
    fn read(&mut self, offset: i64, buf: &mut [u8]) -> bool;
}

/// The header cipher (OpenSSL in the C++).
pub trait Cipher {
    /// rar3: derives the key and IV from the password and this salt
    fn rar3_prepare(&mut self, salt: &[u8; 8]) -> bool;
    /// rar5: derives the key from the password, KDF count and salt
    fn rar5_prepare(&mut self, kdf_count: u8, salt: &[u8; 16]) -> bool;
    /// starts AES-CBC (128 or 256 bits) with this IV, or rar3's derived one
    fn init(&mut self, key_bits: i32, iv: Option<&[u8; 16]>) -> bool;
    /// one 16-byte block
    fn decrypt(&mut self, input: &[u8; 16], output: &mut [u8; 16]) -> bool;
    fn free(&mut self);
}

/// Receives files at the same commit points as the C++ reader. A failed
/// append stops parsing; a successful seek updates the last file's offset.
pub trait Files {
    fn add(&mut self, file: &RarFile) -> bool;
    fn set_data_offset(&mut self, position: i64);
}

/// RarFile::Rar5Crypt
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rar5Crypt {
    pub version: u64,
    pub flags: u64,
    pub kdf_count: u8,
    pub salt: [u8; 16],
    pub iv: [u8; 16],
    pub check_value: [u8; 12],
    pub has_check: bool,
}

/// RarFile
#[derive(Clone, Debug, PartialEq)]
pub struct RarFile {
    /// as the C++ held it: up to the first NUL of the stored name
    pub filename: Vec<u8>,
    pub time: u32,
    pub attr: u32,
    pub size: i64,
    pub split_before: bool,
    pub split_after: bool,
    pub method: u32,
    pub stored: bool,
    pub packed_size: i64,
    pub data_offset: i64,
    pub encrypted_data: bool,
    pub has_salt: bool,
    pub salt: [u8; 8],
    pub crypt: Option<Rar5Crypt>,
}

impl Default for RarFile {
    fn default() -> Self {
        RarFile {
            filename: Vec::new(),
            time: 0,
            attr: 0,
            size: 0,
            split_before: false,
            split_after: false,
            method: 0,
            stored: false,
            packed_size: 0,
            data_offset: -1,
            encrypted_data: false,
            has_salt: false,
            salt: [0; 8],
            crypt: None,
        }
    }
}

/// The volume state RarVolume keeps (read and updated by a parse).
#[derive(Clone, Debug, PartialEq)]
pub struct Volume {
    pub version: i32,
    pub volume_no: u32,
    pub new_naming: bool,
    pub has_next_volume: bool,
    pub multi_volume: bool,
    pub encrypted: bool,
    pub has_password: bool,
    pub decrypt_buf: [u8; 16],
    pub decrypt_pos: u8,
}

impl Default for Volume {
    fn default() -> Self {
        Volume {
            version: 0,
            volume_no: 0,
            new_naming: false,
            has_next_volume: false,
            multi_volume: false,
            encrypted: false,
            has_password: false,
            decrypt_buf: [0; 16],
            decrypt_pos: 16,
        }
    }
}

const SO_SET: i32 = 0;
const SO_CUR: i32 = 1;
const SO_END: i32 = 2;

/// RarSourceCursor
struct Cursor<'a> {
    source: &'a mut dyn Source,
    position: i64,
    eof: bool,
}

impl Cursor<'_> {
    fn read(&mut self, buf: &mut [u8]) -> i64 {
        let size = buf.len() as i64;
        let available = size.min(self.source.size().wrapping_sub(self.position).max(0));
        if available < size {
            // like feof: only a read past the end raises it
            self.eof = true;
        }
        if available <= 0 {
            return 0;
        }
        if !self.source.read(self.position, &mut buf[..available as usize]) {
            return 0;
        }
        self.position = self.position.wrapping_add(available);
        available
    }

    fn seek(&mut self, position: i64, origin: i32) -> bool {
        let target = match origin {
            SO_CUR => self.position.wrapping_add(position),
            SO_END => self.source.size().wrapping_add(position),
            _ => position,
        };
        if target < 0 {
            return false;
        }
        self.position = target;
        self.eof = false;
        true
    }
}

#[derive(Clone, Copy, Default)]
struct Block {
    #[allow(dead_code)]
    crc: u32,
    kind: u8,
    flags: u16,
    addsize: u64,
    trailsize: u64,
    datasize: u64,
}

const RAR3_MAIN_VOLUME: u16 = 0x0001;
const RAR3_MAIN_NEWNUMBERING: u16 = 0x0010;
const RAR3_MAIN_PASSWORD: u16 = 0x0080;
const RAR3_BLOCK_MAIN: u8 = 0x73;
const RAR3_BLOCK_FILE: u8 = 0x74;
const RAR3_BLOCK_ENDARC: u8 = 0x7b;
const RAR3_BLOCK_ADDSIZE: u16 = 0x8000;
const RAR3_FILE_ADDSIZE: u16 = 0x0100;
const RAR3_FILE_SPLITBEFORE: u16 = 0x0001;
const RAR3_FILE_SPLITAFTER: u16 = 0x0002;
const RAR3_FILE_PASSWORD: u16 = 0x0004;
const RAR3_FILE_SALT: u16 = 0x0400;
const RAR3_ENDARC_NEXTVOL: u16 = 0x0001;
const RAR3_ENDARC_DATACRC: u16 = 0x0002;
const RAR3_ENDARC_VOLNUMBER: u16 = 0x0008;

const RAR5_BLOCK_MAIN: u8 = 1;
const RAR5_BLOCK_FILE: u8 = 2;
const RAR5_BLOCK_ENCRYPTION: u8 = 4;
const RAR5_BLOCK_ENDARC: u8 = 5;
const RAR5_BLOCK_EXTRADATA: u16 = 0x01;
const RAR5_BLOCK_DATAAREA: u16 = 0x02;
const RAR5_BLOCK_SPLITBEFORE: u16 = 0x08;
const RAR5_BLOCK_SPLITAFTER: u16 = 0x10;
const RAR5_MAIN_ISVOL: u64 = 0x01;
const RAR5_MAIN_VOLNR: u64 = 0x02;
const RAR5_FILE_TIME: u64 = 0x02;
const RAR5_FILE_CRC: u64 = 0x04;
const RAR5_FILE_EXTRATIME: u64 = 0x03;
const RAR5_FILE_EXTRATIMEUNIXFORMAT: u64 = 0x01;
const RAR5_FILE_EXTRACRYPT: u64 = 0x01;
const RAR5_CRYPT_PSWCHECK: u64 = 0x01;
const RAR5_ENDARC_NEXTVOL: u64 = 0x01;

/// The parser: the volume state, the cursor and the cipher.
struct Parser<'a, 'b> {
    v: &'a mut Volume,
    file: Cursor<'b>,
    cipher: &'a mut dyn Cipher,
    files: &'a mut dyn Files,
}

impl Parser<'_, '_> {
    /// DecryptRead
    fn decrypt_read(&mut self, buffer: &mut [u8]) -> bool {
        let mut done = 0;
        while done < buffer.len() {
            if self.v.decrypt_pos >= 16 {
                let mut buf = [0u8; 16];
                if self.file.read(&mut buf) != 16 {
                    return false;
                }
                self.v.decrypt_pos = 0;
                if !self.cipher.decrypt(&buf, &mut self.v.decrypt_buf) {
                    return false;
                }
            }
            let remaining = 16 - self.v.decrypt_pos as usize;
            let len = (buffer.len() - done).min(remaining);
            let pos = self.v.decrypt_pos as usize;
            buffer[done..done + len].copy_from_slice(&self.v.decrypt_buf[pos..pos + len]);
            self.v.decrypt_pos += len as u8;
            done += len;
        }
        true
    }

    /// Read
    fn read(&mut self, block: Option<&mut Block>, buffer: &mut [u8]) -> bool {
        if self.v.encrypted {
            if !self.decrypt_read(buffer) {
                return false;
            }
        } else if self.file.read(buffer) != buffer.len() as i64 {
            return false;
        }
        if let Some(block) = block {
            block.trailsize = block.trailsize.wrapping_sub(buffer.len() as u64);
        }
        true
    }

    fn read16(&mut self, block: Option<&mut Block>) -> Option<u16> {
        let mut b = [0u8; 2];
        self.read(block, &mut b).then(|| u16::from_le_bytes(b))
    }

    fn read32(&mut self, block: Option<&mut Block>) -> Option<u32> {
        let mut b = [0u8; 4];
        self.read(block, &mut b).then(|| u32::from_le_bytes(b))
    }

    /// ReadV: a RAR5 vint (a 64-bit value takes at most 10 bytes)
    fn read_v(&mut self, mut block: Option<&mut Block>) -> Option<u64> {
        let mut result = 0u64;
        let mut bits = 0u32;
        loop {
            if bits >= 64 {
                return None;
            }
            let mut b = [0u8; 1];
            if !self.read(block.as_deref_mut(), &mut b) {
                return None;
            }
            result = result.wrapping_add(((b[0] & 0x7f) as u64) << bits);
            bits += 7;
            if b[0] & 0x80 == 0 {
                return Some(result);
            }
        }
    }

    /// ReadVLimited: ReadV within a byte budget
    fn read_v_limited(&mut self, block: &mut Block, avail: &mut u64) -> Option<u64> {
        let mut result = 0u64;
        let mut bits = 0u32;
        loop {
            if *avail == 0 || bits >= 64 {
                return None;
            }
            let mut b = [0u8; 1];
            if !self.read(Some(block), &mut b) {
                return None;
            }
            *avail -= 1;
            result = result.wrapping_add(((b[0] & 0x7f) as u64) << bits);
            bits += 7;
            if b[0] & 0x80 == 0 {
                return Some(result);
            }
        }
    }

    fn skip(&mut self, block: &mut Block, mut size: i64) -> bool {
        let mut buf = [0u8; 256];
        while size > 0 {
            let len = size.min(256) as usize;
            if !self.read(Some(block), &mut buf[..len]) {
                return false;
            }
            size -= len as i64;
        }
        true
    }

    /// DetectRarVersion: the signatures compared as C strings (strcmp)
    fn detect_version(&mut self) -> i32 {
        const RAR3: &[u8] = b"Rar!\x1a\x07\x00";
        const RAR5: &[u8] = b"Rar!\x1a\x07\x01\x00";
        let mut sig = [0u8; 8];
        let cnt = self.file.read(&mut sig);
        // strcmp(signature, read): equal up to and including the signature's NUL
        let strcmp_eq = |s: &[u8]| s.iter().zip(sig.iter()).all(|(a, b)| a == b);
        let rar5 = cnt == 8 && strcmp_eq(RAR5);
        let rar3 = !rar5 && cnt == 8 && strcmp_eq(RAR3);
        if rar3 {
            3
        } else if rar5 {
            5
        } else {
            0
        }
    }

    fn rar3_block(&mut self) -> Option<Block> {
        let mut block = Block::default();
        if self.v.encrypted {
            let mut salt = [0u8; 8];
            if !(self.file.read(&mut salt) == 8 && self.cipher.rar3_prepare(&salt) && self.cipher.init(128, None)) {
                return None;
            }
        }
        let mut buf = [0u8; 7];
        if !self.read(None, &mut buf) {
            return None;
        }
        block.crc = u16::from_le_bytes([buf[0], buf[1]]) as u32;
        block.kind = buf[2];
        block.flags = u16::from_le_bytes([buf[3], buf[4]]);
        let size = u16::from_le_bytes([buf[5], buf[6]]);
        let mut blocksize = size as u32;
        if self.v.encrypted {
            // align to 16 bytes
            blocksize = blocksize.wrapping_add((!blocksize).wrapping_add(1) & 15);
        }
        // sizeof(buf) promotes the C++ subtraction to size_t, including
        // its 32-bit wrap before assignment to the 64-bit trailer field.
        block.trailsize = (blocksize as usize).wrapping_sub(7) as u64;
        let mut add = [0u8; 4];
        if block.flags & RAR3_BLOCK_ADDSIZE != 0 && !self.read(None, &mut add) {
            return None;
        }
        block.addsize = u32::from_le_bytes(add) as u64;
        block.datasize = 0;
        if block.flags & RAR3_BLOCK_ADDSIZE != 0 {
            blocksize = blocksize.wrapping_add(block.addsize as u32);
            block.trailsize = (blocksize as usize).wrapping_sub(7).wrapping_sub(4) as u64;
        }
        // a zero type ends the parse (as the C++'s empty block)
        (block.kind != 0).then_some(block)
    }

    fn rar3_file(&mut self, block: &mut Block, f: &mut RarFile) -> bool {
        f.split_before = block.flags & RAR3_FILE_SPLITBEFORE != 0;
        f.split_after = block.flags & RAR3_FILE_SPLITAFTER != 0;
        f.packed_size = block.addsize as i64;
        f.encrypted_data = block.flags & RAR3_FILE_PASSWORD != 0;
        let Some(size) = self.read32(Some(block)) else { return false };
        f.size = size as i64;
        if !self.skip(block, 1) || !self.skip(block, 4) {
            return false;
        }
        let Some(time) = self.read32(Some(block)) else { return false };
        f.time = time;
        let mut b = [0u8; 1];
        if !self.read(Some(block), &mut b) {
            return false;
        }
        if !self.read(Some(block), &mut b) {
            return false;
        }
        f.method = b[0] as u32;
        f.stored = b[0] == 0x30;
        let Some(namelen) = self.read16(Some(block)) else { return false };
        let Some(attr) = self.read32(Some(block)) else { return false };
        f.attr = attr;
        if block.flags & RAR3_FILE_ADDSIZE != 0 {
            let Some(high) = self.read32(Some(block)) else { return false };
            block.trailsize = block.trailsize.wrapping_add((high as u64) << 32);
            f.packed_size = f.packed_size.wrapping_add(((high as u64) << 32) as i64);
            let Some(high) = self.read32(Some(block)) else { return false };
            f.size = f.size.wrapping_add(((high as u64) << 32) as i64);
        }
        if namelen > 8192 {
            return false;
        }
        let mut name = vec![0u8; namelen as usize];
        if !self.read(Some(block), &mut name) {
            return false;
        }
        name.truncate(name.iter().position(|&c| c == 0).unwrap_or(name.len()));
        f.filename = name;
        if block.flags & RAR3_FILE_SALT != 0 {
            let mut salt = [0u8; 8];
            if !self.read(Some(block), &mut salt) {
                return false;
            }
            f.salt = salt;
            f.has_salt = true;
        }
        true
    }

    /// the skip to the next block, with the encrypted padding; false when it
    /// doesn't land past `start`, where the block began (the read position
    /// must advance with every block)
    fn skip_to_next(&mut self, block: &Block, rar5: bool, start: i64) -> bool {
        let mut skip = block.trailsize;
        if self.v.encrypted {
            skip = skip.wrapping_sub((16i32 - self.v.decrypt_pos as i32) as u64);
            if rar5 {
                if self.v.decrypt_pos < 16 {
                    skip = skip.wrapping_add(if !skip.is_multiple_of(16) { 16 - skip % 16 } else { 0 });
                    self.v.decrypt_pos = 16;
                }
            } else {
                self.v.decrypt_pos = 16;
            }
            self.cipher.free();
        }
        self.file.seek(skip as i64, SO_CUR) && self.file.position > start
    }

    fn rar3_volume(&mut self) -> bool {
        while !self.file.eof {
            let start = self.file.position;
            let Some(mut block) = self.rar3_block() else { return false };
            let mut file_block = false;
            if block.kind == RAR3_BLOCK_MAIN {
                if block.flags & RAR3_MAIN_PASSWORD != 0 {
                    self.v.encrypted = true;
                    if !self.v.has_password {
                        return false;
                    }
                }
                self.v.new_naming = block.flags & RAR3_MAIN_NEWNUMBERING != 0;
                self.v.multi_volume = block.flags & RAR3_MAIN_VOLUME != 0;
            } else if block.kind == RAR3_BLOCK_FILE {
                let mut f = RarFile::default();
                let ok = self.rar3_file(&mut block, &mut f);
                if !ok {
                    return false;
                }
                if !self.files.add(&f) {
                    return false;
                }
                file_block = true;
            } else if block.kind == RAR3_BLOCK_ENDARC {
                if block.flags & RAR3_ENDARC_DATACRC != 0 && !self.skip(&mut block, 4) {
                    return false;
                }
                if block.flags & RAR3_ENDARC_VOLNUMBER != 0 {
                    let Some(no) = self.read32(Some(&mut block)) else { return false };
                    self.v.volume_no = no;
                    self.v.has_next_volume = block.flags & RAR3_ENDARC_NEXTVOL != 0;
                }
                break;
            } else if !(0x72..=0x7b).contains(&block.kind) {
                return false;
            }
            if !self.skip_to_next(&block, false, start) {
                return false;
            }
            if file_block {
                self.files.set_data_offset(self.file.position);
            }
        }
        true
    }

    fn rar5_block(&mut self) -> Option<Block> {
        let mut block = Block::default();
        if self.v.encrypted {
            let mut iv = [0u8; 16];
            if !(self.file.read(&mut iv) == 16 && self.cipher.init(256, Some(&iv))) {
                return None;
            }
        }
        block.crc = self.read32(None)?;
        let size = self.read_v(None)? as u32;
        block.trailsize = size as u64;
        block.kind = self.read_v(Some(&mut block))? as u8;
        block.flags = self.read_v(Some(&mut block))? as u16;
        block.addsize = 0;
        if block.flags & RAR5_BLOCK_EXTRADATA != 0 {
            block.addsize = self.read_v(Some(&mut block))?;
        }
        let mut datasize = 0;
        if block.flags & RAR5_BLOCK_DATAAREA != 0 {
            datasize = self.read_v(Some(&mut block))?;
        }
        block.trailsize = block.trailsize.wrapping_add(datasize);
        block.datasize = datasize;
        (block.kind != 0).then_some(block)
    }

    fn rar5_crypt(&mut self, block: &mut Block, f: &mut RarFile, content_len: u64) -> bool {
        let mut avail = content_len;
        let mut crypt = Rar5Crypt::default();
        let Some(version) = self.read_v_limited(block, &mut avail) else { return true };
        crypt.version = version;
        let Some(flags) = self.read_v_limited(block, &mut avail) else { return true };
        crypt.flags = flags;
        if avail < 1 + 16 + 16 {
            return true;
        }
        let mut b = [0u8; 1];
        if !self.read(Some(block), &mut b) {
            return false;
        }
        crypt.kdf_count = b[0];
        avail -= 1;
        if !self.read(Some(block), &mut crypt.salt) {
            return false;
        }
        avail -= 16;
        if !self.read(Some(block), &mut crypt.iv) {
            return false;
        }
        avail -= 16;
        crypt.has_check = crypt.flags & RAR5_CRYPT_PSWCHECK != 0;
        if crypt.has_check {
            if avail < 12 {
                return true;
            }
            if !self.read(Some(block), &mut crypt.check_value) {
                return false;
            }
        }
        f.crypt = Some(crypt);
        true
    }

    fn rar5_file(&mut self, block: &mut Block, f: &mut RarFile) -> bool {
        f.split_before = block.flags & RAR5_BLOCK_SPLITBEFORE != 0;
        f.split_after = block.flags & RAR5_BLOCK_SPLITAFTER != 0;
        f.packed_size = block.datasize as i64;
        let Some(fileflags) = self.read_v(Some(block)) else { return false };
        let Some(size) = self.read_v(Some(block)) else { return false };
        f.size = size as i64;
        let Some(attr) = self.read_v(Some(block)) else { return false };
        f.attr = attr as u32;
        if fileflags & RAR5_FILE_TIME != 0 {
            let Some(t) = self.read32(Some(block)) else { return false };
            f.time = t;
        }
        if fileflags & RAR5_FILE_CRC != 0 && !self.skip(block, 4) {
            return false;
        }
        let Some(comp) = self.read_v(Some(block)) else { return false };
        f.method = ((comp >> 7) & 7) as u32;
        f.stored = f.method == 0;
        if self.read_v(Some(block)).is_none() {
            return false;
        }
        let Some(namelen) = self.read_v(Some(block)) else { return false };
        if namelen > 8192 {
            return false;
        }
        let mut name = vec![0u8; namelen as usize];
        if !self.read(Some(block), &mut name) {
            return false;
        }
        name.truncate(name.iter().position(|&c| c == 0).unwrap_or(name.len()));
        f.filename = name;
        if block.flags & RAR5_BLOCK_EXTRADATA != 0 {
            let mut remsize = block.addsize;
            while remsize > 0 {
                let mut trailsize = block.trailsize;
                let Some(mut len) = self.read_v(Some(block)) else { return false };
                remsize = remsize.wrapping_sub(trailsize.wrapping_sub(block.trailsize).wrapping_add(len));
                trailsize = block.trailsize;
                let Some(kind) = self.read_v(Some(block)) else { return false };
                if kind == RAR5_FILE_EXTRACRYPT {
                    f.encrypted_data = true;
                    let type_bytes = trailsize.wrapping_sub(block.trailsize);
                    let content = len.saturating_sub(type_bytes);
                    if !self.rar5_crypt(block, f, content) {
                        return false;
                    }
                }
                if kind == RAR5_FILE_EXTRATIME {
                    let Some(flags) = self.read_v(Some(block)) else { return false };
                    if flags & RAR5_FILE_EXTRATIMEUNIXFORMAT != 0 {
                        let Some(t) = self.read32(Some(block)) else { return false };
                        f.time = t;
                    } else {
                        let Some(low) = self.read32(Some(block)) else { return false };
                        let Some(high) = self.read32(Some(block)) else { return false };
                        let wintime = ((high as u64) << 32).wrapping_add(low as u64);
                        f.time = ((wintime / 10_000_000) as i64).wrapping_sub(11_644_473_600) as u32;
                    }
                }
                len = len.wrapping_sub(trailsize.wrapping_sub(block.trailsize));
                if !self.skip(block, len as i64) {
                    return false;
                }
            }
        }
        true
    }

    fn rar5_volume(&mut self) -> bool {
        self.file.seek(8, SO_SET);
        while !self.file.eof {
            let start = self.file.position;
            let Some(mut block) = self.rar5_block() else { return false };
            let mut file_block = false;
            if block.kind == RAR5_BLOCK_MAIN {
                let Some(arcflags) = self.read_v(Some(&mut block)) else { return false };
                if arcflags & RAR5_MAIN_VOLNR != 0 {
                    let Some(volnr) = self.read_v(Some(&mut block)) else { return false };
                    self.v.volume_no = volnr as u32;
                }
                self.v.new_naming = true;
                self.v.multi_volume = arcflags & RAR5_MAIN_ISVOL != 0;
            } else if block.kind == RAR5_BLOCK_ENCRYPTION {
                match self.read_v(Some(&mut block)) {
                    Some(0) => {}
                    _ => return false, // only AES
                }
                if self.read_v(Some(&mut block)).is_none() {
                    return false;
                }
                let mut kdf = [0u8; 1];
                if !self.read(Some(&mut block), &mut kdf) {
                    return false;
                }
                let mut salt = [0u8; 16];
                if !self.read(Some(&mut block), &mut salt) {
                    return false;
                }
                self.v.encrypted = true;
                if !self.v.has_password || !self.cipher.rar5_prepare(kdf[0], &salt) {
                    return false;
                }
            } else if block.kind == RAR5_BLOCK_FILE {
                let mut f = RarFile::default();
                if !self.rar5_file(&mut block, &mut f) {
                    return false;
                }
                if !self.files.add(&f) {
                    return false;
                }
                file_block = true;
            } else if block.kind == RAR5_BLOCK_ENDARC {
                let Some(endflags) = self.read_v(Some(&mut block)) else { return false };
                self.v.has_next_volume = endflags & RAR5_ENDARC_NEXTVOL != 0;
                break;
            } else if block.kind > 5 {
                return false;
            }
            if !self.skip_to_next(&block, true, start) {
                return false;
            }
            if file_block {
                self.files.set_data_offset(self.file.position);
            }
        }
        true
    }
}

/// RarVolume::ReadFrom: parses `source` into `volume`; true when the volume
/// was read to its end.
pub fn read_from(volume: &mut Volume, source: &mut dyn Source, cipher: &mut dyn Cipher, files: &mut dyn Files) -> bool {
    let mut p = Parser { v: volume, file: Cursor { source, position: 0, eof: false }, cipher, files };
    p.v.version = p.detect_version();
    p.file.seek(0, SO_SET);
    let ok = match p.v.version {
        3 => p.rar3_volume(),
        5 => p.rar5_volume(),
        _ => false,
    };
    p.cipher.free();
    ok
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Bytes(Vec<u8>);
    impl Source for Bytes {
        fn size(&mut self) -> i64 { self.0.len() as i64 }
        fn read(&mut self, offset: i64, buf: &mut [u8]) -> bool {
            let Some(bytes) = self.0.get(offset as usize..offset as usize + buf.len()) else { return false };
            buf.copy_from_slice(bytes);
            true
        }
    }

    #[derive(Default)]
    struct TestCipher { fail: bool, blocks: usize, frees: usize }
    impl Cipher for TestCipher {
        fn rar3_prepare(&mut self, _: &[u8; 8]) -> bool { true }
        fn rar5_prepare(&mut self, _: u8, _: &[u8; 16]) -> bool { true }
        fn init(&mut self, _: i32, _: Option<&[u8; 16]>) -> bool { true }
        fn decrypt(&mut self, input: &[u8; 16], out: &mut [u8; 16]) -> bool {
            self.blocks += 1;
            if self.fail {
                out[..4].copy_from_slice(&input[..4]);
                return false;
            }
            *out = *input;
            true
        }
        fn free(&mut self) { self.frees += 1; }
    }

    impl Files for Vec<RarFile> {
        fn add(&mut self, file: &RarFile) -> bool { self.push(file.clone()); true }
        fn set_data_offset(&mut self, position: i64) {
            let last = self.last_mut().unwrap();
            last.data_offset = position.wrapping_sub(last.packed_size);
        }
    }

    #[test]
    fn rar3_trailer_uses_native_size_t_then_widens() {
        let max = usize::MAX as u64;
        for (size, add, expected) in [
            (0u16, None, max - 6),
            (7, None, 0),
            (10, Some(0u32), max),
            (11, Some(0), 0),
            (7, Some(u32::MAX), max - 4),
            (u16::MAX, Some(u32::MAX), 65523),
        ] {
            let mut bytes = vec![0, 0, RAR3_BLOCK_FILE, 0, if add.is_some() { 0x80 } else { 0 }];
            bytes.extend(size.to_le_bytes());
            if let Some(add) = add { bytes.extend(add.to_le_bytes()); }
            let mut source = Bytes(bytes);
            let mut volume = Volume::default();
            let mut cipher = TestCipher::default();
            let mut files = Vec::new();
            let mut p = Parser { v: &mut volume, file: Cursor { source: &mut source, position: 0, eof: false }, cipher: &mut cipher, files: &mut files };
            let block = p.rar3_block().unwrap();
            assert_eq!(block.trailsize, expected);
            assert_eq!(block.addsize, add.unwrap_or(0) as u64);
        }
    }

    #[test]
    fn decrypt_cache_partial_reads_and_failed_output() {
        let mut source = Bytes((0..48).collect());
        let mut volume = Volume { encrypted: true, ..Volume::default() };
        let mut cipher = TestCipher::default();
        let mut files = Vec::new();
        let mut p = Parser { v: &mut volume, file: Cursor { source: &mut source, position: 0, eof: false }, cipher: &mut cipher, files: &mut files };
        let mut first = [0; 7];
        assert!(p.decrypt_read(&mut first));
        assert_eq!(first, [0, 1, 2, 3, 4, 5, 6]);
        assert_eq!(p.file.position, 16);
        assert_eq!(p.v.decrypt_pos, 7);
        let mut second = [0; 12];
        assert!(p.decrypt_read(&mut second));
        assert_eq!(second, [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]);
        assert_eq!(p.file.position, 32);
        assert_eq!(p.v.decrypt_pos, 3);
        assert!(p.skip_to_next(&Block { trailsize: 13, ..Block::default() }, true, 0));
        assert_eq!(p.file.position, 32);
        assert_eq!(p.v.decrypt_pos, 16);
        cipher.fail = true;
        let mut p = Parser { v: &mut volume, file: Cursor { source: &mut source, position: 32, eof: false }, cipher: &mut cipher, files: &mut files };
        assert!(!p.decrypt_read(&mut first));
        assert_eq!(p.v.decrypt_pos, 0);
        assert_eq!(p.v.decrypt_buf, [32, 33, 34, 35, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31]);
        assert_eq!(p.file.position, 48);
        p.v.decrypt_pos = 16;
        assert!(!p.decrypt_read(&mut first));
        assert_eq!(p.v.decrypt_pos, 16);
        assert_eq!(p.file.position, 48);
        assert_eq!(cipher.blocks, 3);
        assert_eq!(cipher.frees, 1);
    }

    #[test]
    fn a_block_must_advance() {
        let mut source = Bytes(b"Rar!\x1a\x07\x00\x00\x00\x73\x00\x80\x10\x00\xf0\xff\xff\xff".to_vec());
        let mut volume = Volume::default();
        let mut cipher = TestCipher { fail: false, blocks: 0, frees: 0 };
        let mut files: Vec<RarFile> = Vec::new();
        assert!(!read_from(&mut volume, &mut source, &mut cipher, &mut files));
        assert_eq!(volume.version, 3);
    }

    #[test]
    fn progress_is_measured_from_the_block_start() {
        for rar5 in [false, true] {
            for encrypted in [false, true] {
                for (trailsize, expected) in [(0u64.wrapping_sub(16), false), (0, true)] {
                    let mut source = Bytes(vec![0; 64]);
                    let mut volume = Volume { encrypted, decrypt_pos: 7, ..Volume::default() };
                    let mut cipher = TestCipher::default();
                    let mut files = Vec::new();
                    let mut p = Parser {
                        v: &mut volume,
                        file: Cursor { source: &mut source, position: 32, eof: false },
                        cipher: &mut cipher, files: &mut files,
                    };
                    assert_eq!(p.skip_to_next(&Block { trailsize, ..Block::default() }, rar5, 16), expected);
                }
            }
        }
    }

    #[test]
    fn rar5_non_advancing_blocks() {
        for delta in [0u64, 1] {
            let mut data = b"Rar!\x1a\x07\x01\0".to_vec();
            data.extend([0, 0, 0, 0, 12, 3, 2]);
            let mut size = 0u64.wrapping_sub(17 + delta);
            while size >= 128 {
                data.push((size as u8 & 127) | 128);
                size >>= 7;
            }
            data.push(size as u8);
            let mut source = Bytes(data);
            let mut volume = Volume::default();
            let mut cipher = TestCipher::default();
            let mut files = Vec::new();
            assert!(!read_from(&mut volume, &mut source, &mut cipher, &mut files));
            assert_eq!(volume.version, 5);
        }
    }

    #[test]
    fn signature_and_terminal_blocks() {
        for data in [
            b"Rar!\x1a\x07\0\0\0\x73\0\0\x07\0\0\0\x7b\0\0\x07\0".as_slice(),
            b"Rar!\x1a\x07\x01\0\0\0\0\0\x03\x01\0\0\0\0\0\0\x03\x05\0\0".as_slice(),
        ] {
            let mut source = Bytes(data.to_vec());
            let mut volume = Volume::default();
            let mut cipher = TestCipher::default();
            let mut files = Vec::new();
            assert!(read_from(&mut volume, &mut source, &mut cipher, &mut files));
        }
    }
}
