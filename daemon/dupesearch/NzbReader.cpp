/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2026 Denis <denis@nzbget.com>
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
#include <regex>
#include <limits>
#include "NzbReader.h"
#include "XmlReader.h"
#include "NzbFile.h"
#include "ParParser.h"
#ifdef NZBGET_USE_RUST
#include "nzbget_rs.h"
#endif

#include "DupeUtil.h"
#ifdef NZBGET_USE_RUST
#include "nzbget_rs_dupesearch_nzb.h"
#endif

using DupeUtil::Lower;
using DupeUtil::Trim;

namespace
{

// the file name of a subject: the first quoted string, else the whole subject
std::string NameOfSubject(const std::string& subject)
{
	size_t open = subject.find('"');
	if (open != std::string::npos)
	{
		size_t close = subject.find('"', open + 1);
		if (close != std::string::npos && close > open + 1)
		{
			return Trim(subject.substr(open + 1, close - open - 1));
		}
	}
#ifdef NZBGET_USE_RUST
	NzbgetRsSubjectRange range = nzbget_rs_dupesearch_unquoted_subject((const uint8_t*)subject.data(), subject.size());
	return subject.substr(range.start, range.len);
#else
    // Standard unquoted yEnc subjects decorate the filename with a part count.
    // Strip only that terminal decoration, so volume-like media names stay data.
    static const std::regex tail(R"(\s+yEnc(?:\s+\([0-9]+/[0-9]+\))?\s*$)", std::regex::icase);
    std::smatch match;
    if (std::regex_search(subject, match, tail))
    {
        return Trim(subject.substr(0, (size_t)match.position()));
    }
	return Trim(subject);
#endif
}

bool ValidMessageId(const std::string& id)
{
	if (id.empty() || id.size() > 250)
	{
		return false;
	}
	for (size_t i = 0; i < id.size(); i++)
	{
		unsigned char ch = (unsigned char)id[i];
		bool edge = i == 0 || i + 1 == id.size();
		if (ch <= ' ' || ch == 0x7f || ((ch == '<' || ch == '>') && !edge))
		{
			return false;
		}
	}
	return true;
}

bool IsParName(const std::string& name)
{
#ifdef NZBGET_USE_RUST
	return nzbget_rs_dupesearch_par_name((const uint8_t*)name.data(), name.size()) != 0;
#else
	return name.size() >= 5 && Lower(name.substr(name.size() - 5)) == ".par2";
#endif
}

class Reader : public XmlReader::Handler
{
public:
	void Start(const std::string& name, const XmlReader::Attrs& attrs) override
	{
		m_text.clear();
		if (name == "meta" && !XmlReader::Attr(attrs, "type").empty())
		{
			m_metaType = Lower(XmlReader::Attr(attrs, "type"));
		}
		else if (name == "file")
		{
			files++;
			m_inFile = true;
			if (poster.empty())
			{
				poster = XmlReader::Attr(attrs, "poster");
			}
			m_name = NameOfSubject(XmlReader::Attr(attrs, "subject"));
			m_fileBytes = 0;
			m_firstId.clear();
			m_subject = XmlReader::Attr(attrs, "subject");
			m_parts.clear();
			m_segments.clear();
			m_validParts = 0;
		}
		else if (name == "segment" && m_inFile)
		{
			m_segmentBytes = atoll(XmlReader::Attr(attrs, "bytes").c_str());
			m_segmentNumber = atoll(XmlReader::Attr(attrs, "number").c_str());
			m_inSegment = true;
		}
	}

