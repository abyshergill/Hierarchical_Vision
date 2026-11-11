from django.urls import path

from . import views

app_name = "newsletter"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("new/", views.post_create, name="create"),
    path("publishers/", views.publishers, name="publishers"),
    path("groups/", views.group_list, name="group_list"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/<int:group_pk>/post/", views.post_create, name="group_post_create"),
    path("groups/<int:pk>/request/", views.request_access, name="request_access"),
    path("groups/<int:pk>/members/", views.group_members, name="group_members"),
    path("groups/<int:pk>/members/<int:user_pk>/remove/", views.member_remove, name="member_remove"),
    path("groups/requests/<int:pk>/approve/", views.request_decide, {"approve": True}, name="request_approve"),
    path("groups/requests/<int:pk>/reject/", views.request_decide, {"approve": False}, name="request_reject"),
    path("<int:pk>/", views.post_detail, name="detail"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/comments/", views.comment_create, name="comment_create"),
    path("comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
]
