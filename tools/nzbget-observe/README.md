<!-- vale Google.Headings = NO -->
# NZBGet Observe
<!-- vale Google.Headings = YES -->

An opt-in Rust watcher for investigating missing progress in NZBGet. It connects
job progress with Linux resource observations and preserves a small evidence
window when an active job stops advancing. It never changes the queue, starts
downloads, runs profilers, or restarts NZBGet.

## Build and run

Build separately from the daemon with Rust 1.99 or newer (the lockfile records the
tested dependency versions):

```bash
cargo build --release --locked --manifest-path tools/nzbget-observe/Cargo.toml
export NZBGET_OBSERVE_USER='your-read-only-user'
read -rs NZBGET_OBSERVE_PASSWORD
export NZBGET_OBSERVE_PASSWORD
tools/nzbget-observe/target/release/nzbget-observe \
  --url http://127.0.0.1:6789/jsonrpc --output observe-evidence \
  --interval 15 --stall-seconds 300 --samples 240
```

Use an existing restricted read-only NZBGet account. Passwords are read from the
environment, never from command-line arguments. HTTP is accepted only for literal
loopback addresses; remote endpoints require HTTPS with certificate validation.
Redirects and environment proxies are turned off. The endpoint must end in
`/jsonrpc`, without user information, query parameters, or fragments.

Run the watcher on the **daemon's Linux host**, in its relevant container/namespace
when appropriate. Add `--pid PID` for that daemon's process counters and
`--cgroup RELATIVE_DIRECTORY` for the daemon's cgroup under `/sys/fs/cgroup`.
Without these, pressure measurements describe the watcher's visible host; they do
not establish the resource conditions of a remote daemon. Missing or denied reads
are recorded as unknown. PID start time is included to distinguish PID reuse.

`--samples 1` takes one observation. Without `--samples` the watcher runs until
interrupted. SIGTERM/SIGINT can stop it; no daemon action is performed. Each cycle
makes sequential `status` and `listgroups(0)` requests, each with a three-second
timeout and a one-MiB response cap. The interval must be at least ten seconds.
More than 128 queue entries makes the observation unknown rather than silently
dropping jobs. The two replies are not an atomic daemon snapshot.
Finite runs exit with a failure status if their final RPC observation is unknown.

## What it reports

The watcher writes JSON lines to stdout: sanitized samples, newly detected
symptoms, observation failures, and recovery from observation failures. Exported
job fields are numeric ID, a recognized stage, progress counters, and activity.
Release names, paths, passwords, article IDs, log text, and raw RPC replies are
never written. Keep stdout retention bounded if collecting it with another tool.

The default trigger is **300 seconds of unchanged observed progress for an
actively running job**. Download progress uses remaining bytes and successful or
failed article counts; post-processing also uses stage progress. Queued, paused,
finished and unrecognized stages do not trigger. Global download pause/quota and
post-processing pause suppress the corresponding jobs. Stage changes, any counter
change, detected daemon restart, and observation failures reset the window.
Restart detection uses uptime regression or an uptime increase more than ten
seconds shorter than the monotonic observation interval. Small clock differences
are tolerated; this is not a process-identity guarantee.
Duplicate alerts are suppressed until progress or state changes.

This is a symptom, not proof of a hang. A long-running repair or unpack step can
make useful work without updating these counters. A job that never becomes active
is outside this first detector's scope. Read the suggested next check before
acting.

## Bounded evidence

Each run creates a private subdirectory inside `--output`. A 20-sample memory ring
provides the preceding context. An alert captures that context, RPC collection
wall time and local Linux observations. At most eight evidence files are retained
per run, each limited to one MiB; new alerts replace the oldest slot atomically.
A failed write stops the watcher and can retain one additional partial file.
Completed
run directories are retained for the operator to remove or archive. Alerts do not
launch an automatic profiler or execute shell commands.

Linux observations include CPU/memory/I/O PSI `some avg10`, optional daemon CPU
ticks/RSS and cumulative read/write counters, and optional cgroup CPU throttling,
memory events, and PSI. These are raw observations. CPU ticks require the host's
clock-tick rate to interpret, RSS pages require its page size, cumulative counters
require deltas, and PSI expresses contention rather than its cause.

## Drill down with a question

| Symptom | Next bounded investigation | Decision evidence |
| --- | --- | --- |
| Download progress unchanged | Compare provider waiting, decoder CPU and writer/cache pressure | Article completion latency, CPU stacks, write progress |
| PAR progress unchanged | Separate hashing/scanning, storage waits, and recovery arithmetic | CPU plus off-CPU profiles, bytes scanned, actual hash backend, and repair geometry |
| Unpack/move progress unchanged | Inspect child-process progress and input/output storage | Child CPU, I/O deltas and device latency |
| High CPU PSI | Examine scheduling contention and cgroup throttling | Run-queue latency and throttling deltas |
| High I/O PSI | Find which filesystem/device/process is waiting | Block-I/O latency and per-process I/O deltas |
| High memory PSI | Distinguish reclaim from allocation/copy churn | Memory events, reclaim activity, and an offline allocation profile |

Use release symbols for CPU and off-CPU profiles. Capture short windows around an
actual symptom, check instrumentation overhead against an uninstrumented control,
and preserve both valid and rejected evidence. Do not use diagnostic timings as
Rust/C++ speedup qualification. For a replacement, benchmark the complete caller,
including allocations, copies, and FFI. Compare current and equivalently optimized
C++ across small, typical, and large inputs. Verify correctness and report uncertainty.

## Background

- [Performance investigation methodology](https://www.brendangregg.com/methodology.html)
- [Linux pressure stall information](https://docs.kernel.org/accounting/psi.html)
- [CPU versus off-CPU investigation](https://www.brendangregg.com/offcpuanalysis.html)
- [Prometheus processing-pipeline instrumentation](https://prometheus.io/docs/practices/instrumentation/)
- [Rust release profiling](https://nnethercote.github.io/perf-book/profiling.html)
- [Benchmark variance](https://github.com/google/benchmark/blob/main/docs/reducing_variance.md)

## Shareable description

NZBGet Observe is an opt-in Rust watcher that notices when an active job stops
showing progress and saves a bounded, sanitized evidence window. It respects
pauses and stage changes, keeps Linux resource measurements separate from job
progress, and suggests where to investigate next. The goal is to turn “NZBGet is
slow” into a specific, testable question about provider waiting, decoding,
storage, PAR work, or unpacking. It makes no automatic changes and does not claim
that a stalled progress counter proves a hang.
