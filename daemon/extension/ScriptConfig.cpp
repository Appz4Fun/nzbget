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


#include "nzbget.h"

#include "Util.h"
#include "FileSystem.h"
#include "Options.h"
#include "Log.h"
#include "ScriptConfig.h"
#if defined(__APPLE__) || defined(__linux__)
#define NZBGET_CIPHER_ATOMIC_CONFIG
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/xattr.h>
#ifdef __APPLE__
#include <copyfile.h>
#endif
#endif

namespace
{
#ifdef NZBGET_CIPHER_ATOMIC_CONFIG
struct CipherDescriptor
{
	int value = -1;
	explicit CipherDescriptor(int fd = -1) : value(fd) {}
	~CipherDescriptor() { if (value >= 0) close(value); }
	CipherDescriptor(const CipherDescriptor&) = delete;
	CipherDescriptor& operator=(const CipherDescriptor&) = delete;
};

bool SameCipherFile(const struct stat& a, const struct stat& b)
{
	bool same = a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_size == b.st_size &&
		a.st_mode == b.st_mode && a.st_uid == b.st_uid && a.st_gid == b.st_gid;
#ifdef __APPLE__
	return same && a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
		a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
#else
	return same && a.st_mtim.tv_sec == b.st_mtim.tv_sec && a.st_mtim.tv_nsec == b.st_mtim.tv_nsec &&
		a.st_ctim.tv_sec == b.st_ctim.tv_sec && a.st_ctim.tv_nsec == b.st_ctim.tv_nsec;
#endif
}

bool ReadCipherDescriptor(int fd, std::string& output, struct stat& before)
{
	if (fstat(fd, &before) != 0 || !S_ISREG(before.st_mode) || before.st_size < 0 || before.st_size > 16 * 1024 * 1024) return false;
	output.resize(static_cast<size_t>(before.st_size));
	size_t used = 0;
	while (used < output.size())
	{
		ssize_t count = pread(fd, output.data() + used, output.size() - used, static_cast<off_t>(used));
		if (count < 0 && errno == EINTR) continue;
		if (count <= 0) return false;
		used += static_cast<size_t>(count);
	}
	char extra;
	if (pread(fd, &extra, 1, before.st_size) != 0) return false;
	struct stat after;
	return fstat(fd, &after) == 0 && SameCipherFile(before, after);
}

bool CopyCipherAttributes(int source, int target)
{
#ifdef __APPLE__
	return fcopyfile(source, target, nullptr, COPYFILE_SECURITY | COPYFILE_XATTR) == 0;
#else
	ssize_t size = flistxattr(source, nullptr, 0);
	if (size < 0 || size > 65536) return false;
	std::vector<char> names(static_cast<size_t>(size));
	if (size && flistxattr(source, names.data(), names.size()) != size) return false;
	size_t cursor = 0, total = 0;
	while (cursor < names.size())
	{
		const char* name = names.data() + cursor;
		size_t length = strnlen(name, names.size() - cursor);
		if (length == names.size() - cursor) return false;
		ssize_t bytes = fgetxattr(source, name, nullptr, 0);
		if (bytes < 0 || static_cast<size_t>(bytes) > 1024 * 1024 - total) return false;
		std::vector<char> value(static_cast<size_t>(bytes));
		if (fgetxattr(source, name, value.data(), value.size()) != bytes ||
			fsetxattr(target, name, value.data(), value.size(), 0) != 0) return false;
		total += value.size(); cursor += length + 1;
	}
	return true;
#endif
}
#endif
}

