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
 *  along with this program. If not, see <https://www.gnu.org/licenses/>.
 */


#include "nzbget.h"

#include <boost/test/unit_test.hpp>
#include "XmlRpc.h"
#include "Options.h"
#include "Json.h"

BOOST_AUTO_TEST_SUITE(RemoteTest)

class MockXmlCommand : public XmlCommand
{
public:
	void Execute() override {}
	bool TestNextParamAsStr(char** value) { return NextParamAsStr(value); }
};

BOOST_AUTO_TEST_CASE(TestSaveConfig)
{
	std::string jsonInput = R"({
	"method":"saveconfig",
	"params":[[
		{"Name":"OptionName1","Value":"OptionValue1"},
		{"Name":"OptionName2","Value":"OptionValue2"}
	]],
	"id":1})";

	MockXmlCommand cmd;
	cmd.SetRequest(&jsonInput[0]);
	cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
	cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
	cmd.PrepareParams();

	char* dummy = nullptr;
	char* name = nullptr;
	char* value = nullptr;

	BOOST_CHECK(cmd.TestNextParamAsStr(&dummy));
	BOOST_CHECK(cmd.TestNextParamAsStr(&name));
	BOOST_CHECK(cmd.TestNextParamAsStr(&dummy));
	BOOST_CHECK(cmd.TestNextParamAsStr(&value));

	BOOST_CHECK(cmd.TestNextParamAsStr(&dummy));
	BOOST_CHECK(cmd.TestNextParamAsStr(&name));
	BOOST_CHECK(cmd.TestNextParamAsStr(&dummy));
	BOOST_CHECK(cmd.TestNextParamAsStr(&value));
}

class MockXmlCommandAll final : public XmlCommand
{
public:
	void Execute() override {}
	bool TestNextParamAsInt(int* value)   { return NextParamAsInt(value); }
	bool TestNextParamAsBool(bool* value) { return NextParamAsBool(value); }
	bool TestNextParamAsStr(char** value) { return NextParamAsStr(value); }
};

BOOST_AUTO_TEST_CASE(TestNextParamAsTypes)
{
	{
		std::string jsonInput = R"({"params":[123,456]})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		int val1 = 0, val2 = 0;
		BOOST_CHECK(cmd.TestNextParamAsInt(&val1));
		BOOST_CHECK_EQUAL(val1, 123);
		BOOST_CHECK(cmd.TestNextParamAsInt(&val2));
		BOOST_CHECK_EQUAL(val2, 456);
		BOOST_CHECK(!cmd.TestNextParamAsInt(&val1));
	}

	{
		std::string jsonInput = R"({"params":[true,false]})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		bool val1 = false, val2 = true;
		BOOST_CHECK(cmd.TestNextParamAsBool(&val1));
		BOOST_CHECK_EQUAL(val1, true);
		BOOST_CHECK(cmd.TestNextParamAsBool(&val2));
		BOOST_CHECK_EQUAL(val2, false);
		BOOST_CHECK(!cmd.TestNextParamAsBool(&val1));
	}

	{
		std::string jsonInput = R"({"params":["abc","def"]})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		char* val1 = nullptr;
		char* val2 = nullptr;
		BOOST_CHECK(cmd.TestNextParamAsStr(&val1));
		BOOST_CHECK_EQUAL(std::string(val1), "abc");
		BOOST_CHECK(cmd.TestNextParamAsStr(&val2));
		BOOST_CHECK_EQUAL(std::string(val2), "def");
		BOOST_CHECK(!cmd.TestNextParamAsStr(&val1));
	}
}

BOOST_AUTO_TEST_CASE(TestConfigCommandsParsing)
{
	{
		std::string jsonInput = R"({"params":[true]})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		bool loadFromDisk = false;
		BOOST_CHECK(cmd.TestNextParamAsBool(&loadFromDisk));
		BOOST_CHECK_EQUAL(loadFromDisk, true);
	}

	{
		std::string jsonInput = R"({"params":[]})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		bool loadFromDisk = false;
		BOOST_CHECK(!cmd.TestNextParamAsBool(&loadFromDisk));
		BOOST_CHECK_EQUAL(loadFromDisk, false);
	}
}

