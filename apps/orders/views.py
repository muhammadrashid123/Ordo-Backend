import asyncio
import datetime
import decimal
import logging
import operator
import os
import tempfile
import uuid
import zipfile
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from functools import reduce
from itertools import chain
from typing import Union

from asgiref.sync import sync_to_async
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import (
    Case,
    Count,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
)
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import (
    BasisType,
    Company,
    Office,
    OfficeVendor,
    ShippingMethod,
    Subaccount,
)
from apps.accounts.services.offices import OfficeService

# from apps.accounts.tasks import fetch_order_history
from apps.common import messages as msgs
from apps.common.asyncdrf import AsyncCreateModelMixin, AsyncMixin
from apps.common.choices import OrderStatus, ProductStatus
from apps.common.enums import SupportedVendor
from apps.common.month import Month
from apps.common.pagination import (
    SearchProductPagination,
    SearchProductV2Pagination,
    StandardResultsSetPagination,
)
from apps.common.utils import (
    get_date_range,
    get_week_count,
    group_products_from_search_result,
    normalize_order_status,
    normalize_product_status,
)
from apps.orders.helpers import (
    OfficeProductHelper,
    OfficeVendorHelper,
    ProcedureHelper,
    ProductHelper,
)
from apps.orders.services.order import OrderService
from apps.scrapers.ebay_search import EbaySearch
from apps.scrapers.errors import VendorNotSupported
from apps.scrapers.scraper_factory import ScraperFactory
from apps.types.orders import CartProduct
from apps.types.scraper import SmartID
from config.utils import get_client_session
from services.api_client import (
    DentalCityAPIClient,
    DentalCityCXMLParser,
    DentalCityOrderDetail,
    DentalCityShippingInfo,
)
from services.opendental import OpenDentalClient

from ..accounts.helper import BudgetwiseSpend, OfficeBudgetHelper
from ..accounts.views.crazy_dental_integration import (
    crazy_dental_customer_service_email,
    crazy_dental_ordo_vendor_id,
    get_vendor_customer_id,
)
from ..api_clients.crazy_dental import CrazyDentalNewClient
from ..audit.models import SearchHistory
from . import filters as f
from . import models as m
from . import permissions as p
from . import serializers as s
from .actions.product_management import attach_to_parent, unlink_from_parent
from .models import OfficeProduct, OfficeProductCategory, Product, VendorOrderProduct
from .parsers import XMLParser
from .serializers import DateRangeQuerySerializer
from .tasks import notify_order_creation, perform_real_order, search_and_group_products

logger = logging.getLogger(__name__)


class OrderViewSet(AsyncMixin, ModelViewSet):
    queryset = m.Order.objects.all()
    permission_classes = [p.OfficeSubscriptionPermission]
    serializer_class = s.OrderSerializer
    pagination_class = StandardResultsSetPagination
    filterset_class = f.OrderFilter

    @sync_to_async
    def _get_vendor_orders(self):
        order = self.get_object()
        vendor_orders = order.vendor_orders.all()
        vendors = [vendor_order.vendor for vendor_order in vendor_orders]
        office_vendors = OfficeVendor.objects.filter(office_id=self.kwargs["office_pk"], vendor__in=vendors)
        office_vendors = {office_vendor.vendor_id: office_vendor for office_vendor in office_vendors}
        ret = []
        for vendor_order in vendor_orders:
            # TODO: filter by order status as well
            if vendor_order.vendor.slug != "ultradent" and not vendor_order.invoice_link:
                continue
            ret.append(
                {
                    "vendor_order_id": vendor_order.vendor_order_id,
                    "invoice_link": vendor_order.invoice_link,
                    "vendor": vendor_order.vendor,
                    "username": office_vendors[vendor_order.vendor.id].username,
                    "password": office_vendors[vendor_order.vendor.id].password,
                }
            )

        return ret

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        # queryset = (
        #     queryset.values("id", "status")
        #     .annotate(order_date=m.IsoDate("created_at"))
        #     .annotate(total_amount=Sum("vendor_orders__total_amount"))
        #     .annotate(total_items=Sum("vendor_orders__total_items"))
        # )
        page = self.paginate_queryset(queryset)

        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def get_queryset(self):
        office_pk = self.kwargs["office_pk"]
        office_product_inventory = OfficeProduct.objects.filter(
            office_id=office_pk, product_id=OuterRef("product_id")
        ).values("is_inventory")
        product_prefetch_queryset = VendorOrderProduct.objects.annotate(
            item_inventory=Subquery(office_product_inventory[:1])
        )
        queryset = (
            super()
            .get_queryset()
            .filter(office__id=office_pk)
            .prefetch_related(
                Prefetch("vendor_orders__order_products", product_prefetch_queryset),
            )
        )
        return queryset

    @action(detail=True, methods=["get"], url_path="invoice-download")
    async def download_invoice(self, request, *args, **kwargs):
        vendor_orders = await self._get_vendor_orders()
        session = await get_client_session()
        tasks = []
        if len(vendor_orders) == 0:
            return Response({"message": msgs.NO_INVOICE})

        for vendor_order in vendor_orders:
            scraper = ScraperFactory.create_scraper(
                vendor=vendor_order["vendor"],
                session=session,
                username=vendor_order["username"],
                password=vendor_order["password"],
            )
            tasks.append(
                scraper.download_invoice(
                    invoice_link=vendor_order["invoice_link"], order_id=vendor_order["vendor_order_id"]
                )
            )
        ret = await asyncio.gather(*tasks, return_exceptions=True)

        temp = tempfile.NamedTemporaryFile()

        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as zf:
            for vendor_order, content in zip(vendor_orders, ret):
                zf.writestr(f"{vendor_order['vendor'].name}.zip", content)

        filesize = os.path.getsize(temp.name)
        data = open(temp.name, "rb").read()
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=invoice.zip"
        response["Content-Length"] = filesize
        temp.seek(0)
        return response

    def update(self, request, *args, **kwargs):
        if "nickname" in request.data:
            nickname = request.data.pop("nickname")
            instance = self.get_object()
            vendor_orders = instance.vendor_orders.all()
            extra_fields = []
            for vendor_order in vendor_orders:
                vendor_order.nickname = nickname
                if "vendor_order_id" in request.data:
                    order = vendor_order.order
                    order.order_date = request.data["order_date"]
                    order.status = request.data["order_status"]
                    order.total_items = request.data["total_items"]
                    order.total_amount = request.data["total_amount"]
                    order.save()

                    vendor_order.vendor_order_id = request.data.pop("vendor_order_id")
                    vendor_order.total_amount = request.data.pop("total_amount")
                    vendor_order.total_items = request.data.pop("total_items")
                    vendor_order.order_date = request.data.pop("order_date")
                    vendor_order.status = normalize_order_status(request.data.pop("order_status"))
                    extra_fields = ["vendor_order_id", "total_amount", "total_items", "order_date", "status"]

            m.VendorOrder.objects.bulk_update(vendor_orders, fields=["nickname"] + extra_fields)
        return super().update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[p.OrderApprovalPermission])
    async def approve(self, request, *args, **kwargs):
        serializer = s.OrderApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = await sync_to_async(self.get_object)()
        if order.status != m.OrderStatus.PENDING_APPROVAL:
            return Response({"message": "This order status is not pending approval"})

        vendor_orders = order.vendor_orders.all()
        async for vendor_order in vendor_orders:
            await OrderService.approve_vendor_order(
                approved_by=request.user,
                vendor_order=vendor_order,
                validated_data=serializer.validated_data,
                stage=request.META["HTTP_HOST"],
            )
            await sync_to_async(OrderService.update_vendor_order_spent)(vendor_order, serializer.validated_data)
        order.status = m.OrderStatus.OPEN
        order.order_date = timezone.localtime()
        await sync_to_async(order.save)()

        return Response({"message": "Successfully approved!"})

    @action(detail=True, methods=["post"], url_path="approvalorder-add")
    def add_item_to_vendororder(self, request, *args, **kwargs):
        instance = self.get_object()
        office = m.Office.objects.get(id=kwargs["office_pk"])
        serializer = s.OrderAddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_date = timezone.localtime().date()
        product = serializer.validated_data["product"]
        unit_price = OfficeProductHelper.get_product_price(office=office, product=product)
        quantity = serializer.validated_data["quantity"]
        total_amount = unit_price * quantity

        vendor_order = instance.vendor_orders.filter(
            vendor=product.vendor,
        ).first()
        vendor_order_exists = vendor_order

        if vendor_order:
            vendor_order.status = OrderStatus.PENDING_APPROVAL
            vendor_order.total_amount += total_amount
            vendor_order.save()
        else:
            random_order_id = f"{uuid.uuid4()}"
            vendor_order = m.VendorOrder.objects.create(
                order=instance,
                vendor=product.vendor,
                vendor_order_id=random_order_id,
                total_amount=total_amount,
                total_items=1,
                order_date=order_date,
                status=OrderStatus.PENDING_APPROVAL,
            )

        vendor_order_product = vendor_order.order_products.filter(product_id=product.id).first()

        if vendor_order_product:
            vendor_order_product.status = ProductStatus.PENDING_APPROVAL
            vendor_order_product.quantity += quantity
            vendor_order_product.save()
        else:
            vendor_order_product = m.VendorOrderProduct.objects.create(
                vendor_order=vendor_order,
                product_id=product.id,
                quantity=quantity,
                unit_price=unit_price,
                status=ProductStatus.PENDING_APPROVAL,
            )
            if vendor_order_exists:
                vendor_order.total_items += 1
            instance.total_items += 1

        instance.total_amount += total_amount
        instance.save()
        vendor_order.save()

        return Response(vendor_order_product.id)

    @action(detail=True, methods=["post"], url_path="update-product-status")
    def update_product_status(self, request, *args, **kwargs):
        product_id = request.query_params.get("product_id")
        order_id = kwargs["pk"]
        body = request.data

        try:
            vendor_order_product = VendorOrderProduct.objects.get(vendor_order_id=order_id, id=product_id)

            # Update status and rejected_reason here
            vendor_order_product.status = body["status"]
            vendor_order_product.rejected_reason = body["reason"]
            vendor_order_product.save()
        except Exception as e:
            print(e)
            return Response({"message": "Product not found!", "status": 404})

        return Response(data=s.VendorOrderProductSerializer(vendor_order_product).data, status=status.HTTP_200_OK)


