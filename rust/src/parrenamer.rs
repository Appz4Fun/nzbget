//! ParRenamer::Execute (daemon/postprocess/ParRenamer.cpp): par-rename - the
//! destination directory and its subdirectories walked, par2 files found by
//! their packet header and renamed to "<setid>.volNNN+01.PAR2" when their
//! names don't tell their sets, the par2 files loaded, and every other file
//! renamed to the name the par2 files give the MD5 of its first 16 KiB (the
//! first par2 entry with that hash; nothing else is compared), as the C++
//! did it: the same order of files, checks, messages and renames, paths cut
//! as BString<1024> cut them, a damaged par2 file listed once and renamed to
//! .bad, missing files reported. Loading par2 packets, listing a directory
//! (a snapshot), file checks and reads, moving a file and the messages stay
//! with the caller (`Env`).

use std::ffi::{c_char, c_int};

use md5::{Digest, Md5};

extern "C" {
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn tolower(c: c_int) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
}

/// A C++ exception in a callback: the run ends, the caller rethrows it.
#[derive(Debug)]
pub struct Abort;

pub type R<T> = Result<T, Abort>;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    Info,
    Warning,
    Error,
}

/// An entry of a loaded par2 file's source file map, in the map's order.
pub enum ParEntry {
    /// no source file or no description packet
    Damaged,
    /// the local file name and the printed 16 KiB hash
    File { name: Vec<u8>, hash: Vec<u8> },
}

/// A file read from its start.
pub enum Read {
    OpenFailed,
    ReadFailed,
    Bytes(usize),
}

pub trait Env {
    fn stopped(&mut self) -> R<bool>;
    /// the progress label and stage set, then UpdateProgress
    fn progress(&mut self, label: &[u8], stage: i32) -> R<()>;
    fn message(&mut self, kind: Kind, text: &[u8]) -> R<()>;
    fn debug(&mut self, text: &[u8]) -> R<()>;
    /// DirBrowser's snapshot of a directory
    fn list_dir(&mut self, dir: &[u8]) -> R<Vec<Vec<u8>>>;
    fn dir_exists(&mut self, path: &[u8]) -> R<bool>;
    fn file_exists(&mut self, path: &[u8]) -> R<bool>;
    fn file_size(&mut self, path: &[u8]) -> R<i64>;
    /// DiskFile::Read of the start of a file into `buf`
    fn read(&mut self, path: &[u8], buf: &mut [u8]) -> R<Read>;
    /// LoadPacketsFromFile (None when it fails or the file is empty)
    fn load_par(&mut self, path: &[u8]) -> R<Option<Vec<ParEntry>>>;
    /// ParParser::FindMainPars
    fn find_main_pars(&mut self, dir: &[u8]) -> R<Vec<Vec<u8>>>;
    fn register_parred(&mut self, name: &[u8]) -> R<()>;
    /// RenameFile without the count: true when the file was moved
    fn rename(&mut self, src: &[u8], dst: &[u8]) -> R<bool>;
    /// Util::MatchFileExt with ParIgnoreExt
    fn ignored_ext(&mut self, name: &[u8]) -> R<bool>;
    /// ParParser::FilenameFold
    fn fold(&self, byte: u8) -> u8;
}

/// The members the caller reads and sets.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct State {
    pub file_count: i32,
    pub cur_file: i32,
    pub renamed_count: i32,
    pub has_missed_files: bool,
    pub has_damaged_par_files: bool,
    pub detect_missing: bool,
}

const BSTRING: usize = 1023;
const HEADER: usize = 64;
const MAGIC: &[u8; 8] = b"PAR2\0PKT";

/// BString<1024>'s cut.
fn bstring(mut s: Vec<u8>) -> Vec<u8> {
    s.truncate(BSTRING);
    s
}

/// BString<1024>("%s%c%s", dir, PATH_SEPARATOR, name).
fn join(dir: &[u8], sep: u8, name: &[u8]) -> Vec<u8> {
    bstring([dir, &[sep], name].concat())
}

fn c(s: &[u8]) -> Vec<u8> {
    let mut v: Vec<u8> = s.iter().take_while(|&&b| b != 0).copied().collect();
    v.push(0);
    v
}

fn base_name(path: &[u8]) -> &[u8] {
    &path[crate::paths::base_file_name(path)..]
}

fn text(parts: &[&[u8]]) -> Vec<u8> {
    parts.concat()
}

struct FileHash {
    filename: Vec<u8>,
    hash: Vec<u8>,
    exists: bool,
}