BOOST_AUTO_TEST_CASE(TestAppendCommand)
{
	std::string jsonInput = R"({"method":"append","params":["test.nzb","PD94bWw...","",0,false,false,"",0,"FORCE"],"id":1})";

	MockXmlCommandAll cmd;
	cmd.SetRequest(&jsonInput[0]);
	cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
	cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
	cmd.PrepareParams();

	char* strVal = nullptr;
	int intVal = 0;
	bool boolVal = false;

	// filename
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "test.nzb");

	// content (base64)
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "PD94bWw...");

	// category
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "");

	// priority
	BOOST_CHECK(cmd.TestNextParamAsInt(&intVal));
	BOOST_CHECK_EQUAL(intVal, 0);

	// addTop
	BOOST_CHECK(cmd.TestNextParamAsBool(&boolVal));
	BOOST_CHECK_EQUAL(boolVal, false);

	// addPaused
	BOOST_CHECK(cmd.TestNextParamAsBool(&boolVal));
	BOOST_CHECK_EQUAL(boolVal, false);

	// dupeKey
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "");

	// dupeScore
	BOOST_CHECK(cmd.TestNextParamAsInt(&intVal));
	BOOST_CHECK_EQUAL(intVal, 0);

	// dupeMode
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "FORCE");

	// v13 Parameters loop - must be exhausted (cursor must not leak into "id")
	BOOST_CHECK(!cmd.TestNextParamAsStr(&strVal));
}

BOOST_AUTO_TEST_CASE(TestEditQueueWithIdAfter)
{
	// Nested array as last param with "id" after "params"
	std::string jsonInput = R"({"params":["PausePost", "", [123, 456]],"id":1})";

	MockXmlCommandAll cmd;
	cmd.SetRequest(&jsonInput[0]);
	cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
	cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
	cmd.PrepareParams();

	char* strVal = nullptr;
	int intVal = 0;

	// editCommand
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "PausePost");

	// Optional offset (v17+) - reads "" which is not numeric
	BOOST_CHECK(!cmd.TestNextParamAsInt(&intVal));

	// args
	BOOST_CHECK(cmd.TestNextParamAsStr(&strVal));
	BOOST_CHECK_EQUAL(std::string(strVal), "");

	// IDs from nested array
	BOOST_CHECK(cmd.TestNextParamAsInt(&intVal));
	BOOST_CHECK_EQUAL(intVal, 123);
	BOOST_CHECK(cmd.TestNextParamAsInt(&intVal));
	BOOST_CHECK_EQUAL(intVal, 456);

	// No more IDs
	BOOST_CHECK(!cmd.TestNextParamAsInt(&intVal));
}

BOOST_AUTO_TEST_CASE(TestWhitespaceAfterLastParam)
{
	// Space before closing bracket
	{
		std::string jsonInput = R"({"params":[123 ],"id":1})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		int val = 0;
		BOOST_CHECK(cmd.TestNextParamAsInt(&val));
		BOOST_CHECK_EQUAL(val, 123);
		BOOST_CHECK(!cmd.TestNextParamAsInt(&val));
	}

	// Newline before closing bracket
	{
		std::string jsonInput = "{\"params\":[123\n],\"id\":1}";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		int val = 0;
		BOOST_CHECK(cmd.TestNextParamAsInt(&val));
		BOOST_CHECK_EQUAL(val, 123);
		BOOST_CHECK(!cmd.TestNextParamAsInt(&val));
	}

	// String with trailing space before closing bracket
	{
		std::string jsonInput = R"({"params":["abc" ],"id":1})";
		MockXmlCommandAll cmd;
		cmd.SetRequest(&jsonInput[0]);
		cmd.SetProtocol(XmlRpcProcessor::rpJsonRpc);
		cmd.SetHttpMethod(XmlRpcProcessor::hmPost);
		cmd.PrepareParams();

		char* val = nullptr;
		BOOST_CHECK(cmd.TestNextParamAsStr(&val));
		BOOST_CHECK_EQUAL(std::string(val), "abc");
		BOOST_CHECK(!cmd.TestNextParamAsStr(&val));
	}
}

// the reply to one request from the control user, as the web server would send it
// (jsonP: option JsonP)
static std::string RpcReply(const char* url, XmlRpcProcessor::EHttpMethod httpMethod, const char* body = "",
	bool jsonP = true)
{
	std::string request(body);
	XmlRpcProcessor processor;
	processor.SetUrl(url);
	processor.SetHttpMethod(httpMethod);
	processor.SetUserAccess(XmlRpcProcessor::uaControl);
	processor.SetJsonP(jsonP);
	processor.SetRequest(&request[0]);
	processor.Execute();
	return processor.GetResponse() ? processor.GetResponse() : "";
}