class VendorOrderViewSet(AsyncMixin, ModelViewSet):
    queryset = m.VendorOrder.objects.all()
    permission_classes = [p.OfficeSubscriptionPermission]
    serializer_class = s.VendorOrderSerializer
    filterset_class = f.VendorOrderFilter
    filter_backends = [OrderingFilter, DjangoFilterBackend]
    ordering_fields = ["order_date", "vendor__name", "total_items", "total_amount", "status"]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        office_id = self.kwargs["office_pk"]
        office_product_price = m.OfficeProduct.objects.filter(
            product_id=OuterRef("product_id"), office_id=office_id
        ).values("price")[:1]
        return (
            self.queryset.filter(order__office_id=office_id)
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

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        approved_queryset = queryset.exclude(status=m.OrderStatus.PENDING_APPROVAL)
        approval_queryset = queryset.filter(status=m.OrderStatus.PENDING_APPROVAL)
        approval_order_ids = approval_queryset.values_list("order", flat=True).distinct()
        order_queryset = m.Order.objects.filter(pk__in=approval_order_ids)
        full_queryset = list(
            sorted(chain(order_queryset, approved_queryset), key=lambda instance: instance.order_date, reverse=True)
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
            key=lambda instance: instance.get("order_date"),
            reverse=True,
        )
        return self.get_paginated_response(result)

    @sync_to_async
    def get_office_vendor(self):
        vendor_order = self.get_object()
        # office_vendor = OfficeVendor.objects.get(office_id=self.kwargs["office_pk"], vendor=vendor_order.vendor)
        try:
            office_vendor = OfficeVendor.objects.get(office_id=self.kwargs["office_pk"], vendor=vendor_order.vendor)
        except OfficeVendor.DoesNotExist:
            office_vendor = None

        if office_vendor is None:
            return {"is_invoice_available": None}
        else:
            return {
                "vendor_order_id": vendor_order.vendor_order_id,
                "order_date": vendor_order.order_date,
                "invoice_link": vendor_order.invoice_link,
                "vendor": vendor_order.vendor,
                "is_invoice_available": vendor_order.is_invoice_available,
                "username": office_vendor.username,
                "password": office_vendor.password,
            }

    @action(detail=False, methods=["get"], permission_classes=[p.OfficeSubscriptionPermission])
    async def pending_stats(self, request, *args, **kwargs):
        office_id = self.kwargs["office_pk"]
        count = await m.VendorOrder.objects.filter(
            order__office_id=office_id, status=OrderStatus.PENDING_APPROVAL
        ).acount()
        return Response({"count": count})

    @action(detail=True, methods=["post"], url_path="approve", permission_classes=[p.OrderApprovalPermission])
    async def approve_order(self, request, *args, **kwargs):
        # This API is not used. Considering removal later.
        serializer = s.ApproveRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor_order = await sync_to_async(self.get_object)()

        if vendor_order.status != m.OrderStatus.PENDING_APPROVAL:
            return Response({"message": "this order status is not waiting approval"})

        if serializer.validated_data["is_approved"]:
            await OrderService.approve_vendor_order(
                approved_by=request.user,
                vendor_order=vendor_order,
                validated_data=serializer.validated_data,
                stage=request.META["HTTP_HOST"],
            )

            await sync_to_async(OrderService.update_vendor_order_spent)(vendor_order, serializer.validated_data)

        else:
            await sync_to_async(OrderService.reject_vendor_order)(
                approved_by=request.user, vendor_order=vendor_order, validated_data=serializer.validated_data
            )

        return Response({"message": "okay"})

    @action(detail=True, methods=["get"], url_path="invoice-download")
    async def download_invoice(self, request, *args, **kwargs):
        vendor_order = await self.get_office_vendor()
        if vendor_order["is_invoice_available"] is None:
            # return Response({"message": msgs.NO_INVOICE}, status=status.HTTP_401_UNAUTHORIZED)
            return JsonResponse({"message": "vendor not linked"}, status=401)

        session = await get_client_session()

        scraper = ScraperFactory.create_scraper(
            vendor=vendor_order["vendor"],
            session=session,
            username=vendor_order["username"],
            password=vendor_order["password"],
        )
        content = await scraper.download_invoice(
            invoice_link=vendor_order["invoice_link"],
            order_id=vendor_order["vendor_order_id"],
            vendor=vendor_order["vendor"].name,
        )

        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="wb")
        temp.write(content)
        filesize = os.path.getsize(temp.name)
        data = open(temp.name, "rb").read()
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = "attachment; filename=invoice.pdf"
        response["Content-Length"] = filesize
        temp.seek(0)
        return response

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
            average_amount = (total_amount / approved_orders_count).quantize(Decimal(".01"), rounding=decimal.ROUND_UP)

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


class VendorOrderProductViewSet(ModelViewSet):
    permission_classes = [p.ProductStatusUpdatePermission, p.OfficeSubscriptionPermission]
    queryset = m.VendorOrderProduct.objects.exclude(
        Q(status__icontains="Cancelled") | Q(status__icontains="Rejected")
    ).order_by("-vendor_order__order_date")

    serializer_class = s.VendorOrderProductSerializer
    filterset_class = f.VendorOrderProductFilter
    pagination_class = StandardResultsSetPagination

    def update(self, request, *args, **kwargs):
        kwargs.setdefault("partial", True)
        return super().update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=HTTP_204_NO_CONTENT)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        vendor_order = instance.vendor_order
        order = vendor_order.order
        quantity = instance.quantity
        unit_price = instance.unit_price
        total_amount = unit_price * quantity

        order.total_amount -= total_amount
        order.total_items -= 1
        if not order.total_items:
            order.delete()
            return Response({"message": "All products are removed"})
        else:
            order.save()

        vendor_order.total_amount -= total_amount
        vendor_order.total_items -= 1
        if not vendor_order.total_items:
            vendor_order.delete()
            return Response({"message": "Vendor Order was removed."})
        else:
            vendor_order.save()
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        return self.queryset.filter(vendor_order__order__office__id=self.kwargs["office_pk"])


def get_spending(by, orders, company):
    if by == "month":
        last_year_today = (timezone.localtime() - relativedelta(months=11)).date()
        last_year_today.replace(day=1)
        return (
            orders.filter(order_date__gte=last_year_today)
            .annotate(month=m.YearMonth("order_date"))
            .values("month")
            .order_by("month")
            .annotate(total_amount=Sum("total_amount"))
        )
    else:
        qs = (
            orders.values("vendor_id")
            .order_by("vendor_id")
            .annotate(total_amount=Sum("total_amount"), vendor_name=F("vendor__name"))
        )

        vendor_ids = [q["vendor_id"] for q in qs]
        vendors = OfficeVendor.objects.select_related("vendor").filter(
            office__company=company, vendor_id__in=vendor_ids
        )
        vendors = {v.vendor.id: v for v in vendors}

        return [
            {
                "vendor": {
                    "id": q["vendor_id"],
                    "name": q["vendor_name"],
                    "logo": f"{vendors[q['vendor_id']].vendor.logo}",
                    "office_associated_id": vendors[q["vendor_id"]].id,
                },
                "total_amount": q["total_amount"],
            }
            for q in qs
        ]


def get_inventory_products(office: Union[SmartID, m.Office]):
    if not isinstance(office, m.Office):
        office = get_object_or_404(m.Office, pk=office)

    office_inventory_products = m.OfficeProduct.objects.filter(office=office, is_inventory=True).values(
        "product__product_id", "product__vendor"
    )
    return set(
        [
            f"{office_inventory_product['product__product_id']}-{office_inventory_product['product__vendor']}"
            for office_inventory_product in office_inventory_products
        ]
    )


class CompanySpendAPIView(APIView):
    # TODO: Update proper permission
    permission_classes = [p.CompanyOfficeReadPermission]

    def get(self, request, company_pk):
        company = get_object_or_404(Company, id=company_pk)
        self.check_object_permissions(request, company)
        queryset = m.VendorOrder.objects.select_related("vendor").filter(order__office__company=company)
        data = get_spending(request.query_params.get("by", "vendor"), queryset, company)
        serializer = s.TotalSpendSerializer(data, many=True)
        return Response(serializer.data)


class OfficeSpendAPIView(APIView):
    # TODO: update proper permission
    permission_classes = [p.CompanyOfficeReadPermission]

    def get(self, request, office_pk):
        office = get_object_or_404(Office, id=office_pk)
        self.check_object_permissions(request, office)
        queryset = m.VendorOrder.objects.select_related("vendor").filter(order__office=office)
        data = get_spending(request.query_params.get("by", "vendor"), queryset, office.company)
        serializer = s.TotalSpendSerializer(data, many=True)
        return Response(serializer.data)


class OfficeProductCategoryViewSet(ModelViewSet):
    queryset = m.OfficeProductCategory.objects.all()
    serializer_class = s.OfficeProductCategorySerializer

    def create(self, request, *args, **kwargs):
        request.data.setdefault("office", self.kwargs["office_pk"])
        request.data.setdefault("predefined", False)
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.predefined:
            return Response({"message": msgs.PRODUCT_CATEGORY_NOT_PERMITTED}, status=HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            office_products = instance.products.all()

            # move products to original uncategorized category
            other_product_category = m.OfficeProductCategory.objects.filter(
                slug="other", office=instance.office
            ).first()
            for office_product in office_products:
                office_product.office_product_category = other_product_category

            # this uncommented logic move products to original product category
            # office_product_categories = {}
            # for office_product in office_products:
            #     original_product_category_slug = office_product.product.category.slug
            #     original_product_category = office_product_categories.get(original_product_category_slug)
            #
            #     if original_product_category is None:
            #         original_product_category = m.OfficeProductCategory.objects.filter(
            #             slug=original_product_category_slug, office=instance.office
            #         ).first()
            #         office_product_categories[original_product_category_slug] = original_product_category
            #
            #     office_product.office_product_category = original_product_category

            if office_products:
                m.OfficeProduct.objects.bulk_update(office_products, fields=["office_product_category"])
            instance.delete()

        return Response(status=HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="inventory")
    def get_inventory_view(self, request, *args, **kwargs):
        vendors = {vendor.id: vendor.to_dict() for vendor in m.Vendor.objects.all()}
        queryset = m.OfficeProductCategory.objects.all().with_stats(kwargs["office_pk"])
        serializer = self.get_serializer(queryset, many=True, context={"with_inventory_count": True})
        ret = serializer.data
        for office_product_category in ret:
            vendor_ids = office_product_category.pop("vendor_ids")
            office_product_category["vendors"] = [vendors[vendor_id] for vendor_id in vendor_ids if vendor_id]
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="inventory-vendor")
    def get_inventory_vendor_view(self, request, *args, **kwargs):
        # 1. Fetch categories using a dictionary comprehension for better readability.
        categories = {category.id: category.to_dict() for category in m.OfficeProductCategory.objects.all()}

        # 2. Fetch the office_id directly from kwargs.
        office_id = kwargs["office_pk"]

        # 3. Use values_list to fetch vendor_ids directly as a list.
        vendor_ids = OfficeVendor.objects.filter(office_id=office_id, login_success=True).values_list(
            "vendor", flat=True
        )

        # 4. Use select_related/prefetch_related if needed to optimize database queries.
        queryset = m.Vendor.objects.all().with_stats(office_id, vendor_ids)

        # 5. Serialize the data directly and apply your category logic.
        serializer = s.OfficeProductVendorSerializer(
            queryset, many=True, context={"with_inventory_count": True, "office_id": office_id}
        )

        ret = serializer.data
        for office_product_vendor in ret:
            category_ids = office_product_vendor.pop("category_ids")
            office_product_vendor["categories"] = [
                categories[category_id] for category_id in category_ids if category_id is not None
            ]

        # 6. Return a Response object directly and use status codes as needed.
        return Response(ret, status=status.HTTP_200_OK)


