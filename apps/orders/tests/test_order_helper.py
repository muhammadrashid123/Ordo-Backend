from decimal import Decimal

import faker
from django.test import TestCase
from django.utils import timezone

from apps.accounts.factories import (
    CompanyFactory,
    OfficeFactory,
    OfficeVendorFactory,
    VendorFactory,
)
from apps.orders.factories import (
    OrderFactory,
    ProductFactory,
    VendorOrderFactory,
    VendorOrderProductFactory,
)
from apps.orders.helpers import OrderHelper
from apps.orders.tests.factories import OfficeProductFactory

fake = faker.Faker()


class OrderHelperTestCase(TestCase):
    product_count = 3
    vendor_count = 2

    @classmethod
    def setUpTestData(cls):
        current_time = timezone.localtime()

        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.vendors = VendorFactory.create_batch(cls.vendor_count)
        cls.office_vendors = [OfficeVendorFactory(office=cls.office, vendor=vendor) for vendor in cls.vendors]

        prices = [
            [
                fake.pydecimal(right_digits=2, min_value=Decimal("1.00"), max_value=Decimal("100.00"))
                for i in range(cls.product_count)
            ]
            for j in range(cls.vendor_count)
        ]

        cls.order = OrderFactory(
            office=cls.office,
            order_date=current_time.date(),
            total_items=cls.vendor_count * cls.product_count,
            total_amount=sum(sum(price_list) for price_list in prices),
        )
        cls.vendor_orders = []
        cls.products = []
        cls.office_products = []
        for i, (vendor, vendor_prices) in enumerate(zip(cls.vendors, prices)):
            products = [ProductFactory(vendor=vendor, price=price) for price in vendor_prices]
            if i == 0:
                for product, price in zip(products, vendor_prices):
                    office_product = OfficeProductFactory(office=cls.office, product=product, price=price)
                    cls.office_products.append(office_product)
            cls.products.append(products)
            vendor_order = VendorOrderFactory(
                vendor=vendor,
                order=cls.order,
                total_amount=sum(p.price for p in products),
                total_items=cls.product_count,
                order_date=current_time.date(),
            )
            for product in products:
                VendorOrderProductFactory(
                    vendor_order=vendor_order,
                    product=product,
                )
            cls.vendor_orders.append(vendor_order)

    def test_updating_office_product_price_works(self):
        delta = Decimal(20)
        vendor_order = self.vendor_orders[0]
        office_product = self.office_products[0]
        vendor_order_amount = vendor_order.total_amount
        order_amount = self.order.total_amount

        office_product.price += delta
        office_product.save(update_fields=["price"])

        OrderHelper.update_vendor_order_totals(vendor_order=vendor_order)
        vendor_order.refresh_from_db()
        self.order.refresh_from_db()
        assert vendor_order.total_amount == vendor_order_amount + delta
        assert self.order.total_amount == order_amount + delta

    def test_updating_product_price_works(self):
        delta = Decimal(20)
        vendor_order = self.vendor_orders[1]
        product = self.products[1][0]
        vendor_order_amount = vendor_order.total_amount
        order_amount = self.order.total_amount

        product.price += delta
        product.save(update_fields=["price"])

        OrderHelper.update_vendor_order_totals(vendor_order=vendor_order)
        vendor_order.refresh_from_db()
        self.order.refresh_from_db()
        assert vendor_order.total_amount == vendor_order_amount + delta
        assert self.order.total_amount == order_amount + delta
