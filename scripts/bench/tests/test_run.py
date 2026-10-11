"""Lightweight runner tests; Linux process/lock tests use private fake locks."""
import fcntl
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

RUNNER = Path(__file__).resolve().parents[1] / "run.py"
LINUX = sys.platform.startswith("linux")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.locks = self.root / "locks"
        self.locks.mkdir()
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        self.temp.cleanup()

    def command(self, mode, argv, extra=()):
        return [sys.executable, str(RUNNER), "--mode", mode,
                "--lock-dir", str(self.locks), "--timeout-seconds", "3",
                "--lock-timeout-seconds", "1", *extra, "--", *argv]

    def start(self, mode, argv, extra=(), env=None):
        child = subprocess.Popen(self.command(mode, argv, extra),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.children.append(child)
        return child

    def run_cli(self, mode, argv, extra=(), env=None):
        child = self.start(mode, argv, extra, env)
        stdout, stderr = child.communicate(timeout=8)
        return child.returncode, stdout.decode(), stderr.decode()

    def script(self, body, name="helper.py"):
        script = self.root / name
        script.write_text(body)
        return [sys.executable, str(script)]

    def wait_file(self, path):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.02)
        self.fail(f"helper did not create {path.name}")

    def wait_queued(self, child, name):
        target = str(self.locks / name)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                if any(os.readlink(fd) == target for fd in Path(f"/proc/{child.pid}/fd").iterdir()):
                    return
            except FileNotFoundError:
                pass
            time.sleep(.01)
        self.fail("runner never entered lock acquisition")

    def available(self, name, kind=fcntl.LOCK_EX):
        with (self.locks / name).open("a+") as stream:
            try:
                fcntl.flock(stream, kind | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(stream, fcntl.LOCK_UN)
            return True

    def test_help_describes_required_modes(self):
        result = subprocess.run([sys.executable, str(RUNNER), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build,time", result.stdout)

    def test_time_rejects_interpreters_shells_and_build_tools(self):
        # Removing command validation would execute these programs under time.
        for command in (sys.executable, "sh", "cmake", "make", "cargo", "cc"):
            with self.subTest(command=command):
                status, _, _ = self.run_cli("time", [command, "--version"])
                self.assertEqual(status, 2)

    def test_time_rejects_executable_scripts_even_with_innocent_name(self):
        script = self.root / "measurement"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        status, _, _ = self.run_cli("time", [str(script)])
        self.assertEqual(status, 2)

    @unittest.skipUnless(LINUX, "native ELF execution is Linux-only")
    def test_compiler_and_shell_aliases_cannot_bypass_mode_guards(self):
        compiler = shutil.which("gcc") or shutil.which("cc")
        if compiler:
            alias = self.root / "measurement"
            alias.symlink_to(compiler)
            status, _, _ = self.run_cli("time", [str(alias), "--version"])
            self.assertEqual(status, 2)
        alias = self.root / "driver"
        alias.symlink_to(shutil.which("sh"))
        status, _, _ = self.run_cli("build", [str(alias), "-c", "true"])
        self.assertEqual(status, 2)

    def test_build_rejects_explicit_overparallelism_and_eval(self):
        for argv in (["make", "-j4"], ["cmake", "--build", ".", "--parallel", "4"],
                     ["ninja", "-j"], ["sh", "-c", "true"], ["cargo", "build", "--jobs=9"]):
            with self.subTest(argv=argv):
                status, _, _ = self.run_cli("build", argv)
                self.assertEqual(status, 2)

    @unittest.skipUnless(LINUX, "fake build-driver tests are Linux-only")
    def test_native_cmake_flags_are_capped_but_cargo_program_args_are_not_build_jobs(self):
        ready = self.root / "launched"
        body = f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(ready)!r}).touch()\n"
        for name in ("cmake", "cargo"):
            (self.root / name).write_text(body)
            (self.root / name).chmod(0o755)
        for argv in ([str(self.root / "cmake"), "--build", ".", "--", "-j99"],
                     [str(self.root / "cargo"), "build", "--", "-j99"]):
            status, _, _ = self.run_cli("build", argv)
            self.assertEqual(status, 2)
            self.assertFalse(ready.exists())
        status, _, error = self.run_cli("build", [str(self.root / "cargo"), "run", "--", "-j99"])
        self.assertEqual(status, 0, error)
        self.assertTrue(ready.exists())

    @unittest.skipUnless(LINUX, "fake build-driver tests are Linux-only")
    def test_ninja_symlink_alias_gets_job_cap_and_preserves_invocation_name(self):
        ninja = self.root / "ninja"
        ninja.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nprint(json.dumps({'name':Path(sys.argv[0]).name,'args':sys.argv[1:]}))\n")
        ninja.chmod(0o755)
        alias = self.root / "build-driver"
        alias.symlink_to(ninja)
        for jobs in (3, 2):
            with self.subTest(jobs=jobs):
                status, output, error = self.run_cli("build", [str(alias)], ("--jobs", str(jobs)))
                self.assertEqual(status, 0, error)
                actual = json.loads(output)
                self.assertEqual(actual["name"], "build-driver")
                self.assertEqual(actual["args"], [f"-j{jobs}"])

    @unittest.skipUnless(LINUX, "fake Cargo-driver tests are Linux-only")
    def test_cargo_config_overrides_cannot_bypass_job_cap_or_hide_in_alias(self):
        cargo = self.root / "cargo"
        ready = self.root / "launched"
        cargo.write_text(f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(ready)!r}).touch()\n")
        cargo.chmod(0o755)
        alias = self.root / "build-driver"
        alias.symlink_to(cargo)
        config = self.root / "override.toml"
        config.write_text("[build]\njobs=99\n")
        for executable in (cargo, alias):
            for flags in (("--config", "build.jobs=99"), ("--config=build.jobs=99",), ("--config", str(config))):
                with self.subTest(executable=executable.name, flags=flags):
                    ready.unlink(missing_ok=True)
                    status, _, _ = self.run_cli("build", [str(executable), *flags, "build"])
                    self.assertEqual(status, 2)
                    self.assertFalse(ready.exists())
        ready.unlink(missing_ok=True)
        status, _, error = self.run_cli("build", [str(alias), "--offline", "run", "--", "--config", "build.jobs=99", "-j99"])
        self.assertEqual(status, 0, error)
        self.assertTrue(ready.exists())

    @unittest.skipUnless(LINUX, "metadata collision tests are Linux-only")
    def test_metadata_cannot_replace_inputs_aliases_or_lock_files(self):
        for case in ("fixture", "tool", "executable", "lock", "hardlink", "symlink", "parent_symlink", "parent_symlink_dotdot"):
            with self.subTest(case=case):
                root = self.root / case
                root.mkdir()
                ready = root / "never"
                driver = root / "driver"
                driver.write_text(f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(ready)!r}).touch()\n")
                driver.chmod(0o755)
                fixture, tool = root / "fixture", root / "compiler"
                fixture.write_bytes(b"fixture bytes")
                tool.write_bytes(b"compiler bytes")
                dest = fixture
                fixture_arg = fixture
                if case == "tool":
                    dest = tool
                elif case == "executable":
                    dest = driver
                elif case == "lock":
                    dest = self.locks / "i7-heavy.lock"
                    dest.write_bytes(b"lock bytes")
                elif case == "hardlink":
                    dest = root / "receipt"
                    os.link(fixture, dest)
                elif case == "symlink":
                    dest = root / "receipt"
                    dest.symlink_to(fixture)
                elif case == "parent_symlink":
                    dest = root / "linked-directory"
                    dest.symlink_to(root, target_is_directory=True)
                    fixture_arg = dest / "fixture"
                elif case == "parent_symlink_dotdot":
                    (root / "inner").mkdir()
                    dest = root / "linked-directory"
                    dest.symlink_to(root / "inner", target_is_directory=True)
                    fixture_arg = dest / ".." / "fixture"
                driver_bytes = driver.read_bytes()
                fixture_bytes = fixture.read_bytes()
                tool_bytes = tool.read_bytes()
                inode = dest.lstat().st_ino
                status, _, _ = self.run_cli("build", [str(driver)], ("--metadata", str(dest),
                    "--testbed", "fixture-worker", "--fixture", str(fixture_arg), "--toolchain-binary", str(tool)))
                self.assertEqual(status, 2)
                self.assertFalse(ready.exists())
                self.assertEqual(fixture.read_bytes(), fixture_bytes)
                self.assertEqual(tool.read_bytes(), tool_bytes)
                self.assertEqual(driver.read_bytes(), driver_bytes)
                self.assertEqual(dest.lstat().st_ino, inode)

    def test_metadata_guard_tracks_intermediate_symlinks_in_expanded_input_targets(self):
        for role in ("fixture", "tool", "runner", "lock", "relative_dotdot"):
            with self.subTest(role=role):
                root = self.root / role
                (root / "out").mkdir(parents=True)
                real = root / "real"
                real.mkdir()
                (real / "fixture").write_bytes(b"preserve input")
                metadata = root / "out" / "receipt.json"
                metadata.symlink_to(real, target_is_directory=True)
                outer = root / "outer-input"
                if role == "relative_dotdot":
                    (real / "nested").mkdir()
                    metadata.unlink()
                    metadata.symlink_to(real / "nested", target_is_directory=True)
                    outer.symlink_to("out/receipt.json/../fixture")
                elif role == "lock":
                    (real / "locks").mkdir()
                    outer.symlink_to(metadata / "locks", target_is_directory=True)
                else:
                    outer.symlink_to(metadata / "fixture")
                spec = importlib.util.spec_from_file_location("runner_guard_probe", RUNNER)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if role == "runner":
                    module.RUNNER_ORIGINAL_PATH = outer
                args = SimpleNamespace(metadata=metadata,
                    fixture=[outer] if role in ("fixture", "relative_dotdot") else [],
                    toolchain_binary=[outer] if role == "tool" else [],
                    lock_dir=outer if role == "lock" else root / "unrelated-locks")
                inode = metadata.lstat().st_ino
                with self.assertRaises(ValueError):
                    module.metadata_destination_safe(args, [sys.executable])
                self.assertEqual(metadata.lstat().st_ino, inode)
                self.assertEqual((real / "fixture").read_bytes(), b"preserve input")

    @unittest.skipUnless(LINUX, "Linux treats slash and double-slash as the same root")
    def test_metadata_cannot_replace_missing_input_slot_through_double_slash_root(self):
        metadata = self.root / "absent-fixture"
        alias = Path("//" + str(metadata).lstrip("/"))
        spec = importlib.util.spec_from_file_location("runner_double_slash", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = SimpleNamespace(metadata=metadata, fixture=[alias], toolchain_binary=[], lock_dir=self.locks)
        with self.assertRaises(ValueError):
            module.metadata_destination_safe(args, [sys.executable])
        self.assertFalse(metadata.exists())

    @unittest.skipUnless(LINUX, "metadata collision tests are Linux-only")
    def test_metadata_collision_created_while_queued_is_rejected_under_lock(self):
        metadata, fixture, ready = self.root / "receipt", self.root / "fixture", self.root / "never"
        fixture.write_bytes(b"protected input")
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        with (self.locks / "i7-heavy.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = self.start("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker", "--fixture", str(fixture)))
            self.wait_queued(child, "i7-heavy.lock")
            os.link(fixture, metadata)
            inode = metadata.stat().st_ino
            fcntl.flock(lock, fcntl.LOCK_UN)
            child.communicate(timeout=5)
        self.assertEqual(child.returncode, 2)
        self.assertFalse(ready.exists())
        self.assertEqual(fixture.read_bytes(), b"protected input")
        self.assertEqual(metadata.stat().st_ino, inode)

    @unittest.skipUnless(LINUX, "checkout capture tests are Linux-only")
    def test_checkout_identity_change_is_descriptive_hold(self):
        git = shutil.which("git")
        if not git:
            self.skipTest("Git is unavailable")
        repo = self.root / "checkout"
        subprocess.run([git, "init", "-q", str(repo)], check=True, capture_output=True)
        # Blobs, not commits: this isolated fixture tests revision resolution
        # without creating unsigned development commits.
        before = subprocess.check_output([git, "hash-object", "-w", "--stdin"], cwd=repo, input=b"before").decode().strip()
        after = subprocess.check_output([git, "hash-object", "-w", "--stdin"], cwd=repo, input=b"after").decode().strip()
        head = repo / ".git" / "HEAD"
        head.write_text(before + "\n")
        argv = self.script(f"from pathlib import Path\nPath({str(head)!r}).write_text({(after + chr(10))!r})\n")
        metadata = self.root / "checkout.json"
        child = subprocess.Popen(self.command("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker")),
                                 cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        _, error = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 76, error)
        proof = json.loads(metadata.read_text())
        self.assertEqual(proof["checkout_sha"], before)
        self.assertEqual(proof["checkout_sha_before"], before)
        self.assertEqual(proof["checkout_sha_after"], after)
        self.assertEqual(proof["qualification"], "HOLD")
        self.assertIn("checkout", proof["stability"]["changed_ids"])

    def test_rejects_unbounded_timeout_and_jobs(self):
        for extra in (("--timeout-seconds", "nan"), ("--timeout-seconds", "0"),
                      ("--timeout-seconds", "90000"), ("--jobs", "4"),
                      ("--lock-timeout-seconds", "inf")):
            status, _, _ = self.run_cli("build", ["true"], extra)
            self.assertEqual(status, 2)

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_build_caps_environment_and_keeps_metadata_secret_free(self):
        metadata = self.root / "metadata.json"
        fixture = self.root / "input.bin"
        fixture.write_bytes(b"fixture bytes")
        argv = self.script("import json,os,sys\nprint(json.dumps(dict(os.environ)))\nprint(sys.argv[1:])\n")
        env = dict(os.environ, GITHUB_TOKEN="private-token", BENCHER_API_KEY="private-bencher",
                   MAKEFLAGS="-j99", CARGO_BUILD_JOBS="99")
        env.pop("RUSTUP_HOME", None)
        env.pop("CARGO_HOME", None)
        status, output, error = self.run_cli("build", argv + ["literal $(echo injected)", "private-argument"],
            ("--metadata", str(metadata), "--testbed", "fixture-worker", "--fixture", str(fixture)), env)
        self.assertEqual(status, 0, error)
        child_env = json.loads(output.splitlines()[0])
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn("BENCHER_API_KEY", child_env)
        self.assertEqual(child_env["CARGO_BUILD_JOBS"], "3")
        self.assertEqual(child_env["CMAKE_BUILD_PARALLEL_LEVEL"], "3")
        self.assertEqual(child_env["MAKEFLAGS"], "-j3")
        self.assertIn("literal $(echo injected)", output)
        raw = metadata.read_text()
        self.assertNotIn("private-", raw)
        self.assertNotIn(str(self.root), raw)
        proof = json.loads(raw)
        self.assertEqual(proof["testbed"], "fixture-worker")
        self.assertEqual(proof["exit_code"], 0)
        self.assertEqual(proof["fixtures"][0]["sha256"], hashlib.sha256(b"fixture bytes").hexdigest())
        self.assertEqual(proof["command"]["sha256"], hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest())
        self.assertEqual(proof["runner_sha256"], hashlib.sha256(RUNNER.read_bytes()).hexdigest())
        self.assertEqual(proof["lock_scope"], "test_override")
        self.assertEqual(proof["lock_modes"], {"i7-heavy.lock": "exclusive", "nzbget-rust-benchmark.lock": "shared"})
        self.assertFalse(proof["time_prebuilt"])
        self.assertEqual(child_env["RUSTUP_HOME"], str(Path.home() / ".rustup"))
        self.assertEqual(child_env["CARGO_HOME"], str(Path.home() / ".cargo"))

    @unittest.skipUnless(LINUX, "nested toolchain-cache environment tests are Linux-only")
    def test_explicit_toolchain_caches_survive_nested_isolated_home(self):
        outer_home, cargo_home, rustup_home = [self.root / name for name in
                                              ("outer-isolated-home", "explicit-cargo-cache", "distinct-rustup-cache")]
        for path in (outer_home, cargo_home, rustup_home):
            path.mkdir()
        env = dict(os.environ, HOME=str(outer_home), XDG_CONFIG_HOME=str(outer_home),
                   CARGO_HOME=str(cargo_home), RUSTUP_HOME=str(rustup_home))
        argv = self.script("import json,os\nprint(json.dumps(dict(os.environ)))\n")
        status, output, error = self.run_cli("build", argv, env=env)
        self.assertEqual(status, 0, error)
        child_env = json.loads(output)
        self.assertEqual(child_env["CARGO_HOME"], str(cargo_home))
        self.assertEqual(child_env["RUSTUP_HOME"], str(rustup_home))
        self.assertNotEqual(child_env["HOME"], str(outer_home))
        self.assertEqual(child_env["XDG_CONFIG_HOME"], child_env["HOME"])
        self.assertEqual(child_env["CARGO_BUILD_JOBS"], "3")

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_supervisor_internal_error_reaps_child_tree_before_unlock(self):
        ready, done = self.root / "ready", self.root / "done"
        grandchild = self.script(f"from pathlib import Path\nimport os,time\nos.setsid()\nPath({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(2)\nPath({str(done)!r}).touch()\n", "grand-error.py")
        argv = self.script(f"import subprocess,time\nsubprocess.Popen({grandchild!r},close_fds=True)\ntime.sleep(2)\n")
        wrapper = self.script(f"""import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('runner', {str(RUNNER)!r})
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original = runner.descendants
faulted = False
def fail_once():
    global faulted
    if Path({str(ready)!r}).exists() and not faulted:
        faulted = True
        raise OSError('controlled supervisor failure')
    return original()
runner.descendants = fail_once
raise SystemExit(runner.main())
""", "inject-error.py")
        command = self.command("build", argv)
        command[0:2] = wrapper
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        self.wait_file(ready)
        child.communicate(timeout=5)
        self.assertEqual(child.returncode, 2)
        self.assertFalse(done.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)
        self.assertTrue(self.available("i7-heavy.lock"))
        self.assertTrue(self.available("nzbget-rust-benchmark.lock"))

    @unittest.skipUnless(LINUX, "authoritative child-table tests are Linux-only")
    def test_empty_proc_scan_or_cleanup_exception_never_releases_live_adopted_child(self):
        for case in ("ordinary", "timeout", "emergency_empty", "emergency_exception"):
            with self.subTest(case=case):
                ready, root_pid, injected = [self.root / f"{case}-{name}" for name in ("leaf", "root", "injected")]
                leaf = self.script(f"from pathlib import Path\nimport os,time\nos.setsid()\nPath({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(1)\n", f"{case}-leaf.py")
                driver = self.script(f"""import os,subprocess,time
from pathlib import Path
Path({str(root_pid)!r}).write_text(str(os.getpid()))
subprocess.Popen({leaf!r},close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while not Path({str(ready)!r}).exists(): time.sleep(.005)
""", f"{case}-driver.py")
                wrapper = self.script(f"""import importlib.util,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',{str(RUNNER)!r})
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
real_wait,real_scan=runner.os.waitpid,runner.descendants
reaped=False
last_wait=None
scans=0
def waitpid(pid,flags):
    global reaped,last_wait
    result=real_wait(pid,flags)
    last_wait=result[0]
    if result[0] and Path({str(root_pid)!r}).exists() and result[0]==int(Path({str(root_pid)!r}).read_text()): reaped=True
    return result
def scan():
    global scans
    if reaped and last_wait==0 and Path({str(ready)!r}).exists():
        pid=int(Path({str(ready)!r}).read_text())
        try:
            value=Path('/proc/'+str(pid)+'/stat').read_text()
            fields=value[value.rfind(')')+2:].split()
            live=fields[0]!='Z' and int(fields[1])==os.getpid()
        except FileNotFoundError: live=False
        if live:
            scans+=1
            if {case!r} in ('ordinary','timeout') and scans<= (8 if {case!r}=='timeout' else 1):
                Path({str(injected)!r}).touch()
                return set()
            if {case!r}.startswith('emergency') and scans==1:
                Path({str(injected)!r}).touch()
                raise OSError('controlled supervisor error')
            if {case!r}=='emergency_empty' and scans in (2,3): return set()
            if {case!r}=='emergency_exception' and scans==2: raise RuntimeError('controlled cleanup error')
    return real_scan()
runner.os.waitpid=waitpid
runner.descendants=scan
raise SystemExit(runner.main())
""", f"{case}-wrapper.py")
                extra = ("--timeout-seconds", ".1", "--shutdown-grace-seconds", ".05") if case == "timeout" else ()
                command = self.command("build", driver, extra)
                command[0:2] = wrapper
                child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.children.append(child)
                try:
                    child.communicate(timeout=5)
                    self.assertTrue(injected.exists())
                    pid = int(ready.read_text())
                    with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
                    self.assertEqual(child.returncode, 124 if case == "timeout" else 2 if case.startswith("emergency") else 0)
                    self.assertTrue(self.available("i7-heavy.lock"))
                    self.assertTrue(self.available("nzbget-rust-benchmark.lock"))
                finally:
                    if ready.exists():
                        try: os.kill(int(ready.read_text()), signal.SIGKILL)
                        except ProcessLookupError: pass

    @unittest.skipUnless(LINUX, "SIGCHLD disposition tests are Linux-only")
    def test_inherited_ignored_sigchld_does_not_make_child_status_unreapable(self):
        wrapper = self.script(f"""import importlib.util,signal
spec=importlib.util.spec_from_file_location('runner',{str(RUNNER)!r})
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
signal.signal(signal.SIGCHLD,signal.SIG_IGN)
raise SystemExit(runner.main())
""", "ignored-sigchld.py")
        command = self.command("build", [shutil.which("true")])
        command[0:2] = wrapper
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        try:
            _, error = child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.communicate(timeout=5)
            self.fail("ignored SIGCHLD made command status impossible to reap")
        self.assertEqual(child.returncode, 0, error)

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_build_preserves_multicall_executable_alias(self):
        # Resolving argv[0] would turn the real cargo rustup shim into rustup.
        alias = self.root / "aliased-python"
        alias.symlink_to(sys.executable)
        argv = self.script("import sys\nfrom pathlib import Path\nprint(Path(sys.executable).name)\n")
        argv[0] = str(alias)
        status, output, error = self.run_cli("build", argv)
        self.assertEqual(status, 0, error)
        self.assertEqual(output.strip(), "aliased-python")

    @unittest.skipUnless(LINUX, "capture/lock tests are Linux-only")
    def test_queued_artifacts_are_captured_only_after_lock_acquisition(self):
        metadata = self.root / "queued.json"
        fixture, tool = self.root / "fixture", self.root / "compiler"
        fixture.write_bytes(b"old input")
        tool.write_bytes(b"old compiler")
        alias = self.root / "driver"
        alias.symlink_to(shutil.which("true"))
        with (self.locks / "i7-heavy.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = self.start("build", [str(alias)], ("--metadata", str(metadata), "--testbed", "fixture-worker",
                "--fixture", str(fixture), "--toolchain-binary", str(tool)))
            self.wait_queued(child, "i7-heavy.lock")
            fixture.write_bytes(b"new input")
            tool.write_bytes(b"new compiler")
            alias.unlink()
            alias.symlink_to(shutil.which("false"))
            fcntl.flock(lock, fcntl.LOCK_UN)
            child.communicate(timeout=5)
        self.assertEqual(child.returncode, 1)
        proof = json.loads(metadata.read_text())
        before = {record["id"]: record["sha256"] for record in proof["captures"]["before"]}
        self.assertEqual(proof["capture_version"], 1)
        self.assertEqual(before["fixture-0"], hashlib.sha256(b"new input").hexdigest())
        self.assertEqual(before["tool-0"], hashlib.sha256(b"new compiler").hexdigest())
        self.assertEqual(before["executable"], hashlib.sha256(Path(shutil.which("false")).read_bytes()).hexdigest())
        self.assertEqual(proof["captures"]["before"], proof["captures"]["after"])
        self.assertEqual(proof["stability"]["status"], "stable")

    @unittest.skipUnless(LINUX, "capture/lock tests are Linux-only")
    def test_changes_during_child_execution_are_hold_with_original_before_hashes(self):
        metadata = self.root / "changed.json"
        fixture, tool = self.root / "fixture", self.root / "compiler"
        fixture.write_bytes(b"old input")
        tool.write_bytes(b"old compiler")
        alias = self.root / "driver"
        alias.symlink_to(sys.executable)
        argv = self.script(f"from pathlib import Path\nPath({str(fixture)!r}).write_bytes(b'new input')\nPath({str(tool)!r}).write_bytes(b'new compiler')\np=Path({str(alias)!r})\np.unlink()\np.symlink_to({shutil.which('true')!r})\n")
        argv[0] = str(alias)
        status, _, error = self.run_cli("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker",
                "--fixture", str(fixture), "--toolchain-binary", str(tool)))
        self.assertEqual(status, 76, error)
        proof = json.loads(metadata.read_text())
        before = {record["id"]: record["sha256"] for record in proof["captures"]["before"]}
        after = {record["id"]: record["sha256"] for record in proof["captures"]["after"]}
        self.assertEqual(before["fixture-0"], hashlib.sha256(b"old input").hexdigest())
        self.assertEqual(after["fixture-0"], hashlib.sha256(b"new input").hexdigest())
        self.assertEqual(proof["fixtures"][0]["sha256"], before["fixture-0"])
        self.assertEqual(proof["command"]["sha256"], before["executable"])
        self.assertEqual(set(proof["stability"]["changed_ids"]), {"executable", "fixture-0", "tool-0"})
        self.assertEqual(proof["outcome"], "provenance_drift")
        self.assertEqual(proof["qualification"], "HOLD")
        self.assertEqual(proof["child_exit_code"], 0)

    @unittest.skipUnless(LINUX, "capture/lock tests are Linux-only")
    def test_failed_child_keeps_primary_status_when_after_capture_drifts(self):
        for exit_code, child_code, ending in ((7, 7, "raise SystemExit(7)"),
                                             (143, -signal.SIGTERM, "os.kill(os.getpid(), signal.SIGTERM)")):
            with self.subTest(exit_code=exit_code):
                fixture, metadata = self.root / "fixture", self.root / "proof.json"
                fixture.write_bytes(b"before")
                argv = self.script(f"from pathlib import Path\nimport os,signal\nPath({str(fixture)!r}).write_bytes(b'after')\n{ending}\n")
                status, _, error = self.run_cli("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker",
                                                             "--fixture", str(fixture)))
                self.assertEqual(status, exit_code, error)
                proof = json.loads(metadata.read_text())
                self.assertEqual(proof["exit_code"], exit_code)
                self.assertEqual(proof["child_exit_code"], child_code)
                self.assertEqual(proof["outcome"], "completed")
                self.assertEqual(proof["qualification"], "HOLD")
                self.assertEqual(proof["stability"]["status"], "changed")
                self.assertIn("fixture-0", proof["stability"]["changed_ids"])

    @unittest.skipUnless(LINUX, "native validation/lock tests are Linux-only")
    def test_timing_header_rejects_fifo_replacement_without_blocking(self):
        for phase in (1, 2):
            with self.subTest(phase=phase):
                executable, events = self.root / f"native-{phase}", self.root / f"race-{phase}"
                shutil.copyfile(shutil.which("true"), executable)
                executable.chmod(0o755)
                wrapper = self.script(f"""import importlib.util,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',{str(RUNNER)!r})
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original=Path.is_file
calls=0
def raced(path):
    global calls
    result=original(path)
    if path==Path({str(executable)!r}):
        calls+=1
        if calls=={phase}:
            path.unlink()
            os.mkfifo(path,0o755)
            Path({str(events)!r}).touch()
    return result
Path.is_file=raced
raise SystemExit(runner.main())
""", f"fifo-header-{phase}.py")
                command = self.command("time", [str(executable)], ("--timeout-seconds", ".15"))
                command[0:2] = wrapper
                child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.children.append(child)
                self.wait_file(events)
                try:
                    _, error = child.communicate(timeout=.4)
                except subprocess.TimeoutExpired:
                    # Release the old FIFO header open before reporting RED.
                    writer = os.open(executable, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(writer, b"NOPE")
                        child.communicate(timeout=3)
                    finally:
                        os.close(writer)
                    self.fail("timing header blocked on the replaced FIFO")
                self.assertIn(child.returncode, (2, 76), error)
                self.assertTrue(self.available("i7-heavy.lock"))
                self.assertTrue(self.available("nzbget-rust-benchmark.lock"))

    def test_timing_header_read_deadline_and_cancellation_close_descriptor(self):
        executable = self.root / "native"
        executable.write_bytes(b"\x7fELF")
        executable.chmod(0o755)
        for action in ("deadline", "cancel"):
            with self.subTest(action=action):
                spec = importlib.util.spec_from_file_location("runner_header_bound", RUNNER)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                args = module.arguments(["--mode", "time", "--", str(executable)])
                real_read = os.read
                cancelled, completed, descriptors = [False], [], []
                previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
                def slow_read(descriptor, count):
                    descriptors.append(descriptor)
                    if action == "cancel": cancelled[0] = True
                    time.sleep(1)
                    completed.append(True)
                    return real_read(descriptor, count)
                started = time.monotonic()
                try:
                    module.os.read = slow_read
                    with self.assertRaises(module.CaptureFailure) as error:
                        module.prepare_command(args, deadline=started + .08,
                                               cancelled=lambda: cancelled[0])
                    self.assertEqual(error.exception.code, "deadline" if action == "deadline" else "cancelled")
                    self.assertLess(time.monotonic() - started, .5)
                    self.assertFalse(completed)
                    self.assertEqual(len(descriptors), 1)
                    with self.assertRaises(OSError): os.fstat(descriptors[0])
                    self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
                finally:
                    module.os.read = real_read

    @unittest.skipUnless(LINUX, "native validation/cancellation tests are Linux-only")
    def test_cli_header_cancellation_preserves_signal_status_and_releases_locks(self):
        for phase in (1, 2):
            with self.subTest(phase=phase):
                executable, ready, completed = [self.root / f"header-{phase}-{name}" for name in ("native", "ready", "completed")]
                shutil.copyfile(shutil.which("true"), executable)
                executable.chmod(0o755)
                wrapper = self.script(f"""import importlib.util,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',{str(RUNNER)!r})
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original=runner.os.read
identity=Path({str(executable)!r}).stat()
calls=0
def read(fd,count):
    global calls
    observed=os.fstat(fd)
    if count==4 and (observed.st_dev,observed.st_ino)==(identity.st_dev,identity.st_ino):
        calls+=1
        if calls=={phase}:
            Path({str(ready)!r}).touch()
            time.sleep(1)
            Path({str(completed)!r}).touch()
    return original(fd,count)
runner.os.read=read
raise SystemExit(runner.main())
""", f"header-cancel-{phase}.py")
                command = self.command("time", [str(executable)])
                command[0:2] = wrapper
                child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.children.append(child)
                self.wait_file(ready)
                child.terminate()
                _, error = child.communicate(timeout=.5)
                self.assertEqual(child.returncode, 143, error)
                self.assertFalse(completed.exists())
                self.assertTrue(self.available("i7-heavy.lock"))
                self.assertTrue(self.available("nzbget-rust-benchmark.lock"))

    @unittest.skipUnless(LINUX, "FIFO capture tests are Linux-only")
    def test_fifo_inputs_are_hold_without_launch_or_retained_locks(self):
        for flag in ("--fixture", "--toolchain-binary"):
            with self.subTest(flag=flag):
                fifo = self.root / flag[2:]
                os.mkfifo(fifo)
                metadata, ready = self.root / f"{flag[2:]}.json", self.root / f"{flag[2:]}-never"
                argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n", f"{flag[2:]}.py")
                child = self.start("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker",
                                                  flag, str(fifo), "--timeout-seconds", ".2"))
                try:
                    child.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    # Safely release the old blocking-open implementation during
                    # the red run; no abandoned custodian or fake lock holder.
                    writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        child.communicate(timeout=5)
                    finally:
                        os.close(writer)
                    self.fail("capture blocked on a FIFO before command timeout")
                self.assertEqual(child.returncode, 76)
                self.assertFalse(ready.exists())
                proof = json.loads(metadata.read_text())
                self.assertFalse(proof["command_started"])
                self.assertEqual(proof["qualification"], "HOLD")
                self.assertIn("artifact_unavailable", proof["stability"]["reason_codes"])
                self.assertTrue(self.available("i7-heavy.lock"))
                self.assertTrue(self.available("nzbget-rust-benchmark.lock"))

    def slow_capture_wrapper(self, fixture, events, phase):
        return self.script(f"""import importlib.util,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',{str(RUNNER)!r})
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
real_fdopen=runner.os.fdopen
fixture=Path({str(fixture)!r})
identity=(fixture.stat().st_dev,fixture.stat().st_ino)
opened=0
class Reader:
    def __init__(self,stream): self.stream,self.delayed=stream,False
    def __enter__(self): return self
    def __exit__(self,*args): return self.stream.__exit__(*args)
    def __getattr__(self,name): return getattr(self.stream,name)
    def readinto(self,buffer):
        if not self.delayed:
            self.delayed=True
            with Path({str(events)!r}).open('a') as event: event.write('started\\n')
            time.sleep(.4)
            with Path({str(events)!r}).open('a') as event: event.write('completed\\n')
        return self.stream.readinto(buffer)
def fdopen(fd,*args,**kwargs):
    global opened
    stream=real_fdopen(fd,*args,**kwargs)
    value=os.fstat(fd)
    if (value.st_dev,value.st_ino)==identity:
        opened+=1
        if {phase!r}!='after' or opened==2: return Reader(stream)
    return stream
runner.os.fdopen=fdopen
raise SystemExit(runner.main())
""", f"slow-{phase}-wrapper.py")

    @unittest.skipUnless(LINUX, "capture alarm tests are Linux-only")
    def test_capture_deadline_interrupts_blocking_regular_read_before_launch(self):
        fixture, events, metadata, ready = [self.root / name for name in ("fixture", "events", "proof.json", "never")]
        fixture.write_bytes(b"regular input")
        wrapper = self.slow_capture_wrapper(fixture, events, "before")
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        command = self.command("build", argv, ("--timeout-seconds", ".1", "--metadata", str(metadata),
                                               "--testbed", "fixture-worker", "--fixture", str(fixture)))
        command[0:2] = wrapper
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        _, error = child.communicate(timeout=3)
        self.assertEqual(child.returncode, 76, error)
        self.assertFalse(ready.exists())
        self.assertIn("started", events.read_text())
        self.assertNotIn("completed", events.read_text())
        proof = json.loads(metadata.read_text())
        self.assertFalse(proof["command_started"])
        self.assertEqual(proof["qualification"], "HOLD")
        self.assertTrue(self.available("i7-heavy.lock"))

    @unittest.skipUnless(LINUX, "capture alarm tests are Linux-only")
    def test_incomplete_after_capture_is_hold_without_prefix_digest(self):
        fixture, events, metadata, ready = [self.root / name for name in ("fixture", "events", "proof.json", "ran")]
        fixture.write_bytes(b"regular input")
        wrapper = self.slow_capture_wrapper(fixture, events, "after")
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        command = self.command("build", argv, ("--timeout-seconds", ".2", "--metadata", str(metadata),
                                               "--testbed", "fixture-worker", "--fixture", str(fixture)))
        command[0:2] = wrapper
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        child.communicate(timeout=3)
        self.assertEqual(child.returncode, 76)
        self.assertTrue(ready.exists())
        self.assertNotIn("completed", events.read_text())
        proof = json.loads(metadata.read_text())
        self.assertEqual(proof["child_exit_code"], 0)
        self.assertEqual(proof["qualification"], "HOLD")
        before = {record["id"]: record["sha256"] for record in proof["captures"]["before"]}
        after = {record["id"]: record["sha256"] for record in proof["captures"]["after"]}
        self.assertEqual(before["fixture-0"], hashlib.sha256(b"regular input").hexdigest())
        self.assertIsNone(after["fixture-0"])

    @unittest.skipUnless(LINUX, "capture alarm tests are Linux-only")
    def test_cancelled_blocking_capture_does_not_finish_read_or_launch_command(self):
        fixture, events, metadata, ready = [self.root / name for name in ("fixture", "events", "proof.json", "never")]
        fixture.write_bytes(b"regular input")
        wrapper = self.slow_capture_wrapper(fixture, events, "cancel")
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        command = self.command("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker", "--fixture", str(fixture)))
        command[0:2] = wrapper
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        self.wait_file(events)
        child.terminate()
        child.communicate(timeout=3)
        self.assertEqual(child.returncode, 143)
        self.assertFalse(ready.exists())
        self.assertNotIn("completed", events.read_text())
        self.assertFalse(json.loads(metadata.read_text())["command_started"])
        self.assertTrue(self.available("i7-heavy.lock"))

    def test_growing_regular_reader_cannot_exceed_byte_budget_or_return_prefix_hash(self):
        fixture = self.root / "growing"
        fixture.write_bytes(b"a" * 32)
        spec = importlib.util.spec_from_file_location("runner_growth", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DEFAULT_CAPTURE_MAX_BYTES = 128
        real_fdopen = os.fdopen
        reads = []
        class Reader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def __getattr__(self, name): return getattr(self.stream, name)
            def readinto(self, buffer):
                reads.append(1)
                if len(reads) <= 8:
                    with fixture.open("ab") as writer: writer.write(b"x" * 64)
                return self.stream.readinto(buffer)
        def fdopen(fd, *args, **kwargs): return Reader(real_fdopen(fd, *args, **kwargs))
        module.os.fdopen = fdopen
        try:
            with self.assertRaises(ValueError): module.digest_file(fixture)
        finally:
            module.os.fdopen = real_fdopen
        self.assertLessEqual(len(reads), 3)

    def test_capture_alarm_restores_prior_handler_and_timer_after_failure(self):
        spec = importlib.util.spec_from_file_location("runner_alarm_restore", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        handler = lambda number, frame: None
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, 1, .5)
            with self.assertRaises(ValueError): module.digest_file(fifo)
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertLessEqual(remaining, 1)
            self.assertEqual(interval, .5)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)

    def test_prior_timer_compensation_starts_at_remaining_time_sample(self):
        spec = importlib.util.spec_from_file_location("runner_timer_sample", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        handler = lambda number, frame: None
        checked = [False]
        def delayed_check():
            if not checked[0]:
                checked[0] = True
                time.sleep(.15)
            return False
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, 30, .5)
            started = time.monotonic()
            with module.capture_alarm(started + 5, delayed_check):
                time.sleep(.05)
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            expected = 30 - (time.monotonic() - started)
            self.assertAlmostEqual(remaining, expected, delta=.03)
            self.assertEqual(interval, .5)
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)

    def test_alarm_firing_during_arming_restores_previous_handler_and_timer(self):
        spec = importlib.util.spec_from_file_location("runner_alarm_arming", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_timer, real_clock = signal.setitimer, time.monotonic
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        handler = lambda number, frame: None
        clock, armed = [0.0], [False]
        def timer(which, value, interval=0):
            result = real_timer(which, value, interval)
            if value > 0 and not armed[0]:
                armed[0] = True
                real_timer(which, 0)  # safely disable the real repeating RED alarm
                clock[0] = 11.0
                signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
            return result
        try:
            signal.signal(signal.SIGALRM, handler)
            real_timer(signal.ITIMER_REAL, 30, .5)
            module.signal.setitimer = timer
            module.time.monotonic = lambda: clock[0]
            with self.assertRaises(ValueError):
                with module.capture_alarm(10, None):
                    self.fail("arming failure reached capture body")
            self.assertTrue(armed[0])
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertEqual(interval, .5)
        finally:
            module.signal.setitimer = real_timer
            module.time.monotonic = real_clock
            real_timer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            real_timer(signal.ITIMER_REAL, *previous_timer)

    def test_alarm_after_descriptor_acquisition_closes_owned_descriptor(self):
        fixture = self.root / "fixture"
        fixture.write_bytes(b"controlled bytes")
        spec = importlib.util.spec_from_file_location("runner_descriptor_boundary", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_clock = time.monotonic
        previous_trace = sys.gettrace()
        clock, acquired = [0.0], []
        def trace(frame, event, arg):
            descriptor = frame.f_locals.get("descriptor")
            if frame.f_code is module.digest_file.__code__ and event == "line" and descriptor is not None and not acquired:
                acquired.append(descriptor)
                clock[0] = 11.0
                signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
            return trace
        try:
            module.time.monotonic = lambda: clock[0]
            sys.settrace(trace)
            with self.assertRaises(ValueError): module.digest_file(fixture, deadline=10)
            sys.settrace(previous_trace)
            self.assertEqual(len(acquired), 1)
            with self.assertRaises(OSError): os.fstat(acquired[0])
        finally:
            sys.settrace(previous_trace)
            module.time.monotonic = real_clock
            for descriptor in acquired:
                try: os.close(descriptor)
                except OSError: pass

    def test_alarm_before_open_returns_closes_allocated_descriptor(self):
        fixture = self.root / "fixture"
        fixture.write_bytes(b"controlled bytes")
        spec = importlib.util.spec_from_file_location("runner_open_return", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_open, real_clock = os.open, time.monotonic
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        clock, acquired = [0.0], []
        def opener(*args, **kwargs):
            descriptor = real_open(*args, **kwargs)
            acquired.append(descriptor)
            clock[0] = 11.0
            os.kill(os.getpid(), signal.SIGALRM)
            return descriptor
        try:
            module.os.open = opener
            module.time.monotonic = lambda: clock[0]
            with self.assertRaises(ValueError): module.digest_file(fixture, deadline=10)
            self.assertEqual(len(acquired), 1)
            with self.assertRaises(OSError): os.fstat(acquired[0])
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
        finally:
            module.os.open = real_open
            module.time.monotonic = real_clock
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            for descriptor in acquired:
                try: os.close(descriptor)
                except OSError: pass

    def test_alarm_during_disarm_cannot_interrupt_restoration(self):
        spec = importlib.util.spec_from_file_location("runner_alarm_disarm", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_timer, real_clock = signal.setitimer, time.monotonic
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        handler = lambda number, frame: None
        clock, armed, fired = [0.0], [False], [False]
        def timer(which, value, interval=0):
            if value == 0 and armed[0] and not fired[0]:
                fired[0] = True
                clock[0] = 11.0
                os.kill(os.getpid(), signal.SIGALRM)
            result = real_timer(which, value, interval)
            if value > 0: armed[0] = True
            return result
        try:
            signal.signal(signal.SIGALRM, handler)
            real_timer(signal.ITIMER_REAL, 30, .5)
            module.signal.setitimer = timer
            module.time.monotonic = lambda: clock[0]
            with module.capture_alarm(10, None): pass
            self.assertTrue(fired[0])
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertEqual(interval, .5)
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
        finally:
            module.signal.setitimer = real_timer
            module.time.monotonic = real_clock
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
            real_timer(signal.ITIMER_REAL, 0)
            if signal.SIGALRM in signal.sigpending(): signal.sigwait({signal.SIGALRM})
            signal.signal(signal.SIGALRM, previous_handler)
            real_timer(signal.ITIMER_REAL, *previous_timer)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def test_blocked_pending_caller_alarm_is_preserved_and_capture_fails_closed(self):
        spec = importlib.util.spec_from_file_location("runner_blocked_alarm", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        delivered = []
        handler = lambda number, frame: delivered.append(number)
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, 30, .5)
            os.kill(os.getpid(), signal.SIGALRM)
            with self.assertRaises(module.CaptureFailure) as failure:
                with module.capture_alarm(time.monotonic() + 10, None):
                    self.fail("blocked caller alarm reached capture body")
            self.assertEqual(failure.exception.code, "unavailable")
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            self.assertIn(signal.SIGALRM, signal.pthread_sigmask(signal.SIG_BLOCK, set()))
            self.assertIn(signal.SIGALRM, signal.sigpending())
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[1], .5)
            self.assertFalse(delivered)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if signal.SIGALRM in signal.sigpending(): signal.sigwait({signal.SIGALRM})
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def test_alarm_entering_restoration_mask_still_restores_state(self):
        spec = importlib.util.spec_from_file_location("runner_restore_mask", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_mask, real_clock = signal.pthread_sigmask, time.monotonic
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        previous_mask = real_mask(signal.SIG_BLOCK, set())
        clock, exiting, fired = [0.0], [False], [False]
        handler = lambda number, frame: None
        def mask(how, values):
            if how == signal.SIG_BLOCK and exiting[0] and not fired[0]:
                fired[0] = True
                clock[0] = 11.0
                os.kill(os.getpid(), signal.SIGALRM)
            return real_mask(how, values)
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, 30, .5)
            module.signal.pthread_sigmask = mask
            module.time.monotonic = lambda: clock[0]
            with self.assertRaises(module.CaptureFailure):
                with module.capture_alarm(10, None): exiting[0] = True
            self.assertTrue(fired[0])
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[1], .5)
            self.assertEqual(real_mask(signal.SIG_BLOCK, set()), previous_mask)
        finally:
            module.signal.pthread_sigmask = real_mask
            module.time.monotonic = real_clock
            real_mask(signal.SIG_BLOCK, {signal.SIGALRM})
            signal.setitimer(signal.ITIMER_REAL, 0)
            if signal.SIGALRM in signal.sigpending(): signal.sigwait({signal.SIGALRM})
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            real_mask(signal.SIG_SETMASK, previous_mask)

    @unittest.skipUnless(LINUX, "queued caller signal probe uses Linux pselect")
    def test_queued_caller_alarm_after_entry_mask_restores_original_mask(self):
        spec = importlib.util.spec_from_file_location("runner_entry_mask", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_mask = signal.pthread_sigmask
        previous_mask = real_mask(signal.SIG_BLOCK, set())
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        fired, observed = [False], []
        class CallerAlarm(RuntimeError): pass
        def handler(number, frame):
            observed.append(real_mask(signal.SIG_BLOCK, set()))
            raise CallerAlarm("queued caller alarm")
        # pselect temporarily unmasks the real pending OS signal, then restores
        # the blocked mask before Python dispatches its queued raising handler.
        libc = ctypes.CDLL(None, use_errno=True)
        empty = ctypes.create_string_buffer(128)  # Linux sigset_t
        libc.sigemptyset.argtypes = [ctypes.c_void_p]
        libc.sigemptyset(ctypes.byref(empty))
        class Timespec(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_long), ("nanoseconds", ctypes.c_long)]
        timeout = Timespec(0, 1000000)
        libc.pselect.argtypes = [ctypes.c_int] + [ctypes.c_void_p] * 5
        def mask(how, values):
            result = real_mask(how, values)
            if how == signal.SIG_BLOCK and signal.SIGALRM in values and not fired[0]:
                fired[0] = True
                os.kill(os.getpid(), signal.SIGALRM)
                libc.pselect(0, None, None, None, ctypes.byref(timeout), ctypes.byref(empty))
                self.fail("queued OS alarm was not dispatched")
            return result
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, 30, .5)
            module.signal.pthread_sigmask = mask
            with self.assertRaises(CallerAlarm):
                with module.capture_alarm(time.monotonic() + 10, None):
                    self.fail("entry exception reached capture body")
            self.assertEqual(len(observed), 1)
            self.assertIn(signal.SIGALRM, observed[0])
            self.assertEqual(real_mask(signal.SIG_BLOCK, set()), previous_mask)
            self.assertIs(signal.getsignal(signal.SIGALRM), handler)
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertEqual(interval, .5)
        finally:
            module.signal.pthread_sigmask = real_mask
            real_mask(signal.SIG_BLOCK, {signal.SIGALRM})
            signal.setitimer(signal.ITIMER_REAL, 0)
            if signal.SIGALRM in signal.sigpending(): signal.sigwait({signal.SIGALRM})
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            real_mask(signal.SIG_SETMASK, previous_mask)

    @unittest.skipUnless(LINUX, "capture policy tests are Linux-only")
    def test_capture_byte_policy_holds_oversized_input_before_launch(self):
        metadata, ready = self.root / "proof.json", self.root / "never"
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        status, _, error = self.run_cli("build", argv, ("--capture-max-bytes", "128", "--metadata", str(metadata), "--testbed", "fixture-worker"))
        self.assertEqual(status, 76, error)
        self.assertFalse(ready.exists())
        proof = json.loads(metadata.read_text())
        self.assertEqual(proof["limits"]["capture_max_bytes"], 128)
        self.assertFalse(proof["command_started"])
        self.assertIn("capture_byte_limit", proof["stability"]["reason_codes"])
        for value in ("0", str(8 * 1024 * 1024 * 1024 + 1)):
            status, _, _ = self.run_cli("build", [shutil.which("true")], ("--capture-max-bytes", value))
            self.assertEqual(status, 2)

    @unittest.skipUnless(LINUX, "startup identity policy tests are Linux-only")
    def test_oversized_startup_source_identity_fails_closed_without_partial_hash(self):
        copy = self.root / "large-runner.py"
        copy.write_bytes(RUNNER.read_bytes() + b"\n#" + b"x" * (1024 * 1024) + b"\n")
        metadata, ready = self.root / "source-proof.json", self.root / "never"
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        command = self.command("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker"))
        command[1] = str(copy)
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        child.communicate(timeout=5)
        self.assertEqual(child.returncode, 76)
        self.assertFalse(ready.exists())
        proof = json.loads(metadata.read_text())
        self.assertIsNone(proof["runner_sha256"])
        self.assertEqual(proof["runner_identity_error"], "byte_limit")
        self.assertFalse(proof["command_started"])

    @unittest.skipUnless(LINUX, "capture/lock tests are Linux-only")
    def test_runner_source_change_while_queued_preserves_loaded_identity_and_prevents_launch(self):
        copy = self.root / "copied-runner.py"
        copy.write_bytes(RUNNER.read_bytes())
        original_hash = hashlib.sha256(copy.read_bytes()).hexdigest()
        metadata, ready = self.root / "source.json", self.root / "never"
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        command = self.command("build", argv, ("--metadata", str(metadata), "--testbed", "fixture-worker"))
        command[1] = str(copy)
        with (self.locks / "i7-heavy.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.children.append(child)
            self.wait_queued(child, "i7-heavy.lock")
            copy.write_bytes(copy.read_bytes() + b"\n# source changed while queued\n")
            fcntl.flock(lock, fcntl.LOCK_UN)
            child.communicate(timeout=5)
        self.assertEqual(child.returncode, 76)
        proof = json.loads(metadata.read_text())
        self.assertEqual(proof["runner_sha256"], original_hash)
        self.assertFalse(proof["command_started"])
        self.assertFalse(ready.exists())
        self.assertIn("runner", proof["stability"]["changed_ids"])

    @unittest.skipUnless(LINUX, "capture/lock tests are Linux-only")
    def test_timing_path_changed_while_queued_is_revalidated_before_launch(self):
        metadata = self.root / "path.json"
        alias = self.root / "measurement"
        alias.symlink_to(shutil.which("true"))
        with (self.locks / "nzbget-rust-benchmark.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = self.start("time", [str(alias), "--version"],
                ("--metadata", str(metadata), "--testbed", "fixture-worker"))
            self.wait_queued(child, "nzbget-rust-benchmark.lock")
            alias.unlink()
            alias.symlink_to(sys.executable)
            fcntl.flock(lock, fcntl.LOCK_UN)
            child.communicate(timeout=5)
        self.assertEqual(child.returncode, 76)
        proof = json.loads(metadata.read_text())
        self.assertFalse(proof["command_started"])
        self.assertIn("command_revalidation_failed", proof["stability"]["reason_codes"])

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_build_lock_order_and_shared_benchmark_lock(self):
        ready = self.root / "ready"
        argv = self.script(f"from pathlib import Path\nimport time\nPath({str(ready)!r}).touch()\ntime.sleep(.3)\n")
        with (self.locks / "i7-heavy.lock").open("a+") as heavy:
            fcntl.flock(heavy, fcntl.LOCK_EX)
            child = self.start("build", argv)
            time.sleep(.15)
            self.assertTrue(self.available("nzbget-rust-benchmark.lock"))
            self.assertFalse(ready.exists())
            fcntl.flock(heavy, fcntl.LOCK_UN)
            self.wait_file(ready)
            self.assertFalse(self.available("i7-heavy.lock"))
            self.assertFalse(self.available("nzbget-rust-benchmark.lock"))
            self.assertTrue(self.available("nzbget-rust-benchmark.lock", fcntl.LOCK_SH))
            child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0)
        self.assertTrue(self.available("i7-heavy.lock"))
        self.assertTrue(self.available("nzbget-rust-benchmark.lock"))

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_time_uses_exclusive_benchmark_lock_without_heavy_lock(self):
        metadata = self.root / "time.json"
        with (self.locks / "i7-heavy.lock").open("a+") as heavy:
            fcntl.flock(heavy, fcntl.LOCK_EX)
            child = self.start("time", [shutil.which("sleep"), ".3"],
                               ("--metadata", str(metadata), "--testbed", "fixture-worker"))
            deadline = time.monotonic() + 3
            while self.available("nzbget-rust-benchmark.lock") and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertFalse(self.available("nzbget-rust-benchmark.lock", fcntl.LOCK_SH))
            child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0)
        proof = json.loads(metadata.read_text())
        self.assertTrue(proof["time_prebuilt"])
        self.assertEqual(proof["lock_modes"], {"nzbget-rust-benchmark.lock": "exclusive"})
        self.assertGreater(proof["duration_ns"], 0)

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_preserves_child_failure_and_stdout(self):
        metadata = self.root / "failed.json"
        argv = self.script("import sys\nprint('controlled output')\nsys.exit(7)\n")
        status, output, _ = self.run_cli("build", argv,
                                      ("--metadata", str(metadata), "--testbed", "fixture-worker"))
        self.assertEqual(status, 7)
        self.assertEqual(output, "controlled output\n")
        self.assertEqual(json.loads(metadata.read_text())["exit_code"], 7)

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_lock_timeout_prevents_launch_and_releases_partial_locks(self):
        ready = self.root / "never"
        metadata = self.root / "held.json"
        argv = self.script(f"from pathlib import Path\nPath({str(ready)!r}).touch()\n")
        with (self.locks / "nzbget-rust-benchmark.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            status, _, _ = self.run_cli("build", argv, ("--lock-timeout-seconds", ".1",
                                                       "--metadata", str(metadata), "--testbed", "fixture-worker"))
        self.assertEqual(status, 75)
        self.assertFalse(ready.exists())
        self.assertTrue(self.available("i7-heavy.lock"))
        proof = json.loads(metadata.read_text())
        self.assertEqual(proof["outcome"], "lock_timeout")
        self.assertEqual(proof["exit_code"], 75)
        self.assertFalse(proof["command_started"])

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_lock_lifetime_includes_orphaned_detached_grandchild(self):
        ready, done = self.root / "ready", self.root / "done"
        grandchild = self.script(f"from pathlib import Path\nimport os,time\nos.setsid()\nPath({str(ready)!r}).touch()\ntime.sleep(.4)\nPath({str(done)!r}).touch()\n", "grandchild.py")
        argv = self.script(f"import subprocess\nsubprocess.Popen({grandchild!r}, close_fds=True)\n")
        child = self.start("build", argv)
        self.wait_file(ready)
        self.assertIsNone(child.poll())
        self.assertFalse(self.available("i7-heavy.lock"))
        self.assertFalse(self.available("nzbget-rust-benchmark.lock"))
        child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0)
        self.assertTrue(done.exists())
        self.assertTrue(self.available("i7-heavy.lock"))

    @unittest.skipUnless(LINUX, "descendant supervision is Linux-only")
    def test_timeout_and_signals_kill_descendants_before_unlock(self):
        for stop in ("timeout", signal.SIGTERM, signal.SIGINT, signal.SIGKILL):
            with self.subTest(stop=stop):
                ready = self.root / f"ready-{stop}"
                done = self.root / f"done-{stop}"
                home_record = self.root / f"home-{stop}"
                grandchild = self.script(f"from pathlib import Path\nimport os,signal,time\nos.setsid()\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nPath({str(home_record)!r}).write_text(os.environ['HOME'])\nPath({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(2)\nPath({str(done)!r}).touch()\n", f"grand-{stop}.py")
                argv = self.script(f"import subprocess\nsubprocess.Popen({grandchild!r},close_fds=True)\n", f"parent-{stop}.py")
                extra = ("--timeout-seconds", ".15", "--shutdown-grace-seconds", ".1") if stop == "timeout" else ("--shutdown-grace-seconds", ".1")
                child = self.start("build", argv, extra)
                self.wait_file(ready)
                self.assertFalse(self.available("i7-heavy.lock"))
                if stop != "timeout":
                    child.send_signal(stop)
                child.communicate(timeout=5)
                deadline = time.monotonic() + 4
                while not self.available("i7-heavy.lock") and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(self.available("i7-heavy.lock"))
                self.assertTrue(self.available("nzbget-rust-benchmark.lock"))
                self.assertFalse(done.exists())
                self.assertFalse(Path(home_record.read_text()).exists())
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(ready.read_text()), 0)
                if stop == "timeout":
                    self.assertEqual(child.returncode, 124)
                elif stop != signal.SIGKILL:
                    self.assertEqual(child.returncode, 128 + stop)


if __name__ == "__main__":
    unittest.main()
