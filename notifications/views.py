from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .forms import BroadcastForm
from .models import Broadcast, Notification


@login_required
def notification_list(request):
    page = Paginator(Notification.objects.filter(recipient=request.user), 20).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page": page})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not note.is_read:
        note.is_read = True
        note.save(update_fields=["is_read"])
    target = note.url
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect("notifications:list")


@login_required
def broadcast(request):
    """Admin-only: push a notification to everyone, a role, or hand-picked accounts."""
    if not request.user.is_admin:
        raise PermissionDenied
    initial = {}
    ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()][:500]
    if ids:
        initial = {"audience": Broadcast.Audience.SELECTED, "recipients": ids}
    form = BroadcastForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        recipients = form.resolve_recipients()
        sent = services.broadcast(
            request.user, recipients, form.cleaned_data["title"], form.cleaned_data["message"],
            form.cleaned_data["url"], form.cleaned_data["audience"], form.cleaned_data["send_email"],
        )
        messages.success(request, f"Notification sent to {sent.recipient_count} account(s).")
        return redirect("notifications:broadcast")
    return render(request, "notifications/broadcast.html", {
        "form": form, "recent": Broadcast.objects.select_related("sent_by")[:8],
    })
