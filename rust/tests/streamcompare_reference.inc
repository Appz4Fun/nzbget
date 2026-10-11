// Exact method bodies from c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e; only class name changed.
class Reference {
public:
static constexpr int64 MinProbeCompareBytes = 16 * 1024;
static int64 TotalSize(const StreamRangeList&);
static void SubtractCovered(StreamRangeList&, const StreamRange&);
static __attribute__((noinline)) int64 RequiredCompareFloor(int64, const StreamRangeList&, const StreamRangeList&, const std::vector<int>&);
static int64 BaseCompareFloor(int64 presentBytes)
	{
		return std::min<int64>(MinProbeCompareBytes, std::max<int64>(64, presentBytes));
	}
static bool RangesIntersect(const StreamRange& range1, const StreamRange& range2)
	{
		return range1.Offset < range2.End() && range2.Offset < range1.End();
	}
};
int64 Reference::TotalSize(const StreamRangeList& ranges)
{
	int64 total = 0;
	for (const StreamRange& range : ranges)
	{
		total += range.Size;
	}
	return total;
}
void Reference::SubtractCovered(StreamRangeList& ranges, const StreamRange& covered)
{
	StreamRangeList remaining;

	for (const StreamRange& range : ranges)
	{
		if (!RangesIntersect(range, covered))
		{
			remaining.push_back(range);
			continue;
		}
		if (range.Offset < covered.Offset)
		{
			remaining.push_back({range.Offset, covered.Offset - range.Offset});
		}
		if (covered.End() < range.End())
		{
			remaining.push_back({covered.End(), range.End() - covered.End()});
		}
	}

	ranges = std::move(remaining);
}
int64 Reference::RequiredCompareFloor(int64 decodedFileSize, const StreamRangeList& holes,
	const StreamRangeList& donorRanges, const std::vector<int>& probeParts)
{
	int64 base = BaseCompareFloor(decodedFileSize - TotalSize(holes));

	int64 achievable = 0;
	for (int partIndex : probeParts)
	{
		StreamRangeList presentPart = { donorRanges[partIndex] };
		for (const StreamRange& hole : holes)
		{
			SubtractCovered(presentPart, hole);
		}
		achievable += TotalSize(presentPart);
	}

	return achievable >= 64 ? std::min(base, achievable) : base;
}
