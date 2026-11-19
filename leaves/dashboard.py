"""Daily leave & overtime dashboard.

Admins always see the whole company. Managers see it only when an Admin grants them access, either for their own
team (everyone below them) or for the whole company (``User.leave_dashboard``)."""
import calendar
import csv
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import DashboardAccess, Role, User
from notifications.services import notify

from .export import safe_cell
from .models import Holiday, LeaveApplication, LeaveDay, OvertimeRequest
from .views import _paginate

Status = LeaveApplication.Status
ROWS_PER_PAGE = 25


def _requested_day(request):
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return timezone.localdate()
    return day if 2000 <= day.year <= 2100 else timezone.localdate()


def _scope_people(user):
    """Active people this viewer may see on the dashboard."""
    if user.leave_dashboard_scope == "all":
        return User.objects.filter(is_active=True)
    return user.get_all_subordinates()


def _manager_choices(user, people):
    """People in scope (plus the viewer) who lead a team - used for the "Team" filter."""
    visible = list(people.values_list("pk", flat=True)) + [user.pk]
    return (User.objects.filter(pk__in=visible, is_active=True, direct_reports__is_active=True)
            .distinct().order_by("full_name").only("pk", "full_name", "employee_id"))


def _bars(rows, value_key):
    """Add a 0-100 ``pct`` to every row (bar length relative to the biggest value)."""
    top = max((r[value_key] or 0 for r in rows), default=0) or 1
    for r in rows:
        r["pct"] = round(100 * (r[value_key] or 0) / top)
    return rows


def _resolve(request):
    """The day / team / pending filters of a dashboard request, already checked against what the viewer may see."""
    user = request.user
    if not user.can_view_leave_dashboard:
        raise PermissionDenied
    day = _requested_day(request)
    include_pending = request.GET.get("pending") == "1"
    statuses = [Status.APPROVED, Status.PENDING] if include_pending else [Status.APPROVED]
    people = _scope_people(user)
    managers = _manager_choices(user, people)
    team_lead = None
    try:
        lead_pk = int(request.GET.get("team", ""))
    except ValueError:
        lead_pk = None
    if lead_pk:
        team_lead = next((m for m in managers if m.pk == lead_pk), None)
        if team_lead is None:
            raise PermissionDenied                     # not a team this viewer may look at
        people = people.filter(pk__in=team_lead.get_all_subordinates().values("pk"))
    return {"day": day, "include_pending": include_pending, "statuses": statuses, "people": people,
            "people_ids": people.values("pk"), "managers": managers, "team_lead": team_lead, "headcount": people.count()}


def _export_params(request, day, tab):
    q = request.GET.copy()
    for key in ("lp", "op", "date", "tab"):
        q.pop(key, None)
    q["date"] = day.isoformat()
    q["tab"] = tab
    return q


