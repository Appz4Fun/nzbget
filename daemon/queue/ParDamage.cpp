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


#include "nzbget.h"

#include <algorithm>
#include <climits>
#include <map>
#include <vector>
#include "ParDamage.h"
#include "DupeArticleFallback.h"
#include "ParParser.h"
#include "FileSystem.h"

namespace
{

struct FileDamage
{
	std::string name;
	int64 size = 0;			// decoded size, 0 if no article arrived
	StreamRangeList holes;
};

struct State
{
	std::vector<FileDamage> files;
	int64 doneBytes = 0;	// nzb sizes (encoded) of the data files finished
	int parFilesDone = 0;	// par2-files finished: the set is read again when it changes
	int parFilesRead = -1;
	std::vector<DupeArticleFallback::Par2Desc> par2;
	bool reported = false;
};

// by download id; only touched under the queue guard
std::map<int, State> g_states;

}

void ParDamage::FileCompleted(NzbInfo* nzbInfo, FileInfo* fileInfo, const std::string& filename)
{
	State& state = g_states[nzbInfo->GetId()];
	if (fileInfo->GetParFile() || DupeArticleFallback::IsParFile(fileInfo))
	{
		state.parFilesDone++;
		return;
	}

	state.doneBytes += fileInfo->GetSize();
	if (fileInfo->GetFailedArticles() + fileInfo->GetMissedArticles() == 0)
	{
		return;
	}

	FileDamage damage;
	damage.name = FileSystem::BaseFileName(filename.c_str());
	int64 decodedSize = fileInfo->GetDecodedFileSize();
	if (decodedSize > 0)
	{
		// the bytes no arrived article covers: exact (borrowed articles count)
		damage.size = decodedSize;
		damage.holes = DupeStreamRepair::ComputeHoles(fileInfo);
	}
	else if (fileInfo->GetSuccessArticles() == 0)
	{
		// nothing arrived: the whole file (its length comes from par2 if named there)
		damage.holes = { { 0, fileInfo->GetSize() * 100 / 102 } };
	}
	else
	{
		// articles disagreed on the file's size: no reliable picture
		return;
	}

	if (!damage.holes.empty())
	{
		state.files.push_back(std::move(damage));
	}
}

int ParDamage::BlocksTouched(const StreamRangeList& holes, uint64 blockSize)
{
	if (blockSize == 0)
	{
		return 0;
	}

	std::vector<std::pair<int64, int64>> spans;	// first and last block of each hole
	for (const StreamRange& hole : holes)
	{
		if (hole.Size > 0)
		{
			spans.emplace_back(hole.Offset / (int64)blockSize, (hole.Offset + hole.Size - 1) / (int64)blockSize);
		}
	}
	std::sort(spans.begin(), spans.end());

	int64 count = 0;
	int64 coveredTo = -1;	// last block counted
	for (const auto& span : spans)
	{
		int64 from = std::max(span.first, coveredTo + 1);
		if (span.second >= from)
		{
			count += span.second - from + 1;
			coveredTo = span.second;
		}
	}
	return (int)std::min<int64>(count, INT_MAX);
}

ParDamage::Verdict ParDamage::Judge(NzbInfo* nzbInfo)
{
	Verdict verdict;
	auto it = g_states.find(nzbInfo->GetId());
	if (it == g_states.end() || it->second.files.empty())
	{
		return verdict;
	}
	State& state = it->second;

	if (state.parFilesRead != state.parFilesDone)
	{
		state.par2 = DupeArticleFallback::ListPar2Files(nzbInfo->GetDestDir());
		state.parFilesRead = state.parFilesDone;
	}

	// the damaged files the par2 set describes (by name, or by length when a
	// rename came after): files it doesn't cover (.nfo, .sfv) don't count
	for (const FileDamage& damage : state.files)
	{
		const DupeArticleFallback::Par2Desc* match = nullptr;
		for (const DupeArticleFallback::Par2Desc& desc : state.par2)
		{
			if (desc.blockSize > 0 && (desc.name == damage.name ||
				(damage.size > 0 && (int64)desc.length == damage.size)))
			{
				match = &desc;
				break;
			}
		}
		if (!match)
		{
			continue;
		}
		if (verdict.blockSize == 0)
		{
			verdict.blockSize = match->blockSize;
		}
		if (damage.size > 0)
		{
			verdict.damagedBlocks += BlocksTouched(damage.holes, match->blockSize);
		}
		else
		{
			verdict.damagedBlocks += BlocksTouched({ { 0, (int64)match->length } }, match->blockSize);
		}
	}
	if (verdict.blockSize == 0)
	{
		return verdict;
	}
	verdict.known = true;

	// recovery blocks in every par2 volume, counted whole (an error here can only
	// keep a download, never give one up): by the count its name gives, or by
	// its size (a recovery packet is a block and 68 bytes; nzb sizes are encoded)
	uint64 blockSize = verdict.blockSize;
	for (FileInfo* fileInfo : nzbInfo->GetFileList())
	{
		int blocks = 0;
		if (ParParser::ParseParFilename(fileInfo->GetFilename(), fileInfo->GetFilenameConfirmed(), nullptr, &blocks))
		{
			verdict.recoveryBlocks += blocks >= 0 ? blocks :
				(int)(fileInfo->GetSize() * 100 / 102 / (int64)(blockSize + 68));
		}
	}
	for (CompletedFile& completedFile : nzbInfo->GetCompletedFiles())
	{
		int blocks = 0;
		if (completedFile.GetStatus() != CompletedFile::cfFailure &&
			ParParser::ParseParFilename(completedFile.GetFilename(), true, nullptr, &blocks))
		{
			if (blocks < 0)
			{
				BString<1024> path("%s%c%s", nzbInfo->GetDestDir(), PATH_SEPARATOR, completedFile.GetFilename());
				int64 size = FileSystem::FileSize(path);
				blocks = size > 0 ? (int)(size / (int64)(blockSize + 68)) : 0;
			}
			verdict.recoveryBlocks += blocks;
		}
	}

	verdict.doneBytes = state.doneBytes;
	verdict.totalBytes = std::max<int64>(0, nzbInfo->GetSize() - nzbInfo->GetParSize());
	verdict.projectedBlocks = verdict.doneBytes > 0 ?
		(int)std::min<int64>(INT_MAX, (int64)verdict.damagedBlocks * verdict.totalBytes / verdict.doneBytes) :
		verdict.damagedBlocks;
	return verdict;
}

bool ParDamage::FirstReport(int nzbId)
{
	State& state = g_states[nzbId];
	bool first = !state.reported;
	state.reported = true;
	return first;
}

void ParDamage::Forget(int nzbId)
{
	g_states.erase(nzbId);
}
