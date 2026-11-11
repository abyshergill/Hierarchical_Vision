import os
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone

from accounts.models import IMAGE_EXTENSIONS, validate_image_content, validate_image_dimensions, validate_image_size


# upload_to callables must be module-level functions (migrations serialise them by name)
def newsletter_image_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"newsletter/{uuid.uuid4().hex}{ext}"


class NewsGroup(models.Model):
    """A private, department-specific newsletter space.

    Admins create groups and assign a manager. Only admins, the group manager and people they approved can read or
    post in it; everybody else can only see that the group exists and ask for access.
    """

    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_news_groups",
        help_text="Approves access requests and moderates the group. Admins can always do both.",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="newsgroup_name_ci_unique")]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("newsletter:group_detail", args=[self.pk])

    def can_manage(self, user):
        """Approve / reject requests, add / remove people, moderate posts and comments."""
        return bool(user.is_authenticated and user.is_active and (user.is_admin or self.manager_id == user.pk))

    def can_access(self, user):
        """Read, post and comment. Cached per instance so list pages do not query once per post."""
        if not (user.is_authenticated and user.is_active):
            return False
        if self.can_manage(user):
            return True
        cache = self.__dict__.setdefault("_access_cache", {})
        if user.pk not in cache:
            cache[user.pk] = self.memberships.filter(user_id=user.pk).exists()
        return cache[user.pk]


class GroupMembership(models.Model):
    group = models.ForeignKey(NewsGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="news_group_memberships")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__full_name"]
        constraints = [models.UniqueConstraint(fields=["group", "user"], name="newsgroup_one_membership")]

    def __str__(self):
        return f"{self.user_id} in {self.group_id}"


class GroupAccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    group = models.ForeignKey(NewsGroup, on_delete=models.CASCADE, related_name="requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="news_group_requests")
    message = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "user"], condition=Q(status="pending"), name="newsgroup_one_pending_request"
            )
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.group_id} ({self.status})"

    def decide(self, approve, by):
        """Atomically close a pending request. Returns False if somebody else already decided it."""
        status = self.Status.APPROVED if approve else self.Status.REJECTED
        changed = type(self).objects.filter(pk=self.pk, status=self.Status.PENDING).update(
            status=status, decided_by=by, decided_at=timezone.now()
        )
        if changed and approve:
            GroupMembership.objects.get_or_create(group=self.group, user=self.user, defaults={"added_by": by})
        return bool(changed)


class PostQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Company-wide posts + posts of the groups this person may enter. Never leaks private group content."""
        if not (user.is_authenticated and user.is_active):
            return self.filter(group__isnull=True)
        if user.is_admin:
            return self
        member_of = GroupMembership.objects.filter(user=user).values("group_id")
        return self.filter(Q(group__isnull=True) | Q(group__manager=user) | Q(group_id__in=member_of))


class Post(models.Model):
    """A newsletter entry: text + images. ``group`` empty = company-wide (public); otherwise private to that group."""

    title = models.CharField(max_length=120)
    body = models.TextField(max_length=5000)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="newsletter_posts"
    )
    group = models.ForeignKey(NewsGroup, null=True, blank=True, on_delete=models.CASCADE, related_name="posts")
    is_pinned = models.BooleanField(default=False, help_text="Pinned posts stay at the top and appear in the Pinned sidebar.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-is_pinned", "-created_at"]
        indexes = [models.Index(fields=["group", "-created_at"], name="news_post_group_idx")]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("newsletter:detail", args=[self.pk])

    def can_edit(self, user):
        """Company posts: admins everything, publishers their own. Group posts: admins and the group manager
        everything, members only their own (and only while they still have access)."""
        if not user.is_authenticated:
            return False
        if user.is_admin:
            return True
        if self.group_id:
            return self.group.can_manage(user) or (self.author_id == user.pk and self.group.can_access(user))
        return user.can_publish_newsletter and self.author_id == user.pk

    def can_pin(self, user):
        if not user.is_authenticated:
            return False
        return user.is_admin or bool(self.group_id and self.group.can_manage(user))

    def purge_images(self, queryset=None):
        """Delete image files from storage (call before removing rows)."""
        for img in (queryset if queryset is not None else self.images.all()):
            img.image.delete(save=False)


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(
        upload_to=newsletter_image_path,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size, validate_image_dimensions, validate_image_content],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Image for {self.post_id}"


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="newsletter_comments")
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Comment on {self.post_id}"

    def can_delete(self, user):
        """The author, an Admin, or the manager of the group the post belongs to."""
        if not user.is_authenticated:
            return False
        if user.is_admin or self.author_id == user.pk:
            return True
        return bool(self.post.group_id and self.post.group.can_manage(user))
