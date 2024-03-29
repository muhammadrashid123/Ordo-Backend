import pandas as pd
from django.core.management import BaseCommand
from django.db.models import Q
from pandas import DataFrame

from apps.common.utils import bulk_update
from apps.orders.models import Product


class Command(BaseCommand):
    """
    python manage.py import_products
    """

    help = "Import products from csv files to table"
    MAPPINGS = {
        "henry schien": "henry_schein",
        "benco": "benco",
        "darby": "darby",
        "net32": "net_32",
        "patterson": "patterson",
        "dental city": "dental_city",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            help="The path to csv file containing product similarity",
        )
        parser.add_argument(
            "--commit",
            type=int,
            default=0,
        )

    def show_all_mentioned_vendors(self, df: DataFrame):
        vendors = set()
        all_vendors = list(pd.unique(df[df.columns[1::2]].values.ravel("K")))
        for vendors_str in all_vendors:
            if not isinstance(vendors_str, str):
                continue
            vendors_ = list(map(str.strip, vendors_str.split(",")))
            vendors.update(vendors_)
        return vendors

    def handle(self, *args, **options):
        df = pd.read_csv(options["csv"])
        vendors = self.show_all_mentioned_vendors(df)
        print(f"All mentioned vendors in csv are {', '.join(vendors)}")

        error_rows = []
        success_rows = []
        total_rows = 0
        for row_index, row in df.iterrows():
            total_rows += 1
            parent_products = []
            products = []
            for i in range(0, len(row), 2):
                if not isinstance(row[i], str):
                    continue
                product_name = row[i].strip()
                vendor_names = row[i + 1]
                vendor_names = [self.MAPPINGS[vendor_name.strip().lower()] for vendor_name in vendor_names.split(",")]
                if len(vendor_names) == 1:
                    product = Product.objects.filter(Q(name__icontains=product_name) & Q(vendor__slug=vendor_names[0]))
                    products_count = product.count()
                    if products_count > 1:
                        error_rows.append(row_index)
                        print(f"ERROR: DUPLICATES   ({row_index}, {i}): {vendor_names[0]} - {product_name}")
                        break
                    elif products_count == 0:
                        error_rows.append(row_index)
                        print(f"ERROR: NOT FOUND ({row_index}, {i}): {vendor_names[0]} - {product_name}")
                        break
                    products.append(product.first())
                else:
                    product = Product.objects.filter(
                        name__icontains=product_name,
                        vendor__slug__in=vendor_names,
                    )

                    products_count = product.count()
                    if products_count > 1:
                        error_rows.append(row_index)
                        print(f"ERROR: DUPLICATES ({row_index}, {i}): {vendor_names} {product_name}")
                        break
                    elif products_count == 0:
                        error_rows.append(row_index)
                        print(f"ERROR: NOT FOUND ({row_index}, {i}): {vendor_names} {product_name}")
                        break
                    parent_product = product.first().parent
                    children_products_vendors = set(parent_product.children.values_list("vendor__slug", flat=True))
                    if children_products_vendors != set(vendor_names):
                        error_rows.append(row_index)
                        print(f"ERROR: Double Check ({row_index}, {i}): {vendor_names} {product_name}")
                        break

                    parent_products.append(parent_product)

            if len(parent_products) > 1:
                error_rows.append(row_index)
                print("ERROR: More than 2 parent products exist")
                break

            product_categories = [product.category.slug for product in products]
            parent_product_categories = [parent_product.category.slug for parent_product in parent_products]
            categories = set(product_categories) | set(parent_product_categories)
            if len(categories) > 1:
                print(f"WARNING: {row_index} Mismatching categories: ")
                display_text = [
                    f"{product.name}({product.vendor.slug}) has {product.category.slug}" for product in products
                ]
                print("; ".join(display_text))

            if options["commit"]:
                success_rows.append(row_index)
                if len(parent_products) == 1:
                    parent_product = parent_products[0]
                elif len(parent_products) == 0:
                    parent_product = Product.objects.create(
                        name=products[0].name,
                        category=products[0].category,
                    )

                for product in products:
                    product.parent = parent_product

                bulk_update(Product, products, fields=["parent"])

        print(f"Total {total_rows}...")
        print(f"Succeeded {len(success_rows)}")
        print(success_rows)
        print(f"Errors {len(error_rows)}")
        print(error_rows)
