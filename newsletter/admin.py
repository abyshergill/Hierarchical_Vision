from django.contrib import admin

from .models import GroupAccessRequest, GroupMembership, NewsGroup, Post, PostImage


class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 0


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "author", "is_pinned", "created_at")
    list_filter = ("is_pinned", "group")
    search_fields = ("title", "body")
    inlines = [PostImageInline]


class MembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0
    raw_id_fields = ("user", "added_by")


@admin.register(NewsGroup)
class NewsGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "manager", "created_at")
    search_fields = ("name", "description")
    raw_id_fields = ("manager", "created_by")
    inlines = [MembershipInline]


@admin.register(GroupAccessRequest)
class GroupAccessRequestAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "status", "created_at", "decided_by")
    list_filter = ("status", "group")
    raw_id_fields = ("user", "decided_by")
