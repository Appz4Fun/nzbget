//! Benchmarks of the Rust ports, for continuous benchmarking with Bencher
//! (https://bencher.dev). `cargo bench --bench ports` prints one JSON object
//! on stdout in the Bencher Metric Format:
//!
//!   { "<benchmark>": { "latency": { "value": ns, "lower_value": ns, "upper_value": ns } } }
//!
//! `value` is the median time of one operation in nanoseconds, `lower_value`
//! the fastest and `upper_value` the 90th percentile of the samples. Progress
//! goes to stderr. Inputs are made in here (no files), so the numbers depend
//! on the port code and the machine only.
//!
//! Arguments after `--`: a substring filters the benchmarks by name;
//! `BENCH_QUICK=1` takes fewer, shorter samples (a smoke test).

use std::collections::BTreeMap;
use std::hint::black_box;
use std::time::{Duration, Instant};

use md5::{Digest, Md5};
use nzbget_rs::{
    binrpc, bytes, crc, decode, deobfuscation, escape, json, nzbfile, paths, text, twin, urlcoord, util, webutil,
};

struct Sample {
    median: f64,
    fastest: f64,
    p90: f64,
}

/// Times `f` (one operation per call): the call count is raised until a
/// sample takes at least `target`, then `samples` samples are taken.
fn measure(mut f: impl FnMut(), quick: bool) -> Sample {
    let (target, samples) = if quick { (Duration::from_millis(1), 3) } else { (Duration::from_millis(20), 21) };
    let mut calls: u64 = 1;
    loop {
        let start = Instant::now();
        for _ in 0..calls {
            f();
        }
        if start.elapsed() >= target || calls >= 1 << 30 {
            break;
        }
        calls *= 2;
    }
    let mut times: Vec<f64> = (0..samples)
        .map(|_| {
            let start = Instant::now();
            for _ in 0..calls {
                f();
            }
            start.elapsed().as_secs_f64() * 1e9 / calls as f64
        })
        .collect();
    times.sort_by(f64::total_cmp);
    Sample { median: times[times.len() / 2], fastest: times[0], p90: times[(times.len() * 9 / 10).min(times.len() - 1)] }
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
}

// ---- inputs ----

fn c_locale() -> (Vec<u16>, Vec<i32>) {
    let classes = (0..256u32)
        .map(|b| {
            let b = b as u8;
            (matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c) as u16) | ((b.is_ascii_digit() as u16) << 1)
        })
        .collect();
    let lower = (-128..256).map(|c: i32| if (65..=90).contains(&c) { c + 32 } else { c }).collect();
    (classes, lower)
}

fn par2_packet(kind: &[u8; 16], body: &[u8]) -> Vec<u8> {
    let mut data = vec![7u8; 16];
    data.extend_from_slice(kind);
    data.extend_from_slice(body);
    let mut out = b"PAR2\0PKT".to_vec();
    out.extend_from_slice(&((data.len() + 32) as u64).to_le_bytes());
    out.extend_from_slice(&Md5::digest(&data));
    out.extend_from_slice(&data);
    out
}

/// A par2 set of `files` files: Main, FileDesc and IFSC packets, then
/// `recovery` recovery packets of `slice` bytes.
fn par2_set(files: u8, recovery: usize, slice: usize) -> Vec<u8> {
    let mut rng = Rng(0x9E3779B97F4A7C15);
    let mut main = 65536u64.to_le_bytes().to_vec();
    main.extend_from_slice(&(files as u32).to_le_bytes());
    for id in 1..=files {
        main.extend_from_slice(&[id; 16]);
    }
    let mut set = par2_packet(b"PAR 2.0\0Main\0\0\0\0", &main);
    for id in 1..=files {
        let mut body = vec![id; 16];
        body.extend((0..32).map(|_| rng.next() as u8));
        body.extend_from_slice(&(rng.next() >> 24).to_le_bytes());
        body.extend_from_slice(format!("Release.Name.2026.1080p.WEB.h264-GROUP.part{id:02}.rar").as_bytes());
        body.resize(body.len().div_ceil(4) * 4, 0);
        set.extend(par2_packet(b"PAR 2.0\0FileDesc", &body));
        let mut ifsc = vec![id; 16];
        ifsc.extend((0..20 * 150).map(|_| rng.next() as u8));
        set.extend(par2_packet(b"PAR 2.0\0IFSC\0\0\0\0", &ifsc));
    }
    for _ in 0..recovery {
        let mut body = vec![0u8; 4];
        body.extend((0..slice).map(|_| rng.next() as u8));
        set.extend(par2_packet(b"PAR 2.0\0RecvSlic", &body));
    }
    set
}

