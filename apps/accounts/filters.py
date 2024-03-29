from decimal import Decimal

from django.contrib.admin import SimpleListFilter
from django.db.models import Count, F, Func, OuterRef, Q, Subquery
from django_filters import rest_framework as filters

from apps.common.choices import OrderStatus, OrderType
from apps.common.utils import CUSTOM_DATE_FILTER, get_date_range
from apps.orders import models as om

from .models import Budget, CompanyMember, Vendor


class BudgetFilter(filters.FilterSet):
    start_month = filters.DateFilter(field_name="month", lookup_expr="gte", input_formats=["%Y-%m"])
    end_month = filters.DateFilter(field_name="month", lookup_expr="lte", input_formats=["%Y-%m"])

    class Meta:
        model = Budget
        fields = ["start_month", "end_month"]


class VendorFilter(filters.FilterSet):
    slugs = filters.CharFilter(method="filter_slugs")

    class Meta:
        model = Vendor
        fields = ["slugs"]

    def filter_slugs(self, queryset, name, value):
        slugs = value.split(",")
        if slugs:
            return queryset.filter(slug__in=slugs)
        return queryset


class CompanyMemberFilter(filters.FilterSet):
    office_id = filters.NumberFilter(method="filter_office_members")

    class Meta:
        model = CompanyMember
        fields = ["office_id"]

    def filter_office_members(self, queryset, name, value):
        return queryset.filter(Q(office_id=value) | Q(office__isnull=True))


class VendorDateFilter(SimpleListFilter):
    title = "date range"

    parameter_name = "vendororder_range"

    def lookups(self, request, model_admin):
        return CUSTOM_DATE_FILTER

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the date range.
        """
        date_filter = Q(vendororder__status__in=[OrderStatus.OPEN, OrderStatus.CLOSED])
        date_range = get_date_range(self.value())
        if date_range:
            start_date, end_date = date_range
            date_filter &= Q(vendororder__order_date__gte=start_date, vendororder__order_date__lte=end_date)
        return queryset.annotate(_vendor_order_count=Count("vendororder", filter=date_filter)).order_by(
            "-_vendor_order_count"
        )


class CompanyDateFilter(SimpleListFilter):
    title = "date range"
    parameter_name = "date_range"

    def lookups(self, request, model_admin):
        return CUSTOM_DATE_FILTER

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the date range.
        """
        date_range = get_date_range(self.value())

        orders_filter = Q(
            order_type__in=[OrderType.ORDO_ORDER, OrderType.ORDER_PROCESSING], office__company_id=OuterRef("pk")
        )
        vendor_orders_filter = Q(
            status__in=[OrderStatus.OPEN, OrderStatus.CLOSED], order__office__company_id=OuterRef("pk")
        )
        total_amount_filter = Q(
            order_type__in=[OrderType.ORDO_ORDER, OrderType.ORDER_PROCESSING], office__company_id=OuterRef("pk")
        )

        if date_range:
            start_date, end_date = date_range
            orders_filter &= Q(order_date__gte=start_date, order_date__lte=end_date)
            vendor_orders_filter &= Q(order_date__gte=start_date, order_date__lte=end_date)
            total_amount_filter &= Q(order_date__gte=start_date, order_date__lte=end_date)

        orders = (
            om.Order.objects.filter(orders_filter)
            .order_by()
            .annotate(count=Func(F("id"), function="Count"))
            .values("count")
        )

        vendor_orders = (
            om.VendorOrder.objects.filter(vendor_orders_filter)
            .order_by()
            .annotate(count=Func(F("id"), function="Count"))
            .values("count")
        )

        total_amount = (
            om.Order.objects.filter(total_amount_filter)
            .order_by()
            .annotate(
                sum_total_amount=Func(Func(F("total_amount"), function="Sum"), Decimal(0), function="Coalesce"),
            )
            .values("sum_total_amount")
        )

        qs = queryset.annotate(
            order_count=Subquery(orders),
            vendor_order_count=Subquery(vendor_orders),
            ordo_order_volume=Subquery(total_amount),
        )
        return qs
