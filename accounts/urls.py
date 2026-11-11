from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("api/search/", views.api_search, name="api_search"),
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/change/", views.PasswordChange.as_view(), name="password_change"),
    path("profile/", views.my_profile, name="my_profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("u/<str:employee_id>/", views.profile, name="profile"),
    path("org-chart/", views.org_chart, name="org_chart"),
    path("org-chart/data/", views.org_data, name="org_data"),
    path("manage/users/", views.UserListView.as_view(), name="user_list"),
    path("manage/users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("manage/users/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_edit"),
]
