//! FileSystem's deletes and backup renames (FileSystem.cpp, POSIX):
//! DeleteDirectory (a folder that is empty or holds only hidden files, its
//! empty subfolders removed), DeleteDirectoryWithContent, RenameBak and
//! GetFileExtension, as the C++ did them - links never followed, the same
//! order of deletes and error handling. Delete paths are checked against
//! BString<1024>; RenameBak retains its original buffer behavior. Every file
//! system call stays with the caller (`Ops`); `last_error` is
//! GetLastErrorMessage for the call that failed last.

/// GetPathTypeNoFollow.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PathType {
    Error,
    File,
    Directory,
    Link,
    DirectoryLink,
}

/// A C++ exception in a callback: the operation ends, the caller rethrows it.
#[derive(Debug)]
pub struct Abort;

pub type R<T> = Result<T, Abort>;

pub trait Ops {
    /// lstat: a link is a link
    fn path_type(&mut self, path: &[u8]) -> R<PathType>;
    fn remove_dir(&mut self, path: &[u8]) -> R<bool>;
    fn delete_file(&mut self, path: &[u8]) -> R<bool>;
    /// DeleteLink
    fn delete_link(&mut self, path: &[u8], kind: PathType) -> R<bool>;
    /// DirBrowser's snapshot
    fn list(&mut self, dir: &[u8]) -> R<Vec<Vec<u8>>>;
    fn file_exists(&mut self, path: &[u8]) -> R<bool>;
    fn dir_exists(&mut self, path: &[u8]) -> R<bool>;
    fn move_file(&mut self, from: &[u8], to: &[u8]) -> R<bool>;
    /// GetLastErrorMessage, for the last call that failed
    fn last_error(&mut self) -> R<Vec<u8>>;
    /// errno set to ENAMETOOLONG: a path too long for the C++ buffers
    fn too_long(&mut self) -> R<()>;
}

const BSTRING: usize = 1023;

/// A path joined below a delete root; None when it would not fit the C++
/// path buffers (it is refused, never cut).
fn join_checked(dir: &[u8], sep: u8, name: &[u8]) -> Option<Vec<u8>> {
    let v = [dir, &[sep], name].concat();
    (v.len() <= BSTRING).then_some(v)
}

/// A delete root without trailing separators or trailing "." components.
pub fn normalize_root(dir: &[u8], sep: u8) -> &[u8] {
    let mut d = dir;
    loop {
        if d.len() > 1 && (d.ends_with(&[sep]) || d.ends_with(&[sep, b'.'])) {
            d = &d[..d.len() - 1];
        } else {
            return d;
        }
    }
}

fn is_link(t: PathType) -> bool {
    matches!(t, PathType::Link | PathType::DirectoryLink)
}

/// "could not delete %s: %s" with the last error.
fn could_not_delete<O: Ops>(ops: &mut O, path: &[u8]) -> R<Vec<u8>> {
    let error = ops.last_error()?;
    Ok([&b"could not delete "[..], path, b": ", &error].concat())
}

/// DeleteDirectory: true when the folder was removed.
pub fn delete_directory<O: Ops>(ops: &mut O, dir: &[u8], sep: u8) -> R<bool> {
    let mut too_long = false;
    let result = delete_directory_inner(ops, dir, sep, &mut too_long)?;
    if too_long {
        ops.too_long()?;
    }
    Ok(result && !too_long)
}

fn delete_directory_inner<O: Ops>(ops: &mut O, dir: &[u8], sep: u8, too_long: &mut bool) -> R<bool> {
    let dir = normalize_root(dir, sep);
    if dir.len() > BSTRING {
        *too_long = true;
        ops.too_long()?;
        return Ok(false);
    }
    if ops.remove_dir(dir)? {
        return Ok(true);
    }
    // a link is never followed: the folder it points to isn't this one's to clean
    if is_link(ops.path_type(dir)?) {
        return Ok(false);
    }
    // check if directory contains only hidden files (whose names start with dot)
    for name in ops.list(dir)? {
        let removed = match join_checked(dir, sep, &name) {
            Some(full) => ops.path_type(&full)? == PathType::Directory && delete_directory_inner(ops, &full, sep, too_long)?,
            None => {
                *too_long = true;
                ops.too_long()?;
                false
            }
        };
        if removed {
            continue;
        }
        if name.first() != Some(&b'.') {
            // calling RemoveDirectory to set correct errno
            return ops.remove_dir(dir);
        }
    }
    let mut errmsg = Vec::new();
    if !delete_directory_with_content_inner(ops, dir, sep, &mut errmsg, too_long)? {
        // calling RemoveDirectory to set correct errno
        return ops.remove_dir(dir);
    }
    Ok(true)
}

