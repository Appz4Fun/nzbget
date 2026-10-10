//! ServerVolume's slot arithmetic (StatMeter.cpp): which second, minute,
//! hour and day slot a local time falls in (CalcSlots), and AddStats'
//! clearing of the slots the clock moved past (both ways) before adding the
//! bytes. Times are cut to a C int and divided as C ints, as the C++ did; the
//! C++ indexed the arrays with negative slots for times before 1970 or after
//! 2038-01-19 (memory corruption): those writes are skipped here.

const DAYS_UP_TO_2013_JAN_1: i32 = 15706;
const DAYS_IN_TWENTY_YEARS: i32 = 366 * 20;

/// NzbgetRsVolumeSlots
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Slots {
    pub sec: i32,
    pub min: i32,
    pub hour: i32,
    /// -1 outside the 20 years from 2013 (no day counters)
    pub day: i32,
    /// whether the day is in those 20 years (the day arrays may grow)
    pub in_range: i32,
}

/// CalcSlots: the slots of `loc_cur_time`; sets `first_day` on the first day
/// counted (or an earlier one).
pub fn calc_slots(loc_cur_time: i64, first_day: &mut i32) -> Slots {
    let t = loc_cur_time as i32;
    let days = t / 86400;
    let mut s = Slots {
        sec: t % 60,
        min: (t / 60) % 60,
        hour: (t % 86400) / 3600,
        day: days - DAYS_UP_TO_2013_JAN_1 + 1,
        in_range: 0,
    };
    if 0 <= s.day && s.day < DAYS_IN_TWENTY_YEARS {
        if *first_day == 0 || *first_day > days {
            *first_day = days;
        }
        s.day = days.wrapping_sub(*first_day);
        s.in_range = 1;
    } else {
        s.day = -1;
    }
    s
}

/// Zeroes `count` slots back (or forward) from `slot` in a ring of `ring`
/// slots, as the C++ loops did.
fn clear(array: &mut [i64], slot: i32, count: i32, sign: i32, ring: i32) {
    for i in 0..count.max(0) {
        let mut nul = slot.wrapping_sub(i.wrapping_mul(sign));
        if nul < 0 {
            nul += ring;
        }
        if nul >= ring {
            nul -= ring;
        }
        if let Some(v) = usize::try_from(nul).ok().and_then(|n| array.get_mut(n)) {
            *v = 0;
        }
    }
}

fn add(array: &mut [i64], slot: i32, bytes: i64) {
    if let Some(v) = usize::try_from(slot).ok().and_then(|n| array.get_mut(n)) {
        *v = v.wrapping_add(bytes);
    }
}

/// AddStats for the second, minute and hour counters: clears the slots passed
/// since `loc_data_time` (the previous update) and adds `bytes`.
#[allow(clippy::too_many_arguments)]
pub fn add_stats(
    seconds: &mut [i64], minutes: &mut [i64], hours: &mut [i64], s: &Slots, last_min_slot: i32, last_hour_slot: i32,
    loc_cur_time: i64, loc_data_time: i64, bytes: i64,
) {
    if loc_cur_time != loc_data_time {
        let mut total_delta = loc_cur_time.wrapping_sub(loc_data_time) as i32;
        let sign = if total_delta >= 0 { 1 } else { -1 };
        total_delta = total_delta.wrapping_abs();

        let mut sec_delta = total_delta;
        if sign < 0 {
            sec_delta = sec_delta.wrapping_add(1);
        }
        if sec_delta >= 60 {
            sec_delta = 60;
        }
        clear(seconds, s.sec, sec_delta, sign, 60);

        let mut min_delta = total_delta / 60;
        if sign < 0 {
            min_delta += 1;
        }
        if min_delta.wrapping_abs() >= 60 {
            min_delta = 60;
        }
        if min_delta == 0 && s.min != last_min_slot {
            min_delta = 1;
        }
        clear(minutes, s.min, min_delta, sign, 60);

        let mut hour_delta = total_delta / 3600;
        if sign < 0 {
            hour_delta += 1;
        }
        if hour_delta >= 24 {
            hour_delta = 24;
        }
        if hour_delta == 0 && s.hour != last_hour_slot {
            hour_delta = 1;
        }
        clear(hours, s.hour, hour_delta, sign, 24);
    }
    add(seconds, s.sec, bytes);
    add(minutes, s.min, bytes);
    add(hours, s.hour, bytes);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slots() {
        let mut first = 0;
        // 2026-10-10 12:34:56
        let s = calc_slots(1_791_635_696, &mut first);
        assert_eq!((s.sec, s.min, s.hour, s.day, s.in_range), (56, 34, 12, 0, 1));
        assert_eq!(first, 1_791_635_696 / 86400);
        let s = calc_slots(1_791_635_696 + 86400 * 3, &mut first);
        assert_eq!(s.day, 3);
        assert_eq!(calc_slots(1000, &mut first).day, -1);
    }

    #[test]
    fn clears_and_adds() {
        let (mut sec, mut min, mut hour) = (vec![7i64; 60], vec![7i64; 60], vec![7i64; 24]);
        let mut first = 0;
        let s = calc_slots(1_791_635_696, &mut first);
        add_stats(&mut sec, &mut min, &mut hour, &s, s.min, s.hour, 1_791_635_696, 1_791_635_696 - 3, 5);
        assert_eq!(&sec[53..57], &[7, 0, 0, 5]);
        assert_eq!(min[34], 12);
        // negative slots (an int time before 1970) are skipped, not written
        let s = calc_slots(-61, &mut first);
        add_stats(&mut sec, &mut min, &mut hour, &s, 0, 0, -61, 0, 1);
    }
}
