//! CollectionAnalyzer: what a download's files are (main video or book,
//! sample, subtitles, NFOs, others; an ambiguous collection or a disc
//! structure) and how to rename them to the release name. It matches the
//! C++ code; the C++ side walks the directory and answers whether a path
//! exists.

use std::ffi::c_int;

extern "C" {
    fn isalpha(c: c_int) -> c_int;
    fn tolower(c: c_int) -> c_int;
}

use crate::deobfuscation::is_excessively_obfuscated;
use crate::filetypes::{is_audio_ext, is_book_ext, is_disc_descriptor_ext, is_disc_structure_ext, is_nfo_ext, is_sample_stem, is_subtitle_ext, is_video_ext};
use crate::paths::{sanitize_path_segment, PATH_SEPARATOR};

/// A file of the download (FileEntry).
#[derive(Clone, Default, Debug, PartialEq)]
pub struct Entry {
    pub path: Vec<u8>,
    pub filename: Vec<u8>,
    pub stem: Vec<u8>,
    pub ext: Vec<u8>,
    pub size: u64,
}

/// AnalysisResult; files by their index in the input (None: an empty
/// FileEntry).
#[derive(Default, Debug, PartialEq)]
pub struct Analysis {
    pub main_video: Option<usize>,
    pub sample_video: Option<usize>,
    pub main_book: Option<usize>,
    pub subtitles: Vec<usize>,
    pub nfos: Vec<usize>,
    pub other_files: Vec<usize>,
    pub ambiguous: bool,
    pub disc_structure: bool,
    pub has_audio: bool,
}

const AMBIGUOUS_COLLECTION_RATIO: u64 = 3;

/// CollectionAnalyzer::Analyze.
pub fn analyze(files: &[Entry]) -> Analysis {
    let mut r = Analysis::default();
    // the video track: the largest (the first of equal ones), the second largest
    let (mut largest, mut second, mut video_count) = (0u64, 0u64, 0);
    let mut audio_count = 0;
    let (mut book_count, mut dominant_book, mut dominant_size) = (0, None, 0u64);
    let mut books = Vec::new();
    for (k, f) in files.iter().enumerate() {
        let ext = &f.ext[..];
        if is_disc_structure_ext(ext) || is_disc_descriptor_ext(ext) {
            r.disc_structure = true;
        } else if is_audio_ext(ext) {
            r.has_audio = true;
            audio_count += 1;
            r.other_files.push(k);
        } else if is_book_ext(ext) {
            book_count += 1;
            if f.size > dominant_size {
                dominant_size = f.size;
                dominant_book = Some(k);
            }
            books.push(k);
        } else if is_video_ext(ext) {
            if is_sample_stem(&f.stem) {
                r.sample_video = Some(k);
            } else {
                video_count += 1;
                if f.size > largest {
                    second = largest;
                    largest = f.size;
                    r.main_video = Some(k);
                } else if f.size > second {
                    second = f.size;
                }
            }
        } else if is_subtitle_ext(ext) {
            r.subtitles.push(k);
        } else if is_nfo_ext(ext) {
            r.nfos.push(k);
        } else {
            r.other_files.push(k);
        }
    }
    // the 3:1 dominance rule: comparable videos (a season pack) have no main one
    r.ambiguous = video_count > 1 && largest <= second.wrapping_mul(AMBIGUOUS_COLLECTION_RATIO);
    // music albums without video
    if audio_count > 1 && video_count == 0 {
        r.ambiguous = true;
    }
    if video_count == 0 {
        if book_count == 1 {
            r.main_book = dominant_book;
        } else if book_count > 1 {
            r.ambiguous = true;
            r.other_files.extend(books);
        }
    } else {
        r.other_files.extend(books);
    }
    r
}

impl Analysis {
    /// AnalysisResult::CanRename.
    pub fn can_rename(&self, files: &[Entry]) -> bool {
        let named = |i: Option<usize>| i.is_some_and(|k| !files[k].filename.is_empty());
        (named(self.main_video) || named(self.main_book)) && !self.ambiguous && !self.disc_structure
    }
}

/// Util::StrCaseCmp (the C library's tolower).
fn str_case_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(&x, &y)| unsafe { tolower(x as c_int) == tolower(y as c_int) })
}

