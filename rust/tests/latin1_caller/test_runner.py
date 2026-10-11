#!/usr/bin/env python3
"""Reproduction contract tests; compiler/timing commands are never executed."""
import contextlib,hashlib,io,json,os,runpy,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REAL_RUN=subprocess.run
REAL_OUTPUT=subprocess.check_output

class RunnerContract(unittest.TestCase):
    def invoke(self, directory, relative=False, abbrev=7):
        directory=Path(directory)
        flags=directory/"configured-build/CMakeFiles/libnzbget.dir/flags.make"
        flags.parent.mkdir(parents=True,exist_ok=True)
        flags.write_text(chr(10).join(["CXX_FLAGS = -O3","CXX_DEFINES = -DNZBGET_USE_RUST","CXX_INCLUDES = -I."])+chr(10))
        output=directory/"results"
        argument="results" if relative else str(output)
        calls=[]
        def check_output(command, **kwargs):
            if command[0]=="git":
                return REAL_RUN(["git","-c",f"core.abbrev={abbrev}",*command[1:]],stdout=subprocess.PIPE,check=True,**kwargs).stdout
            return "test toolchain"
        def run(command, **kwargs):
            calls.append(command)
            if command[0]=="tar":
                return REAL_RUN(command,**kwargs)
            if "c++" in command:
                cwd=Path(kwargs["cwd"])
                position=command.index("c++")
                for value in command[position+1:]:
                    if value.endswith(".cpp") or value.endswith(".o"):
                        path=Path(value)
                        self.assertTrue(path.is_absolute(),"compiler input must survive a cwd change")
                        if value.endswith(".cpp"):
                            self.assertTrue(path.is_file(),"compiler input must name the emitted source")
                target=Path(command[command.index("-o")+1])
                self.assertTrue(target.is_absolute(),"compiler output must survive a cwd change")
                target.write_bytes(b"test binary; not measurement data")
            return subprocess.CompletedProcess(command,0)
        previous=Path.cwd()
        try:
            os.chdir(directory)
            with mock.patch.object(sys,"argv",[
                str(HERE/"run.py"),"--baseline","c2316ef5",
                "--build-dir",str(flags.parents[2]),"--output",argument,
                "--trials","1"]),mock.patch("subprocess.check_output",side_effect=check_output),mock.patch("subprocess.run",side_effect=run),contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(HERE/"run.py"),run_name="__main__")
        finally:
            os.chdir(previous)
        return output,calls

    def test_relative_output_remains_valid_in_compiler_cwd(self):
        with tempfile.TemporaryDirectory(prefix="latin-runner-test-") as directory:
            output,calls=self.invoke(directory,relative=True)
            self.assertTrue((output/"latin-whole-driver.cpp").is_file())
            timer_calls=[c for c in calls if "timer" in c]
            self.assertEqual(len(timer_calls),2)
            for command in timer_calls:
                self.assertTrue(Path(command[-1]).is_absolute())

    def test_runtime_patch_hash_is_independent_of_git_abbreviation(self):
        expected="5c9e5af53f1c108114db050892259d7f6a26cc7df17dee1bdab43893b76532b2"
        for width in (7,40):
            with self.subTest(width=width),tempfile.TemporaryDirectory(prefix="latin-hash-test-") as directory:
                output,_=self.invoke(directory,abbrev=width)
                meta=json.loads((output/"metadata.json").read_text())
                self.assertEqual(meta["runtime_patch_sha256"],expected)

    def test_existing_baseline_is_rejected_without_deleting_user_data(self):
        with tempfile.TemporaryDirectory(prefix="latin-stale-test-") as directory:
            output=Path(directory)/"results";baseline=output/"default"
            baseline.mkdir(parents=True)
            stale=baseline/"rust/build.rs";stale.parent.mkdir();stale.write_text("stale auto-discovered input")
            note=output/"notes.txt";note.write_text("user output")
            with self.assertRaises(SystemExit) as caught:
                self.invoke(directory)
            self.assertEqual(caught.exception.code,2)
            self.assertEqual(stale.read_text(),"stale auto-discovered input")
            self.assertEqual(note.read_text(),"user output")

if __name__=="__main__":
    unittest.main()
