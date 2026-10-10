/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */


#ifndef TWINCHECK_H
#define TWINCHECK_H

#include <string>
#include <vector>
#include "Service.h"
#include "DownloadInfo.h"

/*
 * Tells the duplicates of a download apart: a twin holds files byte-identical to
 * the primary's (its articles, par2-files and bytes can stand in for the
 * primary's), an alt is the same release in another encode (a backup only).
 *
 * Each posting gets a fingerprint once (FilesParam): a hash of the MD5 and length
 * of every file its par2 set describes, read from the FileDesc packets of its
 * smallest par2-file (a few articles). Article sizes and parity levels don't
 * change it: par2 checksums the decoded files. Postings with one fingerprint are
 * twins of each other; which of them is a twin or an alt of the download (the
 * label, KindParam) depends on the primary of the dupe key, and changes with it
 * without fetching anything again. A posting without par2 has no fingerprint.
 */
class TwinCheck : public Service
{
public:
	static constexpr const char* FilesParam = "DupeFiles";	// fingerprint, or "none"
	static constexpr const char* KindParam = "DupeKind";	// "twin" or "alt" (of the primary)
	// the smallest par2-file of a posting is fetched only up to this size
	static constexpr int64 MaxIndexSize = 16LL * 1024 * 1024;
	// fingerprints fetched at once
	static constexpr int MaxRunning = 2;

	struct FileSig
	{
		std::string name;
		uint64 length = 0;
		std::string md5;		// hex, the whole file
		std::string hash16k;	// hex, its first 16 KB
	};

	/* the files the FileDesc packets in <data> describe (recovery packets are skipped) */
	static std::vector<FileSig> ParsePar2(const char* data, size_t size);
	/* the posting's fingerprint: equal for postings of byte-identical files, whatever
	 * their names; "" for none */
	static std::string Fingerprint(const std::vector<FileSig>& sigs);

	/* shutdown: cancels running checks and refuses new ones; WaitAll() returns when they ended */
	static void StopAll();
	static void WaitAll();
	static void Reset();

	TwinCheck() { Reset(); }

protected:
	int ServiceInterval() override { return 15; }
	void ServiceWork() override;
};

#endif
