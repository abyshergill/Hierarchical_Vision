from django.conf import settings
from django.db import models


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient_id}: {self.title}"


class Broadcast(models.Model):
    """Audit trail of admin-pushed announcements."""

    class Audience(models.TextChoices):
        ALL = "all", "Everyone"
        MANAGERS = "managers", "All managers"
        EMPLOYEES = "employees", "All employees"
        SELECTED = "selected", "Specific people"

    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    audience = models.CharField(max_length=10, choices=Audience.choices)
    recipient_count = models.PositiveIntegerField(default=0)
    emailed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} -> {self.get_audience_display()} ({self.recipient_count})"
