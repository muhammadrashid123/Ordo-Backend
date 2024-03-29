from asyncio import Semaphore
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
import logging
import re

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.vendor_clients import types
from apps.orders.models import OfficeProduct
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.vendor_clients.headers.top_glove import (
    HTTP_HEADER,
    LOGIN_HEADER,
)

logger = logging.getLogger(__name__)

def text_parser(element):
        if not element:
            return ''
        text = re.sub(r"\s+", " ", " ".join(element.xpath('.//text()').extract()))
        return re.sub(u"(\u2018|\u2019)", "'", text).strip()

class TopGloveClient(BaseClient):
    VENDOR_SLUG = "top_glove"
    BASE_URL = "https://www.topqualitygloves.com"

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        async with self.session.get(f"{self.BASE_URL}/index.php?main_page=login", headers=HTTP_HEADER) as resp:
            text = Selector(text=await resp.text())
            security_token = text.xpath("//form[@name='login']//input[@name='securityToken']/@value").get()
            data = [
                ("email_address", self.username),
                ("password", self.password),
                ("securityToken", security_token),
                ("x", "27"),
                ("y", "3"),
            ]
            return {
                "url": f"{self.BASE_URL}/index.php?main_page=login&action=process",
                "headers": LOGIN_HEADER,
                "data": data,
            }

    async def check_authenticated(self, response: ClientResponse) -> bool:
        text = await response.text()
        dom = Selector(text=text)
        return "logged in" in dom.xpath("//li[@class='headerNavLoginButton']//text()").get()
    
    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        resp = await self.session.get(url=product.product.url)
        logger.debug("Response status: %s", resp.status)
        logger.debug("Product ID: %s", product.product.product_id)
        text = await resp.text()
        if resp.status != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()

        page_response_dom = Selector(text=text)
        variants = page_response_dom.xpath('//div[@class="attrRow"]')

        for variant in variants:
            product_id = text_parser(variant.xpath('.//h4[contains(@class, "optionItem")]'))
            price = text_parser(variant.xpath('.//h4[contains(@class, "optionPrice")]'))
            price = convert_string_to_price(price)

            if product.product.product_id == product_id:
                product_vendor_status = STATUS_ACTIVE
                return PriceInfo(price=price, product_vendor_status=product_vendor_status)

        product_vendor_status = STATUS_UNAVAILABLE
        return PriceInfo(price=0, product_vendor_status=product_vendor_status)