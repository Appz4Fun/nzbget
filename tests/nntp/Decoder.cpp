/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2025-2026 Denis <denis@nzbget.com>
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

#include <boost/test/unit_test.hpp>
#include "Decoder.h"
#include "YEncoder.h"

BOOST_AUTO_TEST_SUITE(NNTPTest)

std::string yEncEncode(const std::string& data)
{
	std::string encodedData = "";
	for (unsigned char c : data)
	{
		encodedData += static_cast<unsigned char>((c + 42) % 256);
	}
	return encodedData;
}

/**
 * Single message:
 * 
 * =ybegin line=128 size=111401 name=al_larsonbw030_ball.jpg\r\n
 * )_)=J*:tpsp*++++V+V**)_*m*0./0/.00/011024:44334>896:A>....\r\n
 * ...Â´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÌ´RÍ©)_\r\n
 * =yend size=111401\r\n
 * .\r\n
*/
BOOST_AUTO_TEST_CASE(SingleMessageTest)
{
	Decoder decoder;
	decoder.SetCrcCheck(true);
	std::stringstream ss;

	const std::string data = "nzbget";
	const std::string crc = "a30bff0d";
	const std::string filename = "name.dat";
	const std::string encodedData = yEncEncode(data);

	ss << "=ybegin line=128 size=" << data.size() << " name=" << filename << "\r\n";
	ss << encodedData << "\r\n";
	ss << "=yend size=" << data.size() << " crc32=" << crc << "\r\n";
	ss << ".\r\n";

	std::string msg = ss.str();

	int len = decoder.DecodeBuffer(msg.data(), msg.size());

	auto status = decoder.Check();
	auto size = decoder.GetSize();
	auto calculatedCrc = decoder.GetCalculatedCrc();
	auto articleName = decoder.GetArticleFilename();
	auto format = decoder.GetFormat();
	auto eof = decoder.GetEof();
	auto res = msg.substr(0, len);

	BOOST_CHECK_EQUAL(status, Decoder::dsFinished);
	BOOST_CHECK_EQUAL(articleName, filename);
	BOOST_CHECK_EQUAL(size, 6);
	BOOST_CHECK_EQUAL(calculatedCrc, 0xa30bff0d);
	BOOST_CHECK_EQUAL(format, Decoder::efYenc);
	BOOST_CHECK_EQUAL(eof, true);
	BOOST_CHECK_EQUAL(res, "nzbget");
}

