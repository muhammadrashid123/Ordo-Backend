import os
from django.conf import settings
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.accounts.models import (
    Company,
    CompanyMember,
    Office,
    Subaccount,
    Subscription,
    User,
)

class CompanyOfficeReadPermission(IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Company):
            return CompanyMember.objects.filter(company=obj, user=request.user)
        elif isinstance(obj, Office):
            return CompanyMember.objects.filter(company=obj.company, user=request.user)


class OrderCheckoutPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        company_pk = view.kwargs.get("company_pk")
        return CompanyMember.objects.filter(user=request.user, company_id=company_pk).exists()


class ProductStatusUpdatePermission(IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        return CompanyMember.objects.filter(company=obj.vendor_order.order.office.company, user=request.user).exists()


class OfficeSubscriptionPermission(BasePermission):
    """office with active subscription"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if the company has a previous subscription
        company_offices = Office.objects.filter(company_id=view.kwargs.get("company_pk")).values('id')
        offices_ids = [office['id'] for office in company_offices]
        
        return Subscription.objects.filter(office_id__in=offices_ids, cancelled_on__isnull=True).exists()


class OrderApprovalPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        company_pk = view.kwargs.get("company_pk")
        return CompanyMember.objects.filter(
            user=request.user, company_id=company_pk, role__in=[User.Role.ADMIN, User.Role.OWNER]
        ).exists()


class DentalCityOrderFlowPermission(BasePermission):
    def has_permission(self, request, view):
        header = request.META.get("HTTP_AUTHORIZATION")
        return header == os.getenv('DENTAL_CITY_AUTH_KEY')


class SubaccountPermission(BasePermission):
    def has_object_permission(self, request, view, obj: Subaccount):
        return CompanyMember.objects.filter(
            user=request.user, company_id=obj.budget.office.company_id, role__in=[User.Role.ADMIN, User.Role.OWNER]
        ).exists()
