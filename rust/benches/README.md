# Benchmarks of the Rust ports

`ports.rs` times the Rust ports on inputs made in the file (no data files), and
prints the results as JSON in the
[Bencher Metric Format](https://bencher.dev/docs/reference/bencher-metric-format/).
[Bencher](https://bencher.dev) tracks them over time and compares every pull
request with the base branch in CI.

## Running them

```sh
cd rust
cargo bench --bench ports                  # all of them: JSON on stdout, progress on stderr
cargo bench --bench ports -- twin/         # the benchmarks whose name contains "twin/"
BENCH_QUICK=1 cargo bench --bench ports    # a fast smoke test (noisy numbers)
```

Each benchmark gets `latency` in nanoseconds per operation: `value` is the
median of 21 samples, `lower_value` the fastest, `upper_value` the 90th
percentile. Bencher compares `value`.

## Adding a benchmark

Every port adds the benchmarks of its hot function to `ports.rs`, named
`module/what is timed and how big`. Make the input in the file, `black_box` the
arguments and the result, and keep one call to well under a second. A port's
pull request also shows its C++ time, its Rust time and the percentage change
(see `PORTING.md`); the benchmark is what keeps the Rust time from slipping
afterwards.

## Continuous benchmarking in CI

Three workflows in `.github/workflows/` run the benchmarks with
[`bencher run`](https://bencher.dev/docs/how-to/github-actions/):

| workflow | when | what |
| --- | --- | --- |
| `bench_base.yml` | push to `dupe-article-fallback` | records the base branch's results and sets the thresholds |
| `bench_pr.yml` | a pull request from this repository into `dupe-article-fallback` | compares the branch with the base branch, comments the report on the pull request, and fails the check on an alert |
| `bench_pr_closed.yml` | a pull request is closed | archives the pull request's branch in Bencher |

The threshold is Bencher's `percentage` test on `latency`, upper boundary 0.10: a
benchmark more than 10% slower than the mean of the base branch's last 16 runs
is an alert. That is the 10% rule of `PORTING.md`.

The workflows do nothing until Bencher is set up:

1. Make a project on [bencher.dev](https://bencher.dev) (or run your own
   [Bencher server](https://bencher.dev/docs/tutorial/docker/)) and an API key for it.
2. In the repository's settings, under Secrets and variables, add:
   - the **secret** `BENCHER_API_KEY`: the API key;
   - the **variable** `BENCHER_PROJECT`: the project's slug or UUID;
   - optionally the variable `BENCHER_HOST`: the URL of a self-hosted server.
3. Run `bench base` once (Actions, "Run workflow") so the base branch has a
   baseline; after that every push to it adds to it.

Bencher's report check fails when there is an alert; it blocks a merge only if
branch protection requires it. Timings on shared GitHub runners vary by a few percent between runs, more for
benchmarks of a few hundred nanoseconds. An alert on such a benchmark is worth a
re-run before a fix. Pull requests from forks have no secrets and aren't benchmarked.

These benchmarks are of the Rust only. The C++ side of a port's comparison
(the pre-port code, built from the commit before it) needs the daemon's build,
so those tables are made with the port's differential harness and put in the
pull request by hand.