class ProductViewSet(AsyncMixin, ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = s.ProductSerializer
    filterset_class = f.ProductFilter
    queryset = m.Product.objects.all()

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAdminUser],
        serializer_class=s.ProductManagementSerializer,
    )
    def manage(self, request):
        serializer = s.ProductManagementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.validated_data["product"]
        new_parent = serializer.validated_data.get("new_parent")
        unlink_from_parent(product, request.user)
        if new_parent:
            attach_to_parent(product, new_parent, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="suggestion")
    def product_suggestion(self, request, *args, **kwargs):
        # get suggestions from inventory list first
        office_id = request.query_params.get("office")
        q = request.query_params.get("q", "")
        office_products = (
            m.OfficeProduct.objects.select_related("product__images")
            .filter(
                Q(office_id=office_id)
                & Q(product__parent__isnull=True)
                & (
                    Q(product__product_id=q)
                    | Q(product__name__icontains=q)
                    | Q(product__tags__keyword__iexact=q)
                    | Q(product__child__product_id=q)
                    | Q(product__child__name__icontains=q)
                    | Q(product__child__tags__keyword__iexact=q)
                )
            )
            .distinct()
            .order_by("-is_inventory")
            .values("id", "is_inventory", "product__product_id", "product__name", "product__images__image")[:5]
        )
        suggestion_products = [
            {
                "id": product["id"],
                "product_id": product["product__product_id"],
                "name": product["product__name"],
                "image": product["product__images__image"],
                "is_inventory": product["is_inventory"],
            }
            for product in office_products
        ]
        # product_ids = [product["product_id"] for product in suggestion_products]
        # if len(office_products) < 5:
        #     # get suggestions from from product list
        #     products = (
        #         m.Product.objects.select_related("images")
        #         .filter(
        #             Q(parent__isnull=True)
        #             & (
        #                 Q(product_id=q)
        #                 | Q(name__icontains=q)
        #                 | Q(tags__keyword__iexact=q)
        #                 | Q(child__product_id=q)
        #                 | Q(child__name__icontains=q)
        #                 | Q(child__tags__keyword__iexact=q)
        #             )
        #         )
        #         .exclude(product_id__in=product_ids)
        #         .distinct()
        #         .values("product_id", "name", "images__image")[: 5 - len(office_products)]
        #     )
        #     suggestion_products.extend(
        #         [
        #             {
        #                 "id": "",
        #                 "product_id": product["product_id"],
        #                 "name": product["name"],
        #                 "image": product["images__image"],
        #                 "is_inventory": False,
        #             }
        #             for product in products
        #         ]
        #     )

        serializer = s.ProductSuggestionSerializer(suggestion_products, many=True)
        return Response(serializer.data)


class ProductDataViewSet(ModelViewSet):
    serializer_class = s.ProductSerializer
    queryset = m.Product.objects.all()

    def get_queryset(self):
        query = self.request.GET.get("search", "")
        return m.Product.objects.search(query)


def get_office_vendor(office_pk, vendor_pk):
    try:
        return OfficeVendor.objects.get(office_id=office_pk, vendor_id=vendor_pk)
    except OfficeVendor.DoesNotExist:
        return


def get_cart(office_pk):
    cart_products = (
        m.Cart.objects.filter(office_id=office_pk, save_for_later=False, instant_checkout=True)
        .order_by("-updated_at")
        .select_related("product")
        .select_related("product__vendor")
        .select_related("promotion")
    )
    if not cart_products:
        return cart_products, []
    else:
        vendors = set(cart_product.product.vendor for cart_product in cart_products)
        q = reduce(operator.or_, [Q(office_id=office_pk) & Q(vendor=vendor) for vendor in vendors])
        office_vendors = OfficeVendor.objects.filter(q).select_related("vendor", "office")
        return cart_products, list(office_vendors)


def get_cart_status_and_order_status(office, user):
    if isinstance(office, str) or isinstance(office, int):
        office = m.Office.objects.get(id=office)

    if not hasattr(office, "checkout_status"):
        m.OfficeCheckoutStatus.objects.create(office=office, user=user)

    can_use_cart = (
        office.checkout_status.user == user
        or office.checkout_status.checkout_status == m.OfficeCheckoutStatus.CHECKOUT_STATUS.COMPLETE
    )
    can_create_order = (
        office.checkout_status.user == user
        or office.checkout_status.order_status == m.OfficeCheckoutStatus.ORDER_STATUS.COMPLETE
    )
    return can_use_cart, can_create_order


def update_cart_or_checkout_status(office, user, checkout_status=None, order_status=None):
    office.checkout_status.user = user
    if checkout_status:
        office.checkout_status.checkout_status = checkout_status
    if order_status:
        office.checkout_status.order_status = order_status
    office.checkout_status.save()


def save_serailizer(serializer):
    serializer.save()
    return serializer.data


def get_serializer_data(serializer_class, data, many=True):
    serializer = serializer_class(data, many=True)
    return serializer.data


