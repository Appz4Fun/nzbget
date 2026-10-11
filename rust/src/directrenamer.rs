//! DirectRenamer's new names (DirectRenamer.cpp): the name a downloaded file
//! gets from the par2 file list (by the MD5 of its first 16 KiB), the name a
//! par2 file gets from its set id, and whether a download's par2 files need
//! renaming at all, as the C++ did it (strcmp/strcasecmp in the current
//! locale, the first ".vol" and the last '.' after it, setw(3) volume numbers).

use std::ffi::{c_char, c_int, CStr};

extern "C" {
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
}

/// BuildNewRegularName: the par2 file name the first par2 hash equal to
/// `hash16k` names, if that differs from `old_name` in more than case.
/// `hashes` yields (filename, hash) in list order; the result is the
/// hash's index.
pub fn regular_name<'a>(old_name: &CStr, hash16k: &CStr, hashes: impl Iterator<Item = (&'a CStr, &'a CStr)>) -> Option<usize> {
    if hash16k.is_empty() {
        return None;
    }
    let (index, (filename, _)) = hashes.enumerate().find(|(_, (_, hash))| *hash == hash16k)?;
    (unsafe { strcasecmp(old_name.as_ptr(), filename.as_ptr()) } != 0).then_some(index)
}

/// ostream << setfill('0') << setw(3) << vol: padded on the left, also
/// before a minus sign.
fn push_vol(out: &mut Vec<u8>, vol: i32) {
    let digits = vol.to_string();
    out.extend(std::iter::repeat_n(b'0', 3usize.saturating_sub(digits.len())));
    out.extend_from_slice(digits.as_bytes());
}

/// BuildNewParName: `set_id` plus the old ".volNN+NN.par2" suffix when that
/// is free in `dest_dir`, else the next free "<set_id>.volNNN+01.PAR2",
/// counting `vol` up for every name tried.
pub fn par_name(old_name: &[u8], dest_dir: &[u8], set_id: &[u8], separator: u8, vol: &mut i32, exists: &mut dyn FnMut(&[u8]) -> bool) -> Vec<u8> {
    par_name_formatted(old_name, dest_dir, set_id, separator, vol, exists, &mut |vol| {
        let mut name = set_id.to_vec();
        name.extend_from_slice(b".vol");
        push_vol(&mut name, vol);
        name.extend_from_slice(b"+01.PAR2");
        Some(name)
    })
}

/// A non-classic C++ locale may group digits or install a custom num_put
/// facet. Let that stream format candidates; None stops after an exception.
pub fn par_name_formatted(old_name: &[u8], dest_dir: &[u8], set_id: &[u8], separator: u8, vol: &mut i32,
    exists: &mut dyn FnMut(&[u8]) -> bool, format: &mut dyn FnMut(i32) -> Option<Vec<u8>>) -> Vec<u8> {
    let full = |name: &[u8]| [dest_dir, &[separator], name].concat();
    let suffix = old_name.windows(4).position(|w| w == b".vol").map(|i| &old_name[i..]);
    if let Some(suffix) = suffix {
        let extension = &suffix[suffix.iter().rposition(|&b| b == b'.').unwrap_or(0)..];
        let mut ext = extension.to_vec();
        ext.push(0);
        if unsafe { strcasecmp(ext.as_ptr().cast(), c".par2".as_ptr()) } == 0 {
            let name = [set_id, suffix].concat();
            if !exists(&full(&name)) {
                return name;
            }
        }
    }
    loop {
        let Some(name) = format(*vol) else { return Vec::new() };
        *vol = vol.wrapping_add(1);
        if !exists(&full(&name)) {
            return name;
        }
    }
}

