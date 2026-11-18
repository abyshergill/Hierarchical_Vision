from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from accounts.ratelimit import rate_limit
from notifications import services as notify_services
from notifications.services import notify

from . import services
from .forms import AccessRequestForm, CommentForm, GroupForm, PostForm
from .models import Comment, GroupAccessRequest, GroupMembership, NewsGroup, Post, PostImage

Req = GroupAccessRequest.Status


def _posts():
    return Post.objects.select_related("author", "group", "group__manager").prefetch_related("images", "comments__author")


def _flag_editable(posts, user):
    for post in posts:
        post.editable = post.can_edit(user)
        post.can_moderate_comments = bool(post.group_id and post.group.can_manage(user))
    return posts


def _after_post(post_or_group):
    """Where to go after a create / edit / delete: the group page for group posts, else the company newsletter."""
    group = post_or_group if isinstance(post_or_group, NewsGroup) else post_or_group.group
    return redirect(group) if group else redirect("newsletter:list")


# ----------------------------------------------------------------------------- company newsletter
def post_list(request):
    page = Paginator(_posts().filter(group__isnull=True), settings.NEWSLETTER_PAGE_SIZE).get_page(request.GET.get("page"))
    posts = _flag_editable(list(page.object_list), request.user)
    return render(request, "newsletter/list.html", {"page": page, "posts": posts})


def post_detail(request, pk):
    post = get_object_or_404(_posts(), pk=pk)
    if post.group_id and not post.group.can_access(request.user):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        messages.info(request, "This post belongs to a private group. Request access to read it.")
        return redirect(post.group)
    return render(request, "newsletter/list.html", {
        "posts": _flag_editable([post], request.user), "single": True, "group": post.group,
    })


@login_required
def post_create(request, group_pk=None):
    group = None
    if group_pk is not None:
        group = get_object_or_404(NewsGroup, pk=group_pk)
        if not group.can_access(request.user):
            raise PermissionDenied
    elif not request.user.can_publish_newsletter:
        raise PermissionDenied
    form = PostForm(request.POST or None, request.FILES or None, user=request.user, group=group)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            post = form.save(commit=False)
            post.author = request.user
            post.group = group
            post.save()
            for f in form.cleaned_data["images"]:
                PostImage.objects.create(post=post, image=f)
        if not group and request.user.is_admin and form.cleaned_data.get("notify_everyone"):
            notify_services.broadcast(
                request.user, User.objects.filter(is_active=True).exclude(pk=request.user.pk),
                f"Newsletter: {post.title}", post.body[:200], post.get_absolute_url(), audience="all",
            )
        messages.success(request, f"Published in {group.name}." if group else "Published to the newsletter.")
        return _after_post(post)
    return render(request, "newsletter/form.html", {"form": form, "post": None, "group": group})