fn json_document(items: usize) -> Vec<u8> {
    let mut s = String::from("[");
    for i in 0..items {
        if i > 0 {
            s.push(',');
        }
        s.push_str(&format!(
            "{{\"ID\":{i},\"Name\":\"Release.Name.{i}.1080p.WEB\",\"Size\":{},\"Paused\":false,\"Ratio\":0.{i},\"Tags\":[\"a\",\"b\",\"c\"],\"Note\":\"cafe \\\"quoted\\\"\"}}",
            i * 1_000_003
        ));
    }
    s.push(']');
    s.into_bytes()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).filter(|a| !a.starts_with("--")).collect();
    let filter = args.first().cloned().unwrap_or_default();
    let quick = std::env::var_os("BENCH_QUICK").is_some();
    let mut results: BTreeMap<String, Sample> = BTreeMap::new();
    let mut bench = |name: &str, f: &mut dyn FnMut()| {
        if !name.contains(&filter) {
            return;
        }
        let sample = measure(f, quick);
        eprintln!("{name}: {:.0} ns (fastest {:.0}, p90 {:.0})", sample.median, sample.fastest, sample.p90);
        results.insert(name.to_string(), sample);
    };

    let mut rng = Rng(0x2545F4914F6CDD1D);
    let (classes, lower_table) = c_locale();
    let ct = nzbfile::Ctype { classes: &classes, space: 1, digit: 2, lower: &lower_table, char_signed: true };

    // text and search helpers
    let haystack: Vec<u8> = (0..1 << 20).map(|_| b'a' + (rng.next() % 20) as u8).collect();
    bench("bytes/find a miss in 1 MiB", &mut || {
        black_box(bytes::find(black_box(&haystack), b"zyxwvuts"));
    });
    let escaped: Vec<u8> = (0..65536u32).map(|i| [b'a', b'"', b'\\', b'\n', 0xc3, 0xa9, b'<', b'&'][(i % 8) as usize]).collect();
    bench("escape/json_encode 64 KiB", &mut || {
        let mut out = Vec::with_capacity(escaped.len() * 2);
        escape::json_encode(black_box(&escaped), &mut out);
        black_box(out);
    });
    bench("escape/xml_encode 64 KiB", &mut || {
        let mut out = Vec::with_capacity(escaped.len() * 2);
        escape::xml_encode(black_box(&escaped), &mut out);
        black_box(out);
    });
    let encoded: Vec<u8> = b"Show%20Name%2Fpart%5B1%5D+%C3%A9%26".iter().copied().cycle().take(8192).collect();
    bench("text/url_decode 8 KiB", &mut || {
        let mut buf = encoded.clone();
        black_box(text::url_decode(&mut buf));
    });
    bench("text/url_encode 8 KiB", &mut || {
        let mut out = Vec::new();
        text::url_encode(black_box(&encoded), &mut out);
        black_box(out);
    });
    let markup: Vec<u8> = b"<p>Some <b>bold</b> text &amp; &lt;more&gt; &#233;</p>\n".iter().copied().cycle().take(16384).collect();
    bench("text/xml_strip_tags 16 KiB", &mut || {
        let mut buf = markup.clone();
        text::xml_strip_tags(&mut buf);
        black_box(buf);
    });
    let xml = [b"<rss><channel>".as_slice(), &vec![b' '; 256 * 1024], b"<title>found</title></channel></rss>"].concat();
    bench("webutil/xml_find_tag in 256 KiB", &mut || {
        black_box(webutil::xml_find_tag(black_box(&xml), b"title"));
    });
    let names: Vec<&[u8]> = vec![
        b"Show.Name.S01E02.1080p.WEB.h264-GROUP.mkv", b"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", b"movie (2026) [1080p].mkv",
        b"abc.xyz.1e5a1fd4ba3d4c3a98d8a7d1d4d3a2b1.mkv", b"Some.Release.Name-GROUP", b"x", b"1234567890abcdef1234567890abcdef.rar",
    ];
    bench("deobfuscation/deobfuscate 7 names", &mut || {
        for n in &names {
            black_box(deobfuscation::deobfuscate(black_box(n)));
        }
    });
    bench("deobfuscation/is_excessively_obfuscated 7 names", &mut || {
        for n in &names {
            black_box(deobfuscation::is_excessively_obfuscated(black_box(n)));
        }
    });
    bench("paths/make_valid_filename 7 names", &mut || {
        for n in &names {
            black_box(paths::make_valid_filename(black_box(n), false));
        }
    });
    bench("util/format_size 6 sizes", &mut || {
        for s in [0i64, 999, 123_456, 98_765_432, 5_000_000_000, 123_456_789_012] {
            black_box(util::format_size(black_box(s)));
        }
    });
    bench("crc/combine x1000", &mut || {
        let mut c = 0u32;
        for i in 0..1000u32 {
            c = crc::combine(black_box(c), black_box(i.wrapping_mul(2654435761)), black_box(716800));
        }
        black_box(c);
    });

    // JSON
    let doc = json_document(2000);
    let limits = json::Limits { string: 0x7ffffffe, array: 0x7ffffffe, object: 0x7ffffffe };
    bench("json/parse 2,000 objects", &mut || {
        black_box(json::parse(black_box(&doc), limits));
    });
    // JSON text with escapes: a \u escape (written in two pieces), quotes, newlines, backslashes
    let unit = [&b"caf\\"[..], b"u00e9 ", br#"\"quoted\" line\nbreak \\ "#].concat();
    let escaped_json: Vec<u8> = unit.iter().copied().cycle().take(65536).collect();
    bench("decode/json_decode 64 KiB", &mut || {
        let mut buf = escaped_json.clone();
        black_box(decode::json_decode(&mut buf));
    });

    // NzbFile
    let parts: Vec<i32> = (1..=3709).collect();
    let sizes: Vec<i64> = (0..3709).map(|i| if i == 3708 { 300_000 } else { 716_800 }).collect();
    bench("nzbfile/file_totals 3,709 segments", &mut || {
        black_box(nzbfile::file_totals(b"[1/30] - \"a.part01.rar\" yEnc (1/3709)", black_box(&parts), black_box(&sizes), &ct));
    });
    let file_names: Vec<String> = (0..5000).map(|i| format!("Release.Name.2026.1080p.WEB.h264-GRP.part{i:05}.rar")).collect();
    let subjects: Vec<String> = file_names.iter().map(|n| format!("[1/5000] - \"{n}\" yEnc (1/2)")).collect();
    let files: Vec<(&[u8], &[u8])> = file_names.iter().zip(&subjects).map(|(n, s)| (n.as_bytes(), s.as_bytes())).collect();
    bench("nzbfile/has_duplicate_filenames 5,000 files", &mut || {
        black_box(nzbfile::has_duplicate_filenames(black_box(&files)));
    });

    // twin par2 lists
    let index = par2_set(30, 0, 0);
    let volume = par2_set(30, 2, 768 * 1024);
    bench("twin/par2_set 30-file index (96 KiB)", &mut || {
        black_box(twin::par2_set(black_box(&index)));
    });
    bench("twin/par2_set 30-file volume (1.6 MiB)", &mut || {
        black_box(twin::par2_set(black_box(&volume)));
    });
    bench("twin/block_size index", &mut || {
        black_box(twin::block_size(black_box(&index)));
    });
    let sigs = twin::par2_set(&index).0;
    bench("twin/fingerprint 30 files", &mut || {
        black_box(twin::fingerprint(black_box(&sigs)));
    });
    bench("twin/volume_blocks 4 names", &mut || {
        for n in ["x.vol03+04.par2", "X.VOL00+128.PAR2", "x.par2", "movie.vol-08.par2"] {
            black_box(twin::volume_blocks(black_box(n)));
        }
    });

    // BinRpc's batched response encoders, with caller scratch and an owned buffer.
    let log_text = b"A log line of typical length, with a few words in it.";
    let logs: Vec<binrpc::LogEntry> = (0..1000u32).map(|id| binrpc::LogEntry {
        id, kind: 2, time: 1_700_000_000, texts: [binrpc::Text::new(log_text)],
    }).collect();
    let mut log_scratch = [std::mem::MaybeUninit::<u8>::uninit(); 16 * 1024];
    bench("binrpc/encode_log_into 10 log entries (caller scratch)", &mut || {
        // The entries and text outlive the call; scratch is separate writable
        // storage and includes room for the response's final NUL.
        let response = unsafe { nzbget_rs::ffi::nzbget_rs_binrpc_encode_log_into(
            black_box(logs.as_ptr()), 10, black_box(log_scratch.as_mut_ptr()).cast(), log_scratch.len()) };
        assert_eq!(response.owned_capacity, 0);
        black_box(response);
        black_box(&log_scratch);
    });
    bench("binrpc/encode_log 1,000 log entries (owned allocation)", &mut || {
        // The large-response fallback uses the same owned response builder.
        let response = unsafe { nzbget_rs::ffi::nzbget_rs_binrpc_encode_log(black_box(logs.as_ptr()), logs.len()) };
        black_box(&response);
        unsafe { nzbget_rs::ffi::nzbget_rs_free(response); }
    });
    bench("urlcoord/dnzb_header 3 lines", &mut || {
        for line in [
            &b"X-DNZB-Category: TV > HD\r\n"[..],
            b"X-DNZB-Name: Some.Show.S01E01.1080p.WEB.h264-GROUP\r\n",
            b"Content-Type: application/x-nzb\r\n",
        ] {
            black_box(urlcoord::dnzb_header(black_box(line)));
        }
    });

    bench("dupeidentity/bare-media identity", &mut || {
        black_box(nzbget_rs::dupeidentity::inner_entry(black_box(b"decoded-video"),
            black_box(b"Show.S01E01.1080p.WEB.H264-GRP.mkv"), 5_000_000_000, 1_000_000_000));
    });

    // Bencher Metric Format
    let mut out = String::from("{\n");
    let last = results.len().saturating_sub(1);
    for (k, (name, s)) in results.iter().enumerate() {
        out.push_str(&format!(
            "  {:?}: {{\"latency\": {{\"value\": {:.1}, \"lower_value\": {:.1}, \"upper_value\": {:.1}}}}}{}\n",
            name,
            s.median,
            s.fastest,
            s.p90,
            if k == last { "" } else { "," }
        ));
    }
    out.push_str("}\n");
    print!("{out}");
}
