//! Rust parts of nzbget, called from C++ through a C ABI (see nzbget_rs.h).
//! Each module replaces one C++ routine and must match its output byte for byte.

pub mod binrpc;
pub mod bytes;
pub mod cmdline;
pub mod collection;
pub mod crc;
pub mod decode;
pub mod decoder;
pub mod deobfuscation;
pub mod directrenamer;
pub mod escape;
pub mod extload;
pub mod feedfilter;
pub mod filetypes;
pub mod fsdelete;
#[cfg(unix)]
pub mod fsops;
pub mod json;
pub mod manifest;
pub mod nntp;
pub mod nzbfile;
pub mod options;
pub mod parparser;
pub mod parrenamer;
pub mod paths;
pub mod rarreader;
pub mod rarrenamer;
pub mod renameanalyzer;
pub mod rpcparams;
pub mod rpcroute;
pub mod scheduler;
pub mod statmeter;
pub mod text;
pub mod url;
pub mod urlcoord;
pub mod util;
pub mod webdownload;
pub mod webserver;
pub mod webutil;
pub mod ffi;
pub mod donorscore;
pub mod dupesearch_nzb;
pub mod releasename;
pub mod posting;
pub mod twin;
pub mod wildmask;

pub mod dupeidentity;

pub mod streampatchparts;
pub mod streamcompare;
pub mod deadpostings;
pub mod dupewatch;

pub mod dupepurge;

pub mod purgejournal;