class CartViewSet(AsyncMixin, AsyncCreateModelMixin, ModelViewSet):
    permission_classes = [p.OfficeSubscriptionPermission]
    model = m.Cart
    serializer_class = s.CartSerializer
    queryset = m.Cart.objects.all()

    def get_queryset(self):
        # orders_product table
        office_pk = self.kwargs["office_pk"]
        office_product_price = OfficeProduct.objects.filter(office_id=office_pk, product_id=OuterRef("pk")).values(
            "price"
        )
        office_product_is_inventory = OfficeProduct.objects.filter(
            office_id=OuterRef("office_id"), product_id=OuterRef("product_id")
        ).values("is_inventory")
        child_prefetch_queryset = (
            Product.objects.annotate(office_product_price=Subquery(office_product_price[:1]))
            .annotate(product_price=Coalesce(F("office_product_price"), F("price")))
            .prefetch_related("images", "category", "vendor")
        )
        queryset = (
            self.queryset.filter(office_id=office_pk)
            .annotate(item_inventory=Subquery(office_product_is_inventory[:1]))
            .with_updated_unit_price()
            .select_related(
                "product",
                "product__vendor",
                "product__category",
            )
            .prefetch_related(
                "product__images",
                Prefetch("product__parent__children", child_prefetch_queryset),
            )
        )
        # order_by = self.request.query_params.get("by", "vendor")
        # if order_by == "time":
        #     return queryset.order_by("-updated_at")
        # else:
        return queryset.order_by("-created_at", "product__vendor", "-save_for_later")

    def get_serializer_class(self):
        if self.request.method in ["GET"]:
            return s.CartSerializer
        return s.CartCreateSerializer

    # async def update_vendor_cart(self, product_id, vendor, serializer=None):
    #     office_vendor = await sync_to_async(get_office_vendor)(
    #         office_pk=self.kwargs["office_pk"], vendor_pk=vendor.id
    #     )
    #     if office_vendor is None:
    #         raise VendorNotConnected()
    #     session = apps.get_app_config("accounts").session
    #     scraper = ScraperFactory.create_scraper(
    #         vendor=vendor,
    #         session=session,
    #         username=office_vendor.username,
    #         password=office_vendor.password,
    #     )
    #     try:
    #         await scraper.remove_product_from_cart(product_id=product_id, use_bulk=False, perform_login=True)
    #     except Exception as e:
    #         raise VendorSiteError(f"{e}")

    #     if not serializer:
    #         return True

    #     updated_save_for_later = serializer.instance and "save_for_later" in serializer.validated_data

    #     if updated_save_for_later and serializer.validated_data["save_for_later"]:
    #         return True

    #     if updated_save_for_later and not serializer.validated_data["save_for_later"]:
    #         quantity = serializer.instance.quantity
    #     else:
    #         quantity = serializer.validated_data["quantity"]

    #     try:
    #         vendor_cart_product = await scraper.add_product_to_cart(
    #             CartProduct(product_id=product_id, product_unit=serializer, quantity=quantity),
    #             perform_login=True,
    #         )
    #         serializer.validated_data["unit_price"] = vendor_cart_product["unit_price"]
    #     except Exception as e:
    #         raise VendorSiteError(f"{e}")

    async def create(self, request, *args, **kwargs):
        data = request.data
        office_pk = self.kwargs["office_pk"]
        data["office"] = office_pk
        can_use_cart, _ = await sync_to_async(get_cart_status_and_order_status)(office=office_pk, user=request.user)
        if not can_use_cart:
            return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)

        serializer = await sync_to_async(self.get_serializer)(data=data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        serializer_data = await sync_to_async(save_serailizer)(serializer)
        return Response(serializer_data, status=HTTP_201_CREATED)

    #
    # @sync_to_async
    # def get_object_with_related(self):
    #     instance = self.get_object()
    #     return instance, instance.product.product_id, instance.product.vendor
    #

    @action(detail=True, url_path="change-product", methods=["post"])
    def change_product(self, request, *args, **kwargs):
        instance = self.get_object()
        product_id = request.data.get("product_id")
        unit_price = request.data.get("unit_price")
        product = get_object_or_404(m.Product, product_id=product_id)
        if m.Cart.objects.filter(office_id=self.kwargs["office_pk"], product=product).exists():
            return Response({"message": "This product is already in your cart"}, status=HTTP_400_BAD_REQUEST)
        instance.unit_price = unit_price
        instance.product = product
        instance.save()
        return Response(self.serializer_class(instance).data)

    @action(detail=False, methods=["post"], url_path="set_promo")
    def set_cart_promotion(self, request, *args, **kwargs):
        vendor_id = request.data.get("vendor_id")
        promo_code = request.data.get("promo_code")
        if not m.Promotion.objects.filter(code=promo_code).exists():
            return Response({"message": "Invalid promo code. Please check promo code."}, status=HTTP_400_BAD_REQUEST)
        promotion = m.Promotion.objects.get(code=promo_code)
        carts = {cart for cart in self.get_queryset() if cart.product.vendor_id == vendor_id}
        for cart in carts:
            cart.promotion_id = promotion.id
        m.Cart.objects.bulk_update(carts, fields=["promotion_id"])
        serializer = s.CartSerializer(self.filter_queryset(self.get_queryset()), many=True)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)

    # async def update(self, request, *args, **kwargs):
    #     instance, product_id, vendor = await self.get_object_with_related()
    #     can_use_cart, _ = await sync_to_async(get_cart_status_and_order_status)(
    #         office=self.kwargs["office_pk"], user=request.user
    #     )
    #     if not can_use_cart:
    #         return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)
    #
    #     serializer = self.get_serializer(instance, request.data, partial=True)
    #     await sync_to_async(serializer.is_valid)(raise_exception=True)
    #     try:
    #         await self.update_vendor_cart(product_id, vendor, serializer)
    #     except VendorSiteError:
    #         return Response({"message": msgs.VENDOR_SITE_ERROR}, status=HTTP_500_INTERNAL_SERVER_ERROR)
    #     except VendorNotConnected:
    #         return Response({"message": "Vendor not connected"}, status=HTTP_400_BAD_REQUEST)
    #     serializer_data = await sync_to_async(save_serailizer)(serializer)
    #     return Response(serializer_data)
    #
    # async def destroy(self, request, *args, **kwargs):
    #     instance, product_id, vendor = await self.get_object_with_related()
    #     can_use_cart, _ = await sync_to_async(get_cart_status_and_order_status)(
    #         office=self.kwargs["office_pk"], user=request.user
    #     )
    #     if not can_use_cart:
    #         return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)
    #
    #     try:
    #         await self.update_vendor_cart(product_id, vendor)
    #     except VendorSiteError:
    #         return Response({"message": msgs.VENDOR_SITE_ERROR}, status=HTTP_500_INTERNAL_SERVER_ERROR)
    #     except VendorNotConnected:
    #         return Response({"message": "Vendor not connected"}, status=HTTP_400_BAD_REQUEST)
    #     await sync_to_async(self.perform_destroy)(instance)
    #     return Response(status=HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="clear")
    def clear_cart(self, request, *args, **kwargs):
        serializer = s.ClearCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart_products = self.get_queryset()
        if serializer.validated_data["remove"] == "save_for_later":
            cart_products.filter(save_for_later=True).delete()
        elif serializer.validated_data["remove"] == "cart":
            cart_products.filter(save_for_later=False).delete()
        return Response({"message": msgs.SUCCESS})

    def get_or_create_office_product_category(self, office, category_slug, category_name):
        existing_category = OfficeProductCategory.objects.filter(slug=category_slug, office_id=office).first()
        if existing_category:
            return existing_category
        else:
            new_category = OfficeProductCategory.objects.create(
                name=category_name, slug=category_slug, predefined=True, office_id=office
            )
            return new_category

    @sync_to_async
    def _create_order(
        self, office_vendors, vendor_order_results, cart_products, approval_needed, shipping_options, fake_order
    ):
        order_date = timezone.localtime().date()
        office = office_vendors[0].office
        vendor_order_ids = []
        office_vendor_ids = []

        with transaction.atomic():
            order = m.Order.objects.create(
                office_id=self.kwargs["office_pk"],
                created_by=self.request.user,
                order_date=order_date,
                status=m.OrderStatus.PENDING_APPROVAL if approval_needed else m.OrderStatus.OPEN,
            )
            total_amount = 0.0
            total_items = 0.0
            budgetwise_spend = BudgetwiseSpend()

            for office_vendor, vendor_order_result in zip(office_vendors, vendor_order_results):
                if not isinstance(vendor_order_result, dict):
                    continue
                office_vendor_ids.append(office_vendor.id)
                vendor = office_vendor.vendor
                shipping_option = shipping_options.get(vendor.slug)
                vendor_order_id = vendor_order_result.get("order_id", "")
                if vendor_order_id is None:
                    vendor_order_id = "invalid"
                vendor_total_amount = vendor_order_result.get("total_amount", 0.0)
                total_amount += float(vendor_total_amount)
                vendor_order_products = cart_products.filter(product__vendor=vendor)
                total_items += (vendor_total_items := vendor_order_products.count())
                vendor_order = m.VendorOrder.objects.create(
                    order=order,
                    vendor=office_vendor.vendor,
                    vendor_order_id=vendor_order_id,
                    total_amount=vendor_total_amount,
                    total_items=vendor_total_items,
                    currency="USD",
                    order_date=order_date,
                    status=m.OrderStatus.PENDING_APPROVAL if approval_needed else m.OrderStatus.OPEN,
                    shipping_option=shipping_option,
                )
                default_budget_spend_type = OfficeBudgetHelper.get_default_budget_type_by_vendor(
                    office_vendor.vendor.slug
                )
                vendor_order_ids.append(vendor_order.id)
                objs = []
                for vendor_order_product in vendor_order_products:
                    if not approval_needed:
                        budget_spend_type = vendor_order_product.budget_spend_type
                        if not budget_spend_type:
                            budget_spend_type = default_budget_spend_type
                        budgetwise_spend[budget_spend_type] += Decimal(
                            vendor_order_product.quantity * vendor_order_product.unit_price
                        )

                    product: Product = vendor_order_product.product
                    objs.append(
                        m.VendorOrderProduct(
                            vendor_order=vendor_order,
                            product=product,
                            quantity=vendor_order_product.quantity,
                            unit_price=vendor_order_product.unit_price,
                            budget_spend_type=vendor_order_product.budget_spend_type,
                            status=m.ProductStatus.PENDING_APPROVAL if approval_needed else m.ProductStatus.PROCESSING,
                        )
                    )
                    if office_vendor.vendor.slug == "crazy_dental":
                        current_date = timezone.localtime().date()
                        office_product_category_obj = self.get_or_create_office_product_category(
                            office=office.id, category_slug=product.category.slug, category_name=product.category.slug
                        )
                        office_product, created = OfficeProduct.objects.get_or_create(
                            office=office,
                            product=product,
                            defaults={
                                "office_product_category": office_product_category_obj,
                                "last_order_date": current_date,
                                "last_order_price": vendor_order_product.unit_price,
                                "vendor_id": crazy_dental_ordo_vendor_id,
                                "is_favorite": True,
                                "is_inventory": True,
                            },
                        )
                        if not created:
                            office_product.last_order_price = vendor_order_product.unit_price
                            office_product.is_favorite = True
                            office_product.is_inventory = True
                            office_product.office_product_category = office_product_category_obj
                            office_product.vendor_id = crazy_dental_ordo_vendor_id
                            office_product.last_order_date = current_date
                            office_product.save()

                    else:
                        OfficeProduct.objects.filter(office=office, product=product).update(
                            last_order_price=vendor_order_product.unit_price, is_inventory=True, is_favorite=True
                        )
                m.VendorOrderProduct.objects.bulk_create(objs)

                send_date = datetime.datetime.utcnow() + timedelta(days=1)
                print("send_date", send_date)
                # fetch_order_history.apply_async(
                #     [office_vendor.vendor.slug, office_vendor.office.id, False], eta=send_date
                # )

            order.total_amount = total_amount
            order.total_items = total_items
            order.save()

            update_cart_or_checkout_status(
                office=office_vendors[0].office,
                user=self.request.user,
                checkout_status=m.OfficeCheckoutStatus.CHECKOUT_STATUS.COMPLETE,
                order_status=m.OfficeCheckoutStatus.ORDER_STATUS.COMPLETE,
            )

            current_date = timezone.localtime().date()
            month = Month(year=current_date.year, month=current_date.month)

            OfficeBudgetHelper.adjust_spends(office_id=office.pk, month=month, spends=budgetwise_spend)

            cart_products.delete()
        if not approval_needed:
            perform_real_order.delay(vendor_order_ids)
        notify_order_creation.delay(vendor_order_ids, approval_needed)
        return s.OrderSerializer(order).data

    # def get_updated_price(self, product_id, all_products):
    #     updated_price = 0
    #     for product in all_products:
    #         if product["id"] == product_id:
    #             updated_price = product["updated_unit_price"]
    #             if updated_price is None:
    #                 updated_price = float(product["unit_price"])
    #
    #             break
    #     return updated_price
    def get_products_children_and_related_office_products(self, cart_product_parent_id, connected_vendor_ids):
        return Product.objects.filter(
            parent_id=cart_product_parent_id, vendor__in=connected_vendor_ids
        ).prefetch_related(
            Prefetch("office_products", queryset=OfficeProduct.objects.filter(office_id=self.kwargs["office_pk"]))
        )

    @action(detail=False, url_path="checkout", methods=["get"], permission_classes=[p.OrderCheckoutPermission])
    async def checkout(self, request, *args, **kwargs):
        can_use_cart = await sync_to_async(get_cart_status_and_order_status)(
            office=self.kwargs["office_pk"], user=request.user
        )
        if not can_use_cart:
            return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)

        cart_products, office_vendors = await sync_to_async(get_cart)(office_pk=self.kwargs["office_pk"])
        if not cart_products:
            return Response({"can_checkout": False, "message": msgs.EMPTY_CART}, status=HTTP_400_BAD_REQUEST)

        await sync_to_async(update_cart_or_checkout_status)(
            office=office_vendors[0].office,
            user=request.user,
            checkout_status=m.OfficeCheckoutStatus.CHECKOUT_STATUS.IN_PROGRESS,
        )

        result = {}
        try:
            connected_vendor_ids = await sync_to_async(OfficeVendorHelper.get_connected_vendor_ids)(
                self.kwargs["office_pk"]
            )
            for office_vendor, cart_item in zip(office_vendors, cart_products):
                cart_product_parent_id = cart_item.product.parent_id

                product_variants = await sync_to_async(self.get_products_children_and_related_office_products)(
                    cart_product_parent_id, connected_vendor_ids
                )

                cart_product_price = cart_item.unit_price

                product_variants_prices = []
                async for product in product_variants:
                    general_price = product.price
                    office_specific_product = product.office_products.all()
                    if office_specific_product:
                        office_specific_product_price = office_specific_product[0].price
                        if office_specific_product_price:
                            product_variants_prices.append(office_specific_product_price)
                        elif general_price:
                            product_variants_prices.append(general_price)
                    elif general_price:
                        product_variants_prices.append(general_price)

                max_product_variants_prices = max(product_variants_prices)
                savings_per_item = max_product_variants_prices - cart_product_price

                total_savings = cart_item.quantity * savings_per_item

                vendor_cart_products = cart_products.filter(product__vendor=office_vendor.vendor).select_related(
                    "promotion"
                )
                subtotal_amount = sum(
                    [
                        cart_product.quantity
                        * (
                            cart_product.unit_price
                            if isinstance(cart_product.unit_price, (int, float, Decimal))
                            else 0
                        )
                        async for cart_product in vendor_cart_products
                    ]
                )
                reduction_amount = 0

                async for cart_product in vendor_cart_products:
                    if isinstance(cart_product.unit_price, (int, float, Decimal)):
                        price = cart_product.unit_price
                        if (
                            cart_product.promotion is not None
                            and cart_product.promotion.type == 1
                            and cart_product.unit_price > cart_product.promotion.reduction_price
                        ):
                            price -= max(0, cart_product.promotion.reduction_price)
                        reduction_amount += cart_product.quantity * price

                result[office_vendor.vendor.slug] = {
                    **office_vendor.vendor.to_dict(),
                    "retail_amount": Decimal(0),
                    "savings_amount": total_savings,
                    "subtotal_amount": subtotal_amount,
                    "shipping_amount": Decimal(0),
                    "tax_amount": Decimal(0),
                    "total_amount": subtotal_amount,
                    "payment_method": "",
                    "shipping_address": "",
                    "reduction_amount": Decimal(reduction_amount),
                }
        except Exception as e:
            return Response({"message": f"{e}"}, status=HTTP_400_BAD_REQUEST)
        products = await sync_to_async(get_serializer_data)(s.CartSerializer, cart_products, many=True)
        # changes for crazy dental cc card
        vendor = [
            office_vendor.vendor.slug
            for office_vendor in office_vendors
            if office_vendor.vendor.slug == "crazy_dental"
        ]
        print("vendor", vendor)
        if vendor:
            get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
            customer_id = await get_vendor_customer_id_async(office_id=self.kwargs["office_pk"])
            if customer_id:
                session = await get_client_session()
                crazy_dental_client = CrazyDentalNewClient(session=session)
                customer_address_info = await crazy_dental_client.get_customer_address(customer_id)
                if customer_address_info[-1]["addressee"]:
                    is_cc_details = True
                else:
                    is_cc_details = False

                return Response({"is_cc_details": is_cc_details, "products": products, "order_details": result})
            else:
                return Response({"is_cc_details": False, "products": products, "order_details": result})
        else:
            return Response({"products": products, "order_details": result})

    @action(detail=False, url_path="confirm-order", methods=["post"], permission_classes=[p.OrderCheckoutPermission])
    async def confirm_order(self, request, *args, **kwargs):
        shipping_options = request.data.get("shipping_options")

        cart_products, office_vendors = await sync_to_async(get_cart)(office_pk=self.kwargs["office_pk"])

        if not cart_products:
            return Response({"can_checkout": False, "message": msgs.EMPTY_CART}, status=HTTP_400_BAD_REQUEST)

        session = await get_client_session()
        tasks = []
        debug = OrderService.is_debug_mode(request.META["HTTP_HOST"])

        redundancy = OrderService.is_force_redundancy()
        # check order app
        if request.user.role == m.User.Role.ADMIN:
            order_approval_needed = False
        else:
            # total_amount = sum(
            #     [Decimal(str(vendor_data["total_amount"])) for vendor, vendor_data in data.items() if
            #      vendor != "amazon"]
            # )

            remaining_budget = await sync_to_async(OfficeService.get_office_remaining_budget)(
                office_pk=self.kwargs["office_pk"]
            )
            office_setting = await sync_to_async(OfficeService.get_office_setting)(office_pk=self.kwargs["office_pk"])
            order_approval_needed = (office_setting.requires_approval_notification_for_all_orders is True) or (
                office_setting.requires_approval_notification_for_all_orders is False
                and remaining_budget[0] < office_setting.budget_threshold
            )
        fake_order = debug or order_approval_needed

        for office_vendor in office_vendors:
            shipping_method_pk = shipping_options.get(office_vendor.vendor.slug)
            shipping_method = await ShippingMethod.objects.filter(pk=shipping_method_pk).afirst()
            shipping_options[office_vendor.vendor.slug] = shipping_method
            scraper = ScraperFactory.create_scraper(
                vendor=office_vendor.vendor,
                session=session,
                username=office_vendor.username,
                password=office_vendor.password,
            )
            tasks.append(
                scraper.redundancy_order(
                    [
                        CartProduct(
                            product_id=cart_product.product.product_id,
                            product_unit=cart_product.product.product_unit,
                            product_url=cart_product.product.url,
                            price=cart_product.unit_price
                            if isinstance(cart_product.unit_price, (int, float, Decimal))
                            else 0,
                            quantity=int(cart_product.quantity),
                        )
                        for cart_product in cart_products
                        if cart_product.product.vendor.id == office_vendor.vendor.id
                    ],
                    shipping_method=shipping_method,
                    fake=fake_order,
                    redundancy=redundancy,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        order_data = await self._create_order(
            office_vendors, results, cart_products, order_approval_needed, shipping_options, fake_order
        )
        await session.close()
        return Response(order_data)

    @action(detail=False, url_path="add-multiple-products", methods=["post"])
    def add_multiple_products(self, request, *args, **kwargs):
        data = request.data
        office_pk = self.kwargs["office_pk"]
        can_use_cart, _ = get_cart_status_and_order_status(office=office_pk, user=request.user)
        if not can_use_cart:
            return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)

        serializer = s.CartCreateSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer_data = save_serailizer(serializer)
        return Response(serializer_data, status=HTTP_201_CREATED)

        # products = request.data
        # office_pk = self.kwargs["office_pk"]
        # can_use_cart, _ = await sync_to_async(get_cart_status_and_order_status)(office=office_pk, user=request.user)
        # if not can_use_cart:
        #     return Response({"message": msgs.CHECKOUT_IN_PROGRESS}, status=HTTP_400_BAD_REQUEST)
        # if not isinstance(products, list):
        #     return Response({"message": msgs.PAYLOAD_ISSUE}, status=HTTP_400_BAD_REQUEST)
        # result = []
        # for product in products:
        #     product["office"] = office_pk
        #     serializer = self.get_serializer(data=product)
        #     await sync_to_async(serializer.is_valid)(raise_exception=True)
        #     product_id = serializer.validated_data["office_product"]["product"]["product_id"]
        #     product_url = serializer.validated_data["office_product"]["product"]["url"]
        #     vendor = serializer.validated_data["office_product"]["product"]["vendor"]
        #     product_category = serializer.validated_data["office_product"]["product"]["category"]
        #     serializer.validated_data["unit_price"] = serializer.validated_data["office_product"]["price"]
        #     #     try:
        #     #         await self.update_vendor_cart(
        #     #             product_id,
        #     #             vendor,
        #     #             serializer,
        #     #         )
        #     if not product_category:
        #         update_product_detail.delay(product_id, product_url, office_pk, vendor.id)
        #         # except VendorSiteError as e:
        #         #     return Response(
        #         #         {"message": f"{msgs.VENDOR_SITE_ERROR} - {e}"},
        #         #         status=HTTP_500_INTERNAL_SERVER_ERROR
        #         #     )
        #         # except VendorNotConnected:
        #         #     return Response({"message": "Vendor not connected"}, status=HTTP_400_BAD_REQUEST)
        #     serializer_data = await sync_to_async(save_serailizer)(serializer)
        #     result.append(serializer_data)
        # return Response(result, status=HTTP_201_CREATED)


class CheckoutAvailabilityAPIView(APIView):
    permission_classes = [p.OrderCheckoutPermission, p.OfficeSubscriptionPermission]

    def get(self, request, *args, **kwargs):
        cart_products, office_vendors = get_cart(office_pk=kwargs.get("office_pk"))
        if not cart_products:
            return Response({"message": msgs.EMPTY_CART}, status=HTTP_400_BAD_REQUEST)

        can_use_cart = False
        if len(office_vendors) > 0:
            can_use_cart, _ = get_cart_status_and_order_status(office=office_vendors[0].office, user=request.user)
        return Response({"can_use_cart": can_use_cart})


class CheckoutUpdateStatusAPIView(APIView):
    permission_classes = [p.OrderCheckoutPermission, p.OfficeSubscriptionPermission]

    def post(self, request, *args, **kwargs):
        cart_products, office_vendors = get_cart(office_pk=kwargs.get("office_pk"))
        if not cart_products:
            return Response({"message": msgs.EMPTY_CART}, status=HTTP_400_BAD_REQUEST)

        office = office_vendors[0].office
        serializer = s.OfficeCheckoutStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if office.checkout_status.checkout_status and office.checkout_status.user != request.user:
            return Response({"message": msgs.WAIT_UNTIL_ORDER_FINISH}, status=HTTP_400_BAD_REQUEST)
        else:
            update_cart_or_checkout_status(
                office=office,
                user=request.user,
                checkout_status=serializer.validated_data["checkout_status"],
            )
            return Response({"message": "Status updated successfully"})


class OfficeProductViewSet(AsyncMixin, ModelViewSet):
    queryset = m.OfficeProduct.objects.all()
    serializer_class = s.OfficeProductSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [p.OfficeSubscriptionPermission]

    def get_serializer_context(self):
        ret = super().get_serializer_context()
        ret["office_pk"] = self.kwargs["office_pk"]
        ret["include_children"] = True
        ret["filter_inventory"] = self.request.query_params.get("inventory", False)
        return ret

    def get_list_queryset(self):
        # Get query parameters from the request
        category_ordering = self.request.query_params.get("category_ordering")
        category_or_price = self.request.query_params.get("category_or_price", "price")
        price_from = self.request.query_params.get("price_from", -1)
        price_to = self.request.query_params.get("price_to", -1)
        office_pk = self.kwargs["office_pk"]
        print("category_ordering", category_ordering)
        # Start with the base queryset of OfficeProduct filtered by office_id
        queryset = OfficeProduct.objects.filter(office__id=office_pk)

        # Apply price filters if provided
        if price_from != 0:
            queryset = queryset.filter(price__gte=price_from)
        if price_to != -1:
            queryset = queryset.filter(price__lte=price_to)

        # Create a custom filter using a filter class
        filterset = f.OfficeProductFilter(data=self.request.query_params, queryset=queryset)
        queryset = filterset.qs

        # Apply custom method 'collapse_by_parent_products' on the queryset
        queryset = queryset.collapse_by_parent_products()

        # Fetch related office products
        office_products = OfficeProduct.objects.filter(Q(office_id=office_pk))

        # connected_vendor_ids = list(OfficeVendorHelper.get_connected_vendor_ids(office_pk))
        cache_key = f"connected_vendor_ids_{office_pk}"

        # Try to get the connected vendor IDs from the cache
        connected_vendor_ids = cache.get(cache_key)

        # If the cache is empty, fetch the connected vendor IDs and store them in the cache
        if connected_vendor_ids is None:
            connected_vendor_ids = list(OfficeVendorHelper.get_connected_vendor_ids(office_pk))
            cache.set(cache_key, connected_vendor_ids, 3600)

        office_product_price = OfficeProduct.objects.filter(Q(office=office_pk) & Q(product_id=OuterRef("pk"))).values(
            "price"
        )
        # Create a query that fetches products associated with vendors linked to the user
        child_prefetch_queryset = (
            Product.objects.filter(vendor__in=connected_vendor_ids)
            .select_related("category", "vendor")
            .prefetch_related("images", Prefetch("office_products", office_products, to_attr="office_product"))
            .annotate(office_product_price=Subquery(office_product_price))
            .annotate(
                product_price=Case(
                    When(office_product_price__isnull=False, then=F("office_product_price")),
                    default=F("price"),
                    output_field=DecimalField(),
                )
            )
            .order_by("product_price")
        )
        print(
            "office_product_category__slug",
        )

        # Annotate the queryset with additional data
        queryset = queryset.select_related("vendor", "office_product_category").annotate(
            category_order=Case(
                When(office_product_category__slug=category_ordering, then=Value(0)),
                When(office_product_category__slug="other", then=Value(2)),
                default=Value(1),
            ),
            last_quantity_ordered=Subquery(
                VendorOrderProduct.objects.filter(
                    product_id=OuterRef("product_id"), vendor_order__order__office_id=office_pk
                )
                .order_by("-updated_at")
                .values("quantity")[:1]
            ),
        )

        # Prefetch related data to optimize database queries
        queryset = queryset.prefetch_related(
            Prefetch(
                "product",
                Product.objects.select_related("vendor", "category").prefetch_related(
                    Prefetch(
                        "parent",
                        Product.objects.annotate(is_inventory=Value(True))
                        .select_related(
                            "category",
                            "vendor",
                        )
                        .prefetch_related(
                            Prefetch("children", child_prefetch_queryset),
                            "images",
                        ),
                    )
                ),
            ),
        )

        # Apply sorting based on category or price
        if category_or_price == "category":
            return queryset.order_by(
                "category_order",
                "office_product_category__slug",
                "price",
                "-updated_at",
            )
        else:
            return queryset.order_by(
                "price",
                "category_order",
                "office_product_category__slug",
                "-updated_at",
            )

    def get_queryset(self):
        if self.action == "list":
            return self.get_list_queryset()
        office_pk = self.kwargs["office_pk"]
        return OfficeProduct.objects.filter(office__id=office_pk)

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="remove")
    def remove_from_inventory(self, request, *args, **kwargs):
        """
        NOTE: Uncategorized API - I left this API because of Uncategorized category in frontend.
        """
        instance = self.get_object()
        other_category = m.OfficeProductCategory.objects.filter(office=instance.office, slug="other").first()
        instance.office_product_category = other_category
        instance.save()
        return Response({"message": "Deleted successfully"}, status=HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="hide")
    def hide_from_inventory(self, request, *args, **kwargs):
        instance = self.get_object()
        hidden_category = m.OfficeProductCategory.objects.filter(
            office=instance.office, slug="hidden-products"
        ).first()
        instance.previous_office_product_category = instance.office_product_category.id
        instance.office_product_category = hidden_category
        instance.save()
        return Response({"message": "Hid successfully"}, status=HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="unhide")
    def unhide_from_inventory(self, request, *args, **kwargs):
        instance = self.get_object()
        previous_category = m.OfficeProductCategory.objects.filter(
            pk=instance.previous_office_product_category
        ).first()
        instance.office_product_category = previous_category
        instance.previous_office_product_category = None
        instance.save()
        return Response({"message": "Unhid successfully"}, status=HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="prices")
    async def get_product_prices(self, request, *args, **kwargs):
        serializer = s.ProductPriceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        product_ids = serializer.validated_data["products"]
        products = {
            product.id: product
            async for product in m.Product.objects.select_related("vendor", "category").filter(id__in=product_ids)
        }
        response = await OfficeProductHelper.get_product_prices(
            products=products, office=self.kwargs["office_pk"], from_api=False
        )
        return Response(response)

    @action(detail=False, methods=["post"], url_path="update_prices")
    async def update_product_prices(self, request, *args, **kwargs):
        serializer = s.ProductPriceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        product_ids = serializer.validated_data["products"]
        products = {
            product.id: product
            async for product in m.Product.objects.select_related("vendor", "category").filter(id__in=product_ids)
        }
        try:
            response = await OfficeProductHelper.update_product_prices(
                products=products, office=self.kwargs["office_pk"], from_api=False
            )
            return Response(response)
        except Exception as e:
            print("price:error:", e)


