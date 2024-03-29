import datetime
from decimal import Decimal
from typing import List, Optional, TypedDict


class LoginInformation(TypedDict):
    url: str
    headers: dict
    data: dict


class VendorOrderDetail(TypedDict):
    subtotal_amount: Optional[Decimal]
    shipping_amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    total_amount: Optional[Decimal]
    payment_method: Optional[str]
    shipping_address: Optional[str]


class Product(TypedDict):
    vendor: str
    product_id: str
    sku: str
    name: str
    nickname: str
    url: str
    images: List[str]
    price: Decimal
    product_vendor_status: str
    category: str
    unit: str


class CartProduct(TypedDict):
    product: Product
    quantity: int


class OrderProduct(TypedDict):
    product: Product
    quantity: int
    unit_price: Decimal
    status: str
    tracking_link: str
    tracking_number: str


class Address(TypedDict):
    address: str
    region_code: str
    postal_code: str


class Order(TypedDict):
    order_id: str
    order_reference: str
    total_amount: Decimal
    currency: str
    order_date: datetime.date
    status: str
    shipping_address: Address
    products: List[OrderProduct]
    invoice_link: str


class VendorCredential(TypedDict):
    username: str
    password: str


class SearchMeta(TypedDict):
    vendor_slug: str
    total_size: int
    page: int
    page_size: int  # number of products per single page
    last_page: bool


class ProductSearch(TypedDict):
    meta: SearchMeta
    products: List[Product]


class ProductPrice(TypedDict):
    price: Decimal
    product_vendor_status: str
