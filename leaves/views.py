from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from accounts.mixins import AdminRequiredMixin

from . import services
from .export import build_leave_csv_response
from .pdf import build_holiday_pdf
from .forms import HolidayForm, LeaveApplicationForm, LeavePolicyForm, LeaveTypeForm, OvertimeForm
from .models import Holiday, LeaveApplication, LeavePolicy, LeaveType, OvertimeRequest

Status = LeaveApplication.Status


def _safe_next(request, default):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return default


def _my_leaves_url(user):
    return reverse("accounts:profile", kwargs={"employee_id": user.employee_id}) + "?tab=leaves"


# ----------------------------------------------------------------- employee
@login_required
def apply(request):
    form = LeaveApplicationForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            application = services.submit_application(form.instance, form.cleaned_days)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                f"{application.leave_type.name} request submitted: {len(form.cleaned_days)} day(s), {application.total_hours} h.",
            )
            return redirect(_my_leaves_url(request.user))
    today = timezone.localdate()
    types = list(LeaveType.objects.filter(is_active=True))
    policy = form.policy
    return render(request, "leaves/apply.html", {
        "form": form,
        "policy": policy,
        "balances": services.get_balances_for_users([request.user], today.year)[request.user.pk],
        # data for the per-day table (the server re-validates everything)
        "type_limits": ",".join(f"{t.pk}:{t.daily_limit(policy)}" for t in types),
        "hourly_types": ",".join(str(t.pk) for t in types if t.allow_hourly),
        "weekdays": ",".join(str(d) for d in settings.WORKING_WEEKDAYS),
        "holiday_list": ",".join(
            f"{d:%Y-%m-%d}" for d in Holiday.objects.filter(date__gte=today - timedelta(days=400)).values_list("date", flat=True)
        ),
        "posted_rows": form.posted_rows,
    })