class OfficeProductUnlinkedVendorViewSet(AsyncMixin, ModelViewSet):
    queryset = m.OfficeProduct.objects.all()
    serializer_class = s.OfficeProductSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [p.OfficeSubscriptionPermission]

    def get_serializer_context(self):
        ret = super().get_serializer_context()
        ret["office_pk"] = self.kwargs["office_pk"]
        ret["include_children"] = True
        ret["filter_inventory"] = False
        return ret

    def get_list_queryset(self):
        # Get query parameters from the request
        category_ordering = self.request.query_params.get("category_ordering")
        category_or_price = self.request.query_params.get("category_or_price", "price")
        price_from = self.request.query_params.get("price_from", -1)
        price_to = self.request.query_params.get("price_to", -1)
        office_pk = self.kwargs["office_pk"]

        # Start with the base queryset of OfficeProduct filtered by office_id
        queryset = OfficeProduct.objects.filter(office__id=office_pk)

        # Apply price filters if provided
        if price_from != 0:
            queryset = queryset.filter(price__gte=price_from)
        if price_to != -1:
            queryset = queryset.filter(price__lte=price_to)

        # Create a custom filter using a filter class
        filterset = f.OfficeProductFilterForUnlinkedVendors(data=self.request.query_params, queryset=queryset)
        queryset = filterset.qs

        # Apply custom method 'collapse_by_parent_products' on the queryset
        queryset = queryset.collapse_by_parent_products()

        # Fetch related office products
        office_products = OfficeProduct.objects.filter(Q(office_id=office_pk))

        # Create a query that fetches products associated with vendors linked to the user
        child_prefetch_queryset = (
            Product.objects.all()
            .select_related("category", "vendor")
            .prefetch_related("images", Prefetch("office_products", office_products, to_attr="office_product"))
        )

        # Annotate the queryset with additional data
        queryset = queryset.select_related("vendor", "office_product_category").annotate(
            category_order=Case(
                When(office_product_category__slug=category_ordering, then=Value(0)),
                When(office_product_category__slug="other", then=Value(2)),
                default=Value(1),
            ),
            last_quantity_ordered=Subquery(
                VendorOrderProduct.objects.filter(
                    product_id=OuterRef("product_id"), vendor_order__order__office_id=office_pk
                )
                .order_by("-updated_at")
                .values("quantity")[:1]
            ),
        )

        # Prefetch related data to optimize database queries
        queryset = queryset.prefetch_related(
            Prefetch(
                "product",
                Product.objects.select_related("vendor", "category").prefetch_related(
                    Prefetch(
                        "parent",
                        Product.objects.annotate(is_inventory=Value(True))
                        .select_related(
                            "category",
                            "vendor",
                        )
                        .prefetch_related(
                            Prefetch("children", child_prefetch_queryset),
                            "images",
                        ),
                    )
                ),
            ),
        )

        # Apply sorting based on category or price
        if category_or_price == "category":
            return queryset.order_by(
                "category_order",
                "office_product_category__slug",
                "price",
                "-updated_at",
            )
        else:
            return queryset.order_by(
                "price",
                "category_order",
                "office_product_category__slug",
                "-updated_at",
            )

    def get_queryset(self):
        if self.action == "list":
            return self.get_list_queryset()
        office_pk = self.kwargs["office_pk"]
        return OfficeProduct.objects.filter(office__id=office_pk)


