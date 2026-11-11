from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "is_read", "created_at")
    list_filter = ("is_read",)


from .models import Broadcast  # noqa: E402


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "recipient_count", "emailed", "sent_by", "created_at")
    readonly_fields = [f.name for f in Broadcast._meta.fields]

    def has_add_permission(self, request):
        return False        # send them from /notifications/broadcast/
