//! Scheduler::CheckTasks' timing: which scheduled tasks are due between the
//! last check and now (local time), day by day over the check interval, with the
//! startup tasks and the reset after a clock jump. Running the tasks stays
//! C++. Dates are computed as the C++ did: gmtime_r's fields and nzbget's
//! Timegm (Boost's arithmetic, without normalizing the fields).

/// A task's schedule and its last run (0: never); NzbgetRsSchedTask in C.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Task {
    /// -1 for a startup task
    pub hours: i32,
    pub minutes: i32,
    /// bit n: weekday n + 1 (1 Monday .. 7 Sunday); 0: every day
    pub week_days: i32,
    pub last_executed: i64,
}

pub const STARTUP_TASK: i32 = -1;

/// The fields of gmtime_r used here.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tm {
    pub year: i64,
    /// 0..=11
    pub mon: i64,
    pub mday: i64,
    pub hour: i64,
    pub min: i64,
    pub sec: i64,
    /// 0 Sunday ..= 6
    pub wday: i64,
}

/// gmtime_r: a time as UTC calendar fields.
/// Only for tests using POSIX time; production uses the caller's libc, which
/// may apply leap seconds from the process timezone's TZif file.
#[cfg(test)]
pub fn gmtime(t: i64) -> Tm {
    let days = t.div_euclid(86400);
    let secs = t.rem_euclid(86400);
    // civil_from_days (Howard Hinnant)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let mday = doy - (153 * mp + 2) / 5 + 1;
    let mon = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + if mon <= 2 { 1 } else { 0 };
    Tm {
        year,
        mon: mon - 1,
        mday,
        hour: secs / 3600,
        min: secs % 3600 / 60,
        sec: secs % 60,
        wday: (days + 4).rem_euclid(7),
    }
}

fn is_leap(year: i64) -> bool {
    year % 400 == 0 || (year % 100 != 0 && year % 4 == 0)
}

fn days_from_0(year: i64) -> i64 {
    let y = year - 1;
    // C integer division (truncating), as the C++ int arithmetic
    365 * y + y / 400 - y / 100 + y / 4
}

/// nzbget's Timegm (internal_timegm, from Boost).
pub fn timegm(t: &Tm) -> i64 {
    const DAYS: [[i64; 12]; 2] = [
        [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334],
        [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335],
    ];
    let mut year = t.year;
    let mut month = t.mon;
    if month > 11 {
        year += month / 12;
        month %= 12;
    } else if month < 0 {
        let diff = (-month + 11) / 12;
        year -= diff;
        month += 12 * diff;
    }
    let day_of_year = DAYS[is_leap(year) as usize][month as usize] + t.mday - 1;
    let days = days_from_0(year) - 719162 + day_of_year;
    86400 * days + 3600 * t.hour + 60 * t.min + t.sec
}

/// The outcome of a check.
#[derive(Debug, PartialEq)]
pub struct Check {
    /// the tasks to run, by index, in order
    pub due: Vec<usize>,
    /// the clock jumped (more than 90 minutes or back): processes the tasks
    /// start aren't run for the past (m_executeProcess = false)
    pub reset: bool,
}

/// Scheduler::CheckTasks' timing for `tasks` (in the scheduler's order):
/// updates their last runs and `last_check` and returns what to run.
/// Nine entries per task normally suffice, but libc's TZif leap corrections
/// can repeat calendar dates and make this bound invalid.
pub fn check_tasks(
    tasks: &mut [Task], last_check: &mut i64, current: i64, local_offset: i64,
    gmtime: impl Fn(i64) -> Tm,
) -> Check {
    let mut r = Check { due: Vec::new(), reset: false };
    if !tasks.is_empty() {
        let diff = current - *last_check;
        if !(0..=60 * 90).contains(&diff) {
            // check all tasks for the last week
            *last_check = current - 60 * 60 * 24 * 7;
            r.reset = true;
            for t in tasks.iter_mut().filter(|t| t.hours != STARTUP_TASK) {
                t.last_executed = 0;
            }
        }
        let local_current = current + local_offset;
        let local_last_check = *last_check + local_offset;
        let tm_current = gmtime(local_current);
        let mut tm_loop = gmtime(local_last_check);
        tm_loop.hour = tm_current.hour;
        tm_loop.min = tm_current.min;
        tm_loop.sec = tm_current.sec;
        let mut lp = timegm(&tm_loop);
        while lp <= local_current {
            for (k, task) in tasks.iter_mut().enumerate() {
                if task.last_executed == lp {
                    continue;
                }
                // the loop day's date with the task's time (the weekday is the
                // loop day's: Timegm doesn't recompute it)
                let appoint = timegm(&Tm { hour: task.hours as i64, min: task.minutes as i64, sec: 0, ..tm_loop });
                let week_day = if tm_loop.wday == 0 { 7 } else { tm_loop.wday };
                let week_ok = task.week_days == 0 || task.week_days & (1 << (week_day - 1)) != 0;
                let due = (task.hours >= 0 && week_ok && local_last_check < appoint && appoint <= local_current)
                    || (task.hours == STARTUP_TASK && task.last_executed == 0);
                if due {
                    r.due.push(k);
                    task.last_executed = lp;
                }
            }
            lp += 60 * 60 * 24;
            tm_loop = gmtime(lp);
        }
    }
    *last_check = current;
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dates() {
        // 2026-10-10 12:34:56 UTC, a Saturday
        let t = 1_791_635_696;
        let tm = gmtime(t);
        assert_eq!((tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec, tm.wday), (2026, 9, 10, 12, 34, 56, 6));
        assert_eq!(timegm(&tm), t);
        assert_eq!(gmtime(0).wday, 4);
        assert_eq!(gmtime(-1).year, 1969);
    }

    #[test]
    fn due() {
        let now = 1_791_635_696; // Saturday 12:34:56
        let mut tasks = [
            Task { hours: 12, minutes: 30, week_days: 0, last_executed: 0 },
            Task { hours: 12, minutes: 40, week_days: 0, last_executed: 0 },
            Task { hours: STARTUP_TASK, minutes: 0, week_days: 0, last_executed: 0 },
        ];
        let mut last = now - 600;
        let c = check_tasks(&mut tasks, &mut last, now, 0, gmtime);
        assert_eq!(c.due, vec![0, 2]);
        assert!(!c.reset);
        assert_eq!(last, now);
    }
}
