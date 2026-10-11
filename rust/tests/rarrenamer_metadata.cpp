// Included by rarrenamer_differential.py after instrumented copies of all
// three implementations. No files are touched: the exact callback trace is
// compared, including early collision exits and exceptions.
struct FileSpec
{
	std::string name = "movie.mkv";
	int64 size = 100;
	bool before = false, after = false;
};
struct VolumeSpec
{
	std::string name = "/dir/obfuscated";
	uint32 number = 0;
	bool next = false, multi = true, naming = true;
	int version = 5;
	std::vector<FileSpec> files = {FileSpec{}};
};

template<class R> static std::vector<std::string> probe(const std::vector<VolumeSpec>& specs, int collisions, int fail, int failAt)
{
	probeTrace.clear();
	probeChecks = 0;
	probeCollisions = collisions;
	probeFail = fail;
	probeFailAt = failAt;
	probeFailureCalls = 0;
	R renamer;
	for (const auto& spec : specs)
	{
		RarVolume v(spec.name.c_str());
		v.m_volumeNo = spec.number;
		v.m_hasNextVolume = spec.next;
		v.m_multiVolume = spec.multi;
		v.m_newNaming = spec.naming;
		v.m_version = spec.version;
		for (const auto& f : spec.files)
		{
			RarFile file;
			file.m_filename = f.name;
			file.m_size = f.size;
			file.m_splitBefore = f.before;
			file.m_splitAfter = f.after;
			v.m_files.push_back(std::move(file));
		}
		renamer.m_volumes.push_back(std::move(v));
	}
	try { renamer.RenameFiles("/dir"); }
	catch (const std::runtime_error&) { probeTrace.push_back("exception"); }
	return probeTrace;
}

static void compare(const std::vector<VolumeSpec>& specs, int collisions = 0, int fail = 0, int failAt = 1)
{
	auto old = probe<ProbeOldRarRenamer>(specs, collisions, fail, failAt);
	auto rust = probe<ProbeRustRarRenamer>(specs, collisions, fail, failAt);
	auto fallback = probe<ProbeFallbackRarRenamer>(specs, collisions, fail, failAt);
	if (old != rust || old != fallback)
	{
		for (const auto& spec : specs) fprintf(stderr, "input: %s (#%u)\n", spec.name.c_str(), spec.number);
		for (const auto& s : old) fprintf(stderr, "old: %s\n", s.c_str());
		for (const auto& s : rust) fprintf(stderr, "rust: %s\n", s.c_str());
		for (const auto& s : fallback) fprintf(stderr, "fallback: %s\n", s.c_str());
		abort();
	}
}

