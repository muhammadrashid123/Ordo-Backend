from django.core.management import BaseCommand

from apps.orders.models import OfficeProduct, VendorOrderProduct


class Command(BaseCommand):
    help = "Fetch Ultradent products and store them into a table"

    def handle(self, *args, **options):
        product_ids = VendorOrderProduct.objects.values_list(
            "vendor_order__order__office", "product", "vendor_order__vendor_id"
        )
        for office_id, product_id, vendor_id in product_ids:
            obj, created = OfficeProduct.objects.update_or_create(
                office_id=office_id,
                product_id=product_id,
                defaults={
                    "is_inventory": True,
                    "vendor_id": vendor_id,
                },
            )
            print(f"{obj} is {'created' if created else 'updated'}")
