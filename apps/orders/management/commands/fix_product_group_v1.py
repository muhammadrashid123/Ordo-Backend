from collections import Counter

from django.contrib.postgres.search import TrigramSimilarity
from django.core.management import BaseCommand
from django.db.models import Prefetch

from apps.common.utils import bulk_update
from apps.orders.helpers import ParentProduct, ProductHelper
from apps.orders.models import Product


class Command(BaseCommand):
    help = "Clean Product grouping; this is "

    def handle(self, *args, **options):
        similarity_threshold = 0.15
        parent_products = (
            Product.objects.prefetch_related(Prefetch("children", to_attr="childrens"))
            .filter(vendor__isnull=True, manufacturer_number__isnull=False)
            .order_by("id")
        )

        total_mismatches = 0
        parent_products_to_be_created = []
        products_to_be_updated = []
        for parent_product in parent_products:
            vendors = [product.vendor for product in parent_product.childrens]
            vendors = Counter(vendors).most_common(1)
            if vendors[0][1] == 1:
                continue

            print(f"Regrouping {total_mismatches}th {parent_product.id}...")
            product_ids = set(product.id for product in parent_product.childrens)
            while product_ids:
                product = parent_product.children.filter(id__in=product_ids).first()
                similar_products = parent_product.children.annotate(
                    similarity=TrigramSimilarity("name", product.name)
                ).filter(
                    similarity__gt=similarity_threshold,
                    manufacturer_number=product.manufacturer_number,
                    id__in=product_ids,
                )
                children_products = list(similar_products.values("id", "url"))
                children_ids = [p["id"] for p in children_products]
                print(f"Sub group products are {', '.join(map(str, children_ids))}")
                for children_product in children_products:
                    print(f'\t {children_product["id"]}: {children_product["url"]}')

                if len(children_ids) > 1:
                    parent_products_to_be_created.append(
                        ParentProduct(
                            product=Product(
                                name=product.name,
                                category=product.category,
                                manufacturer_number=product.manufacturer_number,
                            ),
                            children_ids=children_ids,
                        )
                    )
                else:
                    product.parent = None
                    products_to_be_updated.append(product)

                product_ids = product_ids - set(children_ids)

            print("=" * 100)
            parent_product.delete()
            total_mismatches += 1

        print(f"Total regroup products: {total_mismatches}...")
        if products_to_be_updated:
            bulk_update(model_class=Product, objs=products_to_be_updated, fields=["parent"])

        if parent_products_to_be_created:
            ProductHelper.create_parent_products(parent_products_to_be_created)
