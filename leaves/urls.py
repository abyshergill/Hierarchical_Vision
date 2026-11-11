from django.urls import path

from . import views

app_name = "leaves"

urlpatterns = [
    path("apply/", views.apply, name="apply"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("<int:pk>/review/", views.review, name="review"),
    path("employee/<str:employee_id>/download/", views.employee_download, name="employee_download"),
    path("team/", views.team, name="team"),
    path("holidays/", views.holidays, name="holidays"),
    path("holidays/download.pdf", views.holidays_pdf, name="holidays_pdf"),
    path("holidays/<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
    path("policy/", views.policy_edit, name="policy"),
    path("types/", views.LeaveTypeListView.as_view(), name="type_list"),
    path("types/new/", views.LeaveTypeCreateView.as_view(), name="type_create"),
    path("types/<int:pk>/edit/", views.LeaveTypeUpdateView.as_view(), name="type_edit"),
]
