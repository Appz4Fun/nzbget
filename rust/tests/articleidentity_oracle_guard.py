#!/usr/bin/env python3
"""Verify matcher oracle bodies against immutable C++ baseline."""
import pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[2]
BASE="4cf19abdb8f084a384769a15cf57e56acf86f363"
source=subprocess.check_output(["git","show",BASE+":daemon/queue/DupeArticleFallback.cpp"],cwd=ROOT,text=True)
fixture=(ROOT/"rust/tests/articleidentity_differential.cpp").read_text()
for signature in ["FileInfo* DupeArticleFallback::MatchDonorFile(","uint64 DupeArticleFallback::ArticleSizeStepsHash(","bool DupeArticleFallback::ArticleSizeStepsMatch(","static int DeclaredParts(","bool DupeArticleFallback::StructureMatches(","bool DupeArticleFallback::SizesMatch("]:
 start=source.index(signature);end=source.index("{",start)+1;depth=1
 while depth:
  depth+=(source[end]=="{")-(source[end]=="}");end+=1
 assert fixture.count(source[start:end])==1,signature+" oracle differs from historical body"
print("PASS six exact historical C++ matcher bodies")
