/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2023-2024 Denis <denis@nzbget.com>
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

#include "ManifestFile.h"
#include "Json.h"
#include "FileSystem.h"
#include "Log.h"
#ifdef NZBGET_USE_RUST
#include <exception>
#include "nzbget_rs.h"
#endif

namespace ManifestFile
{
#ifdef NZBGET_USE_RUST
	namespace
	{
		std::string Str(const NzbgetRsStr& str)
		{
			return std::string(str.data, str.len);
		}

		std::vector<std::string> Strs(const NzbgetRsStr* strs, size_t count)
		{
			std::vector<std::string> out;
			out.reserve(count);
			for (size_t i = 0; i < count; ++i)
			{
				out.push_back(Str(strs[i]));
			}
			return out;
		}

		SelectOption Select(const NzbgetRsManifestSelect& select)
		{
			if (select.isString)
			{
				return Str(select.string);
			}
			return select.number;
		}

		Section MakeSection(const NzbgetRsManifestSection& section)
		{
			return Section{section.multi != 0, Str(section.name), Str(section.prefix)};
		}

		void Copy(const NzbgetRsManifest& from, Manifest& manifest)
		{
			std::string* fields[] = {&manifest.author, &manifest.main, &manifest.homepage, &manifest.about,
				&manifest.version, &manifest.name, &manifest.displayName, &manifest.kind, &manifest.license,
				&manifest.taskTime, &manifest.queueEvents, &manifest.nzbgetMinVersion};
			for (size_t i = 0; i < 11; ++i)
			{
				if (from.has[i])
				{
					*fields[i] = Str(from.fields[i]);
				}
			}

			for (size_t i = 0; i < from.optionCount; ++i)
			{
				const NzbgetRsManifestOption& rsOption = from.options[i];
				Option option{};
				option.section = MakeSection(rsOption.section);
				option.name = Str(rsOption.name);
				option.displayName = Str(rsOption.displayName);
				option.description = Strs(rsOption.description, rsOption.descriptionCount);
				option.value = Select(rsOption.value);
				for (size_t j = 0; j < rsOption.selectCount; ++j)
				{
					option.select.emplace_back(Select(rsOption.select[j]));
				}
				manifest.options.emplace_back(std::move(option));
			}
			manifest.options.shrink_to_fit();

			for (size_t i = 0; i < from.commandCount; ++i)
			{
				const NzbgetRsManifestCommand& rsCommand = from.commands[i];
				Command command{};
				command.section = MakeSection(rsCommand.section);
				command.name = Str(rsCommand.name);
				command.displayName = Str(rsCommand.displayName);
				command.action = Str(rsCommand.action);
				command.description = Strs(rsCommand.description, rsCommand.descriptionCount);
				manifest.commands.emplace_back(std::move(command));
			}
			manifest.commands.shrink_to_fit();

			for (size_t i = 0; i < from.sectionCount; ++i)
			{
				Section section = MakeSection(from.sections[i]);
				for (auto& option : manifest.options)
				{
					if (option.section.name == section.name) option.section = section;
				}
				for (auto& command : manifest.commands)
				{
					if (command.section.name == section.name) command.section = section;
				}
			}
			for (size_t i = 0; i < from.descriptionCount; ++i)
			{
				manifest.description.emplace_back(Str(from.description[i]));
			}
			for (size_t i = 0; i < from.requirementsCount; ++i)
			{
				manifest.requirements.emplace_back(Str(from.requirements[i]));
			}
			if (from.has[11]) manifest.nzbgetMinVersion = Str(from.fields[11]);
		}
	}