/// DeleteDirectoryWithContent: `errmsg` cleared, then the first error.
pub fn delete_directory_with_content<O: Ops>(ops: &mut O, dir: &[u8], sep: u8, errmsg: &mut Vec<u8>) -> R<bool> {
    let mut too_long = false;
    let result = delete_directory_with_content_inner(ops, dir, sep, errmsg, &mut too_long)?;
    if too_long {
        ops.too_long()?;
    }
    Ok(result && !too_long)
}

fn delete_directory_with_content_inner<O: Ops>(ops: &mut O, dir: &[u8], sep: u8, errmsg: &mut Vec<u8>, too_long: &mut bool) -> R<bool> {
    errmsg.clear();
    let given = dir;
    let dir = normalize_root(dir, sep);
    if dir.len() > BSTRING {
        *too_long = true;
        ops.too_long()?;
        *errmsg = could_not_delete(ops, given)?;
        return Ok(false);
    }
    let root = ops.path_type(dir)?;
    if is_link(root) {
        if ops.delete_link(dir, root)? {
            return Ok(true);
        }
        *errmsg = could_not_delete(ops, given)?;
        return Ok(false);
    }
    if root != PathType::Directory {
        *errmsg = could_not_delete(ops, given)?;
        return Ok(false);
    }

    let mut ok = true;
    for name in ops.list(dir)? {
        let Some(full) = join_checked(dir, sep, &name) else {
            *too_long = true;
            ops.too_long()?;
            ok = false;
            if errmsg.is_empty() {
                *errmsg = could_not_delete(ops, &[dir, &[sep], &name].concat())?;
            }
            continue;
        };
        let kind = ops.path_type(&full)?;
        let deleted = match kind {
            PathType::Directory => {
                // Keep a message already recorded before a refused path.
                if *too_long && !errmsg.is_empty() {
                    delete_directory_with_content_inner(ops, &full, sep, &mut Vec::new(), too_long)?
                } else {
                    delete_directory_with_content_inner(ops, &full, sep, errmsg, too_long)?
                }
            },
            PathType::Link | PathType::DirectoryLink => ops.delete_link(&full, kind)?,
            PathType::File => ops.delete_file(&full)?,
            PathType::Error => false,
        };
        ok &= deleted;
        if !deleted && errmsg.is_empty() {
            *errmsg = could_not_delete(ops, &full)?;
        }
    }
    let deleted = ops.remove_dir(dir)?;
    ok &= deleted;
    if !deleted && errmsg.is_empty() {
        *errmsg = ops.last_error()?;
    }
    Ok(ok)
}

/// RenameBak: the moved file's new name "<name>.<bakPart>", or
/// "<name>.<i>.<bakPart>" from 2 while that name is taken; `name` is the
/// file name without the text from its last '.' when `remove_old_extension`.
/// The new name is set before the move, also when the move fails.
pub fn rename_bak<O: Ops>(ops: &mut O, filename: &[u8], bak_part: &[u8], remove_old_extension: bool, new_name: &mut Vec<u8>) -> R<bool> {
    let base = if remove_old_extension {
        let mut changed = filename.to_vec();
        changed.truncate(BSTRING);
        if let Some(dot) = changed.iter().rposition(|&b| b == b'.') {
            changed.truncate(dot);
        }
        changed
    } else {
        filename.to_vec()
    };
    *new_name = [&base[..], b".", bak_part].concat();
    let mut i: i32 = 2;
    while ops.file_exists(new_name)? || ops.dir_exists(new_name)? {
        *new_name = [&base[..], b".", i.to_string().as_bytes(), b".", bak_part].concat();
        i = i.wrapping_add(1);
    }
    ops.move_file(filename, new_name)
}

