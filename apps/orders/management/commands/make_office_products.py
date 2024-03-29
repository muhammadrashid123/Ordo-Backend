from django.core.management import BaseCommand

from apps.accounts.models import Company
from apps.orders.models import OfficeProduct, OfficeProductCategory, Product


class Command(BaseCommand):
    help = "Group products"

    def handle(self, *args, **options):
        companies = Company.objects.filter(on_boarding_step=5)
        products = Product.objects.filter(vendor__slug__in=["purelife"])
        for company in companies:
            offices = company.offices.all()

            for office in offices:
                print(f"creating products for {office.name}")
                office_products = []
                office_product_categories = {}
                for product in products:
                    office_product_category = office_product_categories.get(product.category.slug)
                    if office_product_category is None:
                        office_product_category = OfficeProductCategory.objects.filter(
                            office=office, slug=product.category.slug
                        ).first()
                        office_product_categories[product.category.slug] = office_product_category

                    office_products.append(
                        OfficeProduct(
                            office=office,
                            product=product,
                            price=product.price,
                            office_category=product.category,
                            office_product_category=office_product_category,
                            vendor_id=product.vendor_id,
                        )
                    )

                OfficeProduct.objects.bulk_create(office_products, 500, ignore_conflicts=True)
                print(f"{office.name}: Created 500 products")
