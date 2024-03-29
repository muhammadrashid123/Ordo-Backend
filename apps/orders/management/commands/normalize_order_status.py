from django.core.management import BaseCommand
from django.db.models import Q

from apps.orders.models import Order, OrderStatus, VendorOrder


class Command(BaseCommand):
    def normalize_order_status(self, model_class):
        orders = model_class.objects.filter(Q(status__iexact="pending") | Q(status__iexact="processing"))
        for order in orders:
            order.status = OrderStatus.OPEN
        model_class.objects.bulk_update(orders, fields=["status"])

        orders = model_class.objects.filter(Q(status__iexact="complete") | Q(status__iexact="shipped"))
        for order in orders:
            order.status = OrderStatus.CLOSED
        model_class.objects.bulk_update(orders, fields=["status"])

    def handle(self, *args, **options):
        order_statuses = set(Order.objects.values_list("status", flat=True))
        if not order_statuses.issubset({c[0] for c in OrderStatus.choices}):
            self.normalize_order_status(Order)

        vendor_order_statuses = set(VendorOrder.objects.values_list("status", flat=True))
        if not vendor_order_statuses.issubset({c[0] for c in OrderStatus.choices}):
            orders = VendorOrder.objects.all()
            for order in orders:
                order.vendor_status = order.status
            VendorOrder.objects.bulk_update(orders, fields=["vendor_status"])

        self.normalize_order_status(VendorOrder)