static bool HasErrorCode(const std::string& reply, int code)
{
	return reply.find("\"code\" : " + std::to_string(code) + ",") != std::string::npos;
}

// JSON-P is a GET that any web page can make a browser send: it runs only the methods
// that read. Each method below changes something; run without parameters it would
// answer its own "Invalid parameter" (code 2), so a code 4 shows it didn't run.
BOOST_AUTO_TEST_CASE(TestJsonPRefusesUnsafeMethods)
{
	for (const char* method : {"editqueue", "readurl", "append"})
	{
		std::string reply = RpcReply(("/jsonprpc/" + std::string(method) + "?=cb").c_str(), XmlRpcProcessor::hmGet);
		BOOST_TEST_INFO(method << ": " << reply);
		BOOST_CHECK(HasErrorCode(reply, 4));
		BOOST_CHECK(!HasErrorCode(reply, 2));
		// through the callback, so the page that loaded it sees the refusal
		BOOST_CHECK(reply.rfind("cb(", 0) == 0);
		BOOST_CHECK(!reply.empty() && reply.back() == ')');
	}
}

BOOST_AUTO_TEST_CASE(TestJsonPRunsReadingMethods)
{
	std::string reply = RpcReply("/jsonprpc/version?=cb", XmlRpcProcessor::hmGet);
	BOOST_TEST_INFO(reply);
	BOOST_CHECK(reply.rfind("cb(", 0) == 0);
	BOOST_CHECK(reply.find("\"result\"") != std::string::npos);
	BOOST_CHECK(reply.find("\"error\"") == std::string::npos);
}

BOOST_AUTO_TEST_CASE(TestPlainGetRefusesUnsafeMethods)
{
	std::string reply = RpcReply("/jsonrpc/editqueue", XmlRpcProcessor::hmGet);
	BOOST_TEST_INFO(reply);
	BOOST_CHECK(HasErrorCode(reply, 4));
}

BOOST_AUTO_TEST_CASE(TestPostRunsUnsafeMethods)
{
	// it runs, and answers that its parameter is missing
	std::string reply = RpcReply("/jsonrpc", XmlRpcProcessor::hmPost, R"({"method":"editqueue","params":[],"id":1})");
	BOOST_TEST_INFO(reply);
	BOOST_CHECK(HasErrorCode(reply, 2));
	BOOST_CHECK(!HasErrorCode(reply, 4));
}

// JSON-P is off unless option JsonP turns it on: nothing runs, not even a reading method
BOOST_AUTO_TEST_CASE(TestJsonPIsOffByDefault)
{
	std::string request;
	XmlRpcProcessor processor;
	processor.SetUrl("/jsonprpc/version?=cb");
	processor.SetHttpMethod(XmlRpcProcessor::hmGet);
	processor.SetUserAccess(XmlRpcProcessor::uaControl);
	processor.SetRequest(&request[0]);
	processor.Execute();
	std::string reply = processor.GetResponse();
	BOOST_TEST_INFO(reply);
	BOOST_CHECK(HasErrorCode(reply, 403));
	BOOST_CHECK(reply.find("\"result\"") == std::string::npos);
	// through the callback, so the page that loaded it sees why
	BOOST_CHECK(reply.rfind("cb(", 0) == 0);
}

static const char* const ControlPasswordMasked = "\"Name\" : \"ControlPassword\",\n\"Value\" : \"***\"";

// any web page can read a JSON-P answer: even with the control user's login it gets
// the protected options as "***", like the restricted user
BOOST_AUTO_TEST_CASE(TestJsonPReadsAsRestrictedUser)
{
	// Earlier tests destroy their own Options instances, which clears
	// g_Options. Config RPC reads the options, so own them for this test.
	struct RestoreOptions
	{
		Options* previous = g_Options;
		~RestoreOptions() { g_Options = previous; }
	} restoreOptions;
	Options::CmdOptList cmdOpts;
	cmdOpts.push_back("SevenZipCmd=7z");
	cmdOpts.push_back("UnrarCmd=unrar");
	Options options(&cmdOpts, nullptr);

	std::string reply = RpcReply("/jsonprpc/config?=cb", XmlRpcProcessor::hmGet);
	BOOST_CHECK(reply.rfind("cb(", 0) == 0);
	BOOST_CHECK(reply.find(ControlPasswordMasked) != std::string::npos);
	BOOST_CHECK(reply.find("tegbzn6789") == std::string::npos);

	// the control user's own requests still see the value
	std::string direct = RpcReply("/jsonrpc", XmlRpcProcessor::hmPost, R"({"method":"config","params":[],"id":1})");
	BOOST_CHECK(direct.find(ControlPasswordMasked) == std::string::npos);
	BOOST_CHECK(direct.find("\"Name\" : \"ControlPassword\",\n\"Value\" : \"tegbzn6789\"") != std::string::npos);
}