/**
 * Multipart message:
 * 
 * =ybegin part=1 total=10 line=128 size=500000 name=mybinary.dat\r\n
 * =ypart begin=1 end=100000\r\n
 * .... data\r\n
 * =yend size=100000 part=1 pcrc32=abcdef12\r\n
 * .\r\n
 * =ybegin part=5 line=128 size=500000 name=mybinary.dat\r\n
 * =ypart begin=400001 end=500000\r\n
 * .... data\r\n
 * =yend size=100000 part=10 pcrc32=12a45c78 crc32=abcdef12\r\n
 * .\r\n
*/
BOOST_AUTO_TEST_CASE(MultipartMessageTest)
{
	Decoder decoder;
	decoder.SetCrcCheck(true);
	std::stringstream ss;

	const std::string crc = "a30bff0d";
	const std::string data = "nzb";
	const std::string encodedData = yEncEncode(data);
	const std::string pcrc = "cb64ae30";
	const std::string filename = "name.dat";

	const std::string data2 = "get";
	const std::string encodedData2 = yEncEncode(data2);
	const std::string pcrc2 = "fd3b2e70";
	const size_t totalSize = data.size() + data2.size();

	ss << "=ybegin part=1 total=2 line=128 size=" << totalSize << " name=" << filename << "\r\n";
	ss << "=ypart begin=1 end=" << data.size() << "\r\n";
	ss << encodedData << "\r\n";
	ss << "=yend size=" << data.size() << " pcrc32=" << pcrc << "\r\n";
	ss << ".\r\n";

	std::string msg = ss.str();
	ss.str("");

	ss << "=ybegin part=2 total=2 line=128 size=" << totalSize << " name=" << filename << "\r\n";
	ss << "=ypart begin=" << data.size() + 1 << " end=" << totalSize << "\r\n";
	ss << encodedData2 << "\r\n";
	ss << "=yend size=" << data2.size() << " pcrc32=" << pcrc2 << " crc32=" << crc << "\r\n";
	ss << ".\r\n";

	std::string msg2 = ss.str();

	int len = decoder.DecodeBuffer(msg.data(), msg.size());
	{
		auto status = decoder.Check();
		auto size = decoder.GetSize();
		auto calculatedCrc = decoder.GetCalculatedCrc();
		auto articleName = decoder.GetArticleFilename();
		auto format = decoder.GetFormat();
		auto eof = decoder.GetEof();
		auto res = msg.substr(0, len);

		BOOST_CHECK_EQUAL(status, Decoder::dsFinished);
		BOOST_CHECK_EQUAL(articleName, filename);
		BOOST_CHECK_EQUAL(size, totalSize);
		BOOST_CHECK_EQUAL(calculatedCrc, 0xcb64ae30);
		BOOST_CHECK_EQUAL(format, Decoder::efYenc);
		BOOST_CHECK_EQUAL(eof, true);
		BOOST_CHECK_EQUAL(res, "nzb");
	}

	decoder.Clear();
	decoder.SetCrcCheck(true);

	int len2 = decoder.DecodeBuffer(msg2.data(), msg2.size());

	auto articleName = decoder.GetArticleFilename();
	auto status = decoder.Check();
	auto size = decoder.GetSize();
	auto calculatedCrc = decoder.GetCalculatedCrc();
	auto eof = decoder.GetEof();
	auto res = msg2.substr(0, len);

	BOOST_CHECK_EQUAL(articleName, filename);
	BOOST_CHECK_EQUAL(status, Decoder::dsFinished);
	BOOST_CHECK_EQUAL(len, data2.size());
	BOOST_CHECK_EQUAL(len + len2, totalSize);
	BOOST_CHECK_EQUAL(size, totalSize);
	BOOST_CHECK_EQUAL(calculatedCrc, 0xfd3b2e70);
	BOOST_CHECK_EQUAL(eof, true);
	BOOST_CHECK_EQUAL(res, "get");
}

