//! KERNEL ONLY: selective Rust diagnostics, never a C++/Rust migration gate.
//!
//! These call Rust modules directly. They exclude C++ callers, the daemon C ABI,
//! transport, queue ownership and copies unless a benchmark says otherwise.
//! Internal module work is included, such as rpcparams' libc integer parsing.
//! Fixture construction and fixture assertions always happen outside timing.
//! Encoding times fresh output allocation, growth and destruction. In-place
//! parsing/decoding uses iter_batched_ref: cloning, input allocation and input
//! destruction are excluded; mutation and observing the result are timed.
//!
//! Build separately with `cargo bench --locked --bench criterion_ports --no-run`.
//! Under the exclusive timing lock, run the prebuilt executable with `--test`
//! for a fixture smoke check, or `--bench` for Criterion measurements. A smoke
//! check supplies no timing evidence. Criterion estimates are unpaired Rust
//! kernel data and cannot qualify a runtime replacement.

use criterion::{criterion_group, criterion_main, BatchSize, BenchmarkId, Criterion, Throughput};
use nzbget_rs::{decode, escape, rpcparams};
use std::hint::black_box;

// The sizes describe requested payload bytes. IDs and throughput use actual
// input bytes, including framing/padding, rather than claiming exact sizes.
const SIZES: [(&str, usize); 3] = [("small", 32), ("normal", 4096), ("large", 65536)];

fn repeated(unit: &[u8], minimum_bytes: usize) -> Vec<u8> {
    unit.repeat(minimum_bytes.div_ceil(unit.len()))
}

fn rpc_request(payload_bytes: usize) -> Vec<u8> {
    let payload = repeated(br#"Show.Name/part01.rar \"quoted\" "#, payload_bytes);
    let mut request = br#"{"method":"append","params":[42,true,""#.to_vec();
    request.extend_from_slice(&payload);
    request.extend_from_slice(b"\"]}\0");
    request
}

fn parse_rpc(request: &mut [u8]) -> (Option<i32>, Option<bool>, Option<usize>, usize) {
    let mut pos = rpcparams::skip_to_params(request);
    let (step, integer) = rpcparams::next_int(&mut request[pos..], rpcparams::Kind::Json);
    pos += step;
    let (step, flag) = rpcparams::next_bool(&mut request[pos..], rpcparams::Kind::Json, true);
    pos += step;
    let (step, string) = rpcparams::next_str(&mut request[pos..], rpcparams::Kind::Json);
    let string = string.map(|offset| pos + offset);
    (integer, flag, string, pos + step)
}

fn rpc_params(c: &mut Criterion) {
    let mut group = c.benchmark_group("kernel/rpc_json_params_setup_excluded");
    for (size, bytes) in SIZES {
        let request = rpc_request(bytes);
        let mut checked = request.clone();
        let result = parse_rpc(&mut checked);
        assert_eq!(result.0, Some(42));
        assert_eq!(result.1, Some(true));
        let string = result.2.expect("the fixture has a string parameter");
        assert!(checked[string..].starts_with(b"Show.Name/part01.rar"));
        assert_eq!(&checked[result.3..], b"]}\0");
        group.throughput(Throughput::Bytes(request.len() as u64));
        group.bench_with_input(
            BenchmarkId::new(size, request.len()),
            &request,
            |b, input| {
                b.iter_batched_ref(
                    || input.clone(),
                    |buffer| {
                        black_box(parse_rpc(black_box(buffer)));
                        black_box(buffer.as_slice());
                    },
                    BatchSize::LargeInput,
                );
            },
        );
    }
    group.finish();
}

fn json_encode(c: &mut Criterion) {
    let mut group = c.benchmark_group("kernel/json_encode_allocation_included");
    for (size, bytes) in SIZES {
        // Valid UTF-8, plain runs, punctuation and controls. Repeat whole units
        // so the fixture never truncates a UTF-8 code point.
        let input = repeated(
            "Show.Name/part01.rar \"quoted\" \\ \n café ".as_bytes(),
            bytes,
        );
        let mut checked = Vec::new();
        escape::json_encode(&input, &mut checked);
        assert!(checked.starts_with(br#"Show.Name\/part01.rar \"quoted\""#));
        assert!(checked.windows(6).any(|bytes| bytes == br#"\u00e9"#));
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new(size, input.len()), &input, |b, input| {
            b.iter(|| {
                let mut output = Vec::new();
                escape::json_encode(black_box(input), &mut output);
                black_box(output); // Vec destruction is included by iter.
            });
        });
    }
    group.finish();
}

fn json_decode(c: &mut Criterion) {
    let mut group = c.benchmark_group("kernel/json_decode_in_place_setup_excluded");
    let unit = br#"Show.Name\/part01.rar \"quoted\" \n caf\u00e9 "#;
    let decoded_unit = "Show.Name/part01.rar \"quoted\" \n café ".as_bytes();
    for (size, bytes) in SIZES {
        let input = repeated(unit, bytes);
        let expected = decoded_unit.repeat(input.len() / unit.len());
        let mut checked = input.clone();
        let length = decode::json_decode(&mut checked);
        assert_eq!(&checked[..length], expected);
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new(size, input.len()), &input, |b, input| {
            b.iter_batched_ref(
                || input.clone(),
                |buffer| {
                    let length = decode::json_decode(black_box(buffer));
                    black_box(length);
                    black_box(&buffer[..length]);
                },
                BatchSize::LargeInput,
            );
        });
    }
    group.finish();
}

fn base64_decode(c: &mut Criterion) {
    let mut group = c.benchmark_group("kernel/base64_in_place_setup_excluded");
    for (size, bytes) in SIZES {
        // Complete unpadded quartets with CRLF separators exercise the usual
        // fast path and the whitespace-skipping path. The expected output is
        // independently specified rather than another call to the decoder.
        let unit = b"U2hvd05hbWUv\r\n";
        let input = repeated(unit, bytes);
        let expected = b"ShowName/".repeat(input.len() / unit.len());
        let mut checked = input.clone();
        // SAFETY: the buffer is readable/writable for its full input length;
        // input and output are exactly identical, as the API permits.
        let length = unsafe {
            decode::base64_in_place(checked.as_ptr(), checked.len(), checked.as_mut_ptr())
        };
        assert_eq!(&checked[..length], expected);
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new(size, input.len()), &input, |b, input| {
            b.iter_batched_ref(
                || input.clone(),
                |buffer| {
                    let buffer = black_box(buffer);
                    // SAFETY: fresh full-length buffer, identical pointers;
                    // decoding never writes beyond the input already read.
                    let length = unsafe {
                        decode::base64_in_place(buffer.as_ptr(), buffer.len(), buffer.as_mut_ptr())
                    };
                    black_box(length);
                    black_box(&buffer[..length]);
                },
                BatchSize::LargeInput,
            );
        });
    }
    group.finish();
}

criterion_group!(benches, rpc_params, json_encode, json_decode, base64_decode);
criterion_main!(benches);
