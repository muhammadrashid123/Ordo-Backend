from decimal import Decimal

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.accounts.helper import BudgetwiseSpend, OfficeBudgetHelper
from apps.accounts.models import OfficeVendor
from apps.common.choices import ProductStatus
from apps.common.month import Month
from apps.orders.helpers import OrderHelper
from apps.orders.models import OrderStatus, VendorOrder, VendorOrderProduct
from apps.orders.tasks import notify_order_creation, perform_real_order
from config.utils import get_client_session


class OrderService:
    @staticmethod
    def is_debug_mode(stage):
        return "localhost" in stage or "127.0.0.1" in stage

    @staticmethod
    def is_force_redundancy():
        return True

    @sync_to_async
    def get_office_vendor(self, vendor_order) -> OfficeVendor:
        return (
            OfficeVendor.objects.select_related("vendor")
            .filter(office=vendor_order.order.office, vendor=vendor_order.vendor)
            .first()
        )

    @sync_to_async
    def get_vendor_order_products(self, vendor_order, validated_data):
        rejected_items = {
            str(rejected_item["order_product_id"]): rejected_item["rejected_reason"]
            for rejected_item in validated_data.get("rejected_items", [])
        }
        vendor_order_products = VendorOrderProduct.objects.select_related("product").filter(vendor_order=vendor_order)
        approved_vendor_order_products = []

        for vendor_order_product in vendor_order_products:
            if str(vendor_order_product.id) in rejected_items:
                vendor_order_product.rejected_reason = rejected_items[str(vendor_order_product.id)]
                vendor_order_product.status = ProductStatus.REJECTED
            else:
                vendor_order_product.status = ProductStatus.PROCESSING
                approved_vendor_order_products.append(vendor_order_product)

        VendorOrderProduct.objects.bulk_update(vendor_order_products, fields=["rejected_reason", "status"])

        return approved_vendor_order_products

    @staticmethod
    async def approve_vendor_order(approved_by, vendor_order: VendorOrder, validated_data, stage: str):
        session = await get_client_session()
        products = await OrderService.get_vendor_order_products(vendor_order, validated_data)

        if products:
            perform_real_order.delay([vendor_order.id])
            vendor_order.status = OrderStatus.OPEN
        else:
            vendor_order.status = OrderStatus.CLOSED

        vendor_order.order_date = timezone.localtime()
        vendor_order.approved_at = timezone.localtime()
        vendor_order.approved_by = approved_by
        await sync_to_async(vendor_order.save)()

        if products:
            # TODO: this logics should be refactored
            notify_order_creation.delay([vendor_order.id], approval_needed=False)

        if session:
            await session.close()

    @staticmethod
    def reject_vendor_order(approved_by, vendor_order: VendorOrder, validated_data):
        with transaction.atomic():
            vendor_order.status = OrderStatus.CLOSED
            vendor_order.approved_at = timezone.localtime()
            vendor_order.approved_by = approved_by
            vendor_order.rejected_reason = validated_data["rejected_reason"]
            vendor_order.save()

            vendor_order_products = vendor_order.order_products.all()
            for vendor_order_product in vendor_order_products:
                vendor_order_product.status = ProductStatus.REJECTED
                vendor_order_product.rejected_reason = VendorOrderProduct.RejectReason.NOT_NEEDED

            VendorOrderProduct.objects.bulk_update(vendor_order_products, ["rejected_reason", "status"])
            OrderHelper.update_vendor_order_totals(vendor_order)

    @staticmethod
    def update_vendor_order_spent(vendor_order: VendorOrder, validated_data):
        office = vendor_order.order.office
        order_date = vendor_order.order_date
        order_month = Month(year=order_date.year, month=order_date.month)
        budgetwise_spend = BudgetwiseSpend()
        default_budget_spend_type = OfficeBudgetHelper.get_default_budget_type_by_vendor(vendor_order.vendor.slug)

        products = async_to_sync(OrderService.get_vendor_order_products)(vendor_order, validated_data)
        if products:
            for vendor_order_product in products:
                budget_spend_type = vendor_order_product.budget_spend_type
                if not budget_spend_type:
                    budget_spend_type = default_budget_spend_type
                budgetwise_spend[budget_spend_type] += Decimal(
                    vendor_order_product.quantity * vendor_order_product.unit_price
                )
        else:
            budget = OfficeBudgetHelper.get_or_create_budget(
                vendor_order.order.office_id, Month.from_date(vendor_order.order_date)
            )
            slug_mapping = OfficeBudgetHelper.get_slug_mapping(budget)
            budget_spend_type = slug_mapping[vendor_order.vendor.slug]
            budgetwise_spend[budget_spend_type] = vendor_order.total_amount

        OfficeBudgetHelper.adjust_spends(office.id, order_month, budgetwise_spend)