/**
 * Unusual multipart message where there's no \r\n separating between name=... and =ypart:
 * 
 * =ybegin part=1 total=10 line=128 size=500000 name=mybinary.dat=ypart begin=1 end=100000\r\n
 * .... data\r\n
 * =yend size=100000 part=1 pcrc32=abcdef12\r\n
 * .\r\n
 * =ybegin part=5 line=128 size=500000 name=mybinary.dat\r\n
 * =ypart begin=400001 end=500000\r\n
 * .... data\r\n
 * =yend size=100000 part=10 pcrc32=12a45c78 crc32=abcdef12\r\n
 * .\r\n
*/
BOOST_AUTO_TEST_CASE(UnusualMultipartMessageTest)
{
	Decoder decoder;
	decoder.SetCrcCheck(true);
	std::stringstream ss;

	const std::string crc = "a30bff0d";
	const std::string data = "nzb";
	const std::string encodedData = yEncEncode(data);
	const std::string pcrc = "cb64ae30";
	const std::string filename = "name.dat";

	const std::string data2 = "get";
	const std::string encodedData2 = yEncEncode(data2);
	const std::string pcrc2 = "fd3b2e70";
	const size_t totalSize = data.size() + data2.size();

	ss << "=ybegin part=1 total=2 line=128 size=" << totalSize << " name=" << filename;
	ss << "=ypart begin=1 end=" << data.size() << "\r\n";
	ss << encodedData << "\r\n";
	ss << "=yend size=" << data.size() << " pcrc32=" << pcrc << "\r\n";
	ss << ".\r\n";

	std::string msg = ss.str();
	ss.str("");

	ss << "=ybegin part=2 total=2 line=128 size=" << totalSize << " name=" << filename;
	ss << "=ypart begin=" << data.size() + 1 << " end=" << totalSize << "\r\n";
	ss << encodedData2 << "\r\n";
	ss << "=yend size=" << data2.size() << " pcrc32=" << pcrc2 << " crc32=" << crc << "\r\n";
	ss << ".\r\n";

	std::string msg2 = ss.str();

	int len = decoder.DecodeBuffer(msg.data(), msg.size());
	{
		auto status = decoder.Check();
		auto size = decoder.GetSize();
		auto calculatedCrc = decoder.GetCalculatedCrc();
		auto articleName = decoder.GetArticleFilename();
		auto format = decoder.GetFormat();
		auto eof = decoder.GetEof();
		auto res = msg.substr(0, len);

		BOOST_CHECK_EQUAL(status, Decoder::dsFinished);
		BOOST_CHECK_EQUAL(articleName, filename);
		BOOST_CHECK_EQUAL(size, totalSize);
		BOOST_CHECK_EQUAL(calculatedCrc, 0xcb64ae30);
		BOOST_CHECK_EQUAL(format, Decoder::efYenc);
		BOOST_CHECK_EQUAL(eof, true);
		BOOST_CHECK_EQUAL(res, "nzb");
	}

	decoder.Clear();
	decoder.SetCrcCheck(true);

	int len2 = decoder.DecodeBuffer(msg2.data(), msg2.size());

	auto articleName = decoder.GetArticleFilename();
	auto status = decoder.Check();
	auto size = decoder.GetSize();
	auto calculatedCrc = decoder.GetCalculatedCrc();
	auto eof = decoder.GetEof();
	auto res = msg2.substr(0, len);

	BOOST_CHECK_EQUAL(articleName, filename);
	BOOST_CHECK_EQUAL(status, Decoder::dsFinished);
	BOOST_CHECK_EQUAL(len, data2.size());
	BOOST_CHECK_EQUAL(len + len2, totalSize);
	BOOST_CHECK_EQUAL(size, totalSize);
	BOOST_CHECK_EQUAL(calculatedCrc, 0xfd3b2e70);
	BOOST_CHECK_EQUAL(eof, true);
	BOOST_CHECK_EQUAL(res, "get");
}

BOOST_AUTO_TEST_CASE(BufferOverflowTest)
{
	Decoder decoder;
	decoder.SetRawMode(true);

	constexpr int bufSize = 4096;
	auto buf = std::make_unique<char[]>(bufSize);
	memset(buf.get(), 'x', bufSize);

	int len = decoder.DecodeBuffer(buf.get(), bufSize);
	BOOST_CHECK_EQUAL(len, bufSize);
	BOOST_CHECK_EQUAL(decoder.GetEof(), false);
}


BOOST_AUTO_TEST_CASE(UuDecodeOutputBoundTest)
{
	// A uuencoded line decodes to fewer bytes than it has characters, but a line
	// carried over from the previous read decodes on top of what the call was given:
	// the output can exceed the input by up to one line (63 bytes). Callers keep 128
	// bytes past what they read into the buffer for it (it was written past its end).
	Decoder decoder;
	std::string first = "begin 644 f.bin\r\n_" + std::string(62, 'A');	// a partial line
	std::vector<char> buffer(first.size() + 128);
	memcpy(buffer.data(), first.data(), first.size());
	decoder.DecodeBuffer(buffer.data(), (int)first.size());

	std::string next = std::string(22, 'A') + "\r\n";
	while (next.size() < 512 - 87)
	{
		next += "_" + std::string(84, 'A') + "\r\n";
	}
	std::vector<char> second(next.size() + 128, 'Z');
	memcpy(second.data(), next.data(), next.size());
	int outlen = decoder.DecodeBuffer(second.data(), (int)next.size());
	BOOST_CHECK_GT(outlen, 0);
	BOOST_CHECK_LE(outlen, (int)next.size() + 63);
}

