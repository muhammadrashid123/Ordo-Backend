from django.urls import include, path
from rest_framework_nested.routers import SimpleRouter

from .views import AdminDashboardModelViewSet, VendorSortedOrderViewSet

router = SimpleRouter(trailing_slash=False)
router.register(r"admin-view", AdminDashboardModelViewSet, basename="admin_view")
router.register(r"analytics", VendorSortedOrderViewSet, basename="analytics")

urlpatterns = [
    path("", include(router.urls)),
]
