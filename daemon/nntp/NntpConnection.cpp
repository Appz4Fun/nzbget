/*
 *  This file is part of nzbget. See <https://nzbget.com>.
 *
 *  Copyright (C) 2004 Sven Henkel <sidddy@users.sourceforge.net>
 *  Copyright (C) 2007-2016 Andrey Prygunkov <hugbug@users.sourceforge.net>
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
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */


#include "nzbget.h"
#include "Log.h"
#include "NntpConnection.h"
#ifdef NZBGET_USE_RUST
#include <exception>
#include "nzbget_rs.h"
#endif
#include "Connection.h"
#include "NewsServer.h"

static const int CONNECTION_LINEBUFFER_SIZE = 1024*10;

NntpConnection::NntpConnection(NewsServer* newsServer) :
	Connection(newsServer->GetHost(), newsServer->GetPort(), newsServer->GetTls()), m_newsServer(newsServer)
{
	m_lineBuf.Reserve(CONNECTION_LINEBUFFER_SIZE);
	SetCipher(newsServer->GetCipher());
	SetIPVersion(newsServer->GetIpVersion() == 4 ? Connection::ipV4 :
		newsServer->GetIpVersion() == 6 ? Connection::ipV6 : Connection::ipAuto);
	
#ifndef DISABLE_TLS
	SetCertVerifLevel(newsServer->GetCertVerificationLevel());
#endif
}

#ifdef NZBGET_USE_RUST
// a callback that threw stops the exchange; the exception is rethrown after
// Rust returned
struct NntpConnection::RsExchange
{
	NntpConnection* connection;
	std::exception_ptr error;

	template <typename F>
	static int Call(void* ctx, F f) noexcept
	{
		RsExchange* exchange = static_cast<RsExchange*>(ctx);
		try
		{
			f(exchange->connection);
			return 0;
		}
		catch (...)
		{
			exchange->error = std::current_exception();
			return -1;
		}
	}

	NzbgetRsNntpIo Io()
	{
		NewsServer* server = connection->m_newsServer;
		return {this, RsWriteLine, RsReadLine, RsReportError, RsDebug, RsCancelled, server->GetUser(),
			server->GetPassword(), server->GetName(), server->GetHost(), connection->GetHost()};
	}

	void Rethrow()
	{
		if (error)
		{
			std::rethrow_exception(error);
		}
	}
};

int NntpConnection::RsWriteLine(void* ctx, const char* line)
{
	return RsExchange::Call(ctx, [line](NntpConnection* c) { c->WriteLine(line); });
}

int NntpConnection::RsReadLine(void* ctx, char** line)
{
	return RsExchange::Call(ctx, [line](NntpConnection* c) { *line = c->ReadLine(c->m_lineBuf, c->m_lineBuf.Size(), nullptr); });
}

int NntpConnection::RsReportError(void* ctx, const char* prefix, const char* arg)
{
	return RsExchange::Call(ctx, [prefix, arg](NntpConnection* c) { c->ReportError(prefix, arg, false, 0); });
}

int NntpConnection::RsDebug(void* ctx, const char* msg)
{
	return RsExchange::Call(ctx, [msg](NntpConnection*) { debug("%s", msg); });
}

int NntpConnection::RsCancelled(void* ctx, int* cancelled)
{
	return RsExchange::Call(ctx, [cancelled](NntpConnection* c) { *cancelled = c->GetStatus() == csCancelled; });
}

#endif

#ifdef NZBGET_USE_RUST
const char* NntpConnection::Request(const char* req)
{
	if (!req)
	{
		return nullptr;
	}

	// rust/src/nntp.rs: the request, and a login when the server asks for one
	RsExchange exchange{this, nullptr};
	NzbgetRsNntpIo io = exchange.Io();
	int authError = m_authError, authRejected = m_authRejected;
	char* answer = nullptr;
	nzbget_rs_nntp_request(&io, req, &authError, &authRejected, &answer);
	m_authError = authError;
	m_authRejected = authRejected;
	exchange.Rethrow();
	return answer;
}
#else
const char* NntpConnection::Request(const char* req)
{
	if (!req)
	{
		return nullptr;
	}

	m_authError = false;
	m_authRejected = false;

	WriteLine(req);

	char* answer = ReadLine(m_lineBuf, m_lineBuf.Size(), nullptr);

	if (!answer)
	{
		return nullptr;
	}

	if (!strncmp(answer, "480", 3))
	{
		debug("%s requested authorization", GetHost());

		if (!Authenticate())
		{
			return nullptr;
		}

		//try again
		WriteLine(req);
		answer = ReadLine(m_lineBuf, m_lineBuf.Size(), nullptr);
	}

	return answer;
}
#endif

bool NntpConnection::Authenticate()
{
	if (strlen(m_newsServer->GetUser()) == 0 || strlen(m_newsServer->GetPassword()) == 0)
	{
		ReportError("Could not connect to %s: server requested authorization but username/password are not set in settings",
			m_newsServer->GetHost(), false, 0);
		m_authError = true;
		return false;
	}

	m_authError = !AuthInfoUser(0);
	return !m_authError;
}

