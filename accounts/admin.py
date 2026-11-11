from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .forms import UserAdminForm
from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    list_display = ("employee_id", "full_name", "email", "position", "role", "manager", "newsletter_publisher", "is_active")
    list_filter = ("role", "is_active", "newsletter_publisher")
    search_fields = ("employee_id", "full_name", "email")
    ordering = ("full_name",)
    actions = ["send_notification"]

    @admin.action(description="Send a notification to the selected users")
    def send_notification(self, request, queryset):
        """Admin-only shortcut: open the broadcast page with these people pre-selected."""
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True)[:500])
        return redirect(f"{reverse('notifications:broadcast')}?ids={ids}")
