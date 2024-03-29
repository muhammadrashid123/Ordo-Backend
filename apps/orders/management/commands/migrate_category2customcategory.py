from django.core.management import BaseCommand

from apps.orders.models import OfficeProduct, OfficeProductCategory


class Command(BaseCommand):
    help = "Migrate from office_category to office_product_category"

    def handle(self, *args, **options):
        # TODO: this could be optimized using group_by and bulk_update
        office_products = OfficeProduct.objects.filter(office_product_category__isnull=True)
        for office_product in office_products:
            print(f"handling {office_product}")
            office_product_category = OfficeProductCategory.objects.filter(
                office=office_product.office, slug=office_product.office_category.slug
            ).first()
            office_product.office_product_category = office_product_category
            office_product.save()
