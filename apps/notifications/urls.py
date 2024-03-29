from django.urls import include, path
from rest_framework_nested.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register(r"notifications", v.NotificationModelViewset)
urlpatterns = [
    path("", include(router.urls)),
]
