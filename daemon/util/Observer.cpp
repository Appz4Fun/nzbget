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
#include "Observer.h"
#include "Log.h"

void Subject::Attach(Observer* observer)
{
	m_observers.push_back(observer);
}

void Subject::Detach(Observer* observer)
{
	// one that isn't attached: erasing end() is undefined
	auto it = std::find(m_observers.begin(), m_observers.end(), observer);
	if (it != m_observers.end())
	{
		m_observers.erase(it);
	}
}

void Subject::Notify(void* aspect)
{
	debug("Notifying observers");

	for (Observer* observer : m_observers)
	{
		observer->Update(this, aspect);
	}
}
