//! Rust parts of nzbget, called from C++ through a C ABI (see nzbget_rs.h).
//! Each module replaces one C++ routine and must match its output byte for byte.

pub mod collection;
pub mod crc;
pub mod decode;
pub mod decoder;
pub mod deobfuscation;
pub mod escape;
pub mod feedfilter;
pub mod filetypes;
pub mod paths;
pub mod text;
pub mod url;
pub mod util;
pub mod webserver;
pub mod webutil;
pub mod ffi;
pub mod wildmask;
