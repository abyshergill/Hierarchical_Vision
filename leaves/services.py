from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from notifications.services import notify

from .models import Holiday, LeaveApplication, LeaveDay, LeaveEntitlement, LeaveType
from .utils import hours_to_days, q2

Status = LeaveApplication.Status


def _hpd():
    return settings.WORK_HOURS_PER_DAY


def holiday_dates(start, end):
    return set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))


def _row(leave_type, allocated_days, approved_hours, pending_hours):
    hpd = _hpd()
    allocated_h = q2(Decimal(allocated_days) * hpd)
    approved_h, pending_h = q2(approved_hours or 0), q2(pending_hours or 0)
    remaining_h = allocated_h - approved_h - pending_h
    return {
        "leave_type": leave_type,
        "allocated_hours": allocated_h,
        "used_hours": approved_h,
        "pending_hours": pending_h,
        "remaining_hours": remaining_h,
        "allocated_days": hours_to_days(allocated_h, hpd),
        "used_days": hours_to_days(approved_h, hpd),
        "pending_days": hours_to_days(pending_h, hpd),
        "remaining_days": hours_to_days(remaining_h, hpd),
    }


def get_balances_for_users(users, year):
    """{user_pk: [balance rows per active leave type]} using three queries total."""
    users = list(users)
    uids = [u.pk for u in users]
    types = list(LeaveType.objects.filter(is_active=True).order_by("name"))
    overrides = {
        (e.user_id, e.leave_type_id): e.allocated_days
        for e in LeaveEntitlement.objects.filter(user_id__in=uids, year=year)
    }
    sums = defaultdict(dict)
    rows = (
        LeaveApplication.objects.filter(
            applicant_id__in=uids, start_date__year=year, status__in=[Status.APPROVED, Status.PENDING]
        )
        .values("applicant_id", "leave_type_id", "status")
        .annotate(hours=Sum("total_hours"))
        .order_by()
    )
    for r in rows:
        sums[(r["applicant_id"], r["leave_type_id"])][r["status"]] = r["hours"]
    return {
        u.pk: [
            _row(
                lt,
                overrides.get((u.pk, lt.pk), lt.annual_quota_days),
                sums[(u.pk, lt.pk)].get(Status.APPROVED),
                sums[(u.pk, lt.pk)].get(Status.PENDING),
            )
            for lt in types
        ]
        for u in users
    }


def compute_balance(user, leave_type, year, exclude_pk=None):
    """Balance for one leave type (works for inactive types too)."""
    override = LeaveEntitlement.objects.filter(user=user, leave_type=leave_type, year=year).first()
    qs = LeaveApplication.objects.filter(applicant=user, leave_type=leave_type, start_date__year=year)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    grouped = (
        qs.filter(status__in=[Status.APPROVED, Status.PENDING])
        .order_by().values_list("status").annotate(h=Sum("total_hours"))
    )
    totals = {status: hours for status, hours in grouped}
    allocated = override.allocated_days if override else leave_type.annual_quota_days
    return _row(leave_type, allocated, totals.get(Status.APPROVED), totals.get(Status.PENDING))


def team_members(user):
    from accounts.models import User

    if user.is_admin:
        return User.objects.filter(is_active=True).exclude(pk=user.pk).select_related("manager").order_by("full_name")
    return user.get_all_subordinates().select_related("manager").order_by("full_name")


# ---------------------------------------------------------------- notifications
def find_approvers(applicant):
    """Nearest manager/admin above the applicant; otherwise all other admins."""
    from accounts.models import Role, User

    for person in applicant.get_management_chain():
        if person.is_active and person.can_approve_leaves:
            return [person]
    return list(User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=applicant.pk))


def notify_new_application(application):
    app = application
    url = reverse("leaves:team")
    for approver in find_approvers(app.applicant):
        notify(
            approver,
            f"Leave request from {app.applicant.full_name}",
            f"{app.applicant.full_name} ({app.applicant.employee_id}) applied for {app.leave_type.name}: "
            f"{app.period_display} ({app.total_hours} h / {app.total_days} d).\n"
            + "\n".join(app.day_summary[:15]) + ("\n..." if app.days.count() > 15 else "")
            + f"\nReason: {app.reason or '-'}",
            url=url,
        )


def notify_decision(application):
    app = application
    verb = "approved" if app.status == Status.APPROVED else "rejected"
    reviewer = app.reviewed_by.full_name if app.reviewed_by else "your manager"
    msg = f"{reviewer} {verb} your {app.leave_type.name} request for {app.period_display}."
    if app.review_comment:
        msg += f"\nComment: {app.review_comment}"
    notify(
        app.applicant,
        f"Leave {verb}: {app.leave_type.name}",
        msg,
        url=reverse("accounts:profile", kwargs={"employee_id": app.applicant.employee_id}) + "?tab=leaves",
    )


# ---------------------------------------------------------------- workflow
@transaction.atomic
def submit_application(application, days):
    """Persist the application with its per-day time windows, then notify the approver."""
    application.status = Status.PENDING
    application.save()
    LeaveDay.objects.bulk_create([
        LeaveDay(application=application, date=d["date"], start_time=d["start_time"],
                 end_time=d["end_time"], hours=d["hours"])
        for d in days
    ])
    notify_new_application(application)
    return application


@transaction.atomic
def review_application(application_pk, reviewer, approve, comment=""):
    app = (
        LeaveApplication.objects.select_for_update()
        .select_related("applicant", "leave_type")
        .get(pk=application_pk)
    )
    if app.status != Status.PENDING:
        raise ValidationError("This application has already been processed.")
    if not reviewer.can_review(app.applicant):
        raise PermissionDenied("You cannot review this application.")
    if approve:
        balance = compute_balance(app.applicant, app.leave_type, app.start_date.year, exclude_pk=app.pk)
        if app.total_hours > balance["remaining_hours"]:
            raise ValidationError("Approving would exceed the employee's remaining balance.")
    app.status = Status.APPROVED if approve else Status.REJECTED
    app.reviewed_by = reviewer
    app.reviewed_at = timezone.now()
    app.review_comment = comment.strip()
    app.save()
    notify_decision(app)
    return app


def cancel_application(application, user):
    if application.applicant_id != user.pk:
        raise PermissionDenied
    if application.status != Status.PENDING:
        raise ValidationError("Only pending applications can be cancelled.")
    application.status = Status.CANCELLED
    application.save(update_fields=["status"])
    return application
