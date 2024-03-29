import datetime
from decimal import Decimal
import time
import re
import json
import uuid
import scrapy
import requests
import traceback
import asyncio
from scrapy import Selector
from typing import Dict, List, Optional, Tuple
from http.cookies import SimpleCookie

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.utils import catch_network, semaphore_coroutine
from apps.scrapers.schema import VendorOrderDetail, Order
from apps.types.orders import CartProduct

class OfficeDepotScraper(Scraper):

    reqsession = requests.Session()

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        subtotal_manual = sum([prod['price']*prod['quantity'] for prod in products])
        vendor_order_detail =VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
            total_amount=Decimal(subtotal_manual),
            payment_method="",
            shipping_address="",
            reduction_amount=Decimal(subtotal_manual),
        )
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
            },
        }
        
    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        subtotal_manual = sum([prod['price']*prod['quantity'] for prod in products])
        vendor_order_detail =VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
            total_amount=Decimal(subtotal_manual),
            reduction_amount=Decimal(subtotal_manual),
            payment_method="",
            shipping_address=""
        )
        return {
            **vendor_order_detail.to_dict(),
            **self.vendor.to_dict(),
            "order_id":"invalid",
            "order_type": msgs.ORDER_TYPE_PROCESSING
        }
