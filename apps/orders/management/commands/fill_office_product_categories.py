from itertools import islice

from django.core.management import BaseCommand

from apps.accounts.models import Office
from apps.orders.models import OfficeProductCategory, ProductCategory


class Command(BaseCommand):
    help = "Populate office category "

    def add_arguments(self, parser):
        """
        python manage.py fill_office_product_categories
        """
        parser.add_argument(
            "--office_ids",
            type=int,
            help="The list of office ids",
        )

    def load_product_categories(self):
        self.product_categories = ProductCategory.objects.all()

    def fill_office_product_category(self, office):
        office_product_categories = (
            OfficeProductCategory(
                office=office,
                name=product_category.name,
                slug=product_category.slug,
            )
            for product_category in self.product_categories
        )
        OfficeProductCategory.objects.bulk_create(office_product_categories, ignore_conflicts=True)

    def fill_offices_product_category(self, offices):
        office_product_categories = (
            OfficeProductCategory(
                office=office,
                name=product_category.name,
                slug=product_category.slug,
            )
            for office in offices
            for product_category in self.product_categories
        )
        batch_size = 500
        while True:
            batch = list(islice(office_product_categories, batch_size))
            if not batch:
                break
            OfficeProductCategory.objects.bulk_create(batch, batch_size, ignore_conflicts=True)

    def handle(self, *args, **options):
        if options["office_ids"]:
            offices = Office.objects.filter(id__in=options["office_ids"])
        else:
            offices = Office.objects.all()
        self.load_product_categories()
        self.fill_offices_product_category(offices)
