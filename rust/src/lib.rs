//! Rust parts of nzbget, called from C++ through a C ABI (see nzbget_rs.h).
//! Each module replaces one C++ routine and must match its output byte for byte.

pub mod crc;
pub mod decode;
pub mod escape;
pub mod text;
pub mod util;
pub mod webutil;
pub mod ffi;
pub mod wildmask;
