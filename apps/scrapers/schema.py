from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, get_args, get_origin

from django.utils.dateparse import parse_date, parse_datetime


def from_dict(cls, dict_data):
    def convert_dict2dataclass(field_type, v):
        if isinstance(v, field_type):
            return v
        elif field_type in (int, float, str):
            return field_type(v)
        elif field_type == Address:
            return v
        elif field_type is Decimal:
            try:
                v = str(v).replace(",", "").strip(" $")
                v = Decimal(v)
            except InvalidOperation:
                v = Decimal("0")
            return v
        elif field_type is date:
            return parse_date(v)
        elif field_type is datetime:
            return parse_datetime(v)
        else:
            return field_type.from_dict(v)

    data = {}
    for field in fields(cls):
        key = field.name
        value = dict_data.get(key, None)
        if value is not None:
            if get_origin(field.type) is list:
                data[key] = [convert_dict2dataclass(get_args(field.type)[0], item) for item in value]
            else:
                data[key] = convert_dict2dataclass(field.type, value)
        else:
            data[key] = None

    return cls(**data)


class BaseDataClass:
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict):
        return from_dict(cls, value)


@dataclass(frozen=True)
class ProductImage(BaseDataClass):
    image: str


@dataclass(frozen=True)
class Vendor(BaseDataClass):
    id: str
    name: str
    slug: str
    url: str
    logo: str


@dataclass(frozen=True)
class ProductCategory(BaseDataClass):
    name: str
    slug: str


@dataclass(frozen=True, repr=False)
class Product(BaseDataClass):
    product_id: str
    name: str
    nickname: str
    description: str
    url: str
    images: List[ProductImage]
    price: Decimal  # Decimal
    vendor: Vendor
    category: List[str]  # this is a list of categories including sub-categories
    product_unit: str
    # stars: Decimal
    # ratings: Decimal

    def __hash__(self):
        return hash(f"{self.vendor.id}{self.product_id}")

    def __str__(self):
        return f"Product(product_id={self.product_id})"

    def __repr__(self):
        return f"Product(product_id={self.product_id})"


@dataclass(frozen=True)
class OrderProduct(BaseDataClass):
    product: Product
    quantity: int
    unit_price: Decimal
    status: str
    tracking_link: str
    tracking_number: str


@dataclass(frozen=True)
class Address(BaseDataClass):
    address: str
    region_code: str
    postal_code: str


@dataclass(frozen=True)
class Order(BaseDataClass):
    order_id: str
    vendor_order_reference: str
    total_amount: Decimal
    currency: str
    order_date: date
    status: str
    shipping_address: Address
    products: List[OrderProduct]
    invoice_link: str
    total_items: int = 0

    def to_dict(self) -> dict:
        ret = super().to_dict()
        ret["total_items"] = len(self.products)
        return ret


@dataclass(frozen=True)
class VendorOrderDetail(BaseDataClass):
    retail_amount: Decimal
    savings_amount: Decimal
    subtotal_amount: Decimal
    shipping_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    reduction_amount: Decimal
    payment_method: str
    shipping_address: str
