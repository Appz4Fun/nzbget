#!/usr/bin/env python3
"""Run cooperative offline build/timing commands under the worker's locks.

Execution requires Linux for subreaper-backed descendant supervision. Timing
accepts native prebuilt executables; it never invokes a shell or build tool.
This resource coordinator is not a sandbox for untrusted programs.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

# Preserve the invocation's implementation identity. Later source changes must
# not relabel already-loaded code as though it came from the new file.
RUNNER_ORIGINAL_PATH = Path(__file__)
RUNNER_PATH = RUNNER_ORIGINAL_PATH.resolve()
INVOCATION_RUNNER_SHA256 = hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest()

BUILD_TOOLS = {"cargo", "rustc", "rustup", "make", "gmake", "ninja", "cmake", "cc", "gcc", "g++",
               "c++", "clang", "clang++", "ccache", "sccache", "meson", "bazel", "just", "task",
               "npm", "npx", "yarn", "pnpm", "pip", "pip3", "uv"}
SHELLS = {"sh", "bash", "dash", "zsh", "fish", "ksh", "csh", "tcsh"}
INTERPRETERS = {"python", "python3", "pypy", "pypy3", "perl", "ruby", "node", "env", "busybox"}
POLL_SECONDS = 0.02


def bounded_number(maximum):
    def parse(value):
        number = float(value)
        if not math.isfinite(number) or not 0 < number <= maximum:
            raise argparse.ArgumentTypeError(f"must be finite, positive and at most {maximum}")
        return number
    return parse


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("build", "time"), required=True)
    parser.add_argument("--timeout-seconds", type=bounded_number(86400), default=300.0)
    parser.add_argument("--lock-timeout-seconds", type=bounded_number(3600), default=120.0)
    parser.add_argument("--shutdown-grace-seconds", type=bounded_number(30), default=2.0)
    parser.add_argument("--lock-dir", type=Path, default=Path("/tmp"), help="alternate private directory for tests")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3), default=None, help="build jobs, default 3")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--testbed", help="stable, nonsecret hardware identifier; required with metadata")
    parser.add_argument("--fixture", action="append", type=Path, default=[])
    parser.add_argument("--toolchain-binary", action="append", type=Path, default=[], help="hash a compiler/tool binary")
    parser.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND [ARGS]")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command.pop(0)
    if not args.command:
        parser.error("a command after -- is required")
    if args.mode == "time" and args.jobs is not None:
        parser.error("jobs applies only to build mode")
    if args.metadata and not args.testbed:
        parser.error("metadata requires a stable testbed identifier")
    if args.testbed and not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", args.testbed):
        parser.error("invalid testbed identifier")
    args.jobs = args.jobs or 3
    return args


def tool_name(name):
    # Include versioned and cross-compiler names, not just the common aliases.
    name = Path(name).name
    return re.sub(r"[-.]?\d+(?:\.\d+)*$", "", name)


def timing_forbidden(name):
    return (name in BUILD_TOOLS | INTERPRETERS | SHELLS or
            bool(re.search(r"(?:^|-)(gcc|g\+\+|clang|clang\+\+|rustc)$", name)))


def prepare_command(args):
    name = tool_name(args.command[0])
    if name in SHELLS:
        raise ValueError("shell/eval commands are not accepted; pass an argument vector")
    if args.mode == "time" and timing_forbidden(name):
        raise ValueError("timing requires a prebuilt native program, not an interpreter or build tool")
    command = list(args.command)
    if args.mode == "build":
        # Only Cargo's run/test/bench program arguments are exempt. CMake's
        # trailing -- arguments go to the native builder and still need a cap.
        cargo_prefix = 2 if len(command) > 1 and command[1].startswith("+") else 1
        program_args = (name == "cargo" and len(command) > cargo_prefix and
                        command[cargo_prefix] in ("run", "test", "bench"))
        end = command.index("--") if program_args and "--" in command else len(command)
        for index, value in enumerate(command[1:end], 1):
            jobs = None
            if value in ("-j", "--jobs", "--parallel"):
                if index + 1 >= end or not command[index + 1].isdigit():
                    raise ValueError("an explicit jobs flag needs a bounded integer")
                jobs = command[index + 1]
            elif re.fullmatch(r"-j\d+", value):
                jobs = value[2:]
            elif value.startswith(("--jobs=", "--parallel=")):
                jobs = value.split("=", 1)[1]
            if jobs is not None and (not jobs.isdigit() or not 1 <= int(jobs) <= args.jobs):
                raise ValueError("build jobs must be at most the configured cap (maximum 3)")
        if name == "ninja":
            command[1:1] = [f"-j{args.jobs}"]
        elif name == "cmake" and "--build" in command:
            native_start = command.index("--") if "--" in command else len(command)
            command[native_start:native_start] = ["--parallel", str(args.jobs)]
    executable = shutil.which(command[0])
    if not executable:
        raise ValueError("command executable was not found")
    invocation = Path(executable).absolute()
    executable = invocation.resolve()
    resolved_name = tool_name(executable.name)
    if resolved_name in SHELLS:
        raise ValueError("shell/eval commands are not accepted; pass an argument vector")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("command must be an executable regular file")
    if args.mode == "time":
        if timing_forbidden(resolved_name):
            raise ValueError("timing requires a prebuilt native measurement program")
        with executable.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError("timing requires a prebuilt native ELF executable")
    # argv[0] selects cargo/rustc inside the rustup multicall binary. Hash the
    # resolved binary, but preserve the original executable alias for exec.
    command[0] = str(invocation)
    return command, executable


def digest_file(path):
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("captured artifacts must be regular files")
        return hashlib.file_digest(stream, "sha256").hexdigest()


def argv_digest(command):
    return hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest()


def metadata_destination_safe(args, command):
    if args.metadata is None:
        return
    # os.replace replaces the final directory entry, not a symlink's target.
    # Preserve original ancestor entries before resolving any leaf: link/../x
    # still depends on link, even if resolving x would hide that dependency.
    def original_absolute(path):
        return path if path.is_absolute() else Path.cwd() / path

    def entry(path):
        path = original_absolute(path)
        return path.parent.resolve() / path.name

    output = original_absolute(args.metadata)
    output_entry, output_target = entry(output), output.resolve()
    try:
        output_stat = output.stat()
    except FileNotFoundError:
        output_stat = None
    inputs = [Path(command[0]), RUNNER_ORIGINAL_PATH, *args.fixture, *args.toolchain_binary]
    inputs += [directory / name for directory in (args.lock_dir, Path("/tmp"))
               for name in ("i7-heavy.lock", "nzbget-rust-benchmark.lock")]
    for path in inputs:
        original = original_absolute(path)
        for protected in (original, *original.parents):
            if output_entry == entry(protected) or output_target == protected.resolve():
                raise ValueError("metadata destination collides with a protected input or lock")
            if output_stat is not None:
                try:
                    protected_stat = protected.stat()
                except FileNotFoundError:
                    continue
                if (output_stat.st_dev, output_stat.st_ino) == (protected_stat.st_dev, protected_stat.st_ino):
                    raise ValueError("metadata destination collides with a protected input or lock")


def checkout_identity():
    git = shutil.which("git")
    if not git:
        return None
    revision = subprocess.run([git, "rev-parse", "HEAD"], capture_output=True, text=True,
                              env=safe_environment("time", 3), timeout=5)
    if revision.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\n?", revision.stdout):
        return revision.stdout.strip()
    return None


def capture_artifacts(args, command):
    paths = [("runner", "implementation", RUNNER_PATH),
             ("executable", "executable", Path(command[0]))]
    paths += [(f"fixture-{index}", "fixture", path) for index, path in enumerate(args.fixture)]
    paths += [(f"tool-{index}", "toolchain", path) for index, path in enumerate(args.toolchain_binary)]
    records = []
    for identifier, kind, path in paths:
        try:
            digest = digest_file(path)
        except (OSError, ValueError):
            digest = None
        records.append({"id": identifier, "kind": kind, "sha256": digest})
    return records


def capture_stability(before, after):
    first = {record["id"]: record["sha256"] for record in before}
    last = {record["id"]: record["sha256"] for record in after}
    changed = {identifier for identifier in first.keys() | last.keys()
               if first.get(identifier) is None or last.get(identifier) is None or
               first.get(identifier) != last.get(identifier)}
    reasons = set()
    if any(record["sha256"] is None for record in before + after):
        reasons.add("artifact_unavailable")
    if first.get("runner") != INVOCATION_RUNNER_SHA256 or last.get("runner") != INVOCATION_RUNNER_SHA256:
        changed.add("runner")
        reasons.add("runner_source_changed")
    if changed - {"runner"}:
        reasons.add("artifact_changed")
    return {"status": "changed" if changed else "stable", "changed_ids": sorted(changed),
            "reason_codes": sorted(reasons)}


def captured_fields(command, executable, before, after):
    first = {record["id"]: record["sha256"] for record in before}
    return {"capture_version": 1, "captures": {"before": before, "after": after},
            "stability": capture_stability(before, after),
            "command": {"name": executable.name, "sha256": first.get("executable"),
                        "argv_sha256": argv_digest(command)},
            "fixtures": [{"id": record["id"], "sha256": record["sha256"]} for record in before if record["kind"] == "fixture"],
            "toolchain_binaries": [{"id": record["id"], "sha256": record["sha256"]} for record in before if record["kind"] == "toolchain"]}


def mark_drift(result):
    result.update(exit_code=76, outcome="provenance_drift", qualification="HOLD")
    return result


def send_result(fd, result):
    data = json.dumps(result).encode()
    while data:
        data = data[os.write(fd, data):]


def safe_environment(mode, jobs):
    # No inherited token, credential, provider, proxy or arbitrary build flags.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
    if mode == "build":
        # Toolchain locations, not credential-bearing configuration values.
        # Resolve rustup defaults before HOME is isolated. Cargo's cache/config
        # remains accessible; this is for trusted offline drivers, not a sandbox.
        home = Path.home()
        for key, default in (("RUSTUP_HOME", home / ".rustup"), ("CARGO_HOME", home / ".cargo")):
            env[key] = os.environ.get(key, str(default))
        env.update(CARGO_BUILD_JOBS=str(jobs), CMAKE_BUILD_PARALLEL_LEVEL=str(jobs),
                   MAKEFLAGS=f"-j{jobs}", RUST_TEST_THREADS=str(jobs))
    return env


def acquire_locks(args, interrupted):
    paths = [("i7-heavy.lock", fcntl.LOCK_EX), ("nzbget-rust-benchmark.lock", fcntl.LOCK_SH)] if args.mode == "build" else [("nzbget-rust-benchmark.lock", fcntl.LOCK_EX)]
    held = []
    deadline = time.monotonic() + args.lock_timeout_seconds
    try:
        for name, kind in paths:
            fd = os.open(args.lock_dir / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            held.append(fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("lock must be a regular file")
            while True:
                if interrupted[0]:
                    raise InterruptedError
                try:
                    fcntl.flock(fd, kind | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("lock acquisition timed out")
                    time.sleep(POLL_SECONDS)
        return held
    except BaseException:
        for fd in held:
            os.close(fd)
        raise


def descendants():
    """All live descendants, including orphans adopted by the Linux subreaper."""
    pending, found = [os.getpid()], set()
    while pending:
        pid = pending.pop()
        try:
            # Include every thread: a multithreaded driver may fork elsewhere.
            tasks = Path(f"/proc/{pid}/task").iterdir()
            children = []
            for task in tasks:
                try:
                    children.extend(int(value) for value in (task / "children").read_text().split())
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            continue
        for child in children:
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def stop_children(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def emergency_reap():
    """Fail closed: never unlock after a supervisor failure with live children."""
    while True:
        try:
            pids = descendants()
            stop_children(pids, signal.SIGKILL)
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == 0:
                    break
            if not descendants():
                return
        except OSError:
            # Losing /proc visibility must not become an early lock release.
            pass
        time.sleep(POLL_SECONDS)


def supervise(args, command, env, locks, parent_pipe, result_pipe):
    """Custodian survives CLI death; lock release follows descendant reaping."""
    os.setsid()
    interrupted = [0]
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda number, frame: interrupted.__setitem__(0, number))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError("cannot enable Linux descendant supervision")
    original_argv = argv_digest(command)
    try:
        command, executable = prepare_command(args)
    except (OSError, ValueError):
        send_result(result_pipe, mark_drift({"command_started": False, "duration_ns": 0,
            "captures": {"before": [], "after": []}, "stability": {"status": "changed",
            "changed_ids": ["argv"], "reason_codes": ["command_revalidation_failed"]}}))
        return
    metadata_destination_safe(args, command)
    checkout_before = checkout_identity()
    before = capture_artifacts(args, command)
    fields = captured_fields(command, executable, before, before)
    if argv_digest(command) != original_argv:
        fields["stability"]["status"] = "changed"
        fields["stability"]["changed_ids"].append("argv")
        fields["stability"]["reason_codes"].append("argv_changed")
    if fields["stability"]["status"] != "stable":
        # Even a prevented launch keeps independently observed before/after
        # records; never reconstruct the second observation from the first.
        fields["captures"]["after"] = capture_artifacts(args, command)
        observed = capture_stability(before, fields["captures"]["after"])
        fields["stability"]["changed_ids"] = sorted(set(fields["stability"]["changed_ids"] + observed["changed_ids"]))
        fields["stability"]["reason_codes"] = sorted(set(fields["stability"]["reason_codes"] + observed["reason_codes"]))
        fields.update(command_started=False, duration_ns=0, checkout_sha=checkout_before,
                      checkout_sha_before=checkout_before, checkout_sha_after=checkout_identity())
        send_result(result_pipe, mark_drift(fields))
        return
    start = time.monotonic()
    child = subprocess.Popen(command, env=env, start_new_session=True, pass_fds=tuple(locks))
    root_status = None
    stopping_at = None
    outcome = "completed"
    exit_code = 0
    while True:
        # waitpid reaps both the command and adopted grandchildren. Popen.wait
        # alone would let an orphan continue after the root process exited.
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            if pid == child.pid:
                root_status = os.waitstatus_to_exitcode(status)
                child.returncode = root_status
        pids = descendants()
        if root_status is not None and not pids:
            break
        if stopping_at is None:
            parent_ready = select.select([parent_pipe], [], [], 0)[0]
            parent_lost = bool(parent_ready and not os.read(parent_pipe, 1))
            if interrupted[0] or parent_lost or time.monotonic() - start >= args.timeout_seconds:
                stopping_at = time.monotonic()
                outcome = "interrupted" if interrupted[0] or parent_lost else "timeout"
                exit_code = 128 + (interrupted[0] or signal.SIGTERM) if outcome == "interrupted" else 124
        if stopping_at is not None:
            sig = signal.SIGKILL if time.monotonic() - stopping_at >= args.shutdown_grace_seconds else signal.SIGTERM
            stop_children(pids, sig)
        time.sleep(POLL_SECONDS)
    if stopping_at is None:
        exit_code = root_status if root_status >= 0 else 128 - root_status
    result = {"exit_code": exit_code, "outcome": outcome, "command_started": True,
              "child_exit_code": root_status, "duration_ns": int((time.monotonic() - start) * 1e9)}
    # The same identities are captured while the custodian still owns the locks,
    # after every descendant has exited and been reaped.
    result.update(captured_fields(command, executable, before, capture_artifacts(args, command)))
    checkout_after = checkout_identity()
    result.update(checkout_sha=checkout_before, checkout_sha_before=checkout_before, checkout_sha_after=checkout_after)
    if checkout_before != checkout_after:
        result["stability"]["status"] = "changed"
        result["stability"]["changed_ids"].append("checkout")
        result["stability"]["reason_codes"].append("checkout_changed")
    if result["stability"]["status"] != "stable":
        mark_drift(result)
    send_result(result_pipe, result)
    # Inherited lock fds close only after all descendants have been reaped.


def execute(args, command, env, locks, interrupted):
    parent_read, parent_write = os.pipe()
    result_read, result_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        for fd in (*locks, parent_read, parent_write, result_read, result_write):
            os.close(fd)
        raise
    if pid == 0:
        os.close(parent_write)
        os.close(result_read)
        try:
            supervise(args, command, env, locks, parent_read, result_write)
        except BaseException:
            emergency_reap()
            os.write(result_write, b'{"exit_code":2,"outcome":"runner_error","duration_ns":0,"command_started":null}')
        finally:
            # The CLI may have died via SIGKILL and cannot run its TemporaryDirectory
            # cleanup. The surviving custodian owns that cleanup after reaping.
            shutil.rmtree(env["HOME"], ignore_errors=True)
            os._exit(0)  # closes lock fds without unwinding inherited contexts
    os.close(parent_read)
    os.close(result_write)
    for fd in locks:
        os.close(fd)
    try:
        received = []
        while True:
            if interrupted[0] and parent_write is not None:
                os.close(parent_write)
                parent_write = None
            if select.select([result_read], [], [], 0)[0]:
                received.append(os.read(result_read, 65536))
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done:
                break
            time.sleep(POLL_SECONDS)
        while True:
            chunk = os.read(result_read, 65536)
            if not chunk:
                break
            received.append(chunk)
        raw = b"".join(received)
        if not raw:
            raise ValueError("lock supervisor failed without a result")
        result = json.loads(raw)
        if interrupted[0]:
            result.update(exit_code=128 + interrupted[0], outcome="interrupted")
        return result
    finally:
        if parent_write is not None:
            os.close(parent_write)
        os.close(result_read)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def provenance(args, command, executable):
    proof = {"schema_version": 1, "capture_version": 1, "mode": args.mode, "testbed": args.testbed,
             "lock_scope": "worker_default" if args.lock_dir.samefile(Path("/tmp")) else "test_override",
             "runner_sha256": INVOCATION_RUNNER_SHA256,
             "checkout_sha": None, "checkout_sha_before": None, "checkout_sha_after": None,
             "captures": {"before": [], "after": []},
             "stability": {"status": "not_captured", "changed_ids": [], "reason_codes": []},
             "lock_modes": {"i7-heavy.lock": "exclusive", "nzbget-rust-benchmark.lock": "shared"} if args.mode == "build" else {"nzbget-rust-benchmark.lock": "exclusive"},
             "time_prebuilt": args.mode == "time",
             "started_at": utc_now(), "build_jobs": args.jobs if args.mode == "build" else None,
             "limits": {"timeout_seconds": args.timeout_seconds, "lock_timeout_seconds": args.lock_timeout_seconds,
                        "shutdown_grace_seconds": args.shutdown_grace_seconds},
             "command": {"name": executable.name, "sha256": None, "argv_sha256": argv_digest(command)},
             "fixtures": [],
             "toolchain": {"python": platform.python_version(), "kernel": platform.release(), "machine": platform.machine()},
             "toolchain_binaries": []}
    return proof


def save_metadata(path, proof):
    # An atomic replace keeps consumers from seeing a truncated JSON document.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".runner-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(proof, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    args = arguments(argv)
    interrupted = [0]
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda number, frame: interrupted.__setitem__(0, number))
    proof = None
    try:
        command, executable = prepare_command(args)
        if not sys.platform.startswith("linux"):
            raise ValueError("command execution requires the existing Linux worker")
        metadata_destination_safe(args, command)
        if args.metadata:
            proof = provenance(args, command, executable)
        env = safe_environment(args.mode, args.jobs)
        locks = acquire_locks(args, interrupted)
        with tempfile.TemporaryDirectory(prefix="nzbget-bench-home-") as home:
            env.update(HOME=home, XDG_CONFIG_HOME=home)
            result = execute(args, command, env, locks, interrupted)
    except InterruptedError:
        result = {"exit_code": 128 + (interrupted[0] or signal.SIGTERM), "outcome": "interrupted",
                  "duration_ns": 0, "command_started": False}
    except TimeoutError:
        print("runner: lock acquisition timed out; command was not launched", file=sys.stderr)
        result = {"exit_code": 75, "outcome": "lock_timeout", "duration_ns": 0, "command_started": False}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Do not echo exception paths/arguments, which may carry private values.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"runner: {message}", file=sys.stderr)
        result = {"exit_code": 2, "outcome": "runner_error", "duration_ns": 0, "command_started": None}
    if proof is not None:
        proof.update(result, finished_at=utc_now())
        try:
            metadata_destination_safe(args, command)
            save_metadata(args.metadata, proof)
        except (OSError, ValueError):
            print("runner: could not save metadata", file=sys.stderr)
            return 2
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
