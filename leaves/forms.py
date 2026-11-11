from datetime import date, time
from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Holiday, LeaveApplication, LeaveDay, LeavePolicy, LeaveType
from .services import compute_balance, holiday_dates
from .utils import hourly_duration, time_ranges_overlap, working_days_between

Status = LeaveApplication.Status
DATE = lambda: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")  # noqa: E731
MAX_SPAN_DAYS = 62          # one application can cover at most ~2 months (keeps the per-day table sane)


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "code", "description", "annual_quota_days", "allow_hourly", "max_hours_per_day", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class LeavePolicyForm(forms.ModelForm):
    class Meta:
        model = LeavePolicy
        fields = ["max_hours_per_day", "default_start_time"]
        widgets = {"default_start_time": forms.TimeInput(attrs={"type": "time", "step": 900}, format="%H:%M")}


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "description"]
        widgets = {"date": DATE()}


def _fmt(d):
    return f"{d:%a %d %b %Y}"


class LeaveApplicationForm(forms.ModelForm):
    """Date range + a start/end time for EVERY working day in it.

    The day rows arrive as parallel lists ``day_date`` / ``day_start`` / ``day_end``.
    Each day is limited by the admin-defined hours-per-day (leave policy, optionally
    overridden per leave type). Everything is re-validated here - the JS is only a convenience.
    """

    class Meta:
        model = LeaveApplication
        fields = ["leave_type", "start_date", "end_date", "reason"]
        widgets = {"start_date": DATE(), "end_date": DATE(), "reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.applicant = user
        self.policy = LeavePolicy.load()
        self.cleaned_days = []
        self.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True)
        self.fields["reason"].required = True
        self.fields["reason"].label = "Reason (required)"
        self.fields["reason"].help_text = "Please provide a reason for your leave."
        self.fields["end_date"].required = False
        self.fields["end_date"].help_text = "Leave blank for a single day."

    # ---- raw rows (also used to re-render the table after a validation error)
    @property
    def posted_rows(self):
        if not self.is_bound:
            return []
        dates, starts, ends = (self.data.getlist(k) for k in ("day_date", "day_start", "day_end"))
        rows = []
        for i, d in enumerate(dates[: MAX_SPAN_DAYS + 5]):
            rows.append({
                "date": d[:10],
                "start": (starts[i] if i < len(starts) else "")[:5],
                "end": (ends[i] if i < len(ends) else "")[:5],
            })
        return rows

    def _parse_rows(self):
        rows, errors = {}, []
        for r in self.posted_rows:
            try:
                d = date.fromisoformat(r["date"])
                st, et = time.fromisoformat(r["start"]), time.fromisoformat(r["end"])
            except ValueError:
                errors.append("Please enter a valid start and end time for every day.")
                continue
            if d in rows:
                errors.append(f"{_fmt(d)} appears twice.")
            rows[d] = (st, et)
        return rows, errors

    def clean(self):
        data = super().clean()
        leave_type, start = data.get("leave_type"), data.get("start_date")
        if not leave_type or not start:
            return data
        end = data.get("end_date") or start
        if end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
            return data
        if start.year != end.year:
            self.add_error("end_date", "A single application cannot span two calendar years.")
            return data
        if (end - start).days + 1 > MAX_SPAN_DAYS:
            self.add_error("end_date", f"Please apply for at most {MAX_SPAN_DAYS} days at a time.")
            return data

        working = working_days_between(start, end, holiday_dates(start, end), settings.WORKING_WEEKDAYS)
        if not working:
            raise forms.ValidationError("The selected period contains no working days (weekend or public holiday).")

        rows, errors = self._parse_rows()
        limit = leave_type.daily_limit(self.policy)
        missing = [d for d in working if d not in rows]
        extra = [d for d in rows if d not in set(working)]
        if missing:
            errors.append("Set the time for every working day. Missing: " + ", ".join(_fmt(d) for d in missing[:6])
                          + (" ..." if len(missing) > 6 else ""))
        if extra:
            errors.append("Not a working day in this range: " + ", ".join(_fmt(d) for d in sorted(extra)[:6]))
        if errors:
            raise forms.ValidationError(list(dict.fromkeys(errors)))

        days = []
        for d in working:
            st, et = rows[d]
            hours = hourly_duration(st, et)
            if hours <= 0:
                errors.append(f"{_fmt(d)}: the end time must be after the start time.")
            elif hours > limit:
                errors.append(f"{_fmt(d)}: {hours} h is more than the {limit} h per day allowed by the admin.")
            elif not leave_type.allow_hourly and hours != limit:
                errors.append(f"{_fmt(d)}: {leave_type.name} must be taken as a full day ({limit} h).")
            days.append({"date": d, "start_time": st, "end_time": et, "hours": hours})
        if errors:
            raise forms.ValidationError(errors)

        errors = self._overlap_errors(days, start, end)
        if errors:
            raise forms.ValidationError(errors)

        total = sum((x["hours"] for x in days), Decimal("0"))
        balance = compute_balance(self.user, leave_type, start.year)
        if total > balance["remaining_hours"]:
            raise forms.ValidationError(
                f"Not enough {leave_type.name} balance: {balance['remaining_hours']} h remaining "
                f"({balance['remaining_days']} days), this request needs {total} h."
            )

        # store the first / last WORKING day (ModelForm copies cleaned_data onto the instance afterwards)
        data["start_date"], data["end_date"] = days[0]["date"], days[-1]["date"]
        self.cleaned_days = days
        inst = self.instance
        inst.total_hours = total
        inst.is_hourly = any(x["hours"] < limit for x in days)
        inst.start_time, inst.end_time = (days[0]["start_time"], days[0]["end_time"]) if len(days) == 1 else (None, None)
        return data

    def _overlap_errors(self, days, start, end):
        by_date = {x["date"]: x for x in days}
        errors = []
        booked = LeaveDay.objects.filter(
            application__applicant=self.user, application__status__in=[Status.PENDING, Status.APPROVED],
            date__in=list(by_date),
        )
        for other in booked:
            mine = by_date[other.date]
            if time_ranges_overlap(mine["start_time"], mine["end_time"], other.start_time, other.end_time):
                errors.append(f"{_fmt(other.date)} {other.start_time:%H:%M}\u2013{other.end_time:%H:%M} overlaps your existing request.")
        # applications created before per-day rows existed
        legacy = LeaveApplication.objects.filter(
            applicant=self.user, status__in=[Status.PENDING, Status.APPROVED],
            days__isnull=True, start_date__lte=end, end_date__gte=start,
        )
        for other in legacy:
            for d, mine in by_date.items():
                if not (other.start_date <= d <= other.end_date):
                    continue
                if other.is_hourly and other.start_time and other.end_time and not time_ranges_overlap(
                        mine["start_time"], mine["end_time"], other.start_time, other.end_time):
                    continue
                errors.append(f"{_fmt(d)} overlaps your existing request for {other.period_display}.")
        return list(dict.fromkeys(errors))


class ReviewForm(forms.Form):
    comment = forms.CharField(required=False, max_length=500)