@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related("group"), pk=pk)
    if not post.can_edit(request.user):
        raise PermissionDenied
    form = PostForm(request.POST or None, request.FILES or None, instance=post, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            post = form.save()
            removed = form.cleaned_data.get("remove_images")
            if removed:
                post.purge_images(removed)
                PostImage.objects.filter(pk__in=[i.pk for i in removed], post=post).delete()
            for f in form.cleaned_data["images"]:
                PostImage.objects.create(post=post, image=f)
        messages.success(request, "Post updated.")
        return _after_post(post)
    return render(request, "newsletter/form.html", {"form": form, "post": post, "group": post.group})


@login_required
@require_POST
def post_delete(request, pk):
    post = get_object_or_404(Post.objects.select_related("group"), pk=pk)
    if not post.can_edit(request.user):
        raise PermissionDenied
    group = post.group
    post.purge_images()
    post.delete()
    messages.success(request, "Post deleted.")
    return _after_post(group) if group else redirect("newsletter:list")


@login_required
def publishers(request):
    """Admin decides which managers / employees may publish to the company-wide newsletter."""
    if not request.user.is_admin:
        raise PermissionDenied
    people = User.objects.filter(is_active=True).exclude(role=Role.ADMIN).order_by("full_name")
    if request.method == "POST":
        allowed = set(people.values_list("pk", flat=True))
        chosen = {int(x) for x in request.POST.getlist("publishers") if x.isdigit()} & allowed
        before = set(people.filter(newsletter_publisher=True).values_list("pk", flat=True))
        User.objects.filter(pk__in=allowed).update(newsletter_publisher=False)
        User.objects.filter(pk__in=chosen).update(newsletter_publisher=True)
        for user in User.objects.filter(pk__in=chosen - before):
            notify(user, "You can now publish to the newsletter",
                   "An admin gave you permission to post in the company newsletter.",
                   url=reverse("newsletter:create"), send_email=False)
        messages.success(request, f"Saved. {len(chosen)} person(s) can publish to the newsletter.")
        return redirect("newsletter:publishers")
    return render(request, "newsletter/publishers.html", {"people": people})


# ----------------------------------------------------------------------------- comments
@login_required
@require_POST
@rate_limit("newsletter_comment")
def comment_create(request, pk):
    post = get_object_or_404(Post.objects.select_related("group"), pk=pk)
    if post.group_id and not post.group.can_access(request.user):
        raise PermissionDenied
    form = CommentForm(request.POST)
    if form.is_valid():
        Comment.objects.create(post=post, author=request.user, body=form.cleaned_data["body"])
        messages.success(request, "Comment added.")
    else:
        messages.error(request, "Enter a comment of 1 to 1,000 characters.")
    return redirect(post.get_absolute_url() + f"#comments-{post.pk}")


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("post__group"), pk=pk)
    if not comment.can_delete(request.user):
        raise PermissionDenied
    url = comment.post.get_absolute_url() + f"#comments-{comment.post_id}"
    comment.delete()
    messages.success(request, "Comment deleted.")
    return redirect(url)


# ----------------------------------------------------------------------------- groups
@login_required
def group_list(request):
    groups = list(NewsGroup.objects.select_related("manager").annotate(member_count=Count("memberships")))
    states = services.group_states(request.user, groups)
    for g in groups:
        g.state = states.get(g.pk)
    groups.sort(key=lambda g: g.state not in ("manager", "member"))      # groups you belong to come first
    page = Paginator(groups, 10).get_page(request.GET.get("page"))
    return render(request, "newsletter/group_list.html", {"page": page, "groups": page.object_list})


@login_required
def group_detail(request, pk):
    group = get_object_or_404(NewsGroup.objects.select_related("manager"), pk=pk)
    user = request.user
    ctx = {"group": group, "can_manage": group.can_manage(user)}
    if not group.can_access(user):                       # private: no posts, no member list, only the request form
        ctx["pending"] = group.requests.filter(user=user, status=Req.PENDING).first()
        ctx["last_rejected"] = group.requests.filter(user=user, status=Req.REJECTED).first() if not ctx["pending"] else None
        ctx["form"] = AccessRequestForm()
        return render(request, "newsletter/group_locked.html", ctx)
    page = Paginator(_posts().filter(group=group), settings.NEWSLETTER_PAGE_SIZE).get_page(request.GET.get("page"))
    ctx.update({
        "page": page, "posts": _flag_editable(list(page.object_list), user),
        "member_count": group.memberships.count(),
        "pending_count": group.requests.filter(status=Req.PENDING).count() if ctx["can_manage"] else 0,
    })
    return render(request, "newsletter/group.html", ctx)


@login_required
def group_create(request):
    if not request.user.is_admin:
        raise PermissionDenied
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.created_by = request.user
        try:
            group.save()
        except IntegrityError:
            form.add_error("name", "A group with this name already exists.")
        else:
            _notify_new_manager(group, request.user)
            messages.success(request, f"Group “{group.name}” created.")
            return redirect(group)
    return render(request, "newsletter/group_form.html", {"form": form, "group": None})


