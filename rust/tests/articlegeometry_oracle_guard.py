#!/usr/bin/env python3
"""Verify exact historical function-body custody, without compiling anything."""
import pathlib
import subprocess

BASE = "4cf19abdb8f084a384769a15cf57e56acf86f363"
ROOT = pathlib.Path(__file__).resolve().parents[2]
original = subprocess.check_output(["git", "show", BASE + ":daemon/queue/DupeArticleFallback.cpp"], cwd=ROOT, text=True)
driver = (ROOT / "rust/tests/articlegeometry_differential.cpp").read_text()
for declaration in [
    "static int FindArticleIndex(",
    "int64 DupeArticleFallback::ExpectedSegmentOffset(",
    "int64 DupeArticleFallback::ExpectedSegmentEnd(",
    "bool DupeArticleFallback::SegmentAligned(",
    "ArticleInfo* DupeArticleFallback::FirstUntiledArticle(",
]:
    start = original.index(declaration)
    end = original.index("{", start) + 1
    depth = 1
    while depth:
        depth += (original[end] == "{") - (original[end] == "}")
        end += 1
    body = original[start:end]
    assert driver.count(body) == 1, declaration + " differs from historical C++ oracle"
print("PASS exact historical custody for five C++ geometry bodies")