class SearchProductAPIView(AsyncMixin, APIView, SearchProductPagination):
    # queryset = m.OfficeProduct.objects.all()
    # serializer_class = s.OfficeProductSerializer
    # pagination_class = SearchProductPagination
    permission_classes = [p.OfficeSubscriptionPermission]

    def get_queryset(self):
        data = self.request.data
        keyword = data.get("q")
        pagination_meta = data.get("meta", {})
        min_price = data.get("min_price", 0)
        max_price = data.get("max_price", 0)
        vendors_slugs = [vendor_meta["vendor"] for vendor_meta in pagination_meta.get("vendors", [])]
        queryset = m.OfficeProduct.objects.filter(
            Q(office__id=self.kwargs["office_pk"])
            & Q(product__parent__isnull=True)
            & Q(is_inventory=False)
            & (
                Q(product__product_id=keyword)
                | Q(product__name__search=keyword)
                | Q(product__tags__keyword__iexact=keyword)
                | Q(product__child__product_id=keyword)
                | Q(product__child__name__icontains=keyword)
                | Q(product__child__tags__keyword__iexact=keyword)
            )
        )

        product_filters = Q()
        if min_price:
            product_filters &= Q(price__gte=min_price)

        if max_price:
            product_filters &= Q(price__lte=max_price)

        if vendors_slugs:
            product_filters &= Q(product__vendor__slug__in=vendors_slugs)

        if product_filters:
            queryset = queryset.filter(product_filters)
        return queryset.distinct().order_by("price")

    def get_linked_vendors(self):
        office_vendors = OfficeVendor.objects.select_related("vendor").filter(office_id=self.kwargs["office_pk"])
        return list(office_vendors)

    def has_keyword_history(self, keyword: str):
        keyword = keyword.lower()
        office_vendors = self.get_linked_vendors()
        # new_office_vendors is a list of vendors which we haven't search history yet
        vendors_to_be_scraped = []
        vendors_to_be_waited = []
        pagination_meta = self.request.data.get("meta", {})
        vendors_slugs = [
            vendor_meta["vendor"]
            for vendor_meta in pagination_meta.get("vendors", [])
            if vendor_meta["vendor"] != "amazon"
        ]
        amazon_linked = False
        for office_vendor in office_vendors:
            if (
                office_vendor.vendor.slug in ["ultradent", "amazon", "edge_endo"]
                or vendors_slugs
                and office_vendor.vendor.slug not in vendors_slugs
            ):
                amazon_linked = True
                continue

            keyword_obj, _ = m.Keyword.objects.get_or_create(keyword=keyword)
            office_keyword_obj, _ = m.OfficeKeyword.objects.get_or_create(
                keyword=keyword_obj, office_id=self.kwargs["office_pk"], vendor=office_vendor.vendor
            )
            if office_keyword_obj.task_status in [
                m.OfficeKeyword.TaskStatus.NOT_STARTED,
                m.OfficeKeyword.TaskStatus.FAILED,
            ]:
                vendors_to_be_scraped.append(office_vendor.vendor.id)
            elif office_keyword_obj.task_status in [
                m.OfficeKeyword.TaskStatus.IN_PROGRESS,
                m.OfficeKeyword.TaskStatus.FETCHING_COMPLETE,
            ]:
                vendors_to_be_waited.append(office_vendor.vendor.id)

        if vendors_to_be_scraped:
            search_and_group_products.delay(keyword, self.kwargs["office_pk"], vendors_to_be_scraped)
            return False, amazon_linked
        if vendors_to_be_waited:
            return True, amazon_linked
        return True, amazon_linked

    @sync_to_async
    def get_products_from_db(self, *args, **kwargs):
        queryset = self.get_queryset()
        requested_vendors = kwargs.get("requested_vendors", None)
        if requested_vendors:
            queryset = queryset.filter(product__vendor__slug__in=requested_vendors)

        try:
            page = self.paginate_queryset(queryset, self.request, view=self)
        except NotFound:
            page = []
        serializer = s.OfficeProductSerializer(page, many=True, context={"include_children": True})
        data = serializer.data
        # amazon search
        amazon_search_result = kwargs.get("amazon")
        if amazon_search_result:
            amazon_search = True
            amazon_total_size = amazon_search_result["total_size"]
            amazon_last_page = amazon_search_result["last_page"]
            amazon_page = amazon_search_result["page"]
            for amazon_product in amazon_search_result["products"]:
                product_data = amazon_product.to_dict()
                price = product_data.pop("price")
                data.append(
                    {
                        "id": None,
                        "product": product_data,
                        "price": price,
                        "office_product_category": None,
                        "is_favorite": False,
                        "is_inventory": False,
                    }
                )

        else:
            amazon_search = False
            amazon_total_size = 0
            amazon_last_page = True
            amazon_page = 0

        return self.get_paginated_response(
            data,
            amazon_search=amazon_search,
            amazon_total_size=amazon_total_size,
            amazon_page=amazon_page,
            amazon_last_page=amazon_last_page,
        )

    async def fetch_products(self, keyword, min_price, max_price, vendors=None, include_amazon=False):
        pagination_meta = self.request.data.get("meta", {})
        vendors_meta = {vendor_meta["vendor"]: vendor_meta for vendor_meta in pagination_meta.get("vendors", [])}
        session = await get_client_session()
        office_vendors = await sync_to_async(self.get_linked_vendors)()
        tasks = []
        for office_vendor in office_vendors:
            vendor_slug = office_vendor.vendor.slug
            if vendor_slug == "amazon" and include_amazon is False:
                continue

            if vendors and vendor_slug not in vendors:
                continue

            if vendors_meta.keys() and vendor_slug not in vendors_meta.keys():
                continue

            if vendors_meta.get(vendor_slug, {}).get("last_page", False):
                continue
            try:
                scraper = ScraperFactory.create_scraper(
                    vendor=office_vendor.vendor,
                    session=session,
                    username=office_vendor.username,
                    password=office_vendor.password,
                )
            except VendorNotSupported:
                continue
            current_page = vendors_meta.get(vendor_slug, {}).get("page", 0)
            tasks.append(
                scraper.search_products(query=keyword, page=current_page + 1, min_price=min_price, max_price=max_price)
            )
        search_results = await asyncio.gather(*tasks, return_exceptions=True)
        return search_results

    async def post(self, request, *args, **kwargs):
        data = request.data
        keyword = data.get("q")
        keyword = keyword.strip()
        pagination_meta = data.get("meta", {})
        include_amazon = data.get("include_amazon", False)
        requested_vendors = data.get("vendors", [])

        if pagination_meta.get("last_page", False):
            return Response({"message": msgs.NO_SEARCH_PRODUCT_RESULT}, status=HTTP_400_BAD_REQUEST)

        # if len(keyword) <= 3:
        #     return Response({"message": msgs.SEARCH_QUERY_LIMIT}, status=HTTP_400_BAD_REQUEST)

        has_history, amazon_linked = await sync_to_async(self.has_keyword_history)(keyword)
        try:
            min_price = data.get("min_price", 0)
            max_price = data.get("max_price", 0)
            min_price = int(min_price)
            max_price = int(max_price)
        except ValueError:
            return Response({"message": msgs.SEARCH_PRODUCT_WRONG_PARAMETER}, status=HTTP_400_BAD_REQUEST)

        if has_history:
            amazon_result = None
            if amazon_linked and include_amazon:
                search_results = await self.fetch_products(
                    keyword, min_price, max_price, vendors=["amazon"], include_amazon=True
                )
                amazon_result = search_results[0]

            return await self.get_products_from_db(requested_vendors=requested_vendors, amazon=amazon_result)

        search_results = await self.fetch_products(
            keyword, min_price, max_price, vendors=requested_vendors, include_amazon=False
        )
        updated_vendor_meta, products = group_products_from_search_result(search_results)
        if "vendors" in pagination_meta:
            for updated_vendor_meta in updated_vendor_meta["vendors"]:
                vendor_meta = [
                    vendor_meta
                    for vendor_meta in pagination_meta["vendors"]
                    if vendor_meta["vendor"] == updated_vendor_meta["vendor"]
                ][0]
                vendor_meta["page"] = updated_vendor_meta["page"]
                vendor_meta["last_page"] = updated_vendor_meta["last_page"]

            pagination_meta["last_page"] = all(vendor_meta["last_page"] for vendor_meta in pagination_meta["vendors"])
        else:
            pagination_meta = updated_vendor_meta

        # exclude inventory products
        inventory_products = await sync_to_async(get_inventory_products)(self.kwargs["office_pk"])
        results = []
        for product_or_products in products:
            if isinstance(product_or_products, list):
                ret = []
                for product in product_or_products:
                    key = f"{product['product_id']}-{product['vendor']['id']}"
                    if key in inventory_products:
                        continue
                    ret.append(product)
            else:
                key = (
                    f"{product_or_products['product']['product_id']}-{product_or_products['product']['vendor']['id']}"
                )
                if key in inventory_products:
                    continue
                ret = product_or_products
            if ret:
                results.append(ret)

        return Response({"meta": pagination_meta, "products": results})


