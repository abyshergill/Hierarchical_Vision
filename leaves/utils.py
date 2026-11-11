"""Pure-Python leave maths (no Django imports so it is trivially testable)."""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def q2(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def hours_to_days(hours, hours_per_day):
    return q2(Decimal(hours) / Decimal(hours_per_day))


def is_working_day(day, holidays, weekdays):
    return day.weekday() in weekdays and day not in holidays


def count_working_days(start, end, holidays=(), weekdays=(0, 1, 2, 3, 4)):
    holidays = set(holidays)
    total, day = 0, start
    while day <= end:
        if is_working_day(day, holidays, weekdays):
            total += 1
        day += timedelta(days=1)
    return total


def hourly_duration(start_time, end_time):
    """Hours between two ``time`` objects on the same day (0 if end <= start)."""
    base = date(2000, 1, 1)
    delta = datetime.combine(base, end_time) - datetime.combine(base, start_time)
    if delta.total_seconds() <= 0:
        return Decimal("0.00")
    return q2(Decimal(delta.total_seconds()) / Decimal(3600))


def calculate_leave_hours(start, end, *, hourly=False, start_time=None, end_time=None,
                          holidays=(), weekdays=(0, 1, 2, 3, 4), hours_per_day=8):
    """Total leave hours consumed.

    * Full-day leave: working days in [start, end] x hours_per_day.
    * Hourly leave: the time window on ``start`` (0 if that day is not a working day).
    """
    holidays = set(holidays)
    if hourly:
        if not is_working_day(start, holidays, weekdays):
            return Decimal("0.00")
        return hourly_duration(start_time, end_time)
    return q2(Decimal(count_working_days(start, end, holidays, weekdays)) * Decimal(hours_per_day))


def time_ranges_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def working_days_between(start, end, holidays=(), weekdays=(0, 1, 2, 3, 4)):
    """Every working date in [start, end], in order."""
    holidays = set(holidays)
    out, day = [], start
    while day <= end:
        if is_working_day(day, holidays, weekdays):
            out.append(day)
        day += timedelta(days=1)
    return out
