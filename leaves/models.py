from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .utils import hours_to_days


class LeavePolicy(models.Model):
    """Company-wide leave rules edited by Admins (one row, pk=1)."""

    max_hours_per_day = models.DecimalField(
        "maximum leave hours per day", max_digits=4, decimal_places=2, default=Decimal("8.00"),
        validators=[MinValueValidator(Decimal("0.25")), MaxValueValidator(Decimal("24"))],
        help_text="No one can book more than this many leave hours on a single day.",
    )
    default_start_time = models.TimeField(
        default=time(9, 0), help_text="Pre-filled start time when employees set the time for each day.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "leave policy"
        verbose_name_plural = "leave policy"

    def __str__(self):
        return f"Leave policy (max {self.max_hours_per_day} h/day)"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class LeaveType(models.Model):
    """A "Standard Leave" policy defined by Admins and consumed by everyone."""

    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=12, unique=True, help_text="Short code, e.g. AL, SL")
    description = models.TextField(blank=True)
    annual_quota_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))],
        help_text="Days granted to every employee per calendar year.",
    )
    allow_hourly = models.BooleanField(
        "allow partial days", default=False,
        help_text="If ticked, employees may take part of a day (e.g. 09:00-11:00). Otherwise every day must be a full day.",
    )
    max_hours_per_day = models.DecimalField(
        "max hours per day (override)", max_digits=4, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.25")), MaxValueValidator(Decimal("24"))],
        help_text="Optional. Leave empty to use the company-wide limit from the leave policy.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def daily_limit(self, policy=None):
        """Max hours that may be booked on one day for this leave type (admin-controlled)."""
        if self.max_hours_per_day:
            return self.max_hours_per_day
        return (policy or LeavePolicy.load()).max_hours_per_day


class LeaveEntitlement(models.Model):
    """Optional per-person, per-year override of a leave type's standard quota."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_entitlements")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name="entitlements")
    year = models.PositiveSmallIntegerField()
    allocated_days = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        unique_together = [("user", "leave_type", "year")]
        ordering = ["-year", "leave_type__name"]

    def __str__(self):
        return f"{self.user} - {self.leave_type} {self.year}: {self.allocated_days}d"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date:%Y-%m-%d} {self.name}"


class LeaveApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_applications")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="applications")
    is_hourly = models.BooleanField("apply by the hour", default=False)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    reason = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_leaves"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["applicant", "start_date"])]

    def __str__(self):
        return f"{self.applicant} {self.leave_type} {self.start_date}"

    @property
    def day_summary(self):
        """['Mon 01 Mar 2027 09:00-17:00 (8.00 h)', ...] - uses prefetched rows when available."""
        return [f"{d.date:%a %d %b %Y}  {d.start_time:%H:%M}\u2013{d.end_time:%H:%M}  ({d.hours} h)" for d in self.days.all()]

    @property
    def total_days(self):
        return hours_to_days(self.total_hours, settings.WORK_HOURS_PER_DAY)

    @property
    def period_display(self):
        if self.start_date == self.end_date:
            if self.start_time and self.end_time:
                return f"{self.start_date:%d %b %Y}, {self.start_time:%H:%M}\u2013{self.end_time:%H:%M}"
            return f"{self.start_date:%d %b %Y}"
        return f"{self.start_date:%d %b %Y} \u2192 {self.end_date:%d %b %Y}"


class LeaveDay(models.Model):
    """One booked day of a leave application, with the time window the employee chose."""

    application = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE, related_name="days")
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ["date"]
        unique_together = [("application", "date")]

    def __str__(self):
        return f"{self.date} {self.start_time:%H:%M}-{self.end_time:%H:%M}"
