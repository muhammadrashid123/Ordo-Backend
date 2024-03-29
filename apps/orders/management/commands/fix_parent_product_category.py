from collections import Counter

from django.core.management import BaseCommand
from django.db.models import Prefetch

from apps.common.utils import bulk_update
from apps.orders.models import Product


class Command(BaseCommand):
    help = "Fill missing parent product category with children's one"

    def handle(self, *args, **options):
        parent_products = Product.objects.prefetch_related(Prefetch("children", to_attr="childrens")).filter(
            vendor__isnull=True, category__isnull=True
        )
        parent_products_to_be_updated = []
        parent_products_to_be_deleted = []
        for parent_product in parent_products:
            children_categories = parent_product.children.values_list("category", flat=True)
            if not children_categories:
                parent_products_to_be_deleted.append(parent_product.id)
                continue
            counter = Counter(list(children_categories))
            parent_product.category_id = counter.most_common(1)[0][0]
            parent_products_to_be_updated.append(parent_product)

        print(f"Updated {len(parent_products_to_be_updated)} products...")
        bulk_update(model_class=Product, objs=parent_products_to_be_updated, fields=["category"])

        print(f"Deleted {len(parent_products_to_be_deleted)} products...")
        Product.objects.filter(id__in=parent_products_to_be_deleted).delete()
