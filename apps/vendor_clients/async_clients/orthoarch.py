from asyncio import Semaphore
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import BaseClient

class OrthoarchClient(BaseClient):
    VENDOR_SLUG = "Orthoarch"