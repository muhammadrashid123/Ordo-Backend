from decimal import Decimal
from typing import TypedDict, Union

PriceType = Union[str, Decimal]


class LinkedVendor(TypedDict):
    vendor: str
    username: str
    password: str


class CartProduct(TypedDict):
    product_id: str
    product_description: str
    product_unit: str
    product_url: str
    quantity: int
    price: float
    sku: str
    manufacturer_number: str


class VendorCartProduct(TypedDict):
    product_id: Union[str, int]
    unit_price: PriceType


class ProductTrack(TypedDict):
    product_id: str
    tracking_link: str
    tracking_number: str
