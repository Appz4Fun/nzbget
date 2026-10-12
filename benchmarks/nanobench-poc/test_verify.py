"""Bounded regular-file/FIFO regressions; no benchmark or bundle execution."""
import json
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import hashlib
import io
import shutil
import zipfile
import signal
import time
from contextlib import contextmanager
from unittest import mock
import verify as pilot


@contextmanager
def ownership_mask():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def capture_command(command, root, payload_timeout=3, cleanup_timeout=3):
    """Single-threaded POSIX fixture custody, not a benchmark launcher.

    Popen construction itself has no local deadline: callers must externally
    bound the complete suite. A missing returned handle leaves custody UNKNOWN.
    """
    (root / "command.json").write_text(json.dumps({
        "argv": command, "payload_timeout": payload_timeout, "cleanup_timeout": cleanup_timeout,
        "launch_local_timeout": None, "external_suite_bound_required": True,
    }))
    child = None
    returncode = None
    status = "incomplete"
    with (root / "stdout").open("x") as out, (root / "stderr").open("x") as err:
        try:
            with ownership_mask():
                child = subprocess.Popen(command, stdout=out, stderr=err)
            returncode = child.wait(timeout=payload_timeout)
            status = "completed"
        except subprocess.TimeoutExpired:
            status = "timeout"
            raise
        except KeyboardInterrupt:
            status = "interrupted"
            raise
        except OSError:
            status = "launch-failure" if child is None else "wait-failure"
            raise
        finally:
            # Real secondary SIGINT remains pending until child custody and the
            # terminal receipt are settled; restore exactly the prior mask.
            with ownership_mask():
                reaped = status == "completed"
                cleanup_error = None
                if child is not None and not reaped:
                    deadline = time.monotonic() + cleanup_timeout
                    try:
                        child.kill()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(command, cleanup_timeout)
                        returncode = child.wait(timeout=remaining)
                        reaped = True
                    except BaseException as error:
                        cleanup_error = type(error).__name__
                        returncode = None
                receipt = {
                    "exit": returncode, "status": "cleanup-incomplete" if cleanup_error else status,
                    "primary_status": status,
                    "ownership": "owned" if child is not None else "UNKNOWN",
                    "reaped": reaped if child is not None else "UNKNOWN",
                    "cleanup_error": cleanup_error,
                    "deferred_sigint": signal.SIGINT in signal.sigpending(),
                }
                (root / "completion.json").write_text(json.dumps(receipt))
                if cleanup_error is not None:
                    raise RuntimeError("Incomplete child cleanup; retained evidence: " + root.name)
    return returncode


@unittest.skipUnless(all(hasattr(os, flag) for flag in ["O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"]),
                     "Safe no-follow/nonblocking file admission unavailable")
