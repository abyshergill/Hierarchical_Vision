from django.urls import path
from . import views

app_name = "support"
urlpatterns = [
    path("", views.create, name="create"),
    path("inbox/", views.inbox, name="inbox"),
    path("<int:pk>/status/", views.update, name="update"),
]
