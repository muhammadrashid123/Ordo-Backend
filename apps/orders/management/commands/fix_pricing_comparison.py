from functools import reduce
from operator import or_

import pandas as pd
from django.core.management import BaseCommand
from django.db.models import Prefetch, Q

from apps.common.utils import bulk_update
from apps.orders.models import Product


class Command(BaseCommand):
    """
    python manage.py import_products
    """

    help = "Fix patterson pricing mapping"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            help="The path to csv file containing product similarity",
        )
        parser.add_argument("--use_by", type=str, default="vendor_product_id")

    def fix_patterson(self, df):
        patterson_products = []
        for _, row in df.iterrows():
            vendor_products = row["vendor_products"].split(";")
            other_vendor_products = []
            patterson_product = None
            for vendor_product in vendor_products:
                vendor_slug = vendor_product.split("-")[0]
                product_id = vendor_product.split("-", 1)[1]
                if vendor_slug == "patterson":
                    product_id = f"0{product_id}"
                    patterson_product = Product.objects.filter(vendor__slug="patterson", product_id=product_id).first()
                else:
                    other_vendor_products.append((vendor_slug, product_id))

            if patterson_product:
                q = reduce(or_, [Q(vendor__slug=p[0]) & Q(product_id=p[1]) for p in other_vendor_products])
                sibling = Product.objects.filter(q).first()
                if sibling is None:
                    print("No Siblings")
                    print(other_vendor_products)
                else:
                    print("Has Siblings")
                    print(other_vendor_products)
                    patterson_product.parent = sibling.parent
                patterson_products.append(patterson_product)

        bulk_update(Product, patterson_products, fields=["parent"])

    def fix_names(self):
        products = Product.objects.prefetch_related(Prefetch("children", to_attr="childrens")).filter(
            vendor__isnull=True
        )

        products_to_updated = []
        for product in products:
            children_names = [p.name for p in product.childrens]
            if children_names and product.name not in children_names:
                product.name = sorted(children_names, key=lambda x: len(x))[0]
                products_to_updated.append(product)

        bulk_update(Product, products_to_updated, fields=["name"])

    def handle(self, *args, **options):
        print(f"reading {options['csv']}..")
        df = pd.read_csv(options["csv"])
        self.fix_patterson(df)
        self.fix_names(df)
