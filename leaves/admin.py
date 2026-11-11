from django.contrib import admin

from .models import Holiday, LeaveApplication, LeaveDay, LeaveEntitlement, LeavePolicy, LeaveType


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "annual_quota_days", "allow_hourly", "max_hours_per_day", "is_active")


@admin.register(LeaveEntitlement)
class LeaveEntitlementAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "year", "allocated_days")
    list_filter = ("year", "leave_type")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name")


@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = ("__str__", "max_hours_per_day", "default_start_time", "updated_by", "updated_at")

    def has_add_permission(self, request):
        return not LeavePolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class LeaveDayInline(admin.TabularInline):
    model = LeaveDay
    extra = 0


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ("applicant", "leave_type", "start_date", "end_date", "total_hours", "status")
    list_filter = ("status", "leave_type")
    search_fields = ("applicant__full_name", "applicant__employee_id")
    inlines = [LeaveDayInline]