@login_required
def group_edit(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied
    group = get_object_or_404(NewsGroup, pk=pk)
    old_manager = group.manager_id
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        try:
            group = form.save()
        except IntegrityError:
            form.add_error("name", "A group with this name already exists.")
        else:
            if group.manager_id != old_manager:
                _notify_new_manager(group, request.user)
            messages.success(request, "Group saved.")
            return redirect(group)
    return render(request, "newsletter/group_form.html", {"form": form, "group": group})


@login_required
@require_POST
def group_delete(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied
    group = get_object_or_404(NewsGroup, pk=pk)
    with transaction.atomic():
        for post in group.posts.all():
            post.purge_images()
        name = group.name
        group.delete()
    messages.success(request, f"Group “{name}” and all its posts were deleted.")
    return redirect("newsletter:group_list")


def _notify_new_manager(group, by):
    if group.manager_id and group.manager_id != by.pk:
        notify(group.manager, f"You now manage the “{group.name}” group",
               "You can approve access requests, add people and moderate posts.", url=group.get_absolute_url(), send_email=False)


# ----------------------------------------------------------------------------- access requests & members
@login_required
@require_POST
@rate_limit("newsletter_group_request")
def request_access(request, pk):
    group = get_object_or_404(NewsGroup.objects.select_related("manager"), pk=pk)
    user = request.user
    if group.can_access(user):
        messages.info(request, "You already have access to this group.")
        return redirect(group)
    form = AccessRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Your message can be at most 300 characters.")
        return redirect(group)
    try:
        with transaction.atomic():
            GroupAccessRequest.objects.create(group=group, user=user, message=form.cleaned_data["message"])
    except IntegrityError:                                   # one open request per person and group
        messages.info(request, "Your request is already waiting for approval.")
        return redirect(group)
    for person in services.approvers(group):
        notify(person, f"Access request: {group.name}", f"{user.full_name} ({user.employee_id}) asks to join this group.",
               url=reverse("newsletter:group_members", args=[group.pk]), send_email=False)
    messages.success(request, "Request sent. You will be notified when it is approved.")
    return redirect(group)


@login_required
def group_members(request, pk):
    """Manager / Admin console: approve or reject requests, add or remove people."""
    group = get_object_or_404(NewsGroup.objects.select_related("manager"), pk=pk)
    if not group.can_manage(request.user):
        raise PermissionDenied
    member_ids = set(group.memberships.values_list("user_id", flat=True))
    candidates = User.objects.filter(is_active=True).exclude(pk__in=member_ids).order_by("full_name")
    if group.manager_id:
        candidates = candidates.exclude(pk=group.manager_id)
    if request.method == "POST":                              # add people
        allowed = set(candidates.values_list("pk", flat=True))
        chosen = {int(x) for x in request.POST.getlist("people") if x.isdigit()} & allowed
        added = 0
        for person in User.objects.filter(pk__in=chosen):
            _, created = GroupMembership.objects.get_or_create(group=group, user=person, defaults={"added_by": request.user})
            if created:
                added += 1
                notify(person, f"You were added to “{group.name}”", "You can now read, post and comment in this group.",
                       url=group.get_absolute_url(), send_email=False)
        GroupAccessRequest.objects.filter(group=group, user_id__in=chosen, status=Req.PENDING).update(
            status=Req.APPROVED, decided_by=request.user, decided_at=timezone.now())
        messages.success(request, f"{added} person(s) added.")
        return redirect("newsletter:group_members", pk=group.pk)
    return render(request, "newsletter/group_members.html", {
        "group": group,
        "pending": group.requests.filter(status=Req.PENDING).select_related("user"),
        "members": group.memberships.select_related("user"),
        "candidates": candidates,
    })


@login_required
@require_POST
def request_decide(request, pk, approve):
    req = get_object_or_404(GroupAccessRequest.objects.select_related("group", "user"), pk=pk)
    if not req.group.can_manage(request.user):
        raise PermissionDenied
    with transaction.atomic():
        done = req.decide(approve, request.user)
    if not done:
        messages.info(request, "This request was already handled.")
    else:
        verdict = "approved" if approve else "declined"
        notify(req.user, f"Access to “{req.group.name}” {verdict}",
               "You can now read, post and comment." if approve else "Contact the group manager if you think this is a mistake.",
               url=req.group.get_absolute_url(), send_email=False)
        messages.success(request, f"Request from {req.user.full_name} {verdict}.")
    return redirect("newsletter:group_members", pk=req.group_id)


@login_required
@require_POST
def member_remove(request, pk, user_pk):
    group = get_object_or_404(NewsGroup, pk=pk)
    if not group.can_manage(request.user):
        raise PermissionDenied
    deleted, _ = GroupMembership.objects.filter(group=group, user_id=user_pk).delete()
    if deleted:
        messages.success(request, "Member removed. They keep no access to the group.")
    return redirect("newsletter:group_members", pk=group.pk)
