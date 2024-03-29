from django.core.management import BaseCommand

from apps.orders.models import (
    OrderStatus,
    ProductStatus,
    VendorOrder,
    VendorOrderProduct,
)


class Command(BaseCommand):
    def normalize_order_status(self, order_status):
        order_status = order_status.lower()
        if any(
            status in order_status
            for status in ("delivered", "shipped", "complete", "order shipped", "cancelled", "closed")
        ):
            return "closed"
        elif any([status in order_status for status in ("open", "in progress", "processing", "pending")]):
            return "open"
        else:
            return order_status

    def normalize_order_product_status(self, order_product_status):
        order_product_status = order_product_status.lower()

        if any(status in order_product_status for status in ("processing", "pending", "open")):
            return "processing"
        elif any([status in order_product_status for status in ("backordered",)]):
            return "backordered"
        elif any([status in order_product_status for status in ("returned",)]):
            return "returned"
        elif any([status in order_product_status for status in ("cancelled",)]):
            return "cancelled"
        elif any([status in order_product_status for status in ("received", "complete", "shipped")]):
            return "received"
        else:
            return order_product_status

    def handle(self, *args, **options):
        vendor_orders = VendorOrder.objects.exclude(status__in=[c[0] for c in OrderStatus.choices])
        objs = []
        for vendor_order in vendor_orders:
            vendor_order.status = self.normalize_order_status(vendor_order.status)
            objs.append(vendor_order)

        if objs:
            VendorOrder.objects.bulk_update(objs, fields=["status"])

        vendor_order_products = VendorOrderProduct.objects.exclude(status__in=[c[0] for c in ProductStatus.choices])
        objs = []
        for vendor_order_product in vendor_order_products:
            vendor_order_product.status = self.normalize_order_product_status(vendor_order_product.status)
            objs.append(vendor_order_product)

        if objs:
            VendorOrderProduct.objects.bulk_update(objs, fields=["status"])
