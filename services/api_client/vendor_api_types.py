import datetime
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import List

DENTAL_CITY_SHIPPING_AMOUNT = Decimal("12.99")
DENTAL_CITY_SHIPPING_SUBTOTAL_THRESHOLD = Decimal("250")


@dataclass(frozen=True)
class Net32Product:
    mp_id: str
    price: Decimal
    inventory_quantity: int

    @property
    def product_identifier(self):
        return self.mp_id


@dataclass(frozen=True)
class Net32ProductInfo(Net32Product):
    name: str
    manufacturer_number: str
    category: str
    url: str
    retail_price: Decimal
    availability: str


@dataclass(frozen=True)
class DentalCityProduct:
    product_sku: str
    list_price: Decimal
    partner_price: Decimal
    web_price: Decimal
    manufacturer: str
    manufacturer_part_number: str
    manufacturer_special: str
    # partner_code: str
    product_desc: str
    # product_long_desc: str
    # product_image_url: str
    # available_quantity: int
    # flyer_special: str
    # fulfillment_type: str
    # free_goods_id: str
    # eta_date: str
    # update_date: str  # 04/05/2023

    @property
    def product_identifier(self):
        return self.product_sku

    @property
    def price(self):
        return self.partner_price

    @classmethod
    def from_dict(cls, data: dict):
        field_names = [field.name for field in fields(cls)]
        data = {key: value for key, value in data.items() if key in field_names}
        return cls(
            list_price=Decimal(data.pop("list_price", 0)),
            partner_price=Decimal(data.pop("partner_price", 0)),
            web_price=Decimal(data.pop("web_price", 0)),
            **data
        )


@dataclass(frozen=True)
class DentalCityAddress:
    name: str
    address_id: str
    deliver_to: str
    street: str
    city: str
    state: str
    postal_code: str
    country_code: str
    country_name: str


@dataclass(frozen=True)
class DentalCityBillingAddress(DentalCityAddress):
    pass


@dataclass(frozen=True)
class DentalCityShippingAddress(DentalCityAddress):
    email: str
    phone_number_country_code: str
    phone_number_national_number: str


@dataclass(frozen=True)
class DentalCityOrderProduct:
    product_sku: str
    unit_price: Decimal
    quantity: int
    manufacturer_part_number: str
    product_description: str


@dataclass(frozen=True)
class DentalCityOrderInfo:
    order_id: str
    order_datetime: datetime.datetime
    shipping_address: DentalCityShippingAddress
    billing_address: DentalCityBillingAddress
    order_products: List[DentalCityOrderProduct]

    @property
    def order_datetime_string(self):
        return self.order_datetime.isoformat()

    @property
    def sub_total(self) -> Decimal:
        return sum([product.unit_price * product.quantity for product in self.order_products])

    @property
    def shipping_amount(self) -> Decimal:
        if self.sub_total < DENTAL_CITY_SHIPPING_SUBTOTAL_THRESHOLD:
            return DENTAL_CITY_SHIPPING_AMOUNT
        else:
            return Decimal("0")

    @property
    def total_amount(self) -> Decimal:
        return self.sub_total + self.shipping_amount


@dataclass(frozen=True)
class DentalCityPartnerInfo:
    partner_name: str
    shared_secret: str
    customer_id: str


@dataclass(frozen=True)
class DentalCityOrderDetail:
    order_id: str
    vendor_order_id: str
    total_amount: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    order_products: List[DentalCityOrderProduct]


@dataclass(frozen=True)
class DentalCityShippingProduct:
    product_sku: str
    quantity: int


@dataclass(frozen=True)
class DentalCityShippingInfo:
    order_id: str
    payload_id: str
    carrier: str
    shipment_identifier: str
    shipping_products: List[DentalCityShippingProduct]


@dataclass(frozen=True)
class DentalCityInvoiceProduct:
    product_sku: str
    unit_price: Decimal
    total_price: Decimal


@dataclass(frozen=True)
class DentalCityInvoiceDetail:
    payload_id: str
    order_id: str
    invoice_id: str
    total_amount: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    invoice_products: List[DentalCityInvoiceProduct]


@dataclass(frozen=True)
class DCDentalProduct:
    name: str
    product_id: str
    sku: str
    price: Decimal
    quantity: Decimal
    manufacturer: str
    # manufacturer_special: str

    @property
    def product_identifier(self):
        return self.product_id

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            manufacturer=data.pop("Manufacturer"),
            # manufacturer_special=data.pop("Active Promotion"),
            name=data.pop("Description"),
            product_id=data.pop("Internal_ID"),
            sku=data.pop("Item"),
            price=Decimal(data.pop("pricing_unitprice", 0)),
            quantity=Decimal(data.pop("On_Hand") if data["On_Hand"] else 0),
        )


@dataclass(frozen=True)
class CrazyDentalProduct:
    name: str
    product_id: str
    sku: str
    price: Decimal
    quantity: Decimal
    manufacturer: str
    # manufacturer_special: str

    @property
    def product_identifier(self):
        return self.product_id

    @classmethod
    def from_dict(cls, data: dict):
        product_id = data.get("Item")
        if product_id is None:
            print("Missing 'Item' key in data:", data)  # Debugging statement
            return None  # Return None or raise an exception, depending on your requirements
        sku = product_id
        return cls(
            manufacturer=data.pop("Manufacturer"),
            # manufacturer_special=data.pop("Active Promotion"),
            name=data.pop("Description"),
            product_id=product_id,
            sku=sku,
            price=Decimal(data.pop("pricing_unitprice", 0)),
            quantity=Decimal(data.pop("On_Hand") if data.get("On_Hand") else 0),
        )