struct ParInfo {
    filename: Vec<u8>,
    set_id: Vec<u8>,
}

pub struct ParRenamer<'a, E: Env> {
    env: &'a mut E,
    state: &'a mut State,
    sep: u8,
    dest_dir: Vec<u8>,
    dir_list: Vec<Vec<u8>>,
    file_hashes: Vec<FileHash>,
    par_infos: Vec<ParInfo>,
    bad_pars: Vec<Vec<u8>>,
    loaded_pars: Vec<Vec<u8>>,
}

/// ParRenamer::Execute.
pub fn execute<E: Env>(env: &mut E, state: &mut State, info_name: &[u8], dest_dir: &[u8], sep: u8) -> R<()> {
    let mut r = ParRenamer { env, state, sep, dest_dir: dest_dir.to_vec(), dir_list: Vec::new(), file_hashes: Vec::new(),
        par_infos: Vec::new(), bad_pars: Vec::new(), loaded_pars: Vec::new() };
    r.run(info_name)
}

impl<E: Env> ParRenamer<'_, E> {
    fn run(&mut self, info_name: &[u8]) -> R<()> {
        self.env.progress(&text(&[b"Checking renamed files for ", info_name]), 0)?;
        let dest_dir = self.dest_dir.clone();
        self.build_dir_list(&dest_dir)?;

        for dir in std::mem::take(&mut self.dir_list) {
            self.env.debug(&text(&[b"Checking ", &dir]))?;
            self.file_hashes.clear();
            self.par_infos.clear();
            self.bad_pars.clear();
            self.loaded_pars.clear();

            self.check_files(&dir, true)?;
            self.rename_par_files(&dir)?;

            self.load_main_par_files(&dir)?;
            if self.state.has_damaged_par_files {
                self.load_extra_par_files(&dir)?;
            }

            self.check_files(&dir, false)?;

            if self.state.detect_missing {
                self.check_missing()?;
            }

            if self.state.renamed_count > 0 && !self.bad_pars.is_empty() {
                self.rename_bad_par_files()?;
            }
        }
        Ok(())
    }

    fn build_dir_list(&mut self, dir: &[u8]) -> R<()> {
        self.dir_list.push(dir.to_vec());
        for name in self.env.list_dir(dir)? {
            if !self.env.stopped()? {
                let full = join(dir, self.sep, &name);
                if self.env.dir_exists(&full)? {
                    self.build_dir_list(&full)?;
                } else {
                    self.state.file_count = self.state.file_count.wrapping_add(1);
                }
            }
        }
        Ok(())
    }

    fn load_main_par_files(&mut self, dir: &[u8]) -> R<()> {
        for name in self.env.find_main_pars(dir)? {
            let full = join(dir, self.sep, &name);
            self.load_par_file(&full)?;
        }
        Ok(())
    }

    fn load_extra_par_files(&mut self, dir: &[u8]) -> R<()> {
        for name in self.env.list_dir(dir)? {
            let full = join(dir, self.sep, &name);
            let env = &*self.env;
            if crate::parparser::parse_par_filename(&full, true, &|b| env.fold(b)).is_some()
                && !self.bad_pars.contains(&full) && !self.loaded_pars.contains(&full) {
                self.load_par_file(&full)?;
            }
        }
        Ok(())
    }

    fn load_par_file(&mut self, path: &[u8]) -> R<()> {
        let Some(entries) = self.env.load_par(path)? else {
            self.env.message(Kind::Warning, &text(&[b"Could not load par2-file ", path]))?;
            self.state.has_damaged_par_files = true;
            self.bad_pars.push(path.to_vec());
            return Ok(());
        };

        self.loaded_pars.push(path.to_vec());
        self.env.message(Kind::Info, &text(&[b"Loaded par2-file ", base_name(path), b" for par-rename"]))?;

        // a par2-file missing several description packets is listed (and
        // later renamed to .bad) once
        let mut damaged = false;
        for entry in entries {
            if self.env.stopped()? {
                break;
            }
            match entry {
                ParEntry::Damaged => {
                    if !damaged {
                        self.env.message(Kind::Warning, &text(&[b"Damaged par2-file detected: ", base_name(path)]))?;
                        self.bad_pars.push(path.to_vec());
                        damaged = true;
                    }
                    self.state.has_damaged_par_files = true;
                }
                ParEntry::File { name, hash } => {
                    // the C++ compared and stored C strings
                    let name = c(&name);
                    let hash = c(&hash);
                    let (name, hash) = (&name[..name.len() - 1], &hash[..hash.len() - 1]);
                    if !self.file_hashes.iter().any(|f| f.hash == hash) {
                        self.file_hashes.push(FileHash { filename: name.to_vec(), hash: hash.to_vec(), exists: false });
                        self.env.register_parred(name)?;
                    }
                }
            }
        }
        Ok(())
    }

    fn check_files(&mut self, dir: &[u8], check_pars: bool) -> R<()> {
        for name in self.env.list_dir(dir)? {
            if self.env.stopped()? {
                continue;
            }
            let full = join(dir, self.sep, &name);
            if self.env.dir_exists(&full)? {
                continue;
            }
            let stage = if self.state.file_count > 0 {
                self.state.cur_file.wrapping_mul(1000) / self.state.file_count / 2
            } else {
                1000
            };
            self.env.progress(&text(&[b"Checking file ", &name]), stage)?;
            self.state.cur_file = self.state.cur_file.wrapping_add(1);

            if check_pars {
                self.check_par_file(&full)?;
            } else {
                self.check_regular_file(dir, &full)?;
            }
        }
        Ok(())
    }

    fn check_missing(&mut self) -> R<()> {
        for i in 0..self.file_hashes.len() {
            if self.file_hashes[i].exists {
                continue;
            }
            let name = self.file_hashes[i].filename.clone();
            if self.env.ignored_ext(&name)? {
                self.env.message(Kind::Info, &text(&[b"File ", &name, b" is missing, ignoring"]))?;
            } else {
                self.env.message(Kind::Info, &text(&[b"File ", &name, b" is missing"]))?;
                self.state.has_missed_files = true;
            }
        }
        Ok(())
    }

    fn check_regular_file(&mut self, dir: &[u8], path: &[u8]) -> R<()> {
        self.env.debug(&text(&[b"Computing hash for ", path]))?;

        let mut buf = vec![0u8; 16 * 1024];
        let n = match self.env.read(path, &mut buf)? {
            Read::OpenFailed => return self.env.message(Kind::Error, &text(&[b"Could not open file ", path])),
            Read::ReadFailed => return self.env.message(Kind::Error, &text(&[b"Could not read file ", path])),
            Read::Bytes(n) => n.min(buf.len()),
        };
        let hash16k = crate::renameanalyzer::print(&Md5::digest(&buf[..n]));
        let hash16k = &hash16k[..32];

        self.env.debug(&text(&[b"file: ", base_name(path), b"; hash16k: ", hash16k]))?;

        let Some(i) = self.file_hashes.iter().position(|f| f.hash == hash16k) else { return Ok(()) };
        let correct = self.file_hashes[i].filename.clone();
        self.env.debug(&text(&[b"Found correct filename: ", &correct]))?;
        self.file_hashes[i].exists = true;

        let dst = join(dir, self.sep, &correct);
        if !self.env.file_exists(&dst)? && !is_splitted_fragment(path, &correct) {
            self.rename_file(path, &dst)?;
        }
        Ok(())
    }

    fn check_par_file(&mut self, path: &[u8]) -> R<()> {
        self.env.debug(&text(&[b"Checking par2-header for ", path]))?;

        let mut header = [0u8; HEADER];
        match self.env.read(path, &mut header)? {
            Read::OpenFailed => return self.env.message(Kind::Error, &text(&[b"Could not open file ", path])),
            Read::ReadFailed => return self.env.message(Kind::Error, &text(&[b"Could not read file ", path])),
            Read::Bytes(_) => {}
        }

        let length = u64::from_le_bytes(header[8..16].try_into().unwrap());
        if &header[..8] != MAGIC || (HEADER as u64) > length || length & 3 != 0
            || self.env.file_size(path)? < length as u32 as i32 as i64 {
            // not par2-file or damaged header, ignoring the file
            return Ok(());
        }

        let set_id: Vec<u8> = crate::renameanalyzer::print(&header[32..48])[..32].iter()
            .map(|&b| unsafe { tolower(b as c_int) } as u8).collect();

        self.env.debug(&text(&[b"Storing: ", base_name(path), b"; setid: ", &set_id]))?;
        self.par_infos.push(ParInfo { filename: path.to_vec(), set_id });
        Ok(())
    }

    fn rename_par_files(&mut self, dir: &[u8]) -> R<()> {
        if self.need_rename_par_files() {
            for i in 0..self.par_infos.len() {
                let filename = self.par_infos[i].filename.clone();
                let set_id = self.par_infos[i].set_id.clone();
                self.rename_par_file(dir, &filename, &set_id)?;
            }
        }
        Ok(())
    }

    /// ParseParFilename's base length; 0 where the C++ read an uninitialized int.
    fn base_len(&self, name: &[u8]) -> usize {
        crate::parparser::parse_par_filename(name, true, &|b| self.env.fold(b)).map_or(0, |(len, _)| len)
    }

    fn need_rename_par_files(&self) -> bool {
        for (i, par1) in self.par_infos.iter().enumerate() {
            let base1 = c(base_name(&par1.filename));
            let Some(dot) = base1[..base1.len() - 1].iter().rposition(|&b| b == b'.') else { return true };
            if unsafe { strcasecmp(base1[dot..].as_ptr().cast(), c".par2".as_ptr()) } != 0 {
                // file doesn't have "par2" extension
                return true;
            }
            let len1 = self.base_len(&base1[..base1.len() - 1]);
            for par2 in &self.par_infos[i + 1..] {
                if par1.set_id == par2.set_id {
                    let base2 = c(base_name(&par2.filename));
                    let len2 = self.base_len(&base2[..base2.len() - 1]);
                    if len1 != len2 || unsafe { strncasecmp(base1.as_ptr().cast(), base2.as_ptr().cast(), len1) } != 0 {
                        // same setid but different base file names
                        return true;
                    }
                }
            }
        }
        false
    }

    fn rename_par_file(&mut self, dir: &[u8], filename: &[u8], set_id: &[u8]) -> R<()> {
        self.env.debug(&text(&[b"Renaming: ", base_name(filename), b"; setid: ", set_id]))?;
        // the first name, then the next one while the last one exists
        let mut num: i32 = 1;
        loop {
            let dest = bstring([dir, &[self.sep], set_id, format!(".vol{num:03}+01.PAR2").as_bytes()].concat());
            num = num.wrapping_add(1);
            if !self.env.file_exists(&dest)? {
                return self.rename_file(filename, &dest);
            }
        }
    }

    fn rename_file(&mut self, src: &[u8], dst: &[u8]) -> R<()> {
        if self.env.rename(src, dst)? {
            self.state.renamed_count = self.state.renamed_count.wrapping_add(1);
        }
        Ok(())
    }

    fn rename_bad_par_files(&mut self) -> R<()> {
        for bad in self.bad_pars.clone() {
            let dest = bstring([&bad[..], b".bad"].concat());
            self.rename_file(&bad, &dest)?;
        }
        Ok(())
    }
}