@login_required
def dashboard(request):
    user = request.user
    if not user.can_view_leave_dashboard:
        raise PermissionDenied
    f = _resolve(request)
    day, include_pending, statuses = f["day"], f["include_pending"], f["statuses"]
    people, people_ids, managers, team_lead, headcount = f["people"], f["people_ids"], f["managers"], f["team_lead"], f["headcount"]

    # ---------------------------------------------------------------- leave on the day
    leave_rows = (LeaveDay.objects.filter(date=day, application__applicant__in=people_ids)
                  .select_related("application__applicant__manager", "application__leave_type",
                                  "application__alternate_employee"))
    shown = leave_rows.filter(application__status__in=statuses)
    approved = leave_rows.filter(application__status=Status.APPROVED)
    pending_leave_people = (leave_rows.filter(application__status=Status.PENDING)
                            .values("application__applicant").distinct().count())
    on_leave = approved.values("application__applicant").distinct().count()
    leave_hours = approved.aggregate(h=Sum("hours"))["h"] or 0
    partial = shown.filter(hours__lt=settings.WORK_HOURS_PER_DAY).values("application__applicant").distinct().count()
    by_type = _bars(list(
        shown.values("application__leave_type__name", "application__leave_type__code")
        .annotate(people=Count("application__applicant", distinct=True), hours=Sum("hours"))
        .order_by("-people", "application__leave_type__name")
    ), "people")
    leave_page = _paginate(request, shown.order_by("application__applicant__full_name"), ROWS_PER_PAGE, "lp", "#people")

    # ---------------------------------------------------------------- overtime on the day
    ot_all = OvertimeRequest.objects.filter(date=day, applicant__in=people_ids)
    ot_shown = ot_all.filter(status__in=statuses).select_related("applicant__manager", "reviewed_by")
    ot_approved = ot_all.filter(status=Status.APPROVED)
    ot_people = ot_approved.values("applicant").distinct().count()
    ot_hours = ot_approved.aggregate(h=Sum("hours"))["h"] or 0
    ot_pending = ot_all.filter(status=Status.PENDING).count()
    ot_by_team = _bars(list(
        ot_shown.values("applicant__manager__full_name")
        .annotate(people=Count("applicant", distinct=True), hours=Sum("hours"))
        .order_by("-hours", "applicant__manager__full_name")[:10]
    ), "hours")
    ot_page = _paginate(request, ot_shown.order_by("start_time", "applicant__full_name"), ROWS_PER_PAGE, "op", "#people")

    leave_by_team = _bars(list(
        shown.values("application__applicant__manager__full_name")
        .annotate(people=Count("application__applicant", distinct=True), hours=Sum("hours"))
        .order_by("-people", "application__applicant__manager__full_name")[:8]
    ), "people")

    # ---------------------------------------------------------------- the whole month around the chosen day
    first, last = day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])
    leave_by_day = dict(
        LeaveDay.objects.filter(date__range=(first, last), application__status__in=statuses,
                                application__applicant__in=people_ids)
        .values("date").annotate(n=Count("application__applicant", distinct=True)).values_list("date", "n")
    )
    ot_by_day = dict(
        OvertimeRequest.objects.filter(date__range=(first, last), status__in=statuses, applicant__in=people_ids)
        .values("date").annotate(n=Count("applicant", distinct=True)).values_list("date", "n")
    )
    holidays = dict(Holiday.objects.filter(date__range=(first, last)).values_list("date", "name"))
    month = []
    for i in range((last - first).days + 1):
        d = first + timedelta(days=i)
        month.append({"date": d, "leave": leave_by_day.get(d, 0), "ot": ot_by_day.get(d, 0),
                      "holiday": holidays.get(d, ""), "weekend": d.weekday() >= 5})

    query = request.GET.copy()
    for key in ("date", "lp", "op"):
        query.pop(key, None)
    nav_base = "?" + (query.urlencode() + "&" if query else "") + "date="
    tab = "ot" if request.GET.get("tab") == "ot" else "leave"
    tab_query = request.GET.copy()
    for key in ("tab", "lp", "op"):
        tab_query.pop(key, None)
    tab_base = "?" + (tab_query.urlencode() + "&" if tab_query else "")
    chart_data = {
        "navBase": nav_base, "selected": day.isoformat(), "headcount": headcount, "pending": include_pending,
        "month": [{"d": m["date"].isoformat(), "label": f"{m['date']:%a %d %b}", "leave": m["leave"], "ot": m["ot"],
                   "weekend": m["weekend"], "holiday": m["holiday"]} for m in month],
        "monthName": f"{day:%B %Y}",
        "leaveTypes": [{"name": t["application__leave_type__name"], "people": t["people"], "hours": float(t["hours"] or 0)}
                       for t in by_type],
        "leaveTeams": [{"name": t["application__applicant__manager__full_name"] or "No manager", "people": t["people"]}
                       for t in leave_by_team],
        "otTeams": [{"name": t["applicant__manager__full_name"] or "No manager", "people": t["people"],
                     "hours": float(t["hours"] or 0)} for t in ot_by_team],
    }
    return render(request, "leaves/dashboard.html", {
        "chart_data": chart_data, "tab": tab, "tab_base": tab_base,
        "export_query": (lambda q: q.urlencode())(_export_params(request, day, tab)),
        "day": day, "today": timezone.localdate(),
        "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "keep": query.urlencode(),                 # filters to keep when moving to another day
        "include_pending": include_pending, "scope": user.leave_dashboard_scope,
        "managers": managers, "team_lead": team_lead, "headcount": headcount,
        "holiday": Holiday.objects.filter(date=day).first(),
        "on_leave": on_leave, "leave_hours": leave_hours, "pending_leave_people": pending_leave_people,
        "partial": partial, "out_pct": round(100 * on_leave / headcount, 1) if headcount else 0,
        "by_type": by_type, "leave_page": leave_page,
        "ot_people": ot_people, "ot_hours": ot_hours, "ot_pending": ot_pending,
        "ot_by_team": ot_by_team, "ot_page": ot_page,
        "month": month, "month_name": f"{day:%B %Y}", "leave_by_team": leave_by_team,
    })


