#ifndef NZBGET_SOCKET_DEADLINE_H
#define NZBGET_SOCKET_DEADLINE_H

#include <chrono>
#include <functional>
#include <algorithm>
#include <cstdint>
#include <cerrno>
#ifndef WIN32
#include <poll.h>
#endif

// Optional probe-only deadline. Ordinary download sockets keep their existing I/O.
struct SocketDeadline
{
	std::chrono::steady_clock::time_point end;
	std::function<bool()> cancelled;
	bool Stopped() const { return std::chrono::steady_clock::now() >= end || (cancelled && cancelled()); }
	bool Wait(SOCKET socket, bool read, bool write) const
	{
		while (!Stopped())
		{
			auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now()).count();
			int milliseconds = static_cast<int>(std::max<int64_t>(1, std::min<int64_t>(50, remaining)));
#ifdef WIN32
			fd_set reads, writes;
			FD_ZERO(&reads); FD_ZERO(&writes);
			if (read) FD_SET(socket, &reads);
			if (write) FD_SET(socket, &writes);
			timeval timeout{milliseconds / 1000, (milliseconds % 1000) * 1000};
			int result = select(0, &reads, &writes, nullptr, &timeout);
			if (result < 0 && WSAGetLastError() != WSAEINTR) return false;
#else
			pollfd descriptor{socket, static_cast<short>((read ? POLLIN : 0) | (write ? POLLOUT : 0)), 0};
			int result = poll(&descriptor, 1, milliseconds);
			if (result < 0 && errno != EINTR) return false;
#endif
			if (result > 0) return !Stopped();
		}
		return false;
	}
};
#endif
