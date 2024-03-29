import asyncio
import logging

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.viewsets import ModelViewSet

from apps.accounts import models as m
from apps.accounts import serializers as s
from apps.accounts import tasks as accounts_tasks
from apps.common import messages as msgs
from apps.common.asyncdrf import AsyncMixin
from apps.common.enums import OnboardingStep
from apps.orders.helpers import OrderHelper
from apps.scrapers.errors import (
    NetworkConnectionException,
    VendorAuthenticationFailed,
    VendorNotSupported,
)
from django.db.models import Prefetch
from apps.accounts.tasks import notyify_for_unlinked_vendor
from rest_framework import status
logger = logging.getLogger(__name__)


class OfficeVendorViewSet(AsyncMixin, ModelViewSet):
    serializer_class = s.OfficeVendorListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = m.OfficeVendor.objects.filter(office_id=self.kwargs["office_pk"])
        if self.action == "list":
            return queryset.select_related("vendor", "default_shipping_option").prefetch_related(
                Prefetch('shipping_options', queryset=m.ShippingMethod.objects.order_by('id')))
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        notyify_for_unlinked_vendor(office_name=instance.office.name,vendor_name=instance.vendor.name,
                                    reason=f"{self.request.user.username} has unlinked the vendor.")
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_serializer_class(self):
        if self.request.method in ["POST"]:
            return s.OfficeVendorSerializer
        return s.OfficeVendorListSerializer

    @sync_to_async
    def _validate(self, data):
        office = get_object_or_404(m.Office, id=data["office"])
        company = office.company
        if company.on_boarding_step < OnboardingStep.BILLING_INFORMATION:
            raise ValidationError({"message": msgs.VENDOR_IMPOSSIBLE_LINK})
        company.on_boarding_step = OnboardingStep.LINK_VENDOR
        company.save()

        serializer = s.OfficeVendorSerializer(data=data)
        serializer.is_valid()
        return serializer

    @sync_to_async
    def serializer_data(self, serializer):
        return serializer.data

    @sync_to_async
    def check_vendor_exists(self, username, vendor_id):
        return m.OfficeVendor.objects.filter(username=username, vendor=vendor_id).exists()

    @sync_to_async()
    def relink_failed(self, email, vendor, message):
        cache_key = str(vendor)
        existing_data = cache.get(cache_key, {})
        existing_data.setdefault(email, {"email": email, "vendor_id": vendor, "count": 0})

        existing_data[email]["count"] += 1

        if existing_data[email]["count"] == 3:
            accounts_tasks.send_third_timer_relink_mail.delay(email, message, vendor)
            cache.delete(cache_key)
        else:
            cache.set(cache_key, existing_data, timeout=None)
        # existing_data = cache.get(vendor, {})
        # if email in existing_data:
        #     # If it exists, update the count variable
        #     existing_data[email]['count'] += 1
        # else:
        #     existing_data[email] = {
        #         'email': email,
        #         'vendor_id': vendor,
        #         'count': 1
        #     }
        #
        # if existing_data[email]['count'] == 3:
        #     accounts_tasks.send_third_timer_relink_mail.delay(email, message, vendor)
        #     cache.delete(vendor)
        #
        # else:
        #     cache.set(vendor, existing_data, timeout=None)

    async def create(self, request, *args, **kwargs):
        offices = request.data["offices"]

        if not offices:
            return Response({"message": "Select Offices "}, status=HTTP_400_BAD_REQUEST)

        serializer = await self._validate({**request.data, "office": offices[0]})
        for office in offices:
            serializer = await self._validate({**request.data, "office": office})
            office_vendor = None
            try:
                if (
                    serializer.validated_data["vendor"].slug != "amazon"
                    and serializer.validated_data["vendor"].slug != "ebay"
                ):
                    office_vendor = await sync_to_async(serializer.save)()
                    # login_cookies = await scraper.login()

                    # All scrapers work with login_cookies,
                    # but henryschein doesn't work with login_cookies...
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, accounts_tasks.link_vendor, office_vendor.vendor.slug, office_vendor.office_id
                    )

                else:
                    await sync_to_async(serializer.save)()

            except VendorNotSupported:
                await self.relink_failed(
                    request.user.email, request.data["vendor"], msgs.VENDOR_SCRAPER_IMPROPERLY_CONFIGURED
                )
                return Response(
                    {
                        "message": msgs.VENDOR_SCRAPER_IMPROPERLY_CONFIGURED,
                    },
                    status=HTTP_400_BAD_REQUEST,
                )
            except VendorAuthenticationFailed:
                if office_vendor:
                    await sync_to_async(office_vendor.delete)()
                await self.relink_failed(request.user.email, request.data["vendor"], msgs.VENDOR_WRONG_INFORMATION)
                return Response({"message": msgs.VENDOR_WRONG_INFORMATION}, status=HTTP_400_BAD_REQUEST)
            except NetworkConnectionException:
                if office_vendor:
                    await sync_to_async(office_vendor.delete)()
                await self.relink_failed(
                    request.user.email, request.data["vendor"], msgs.VENDOR_BAD_NETWORK_CONNECTION
                )
                return Response({"message": msgs.VENDOR_BAD_NETWORK_CONNECTION}, status=HTTP_400_BAD_REQUEST)
            except Exception as e:  # noqa
                logger.debug(e)
                if office_vendor:
                    await sync_to_async(office_vendor.delete)()
                await self.relink_failed(request.user.email, request.data["vendor"], msgs.UNKNOWN_ISSUE)
                return Response({"message": msgs.UNKNOWN_ISSUE, **serializer.data}, status=HTTP_400_BAD_REQUEST)

        data = await self.serializer_data(serializer)
        return Response({"message": msgs.VENDOR_CONNECTED, **data})

    @action(detail=True, methods=["post"])
    def relink_office_vendor(self, request, *args, **kwargs):
        logger.info("Starting relink...")
        office_vendor = self.get_object()
        if "username" in request.data:
            office_vendor.username = request.data["username"]
        if "password" in request.data:
            office_vendor.password = request.data["password"]
        office_vendor.save()
        res = asyncio.run(OrderHelper.login_vendor(office_vendor, office_vendor.vendor))
        if res:
            logger.info("Updating the login status...")
            office_vendor.login_success = True
            office_vendor.save()
            accounts_tasks.fetch_order_history.delay(
                vendor_slug=office_vendor.vendor.slug,
                office_id=office_vendor.office.id,
            )
            return Response({"message": "The vendor is successfully relinked!"})
        return Response({"message": "The credential is incorrect!"}, status=HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"], url_path="fetch-prices")
    def fetch_product_prices(self, request, *args, **kwargs):
        instance = self.get_object()
        accounts_tasks.fetch_vendor_products_prices.delay(office_vendor_id=instance.id)
        return Response(s.OfficeVendorSerializer(instance).data)

    @action(detail=True, methods=["post"], url_path="fetch")
    def fetch_orders(self, request, *args, **kwargs):
        instance = self.get_object()
        accounts_tasks.fetch_order_history.delay(vendor_slug=instance.vendor.slug, office_id=instance.office.id)
        return Response(s.OfficeVendorSerializer(instance).data)