bool ScriptConfig::ReadCipherSnapshot(std::string& bytes)
{
	std::lock_guard<std::mutex> lock(m_configWriteMutex);
#ifndef NZBGET_CIPHER_ATOMIC_CONFIG
	return false; // Unsupported atomic metadata-preserving platform adapter.
#else
	CipherDescriptor file(open(g_Options->GetConfigFilename(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
	struct stat metadata;
	return file.value >= 0 && ReadCipherDescriptor(file.value, bytes, metadata);
#endif
}

ScriptConfig::CipherCommit ScriptConfig::CommitCipherPatch(std::string_view expected, std::string_view replacement,
	const std::function<bool()>& cancel)
{
	std::lock_guard<std::mutex> lock(m_configWriteMutex);
	if (expected.size() > 16 * 1024 * 1024 || replacement.size() > 16 * 1024 * 1024) return CipherCommit::Failed;
	if (cancel()) return CipherCommit::Cancelled;
#ifndef NZBGET_CIPHER_ATOMIC_CONFIG
	return CipherCommit::Failed;
#else
	fs::path filename(g_Options->GetConfigFilename());
	std::string leaf = filename.filename().string();
	CipherDescriptor parent(open(filename.parent_path().empty() ? "." : filename.parent_path().string().c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
	if (parent.value < 0 || leaf.empty()) return CipherCommit::Failed;
	CipherDescriptor original(openat(parent.value, leaf.c_str(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
	std::string current;
	struct stat before;
	if (original.value < 0 || !ReadCipherDescriptor(original.value, current, before)) return CipherCommit::Failed;
	if (current != expected) return CipherCommit::Conflict;
	if (current == replacement) return CipherCommit::Unchanged;
	static std::atomic<uint64_t> sequence{0};
	std::string temporary;
	int descriptor = -1;
	for (int attempt = 0; attempt < 16; ++attempt)
	{
		temporary = "." + leaf + ".tls-" + std::to_string(getpid()) + "-" + std::to_string(sequence.fetch_add(1));
		descriptor = openat(parent.value, temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
		if (descriptor >= 0 || errno != EEXIST) break;
	}
	if (descriptor < 0) return CipherCommit::Failed;
	CipherDescriptor output(descriptor);
	struct RemoveTemporary
	{
		int parent; const std::string& name;
		~RemoveTemporary() { unlinkat(parent, name.c_str(), 0); }
	} cleanup{parent.value, temporary};
	size_t used = 0;
	while (used < replacement.size())
	{
		if (cancel()) return CipherCommit::Cancelled;
		ssize_t count = write(output.value, replacement.data() + used, replacement.size() - used);
		if (count < 0 && errno == EINTR) continue;
		if (count <= 0) return CipherCommit::Failed;
		used += static_cast<size_t>(count);
	}
	if (!CopyCipherAttributes(original.value, output.value) || fchown(output.value, before.st_uid, before.st_gid) != 0 ||
		fchmod(output.value, before.st_mode & 07777) != 0 || fsync(output.value) != 0) return CipherCommit::Failed;
	int closeResult = close(output.value); output.value = -1;
	if (closeResult != 0) return CipherCommit::Failed;
	struct stat after, entry;
	std::string rechecked;
	if (!ReadCipherDescriptor(original.value, rechecked, after) || !SameCipherFile(before, after) || rechecked != expected ||
		fstatat(parent.value, leaf.c_str(), &entry, AT_SYMLINK_NOFOLLOW) != 0 || !SameCipherFile(before, entry)) return CipherCommit::Conflict;
	if (cancel()) return CipherCommit::Cancelled;
	if (renameat(parent.value, temporary.c_str(), parent.value, leaf.c_str()) != 0) return CipherCommit::Failed;
	// The replacement has happened. A late cancel or directory-sync failure must
	// never be reported as "unchanged"; retain the truthful committed state.
	if (fsync(parent.value) != 0) warn("TLS cipher settings were replaced, but the configuration directory could not be synchronized");
	return CipherCommit::Saved;
#endif
}

void ScriptConfig::InitOptions()
{
	InitConfigTemplates();
}

bool ScriptConfig::LoadConfig(Options::OptEntries* optEntries)
{
	std::lock_guard<std::mutex> lock(m_configWriteMutex);
	return LoadConfigUnlocked(optEntries);
}

bool ScriptConfig::LoadConfigUnlocked(Options::OptEntries* optEntries)
{
	// read config file
	DiskFile infile;

	if (!infile.Open(g_Options->GetConfigFilename(), DiskFile::omRead))
	{
		return false;
	}

	int fileLen = (int)FileSystem::FileSize(g_Options->GetConfigFilename());
	if (fileLen <= 0)
	{
		// nothing to read: a buffer of one byte read an empty line forever
		return true;
	}
	CString buf;
	buf.Reserve(fileLen);

	while (infile.ReadLine(buf, fileLen + 1))
	{
		// remove trailing '\n' and '\r' and spaces
		Util::TrimRight(buf);

		// skip comments and empty lines
		if (buf[0] == 0 || buf[0] == '#' || strspn(buf, " ") == strlen(buf))
		{
			continue;
		}

		CString optname;
		CString optvalue;
		if (Options::SplitOptionString(buf, optname, optvalue))
		{
			optEntries->emplace_back(optname, optvalue);
		}
	}

	infile.Close();

	Options::ConvertOldOptions(optEntries);

	return true;
}

// Versioned, unambiguous saved-value token shared with Config.cipherBaseline.
// Missing fields differ from present empty fields; duplicate keys are last-wins.
std::string ScriptConfig::CipherBaseline(const Options::OptEntries& optEntries)
{
	std::map<std::string, std::string> fields;
	constexpr char hex[] = "0123456789abcdef";
	for (const auto& entry : optEntries)
	{
		if (!entry.GetName() || !entry.GetValue()) continue;
		std::string name(entry.GetName());
		for (char& c : name) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
		if (!name.starts_with("server")) continue;
		size_t dot = name.find('.', 6);
		if (dot == std::string::npos || dot == 6 || name[6] == '0' ||
			!std::all_of(name.begin() + 6, name.begin() + dot, [](char c) { return c >= '0' && c <= '9'; })) continue;
		std::string suffix = name.substr(dot + 1);
		if (suffix != "host" && suffix != "port" && suffix != "cipher") continue;
		std::string value;
		for (unsigned char c : std::string_view(entry.GetValue())) { value += hex[c >> 4]; value += hex[c & 15]; }
		fields[name] = std::move(value);
	}
	std::string token = "v1\n";
	for (const auto& [name, value] : fields) { token += name; token += '='; token += value; token += '\n'; }
	return token;
}

bool ScriptConfig::SaveConfig(Options::OptEntries* optEntries, const char* cipherBaseline, bool* conflict)
{
	std::lock_guard<std::mutex> lock(m_configWriteMutex);
	if (conflict) *conflict = false;
	if (cipherBaseline)
	{
		Options::OptEntries current;
		if (!LoadConfigUnlocked(&current)) return false;
		if (CipherBaseline(current) != cipherBaseline)
		{
			if (conflict) *conflict = true;
			return false;
		}
	}
	struct CaseInsensitiveLess
	{
		bool operator()(std::string_view a, std::string_view b) const
		{
			return std::lexicographical_compare(
				a.begin(), a.end(), b.begin(), b.end(),
				[](unsigned char ca, unsigned char cb)
				{
					return std::tolower(ca) < std::tolower(cb);
				}
			);
		}
	};

	// save to config file
	DiskFile infile;

	if (!infile.Open(g_Options->GetConfigFilename(), DiskFile::omReadWrite))
	{
		return false;
	}

	std::map<std::string_view, std::string_view, CaseInsensitiveLess> values;
	for (const auto& entry : *optEntries)
	{
		if (entry.GetName() && entry.GetValue())
		{
			values[entry.GetName()] = entry.GetValue();
		}
	}

	std::set<std::string_view, CaseInsensitiveLess> writtenOptions;

	// read config file into memory array
	int fileLen = (int)FileSystem::FileSize(g_Options->GetConfigFilename()) + 1;
	CString content;
	content.Reserve(fileLen);
	std::vector<CString> config;
	while (infile.ReadLine(content, fileLen + 1))
	{
		config.push_back(*content);
	}
	content.Clear();

	// write config file back to disk, replace old values of existing options with new values
	infile.Seek(0);
	for (CString& buf : config)
	{
		const char* eq = strchr(buf, '=');
		if (eq && buf[0] != '#')
		{
			// remove trailing '\n' and '\r' and spaces
			buf.TrimRight();

			CString optname;
			CString optvalue;
			if (g_Options->SplitOptionString(buf, optname, optvalue))
			{
				auto it = values.find(*optname);
				if (it != values.end() && writtenOptions.insert(it->first).second)
				{
					infile.Print("%.*s=%.*s\n",
						static_cast<int>(it->first.size()), it->first.data(),
						static_cast<int>(it->second.size()), it->second.data());
				}
			}
		}
		else
		{
			// every line ends: a last line without a line end (a comment, typically)
			// had the first new option glued onto it, and that option was lost
			int len = buf.Length();
			infile.Print("%s%s", *buf, len > 0 && buf[len - 1] == '\n' ? "" : "\n");
		}
	}

	// write new options
	for (const auto& entry : *optEntries)
	{
		if (entry.GetName() && entry.GetValue())
		{
			const char* name = entry.GetName();
			if (writtenOptions.insert(name).second)
			{
				auto it = values.find(name);
				std::string_view val = (it != values.end()) ? it->second : entry.GetValue();
				infile.Print("%s=%.*s\n", name, static_cast<int>(val.size()), val.data());
			}
		}
	}

	// close and truncate the file
	int pos = (int)infile.Position();
	infile.Close();

	FileSystem::TruncateFile(g_Options->GetConfigFilename(), pos);

	return true;
}

bool ScriptConfig::LoadConfigTemplates(ConfigTemplates* configTemplates)
{
	CharBuffer buffer;
	if (!FileSystem::LoadFileIntoBuffer(g_Options->GetConfigTemplate(), buffer, true))
	{
		return false;
	}
	configTemplates->emplace_back(ConfigTemplate(buffer));

	return true;
}

void ScriptConfig::InitConfigTemplates()
{
	if (!LoadConfigTemplates(&m_configTemplates))
	{
		error("Could not read configuration templates");
	}
}