class ProductV2ViewSet(AsyncMixin, ModelViewSet):
    queryset = m.Product.objects.all()
    serializer_class = s.ProductV2Serializer
    pagination_class = SearchProductV2Pagination
    # filterset_class = f.ProductV2Filter
    http_method_names = ["get"]

    def get_queryset(self):
        query = self.request.GET.get("search", "")
        SearchHistory.objects.create(user=self.request.user, query=query)
        office_pk = self.request.query_params.get("office_pk")
        selected_products = self.request.query_params.get("selected_products")
        vendors = self.request.query_params.get("vendors")
        price_from = self.request.query_params.get("price_from", "")
        price_from = Decimal(price_from) if price_from.strip() else -1
        price_to = self.request.query_params.get("price_to", "")
        price_to = Decimal(price_to) if price_to.strip() else -1

        selected_products = selected_products.split(",") if selected_products else []
        print("selected_products", selected_products)
        products, available_vendors = ProductHelper.get_products_v3(
            query=query,
            office=office_pk,
            fetch_parents=True,
            selected_products=selected_products,
            vendors=vendors,
            price_from=price_from,
            price_to=price_to,
        )
        self.available_vendors = available_vendors
        print("products", products)
        print("available_vendors", available_vendors)
        return products
        # products = m.Product.objects.search(query)
        # product_ids = products.values_list("id", flat=True)
        # return ProductHelper.get_products_v2(
        #     office=office_pk, fetch_parents=True, selected_products=selected_products, product_ids=product_ids
        # )

    def get_serializer_context(self):
        serializer_context = super().get_serializer_context()
        office_pk = self.request.query_params.get("office_pk")
        vendors = self.request.query_params.get("vendors")
        price_from = self.request.query_params.get("price_from")
        price_to = self.request.query_params.get("price_to")

        return {
            **serializer_context,
            "office_pk": office_pk,
            "vendors": vendors.split(",") if vendors else None,
            "price_from": price_from,
            "price_to": price_to,
        }

    def list(self, request, *args, **kwargs):
        query = self.request.GET.get("search", "")
        vendors = self.request.query_params.get("vendors", "").split(",")
        price_from = self.request.query_params.get("price_from")
        price_to = self.request.query_params.get("price_to")

        queryset = self.get_queryset()
        count_per_page = int(self.request.query_params.get("per_page", 10))
        current_page = int(self.request.query_params.get("page", 1))

        # Temporarily block Amazon Search
        # if "amazon" in vendors:
        #     # Add on the fly results
        #     try:
        #         products_fly = AmazonSearchScraper()._search_products(
        #             query=query, from_price=price_from, to_price=price_to, page=current_page
        #         )
        #     except Exception:  # noqa
        #         products_fly = {"products": []}

        #     if products_fly["products"]:
        #         ProductService.generate_products_from_data(products=products_fly["products"], vendor_slug="amazon")
        #         amazon_product_ids = [i["product_id"] for i in products_fly["products"]]
        #         queryset = queryset | Product.objects.filter(product_id__in=amazon_product_ids)

        # Fetching one more item to make sure if there is some more
        queryset = queryset[: current_page * count_per_page + 1]
        product_list = list(queryset)

        if "ebay" in vendors:
            try:
                ebay_products = EbaySearch().execute(keyword=query, from_price=price_from, to_price=price_to)

                if ebay_products:
                    self.available_vendors.append("ebay")
                    product_list.extend(ebay_products)
            except Exception:  # noqa
                print("Ebay search exception")

        pagination_obj = Paginator(product_list, count_per_page)

        ret = {
            "vendor_slugs": getattr(self, "available_vendors", None),
            "products": [],
        }

        if current_page < 1 or pagination_obj.num_pages < current_page:
            return Response({"message": "The page number is incorrect!"}, status=HTTP_400_BAD_REQUEST)

        page = pagination_obj.page(current_page)

        if page is not None:
            product_data = []
            for page_item in page:
                if isinstance(page_item, m.Product):
                    serializer = self.get_serializer(page_item)
                    serialized_data = serializer.data
                    serialized_data["searched_data"] = False
                    product_data.append(serialized_data)
                else:
                    page_item["searched_data"] = True
                    product_data.append(page_item)
            ret["products"] = product_data
            bottom = (current_page - 1) * count_per_page
            top = bottom + count_per_page

            if price_to is not None or price_from is not None:
                ret["products"].sort(
                    key=lambda parent: float(parent["children"][0]["product_price"])
                    if parent["children"]
                    else float("inf")
                )

            return Response(
                {
                    "total": -1,
                    "from": bottom + 1,
                    "to": top,
                    "per_page": count_per_page,
                    "current_page": page.number,
                    "next_page": page.next_page_number() if page.has_next() else None,
                    "prev_page": page.previous_page_number() if page.has_previous() else None,
                    "data": ret,
                    # "log": log,
                }
            )

        serializer = self.get_serializer(product_list, many=True)
        ret["products"] = serializer.data
        return Response(ret)

    @action(detail=False, url_path="search/vendors")
    async def search_from_vendors(self, request, *args, **kwargs):
        # Currently, we support amazon search on-the-fly
        serializer = s.VendorProductSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        await OfficeProductHelper.get_products_from_vendors(
            vendor_slugs=["amazon"],
            office_id=self.kwargs.get("office_pk"),
            q=serializer.validated_data["q"],
            min_price=serializer.validated_data["min_price"],
            max_price=serializer.validated_data["max_price"],
        )

    @action(detail=False, url_path="suggest", methods=["get"])
    def get_product_suggestion(self, request, *args, **kwargs):
        office_pk = request.query_params.get("office_pk")
        # print("office_pk", office_pk)
        vendors = list(OfficeVendorHelper.get_connected_vendor_ids(office_pk))
        # print("vendors list ids", vendors)

        suggested_products = ProductHelper.suggest_products(
            search=request.query_params.get("search"), office=office_pk, vendors=vendors
        )[:5]
        return Response(s.SimpleProductSerializer(suggested_products, many=True).data)


