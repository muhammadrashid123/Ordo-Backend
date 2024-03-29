"""ordo_backend URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.auth.views import MyTokenObtainPairView, MyTokenVerifyView, ImpersonateUser
from config.utils import get_bool_config

spectacular_urlpatterns = [
    # YOUR PATTERNS
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI:
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.orders.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.admin_view.urls")),
    path("api/greetings/", include("apps.greetings.urls")),
    path("api/waitlist/", include("apps.waitlist.urls")),
    path("_nested_admin/", include("nested_admin.urls")),
    path("api/auth/login/", MyTokenObtainPairView.as_view(), name="login"),
    path("api/token-verify/", MyTokenVerifyView.as_view(), name="verify-token"),
    path(
        "api/password_reset/",
        include("django_rest_passwordreset.urls", namespace="password_reset"),
    ),
    path("api/audit/", include("apps.audit.urls")),
    path("api/reports/", include("apps.reports.urls")),
    path("api/auth/login-impersonate/<int:user_id>/", ImpersonateUser.as_view(), name="login-impersonate"),
]

if get_bool_config("EXPOSE_SCHEMA", False):
    from drf_spectacular.views import (
        SpectacularAPIView,
        SpectacularRedocView,
        SpectacularSwaggerView,
    )

    spectacular_urlpatterns = [
        # YOUR PATTERNS
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        # Optional UI:
        path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
        path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    ]
    urlpatterns = [*urlpatterns, *spectacular_urlpatterns]
