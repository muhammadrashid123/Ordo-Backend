from django.urls import path

from .views import GetAllGreetings, GetGreetingsByRole, GetLastGreetings

urlpatterns = [
    path("last", GetLastGreetings.as_view(), name="last"),
    path("all", GetAllGreetings.as_view(), name="all_greetings"),
    path("all/<str:role>", GetGreetingsByRole.as_view(), name="greetings_by_role"),
]