@login_required
def dashboard_access(request):
    """Admin decides which managers may open the dashboard, and whether they see their team or the whole company."""
    if not request.user.is_admin:
        raise PermissionDenied
    managers = User.objects.filter(is_active=True, role=Role.MANAGER).select_related("manager").order_by("full_name")
    valid = set(DashboardAccess.values)
    if request.method == "POST":
        changed = 0
        for m in managers:
            value = request.POST.get(f"access_{m.pk}")
            if value is None or value not in valid or value == m.leave_dashboard:
                continue
            was = m.leave_dashboard
            User.objects.filter(pk=m.pk).update(leave_dashboard=value)
            changed += 1
            if value and not was:
                notify(m, "You can now open the leave & OT dashboard",
                       "An admin gave you access to the daily leave and overtime dashboard "
                       f"({DashboardAccess(value).label.lower()}).",
                       url=reverse("leaves:dashboard"), send_email=False)
        messages.success(request, f"Saved. {changed} manager{'s' if changed != 1 else ''} updated.")
        return redirect("leaves:dashboard_access")
    counts = {c: 0 for c in valid}
    for m in managers:
        counts[m.leave_dashboard] = counts.get(m.leave_dashboard, 0) + 1
    return render(request, "leaves/dashboard_access.html", {
        "managers": managers, "choices": DashboardAccess.choices,
        "granted": counts[DashboardAccess.TEAM] + counts[DashboardAccess.ALL],
    })


@login_required
def dashboard_export(request):
    """Download the people table (``tab=leave`` or ``tab=ot``) for the chosen day, team and status filter as CSV."""
    f = _resolve(request)
    day = f["day"]
    kind = "ot" if request.GET.get("tab") == "ot" else "leave"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{"overtime" if kind == "ot" else "leave"}-{day.isoformat()}.csv"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response.write("\ufeff")                          # BOM so Excel opens it as UTF-8
    w = csv.writer(response)
    scope = f["team_lead"].full_name if f["team_lead"] else ("Whole company" if request.user.leave_dashboard_scope == "all" else "My team")
    w.writerow([safe_cell(f"{'Overtime' if kind == 'ot' else 'Leave'} on {day:%A %d %B %Y}"), safe_cell(scope),
                "including pending" if f["include_pending"] else "approved only"])
    if kind == "ot":
        w.writerow(["Employee ID", "Name", "Position", "Team (manager)", "Date", "Start", "End", "Hours", "Status", "Reason"])
        rows = (OvertimeRequest.objects.filter(date=day, applicant__in=f["people_ids"], status__in=f["statuses"])
                .select_related("applicant__manager").order_by("applicant__full_name", "start_time"))
        for o in rows:
            w.writerow([safe_cell(x) for x in (o.applicant.employee_id, o.applicant.full_name, o.applicant.position,
                                               o.applicant.manager.full_name if o.applicant.manager else "", o.date.isoformat(),
                                               f"{o.start_time:%H:%M}", f"{o.end_time:%H:%M}", o.hours, o.get_status_display(), o.reason)])
    else:
        w.writerow(["Employee ID", "Name", "Position", "Team (manager)", "Leave type", "Date", "Start", "End", "Hours", "Status", "Covered by"])
        rows = (LeaveDay.objects.filter(date=day, application__applicant__in=f["people_ids"], application__status__in=f["statuses"])
                .select_related("application__applicant__manager", "application__leave_type", "application__alternate_employee")
                .order_by("application__applicant__full_name"))
        for d in rows:
            a = d.application
            w.writerow([safe_cell(x) for x in (a.applicant.employee_id, a.applicant.full_name, a.applicant.position,
                                               a.applicant.manager.full_name if a.applicant.manager else "", a.leave_type.name,
                                               d.date.isoformat(), f"{d.start_time:%H:%M}", f"{d.end_time:%H:%M}", d.hours,
                                               a.get_status_display(), a.alternate_employee.full_name if a.alternate_employee else "")])
    return response