BOOST_AUTO_TEST_CASE(UuDecodeShortLineTest)
{
	// a line shorter than its length character says ("M" = 45 bytes in 60
	// characters, here 46): the decoder read the missing characters from past
	// the line. They count as spaces (zero bits) now, the same as the full line.
	auto decode = [](const std::string& line)
	{
		Decoder decoder;
		std::string text = "begin 644 f.bin\r\n" + line + "\r\n";
		std::vector<char> buffer(text.size() + 128, 'Z');
		memcpy(buffer.data(), text.data(), text.size());
		int outlen = decoder.DecodeBuffer(buffer.data(), (int)text.size());
		return std::string(buffer.data(), outlen > 0 ? outlen : 0);
	};
	std::string shortLine = "M" + std::string(46, '!');
	std::string fullLine = shortLine + std::string(14, ' ');
	std::string got = decode(shortLine);
	BOOST_CHECK_EQUAL(got.size(), 45);
	BOOST_CHECK(got == decode(fullLine));
}

namespace
{
	// Raw decoding must only inspect input, including at the public ABI boundary.
	void CheckRawChunk(Decoder& decoder, const std::string& chunk, bool eof)
	{
		std::vector<char> buffer(32 + chunk.size() + 128 + 32, 'Z');
		memcpy(buffer.data() + 32, chunk.data(), chunk.size());
		const auto before = buffer;
		BOOST_CHECK_EQUAL(decoder.DecodeBuffer(buffer.data() + 32, (int)chunk.size()), (int)chunk.size());
		BOOST_CHECK(buffer == before); // Input, 128-byte slack and both canaries.
		BOOST_CHECK_EQUAL(decoder.GetEof(), eof);
	}

	std::string CapturedRawWire()
	{
		// The retained 128-byte Stage2 wire, not a new fragmentation schedule.
		return "fixture raw\r\n" + std::string(110, 'R') + "\r\n.\r\n";
	}
}

BOOST_AUTO_TEST_CASE(RawTerminatorPartitions)
{
	const std::string marker = "\r\n.\r\n";
	for (unsigned splits = 0; splits < 16; ++splits)
	{
		BOOST_TEST_CONTEXT("split mask " << splits)
		{
			Decoder decoder;
			decoder.SetRawMode(true);
			size_t start = 0;
			for (size_t end = 1; end <= marker.size(); ++end)
			{
				if (end == marker.size() || (splits & (1u << (end - 1))))
				{
					CheckRawChunk(decoder, marker.substr(start, end - start), end == marker.size());
					start = end;
				}
			}
		}
	}
}

BOOST_AUTO_TEST_CASE(RawCapturedFragmentSchedule)
{
	const std::string wire = CapturedRawWire();
	BOOST_REQUIRE_EQUAL(wire.size(), 128);
	const size_t chunks[] = {1, 6, 17, 17, 17, 17, 17, 17, 15, 1, 1, 1, 1};
	Decoder decoder;
	decoder.SetRawMode(true);
	size_t offset = 0;
	for (size_t len : chunks)
	{
		CheckRawChunk(decoder, wire.substr(offset, len), offset + len == wire.size());
		offset += len;
	}
	BOOST_CHECK_EQUAL(offset, wire.size());
}

BOOST_AUTO_TEST_CASE(RawOneByteChunks)
{
	const std::string wire = CapturedRawWire();
	Decoder decoder;
	decoder.SetRawMode(true);
	for (size_t i = 0; i < wire.size(); ++i)
	{
		CheckRawChunk(decoder, wire.substr(i, 1), i + 1 == wire.size());
	}
}

BOOST_AUTO_TEST_CASE(RawPrefixOverlap)
{
	const std::vector<std::vector<std::string>> sequences = {
		{"\r", "\r", "\n", ".", "\r", "\n"},
		{"\r\n", "\r", "\n", ".", "\r", "\n"},
		{"\r\n.\r", "\r", "\n", ".", "\r", "\n"}
	};
	for (const auto& chunks : sequences)
	{
		Decoder decoder;
		decoder.SetRawMode(true);
		for (size_t i = 0; i < chunks.size(); ++i)
		{
			CheckRawChunk(decoder, chunks[i], i + 1 == chunks.size());
		}
	}
	Decoder decoder;
	decoder.SetRawMode(true);
	CheckRawChunk(decoder, "\r\n.\r\n", true);
	CheckRawChunk(decoder, ".\r\n", true);
}

