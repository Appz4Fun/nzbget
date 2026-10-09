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


#ifndef PARDAMAGE_H
#define PARDAMAGE_H

#include <string>
#include "DownloadInfo.h"
#include "DupeStreamRepair.h"

/*
 * The par2 blocks a download's failed articles spoil, against the recovery
 * blocks its par2-files hold. Health counts articles, but par2 repairs whole
 * blocks: one lost article of 0.7 MB spoils a block of 15-25 MB, so a download
 * at health 98% can have most of its blocks damaged and fail par-repair after
 * downloading in full. Kept in memory only (all calls under the queue guard):
 * after a restart the files finished before it count as undamaged.
 */
class ParDamage
{
public:
	struct Verdict
	{
		bool known = false;			// a damaged file matched a par2 set with its block size
		uint64 blockSize = 0;
		int damagedBlocks = 0;		// in the data files finished so far
		int recoveryBlocks = 0;		// in all par2 volumes of the download, counted whole
		int64 doneBytes = 0;		// data finished so far
		int64 totalBytes = 0;		// data of the download
		int projectedBlocks = 0;	// damagedBlocks at the rate so far, for all the data

		/* the blocks already spoiled are more than all its par2-files can repair */
		bool Certain() const { return known && damagedBlocks > recoveryBlocks; }
		/* at the rate so far, a fifth or more of the data done, the damage will be
		 * well past what par2 repairs (by a quarter and two blocks) */
		bool Projected() const
		{
			return known && doneBytes * 5 >= totalBytes &&
				(int64)projectedBlocks * 4 > (int64)recoveryBlocks * 5 + 8;
		}
	};

	/* a file of the download is finished (its article list still exists) */
	static void FileCompleted(NzbInfo* nzbInfo, FileInfo* fileInfo, const std::string& filename);
	static Verdict Judge(NzbInfo* nzbInfo);
	/* true the first time it's asked for a download, false after */
	static bool FirstReport(int nzbId);
	static void Forget(int nzbId);

	/* distinct blocks of <blockSize> the ranges touch */
	static int BlocksTouched(const StreamRangeList& holes, uint64 blockSize);
};

#endif