/// NeedRenamePars: a par2 file without the ".par2" extension (any case), or
/// two par2 files of one set that ParParser::SameParCollection does not put
/// in the same collection. `pars` is (filename, set id); `fold` is the C++
/// tolower ParParser uses. SameParCollection is symmetric, so each pair is
/// checked once.
pub fn need_rename_pars(pars: &[(Option<&CStr>, &CStr)], fold: &dyn Fn(u8) -> u8) -> bool {
    pars.iter().enumerate().any(|(i, &(name, set_id))| {
        let Some(name) = name else { return true };
        !crate::util::ends_with(name.to_bytes(), b".par2", false) ||
            pars[i + 1..].iter().any(|&(name2, set_id2)| {
                set_id == set_id2 && name2.is_none_or(|name2| !crate::parparser::same_par_collection(name, name2, false, fold))
            })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regular_name_takes_the_first_matching_hash() {
        let hashes = [(c"a.mkv", c"H1"), (c"b.mkv", c"H2"), (c"c.mkv", c"H2")];
        let find = |old: &CStr, hash: &CStr| regular_name(old, hash, hashes.iter().copied());
        assert_eq!(find(c"x.bin", c"H2"), Some(1));
        assert_eq!(find(c"B.MKV", c"H2"), None);
        assert_eq!(find(c"x.bin", c""), None);
        assert_eq!(find(c"x.bin", c"H3"), None);
    }

    #[test]
    fn par_name_reuses_the_suffix_or_counts_volumes() {
        let mut taken = vec![b"/d/S.vol01+02.par2".to_vec()];
        let mut vol = 1;
        let mut exists = |p: &[u8]| taken.iter().any(|t| t == p);
        assert_eq!(par_name(b"x.vol01+02.PaR2", b"/d", b"T", b'/', &mut vol, &mut exists), b"T.vol01+02.PaR2");
        assert_eq!(vol, 1);
        assert_eq!(par_name(b"x.vol01+02.par2", b"/d", b"S", b'/', &mut vol, &mut exists), b"S.vol001+01.PAR2");
        assert_eq!(vol, 2);
        taken.push(b"/d/S.vol002+01.PAR2".to_vec());
        let mut exists = |p: &[u8]| taken.iter().any(|t| t == p);
        assert_eq!(par_name(b"x.par2", b"/d", b"S", b'/', &mut vol, &mut exists), b"S.vol003+01.PAR2");
        assert_eq!(vol, 4);
        // the last '.' after the first ".vol"
        assert_eq!(par_name(b"a.vol.b.vol1.par2", b"", b"S", b'/', &mut vol, &mut |_| false), b"S.vol.b.vol1.par2");
        assert_eq!(par_name(b"a.vol1.par2.x", b"", b"S", b'/', &mut vol, &mut |_| false), b"S.vol004+01.PAR2");
        let mut vol = -5;
        assert_eq!(par_name(b"", b"", b"S", b'/', &mut vol, &mut |_| false), b"S.vol0-5+01.PAR2");
        let mut vol = 1234;
        assert_eq!(par_name(b"", b"", b"S", b'/', &mut vol, &mut |_| false), b"S.vol1234+01.PAR2");
        let mut vol = i32::MAX;
        par_name(b"", b"", b"S", b'/', &mut vol, &mut |_| false);
        assert_eq!(vol, i32::MIN);
    }

    #[test]
    fn need_rename_pars_checks_extensions_and_sets() {
        let fold = |b: u8| b.to_ascii_lowercase();
        let need = |pars: &[(Option<&CStr>, &CStr)]| need_rename_pars(pars, &fold);
        assert!(!need(&[]));
        assert!(!need(&[(Some(c"a.PAR2"), c"S"), (Some(c"A.vol1+2.par2"), c"S"), (Some(c"b.par2"), c"T")]));
        assert!(need(&[(Some(c"a.par2"), c"S"), (Some(c"b.vol1+2.par2"), c"S")]));
        assert!(need(&[(Some(c"a.par"), c"S")]));
        assert!(need(&[(None, c"S")]));
        assert!(need(&[(Some(c"a.par2"), c"S"), (None, c"S")]));
        // a name SameParCollection cannot parse is never in a collection
        assert!(need(&[(Some(c".par2"), c"S"), (Some(c".par2"), c"S")]));
        assert!(!need(&[(Some(c".par2"), c"S"), (Some(c".par2"), c"T")]));
    }
}
