#!/usr/bin/env python3
"""Require exact guarded production function in candidate correctness fixture."""
from pathlib import Path
root=Path(__file__).resolve().parents[2]
source=(root/"daemon/queue/DupeArticleFallback.cpp").read_text()
fixture=(root/"rust/tests/articleidentity_candidate.cpp").read_text()
start=source.index("FileInfo* DupeArticleFallback::MatchDonorFile(");end=source.index("{",start)+1;depth=1
while depth:
 depth+=(source[end]=="{")-(source[end]=="}");end+=1
assert fixture.count(source[start:end])==1,"candidate production matcher differs from fixture"
print("PASS actual guarded production matcher custody")