class FileAdmissionTests(unittest.TestCase):
    def run_probe(self, mode):
        verifier = Path(__file__).with_name("verify.py").resolve()
        code = r'''
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("pilot_verify", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path(sys.argv[2])
path = module.ROOT / "artifact"
mode = sys.argv[3]
if mode == "fifo":
    os.mkfifo(path)
else:
    path.write_bytes(b"fixture")
directory_context = module.packet_directory()
directory_fd = directory_context.__enter__()
if mode == "replacement":
    original_open = module.os.open
    def swap(target, flags, **kwargs):
        path.unlink()
        os.mkfifo(path)
        if not flags & os.O_NONBLOCK:
            raise AssertionError("nonblocking admission flag absent")
        return original_open(target, flags, **kwargs)
    module.os.open = swap
if mode in {"regular-replacement", "fallback-symlink", "same-inode-symlink"}:
    original_open = module.os.open
    replacement = module.ROOT / "replacement"
    replacement.write_bytes(b"different")
    if mode in {"fallback-symlink", "same-inode-symlink"}:
        if hasattr(module.os, "O_NOFOLLOW"):
            del module.os.O_NOFOLLOW
        link = module.ROOT / "replacement-link"
        link.symlink_to((module.ROOT / "original-away").resolve()
                        if mode == "same-inode-symlink" else replacement.resolve())
    def swap_regular(target, flags, **kwargs):
        if mode == "same-inode-symlink":
            os.replace(path, module.ROOT / "original-away")
        os.replace(replacement if mode == "regular-replacement" else link, path)
        return original_open(target, flags, **kwargs)
    module.os.open = swap_regular
try:
    result = module.read("artifact", directory_fd)
except ValueError:
    if mode == "regular":
        raise
    print("rejected")
except OSError:
    if mode not in {"fallback-symlink", "same-inode-symlink"}:
        raise
    print("rejected")
else:
    if mode != "regular" or result != b"fixture":
        raise AssertionError("incorrect admission")
    print("accepted")
finally:
    directory_context.__exit__(None, None, None)
'''
        root = Path(tempfile.mkdtemp(prefix="pilot-admission-"))
        self.last_probe_root = root
        command = [sys.executable, "-c", code, str(verifier), str(root), mode]
        returncode = capture_command(command, root)
        self.assertEqual(returncode, 0,
                         (root / "stderr").read_text() + " Evidence: " + root.name)
        self.assertEqual((root / "stdout").read_text().strip(),
                         "accepted" if mode == "regular" else "rejected")

    def test_regular_control(self):
        self.run_probe("regular")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO filesystem API unavailable")
    def test_fifo_rejected_without_blocking(self):
        self.run_probe("fifo")

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
                         "POSIX nonblocking FIFO API unavailable")
    def test_replacement_fifo_rejected_without_blocking(self):
        self.run_probe("replacement")

    def test_regular_replacement_rejected(self):
        self.run_probe("regular-replacement")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "symlink"),
                         "POSIX symlink fallback simulation unavailable")
    def test_symlink_replacement_without_nofollow_rejected(self):
        self.run_probe("fallback-symlink")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "symlink"),
                         "POSIX symlink fallback simulation unavailable")
    def test_same_inode_symlink_without_nofollow_rejected(self):
        self.run_probe("same-inode-symlink")

    def test_launch_failure_has_terminal_receipt(self):
        with mock.patch.object(subprocess, "Popen", side_effect=OSError("synthetic launch failure")):
            with self.assertRaises(OSError):
                self.run_probe("regular")
        receipt = json.loads((self.last_probe_root / "completion.json").read_text())
        self.assertEqual(receipt["status"], "launch-failure")
        self.assertIsNone(receipt["exit"])
        self.assertTrue((self.last_probe_root / "stdout").exists())
        self.assertTrue((self.last_probe_root / "stderr").exists())

    def test_interrupted_probe_is_reaped_before_receipt_and_unwind(self):
        child = mock.Mock()
        child.wait.side_effect = [KeyboardInterrupt(), -9]
        with mock.patch.object(subprocess, "Popen", return_value=child):
            with self.assertRaises(KeyboardInterrupt):
                self.run_probe("regular")
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)
        receipt = json.loads((self.last_probe_root / "completion.json").read_text())
        self.assertEqual(receipt["status"], "interrupted")
        self.assertEqual(receipt["ownership"], "owned")
        self.assertTrue(receipt["reaped"])
        self.assertEqual(receipt["exit"], -9)

    def test_interrupted_launch_has_no_invented_child_exit(self):
        with mock.patch.object(subprocess, "Popen", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_probe("regular")
        receipt = json.loads((self.last_probe_root / "completion.json").read_text())
        self.assertEqual(receipt["status"], "interrupted")
        self.assertEqual(receipt["ownership"], "UNKNOWN")
        self.assertEqual(receipt["reaped"], "UNKNOWN")
        self.assertIsNone(receipt["exit"])

    def test_secondary_sigint_is_deferred_until_reap_and_receipt(self):
        root = Path(tempfile.mkdtemp(prefix="pilot-secondary-signal-"))
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        child = mock.Mock()
        child.wait.side_effect = [subprocess.TimeoutExpired(["fixture"], 3), -9]
        child.kill.side_effect = lambda: os.kill(os.getpid(), signal.SIGINT)
        with mock.patch.object(subprocess, "Popen", return_value=child):
            with self.assertRaises(KeyboardInterrupt):
                capture_command(["fixture"], root)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
        receipt = json.loads((root / "completion.json").read_text())
        self.assertTrue(receipt["reaped"])
        self.assertTrue(receipt["deferred_sigint"])
        self.assertEqual(receipt["exit"], -9)

    def test_queued_launch_sigint_preserves_acquired_child_ownership(self):
        root = Path(tempfile.mkdtemp(prefix="pilot-launch-signal-"))
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        child = mock.Mock()
        child.wait.return_value = -9
        def launched(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGINT)
            return child
        with mock.patch.object(subprocess, "Popen", side_effect=launched):
            with self.assertRaises(KeyboardInterrupt):
                capture_command(["fixture"], root)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
        child.kill.assert_called_once()
        receipt = json.loads((root / "completion.json").read_text())
        self.assertEqual(receipt["ownership"], "owned")
        self.assertTrue(receipt["reaped"])
        self.assertEqual(receipt["exit"], -9)

    def test_cleanup_failure_is_incomplete_not_pass(self):
        for failure in [OSError("synthetic kill failure"), KeyboardInterrupt()]:
            root = Path(tempfile.mkdtemp(prefix="pilot-cleanup-failure-"))
            child = mock.Mock()
            child.wait.side_effect = subprocess.TimeoutExpired(["fixture"], 3)
            child.kill.side_effect = failure
            with mock.patch.object(subprocess, "Popen", return_value=child):
                with self.assertRaises(RuntimeError):
                    capture_command(["fixture"], root)
            receipt = json.loads((root / "completion.json").read_text())
            self.assertEqual(receipt["status"], "cleanup-incomplete")
            self.assertEqual(receipt["ownership"], "owned")
            self.assertFalse(receipt["reaped"])
            self.assertIsNone(receipt["exit"])

    def test_cleanup_wait_has_a_monotonic_bound(self):
        root = Path(tempfile.mkdtemp(prefix="pilot-cleanup-bound-"))
        child = mock.Mock()
        child.wait.side_effect = [subprocess.TimeoutExpired(["fixture"], 3), -9]
        with mock.patch.object(subprocess, "Popen", return_value=child), \
                mock.patch.object(time, "monotonic", side_effect=[10.0, 10.25]):
            with self.assertRaises(subprocess.TimeoutExpired):
                capture_command(["fixture"], root, cleanup_timeout=1)
        self.assertEqual(child.wait.call_args_list[-1].kwargs["timeout"], 0.75)


class RecordValidationTests(unittest.TestCase):
    def test_record_schema_rejects_bool_and_noninteger_ids(self):
        record = json.loads(Path(__file__).with_name("results.json").read_text())["records"][0]
        pilot.check_record_schema(record)
        for value in [True, 1.0, "1", 0, 4]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot.check_record_schema({**record, "trial": value})
        for field, value in [("round", False), ("iterations", True), ("ns", True)]:
            changed = copy.deepcopy(record)
            changed["entries"][0]["samples"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                pilot.check_record_schema(changed)
        with self.assertRaises(ValueError):
            pilot.check_case([True, 65531, 0, "cross"])

    def test_failed_stderr_is_not_a_completed_comparison(self):
        record = json.loads(Path(__file__).with_name("results.json").read_text())["records"][0]
        with self.assertRaises(ValueError):
            pilot.check_record_schema({**record, "stderr": "FAIL synthetic child failure"})

    def test_unknown_and_duplicate_result_methods(self):
        pilot.check_result_method("original", {})
        with self.assertRaises(ValueError):
            pilot.check_result_method("bogus", {})
        with self.assertRaises(ValueError):
            pilot.check_result_method("original", {"original": []})

    def test_release_and_dropped_inventory_rejected(self):
        pilot.check_export_status({"qualification": "HOLD", "production_status": "HOLD unchanged"})
        with self.assertRaises(ValueError):
            pilot.check_export_status({"qualification": "HOLD", "production_status": "RELEASED"})
        pilot.check_original_inventory({"sha256": dict.fromkeys(pilot.ORIGINAL_FILES)})
        with self.assertRaises(ValueError):
            pilot.check_original_inventory({"sha256": dict.fromkeys(
                pilot.ORIGINAL_FILES - {"original-recorder.py"})})

    def test_ambiguous_json_and_nonfinite_constants_rejected(self):
        with self.assertRaises(ValueError):
            pilot.load_json('{"qualification":"RELEASED","qualification":"HOLD"}')
        with self.assertRaises(ValueError):
            pilot.load_json('{"value":Infinity}')

    def test_fixed_publication_metadata_cannot_claim_a_new_run(self):
        export = json.loads(Path(__file__).with_name("export-manifest.json").read_text())
        pilot.check_publication_metadata(export)
        for change in [{"new_timing_runs": 1}, {"new_timing_runs": False},
                       {"original_attempt": "002"}, {"runtime_release_approved": True}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                pilot.check_publication_metadata({**export, **change})

    def test_result_fields_reject_invalid_numbers(self):
        good = dict(median_ns=2.0, speed_ratio=1.0, speed_low=0.9,
                    speed_high=1.1, tied_rounds=0)
        for field in ["median_ns", "speed_ratio", "speed_low", "speed_high"]:
            for value in [float("inf"), float("nan"), 0.0, -1.0]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        pilot.check_result({**good, field: value})

    def test_result_interval_order(self):
        with self.assertRaises(ValueError):
            pilot.check_result(dict(median_ns=2, speed_ratio=1,
                                    speed_low=2, speed_high=1, tied_rounds=0))

    def test_point_estimate_outside_pilot_interval_rejected(self):
        for ratio in [0.8, 1.2]:
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                pilot.check_result(dict(median_ns=2, speed_ratio=ratio,
                                        speed_low=0.9, speed_high=1.1, tied_rounds=0))
        pilot.check_result(dict(median_ns=2, speed_ratio=1,
                                speed_low=1, speed_high=1, tied_rounds=52))

    def test_scenario_boundary_bypass_rejected(self):
        tiny = [{"scratch_allocations": 0} for _ in range(4)]
        normal = [{"scratch_allocations": n} for n in [0, 1, 1, 0]]
        pilot.check_boundary(17, tiny, [0, 0, 0, 0], 104)
        pilot.check_boundary(65531, normal, [106, 106, 0, 0], 104)
        with self.assertRaises(ValueError):
            pilot.check_boundary(65531, tiny, [0, 0, 0, 0], 104)
        with self.assertRaises(ValueError):
            pilot.check_boundary(65531, normal, [0, 0, 0, 0], 104)
        with self.assertRaises(ValueError):
            pilot.check_boundary(65531, normal, [2, 2, 0, 0], 104)


@unittest.skipUnless(all(hasattr(os, flag) for flag in ["O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"])
                     and hasattr(os, "symlink"), "Directory-relative POSIX fixture unavailable")
class DirectoryAdmissionTests(unittest.TestCase):
    def test_bound_directory_cannot_be_redirected_after_open(self):
        with tempfile.TemporaryDirectory(prefix="pilot-directory-") as directory:
            base = Path(directory)
            packet = base / "packet"
            packet.mkdir()
            (packet / "artifact").write_bytes(b"original")
            replacement = base / "replacement"
            replacement.mkdir()
            (replacement / "artifact").write_bytes(b"redirected")
            with mock.patch.object(pilot, "ROOT", packet.resolve()):
                with pilot.packet_directory() as fd:
                    packet.rename(base / "original-away")
                    packet.symlink_to(replacement.resolve(), target_is_directory=True)
                    self.assertEqual(pilot.read("artifact", fd), b"original")
                with self.assertRaises(ValueError):
                    pilot.read("artifact")


@unittest.skipUnless(all(hasattr(os, flag) for flag in ["O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"]),
                     "Safe whole-packet verifier platform unavailable")
class WholePacketTests(unittest.TestCase):
    def test_normal_entry_point_and_repacked_negative_cases(self):
        source = Path(__file__).resolve().parent
        for mutation in ["intact", "readme", "index", "historical-status-count",
                         "snapshot-COPYING", "snapshot-context", "release", "prospective-plan"]:
            with self.subTest(mutation=mutation):
                packet = Path(tempfile.mkdtemp(prefix="pilot-whole-packet-"))
                for item in source.iterdir():
                    if item.is_file():
                        shutil.copyfile(item, packet / item.name)
                export_path = packet / "export-manifest.json"
                export = json.loads(export_path.read_text())
                if mutation in {"readme", "index"}:
                    name = "README.md" if mutation == "readme" else "index.html"
                    with (packet / name).open("a") as stream:
                        stream.write("\nSynthetic contradictory release claim\n")
                elif mutation == "historical-status-count":
                    path = packet / "original-evidence-manifest.json"
                    original = json.loads(path.read_text())
                    original.update(production_status="RELEASED", timed_samples=1)
                    path.write_text(json.dumps(original))
                elif mutation.startswith("snapshot-"):
                    name = "COPYING" if mutation == "snapshot-COPYING" else "rust/tests/cryptoread_compare.py"
                    archive_path = packet / "source-snapshot.zip"
                    with zipfile.ZipFile(archive_path) as archive:
                        members = {item: archive.read(item) for item in archive.namelist()}
                    members[name] += b"\nSynthetic altered recovered source\n"
                    output = io.BytesIO()
                    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        for item, data in members.items():
                            archive.writestr(item, data)
                    archive_path.write_bytes(output.getvalue())
                    manifest_path = packet / "source-snapshot-manifest.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest["sha256"][name] = hashlib.sha256(members[name]).hexdigest()
                    manifest["archive_sha256"] = hashlib.sha256(output.getvalue()).hexdigest()
                    manifest_path.write_text(json.dumps(manifest))
                elif mutation == "release":
                    export["production_status"] = "RELEASED"
                elif mutation == "prospective-plan":
                    export["prospective_plan_custody"] = "verified before execution"
                export["sha256"] = {name: hashlib.sha256((packet / name).read_bytes()).hexdigest()
                                     for name in export["sha256"]}
                export_path.write_text(json.dumps(export))
                command = [sys.executable, str(packet / "verify.py")]
                (packet / "fixture.json").write_text(json.dumps({"synthetic_mutation": mutation}))
                returncode = capture_command(command, packet, payload_timeout=5)
                self.assertEqual(returncode, 0 if mutation == "intact" else 1,
                                 (packet / "stderr").read_text() + " Evidence: " + packet.name)
                if mutation == "intact":
                    self.assertIn("QUALIFICATION HOLD", (packet / "stdout").read_text())


if __name__ == "__main__":
    unittest.main()
