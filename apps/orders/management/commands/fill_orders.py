from django.core.management import BaseCommand

from apps.orders.models import Order


class Command(BaseCommand):
    def handle(self, *args, **options):
        orders = Order.objects.all()
        for order in orders:
            vendor_orders = order.vendor_orders.all()
            order.order_date = vendor_orders.first().order_date
            order.total_items = sum([vendor_order.total_items for vendor_order in vendor_orders])
            order.total_amount = sum([vendor_order.total_amount for vendor_order in vendor_orders])
            order.save()
