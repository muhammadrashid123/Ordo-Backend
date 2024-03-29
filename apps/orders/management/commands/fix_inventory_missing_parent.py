from collections import defaultdict

from django.core.management import BaseCommand

from apps.common.utils import bulk_create
from apps.orders.models import OfficeProduct, OfficeProductCategory


class Command(BaseCommand):
    help = "Fix inventory missing product"

    def handle(self, *args, **options):
        inventory_parent_products = (
            OfficeProduct.objects.filter(is_inventory=True, product__parent__isnull=False)
            .values("office", "product__parent_id", "product__parent__category__slug")
            .distinct()
        )
        inventory_parent_products_by_office = defaultdict(list)
        for inventory_parent_product in inventory_parent_products:
            inventory_parent_products_by_office[inventory_parent_product["office"]].append(
                (
                    inventory_parent_product["product__parent_id"],
                    inventory_parent_product["product__parent__category__slug"],
                )
            )

        office_products = []
        for office_id, inventory_products in inventory_parent_products_by_office.items():
            office_product_category_mapper = OfficeProductCategory.office_product_categories_mapper(office_id)
            inventory_products = {
                inventory_product[0]: inventory_product[1] for inventory_product in inventory_products
            }
            inventory_product_ids = set(inventory_products.keys())
            product_ids = set(
                OfficeProduct.objects.filter(product_id__in=inventory_products).values_list("product_id", flat=True)
            )
            missing_product_ids = inventory_product_ids - product_ids
            for missing_product_id in missing_product_ids:
                office_products.append(
                    OfficeProduct(
                        office_id=office_id,
                        product_id=missing_product_id,
                        is_inventory=True,
                        office_product_category_id=office_product_category_mapper[
                            inventory_products[missing_product_id]
                        ],
                    )
                )

        bulk_create(model_class=OfficeProduct, objs=office_products)