/// std::filesystem's stem and extension of a file name: "." and ".." have
/// none, a name starting with its only '.' has no extension.
pub fn stem_ext(name: &[u8]) -> (&[u8], &[u8]) {
    if name == b"." || name == b".." {
        return (name, &[]);
    }
    match name.iter().rposition(|&b| b == b'.') {
        Some(k) if k > 0 => (&name[..k], &name[k..]),
        _ => (name, &[]),
    }
}

/// The file name of a path (after the last separator).
fn file_name(path: &[u8]) -> &[u8] {
    path.iter().rposition(|&b| b == PATH_SEPARATOR).map_or(path, |k| &path[k + 1..])
}

/// parent_path() / name, for the paths the directory walk gives.
fn sibling(path: &[u8], name: &[u8]) -> Vec<u8> {
    let parent = match path.iter().rposition(|&b| b == PATH_SEPARATOR) {
        None => &path[..0],
        Some(0) => &path[..1],
        Some(k) => &path[..k],
    };
    let mut p = parent.to_vec();
    if !p.is_empty() && *p.last().unwrap() != PATH_SEPARATOR {
        p.push(PATH_SEPARATOR);
    }
    p.extend_from_slice(name);
    p
}

/// A planned rename (RenameAction): the file's index, the new path and name.
#[derive(Debug, PartialEq)]
pub struct Action {
    pub src: usize,
    pub dst_path: Vec<u8>,
    pub new_filename: Vec<u8>,
}

/// RenamePlan.
#[derive(Default, Debug, PartialEq)]
pub struct Plan {
    pub actions: Vec<Action>,
    pub ambiguous: bool,
    pub disc_structure: bool,
    pub can_rename: bool,
    pub target_name_obfuscated: bool,
    pub effective_base_name: Vec<u8>,
}

/// What BuildPlan asks the C++ side.
pub trait Disk {
    /// fs::exists (false on an error).
    fn exists(&mut self, path: &[u8]) -> bool;
    /// Util::MatchFileExt(path, ignoreExt, ",").
    fn ignored(&mut self, path: &[u8]) -> bool;
}

/// CollectionAnalyzer::BuildPlan for the files of the directory (in the
/// order the C++ walk gave them) and whether it found a disc structure
/// directory.
pub fn build_plan(files: &[Entry], disc_dir: bool, target_name: &[u8], disk: &mut dyn Disk) -> Plan {
    let mut analysis = analyze(files);
    if disc_dir {
        analysis.disc_structure = true;
    }
    let mut plan = Plan {
        ambiguous: analysis.ambiguous,
        disc_structure: analysis.disc_structure,
        can_rename: analysis.can_rename(files),
        ..Plan::default()
    };
    if !plan.can_rename {
        return plan;
    }
    let mut used: Vec<Vec<u8>> = Vec::new();
    let mut rename = |plan: &mut Plan, k: usize, new_basename: &[u8]| -> Vec<u8> {
        let entry = &files[k];
        let clean = sanitize_path_segment(new_basename);
        if clean.is_empty() {
            return entry.stem.clone();
        }
        if entry.filename == clean {
            used.push(entry.path.clone());
            return entry.stem.clone();
        }
        let mut dst = sibling(&entry.path, &clean);
        if disk.ignored(&dst) {
            return entry.stem.clone();
        }
        let collides = |disk: &mut dyn Disk, used: &[Vec<u8>], p: &[u8]| disk.exists(p) || used.iter().any(|u| str_case_eq(u, p));
        if collides(disk, &used, &dst) {
            let (stem, ext) = stem_ext(&clean);
            let mut n = 0;
            loop {
                n += 1;
                let name = [stem, b".duplicate", n.to_string().as_bytes(), ext].concat();
                dst = sibling(&entry.path, &name);
                if !collides(disk, &used, &dst) {
                    break;
                }
            }
        }
        let name = file_name(&dst).to_vec();
        let final_stem = stem_ext(&name).0.to_vec();
        used.push(dst.clone());
        plan.actions.push(Action { src: k, dst_path: dst, new_filename: name });
        final_stem
    };

    let clean_target = sanitize_path_segment(target_name);
    let can_use_target = !clean_target.is_empty() && clean_target != b"nzb" && !is_excessively_obfuscated(&clean_target);

    // the main video, or else the main book
    let main = analysis
        .main_video
        .filter(|&k| !files[k].filename.is_empty())
        .map(|k| (k, true))
        .or_else(|| analysis.main_book.filter(|&k| !files[k].filename.is_empty()).map(|k| (k, false)));
    let Some((main, is_video)) = main else { return plan };
    let f = &files[main];
    let base = if is_excessively_obfuscated(&f.filename) {
        if can_use_target {
            rename(&mut plan, main, &[&clean_target[..], &f.ext].concat())
        } else {
            plan.target_name_obfuscated = true;
            f.stem.clone()
        }
    } else if !f.ext.is_empty() && !ends_with_case(&f.filename, &f.ext) {
        rename(&mut plan, main, &[&f.filename[..], &f.ext].concat())
    } else {
        f.stem.clone()
    };
    plan.effective_base_name = base.clone();
    if is_video && !base.is_empty() && !is_excessively_obfuscated(&base) {
        if let Some(s) = analysis.sample_video.filter(|&k| !files[k].filename.is_empty()) {
            let name = resolve_sample_name(&base, &files[s].ext);
            rename(&mut plan, s, &name);
        }
        for &s in &analysis.subtitles {
            let name = resolve_subtitle_name(&base, &files[s].stem, &files[s].ext);
            rename(&mut plan, s, &name);
        }
    }
    plan
}

