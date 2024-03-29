import factory
from factory.django import DjangoModelFactory

from apps.accounts import models as account_models
from apps.accounts.factories import OfficeFactory
from apps.orders import models
from apps.orders.factories import ProductFactory


class OfficeProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = models.OfficeProductCategory

    office = factory.SubFactory(account_models.Office)
    name = factory.Faker("word")
    slug = factory.LazyAttribute(lambda o: o.name)
    predefined = False


class ProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = models.ProductCategory

    name = factory.Faker("word")


class OfficeProductFactory(DjangoModelFactory):
    class Meta:
        model = models.OfficeProduct

    office = factory.SubFactory(OfficeFactory)
    product = factory.SubFactory(ProductFactory)
    price = factory.Faker("pydecimal", min_value=1, max_value=100)
    office_category = factory.SubFactory(ProductCategoryFactory)
    office_product_category = factory.LazyAttribute(
        lambda o: OfficeProductCategoryFactory(office=o.office, name=o.office_category.name)
    )
    last_order_date = factory.Faker("date")
    last_order_price = factory.Faker("pydecimal", min_value=1, max_value=100)
    last_price_updated = factory.Faker("date_time")