BOOST_AUTO_TEST_CASE(RawNearMiss)
{
	const std::vector<std::string> wires = {
		"\r\n..\r\n", "\n.\r\n", "\r\n.\n", "\r.\r\n",
		"\r\n.x\r\n", "\r\n.\rX", std::string("\0\r\n.\0\r\n", 7)
	};
	for (const auto& wire : wires)
	{
		Decoder decoder;
		decoder.SetRawMode(true);
		for (char c : wire)
		{
			CheckRawChunk(decoder, std::string(1, c), false);
		}
	}
}

BOOST_AUTO_TEST_CASE(RawZeroLengthPolicy)
{
	const std::string prefixes[] = {"", "\r", "\r\n", "\r\n.\r"};
	const std::string continuations[] = {"x", "\n.\r\n", ".\r\n", "\n"};
	for (size_t i = 0; i < 4; ++i)
	{
		Decoder decoder;
		decoder.SetRawMode(true);
		CheckRawChunk(decoder, "\r\n.\r\nx", true);
		if (i != 0)
		{
			CheckRawChunk(decoder, prefixes[i], true);
		}
		// A non-null empty call resets the prefix; only prior state zero keeps EOF.
		CheckRawChunk(decoder, "", i == 0);
		CheckRawChunk(decoder, continuations[i], i == 0);
		CheckRawChunk(decoder, "\r\n.\r\n", true);
	}
}

BOOST_AUTO_TEST_CASE(RawClearReuse)
{
	const std::string marker = "\r\n.\r\n";
	for (size_t prefix = 1; prefix <= 4; ++prefix)
	{
		Decoder decoder;
		std::string header = "begin 644 f.bin\r\n";
		BOOST_CHECK_EQUAL(decoder.DecodeBuffer(header.data(), (int)header.size()), 0);
		BOOST_REQUIRE_EQUAL(decoder.GetFormat(), Decoder::efUx);
		decoder.SetRawMode(true);
		CheckRawChunk(decoder, marker.substr(0, prefix), false);
		decoder.Clear();
		BOOST_CHECK_EQUAL(decoder.GetEof(), false);
		BOOST_CHECK_EQUAL(decoder.GetFormat(), Decoder::efUx);
		// Returning the entire suffix also proves Clear retained raw mode.
		CheckRawChunk(decoder, marker.substr(prefix), false);
		CheckRawChunk(decoder, marker, true);
	}
}

BOOST_AUTO_TEST_CASE(RawBulkWorkingBuffers)
{
	const std::vector<std::string> wires = {
		CapturedRawWire(), std::string(65536 - 5, (char)0x80) + "\r\n.\r\n"
	};
	for (const auto& wire : wires)
	{
		Decoder decoder;
		decoder.SetRawMode(true);
		CheckRawChunk(decoder, wire, true);
	}
}

BOOST_AUTO_TEST_CASE(RawLegacyEofPolicy)
{
	const std::vector<std::vector<std::string>> sequences = {
		{"\r\n.\r\nx", "more", "\r", "x"},
		{"\r\n.\r", "\n", "x"},
		{"\r\n.", "\r\n", "x"}
	};
	const std::vector<std::vector<bool>> expected = {
		{true, true, true, false}, {false, true, true}, {false, true, false}
	};
	for (size_t i = 0; i < sequences.size(); ++i)
	{
		Decoder decoder;
		decoder.SetRawMode(true);
		for (size_t j = 0; j < sequences[i].size(); ++j)
		{
			CheckRawChunk(decoder, sequences[i][j], expected[i][j]);
		}
	}
}

BOOST_AUTO_TEST_SUITE_END()
