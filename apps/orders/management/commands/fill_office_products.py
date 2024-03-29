import datetime

from django.core.management import BaseCommand
from django.core.paginator import Paginator

from apps.accounts.models import Office, Vendor
from apps.orders.models import OfficeProduct, Product
from config.constants import FORMULA_VENDORS


class Command(BaseCommand):
    help = "Move products to Office Products Table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--office",
            type=int,
            help="office id",
        )
        parser.add_argument(
            "--vendor",
            type=str,
            help="vendor slug",
        )

    def handle(self, *args, **options):
        vendor_slug = options["vendor"]
        office_id = options["office"]
        batch_size = 1000

        # Move products from formular vendors only
        if vendor_slug not in FORMULA_VENDORS:
            return None

        if not Office.objects.filter(id=office_id).exists():
            return None

        vendor = Vendor.objects.filter(slug=vendor_slug).first()
        if vendor is None:
            return None

        queryset = Product.objects.filter(vendor=vendor).order_by("-created_at")
        paginator = Paginator(queryset, batch_size)
        for page_number in paginator.page_range:
            page = paginator.page(page_number)
            office_products = [
                OfficeProduct(
                    office_id=office_id,
                    product_id=vendor_product.id,
                    vendor=vendor,
                    office_category=vendor_product.category,
                    price_expiration=(
                        vendor_product.price_expiration
                        if vendor_product.price_expiration
                        else vendor_product.created_at - datetime.timedelta(days=20)  # 20days ago temporary
                    ),
                )
                for vendor_product in page.object_list
            ]
            OfficeProduct.objects.bulk_create(office_products, ignore_conflicts=True)
