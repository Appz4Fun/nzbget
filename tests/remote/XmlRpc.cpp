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

// the reply to one request, as the web server would send it
static std::string RpcReply(const char* url, XmlRpcProcessor::EHttpMethod httpMethod, const char* body = "")
{
	std::string request(body);
	XmlRpcProcessor processor;
	processor.SetUrl(url);
	processor.SetHttpMethod(httpMethod);
	processor.SetUserAccess(XmlRpcProcessor::uaControl);
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

BOOST_AUTO_TEST_SUITE_END()
