from django.conf import settings
from django.db import models


class SupportRequest(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "Request received"
        IN_PROGRESS = "in_progress", "In process"
        COMPLETE = "complete", "Complete"

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_requests")
    subject = models.CharField(max_length=150)
    description = models.TextField(max_length=5000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.subject
