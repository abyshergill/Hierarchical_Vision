from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.ratelimit import rate_limit
from .forms import StatusForm, SupportForm
from .models import SupportRequest


def require_admin(user):
    if not user.is_admin:
        raise PermissionDenied


@login_required
@rate_limit("support_submit")
def create(request):
    form = SupportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.requester = request.user
        ticket.save()
        messages.success(request, "Your support request was submitted to the admins.")
        return redirect("support:create")
    return render(request, "support/create.html", {"form": form})


@login_required
def inbox(request):
    require_admin(request.user)
    status = request.GET.get("status", "")
    tickets = SupportRequest.objects.select_related("requester")
    if status in SupportRequest.Status.values:
        tickets = tickets.filter(status=status)
    return render(request, "support/inbox.html", {"tickets": tickets, "statuses": SupportRequest.Status.choices, "selected_status": status})


@login_required
@require_POST
def update(request, pk):
    require_admin(request.user)
    ticket = get_object_or_404(SupportRequest, pk=pk)
    form = StatusForm(request.POST, instance=ticket)
    if form.is_valid():
        form.save()
        messages.success(request, "Support request status updated.")
    else:
        messages.error(request, "Please select a valid status.")
    return redirect("support:inbox")
