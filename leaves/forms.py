from datetime import date, time
from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Holiday, LeaveApplication, LeaveDay, LeavePolicy, LeaveType, OvertimeRequest
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
        fields = ["leave_type", "start_date", "end_date", "alternate_employee", "reason"]
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
        from accounts.models import User

        alt = self.fields["alternate_employee"]
        alt.queryset = User.objects.filter(is_active=True).exclude(pk=user.pk).order_by("full_name")
        alt.required = True
        alt.label = "Alternate employee (covers for you)"
        alt.empty_label = "Select a colleague\u2026"
        alt.help_text = "Who will take over your work while you are away? They cannot be on leave on those days."
        alt.label_from_instance = lambda u: f"{u.full_name} ({u.employee_id})"
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
        errors.extend(self._alternate_errors(data.get("alternate_employee"), working))
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

    def _alternate_errors(self, alternate, working):
        """The cover person must be someone else and must not be away on any of the requested days."""
        if alternate is None:
            return []
        if alternate.pk == self.user.pk:
            return ["You cannot name yourself as your alternate employee."]
        if not alternate.is_active:
            return ["The alternate employee is no longer active."]
        away = sorted(set(
            LeaveDay.objects.filter(
                application__applicant=alternate, application__status__in=[Status.PENDING, Status.APPROVED],
                date__in=working,
            ).values_list("date", flat=True)
        ))
        if away:
            return [f"{alternate.full_name} is already on leave on " + ", ".join(_fmt(d) for d in away[:4])
                    + (" ..." if len(away) > 4 else "") + " - please choose another alternate."]
        return []

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


class OvertimeForm(forms.ModelForm):
    """One day, from/to time. Hours are always calculated on the server."""

    class Meta:
        model = OvertimeRequest
        fields = ["date", "start_time", "end_time", "reason"]
        widgets = {
            "date": DATE(),
            "start_time": forms.TimeInput(attrs={"type": "time", "step": 900}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time", "step": 900}, format="%H:%M"),
            "reason": forms.Textarea(attrs={"rows": 3, "maxlength": 1000}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.applicant = user
        self.fields["reason"].label = "Reason / work to be done"
        self.fields["reason"].max_length = 1000

    def clean_reason(self):
        reason = " ".join(self.cleaned_data.get("reason", "").split())
        if not reason:
            raise forms.ValidationError("Please describe the work that needs overtime.")
        return reason[:1000]

    def clean_date(self):
        from django.utils import timezone

        day = self.cleaned_data["date"]
        today = timezone.localdate()
        if (today - day).days > settings.OT_MAX_DAYS_BACK:
            raise forms.ValidationError(f"Overtime can only be requested up to {settings.OT_MAX_DAYS_BACK} days back.")
        if (day - today).days > settings.OT_MAX_DAYS_AHEAD:
            raise forms.ValidationError(f"Overtime can only be requested up to {settings.OT_MAX_DAYS_AHEAD} days ahead.")
        return day

    def clean(self):
        data = super().clean()
        day, st, et = data.get("date"), data.get("start_time"), data.get("end_time")
        if not (day and st and et):
            return data
        hours = hourly_duration(st, et)
        if hours <= 0:
            self.add_error("end_time", "The end time must be after the start time (overtime cannot cross midnight - "
                                       "submit two requests instead).")
            return data
        cap = Decimal(settings.OT_MAX_HOURS_PER_DAY)
        others = OvertimeRequest.objects.filter(applicant=self.user, date=day, status__in=[Status.PENDING, Status.APPROVED])
        errors = []
        for o in others:
            if time_ranges_overlap(st, et, o.start_time, o.end_time):
                errors.append(f"This overlaps your existing overtime request ({o.start_time:%H:%M}\u2013{o.end_time:%H:%M}).")
        booked = sum((o.hours for o in others), Decimal("0"))
        if hours + booked > cap:
            errors.append(f"At most {cap} overtime hours per day are allowed (you already have {booked} h on {_fmt(day)}).")
        clash = LeaveDay.objects.filter(
            application__applicant=self.user, application__status__in=[Status.PENDING, Status.APPROVED], date=day,
        )
        for d in clash:
            if time_ranges_overlap(st, et, d.start_time, d.end_time):
                errors.append(f"You are on leave {d.start_time:%H:%M}\u2013{d.end_time:%H:%M} that day - overtime cannot overlap leave.")
        if errors:
            raise forms.ValidationError(errors)
        self.instance.hours = hours
        return data
