import datetime
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum, IntEnum, auto
from typing import List, TypedDict, Union

from apps.scrapers.schema import Product

SmartID = Union[str, int]
SmartProductID = SmartID
InvoiceFile = Union[bytes, str]


class LoginInformation(TypedDict):
    url: str
    headers: dict
    data: dict


class ProductSearch(TypedDict):
    vendor_slug: str
    total_size: int
    page: int
    page_size: int
    products: List[Product]
    last_page: bool


class VendorInformation(TypedDict):
    id: int
    name: str
    slug: str
    url: str
    logo: str


class InvoiceFormat(Enum):
    USE_ORDO_FORMAT = auto()
    USE_VENDOR_FORMAT = auto()


class InvoiceType(IntEnum):
    HTML_INVOICE = auto()
    PDF_INVOICE = auto()


@dataclass(frozen=True)
class InvoiceVendorInfo:
    name: str
    logo: str


@dataclass(frozen=True)
class InvoiceAddress:
    shipping_address: str
    billing_address: str


@dataclass(frozen=True)
class InvoiceOrderDetail:
    order_id: str
    order_date: datetime.date
    payment_method: str
    total_items: int
    sub_total_amount: Decimal
    shipping_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class InvoiceProduct:
    product_url: str
    product_name: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class InvoiceInfo:
    address: InvoiceAddress
    vendor: InvoiceVendorInfo
    order_detail: InvoiceOrderDetail
    products: List[InvoiceProduct]

    def to_dict(self):
        return asdict(self)