BOOST_AUTO_TEST_CASE(TestProtectedOptions)
{
	BOOST_CHECK(Options::OptEntry("ControlPassword", "x").Restricted());
	BOOST_CHECK(Options::OptEntry("Server1.Username", "x").Restricted());
	// the indexer's API key, and the switch for JSON-P itself
	BOOST_CHECK(Options::OptEntry("DupeSearchApiKey", "x").Restricted());
	BOOST_CHECK(Options::OptEntry("JsonP", "yes").Restricted());
	BOOST_CHECK(!Options::OptEntry("DupeSearchUrl", "x").Restricted());
	BOOST_CHECK(!Options::OptEntry("DupeCheck", "yes").Restricted());
}

BOOST_AUTO_TEST_CASE(TlsCipherRejectsRestrictedAndAddAccounts)
{
	for (const char* method : {"tlscipherstart", "tlscipherstatus", "tlsciphercancel"})
	{
		for (auto access : {XmlRpcProcessor::uaRestricted, XmlRpcProcessor::uaAdd})
		{
			std::string request = std::string("{\"method\":\"") + method + "\",\"params\":[],\"id\":1}";
			XmlRpcProcessor rpc;
			rpc.SetUserAccess(access); rpc.SetHttpMethod(XmlRpcProcessor::hmPost); rpc.SetUrl("/jsonrpc");
			rpc.SetRequest(request.data()); rpc.Execute();
			BOOST_CHECK(std::string(rpc.GetResponse()).find("Access denied") != std::string::npos);
		}
	}
}

BOOST_AUTO_TEST_CASE(TlsCipherRejectsGetAndMalformedPost)
{
	for (const char* method : {"tlscipherstart", "tlscipherstatus", "tlsciphercancel"})
	{
		std::string url = std::string("/jsonrpc/") + method;
		std::string reply = RpcReply(url.c_str(), XmlRpcProcessor::hmGet);
		BOOST_CHECK(reply.find("\"error\"") != std::string::npos);
	}
	for (const char* request : {
		R"({"method":"tlscipherstart","params":["host.invalid"],"id":1})",
		R"({"method":"tlscipherstatus","params":[42],"id":1})",
		R"({"method":"tlsciphercancel","params":[],"id":1})",
		R"({"method":"tlscipherstatus","params":["bad\u0000id"],"id":1})",
		R"({"method":"tlscipherstatus","params":["one","two"],"id":1})"})
	{
		std::string reply = RpcReply("/jsonrpc", XmlRpcProcessor::hmPost, request);
		BOOST_CHECK(reply.find("Invalid cipher") != std::string::npos);
	}
}

BOOST_AUTO_TEST_CASE(TlsCipherStatusIsStructuredAndReportsUnavailableBackend)
{
	std::string reply = RpcReply("/jsonrpc", XmlRpcProcessor::hmPost, R"({"method":"tlscipherstatus","params":[],"id":1})");
	auto document = Json::Deserialize(reply);
	BOOST_REQUIRE(document && document->is_object());
	BOOST_REQUIRE(document->as_object().contains("result"));
	const auto& result = document->as_object().at("result");
	BOOST_REQUIRE(result.is_object());
	BOOST_REQUIRE(result.as_object().contains("Available"));
#if defined(NZBGET_USE_RUST) && !defined(DISABLE_TLS) && (defined(__APPLE__) || defined(__linux__))
	BOOST_CHECK(result.as_object().at("Available").as_bool());
	std::string stale = RpcReply("/jsonrpc", XmlRpcProcessor::hmPost, R"({"method":"tlscipherstatus","params":["unknown-fixture-job"],"id":1})");
	BOOST_CHECK(stale.find("unknown cipher job") != std::string::npos);
#else
	BOOST_CHECK(!result.as_object().at("Available").as_bool());
	BOOST_CHECK(reply.find("unavailable") != std::string::npos);
#endif
	BOOST_CHECK(reply.size() <= 1024 * 1024);
}

BOOST_AUTO_TEST_SUITE_END()
