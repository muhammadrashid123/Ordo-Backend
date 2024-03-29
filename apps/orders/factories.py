from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.factories import OfficeFactory, VendorFactory

from ..common.choices import ProductStatus
from . import models as m


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = m.Product

    vendor = factory.SubFactory(VendorFactory)
    product_id = factory.Sequence(lambda n: f"test{n}")
    name = factory.Sequence(lambda n: f"Product {n}")
    price = factory.Faker("pydecimal", right_digits=2, min_value=Decimal("1.00"), max_value=Decimal("100.00"))


class OrderFactory(DjangoModelFactory):
    class Meta:
        model = m.Order

    office = factory.SubFactory(OfficeFactory)
    order_date = factory.LazyFunction(timezone.localtime)
    total_items = 0
    total_amount = Decimal(0)
    order_type = "Ordo Order"


class OrderProductFactory(DjangoModelFactory):
    class Meta:
        model = m.VendorOrderProduct


class VendorOrderFactory(DjangoModelFactory):
    class Meta:
        model = m.VendorOrder

    vendor = factory.SubFactory(VendorFactory)
    order = factory.SubFactory(OrderFactory)
    total_amount = 0
    total_items = 0
    order_date = factory.Faker("date")


class VendorOrderProductFactory(DjangoModelFactory):
    class Meta:
        model = m.VendorOrderProduct

    vendor_order = factory.SubFactory(VendorOrderFactory)
    product = factory.SubFactory(ProductFactory)
    quantity = 1
    unit_price = factory.LazyAttribute(lambda o: o.product.price)
    tracking_link = factory.Faker("url")
    tracking_number = factory.Faker("url")
    status = ProductStatus.PENDING_APPROVAL
    vendor_status = "NEW"
    rejected_reason = None


class ProcedureCodeFactory(DjangoModelFactory):
    class Meta:
        model = m.ProcedureCode


class ProcedureFactory(DjangoModelFactory):
    class Meta:
        model = m.Procedure


class ProcedureCategoryLinkFactory(DjangoModelFactory):
    class Meta:
        model = m.ProcedureCategoryLink
