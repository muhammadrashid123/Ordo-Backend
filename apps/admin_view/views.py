import decimal
from datetime import datetime, timedelta
from itertools import chain
from operator import itemgetter

from django.db import models
from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import (
    BasisType,
    Company,
    Office,
    OfficeBudget,
    Subaccount,
    SubCompany,
    User,
)
from apps.common.pagination import StandardResultsSetPagination
from apps.orders import models as m
from apps.orders import serializers as s

from ..common.asyncdrf import AsyncMixin
from ..common.choices import ProductStatus
from ..common.month import Month
from ..common.utils import normalize_order_status, normalize_product_status
from ..orders.serializers import DateRangeQuerySerializer
from .serializers import (
    CompanySerializer,
    OfficeBudgetSerializer,
    OfficeSerializer,
    SubCompanySerializer,
)


class OrderSortedStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    PENDING_APPROVAL = "pendingapproval", "Pending Approval"


class VendorSortedOrderViewSet(AsyncMixin, ModelViewSet):
    queryset = m.VendorOrder.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = s.VendorOrderSerializer
    filter_backends = [OrderingFilter, DjangoFilterBackend]
    ordering_fields = ["order_date", "vendor__name", "total_items", "total_amount", "status"]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        office_id = self.request.query_params.get("office_pk", "")
        offices = self.request.query_params.get("offices", "")
        # sorting = self.request.query_params.get("sort", "null")
        offices_ids = [int(i) for i in offices.split(",")]

        if len(offices_ids) == 0:
            offices_ids.append(office_id)

        office_product_price = m.OfficeProduct.objects.filter(
            product_id=OuterRef("product_id"), office_id__in=offices_ids
        ).values("price")[:1]
        res = (
            self.queryset.filter(order__office_id__in=offices_ids)
            .select_related("order", "vendor", "order__office")
            .prefetch_related(
                Prefetch(
                    "order_products",
                    m.VendorOrderProduct.objects.select_related("product", "product__vendor", "product__category")
                    .prefetch_related("product__images")
                    .annotate(
                        office_product_price=Subquery(office_product_price),
                        updated_unit_price=Coalesce(F("office_product_price"), F("product__price")),
                    ),
                )
            )
            .order_by("-order_date", "-order_id")
        )
        return res

    def item_price_sort_key(ins):
        if ins.total_items > 0:
            return float(ins.total_amount) / float(ins.total_items)
        else:
            return float(ins.total_amount) / 1.0

    def sort_by_total_items(self, instance):
        return instance.total_items

    def list(self, request, *args, **kwargs):
        office_id = self.request.query_params["office_pk"]
        offices = self.request.query_params["offices"]
        offices_ids = [int(i) for i in offices.split(",")]
        if len(offices_ids) == 0:
            offices_ids.append(office_id)
        queryset = self.filter_queryset(self.get_queryset())
        approved_queryset = queryset.exclude(status=m.OrderStatus.PENDING_APPROVAL)
        approval_queryset = queryset.filter(status=m.OrderStatus.PENDING_APPROVAL)
        approval_order_ids = approval_queryset.values_list("order", flat=True).distinct()
        order_queryset = m.Order.objects.filter(pk__in=approval_order_ids)
        # order_queryset = m.Order.objects.filter(pk__in=approval_order_ids, office_id__in=offices_ids)
        sorting = self.request.query_params["sort"]
        if sorting == "null":
            full_queryset = sorted(
                chain(order_queryset, approved_queryset), key=self.sort_by_total_items, reverse=True
            )

        if sorting == "null":
            full_queryset = sorted(
                chain(order_queryset, approved_queryset), key=self.sort_by_total_items, reverse=True
            )
        elif sorting == "price":
            full_queryset = list(
                sorted(
                    chain(order_queryset, approved_queryset), key=lambda instance: instance.total_amount, reverse=True
                )
            )
        elif sorting == "item_price":
            full_queryset = sorted(
                chain(order_queryset, approved_queryset), key=self.item_price_sort_key, reverse=True
            )

        elif sorting == "category":
            full_queryset = sorted(
                chain(order_queryset, approved_queryset),
                key=lambda instance: itemgetter("products__category__name")(instance),
                reverse=True,
            )
        elif sorting == "vendor_amount":
            full_queryset = list(
                sorted(
                    chain(order_queryset, approved_queryset), key=lambda instance: instance.total_amount, reverse=True
                )
            )

        page = self.paginate_queryset(full_queryset)

        orders_to_serialize = []
        vendor_orders_to_serialize = []

        for item in page:
            if isinstance(item, m.VendorOrder):
                vendor_orders_to_serialize.append(item)
            else:
                orders_to_serialize.append(item)

        serialized_orders = s.OrderSerializer(orders_to_serialize, many=True)
        serialized_vendor_orders = s.VendorOrderSerializer(vendor_orders_to_serialize, many=True)

        result = sorted(
            (serialized_orders.data + serialized_vendor_orders.data),
            key=lambda instance: instance.get("total_items"),
            reverse=True,
        )
        return self.get_paginated_response(result)

    @action(detail=False, methods=["get"], url_path="stats")
    def get_orders_stats(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        total_items = 0
        total_amount = 0
        average_amount = 0

        requested_date = timezone.localdate()

        query_serializer = DateRangeQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        attrs = query_serializer.validated_data
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if start_date and end_date:
            start_month = Month.from_date(start_date)
            end_month = Month.from_date(end_date)
        else:
            start_month = end_month = Month.from_date(requested_date)

        if "start_date" not in request.query_params or "end_date" not in request.query_params:
            month = Month.from_date(requested_date)
            queryset = queryset.filter(order_date__gte=month.first_day(), order_date__lte=month.last_day())

        subaccounts = (
            Subaccount.objects.filter(
                budget__office_id=self.kwargs["office_pk"],
                budget__month__gte=start_month,
                budget__month__lte=end_month,
            )
            .annotate(
                total_budget=Case(
                    When(budget__basis=BasisType.PRODUCTION, then=F("budget__adjusted_production")),
                    When(budget__basis=BasisType.COLLECTION, then=F("budget__collection")),
                    output_field=models.DecimalField(),
                ),
                amount=F("total_budget") * F("percentage"),
            )
            .values("slug")
            .annotate(
                agg_total_amount=Sum("amount"),
                agg_total_spend=Sum("spend"),
            )
        )
        budget_stats = [
            {"slug": s["slug"], "total_amount": s["agg_total_amount"], "total_spend": s["agg_total_spend"]}
            for s in subaccounts
        ]

        approved_orders_queryset = queryset.exclude(status=m.OrderStatus.PENDING_APPROVAL)
        aggregation = approved_orders_queryset.aggregate(
            total_items=Sum("total_items"), total_amount=Sum("total_amount")
        )
        approved_orders_count = approved_orders_queryset.count()
        if approved_orders_count:
            total_items = aggregation["total_items"]
            total_amount = aggregation["total_amount"]
            average_amount = (total_amount / approved_orders_count).quantize(
                decimal.Decimal(".01"), rounding=decimal.ROUND_UP
            )

        pending_orders_count = queryset.filter(status=m.OrderStatus.PENDING_APPROVAL).count()
        vendors = (
            queryset.order_by("vendor_id")
            .values("vendor_id")
            .annotate(order_counts=Count("vendor_id"))
            .annotate(order_total_amount=Sum("total_amount"))
            .annotate(vendor_name=F("vendor__name"))
            .annotate(vendor_logo=F("vendor__logo"))
        )
        back_ordered_count = queryset.filter(
            Exists(
                m.VendorOrderProduct.objects.filter(vendor_order=OuterRef("pk"), status=m.ProductStatus.BACK_ORDERED)
            )
        ).count()

        ret = {
            "order": {
                "order_counts": approved_orders_count,
                "pending_order_counts": pending_orders_count,
                "total_items": total_items,
                "total_amount": total_amount,
                "average_amount": average_amount,
                "backordered_count": back_ordered_count,
            },
            "budget": budget_stats,
            "vendors": [
                {
                    "id": vendor["vendor_id"],
                    "name": vendor["vendor_name"],
                    "logo": f"{vendor['vendor_logo']}",
                    "order_counts": vendor["order_counts"],
                    "total_amount": vendor["order_total_amount"],
                }
                for vendor in vendors
            ],
        }
        return Response(ret)

    @action(detail=True, methods=["post"], url_path="vendororders-return")
    def update_vendororder_return(self, request, *args, **kwargs):
        print("Update")
        serializer = s.VendorOrderReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data["return_items"]:
            for item in serializer.validated_data["return_items"]:
                vendor_product = m.VendorOrderProduct.objects.get(id=item)
                vendor_product.status = ProductStatus.RETURNED
                vendor_product.save()

        return Response()

    def get_serializer_context(self):
        serializer_context = super().get_serializer_context()
        office_pk = self.kwargs["office_pk"]
        return {
            **serializer_context,
            "office_id": office_pk,
        }

    @action(detail=False, methods=["post"], url_path="manual-create-order")
    def manual_create_order(self, request, *args, **kwargs):
        data = request.data
        data["order_status"] = normalize_order_status(data.get("order_status"))

        serializer_class = s.ManualOrderCreateSerializer
        serializer = serializer_class(data=self.request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        vendor_order = serializer.save()

        return Response(data=s.VendorOrderSerializer(vendor_order).data, status=HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="manual-add-product")
    def add_product_to_order(self, request, *args, **kwargs):
        data = request.data
        data["status"] = normalize_product_status(data.get("status"))

        serializer_class = s.ManualCreateProductSerializer
        serializer = serializer_class(data=self.request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        product = serializer.save()

        return Response(data=s.VendorOrderProductSerializer(product).data, status=HTTP_201_CREATED)


class AdminDashboardModelViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "post"]

    def get_queryset(self):
        user = User.objects.get(id=self.request.user.id)
        return Company.objects.filter(creator=user)

    @action(detail=False, methods=["get"])
    def top_vendor_spent(self, request, *args, **kwargs):
        startdate_str = self.request.query_params.get("start_date", "")
        enddate_str = self.request.query_params.get("end_date", "")
        office_pks = [int(pk) for pk in self.request.query_params.get("offices", "").split(",") if pk.isdigit()]

        startdate = (
            datetime.strptime(startdate_str, "%Y-%m-%d").date()
            if startdate_str
            else timezone.now().date() - timedelta(days=30)
        )
        enddate = datetime.strptime(enddate_str, "%Y-%m-%d").date() if enddate_str else timezone.now().date()

        queryset = m.VendorOrder.objects.filter(
            Q(order_date__gte=startdate),
            Q(order_date__lte=enddate),
            Q(order__office__pk__in=office_pks) if office_pks else Q(),
        )

        vendor_totals = {}
        for vendor_order in queryset:
            vendor_name = vendor_order.vendor.id
            if vendor_name not in vendor_totals:
                vendor_totals[vendor_name] = 0
            vendor_totals[vendor_name] += vendor_order.total_amount

        sorted_vendors = sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:5]

        top_vendor_orders = m.Vendor.objects.filter(id__in=[vendor[0] for vendor in sorted_vendors])

        serialized_top_vendors = s.VendorSerializer(top_vendor_orders, many=True)
        return Response(serialized_top_vendors.data)

    @action(detail=False, methods=["get"])
    def vendors_orders(self, request, *args, **kwargs):
        startdate_str = self.request.query_params.get("start_date", "")
        enddate_str = self.request.query_params.get("end_date", "")
        office_pks = [int(pk) for pk in self.request.query_params.get("offices", "").split(",") if pk.isdigit()]
        sorting = self.request.query_params.get("sort", "")
        startdate = (
            datetime.strptime(startdate_str, "%Y-%m-%d").date()
            if startdate_str
            else timezone.now().date() - timedelta(days=30)
        )
        enddate = datetime.strptime(enddate_str, "%Y-%m-%d").date() if enddate_str else timezone.now().date()

        print(f"startdate: {startdate}, enddate: {enddate}, offices: {office_pks}, sorting: {sorting}")

        queryset = m.VendorOrder.objects.filter(
            Q(order_date__gte=startdate),
            Q(order_date__lte=enddate),
            Q(order__office__pk__in=office_pks) if office_pks else Q(),
        )

        if sorting == "null":
            queryset = queryset.order_by("-total_items")
        elif sorting == "total_price":
            queryset = sorted(queryset, key=lambda x: x.total_amount, reverse=True)
        elif sorting == "unit_price":
            queryset = queryset.annotate(product_amount=Coalesce(Sum("products__amount"), 0))
            queryset = queryset.order_by("-product_amount")
        else:
            queryset = queryset.order_by("-total_items")

        paginator = PageNumberPagination()
        paginator.page_size = int(self.request.query_params.get("per_page", 10))
        page = paginator.paginate_queryset(queryset, request)
        serialized_vendor_orders = s.VendorOrderSerializer(page, many=True)
        return paginator.get_paginated_response(serialized_vendor_orders.data)

    @action(detail=False, methods=["get"])
    def get_offices_tree(self, request, *args, **kwargs):
        if request.user is not None:
            # user_profile = User.objects.get(id=request.user.id)
            company_id = request.query_params["company_id"]
            companies = [Company.objects.get(id=company_id)]
            # companies = Company.objects.filter(creator=user_profile)

            data = []
            for company in companies:
                company_serializer = CompanySerializer(company).data
                company_data = {
                    "company": company_serializer,
                    "subcompanies": [],
                }
                subcompanies = SubCompany.objects.filter(company=company)
                for subcompany in subcompanies:
                    subcompany_serializer = SubCompanySerializer(subcompany).data
                    subcompany_data = {
                        "subcompany": subcompany_serializer,
                        "offices": [],
                    }
                    offices = Office.objects.filter(company=company)
                    for office in offices:
                        office_serializer = OfficeSerializer(office).data
                        subcompany_data["offices"].append({"office": office_serializer})
                    company_data["subcompanies"].append(subcompany_data)
                data.append(company_data)
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid user"}, status=status.HTTP_401_UNAUTHORIZED)

    @action(detail=False, methods=["get"])
    def dashboard_analytics(self, request, *args, **kwargs):
        try:
            if request.user is not None:
                companies = Company.objects.filter(creator=request.user)
                offices = Office.objects.filter(company__in=companies)
                offices_serializer = OfficeSerializer(offices, many=True)
                office_budgets = OfficeBudget.objects.filter(office__in=offices)
                over_budget_offices = [office for office in offices if self.is_office_over_budget(office)]
                office_budget_serializer = OfficeBudgetSerializer(office_budgets, many=True)
                office_budgets_data = office_budget_serializer.data
                over_budget_offices_serializer = OfficeSerializer(over_budget_offices, many=True)

                response_data = {
                    "message": "Success",
                    "offices": offices_serializer.data,
                    "office_budgets": office_budgets_data,
                    "over_budget_offices": over_budget_offices_serializer.data,
                }

                return Response(response_data)

        except Exception as e:
            return Response({"message": str(e)}, status=500)

    def is_office_over_budget(self, office):
        return office.budget.total_budget > office.budget.adjusted_production
