import glob

from django.core.management import BaseCommand

from apps.accounts.helper import ShippingHelper
from apps.common.utils import get_file_name_and_ext


class Command(BaseCommand):
    """
    python manage.py import_shipping_options --directory shipping_options --vendors henry_schein --office 135
    """

    help = "Import shipping options from json files to table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            type=str,
            help="The path to directory contains shipping options",
            default="products",
        )
        parser.add_argument(
            "--vendors",
            type=str,
            help="Vendor ID",
        )
        parser.add_argument(
            "--office",
            type=str,
            help="Office ID",
        )
        parser.add_argument("--verbose", type=bool, help="debug mode", default=False)

    def load_shipping_options(self, directory, vendors, office=None):
        for file_name in sorted(glob.glob(f"{directory}/*.json")):
            print(f"Read shipping options from {file_name}")
            vendor, _ = get_file_name_and_ext(file_name)
            if vendors and vendor not in vendors:
                continue
            ShippingHelper.import_shipping_options_from_json(file_path=file_name, vendor_slug=vendor, office_id=office)

    def handle(self, *args, **options):
        vendors = options["vendors"]
        if vendors:
            vendors = vendors.split(",")
        else:
            vendors = []
        self.load_shipping_options(options["directory"], vendors, options["office"])
