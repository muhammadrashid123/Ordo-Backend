# flake8: noqa

from apps.accounts.models import Office, OfficeSetting
from apps.orders.models import (
    OfficeProduct,
    OfficeProductCategory,
    Product,
    ProductCategory,
)

# Change Other slug to Uncategorized
product_categories = ProductCategory.objects.filter(name="Dental Equipment Parts and Accessories")
for product_category in product_categories:
    product_category.name = "Dental Equipment Parts & Accessories"
    product_category.save()

office_product_categories = OfficeProductCategory.objects.filter(name="Dental Equipment Parts and Accessories")
for product_category in office_product_categories:
    product_category.name = "Dental Equipment Parts & Accessories"
    product_category.save()


products = Product.objects.filter(manufacturer_number__isnull=True, vendor__isnull=True)
for product in products:
    children_manufacturer_numbers = product.children.values_list("manufacturer_number", flat=True).distinct()
    if len(children_manufacturer_numbers) == 1 and children_manufacturer_numbers[0]:
        product.manufacturer_number = children_manufacturer_numbers[0]
        product.save()
    else:
        product.delete()

offices = Office.objects.all()
for office in offices:
    OfficeSetting.objects.create(office=office)
