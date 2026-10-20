/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2013-2016 Andrey Prygunkov <hugbug@users.sourceforge.net>
 *  Copyright (C) 2023 Denis <denis@nzbget.com>
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

#ifndef SCRIPTCONFIG_H
#define SCRIPTCONFIG_H

#include "NString.h"
#include "Container.h"
#include "Options.h"
#include <mutex>
#include <atomic>
#include <string_view>
#include <functional>

class ScriptConfig
{
public:

	class ConfigTemplate
	{
	public:
		ConfigTemplate(const char* templ)
			: m_template(templ) {}
		const char* GetTemplate() { return m_template; }

	private:
		CString m_template;
	};

	using ConfigTemplates = std::deque<ConfigTemplate>;

	void InitOptions();
	bool LoadConfig(Options::OptEntries* optEntries);
	bool SaveConfig(Options::OptEntries* optEntries, const char* cipherBaseline = nullptr, bool* conflict = nullptr);
	static std::string CipherBaseline(const Options::OptEntries& optEntries);
	enum class CipherCommit { Saved, Unchanged, Conflict, Cancelled, Failed };
	bool ReadCipherSnapshot(std::string& bytes);
	CipherCommit CommitCipherPatch(std::string_view expected, std::string_view replacement, const std::function<bool()>& cancel);
	bool LoadConfigTemplates(ConfigTemplates* configTemplates);
	ConfigTemplates* GetConfigTemplates() { return &m_configTemplates; }

private:
	ConfigTemplates m_configTemplates;
	inline static std::mutex m_configWriteMutex;

	void InitConfigTemplates();
	bool LoadConfigUnlocked(Options::OptEntries* optEntries);
};

extern ScriptConfig* g_ScriptConfig;

#endif
