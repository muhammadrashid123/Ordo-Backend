from django.urls import include, path
from . import views

urlpatterns = [
    path("inventory-list/", views.InventoryListAPIView.as_view(), name="inventory-list"),
]