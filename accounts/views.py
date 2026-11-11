from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView, UpdateView

from leaves.models import Holiday, LeaveApplication
from leaves.services import get_balances_for_users

from .forms import EmployeeLoginForm, ProfileSelfForm, UserAdminForm
from . import throttle
from .mixins import AdminRequiredMixin
from .ratelimit import rate_limit
from .models import User, search_employees

BRANCH_COLORS = ["#0a84ff", "#30d158", "#ff375f", "#ff9f0a", "#bf5af2", "#64d2ff", "#ac8e68", "#ffd60a"]


class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmployeeLoginForm
    redirect_authenticated_user = True

    def form_invalid(self, form):
        locked = throttle.is_locked(self.request, self.request.POST.get("username", ""))
        if locked:
            form.add_error(None, f"Too many failed attempts. Try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes.")
        response = super().form_invalid(form)
        if locked:
            response.status_code = 429
        return response


class PasswordChange(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:home")

    def form_valid(self, form):
        messages.success(self.request, "Your password was updated.")
        return super().form_valid(form)


# --------------------------------------------------------------------------- search
def home(request):
    return render(request, "accounts/home.html")


@rate_limit("search")
def search(request):
    q = request.GET.get("q", "").strip()
    results = list(search_employees(q)[:60]) if q else []
    # Typing an exact Employee ID jumps straight to the profile.
    exact = [u for u in results if u.employee_id.lower() == q.lower()]
    if request.user.is_authenticated and len(exact) == 1:
        return redirect(exact[0])
    return render(request, "accounts/search_results.html", {"q": q, "results": results})


@rate_limit("api_search")
def api_search(request):
    q = request.GET.get("q", "").strip()
    data = [
        {
            "name": u.full_name,
            "employee_id": u.employee_id,
            "position": u.position,
            "url": u.get_absolute_url(),
            "avatar": u.profile_picture.url if u.profile_picture else "",
            "initials": u.initials,
        }
        for u in (search_employees(q)[:6] if len(q) >= 1 else [])
    ]
    return JsonResponse({"results": data})


# --------------------------------------------------------------------------- profile
@login_required
def my_profile(request):
    return redirect(request.user)


@login_required
def profile(request, employee_id):
    target = get_object_or_404(User.objects.select_related("manager"), employee_id__iexact=employee_id, is_active=True)
    viewer = request.user
    can_see_private = viewer.can_view_private(target)     # leaves tab
    can_see_salary = viewer.can_view_salary(target)       # admins + the owner only (NOT managers)

    tab = request.GET.get("tab", "info")
    allowed_tabs = {"info"}
    if can_see_private:
        allowed_tabs.add("leaves")
    if can_see_salary:
        allowed_tabs.add("salary")
    if tab not in allowed_tabs:
        tab = "info"

    ctx = {
        "target": target,
        "tab": tab,
        "can_see_private": can_see_private,
        "can_see_salary": can_see_salary,
        "can_edit_self": viewer == target,
        "direct_reports": target.direct_reports.filter(is_active=True).order_by("full_name"),
        "chain": target.get_management_chain(),
    }

    if tab == "leaves":
        try:
            year = int(request.GET.get("year", timezone.localdate().year))
        except ValueError:
            year = timezone.localdate().year
        year = min(max(year, 2000), 2100)
        balances = get_balances_for_users([target], year)[target.pk]
        ctx.update(
            year=year,
            balances=balances,
            applications=target.leave_applications.select_related("leave_type", "reviewed_by", "alternate_employee").prefetch_related("days").order_by("-created_at")[:50],
            overtime=target.overtime_requests.select_related("reviewed_by")[:30],
            upcoming_holidays=Holiday.objects.filter(date__gte=timezone.localdate()).order_by("date")[:6],
            can_apply=viewer == target,
            can_review_target=viewer.can_review(target),
            can_download=viewer.can_export_leaves(target),
            Status=LeaveApplication.Status,
        )
    return render(request, "accounts/profile.html", ctx)


@login_required
def profile_edit(request):
    form = ProfileSelfForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect(request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})


# --------------------------------------------------------------------------- org chart
def org_chart(request):
    """Renders the endless-canvas shell; the people are loaded from ``org_data``."""
    return render(request, "accounts/org_chart.html")


@rate_limit("org_data")
def org_data(request):
    """Flat JSON list of active people; the browser builds the tree lazily.

    The chart is public; contact details are visible only to signed-in users. Edit / add links are only emitted for
    Admins, so no management URL is leaked to other roles (the views themselves
    are still Admin-only)."""
    is_admin = request.user.is_authenticated and request.user.is_admin
    users = []
    for u in User.objects.filter(is_active=True).order_by("full_name"):
        item = {
            "id": u.pk,
            "name": u.full_name,
            "employee_id": u.employee_id,
            "position": u.position or "",
            "manager_id": u.manager_id,
            "initials": u.initials,
            "image_url": u.profile_picture.url if u.profile_picture else "",
            "profile_url": u.get_absolute_url(),
        }
        if request.user.is_authenticated:
            item["email"] = u.email
            item["contact"] = u.contact_info or ""
        if is_admin:
            item["edit_url"] = reverse("accounts:user_edit", args=[u.pk])
            item["add_url"] = f"{reverse('accounts:user_create')}?manager={u.pk}"
        users.append(item)
    response = JsonResponse({"users": users})
    response["Cache-Control"] = "private, no-store"
    return response


# --------------------------------------------------------------------------- admin: user management
class UserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = "accounts/user_list.html"
    paginate_by = 25
    context_object_name = "users"

    def get_queryset(self):
        qs = User.objects.select_related("manager").order_by("full_name")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(employee_id__icontains=q) | Q(email__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class UserCreateView(AdminRequiredMixin, CreateView):
    model = User
    form_class = UserAdminForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def get_initial(self):
        initial = super().get_initial()
        manager = self.request.GET.get("manager", "")
        if manager.isdigit() and User.objects.filter(pk=int(manager), is_active=True).exists():
            initial["manager"] = int(manager)      # pre-select from the org chart "Add" button
        return initial

    def form_valid(self, form):
        messages.success(self.request, f"Created {form.instance.full_name}.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "creating": True}


class UserUpdateView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserAdminForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def form_valid(self, form):
        messages.success(self.request, f"Saved {form.instance.full_name}.")
        return super().form_valid(form)