/// GetFileExtension: the text from the last '.', if any.
pub fn file_extension(filename: &[u8]) -> Option<&[u8]> {
    filename.iter().rposition(|&b| b == b'.').map(|i| &filename[i..])
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    /// An in-memory tree: path -> kind; failing paths can't be deleted.
    struct Tree {
        nodes: BTreeMap<Vec<u8>, PathType>,
        stuck: Vec<Vec<u8>>,
        last: Vec<u8>,
        log: Vec<String>,
    }

    impl Tree {
        fn new(nodes: &[(&str, PathType)]) -> Tree {
            Tree { nodes: nodes.iter().map(|(p, t)| (p.as_bytes().to_vec(), *t)).collect(), stuck: Vec::new(), last: Vec::new(), log: Vec::new() }
        }
        fn children(&self, dir: &[u8]) -> Vec<Vec<u8>> {
            let prefix = [dir, b"/"].concat();
            self.nodes.keys().filter(|k| k.starts_with(&prefix) && !k[prefix.len()..].contains(&b'/'))
                .map(|k| k[prefix.len()..].to_vec()).collect()
        }
        fn remove(&mut self, path: &[u8], what: &str) -> bool {
            self.log.push(format!("{what} {}", String::from_utf8_lossy(path)));
            if self.stuck.iter().any(|s| s == path) || !self.nodes.contains_key(path) {
                self.last = format!("cannot {what} {}", String::from_utf8_lossy(path)).into_bytes();
                return false;
            }
            self.nodes.remove(path);
            true
        }
    }

    impl Ops for Tree {
        fn path_type(&mut self, path: &[u8]) -> R<PathType> {
            Ok(*self.nodes.get(path).unwrap_or(&PathType::Error))
        }
        fn remove_dir(&mut self, path: &[u8]) -> R<bool> {
            if self.nodes.get(path) != Some(&PathType::Directory) || !self.children(path).is_empty() {
                self.log.push(format!("rmdir {}", String::from_utf8_lossy(path)));
                self.last = b"not empty".to_vec();
                return Ok(false);
            }
            Ok(self.remove(path, "rmdir"))
        }
        fn delete_file(&mut self, path: &[u8]) -> R<bool> {
            Ok(self.remove(path, "unlink"))
        }
        fn delete_link(&mut self, path: &[u8], _: PathType) -> R<bool> {
            Ok(self.remove(path, "unlink-link"))
        }
        fn list(&mut self, dir: &[u8]) -> R<Vec<Vec<u8>>> {
            Ok(self.children(dir))
        }
        fn file_exists(&mut self, path: &[u8]) -> R<bool> {
            Ok(self.nodes.get(path) == Some(&PathType::File))
        }
        fn dir_exists(&mut self, path: &[u8]) -> R<bool> {
            Ok(self.nodes.get(path) == Some(&PathType::Directory))
        }
        fn move_file(&mut self, from: &[u8], to: &[u8]) -> R<bool> {
            let Some(t) = self.nodes.remove(from) else { return Ok(false) };
            self.nodes.insert(to.to_vec(), t);
            Ok(true)
        }
        fn last_error(&mut self) -> R<Vec<u8>> {
            Ok(self.last.clone())
        }
        fn too_long(&mut self) -> R<()> {
            self.last = b"name too long".to_vec();
            Ok(())
        }
    }

    use PathType::*;

    #[test]
    fn hidden_files_only() {
        let mut t = Tree::new(&[("/d", Directory), ("/d/.hidden", File), ("/d/empty", Directory), ("/d/.git", Directory), ("/d/.git/x", File)]);
        assert!(delete_directory(&mut t, b"/d", b'/').unwrap());
        assert!(t.nodes.is_empty());
        let mut t = Tree::new(&[("/d", Directory), ("/d/.hidden", File), ("/d/file", File)]);
        assert!(!delete_directory(&mut t, b"/d", b'/').unwrap());
        assert_eq!(t.nodes.len(), 3);
    }

    #[test]
    fn links_are_not_followed() {
        let mut t = Tree::new(&[("/l", Link)]);
        assert!(!delete_directory(&mut t, b"/l", b'/').unwrap());
        let mut t = Tree::new(&[("/d", Directory), ("/d/link", Link), ("/d/sub", Directory), ("/d/sub/f", File)]);
        let mut err = b"old".to_vec();
        assert!(delete_directory_with_content(&mut t, b"/d", b'/', &mut err).unwrap());
        assert!(err.is_empty());
        assert!(t.log.contains(&"unlink-link /d/link".to_string()));
    }

    #[test]
    fn first_error_kept() {
        let mut t = Tree::new(&[("/d", Directory), ("/d/a", File), ("/d/b", File)]);
        t.stuck = vec![b"/d/a".to_vec(), b"/d/b".to_vec()];
        let mut err = Vec::new();
        assert!(!delete_directory_with_content(&mut t, b"/d", b'/', &mut err).unwrap());
        assert_eq!(err, b"could not delete /d/a: cannot unlink /d/a");
        let mut t = Tree::new(&[("/x", File)]);
        assert!(!delete_directory_with_content(&mut t, b"/x", b'/', &mut err).unwrap());
        assert_eq!(err, b"could not delete /x: ");
    }

    #[test]
    fn rename_bak_counts() {
        let mut t = Tree::new(&[("/d/a.nzb", File), ("/d/a.bak", File), ("/d/a.2.bak", Directory)]);
        let mut name = Vec::new();
        assert!(rename_bak(&mut t, b"/d/a.nzb", b"bak", true, &mut name).unwrap());
        assert_eq!(name, b"/d/a.3.bak");
        let mut t = Tree::new(&[("/d.x/a", File)]);
        assert!(rename_bak(&mut t, b"/d.x/a", b"bak", true, &mut name).unwrap());
        assert_eq!(name, b"/d.bak");
        assert!(!rename_bak(&mut t, b"/missing", b"bak", false, &mut name).unwrap());
        assert_eq!(name, b"/missing.bak");
    }

    #[test]
    fn roots_normalized_and_long_paths_refused() {
        assert_eq!(normalize_root(b"/d/x/", b'/'), b"/d/x");
        assert_eq!(normalize_root(b"/d/x/././/", b'/'), b"/d/x");
        assert_eq!(normalize_root(b"/", b'/'), b"/");
        assert_eq!(normalize_root(b"/.//./", b'/'), b"/");
        assert_eq!(normalize_root(b"x/.", b'/'), b"x");
        let mut t = Tree::new(&[("/l", Link)]);
        let mut err = Vec::new();
        assert!(delete_directory_with_content(&mut t, b"/l/", b'/', &mut err).unwrap());
        assert_eq!(t.log, vec!["unlink-link /l".to_string()]);
        let long = format!("/{}", "a".repeat(1023));
        let mut t = Tree::new(&[(long.as_str(), Directory)]);
        assert!(!delete_directory_with_content(&mut t, long.as_bytes(), b'/', &mut err).unwrap());
        assert!(err.ends_with(b": name too long"));
        assert!(!delete_directory(&mut t, long.as_bytes(), b'/').unwrap());
        assert_eq!(t.nodes.len(), 1);
        let dir = format!("/{}", "d".repeat(1000));
        let entry = format!("{dir}/{}", "e".repeat(40));
        let mut t = Tree::new(&[(dir.as_str(), Directory), (entry.as_str(), File)]);
        assert!(!delete_directory_with_content(&mut t, dir.as_bytes(), b'/', &mut err).unwrap());
        assert_eq!(t.nodes.len(), 2);
    }

    #[test]
    fn long_child_error_survives_later_directory_and_parent_removal() {
        let dir = format!("/{}", "d".repeat(999));
        let long = format!("{dir}/.{}", "a".repeat(22));
        let short = format!("{dir}/z");
        let mut t = Tree::new(&[(dir.as_str(), Directory), (long.as_str(), File), (short.as_str(), Directory)]);
        let mut error = Vec::new();
        assert!(!delete_directory_with_content(&mut t, dir.as_bytes(), b'/', &mut error).unwrap());
        assert_eq!(error, format!("could not delete {long}: name too long").as_bytes());
        assert_eq!(t.last, b"name too long");
        assert_eq!(t.log, [format!("rmdir {short}"), format!("rmdir {dir}")]);
        assert!(t.nodes.contains_key(long.as_bytes()));
    }

    #[test]
    fn extensions() {
        assert_eq!(file_extension(b"a.tar.gz"), Some(&b".gz"[..]));
        assert_eq!(file_extension(b"/d.x/a"), Some(&b".x/a"[..]));
        assert_eq!(file_extension(b"noext"), None);
    }
}
