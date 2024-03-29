from django.core.management import BaseCommand

from apps.orders.services.product import ProductService


class Command(BaseCommand):
    help = "Group products"

    def handle(self, *args, **options):
        ProductService.group_products()
