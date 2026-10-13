#!/usr/bin/env python3
"""Keep exact historical pin/lead bodies in the correctness fixture."""
import pathlib
import subprocess
ROOT=pathlib.Path(__file__).resolve().parents[2]
BASE="4cf19abdb8f084a384769a15cf57e56acf86f363"
original=subprocess.check_output(["git","show",BASE+":daemon/queue/DupeArticleFallback.cpp"],cwd=ROOT,text=True)
fixture=(ROOT/"rust/tests/articlefallback_differential.cpp").read_text()
for declaration in ["bool DupeArticleFallback::RegisterLeadFailure(","void DupeArticleFallback::RegisterLeadSuccess(","void DupeArticleFallback::FinishPin(","std::vector<CString> DupeArticleFallback::OrderSources("]:
 start=original.index(declaration);end=original.index("{",start)+1;depth=1
 while depth:
  depth+=(original[end]=="{")-(original[end]=="}");end+=1
 assert fixture.count(original[start:end])==1,declaration+" historical-body mismatch"
print("PASS exact historical custody for four C++ lead/pin bodies")

start=original.index("\twhile (round < (int)sources.size()")
end=original.index("\n\tif (round >= (int)sources.size())",start)
assert fixture.count(original[start:end])==1,"blocked-source historical loop mismatch"
print("PASS historical blocked-source advancement loop")