static void cases()
{
	// Complete and incomplete sets, ambiguity, name preference and first largest
	// tie-breaking. Later sets may reuse the same volumes, even after a rename.
	VolumeSpec first, second, decoy, twin;
	first.next = true;
	first.name = "/dir/a.part01.rar";
	first.files[0].after = true;
	second.number = 1;
	second.name = "/dir/a.part02.rar";
	second.files[0].before = true;
	decoy = second;
	decoy.name = "/dir/b.part02.rar";
	twin = first;
	twin.name = "/dir/z.part01.rar";
	for (int mode = 0; mode < 8; ++mode)
	{
		auto a = first, b = second, c = decoy, d = twin;
		if (mode & 1) a.name = "/dir/b.part01.rar";
		if (mode & 2) c.version = 3;
		if (mode & 4) b.files[0].name = std::string("movie.mkv\0suffix", 16);
		for (int collisions = 0; collisions < 5; ++collisions)
		{
			compare({a, c, b, d}, collisions);
			compare({d, b, c, a}, collisions);
		}
	}
	compare({first});
	compare({second});
	compare({});
	first.files.clear();
	compare({first, second});
	first = VolumeSpec{};
	first.files.push_back({"equal.avi", 100, false, false});
	compare({first}, 3);
	first.files[1].size++;
	compare({first}, 3);
	first.files[0].size = INT64_MIN;
	first.files[1].size = INT64_MAX;
	compare({first});

	// C string comparisons, arbitrary byte names, extension stripping after
	// the 1023-byte BString cut, and truncation of collision suffixes.
	for (size_t n : {0, 1, 1018, 1019, 1020, 1022, 1023, 1024, 1100})
	{
		first = VolumeSpec{};
		first.files[0].name = std::string(n, 'a') + ".mkv";
		compare({first}, 3);
		first.files[0].name = std::string(n, 'a') + ".long";
		compare({first}, 3);
	}
	for (const std::string& name : {std::string("x\\movie.mkv"), std::string("x/movie.mkv"),
		std::string("x\0wrong.mkv", 11), std::string("\xff\x80.mkv"), std::string("100%.mkv")})
	{
		first = VolumeSpec{};
		first.files[0].name = name;
		compare({first}, 2);
	}

	// The part number BString uses the *format* constructor, which copies
	// digits AND .rar, then cuts to 1023 bytes. It does not use the capture len.
	for (size_t digits : {1, 2, 4, 10, 1020, 1023, 1024, 1100})
	{
		first = VolumeSpec{};
		first.name = "/dir/a.part" + std::string(digits - 1, '0') + "1.rar";
		compare({first});
	}
	for (const char* name : {"a.part1.rar", "a.PART1.RAR", "apart1.rar", "part1.rar",
		"a.part1.rar\n", "a\n.part1.rar", "a.part4294967297.rar", "a.part9999999999999999999999.rar"})
	{
		first = VolumeSpec{};
		first.name = std::string("/dir/") + name;
		compare({first});
	}
	// Old naming, mixed naming, and self destinations skipped before stat.
	first = VolumeSpec{};
	first.naming = false;
	first.name = "/dir/movie.rar";
	compare({first}, 2);
	first.next = true;
	first.files[0].after = true;
	second.naming = false;
	second.name = "/dir/obfuscated2";
	compare({first, second}, 2);
	second.naming = true;
	compare({first, second}, 2);

	// Exceptions must return through the Rust frame before being rethrown.
	first = VolumeSpec{};
	compare({first}, 0, 1); // file-exists exception
	compare({first}, 0, 2); // rename exception
	compare({first}, 0, 3); // regex exception
	first.next = true;
	first.name = "/dir/a.part01.rar";
	second = first;
	second.number = 1;
	second.next = false;
	second.name = "/dir/b.part02.rar";
	twin = first;
	twin.name = "/dir/c.part01.rar";
	for (int fail = 1; fail <= 3; ++fail)
		for (int at = 1; at <= 4; ++at)
			compare({first, second, twin}, 2, fail, at);

	// Name matching around the bounded temporary's cutoff, including NULs.
	for (size_t n : {0, 1, 1010, 1018, 1020, 1023, 1024, 1100})
	{
		first = VolumeSpec{};
		first.name = "/dir/" + std::string(n, 'a') + ".part01.rar";
		first.next = true;
		second = first;
		second.name = "/dir/" + std::string(n, 'a') + ".part02.rar";
		second.number = 1;
		second.next = false;
		decoy = second;
		decoy.name[5] = 'b';
		compare({first, decoy, second}, 2);
	}
	puts("synthetic metadata, callback order and exception cases agree");
}

static void randomCases()
{
	// Vary metadata independently of the finite archive fixtures, while keeping
	// volume numbers small so every chain terminates without wrapping.
	uint32 state = 0x71234567;
	auto pick = [&](uint32 n) {
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		return state % n;
	};
	const std::string names[] = {"a.part01.rar", "a.part02.rar", "a.part03.rar",
		"b.part01.rar", "b.part02.rar", "a.rar", "a.r00", "a.r01", "A.PART01.RAR",
		"a.part001.rar", "apart1.rar", "a\n.part1.rar", "hidden", "a.", ".rar"};
	const std::string files[] = {"movie.mkv", "equal.avi", "dir\\movie.mkv",
		std::string("movie.mkv\0suffix", 16), std::string("\xff.mkv"), "100%.mkv"};
	for (int round = 0; round < 1000; ++round)
	{
		std::vector<VolumeSpec> specs;
		const uint32 count = 1 + pick(10);
		for (uint32 i = 0; i < count; ++i)
		{
			VolumeSpec v;
			v.name = "/dir/" + names[pick(sizeof names / sizeof *names)];
			v.number = pick(4);
			v.next = pick(2);
			v.multi = pick(4) != 0;
			v.naming = pick(2);
			v.version = pick(4) ? 5 : 3;
			v.files.clear();
			const uint32 fileCount = pick(4);
			for (uint32 j = 0; j < fileCount; ++j)
				v.files.push_back({files[pick(sizeof files / sizeof *files)],
					(int64)pick(4) - 1, pick(4) == 0, pick(4) == 0});
			specs.push_back(std::move(v));
		}
		compare(specs, pick(5));
	}
	puts("1000 randomized metadata cases agree");
}

int main()
{
	for (const char* locale : {"C", "C.UTF-8"})
	{
		if (!setlocale(LC_ALL, locale)) continue;
		cases();
		randomCases();
	}
}
