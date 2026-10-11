#ifndef DUPEIDENTITY_H
#define DUPEIDENTITY_H

#include <ctime>
#include <string>
#include <vector>
#include <functional>
#include "ArticleFetcher.h"
#include "DonorHealth.h"
#include "NzbReader.h"

// Rust decides identity; the daemon owns article transport and queue objects.
class DupeIdentity
{
public:
	struct Identity
	{
		std::string name;
		std::string extension;
		unsigned long long bytes = 0;
		explicit operator bool() const { return bytes != 0 && !extension.empty(); }
	};
	static Identity FromArticle(const std::vector<char>& data, const std::string& name,
		unsigned long long total, unsigned long long minimum);
	using FetchFunc = std::function<ArticleFetcher::FetchedArticle(const std::string&, const std::vector<CString>&)>;
	static Identity Read(const NzbSummary& info, time_t deadline, const FetchFunc& fetch = FetchFunc());
	static ArticleFetcher::FetchedArticle FetchArticle(const NzbSummary::Head& head,
        const std::vector<std::string>& groups, time_t deadline, const FetchFunc& fetch = FetchFunc());
    static unsigned long long WholeBytes(const NzbSummary& info);
    static double Alive(const DonorHealth::Health& health, const NzbSummary& info);
    static int UnlistedMissing(const DonorHealth::Health& health, const NzbSummary& info);
    static bool ParDoomed(const NzbSummary& info, double alive, time_t deadline);
    static bool OuterCompatible(const std::string& title, const std::string& name);
    static bool SameData(const NzbSummary& a, const NzbSummary& b);
	static bool Candidate(const std::string& title, long long bytes, const std::string& name, long long size);
	static bool Matches(const std::string& title, const std::string& mainName,
		const Identity& mine, const Identity& theirs);
	static std::vector<std::string> Hints(const NzbSummary& pick, const NzbSummary& donor, bool sameInner);
};

#endif
