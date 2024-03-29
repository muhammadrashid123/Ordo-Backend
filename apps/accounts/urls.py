from django.urls import include, path
from rest_framework_nested.routers import NestedSimpleRouter, SimpleRouter

import apps.accounts.apps
import apps.accounts.tasks
import apps.accounts.views.company
import apps.accounts.views.company_member
import apps.accounts.views.company_region
import apps.accounts.views.coupon_check
import apps.accounts.views.crazy_dental_integration
import apps.accounts.views.health
import apps.accounts.views.invitation_check
import apps.accounts.views.office
import apps.accounts.views.office_budget
import apps.accounts.views.office_vendor
import apps.accounts.views.sub_company
import apps.accounts.views.subaccount
import apps.accounts.views.user
import apps.accounts.views.user_signup
import apps.accounts.views.vendor
import apps.accounts.views.vendor_request

router = SimpleRouter(trailing_slash=False)
router.register(r"companies", apps.accounts.views.company.CompanyViewSet, basename="companies")
router.register(r"vendors", apps.accounts.views.vendor.VendorViewSet, basename="vendors")
router.register(r"users", apps.accounts.views.user.UserViewSet, basename="users")
router.register(r"subcompanies", apps.accounts.views.sub_company.SubCompanyViewSet, basename="subcompany")

company_router = NestedSimpleRouter(router, r"companies", lookup="company")
company_router.register(r"members", apps.accounts.views.company_member.CompanyMemberViewSet, basename="members")
company_router.register(r"offices", apps.accounts.views.office.OfficeViewSet, basename="offices")
company_router.register(
    r"vendor-requests", apps.accounts.views.vendor_request.VendorRequestViewSet, basename="vendor-requests"
)
company_router.register(r"subcompany", apps.accounts.views.sub_company.SubCompanyViewSet, basename="subcompanies")
company_router.register(r"regions", apps.accounts.views.company_region.RegionViewSet, basename="company-regions")

office_router = NestedSimpleRouter(company_router, r"offices", lookup="office")
office_router.register(r"vendors", apps.accounts.views.office_vendor.OfficeVendorViewSet, basename="vendors")
office_router.register(r"budgets", apps.accounts.views.office_budget.BudgetViewSet, basename="budgets")
office_router.register(r"subaccounts", apps.accounts.views.subaccount.SubaccountViewSet, basename="subaccounts")

urlpatterns = [
    path("health/check", apps.accounts.views.health.HealthCheck.as_view()),
    path("", include(router.urls)),
    path("", include(company_router.urls)),
    path("", include(office_router.urls)),
    path(
        "crazy-dental/create-customer",
        apps.accounts.views.crazy_dental_integration.CreateCustomerAPIView.as_view(),
        name="create-customer",
    ),
    path(
        "crazy-dental/user-address",
        apps.accounts.views.crazy_dental_integration.UserAddressListCreateAPIView.as_view(),
        name="user-address",
    ),
    path(
        "crazy-dental/user-credit-card",
        apps.accounts.views.crazy_dental_integration.DCDentalCreditCardView.as_view(),
        name="user-credit-card",
    ),
    path("auth/signup", apps.accounts.views.user_signup.UserSignupAPIView.as_view(), name="signup"),
    path(
        "accept-invite/<str:token>", apps.accounts.views.invitation_check.CompanyMemberInvitationCheckAPIView.as_view()
    ),
    path("check-coupon", apps.accounts.views.coupon_check.CouponCheckView.as_view(), name="check-coupon"),
]