	void End(const std::string& name) override
	{
		if (name == "meta" && !m_metaType.empty())
		{
			meta[m_metaType] = Trim(m_text);
			m_metaType.clear();
		}
		else if (name == "segment" && m_inSegment)
		{
            // Keep the ID and size together until duplicate part numbers have
            // been resolved with the queue parser's keep-last policy.
            m_segments.push_back({ m_segmentNumber, m_segmentBytes, Trim(m_text) });
			m_inSegment = false;
		}
		else if (name == "group" && m_inFile)
		{
			std::string group = Trim(m_text);
			if (!group.empty())
			{
				groups.insert(group);
			}
		}
		else if (name == "file")
		{
            std::stable_sort(m_segments.begin(), m_segments.end(),
                [](const Segment& a, const Segment& b) { return a.number < b.number; });
            for (size_t i = 0; i < m_segments.size(); i++)
            {
                const Segment& segment = m_segments[i];
                if (i + 1 < m_segments.size() && m_segments[i + 1].number == segment.number) continue;
                m_parts.push_back({ segment.number, segment.bytes });
                // Invalid retained data still makes geometry unknown. Never
                // resurrect an earlier valid duplicate in place of this ID.
                if (!ValidMessageId(segment.id))
                {
                    if (!IsParName(m_name)) geometryValid = false;
                    continue;
                }
                sizes[m_name] += segment.bytes;
                ids.insert(segment.id);
                if (!IsParName(m_name)) dataIds.insert(segment.id);
                m_validParts++;
                if (!IsParName(m_name) && segment.bytes > 0) articleSizes.push_back((uint64_t)segment.bytes);
                if (segment.bytes > 0 && m_fileBytes <= std::numeric_limits<long long>::max() - segment.bytes)
                    m_fileBytes += segment.bytes;
                else if (!IsParName(m_name)) geometryValid = false;
                if (segment.number == 1) m_firstId = segment.id;
            }
            uint64_t listed = m_parts.size(), declared = listed;
#ifdef NZBGET_USE_RUST
            std::vector<NzbgetRsDupePart> raw;
            raw.reserve(m_parts.size());
            for (const auto& part : m_parts) raw.push_back({ part.first, part.second });
            int count = NzbFile::DeclaredParts(m_subject.c_str());
            nzbget_rs_dupe_part_counts(raw.data(), raw.size(), count > 0 ? (uint32_t)count : 0,
                IsParName(m_name), &listed, &declared);
#else
            for (const auto& part : m_parts) if (part.first > 0 && part.first <= 200000)
                declared = std::max(declared, (uint64_t)part.first);
#endif
            listedParts += m_validParts;
            declaredParts += declared;
            if (!IsParName(m_name))
            {
                dataListedParts += m_validParts;
                dataDeclaredParts += declared;
            }
            if (IsParName(m_name) && m_fileBytes > 0 && !m_firstId.empty())
                parityHeads.push_back({ m_name, m_firstId, m_fileBytes });

			if (!IsParName(m_name) && m_fileBytes > 0)
			{
				dataFiles++;
				if (dataBytes <= std::numeric_limits<long long>::max() - m_fileBytes) dataBytes += m_fileBytes;
				else geometryValid = false;
				if (!m_firstId.empty()) heads.push_back({ m_name, m_firstId, m_fileBytes });
			}
			else if (!IsParName(m_name)) geometryValid = false;
			m_inFile = false;
		}
		m_text.clear();
	}

	void Text(const std::string& text) override
	{
		m_text += text;
	}

	int files = 0;
	std::string poster;
	std::map<std::string, long long> sizes;
	std::vector<NzbSummary::Head> heads;
	long long dataBytes = 0;
	int dataFiles = 0;
	bool geometryValid = true;
	uint64_t listedParts = 0, declaredParts = 0;
	uint64_t dataListedParts = 0, dataDeclaredParts = 0;
	std::vector<uint64_t> articleSizes;
	std::vector<NzbSummary::Head> parityHeads;
	std::set<std::string> ids;
	std::set<std::string> dataIds;
	std::set<std::string> groups;
	std::map<std::string, std::string> meta;

private:
	std::string m_text;
	std::string m_metaType;
	std::string m_name;
	long long m_segmentBytes = 0;
	long long m_segmentNumber = 0;
	long long m_fileBytes = 0;
	std::string m_firstId;
	std::string m_subject;
	uint64_t m_validParts = 0;
	std::vector<std::pair<long long,long long>> m_parts;
    struct Segment
    {
        long long number;
        long long bytes;
        std::string id;
    };
    std::vector<Segment> m_segments;
	bool m_inFile = false;
	bool m_inSegment = false;
};

}

