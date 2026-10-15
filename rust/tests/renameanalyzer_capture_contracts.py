#!/usr/bin/env python3
"""Fault checks for checked(); extract its AST without importing the build runner.

All children below are doubles. No compiler, target binary or provider is run.
Set NZBGET_CAPTURE_SOURCE to a preserved runner to demonstrate the old failures.
"""
import ast
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


SOURCE = Path(os.environ.get("NZBGET_CAPTURE_SOURCE", Path(__file__).with_name("renameanalyzer_differential.py")))


class Child:
    def __init__(self, stdout, exit_code):
        self.pid = 987654321
        self.stdout = stdout
        self.exit_code = exit_code
        self.returncode = None
        self.reaped = False
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.exit_code = -15

    def kill(self):
        self.terminated = True
        self.exit_code = -9

    def wait(self, timeout=None):
        self.stdout.write(b"retained child bytes\n")
        self.returncode = self.exit_code
        self.reaped = True
        return self.returncode


class CaptureContracts(unittest.TestCase):
    def exercise(self, fault=None, exit_code=0):
        node, = [n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "checked"]
        module = ast.Module(body=[node], type_ignores=[])
        children = []

        def popen(argv, **kwargs):
            child = Child(kwargs["stdout"], exit_code)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="nzbget-capture-contract-") as directory:
            evidence = Path(directory)
            namespace = dict(evidence=evidence, process_number=0, Path=Path, json=json, os=os,
                             sys=sys, time=time, subprocess=types.SimpleNamespace(
                                 Popen=popen, TimeoutExpired=subprocess.TimeoutExpired,
                                 CalledProcessError=subprocess.CalledProcessError,
                                 CompletedProcess=subprocess.CompletedProcess))
            exec(compile(module, str(SOURCE), "exec"), namespace)
            original_write = Path.write_text

            def write(path, data, *args, **kwargs):
                if fault == "process_metadata" and path.name.endswith(".process.json"):
                    raise OSError(errno.ENOSPC, "injected process metadata failure")
                if fault == "all_status" and path.name.endswith("status.json"):
                    raise OSError(errno.ENOSPC, "injected terminal record failure")
                return original_write(path, data, *args, **kwargs)

            def sync(fd):
                if fault == "raw_sync":
                    raise OSError(errno.ENOSPC, "injected raw sync failure")

            error = None
            stderr = io.StringIO()
            with patch.object(Path, "write_text", write), patch.object(os, "fsync", sync), contextlib.redirect_stderr(stderr):
                try:
                    namespace["checked"](["diagnostic-child"])
                except BaseException as caught:
                    error = caught
            status_path = evidence / "process-01.status.json"
            status = json.loads(status_path.read_text()) if status_path.exists() else None
            waited_path = evidence / "process-01.wait-status.json"
            waited = json.loads(waited_path.read_text()) if waited_path.exists() else None
            return children, status, waited, error, stderr.getvalue()

    def test_metadata_failure_reaps_and_stops(self):
        children, status, waited, error, _ = self.exercise("process_metadata")
        self.assertIsNotNone(error)
        self.assertEqual(len(children), 1)
        self.assertTrue(children[0].reaped)
        self.assertTrue(children[0].terminated)
        self.assertTrue(status["reaped"])
        self.assertFalse(status["capture_complete"])
        self.assertEqual(status["exit"], -15)

    def test_raw_sync_failure_retains_known_nonzero_exit(self):
        children, status, waited, error, _ = self.exercise("raw_sync", 7)
        self.assertIsNotNone(error)
        self.assertTrue(children[0].reaped)
        self.assertIsNotNone(status)
        self.assertEqual(status["exit"], 7)
        self.assertTrue(status["reaped"])
        self.assertFalse(status["capture_complete"])
        self.assertEqual(waited["exit"], 7)

    def test_unwritable_terminal_reports_incomplete_known_exit(self):
        children, status, waited, error, stderr = self.exercise("all_status", 7)
        self.assertIsNotNone(error)
        self.assertTrue(children[0].reaped)
        self.assertIsNone(status)
        self.assertIn("INCOMPLETE CHILD CAPTURE ", stderr)
        terminal = json.loads(stderr.split("INCOMPLETE CHILD CAPTURE ", 1)[1])
        self.assertEqual(terminal["exit"], 7)
        self.assertTrue(terminal["reaped"])
        self.assertFalse(terminal["capture_complete"])

    def test_success_keeps_exit_and_reaping(self):
        children, status, waited, error, _ = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(children), 1)
        self.assertTrue(children[0].reaped)
        self.assertFalse(children[0].terminated)
        self.assertEqual(status["exit"], 0)
        self.assertTrue(status["reaped"])


if __name__ == "__main__":
    unittest.main()
