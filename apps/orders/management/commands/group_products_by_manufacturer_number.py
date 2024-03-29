import datetime

from django.core.management import BaseCommand

from apps.orders.helpers import ProductHelper


class Command(BaseCommand):
    help = "Group products"

    def add_arguments(self, parser):
        """
        python manage.py group_products_by_manufacturer_number --vendor 14 --since 2022-04-12T11:50:29.751119+00:00
        """
        parser.add_argument(
            "--since",
            help="iso format of time",
        )

        parser.add_argument(
            "--vendor",
            type=str,
            help="vendor id to group",
        )

    def handle(self, *args, **options):
        since = datetime.datetime.fromisoformat(options["since"]) if options["since"] else None
        vendor_id = int(options["vendor"]) if options["vendor"] else -1
        ProductHelper.group_products_by_manufacturer_numbers(since, vendor_id)
