import datetime

import factory
import pytz
from factory import fuzzy

from services.api_client.vendor_api_types import (
    DentalCityBillingAddress,
    DentalCityOrderInfo,
    DentalCityOrderProduct,
    DentalCityPartnerInfo,
    DentalCityProduct,
    DentalCityShippingAddress,
)


class DentalCityProductFactory(factory.Factory):
    class Meta:
        model = DentalCityProduct

    product_sku = fuzzy.FuzzyText()
    list_price = fuzzy.FuzzyDecimal(low=0)
    partner_price = fuzzy.FuzzyDecimal(low=0)
    web_price = fuzzy.FuzzyDecimal(low=0)
    partner_code = fuzzy.FuzzyText()
    product_desc = fuzzy.FuzzyText()
    available_quantity = fuzzy.FuzzyText()
    manufacturer = fuzzy.FuzzyText()
    manufacturer_part_number = fuzzy.FuzzyText()
    manufacturer_special = fuzzy.FuzzyText()
    flyer_special = fuzzy.FuzzyText()
    eta_date = fuzzy.FuzzyText()
    update_date = fuzzy.FuzzyText()


class DentalCityPartnerInfoFactory(factory.Factory):
    class Meta:
        model = DentalCityPartnerInfo

    partner_name = fuzzy.FuzzyText()
    shared_secret = fuzzy.FuzzyText()
    customer_id = fuzzy.FuzzyText()


class DentalCityOrderProductFactory(factory.Factory):
    product_sku = fuzzy.FuzzyText()
    unit_price = fuzzy.FuzzyDecimal(low=1)
    quantity = fuzzy.FuzzyInteger(low=1)
    manufacturer_part_number = fuzzy.FuzzyText()
    product_description = fuzzy.FuzzyText()

    class Meta:
        model = DentalCityOrderProduct


class DentalCityAddressFactory(factory.Factory):
    name = fuzzy.FuzzyText()
    address = fuzzy.FuzzyText()
    street = fuzzy.FuzzyText()
    city = fuzzy.FuzzyText()
    state = fuzzy.FuzzyText()
    postal_code = fuzzy.FuzzyText()
    country_code = fuzzy.FuzzyText()
    country_name = fuzzy.FuzzyText()


class DentalCityBillingAddressFactory(DentalCityAddressFactory):
    class Meta:
        model = DentalCityBillingAddress


class DentalCityShippingAddressFactory(DentalCityAddressFactory):
    email = fuzzy.FuzzyText()
    phone_number = fuzzy.FuzzyText()

    class Meta:
        model = DentalCityShippingAddress


class DentalCityOrderInfoFactory(factory.Factory):
    class Meta:
        model = DentalCityOrderInfo

    order_id = fuzzy.FuzzyText()
    order_datetime = fuzzy.FuzzyDateTime(datetime.datetime.now(pytz.utc))
    shipping_address = factory.SubFactory(DentalCityShippingAddressFactory)
    billing_address = factory.SubFactory(DentalCityBillingAddressFactory)

    @factory.lazy_attribute
    def order_products(self):
        return [DentalCityOrderProductFactory() for _ in range(2)]