/// Util::EndsWith(str, suffix, false).
fn ends_with_case(s: &[u8], suffix: &[u8]) -> bool {
    suffix.is_empty() || (s.len() >= suffix.len() && str_case_eq(&s[s.len() - suffix.len()..], suffix))
}

/// CollectionAnalyzer::ResolveTargetName.
pub fn resolve_target_name(meta: &[u8], nzb: &[u8]) -> Vec<u8> {
    if !meta.is_empty() && !is_excessively_obfuscated(meta) {
        meta.to_vec()
    } else if !nzb.is_empty() {
        nzb.to_vec()
    } else {
        meta.to_vec()
    }
}

/// CollectionAnalyzer::ResolveSubtitleName: a language tag of the stem
/// ("12345.en") kept.
pub fn resolve_subtitle_name(base: &[u8], sub_stem: &[u8], sub_ext: &[u8]) -> Vec<u8> {
    if let Some(dot) = sub_stem.iter().rposition(|&b| b == b'.').filter(|&d| d > 0) {
        let tag = &sub_stem[dot + 1..];
        if (2..=4).contains(&tag.len()) && tag.iter().all(|&c| unsafe { isalpha(c as c_int) } != 0) {
            return [base, b".", tag, sub_ext].concat();
        }
    }
    [base, sub_ext].concat()
}

/// CollectionAnalyzer::ResolveSampleName.
pub fn resolve_sample_name(base: &[u8], ext: &[u8]) -> Vec<u8> {
    [base, b"-sample", ext].concat()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(path: &str, size: u64) -> Entry {
        let name = file_name(path.as_bytes()).to_vec();
        let (stem, ext) = stem_ext(&name);
        Entry { path: path.into(), filename: name.clone(), stem: stem.to_vec(), ext: ext.to_vec(), size }
    }

    struct NoDisk;
    impl Disk for NoDisk {
        fn exists(&mut self, _: &[u8]) -> bool {
            false
        }
        fn ignored(&mut self, _: &[u8]) -> bool {
            false
        }
    }

    #[test]
    fn plan() {
        let files = [entry("/d/a8f7s6d5f4g3h2j1k0l9.mkv", 1000), entry("/d/a8f7s6d5f4g3h2j1k0l9.en.srt", 1), entry("/d/x-sample.mkv", 10)];
        let p = build_plan(&files, false, b"Show.S01E01.1080p", &mut NoDisk);
        assert!(p.can_rename);
        assert_eq!(p.actions[0].new_filename, b"Show.S01E01.1080p.mkv");
        assert_eq!(p.actions[1].new_filename, b"Show.S01E01.1080p-sample.mkv");
        assert_eq!(p.actions[2].new_filename, b"Show.S01E01.1080p.en.srt");
    }

    #[test]
    fn ambiguous() {
        let files = [entry("/d/e1.mkv", 1000), entry("/d/e2.mkv", 900)];
        assert!(analyze(&files).ambiguous);
        assert_eq!(stem_ext(b".bashrc"), (&b".bashrc"[..], &b""[..]));
    }
}
