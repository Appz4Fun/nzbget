#!/usr/bin/env python3
"""Linux libc-locale complete-record compatibility gate.

Uses an isolated valid ISO-8859-1 LC_CTYPE with byte0xA0 classified as space,
plus C/C.UTF-8/en_US.UTF-8 controls. It never changes the machine locale or the
production daemon. Run from repo root with --library and a new --artifacts dir.
"""
import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path

LOCALE_SOURCE = 'LC_CTYPE\nupper <U0041>;<U0042>;<U0043>;<U0044>;<U0045>;<U0046>;<U0047>;<U0048>;<U0049>;<U004A>;<U004B>;<U004C>;<U004D>;<U004E>;<U004F>;<U0050>;<U0051>;<U0052>;<U0053>;<U0054>;<U0055>;<U0056>;<U0057>;<U0058>;<U0059>;<U005A>\nlower <U0061>;<U0062>;<U0063>;<U0064>;<U0065>;<U0066>;<U0067>;<U0068>;<U0069>;<U006A>;<U006B>;<U006C>;<U006D>;<U006E>;<U006F>;<U0070>;<U0071>;<U0072>;<U0073>;<U0074>;<U0075>;<U0076>;<U0077>;<U0078>;<U0079>;<U007A>\nalpha <U0041>;<U0042>;<U0043>;<U0044>;<U0045>;<U0046>;<U0047>;<U0048>;<U0049>;<U004A>;<U004B>;<U004C>;<U004D>;<U004E>;<U004F>;<U0050>;<U0051>;<U0052>;<U0053>;<U0054>;<U0055>;<U0056>;<U0057>;<U0058>;<U0059>;<U005A>;<U0061>;<U0062>;<U0063>;<U0064>;<U0065>;<U0066>;<U0067>;<U0068>;<U0069>;<U006A>;<U006B>;<U006C>;<U006D>;<U006E>;<U006F>;<U0070>;<U0071>;<U0072>;<U0073>;<U0074>;<U0075>;<U0076>;<U0077>;<U0078>;<U0079>;<U007A>\ndigit <U0030>..<U0039>\nspace <U0009>..<U000D>;<U0020>;<U00A0>\nblank <U0009>;<U0020>;<U00A0>\ncntrl <U0000>..<U001F>;<U007F>\npunct <U0021>..<U002F>;<U003A>..<U0040>;<U005B>..<U0060>;<U007B>..<U007E>\ngraph <U0021>..<U007E>\nprint <U0020>..<U007E>;<U00A0>\nxdigit <U0030>..<U0039>;<U0041>..<U0046>;<U0061>..<U0066>\ntoupper (<U0061>,<U0041>);(<U0062>,<U0042>);(<U0063>,<U0043>);(<U0064>,<U0044>);(<U0065>,<U0045>);(<U0066>,<U0046>);(<U0067>,<U0047>);(<U0068>,<U0048>);(<U0069>,<U0049>);(<U006A>,<U004A>);(<U006B>,<U004B>);(<U006C>,<U004C>);(<U006D>,<U004D>);(<U006E>,<U004E>);(<U006F>,<U004F>);(<U0070>,<U0050>);(<U0071>,<U0051>);(<U0072>,<U0052>);(<U0073>,<U0053>);(<U0074>,<U0054>);(<U0075>,<U0055>);(<U0076>,<U0056>);(<U0077>,<U0057>);(<U0078>,<U0058>);(<U0079>,<U0059>);(<U007A>,<U005A>)\ntolower (<U0041>,<U0061>);(<U0042>,<U0062>);(<U0043>,<U0063>);(<U0044>,<U0064>);(<U0045>,<U0065>);(<U0046>,<U0066>);(<U0047>,<U0067>);(<U0048>,<U0068>);(<U0049>,<U0069>);(<U004A>,<U006A>);(<U004B>,<U006B>);(<U004C>,<U006C>);(<U004D>,<U006D>);(<U004E>,<U006E>);(<U004F>,<U006F>);(<U0050>,<U0070>);(<U0051>,<U0071>);(<U0052>,<U0072>);(<U0053>,<U0073>);(<U0054>,<U0074>);(<U0055>,<U0075>);(<U0056>,<U0076>);(<U0057>,<U0077>);(<U0058>,<U0078>);(<U0059>,<U0079>);(<U005A>,<U007A>)\nEND LC_CTYPE\n'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("deadpostings_caller", root / "rust/tests/deadpostings_cpp_differential.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = artifacts / "locale.src"
    source.write_text(LOCALE_SOURCE)
    locales = artifacts / "locales"
    locales.mkdir()
    result = module.locked_run(["localedef", "--no-archive", "--quiet", "--force", "-f", "ISO-8859-1", "-i", str(source), str(locales / "nzbget_space")], text=True, capture_output=True)
    (artifacts / "localedef.log").write_text(result.stdout + result.stderr)
    if not (locales / "nzbget_space/LC_CTYPE").exists():
        raise RuntimeError("isolated locale generation failed")
    driver = artifacts / "driver.cpp"
    driver.write_text(module.harness(root))
    exe = artifacts / "driver"
    result = module.locked_run(["g++", "-std=c++17", "-O3", "-DNDEBUG", "-fPIC", str(driver), str(args.library.resolve()), "-ldl", "-lpthread", "-lm", "-o", str(exe)], text=True, capture_output=True)
    (artifacts / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("locale native caller build failed")
    rows = []
    for byte in range(256):
        prefix = bytes([byte])
        for stamp in [b"1800000000", b"-1", b"+1", b"9223372036854775808"]:
            rows.append(prefix + stamp + b"\t1,2,1\t")
        for value in [b"0", b"1", b"+1", b"-1", b"4294967295", b"4294967296", b"-18446744073709551615"]:
            rows.append(b"1800000000\t" + prefix + value + b",2\t")
    rows += [b"\xa01800000000\t1\t", b"1800000000\t\xa01,2\t", b"\xa0-1\t\xa0+1\t"]
    corpus = "".join(row.hex() + "\n" for row in rows)
    (artifacts / "corpus.hex").write_text(corpus)
    summary = []
    for name in ["C", "C.UTF-8", "en_US.UTF-8", "nzbget_space"]:
        env = os.environ.copy()
        if name == "nzbget_space":
            env["LOCPATH"] = str(locales)
        else:
            env.pop("LOCPATH", None)
        env["NZBGET_DEADPOSTINGS_LOCALE"] = name
        result = module.locked_run([str(exe)], input=corpus, env=env, text=True, capture_output=True)
        (artifacts / (name.replace("/", "_") + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode == 77 and name != "nzbget_space":
            summary.append({"locale": name, "available": False})
            continue
        if result.returncode:
            raise RuntimeError("complete-record locale differential failed: " + name)
        summary.append({"locale": name, "cases": len(rows), "complete_outputs_match": True})
    (artifacts / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))

if __name__ == "__main__":
    main()
