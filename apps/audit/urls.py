from django.urls import include, path
from . import views

urlpatterns = [
    path("bad-image", views.ReportBadUrl.as_view(), name="report-bad-url"),
]