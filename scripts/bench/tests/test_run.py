"""Lightweight runner tests; Linux process/lock tests use private fake locks."""
import fcntl
import hashlib
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
