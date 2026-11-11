from django.contrib import admin
from .models import SupportRequest


@admin.register(SupportRequest)
class SupportRequestAdmin(admin.ModelAdmin):
    list_display = ("subject", "requester", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("subject", "requester__full_name", "requester__employee_id")
    readonly_fields = ("requester", "subject", "description", "created_at", "updated_at")

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_admin

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_admin

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_admin

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