class ProcedureViewSet(AsyncMixin, ModelViewSet):
    queryset = m.Procedure.objects.all()
    serializer_class = s.ProcedureSerializer

    # This can be used later
    # def get_queryset(self):
    #     query = self.request.GET.get("search", "")
    #     if query:
    #         return m.Procedure.objects.search(query)
    #     return m.Procedure.objects.all()

    @action(detail=False)
    def summary_category(self, request, *args, **kwargs):
        today = timezone.localtime().date()
        office_pk = self.kwargs["office_pk"]
        office = m.Office.objects.get(id=office_pk)
        dental_api = office.dental_api
        if not dental_api:
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": "No Open Dental key"})
        day_range = self.request.query_params.get("date_range")
        start_end_date = get_date_range(day_range)
        day_from = start_end_date[0]
        day_to = start_end_date[1]
        first_day_of_this_week = today - datetime.timedelta(days=today.weekday())
        day_prev_12weeks_from = first_day_of_this_week + relativedelta(weeks=-12)
        day_prev_12weeks_to = first_day_of_this_week - datetime.timedelta(days=1)

        ProcedureHelper.fetch_procedure_period(day_prev_12weeks_from, office_pk)

        query = self.request.GET.get("search", "")
        if query:
            summary_category_ids = (
                self.get_queryset()
                .search(query)
                .filter(
                    office=office,
                    start_date__gte=day_prev_12weeks_from,
                    start_date__lte=day_prev_12weeks_to,
                    procedurecode__summary_category__isnull=False,
                )
                .values_list("procedurecode__summary_category", flat=True)
            )
            summary_categories = m.ProcedureCategoryLink.objects.filter(id__in=summary_category_ids)
        else:
            summary_categories = m.ProcedureCategoryLink.objects.all()
        proc_total = {
            category.summary_slug: {
                "is_favorite": category.is_favorite,
                "count": 0,
                "avg_count": 0,
            }
            for category in summary_categories
        }

        ret_proccodes = (
            m.ProcedureCode.objects.all()
            .values_list(
                "summary_category__summary_slug",
            )
            .annotate(dcount=Count("proccode"), codes=ArrayAgg("proccode"))
            .order_by("dcount")
            .filter(summary_category__isnull=False)
        )

        for slug, _, codes in ret_proccodes:
            if slug in proc_total:
                proc_total[slug]["codes"] = codes

        ret_trailing = (
            self.get_queryset()
            .filter(
                office=office,
                start_date__gte=day_prev_12weeks_from,
                start_date__lte=day_prev_12weeks_to,
            )
            .order_by(
                "procedurecode__summary_category__category_order", "-procedurecode__summary_category__is_favorite"
            )
            .values_list("procedurecode__summary_category", "procedurecode__summary_category__summary_slug")
            .annotate(sum_count=Sum("count"))
            .filter(procedurecode__summary_category__isnull=False)
        )
        for _, slug, total_count in ret_trailing:
            if slug in proc_total:
                proc_total[slug]["avg_count"] = round(total_count * get_week_count(day_range) / 12)

        ret_schedule = []
        try:
            with open("query/proc_schedule.sql", "r") as f:
                raw_sql = f.read()
            query = raw_sql.format(day_from=(day_from if day_from > today else today), day_to=day_to, codes="")
            od_client = OpenDentalClient(dental_api.key)
            ret_schedule, status = od_client.query(query)
            if status != HTTP_200_OK:
                return Response(status=status, data={"message": f"{ret_schedule}"})
        except Exception as e:
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": f"{e}"})

        for proc in ret_schedule:
            for slug, cate in proc_total.items():
                if "codes" in cate and proc["ProcCode"] in cate["codes"]:
                    proc_total[slug]["count"] += proc["Count"]

        return Response(proc_total)

    @action(detail=False)
    def summary_detail(self, request, *args, **kwargs):
        today = timezone.localtime().date()
        summary_category = self.request.query_params.get("summary_category")
        office_pk = self.kwargs["office_pk"]
        day_range = self.request.query_params.get("date_range")
        start_end_date = get_date_range(day_range)
        day_from, day_to = start_end_date
        first_day_of_this_week = today - datetime.timedelta(days=today.weekday())
        day_prev_12weeks_from = first_day_of_this_week - relativedelta(weeks=12)
        day_prev_12weeks_to = first_day_of_this_week - datetime.timedelta(days=1)

        # TODO: naming
        summary_query = m.ProcedureCategoryLink.objects.filter(summary_slug=summary_category).first()
        if not summary_query:
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": "No such summary category slug exists"})

        office = m.Office.objects.filter(id=office_pk).first()

        # TODO: use serializer
        if not office:
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": f"Office with pk={office_pk} not found"})

        dental_api = office.dental_api
        if not dental_api:
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": "No Open Dental key"})
        proccode_ids = (
            self.get_queryset()
            .filter(
                office=office,
                start_date__gte=day_prev_12weeks_from,
                start_date__lte=day_prev_12weeks_to,
                procedurecode__summary_category=summary_query,
            )
            .values_list("procedurecode", flat=True)
        )

        ret_proccodes = m.ProcedureCode.objects.filter(id__in=proccode_ids).values_list(
            "summary_category__summary_slug", "proccode", "descript", "abbr_desc"
        )
        proc_total = {}
        for slug, code, descript, abbr_desc in ret_proccodes:
            proc_total[code] = {
                "Category": slug,
                "Code": code,
                "Description": descript,
                "Abbr_Desc": abbr_desc,
                "avg_count": 0,
                "schedule": 0,
                "complete": 0,
                "total": 0,
            }

        ret_complete = (
            self.get_queryset()
            .filter(
                office=office,
                start_date__gte=day_from,
                start_date__lte=day_to,
                procedurecode__summary_category=summary_query,
            )
            .values_list("procedurecode__proccode")
            .annotate(sum_count=Sum("count"))
        )
        for code, completed_count in ret_complete:
            proc_total[code]["complete"] = completed_count
            proc_total[code]["total"] = completed_count

        ret_trailing = (
            self.get_queryset()
            .filter(
                office=office,
                start_date__gte=day_prev_12weeks_from,
                start_date__lte=day_prev_12weeks_to,
                procedurecode__summary_category=summary_query,
            )
            .values_list("procedurecode__proccode")
            .annotate(sum_count=Sum("count"))
        )
        for code, count in ret_trailing:
            if code in proc_total:
                proc_total[code]["avg_count"] = round(count * get_week_count(day_range) / 12)

        try:
            od_client = OpenDentalClient(dental_api)
            # This might be needed later to grab data from db.
            # with open("query/proc_result_new.sql", "r") as f:
            #     raw_sql = f.read()
            # query = raw_sql.format(day_from=day_from, day_to=day_to, proc_codes=proccodes_comma)
            # json_procedure = od_client.query(query)[0]

            with open(settings.BASE_DIR / "query/proc_schedule.sql", "r") as f:
                raw_sql = f.read()
            proccodes_dash = "|".join(proc_total.keys())
            query = raw_sql.format(
                day_from=(day_from if day_from > today else today), day_to=day_to, codes=proccodes_dash
            )
            ret_schedule, status = od_client.query(query)
            if status != HTTP_200_OK:
                return Response(status=status, data={"message": f"{ret_schedule}"})
            for item in ret_schedule:
                if item["ProcCode"] in proc_total:
                    proc_total[item["ProcCode"]]["schedule"] = item["Count"]
                    proc_total[item["ProcCode"]]["total"] += item["Count"]

            return Response(data=proc_total)

        except Exception as e:  # noqa
            return Response(status=HTTP_400_BAD_REQUEST, data={"message": f"{e}"})


class ProcedureCategoryLink(ModelViewSet):
    queryset = m.ProcedureCategoryLink.objects.all()
    serializer_class = s.ProcedureCategoryLinkSerializer

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)

    @action(detail=False, url_path="linked-products")
    def get_linked_inventory_products(self, request, *args, **kwargs):
        office_pk = self.kwargs["office_pk"]
        summary_category = self.request.query_params.get("summary_category", "all")
        slugs = self.queryset.get(summary_slug=summary_category).linked_slugs

        office_product_price = OfficeProduct.objects.filter(office_id=office_pk, product_id=OuterRef("pk")).values(
            "price"
        )
        linked_vendor_ids = OfficeVendor.objects.filter(office_id=self.kwargs["office_pk"]).values_list(
            "vendor_id", flat=True
        )
        child_prefetch_queryset = (
            Product.objects.annotate(office_product_price=Subquery(office_product_price[:1]))
            .annotate(product_price=Coalesce(F("office_product_price"), F("price")))
            .filter(vendor__id__in=linked_vendor_ids)
            .prefetch_related("images", "category", "vendor")
        )
        queryset = (
            m.OfficeProduct.objects.filter(
                office_id=office_pk, is_inventory=True, office_product_category__slug__in=slugs
            )
            .annotate(
                last_quantity_ordered=Subquery(
                    VendorOrderProduct.objects.filter(
                        product_id=OuterRef("product_id"), vendor_order__order__office_id=office_pk
                    )
                    .order_by("-updated_at")
                    .values("quantity")[:1]
                )
            )
            .prefetch_related(
                "office_product_category",
                "vendor",
                Prefetch(
                    "product",
                    Product.objects.all().prefetch_related(
                        "vendor",
                        Prefetch(
                            "parent",
                            Product.objects.filter(vendor__id__in=linked_vendor_ids).prefetch_related(
                                Prefetch("children", child_prefetch_queryset), "images", "category"
                            ),
                        ),
                    ),
                ),
            )
        )
        all_products = s.OfficeProductSerializer(queryset, many=True, context={"include_children": True}).data
        filtered_products = []
        for product in all_products:
            filtered_children = []
            for children in product["product"]["children"]:
                if children["vendor"]["id"] in linked_vendor_ids:
                    filtered_children.append(children)

            product["product"]["children"] = filtered_children
            if product["product"]["vendor"] is not None:
                if product["product"]["vendor"]["id"] not in linked_vendor_ids:
                    product["product"]["vendor"] = None

            # if len(filtered_children) == 0:
            #     product["product"]["vendor"] = None
            filtered_products.append(product)
        return Response(filtered_products)


class DentalCityProductAPIView(AsyncMixin, APIView):
    async def get(self, request):
        try:
            page_number = int(request.query_params.get("page_number"))
        except (ValueError, TypeError):
            page_number = 1

        session = await get_client_session()
        api_client = DentalCityAPIClient(session=session, auth_key=settings.DENTAL_CITY_AUTH_KEY)
        page_products = await api_client.get_page_products(page_number)
        return Response([asdict(product) for product in page_products])


class DentalCityOrderFlowOrderResponse(APIView):
    authentication_classes = []
    permission_classes = [p.DentalCityOrderFlowPermission]
    parser_classes = [XMLParser]

    def post(self, request):
        logger.info(f"OrderResponse: {request.data}")
        order_id = DentalCityCXMLParser.parse_order_response(request.data)
        order = m.VendorOrder.objects.filter(vendor__slug=SupportedVendor.DentalCity.value, id=order_id).first()
        if order is not None:
            order.vendor_status = "pending"
            order.status = m.OrderStatus.OPEN
            order.save()
        return Response({"message": msgs.SUCCESS})


class DentalCityOrderFlowConfirmationRequest(APIView):
    permission_classes = [p.DentalCityOrderFlowPermission]
    parser_classes = [XMLParser]

    def post(self, request):
        logger.info(f"ConfirmationRequest: {request.data}")
        order_detail: DentalCityOrderDetail = DentalCityCXMLParser.parse_confirm_request(request.data)
        order_id = order_detail.order_id
        vendor_order_id = order_detail.vendor_order_id
        order = m.VendorOrder.objects.filter(vendor__slug=SupportedVendor.DentalCity.value, id=order_id).first()
        if order is not None:
            order.vendor_order_id = vendor_order_id
            order.vendor_status = "in progress"
            order.status = m.OrderStatus.OPEN
            order.save()

        return Response({"message": msgs.SUCCESS})


class DentalCityOrderFlowShipmentNoticeRequest(APIView):
    permission_classes = [p.DentalCityOrderFlowPermission]
    parser_classes = [XMLParser]

    def post(self, request):
        logger.info(f"ShipmentNoticeRequest: {request.data}")
        shipping_info: DentalCityShippingInfo = DentalCityCXMLParser.parse_shipment_notice_request(request.data)
        order_id = shipping_info.order_id
        order = m.VendorOrder.objects.filter(id=order_id).first()
        if order is not None:
            order.vendor_status = "shipped"
            order.status = m.OrderStatus.CLOSED
            order.save()

        return Response({"message": msgs.SUCCESS})


class DentalCityOrderFlowInvoiceDetailRequest(APIView):
    permission_classes = [p.DentalCityOrderFlowPermission]
    parser_classes = [XMLParser]

    def post(self, request):
        logger.info(f"InvoiceDetailRequest: {request.data}")

        DentalCityCXMLParser.parse_invoice_detail_request(request.data)

        return Response({"message": msgs.SUCCESS})


class ReturnProductOrderAPIView(APIView):
    def post(self, request):
        data = request.data
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)
        vendor_order_id = data.get("vendor_order_id")
        # message = (
        #     f"Kindly cancel the order associated with Customer ID {customer_id} and"
        #     f" Order ID {vendor_order_id}. Thank you."
        # )
        html_message = """
                <html>
                <head></head>
                <body>
                    <p>Hi,</p>
                    <p>This is an auto-generated customer's return request. Kindly initiate a request for Customer ID
                     <strong>{customer_id}</strong> for Order ID <strong>{order_id}</strong>. Thanks.</p>
                    <br>
                    <p>Regards,</p>
                    <p>Team Ordo.</p>
                </body>
                </html>
            """.format(
            customer_id=customer_id, order_id=vendor_order_id
        )

        send_mail(
            subject="Order return Request",
            message="message",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=crazy_dental_customer_service_email,
            html_message=html_message,
        )
        if send_mail:
            return Response({"message": "Order cancellation request sent successfully."})
        else:
            return Response({"message": "Failed to send order cancellation request."})
