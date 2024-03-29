from django.core.management import BaseCommand

from apps.orders.helpers import ProductHelper


class Command(BaseCommand):
    """
    python manage.py import_products
    """

    help = "Import products from csv files to table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            help="The path to csv file containing product similarity",
        )
        parser.add_argument("--use_by", type=str, default="vendor_product_id")

    def handle(self, *args, **options):
        ProductHelper.import_products_similarity(file_name=options["csv"], use_by=options["use_by"])
