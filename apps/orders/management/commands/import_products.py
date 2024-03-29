import glob

from django.core.management import BaseCommand

from apps.common.utils import get_file_name_and_ext
from apps.orders.helpers import ProductHelper


class Command(BaseCommand):
    """
    python manage.py import_products --vendors henry_schein --fields manufacturer_number
    """

    help = "Import products from csv files to table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            type=str,
            help="The path to directory contains product csv files",
            default="products",
        )
        parser.add_argument(
            "--fields",
            type=str,
            help="list of fields that should be updated",
        )
        parser.add_argument(
            "--vendors",
            type=str,
            help="import products from vendors",
        )
        parser.add_argument("--product-id", type=str, help="Product ID field to use", default="product_id")
        parser.add_argument("--verbose", action="store_true", help="debug mode")

    def load_products(self, directory, vendors, fields=None, verbose=False, product_id_field="product_id"):
        for file_name in sorted(glob.glob(f"{directory}/*.csv")):
            print(f"Read product data from {file_name}")
            vendor, _ = get_file_name_and_ext(file_name)
            if vendors and vendor not in vendors:
                continue
            ProductHelper.import_products_from_csv_v2(
                file_path=file_name,
                vendor_slug=vendor,
                fields=fields,
                verbose=verbose,
                product_id_field=product_id_field,
            )

    def handle(self, *args, **options):
        vendors = options["vendors"]
        if vendors:
            vendors = vendors.split(",")
        else:
            vendors = []

        fields = options["fields"]
        if fields:
            fields = fields.split(",")
        else:
            fields = []
        self.load_products(options["directory"], vendors, fields, options["verbose"], options["product_id"])
