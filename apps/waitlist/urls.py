# urls.py
from django.urls import path

from .views import WaitListCreateAPIView

urlpatterns = [
    path("create/", WaitListCreateAPIView.as_view(), name="waitlist-create-api"),
]