	bool Load(Manifest& manifest, const char* directory)
	{
		std::string path = std::string(directory) + PATH_SEPARATOR + MANIFEST_FILE;
		DiskFile file;
		if (!file.Open(path.c_str(), DiskFile::omRead)) return false;

		std::string jsonStr;
		char buffer[BUFFER_SIZE];
		while (file.ReadLine(buffer, BUFFER_SIZE))
		{
			jsonStr += buffer;
		}

		// rust/src/manifest.rs; copying the manifest happens in the callback,
		// its exceptions are handled here as the C++ handled them
		struct Context
		{
			Manifest* manifest;
			std::exception_ptr error;
		} context{&manifest, nullptr};
		const NzbgetRsJsonLimits limits{Json::string::max_size(), Json::JsonArray::max_size(), Json::JsonObject::max_size()};
		int loaded = nzbget_rs_manifest_load(jsonStr.data(), jsonStr.size(), limits, &context,
			[](void* ctx, const NzbgetRsManifest* from) noexcept
			{
				Context& context = *static_cast<Context*>(ctx);
				try
				{
					Copy(*from, *context.manifest);
				}
				catch (...)
				{
					context.error = std::current_exception();
				}
			});

		if (loaded == -1)
		{
			error("Failed to parse %s. Syntax error.", path.c_str());
			return false;
		}

		// a value of another type than expected ("[]" for the whole file, a
		// string among the commands) threw out of the extension loading and
		// ended the daemon at start: the extension is refused instead
		try
		{
			if (loaded == -2)
			{
				error("Failed to parse %s. The manifest isn't a JSON object.", path.c_str());
				return false;
			}
			if (context.error)
			{
				std::rethrow_exception(context.error);
			}
			if (loaded == -3)
			{
				// the exception Boost.JSON throws for an entry that isn't an object
				const Json::JsonValue notObject;
				(void)notObject.as_object();
			}
		}
		catch (const std::exception& e)
		{
			error("Failed to parse %s: %s", path.c_str(), e.what());
			return false;
		}

		return loaded == 1;
	}

#else
	bool Load(Manifest& manifest, const char* directory)
	{
		std::string path = std::string(directory) + PATH_SEPARATOR + MANIFEST_FILE;
		DiskFile file;
		if (!file.Open(path.c_str(), DiskFile::omRead)) return false;

		std::string jsonStr;
		char buffer[BUFFER_SIZE];
		while (file.ReadLine(buffer, BUFFER_SIZE))
		{
			jsonStr += buffer;
		}
		
		auto desRes = Json::Deserialize(jsonStr);
		if (!desRes.has_value())
		{
			error("Failed to parse %s. Syntax error.", path.c_str());
			return false;
		}

		// a value of another type than expected ("[]" for the whole file, a
		// string among the commands) threw out of the extension loading and
		// ended the daemon at start: the extension is refused instead
		try
		{
			Json::JsonValue jsonValue = std::move(desRes.value());
			if (!jsonValue.is_object())
			{
				error("Failed to parse %s. The manifest isn't a JSON object.", path.c_str());
				return false;
			}
			Json::JsonObject json = jsonValue.as_object();

			if (!ValidateAndSet(json, manifest))
				return false;

			CheckKeyAndSet(json, "nzbgetMinVersion", manifest.nzbgetMinVersion);
		}
		catch (const std::exception& e)
		{
			error("Failed to parse %s: %s", path.c_str(), e.what());
			return false;
		}

		return true;
	}

#endif

	bool ValidateAndSet(const Json::JsonObject& json, Manifest& manifest)
	{
		if (!CheckKeyAndSet(json, "author", manifest.author))
			return false;

		if (!CheckKeyAndSet(json, "main", manifest.main))
			return false;

		if (!CheckKeyAndSet(json, "homepage", manifest.homepage))
			return false;

		if (!CheckKeyAndSet(json, "about", manifest.about))
			return false;

		if (!CheckKeyAndSet(json, "version", manifest.version))
			return false;

		if (!CheckKeyAndSet(json, "name", manifest.name))
			return false;

		if (!CheckKeyAndSet(json, "displayName", manifest.displayName))
			return false;

		if (!CheckKeyAndSet(json, "kind", manifest.kind))
			return false;

		if (!CheckKeyAndSet(json, "license", manifest.license))
			return false;

		if (!CheckKeyAndSet(json, "taskTime", manifest.taskTime))
			return false;

		if (!CheckKeyAndSet(json, "queueEvents", manifest.queueEvents))
			return false;

		if (!ValidateOptionsAndSet(json, manifest.options))
			return false;

		if (!ValidateCommandsAndSet(json, manifest.commands))
			return false;

		ValidateSectionsAndSet(json, manifest.options, manifest.commands);

		if (!ValidateTxtAndSet(json, manifest.description, "description"))
			return false;

		if (!ValidateTxtAndSet(json, manifest.requirements, "requirements"))
			return false;

		return true;
	}

	bool ValidateCommandsAndSet(const Json::JsonObject& json, std::vector<Command>& commands)
	{
		auto rawCommands = json.if_contains("commands");
		if (!rawCommands || !rawCommands->is_array())
			return false;

		for (auto& value : rawCommands->as_array())
		{
			Json::JsonObject cmdJson = value.as_object();
			Command command{};

			CheckKeyAndSet(cmdJson, "section", command.section.name, DEFAULT_SECTION_NAME);

			if (!CheckKeyAndSet(cmdJson, "name", command.name))
				continue;

			if (!CheckKeyAndSet(cmdJson, "displayName", command.displayName))
				continue;

			if (!ValidateTxtAndSet(cmdJson, command.description, "description"))
				continue;

			if (!CheckKeyAndSet(cmdJson, "action", command.action))
				continue;

			commands.emplace_back(std::move(command));
		}

		commands.shrink_to_fit();

		return true;
	}