@login_required
@require_POST
def cancel(request, pk):
    application = get_object_or_404(LeaveApplication, pk=pk)
    try:
        services.cancel_application(application, request.user)
        messages.success(request, "Request cancelled.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect(_safe_next(request, _my_leaves_url(request.user)))


def _requested_year(request):
    """?year=YYYY, limited to a sane range so odd values cannot reach the database or the PDF."""
    default = timezone.localdate().year
    try:
        year = int(request.GET.get("year", default))
    except (TypeError, ValueError):
        return default
    return year if 2000 <= year <= 2100 else default


@login_required
def holidays(request):
    year = _requested_year(request)
    form = None
    if request.user.is_admin:
        form = HolidayForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Holiday added.")
            return redirect(f"{reverse('leaves:holidays')}?year={year}")
    page = Paginator(Holiday.objects.filter(date__year=year), 15).get_page(request.GET.get("page"))
    return render(request, "leaves/holidays.html", {
        "page": page, "holidays": page.object_list, "year": year, "form": form, "extra": f"&year={year}",
    })


@login_required
def holidays_pdf(request):
    """Download the holiday schedule of one year as a PDF (any signed-in user, same audience as the page)."""
    year = _requested_year(request)
    rows = Holiday.objects.filter(date__year=year).order_by("date").values_list("date", "name", "description")
    pdf = build_holiday_pdf(year, rows, generated_at=timezone.localtime().replace(tzinfo=None))
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="holidays-{year}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def holiday_delete(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied
    get_object_or_404(Holiday, pk=pk).delete()
    messages.success(request, "Holiday removed.")
    return redirect("leaves:holidays")


# ----------------------------------------------------------------- manager
TEAM_PENDING_PER_PAGE = 20
TEAM_MEMBERS_PER_PAGE = 25


def _paginate(request, items, per_page, param, anchor=""):
    """Paginate ``items`` using its own query parameter, so several lists on one page page independently.

    Adds ``prev_url`` / ``next_url`` to the page; every other query parameter (the other lists' pages, the search)
    is kept in those links."""
    page = Paginator(items, per_page).get_page(request.GET.get(param))

    def url(number):
        params = request.GET.copy()
        params[param] = number
        return f"?{params.urlencode()}{anchor}"

    page.prev_url = url(page.previous_page_number()) if page.has_previous() else ""
    page.next_url = url(page.next_page_number()) if page.has_next() else ""
    return page


@login_required
def team(request):
    if not request.user.can_approve_leaves:
        raise PermissionDenied
    year = timezone.localdate().year
    members = services.team_members(request.user)
    member_ids = members.values("pk")
    pending = [
        a for a in LeaveApplication.objects.filter(applicant__in=member_ids, status=Status.PENDING)
        .select_related("applicant", "leave_type", "alternate_employee").prefetch_related("days").order_by("start_date", "pk")
        if request.user.can_review(a.applicant)
    ]
    pending_ot = [
        o for o in OvertimeRequest.objects.filter(applicant__in=member_ids, status=Status.PENDING)
        .select_related("applicant").order_by("date", "start_time", "pk")
        if request.user.can_review(o.applicant)
    ]
    upcoming = (
        LeaveApplication.objects.filter(applicant__in=member_ids, status=Status.APPROVED, end_date__gte=timezone.localdate())
        .select_related("applicant", "leave_type", "alternate_employee").order_by("start_date")[:30]
    )
    q = request.GET.get("q", "").strip()[:100]
    if q:
        members = members.filter(Q(full_name__icontains=q) | Q(employee_id__icontains=q) | Q(position__icontains=q))
    pending_page = _paginate(request, pending, TEAM_PENDING_PER_PAGE, "lp", "#pending")
    ot_page = _paginate(request, pending_ot, TEAM_PENDING_PER_PAGE, "op", "#overtime")
    member_page = _paginate(request, members, TEAM_MEMBERS_PER_PAGE, "tp", "#balances")
    page_members = list(member_page.object_list)
    balances = services.get_balances_for_users(page_members, year)   # only the people on this page
    return render(request, "leaves/team.html", {
        "pending": pending,
        "pending_page": pending_page,
        "pending_ot": pending_ot,
        "ot_page": ot_page,
        "upcoming": upcoming,
        "member_page": member_page,
        "team_rows": [(m, balances[m.pk]) for m in page_members],
        "q": q,
        "leave_types": LeaveType.objects.filter(is_active=True),
        "holidays": Holiday.objects.filter(date__gte=timezone.localdate()).order_by("date")[:10],
        "year": year,
    })


@login_required
def employee_download(request, employee_id):
    """Download one employee's leave balances + history as CSV (Managers/Admins only)."""
    from accounts.models import User

    target = get_object_or_404(User, employee_id__iexact=employee_id, is_active=True)
    if not request.user.can_export_leaves(target):
        raise PermissionDenied
    try:
        year = int(request.GET.get("year", timezone.localdate().year))
    except ValueError:
        year = timezone.localdate().year
    year = min(max(year, 2000), 2100)
    return build_leave_csv_response(target, year, request.user)


@login_required
@require_POST
def review(request, pk):
    decision = request.POST.get("decision")
    if decision not in {"approve", "reject"}:
        return HttpResponseBadRequest("Invalid decision.")
    try:
        app = services.review_application(pk, request.user, decision == "approve", request.POST.get("comment", ""))
        messages.success(request, f"{app.applicant.full_name}'s request was {app.get_status_display().lower()}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except LeaveApplication.DoesNotExist:
        raise Http404
    return redirect(_safe_next(request, reverse("leaves:team")))


MAX_BULK_ITEMS = 1000


def _bulk_ids(request):
    """Ids of the rows the reviewer saw on the page (so nothing submitted after page load is approved blindly)."""
    field = "page_ids" if request.POST.get("scope") == "page" else "ids"
    ids = []
    for raw in request.POST.getlist(field)[:MAX_BULK_ITEMS]:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(ids))


def _bulk_respond(request, done, failed, label):
    if done:
        messages.success(request, f"Approved {len(done)} {label}{'s' if len(done) != 1 else ''}.")
    if failed:
        shown = "; ".join(failed[:5]) + (f" (+{len(failed) - 5} more)" if len(failed) > 5 else "")
        messages.error(request, f"{len(failed)} could not be approved: {shown}")
    if not done and not failed:
        messages.info(request, "Nothing to approve.")


@login_required
@require_POST
def review_all(request):
    """Approve every pending leave request listed on the Team leaves page in one click."""
    if not request.user.can_approve_leaves:
        raise PermissionDenied
    done, failed = services.bulk_review(
        services.review_application, _bulk_ids(request), request.user, True, request.POST.get("comment", "")
    )
    _bulk_respond(request, done, failed, "leave request")
    return redirect(_safe_next(request, reverse("leaves:team")))


# ----------------------------------------------------------------- overtime (OT)
@login_required
def overtime(request):
    """Apply for overtime and see your own requests."""
    form = OvertimeForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        ot = services.submit_overtime(form.instance)
        messages.success(request, f"Overtime request submitted: {ot.period_display} ({ot.hours} h). Your manager was notified.")
        return redirect("leaves:overtime")
    mine = Paginator(OvertimeRequest.objects.filter(applicant=request.user).select_related("reviewed_by"), 10).get_page(request.GET.get("page"))
    year = timezone.localdate().year
    approved_hours = sum(
        (o.hours for o in OvertimeRequest.objects.filter(applicant=request.user, status=Status.APPROVED, date__year=year)),
        0,
    )
    return render(request, "leaves/overtime.html", {
        "form": form, "page": mine, "requests": mine.object_list, "approved_hours": approved_hours, "year": year,
        "max_hours": settings.OT_MAX_HOURS_PER_DAY,
    })


@login_required
@require_POST
def overtime_cancel(request, pk):
    ot = get_object_or_404(OvertimeRequest, pk=pk)
    try:
        services.cancel_overtime(ot, request.user)
        messages.success(request, "Overtime request cancelled.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect(_safe_next(request, reverse("leaves:overtime")))


@login_required
@require_POST
def overtime_review(request, pk):
    decision = request.POST.get("decision")
    if decision not in {"approve", "reject"}:
        return HttpResponseBadRequest("Invalid decision.")
    try:
        ot = services.review_overtime(pk, request.user, decision == "approve", request.POST.get("comment", ""))
        messages.success(request, f"{ot.applicant.full_name}'s overtime was {ot.get_status_display().lower()}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except OvertimeRequest.DoesNotExist:
        raise Http404
    return redirect(_safe_next(request, reverse("leaves:team")))


@login_required
@require_POST
def overtime_review_all(request):
    """Approve every pending OT request listed on the Team leaves page in one click."""
    if not request.user.can_approve_leaves:
        raise PermissionDenied
    done, failed = services.bulk_review(
        services.review_overtime, _bulk_ids(request), request.user, True, request.POST.get("comment", "")
    )
    _bulk_respond(request, done, failed, "OT request")
    return redirect(_safe_next(request, reverse("leaves:team") + "#overtime"))


# ----------------------------------------------------------------- admin: standard leaves
class LeaveTypeListView(AdminRequiredMixin, ListView):
    model = LeaveType
    template_name = "leaves/type_list.html"
    context_object_name = "types"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "policy": LeavePolicy.load()}


@login_required
def policy_edit(request):
    """Admin sets the maximum leave hours anyone may book on one day."""
    if not request.user.is_admin:
        raise PermissionDenied
    policy = LeavePolicy.load()
    form = LeavePolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        policy = form.save(commit=False)
        policy.updated_by = request.user
        policy.save()
        messages.success(request, f"Daily leave limit is now {policy.max_hours_per_day} h.")
        return redirect("leaves:type_list")
    return render(request, "leaves/policy_form.html", {"form": form, "policy": policy})


class LeaveTypeCreateView(AdminRequiredMixin, CreateView):
    model = LeaveType
    form_class = LeaveTypeForm
    template_name = "leaves/type_form.html"
    success_url = reverse_lazy("leaves:type_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Standard leave created.")
        return super().form_valid(form)


class LeaveTypeUpdateView(AdminRequiredMixin, UpdateView):
    model = LeaveType
    form_class = LeaveTypeForm
    template_name = "leaves/type_form.html"
    success_url = reverse_lazy("leaves:type_list")

    def form_valid(self, form):
        messages.success(self.request, "Standard leave updated.")
        return super().form_valid(form)