std::string NzbSummary::Fingerprint() const
{
	// FNV-1a over the sorted message-ids
	uint64_t hash = 1469598103934665603ULL;
	for (const std::string& id : messageIds)
	{
		for (unsigned char ch : id)
		{
			hash = (hash ^ ch) * 1099511628211ULL;
		}
		hash = (hash ^ '\n') * 1099511628211ULL;
	}
	char buffer[32];
	snprintf(buffer, sizeof(buffer), "%016llx", (unsigned long long)hash);
	return buffer;
}

bool NzbReader::Parse(const std::string& data, NzbSummary& summary)
{
	summary = NzbSummary();
	Reader reader;
	if (!XmlReader::Parse(data, reader) || !reader.files || reader.ids.empty())
	{
		return false;
	}

	summary.files = reader.files;
	summary.poster = reader.poster;
	summary.meta = reader.meta;
	summary.messageIds.assign(reader.ids.begin(), reader.ids.end());
	summary.dataMessageIds.assign(reader.dataIds.begin(), reader.dataIds.end());
	summary.groups.assign(reader.groups.begin(), reader.groups.end());
    summary.listedParts = reader.listedParts;
    summary.declaredParts = reader.declaredParts;
    summary.dataListedParts = reader.dataListedParts;
    summary.dataDeclaredParts = reader.dataDeclaredParts;
    if (!reader.articleSizes.empty())
    {
        std::sort(reader.articleSizes.begin(), reader.articleSizes.end());
        summary.articleBytes = reader.articleSizes[reader.articleSizes.size()/2];
    }
    // File size does not identify a PAR2 index: an index can be larger than
    // a recovery volume. Use the shared filename parser and keep capacity
    // paired with the selected index's collection.
    for (const auto& head : reader.parityHeads)
    {
        int baseLen = 0;
        if (ParParser::ParseParFilename(head.name.c_str(), true, &baseLen, nullptr) &&
            baseLen >= 0 && (size_t)baseLen + 5 == head.name.size())
        {
            if (!summary.parIndex.messageId.empty() &&
                !ParParser::SameParCollection(summary.parIndex.name.c_str(), head.name.c_str(), true))
            {
                // Whole-NZB dataBytes cannot be paired with one independent
                // PAR collection's capacity. Keep feasibility unknown.
                summary.parIndex = NzbSummary::Head();
                break;
            }
            if (summary.parIndex.messageId.empty()) summary.parIndex = head;
        }
    }
    if (!summary.parIndex.messageId.empty())
    {
        for (const auto& head : reader.parityHeads)
        {
            int baseLen = 0;
            if (ParParser::ParseParFilename(head.name.c_str(), true, &baseLen, nullptr) &&
                baseLen >= 0 && (size_t)baseLen + 5 < head.name.size() &&
                ParParser::SameParCollection(summary.parIndex.name.c_str(), head.name.c_str(), true))
                summary.recoveryBytes.push_back((uint64_t)head.bytes);
        }
    }

	std::string mainName;
	long long mainSize = -1;
	std::string anyName;
	long long anySize = -1;
	for (const auto& entry : reader.sizes)
	{
		summary.totalBytes += entry.second;
		summary.filenames.insert(Lower(entry.first));
		if (entry.second > anySize)
		{
			anySize = entry.second;
			anyName = entry.first;
		}
		if (!IsParName(entry.first) && entry.second > mainSize)
		{
			mainSize = entry.second;
			mainName = entry.first;
		}
	}
	summary.mainName = mainSize >= 0 ? mainName : anyName;
	if (reader.geometryValid)
	{
		summary.dataBytes = reader.dataBytes;
		summary.dataFiles = reader.dataFiles;
		summary.heads = std::move(reader.heads);
	}
	std::stable_sort(summary.heads.begin(), summary.heads.end(),
		[](const NzbSummary::Head& a, const NzbSummary::Head& b) { return a.bytes > b.bytes; });
	if (summary.heads.size() > 3) summary.heads.resize(3);
	return true;
}
