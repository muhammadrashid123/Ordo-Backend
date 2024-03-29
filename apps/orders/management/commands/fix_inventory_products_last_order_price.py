from django.core.management import BaseCommand

from apps.common.utils import bulk_update
from apps.orders.models import OfficeProduct, VendorOrderProduct


class Command(BaseCommand):
    def handle(self, *args, **options):
        office_products_to_be_updated = []
        office_products = OfficeProduct.objects.filter(product__vendor__isnull=False, is_inventory=True)
        for office_product in office_products:
            vendor_order_products = (
                VendorOrderProduct.objects.select_related(
                    "vendor_order",
                )
                .filter(
                    product=office_product.product,
                    vendor_order__order__office=office_product.office,
                )
                .order_by("-vendor_order__order_date")
                .values("vendor_order__order_date", "unit_price")
            )
            if not vendor_order_products:
                continue
            last_order_date = vendor_order_products[0]["vendor_order__order_date"]
            last_order_price = vendor_order_products[0]["unit_price"]
            update_list = False
            if office_product.last_order_date is None or office_product.last_order_date < last_order_date:
                office_product.last_order_date = vendor_order_products[0]["vendor_order__order_date"]
                update_list = True

            if office_product.last_order_price is None:
                office_product.last_order_price = last_order_price
                update_list = True

            if update_list:
                office_products_to_be_updated.append(office_product)

        bulk_update(OfficeProduct, office_products_to_be_updated, fields=["last_order_date", "last_order_price"])
        print(f"{len(office_products_to_be_updated)} products updated")