/// ParRenamer::IsSplittedFragment: the disk file is "<correct name>.NNN"
/// with NNN (all digits) at most 1 (.000 or .001; atoi's value).
pub fn is_splitted_fragment(filename: &[u8], correct_name: &[u8]) -> bool {
    let base = c(base_name(filename));
    let correct = c(correct_name);
    let base_len = correct.len() - 1;
    let has_extension = base[..base.len() - 1].contains(&b'.');
    if !has_extension || unsafe { strncasecmp(base.as_ptr().cast(), correct.as_ptr().cast(), base_len) } != 0 {
        return false;
    }
    // strncasecmp matched base_len bytes, none of them the terminator
    if base.get(base_len) != Some(&b'.') {
        return false;
    }
    let digits = &base[base_len + 1..base.len() - 1];
    digits.iter().all(u8::is_ascii_digit) && unsafe { atoi(base[base_len + 1..].as_ptr().cast()) } <= 1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitted_fragments() {
        assert!(is_splitted_fragment(b"/d/movie.mkv.001", b"movie.mkv"));
        assert!(is_splitted_fragment(b"/d/MOVIE.MKV.000", b"movie.mkv"));
        assert!(is_splitted_fragment(b"/d/movie.mkv.", b"movie.mkv"));
        assert!(!is_splitted_fragment(b"/d/movie.mkv.002", b"movie.mkv"));
        assert!(!is_splitted_fragment(b"/d/movie.mkv.001x", b"movie.mkv"));
        assert!(!is_splitted_fragment(b"/d/movie.mkv", b"movie.mkv"));
        assert!(!is_splitted_fragment(b"/d/other.001", b"movie.mkv"));
        // atoi of a number beyond long is LONG_MAX, as int -1
        assert!(is_splitted_fragment(b"/d/a.99999999999999999999999", b"a"));
    }

    #[test]
    fn bstring_cut() {
        assert_eq!(join(&[b'a'; 1020], b'/', b"bcdef").len(), 1023);
    }
}