bool NntpConnection::AuthInfoUser(int recur)
{
	if (recur > 10)
	{
		return false;
	}

	WriteLine(BString<1024>("AUTHINFO USER %s\r\n", m_newsServer->GetUser()));

	char* answer = ReadLine(m_lineBuf, m_lineBuf.Size(), nullptr);
	if (!answer)
	{
		ReportErrorAnswer("Authorization for %s (%s) failed: Connection closed by remote host", nullptr);
		return false;
	}

	if (!strncmp(answer, "281", 3))
	{
		debug("Authorization for %s successful", GetHost());
		return true;
	}
	else if (!strncmp(answer, "381", 3))
	{
		return AuthInfoPass(++recur);
	}
	else if (!strncmp(answer, "480", 3))
	{
		return AuthInfoUser(++recur);
	}

	if (char* p = strrchr(answer, '\r')) *p = '\0'; // remove last CRLF from error message
	m_authRejected = !strncmp(answer, "502", 3);

	if (GetStatus() != csCancelled)
	{
		ReportErrorAnswer("Authorization for %s (%s) failed: %s", answer);
	}
	return false;
}

bool NntpConnection::AuthInfoPass(int recur)
{
	if (recur > 10)
	{
		return false;
	}

	WriteLine(BString<1024>("AUTHINFO PASS %s\r\n", m_newsServer->GetPassword()));

	char* answer = ReadLine(m_lineBuf, m_lineBuf.Size(), nullptr);
	if (!answer)
	{
		ReportErrorAnswer("Authorization failed for %s (%s): Connection closed by remote host", nullptr);
		return false;
	}
	else if (!strncmp(answer, "2", 1))
	{
		debug("Authorization for %s successful", GetHost());
		return true;
	}
	else if (!strncmp(answer, "381", 3))
	{
		return AuthInfoPass(++recur);
	}

	if (char* p = strrchr(answer, '\r')) *p = '\0'; // remove last CRLF from error message
	m_authRejected = !strncmp(answer, "502", 3);

	if (GetStatus() != csCancelled)
	{
		ReportErrorAnswer("Authorization for %s (%s) failed: %s", answer);
	}
	return false;
}

#ifdef NZBGET_USE_RUST
const char* NntpConnection::JoinGroup(const char* grp)
{
	if (!m_activeGroup.Empty() && !strcmp(m_activeGroup, grp))
	{
		// already in group
		strcpy(m_lineBuf, "211 ");
		return m_lineBuf;
	}

	// rust/src/nntp.rs
	RsExchange exchange{this, nullptr};
	NzbgetRsNntpIo io = exchange.Io();
	int authError = m_authError, authRejected = m_authRejected;
	char* answer = nullptr;
	int joined = 0;
	nzbget_rs_nntp_join_group(&io, grp, &authError, &authRejected, &answer, &joined);
	m_authError = authError;
	m_authRejected = authRejected;
	exchange.Rethrow();
	if (joined)
	{
		m_activeGroup = grp;
	}
	return answer;
}
#else
const char* NntpConnection::JoinGroup(const char* grp)
{
	if (!m_activeGroup.Empty() && !strcmp(m_activeGroup, grp))
	{
		// already in group
		strcpy(m_lineBuf, "211 ");
		return m_lineBuf;
	}

	const char* answer = Request(BString<1024>("GROUP %s\r\n", grp));

	if (answer && !strncmp(answer, "2", 1))
	{
		debug("Changed group to %s on %s", grp, GetHost());
		m_activeGroup = grp;
	}
	else
	{
		debug("Error changing group on %s to %s: %s.", GetHost(), grp, answer);
	}

	return answer;
}
#endif

#ifdef NZBGET_USE_RUST
bool NntpConnection::Connect()
{
	debug("Opening connection to %s", GetHost());

	if (m_status == csConnected)
	{
		return true;
	}
	m_authRejected = false;
	m_activeGroup = nullptr;

	if (!Connection::Connect())
	{
		return false;
	}

	// rust/src/nntp.rs: the greeting, and the login when one is set
	RsExchange exchange{this, nullptr};
	NzbgetRsNntpIo io = exchange.Io();
	int authError = m_authError, authRejected = m_authRejected;
	int result = 0;
	nzbget_rs_nntp_handshake(&io, &authError, &authRejected, &result);
	m_authError = authError;
	m_authRejected = authRejected;
	exchange.Rethrow();
	if (result == 1)
	{
		Disconnect();
		return false;
	}
	return result == 0;
}
#else
bool NntpConnection::Connect()
{
	debug("Opening connection to %s", GetHost());

	if (m_status == csConnected)
	{
		return true;
	}
	m_authRejected = false;
	m_activeGroup = nullptr;

	if (!Connection::Connect())
	{
		return false;
	}

	char* answer = ReadLine(m_lineBuf, m_lineBuf.Size(), nullptr);

	if (!answer)
	{
		ReportErrorAnswer("Connection to %s (%s) failed: Connection closed by remote host", nullptr);
		Disconnect();
		return false;
	}

	if (strncmp(answer, "2", 1))
	{
		ReportErrorAnswer("Connection to %s (%s) failed: %s", answer);
		Disconnect();
		return false;
	}

	if ((strlen(m_newsServer->GetUser()) > 0 && strlen(m_newsServer->GetPassword()) > 0) &&
		!Authenticate())
	{
		return false;
	}

	debug("Connection to %s established", GetHost());

	return true;
}
#endif

bool NntpConnection::Disconnect()
{
	if (m_status == csConnected)
	{
		Request("quit\r\n");
	}
	// also when the connection broke (a timeout, a reset) or was cancelled: kept,
	// the next connection skipped GROUP for that group, and a server that needs
	// it answered "no such article"
	m_activeGroup = nullptr;
	return Connection::Disconnect();
}

void NntpConnection::ReportErrorAnswer(const char* msgPrefix, const char* answer)
{
	BString<1024> errStr(msgPrefix, m_newsServer->GetName(), m_newsServer->GetHost(), answer);
	// the server's answer is in it: not a format
	ReportError("%s", errStr, false, 0);
}
