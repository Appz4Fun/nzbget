// Equally improved all-C++ counterfactual, mechanically copied from the
// production helpers and caller. Only class name and Rust dispatch differ.
// Reference supplies the exact original BaseCompareFloor/TotalSize/intersect.
class ImprovedControl : public Reference {
public:
    [[gnu::noinline]] static int64 RequiredCompareFloor(int64 decodedFileSize, const StreamRangeList& holes,
        const StreamRangeList& donorRanges, const std::vector<int>& probeParts);
private:
	// Owned scratch belongs to exceptional geometry, not the ordinary caller.
	[[gnu::noinline]] static int64 RequiredCompareFloorExact(const StreamRangeList& holes,
		const StreamRangeList& donorRanges, const std::vector<int>& probeParts);
	[[gnu::noinline]] static int64 RequiredCompareFloorUnordered(const StreamRangeList& holes,
		const StreamRangeList& donorRanges, const std::vector<int>& probeParts);
	[[gnu::always_inline]] static inline int64 RequiredCompareFloorAvailable(const StreamRange* ranges,
		size_t count, const StreamRangeList& donorRanges, const std::vector<int>& probeParts);
};

inline int64 ImprovedControl::RequiredCompareFloorAvailable(const StreamRange* ranges, size_t count,
	const StreamRangeList& donorRanges, const std::vector<int>& probeParts)
{
	int64 achievable = 0;
	const StreamRange* end = ranges + count;
	for (int partIndex : probeParts)
	{
		const auto& donor = donorRanges[partIndex];
		int64 bytes = donor.Size;
		auto start = count <= 8 ? ranges : std::lower_bound(ranges, end, donor.Offset,
			[](const auto& hole, int64 offset) { return hole.End() <= offset; });
		for (auto hole = start; hole != end && hole->Offset < donor.End(); ++hole)
		{
			if (hole->End() <= donor.Offset) continue;
			bytes -= std::max<int64>(0, std::min(donor.End(), hole->End()) - std::max(donor.Offset, hole->Offset));
		}
		achievable += bytes;
	}
	return achievable;
}

int64 ImprovedControl::RequiredCompareFloorExact(const StreamRangeList& holes,
	const StreamRangeList& donorRanges, const std::vector<int>& probeParts)
{
	int64 achievable = 0;
	StreamRangeList present, remaining;
	for (int partIndex : probeParts)
	{
		// Reset contents while retaining both capacities across ordered probes.
		present.clear();
		present.push_back(donorRanges[partIndex]);
		for (const auto& hole : holes)
		{
			remaining.clear();
			for (const auto& range : present)
			{
				if (!RangesIntersect(range, hole)) remaining.push_back(range);
				else
				{
					if (range.Offset < hole.Offset) remaining.push_back({range.Offset, hole.Offset - range.Offset});
					if (hole.End() < range.End()) remaining.push_back({hole.End(), range.End() - hole.End()});
				}
			}
			present.swap(remaining);
		}
		achievable += TotalSize(present);
	}
	return achievable;
}

int64 ImprovedControl::RequiredCompareFloorUnordered(const StreamRangeList& holes,
	const StreamRangeList& donorRanges, const std::vector<int>& probeParts)
{
	// Eight is the existing linear-scan limit. Every scratch element is
	// constructed; compaction writes only within the populated prefix.
	std::array<StreamRange, 8> small{};
	StreamRangeList large;
	StreamRange* ranges;
	if (holes.size() <= small.size())
	{
		std::copy(holes.begin(), holes.end(), small.begin());
		ranges = small.data();
	}
	else
	{
		large = holes;
		ranges = large.data();
	}
	std::sort(ranges, ranges + holes.size(), [](auto& left, auto& right) { return left.Offset < right.Offset; });
	size_t count = 0;
	for (size_t i = 0; i < holes.size(); ++i)
	{
		auto hole = ranges[i];
		if (count && hole.Offset <= ranges[count - 1].End())
		{
			auto& last = ranges[count - 1];
			last.Size = std::max(last.End(), hole.End()) - last.Offset;
		}
		else ranges[count++] = hole;
	}
	return RequiredCompareFloorAvailable(ranges, count, donorRanges, probeParts);
}
int64 ImprovedControl::RequiredCompareFloor(int64 decodedFileSize, const StreamRangeList& holes,
	const StreamRangeList& donorRanges, const std::vector<int>& probeParts)
{
	static_assert(MinProbeCompareBytes == 16 * 1024, "Rust stream compare floor cap");
	static_assert(std::is_standard_layout<StreamRange>::value, "StreamRange C ABI layout");
	static_assert(sizeof(StreamRange) == sizeof(NzbgetRsStreamCompareRange), "StreamRange C ABI size");
	static_assert(alignof(StreamRange) == alignof(NzbgetRsStreamCompareRange), "StreamRange C ABI alignment");
	static_assert(offsetof(StreamRange, Offset) == offsetof(NzbgetRsStreamCompareRange, offset), "StreamRange offset");
	static_assert(offsetof(StreamRange, Size) == offsetof(NzbgetRsStreamCompareRange, size), "StreamRange size");
	static_assert(sizeof(int) == sizeof(int32_t), "Probe index C ABI size");
	// No probes need only the original base calculation; avoid FFI overhead.
	if (probeParts.empty())
	{
		return BaseCompareFloor(decodedFileSize - TotalSize(holes));
	}
	// No holes need only the raw donor-size sum, including reversed sizes.
	if (holes.empty())
	{
		int64 achievable = 0;
		for (int partIndex : probeParts)
		{
			if ((unsigned)partIndex >= donorRanges.size()) std::abort();
			achievable += donorRanges[partIndex].Size;
		}
		int64 base = BaseCompareFloor(decodedFileSize);
		return achievable >= 64 ? std::min(base, achievable) : base;
	}
	// Classification must not evaluate overflowing signed endpoints which the
	// original subtraction can leave unused after an earlier hole consumes it.
	auto wrappedEnd = [](const StreamRange& range)
	{
		return std::bit_cast<int64>((uint64_t)range.Offset + (uint64_t)range.Size);
	};
	int64 sum = 0, previous = std::numeric_limits<int64>::min();
	bool ordered = true, positive = true;
	for (const auto& hole : holes)
	{
		sum += hole.Size;
		int64 end = wrappedEnd(hole);
		positive &= hole.Size >= 0;
		positive &= end >= hole.Offset;
		ordered &= hole.Offset >= previous;
		previous = end;
	}
	int64 base = BaseCompareFloor(decodedFileSize - sum);
	for (int partIndex : probeParts)
	{
		if (partIndex < 0 || (size_t)partIndex >= donorRanges.size()) std::abort();
		positive &= donorRanges[partIndex].Size >= 0;
		positive &= wrappedEnd(donorRanges[partIndex]) >= donorRanges[partIndex].Offset;
	}
	int64 achievable = !positive ? RequiredCompareFloorExact(holes, donorRanges, probeParts) :
		!ordered ? RequiredCompareFloorUnordered(holes, donorRanges, probeParts) :
		RequiredCompareFloorAvailable(holes.data(), holes.size(), donorRanges, probeParts);
	return achievable >= 64 ? std::min(base, achievable) : base;
}