	bool ValidateOptionsAndSet(const Json::JsonObject& json, std::vector<Option>& options)
	{
		auto rawOptions = json.if_contains("options");
		if (!rawOptions || !rawOptions->is_array())
			return false;

		for (auto& optionVal : rawOptions->as_array())
		{
			Json::JsonObject optionJson = optionVal.as_object();
			auto selectJson = optionJson.if_contains("select");
			if (!selectJson || !selectJson->is_array())
				continue;

			Option option{};

			CheckKeyAndSet(optionJson, "section", option.section.name, DEFAULT_SECTION_NAME);

			if (!CheckKeyAndSet(optionJson, "name", option.name))
				continue;

			if (!CheckKeyAndSet(optionJson, "displayName", option.displayName))
				continue;

			if (!CheckKeyAndSet(optionJson, "value", option.value))
				continue;

			if (!ValidateTxtAndSet(optionJson, option.description, "description"))
				continue;

			for (auto& selectVal : selectJson->as_array())
			{
				if (selectVal.is_string())
				{
					option.select.emplace_back(selectVal.get_string().c_str());
					continue;
				}
				if (selectVal.is_number())
				{
					option.select.emplace_back(selectVal.to_number<double>());
					continue;
				}
			}

			options.emplace_back(std::move(option));
		}

		options.shrink_to_fit();

		return true;
	}

	bool ValidateTxtAndSet(const Json::JsonObject& json, std::vector<std::string>& property, const char* propName)
	{
		auto rawProp = json.if_contains(propName);
		if (!rawProp || !rawProp->is_array())
			return false;

		for (auto& value : rawProp->as_array())
		{
			if (value.is_string())
			{
				property.emplace_back(value.get_string().c_str());
			}
		}

		property.shrink_to_fit();

		return true;
	}

	bool CheckKeyAndSet(const Json::JsonObject& json, const char* key, std::string& property)
	{
		const auto& rawProperty = json.if_contains(key);
		if (!rawProperty || !rawProperty->is_string())
			return false;

		property = rawProperty->get_string().c_str();
		return true;
	}

	bool CheckKeyAndSet(const Json::JsonObject& json, const char* key, std::string& property, std::string defValue)
	{
		const auto& rawProperty = json.if_contains(key);
		if (!rawProperty || !rawProperty->is_string())
		{
			property = std::move(defValue);
			return false;
		}

		property = rawProperty->get_string().c_str();
		return true;
	}

	bool CheckKeyAndSet(const Json::JsonObject& json, const char* key, SelectOption& property)
	{
		const auto& rawProperty = json.if_contains(key);
		if (!rawProperty)
			return false;

		if (rawProperty->is_string())
		{
			property = rawProperty->get_string().c_str();
			return true;
		}

		if (rawProperty->is_number())
		{
			property = rawProperty->to_number<double>();
			return true;
		}

		return false;
	}

	bool CheckKeyAndSet(const Json::JsonObject& json, const char* key, bool& property)
	{
		const auto& rawProperty = json.if_contains(key);
		if (rawProperty && rawProperty->is_bool())
		{
			property = rawProperty->as_bool();
			return true;
		}

		return false;
	}

	bool ValidateSectionsAndSet(const Json::JsonObject& json, std::vector<Option>& options, std::vector<Command>& commands)
	{
		auto rawSections = json.if_contains("sections");
		if (!rawSections || !rawSections->is_array())
			return false;

		for (auto& sectionVal : rawSections->as_array())
		{
			Json::JsonObject sectionJson = sectionVal.as_object();

			Section section;

			if (!CheckKeyAndSet(sectionJson, "name", section.name))
				continue;

			if (Util::StrCaseCmp(section.name, DEFAULT_SECTION_NAME))
				continue;

			if (!CheckKeyAndSet(sectionJson, "prefix", section.prefix))
				continue;

			if (!CheckKeyAndSet(sectionJson, "multi", section.multi))
				continue;

			for (auto& option : options)
			{
				if (option.section.name == section.name)
				{
					option.section = section;
				}
			}

			for (auto& command : commands)
			{
				if (command.section.name == section.name)
				{
					command.section = section;
				}
			}
		}

		return true;
	}
}
