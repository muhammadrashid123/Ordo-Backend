import datetime
from typing import NamedTuple, Union

from apps.orders.models import OfficeProduct, Product


class VendorParams(NamedTuple):
    inventory_age: datetime.timedelta
    regular_age: datetime.timedelta
    request_rate: float
    batch_size: int = 1
    needs_login: bool = True


class ProcessTask(NamedTuple):
    product: Union[Product, OfficeProduct]
    attempt: int = 0


class ProcessResult(NamedTuple):
    timestamp: datetime.datetime
    success: bool


class Stats(NamedTuple):
    rate: float
    error_rate: float
    total: int
