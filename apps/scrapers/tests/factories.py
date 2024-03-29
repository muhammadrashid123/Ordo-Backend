import datetime

import factory
from factory import fuzzy

from apps.types.scraper import (
    InvoiceAddress,
    InvoiceInfo,
    InvoiceOrderDetail,
    InvoiceProduct,
    InvoiceVendorInfo,
)


class InvoiceAddressFactory(factory.Factory):
    class Meta:
        model = InvoiceAddress

    shipping_address = fuzzy.FuzzyText()
    billing_address = fuzzy.FuzzyText()


class InvoiceVendorInfoFactory(factory.Factory):
    class Meta:
        model = InvoiceVendorInfo

    name = fuzzy.FuzzyText()
    logo = fuzzy.FuzzyText()


class InvoiceOrderDetailFactory(factory.Factory):
    class Meta:
        model = InvoiceOrderDetail

    order_id = fuzzy.FuzzyText()
    order_date = fuzzy.FuzzyDate(start_date=datetime.date.today())
    payment_method = fuzzy.FuzzyText()
    total_items = fuzzy.FuzzyInteger(low=1)
    sub_total_amount = fuzzy.FuzzyDecimal(low=0)
    shipping_amount = fuzzy.FuzzyDecimal(low=0)
    tax_amount = fuzzy.FuzzyDecimal(low=0)
    total_amount = fuzzy.FuzzyDecimal(low=0)


class InvoiceProductFactory(factory.Factory):
    class Meta:
        model = InvoiceProduct

    product_url = fuzzy.FuzzyText()
    product_name = fuzzy.FuzzyText()
    quantity = fuzzy.FuzzyInteger(low=0)
    unit_price = fuzzy.FuzzyDecimal(low=0)


class InvoiceInfoFactory(factory.Factory):
    class Meta:
        model = InvoiceInfo

    address = factory.SubFactory(InvoiceAddressFactory)
    order_detail = factory.SubFactory(InvoiceOrderDetailFactory)
    vendor = factory.SubFactory(InvoiceVendorInfoFactory)

    @factory.lazy_attribute
    def products(self):
        return [InvoiceProductFactory() for _ in range(2)]
