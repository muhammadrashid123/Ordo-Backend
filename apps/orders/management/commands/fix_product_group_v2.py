from collections import defaultdict

from django.contrib.postgres.search import TrigramSimilarity
from django.core.management import BaseCommand
from django.db.models import Prefetch, Sum

from apps.common.utils import bulk_update
from apps.orders.models import Product


class Command(BaseCommand):
    help = "Clean Product grouping; this is "

    def add_arguments(self, parser):
        parser.add_argument(
            "--db_commit",
            type=bool,
            default=False,
        )

    def handle(self, *args, **options):
        parent_products = (
            Product.objects.prefetch_related(Prefetch("children", to_attr="childrens"))
            .filter(vendor__isnull=True, manufacturer_number__isnull=False)
            .order_by("id")
        )

        products_to_be_updated = []
        for parent_product in parent_products:
            product_by_vendors = defaultdict(list)
            for product in parent_product.childrens:
                product_by_vendors[product.vendor.id].append(product)
            product_by_vendors = {k: v for k, v in product_by_vendors.items() if len(v) >= 2}
            for vendor, products in product_by_vendors.items():
                similarities = {}
                product_ids = [product.id for product in products]
                for product in products:
                    similarities[product.id] = (
                        parent_product.children.exclude(id__in=product_ids)
                        .annotate(similarity=TrigramSimilarity("name", product.name))
                        .aggregate(Sum("similarity"))["similarity__sum"]
                    )

                top_product_id = max(similarities, key=similarities.get)
                other_products = set(similarities.keys())
                other_products.remove(top_product_id)

                for product in products:
                    if product.id == top_product_id:
                        continue
                    product.parent = None
                    products_to_be_updated.append(product)
                    print(product.id, product.name)
            else:
                print("=" * 100)

        if options["db_commit"]:
            bulk_update(model_class=Product, objs=products_to_be_updated, fields=["parent"])
