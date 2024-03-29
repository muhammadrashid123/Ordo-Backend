import logging
from typing import Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.orders.updater import STATUS_ACTIVE
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.vendor_clients.headers.midwest_dental import (
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    PRE_LOGIN_HEADERS,
)

logger = logging.getLogger(__name__)


class MidwestDentalClient(BaseClient):
    VENDOR_SLUG = "midwest_dental"

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        async with self.session.get(
            url="https://www.mwdental.com/customer/account/login/", headers=PRE_LOGIN_HEADERS
        ) as resp:
            text = await resp.text()
            dom = Selector(text=text)
            form_key = dom.xpath('//form[@id="login-form"]/input[@name="form_key"]/@value').get()
            return {
                "url": "https://www.mwdental.com/customer/account/loginPost/",
                "headers": LOGIN_HEADERS,
                "data": {
                    "form_key": form_key,
                    "login[username]": self.username,
                    "login[password]": self.password,
                    "send.x": "34",
                    "send.y": "12",
                },
            }

    async def check_authenticated(self, resp: ClientResponse) -> bool:
        text = await resp.text()
        dom = Selector(text=text)
        return bool(dom.xpath("//a[@title='Log Out']"))

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        if product.product.url is None:
            logger.warning("Url is empty for product %s", product.id)
            raise EmptyResults()

        resp = await self.session.get(url=product.product.url, headers=GET_PRODUCT_PAGE_HEADERS)
        logger.debug("Response status: %s", resp.status)
        logger.debug("Product ID: %s", product.product.product_id)
        if resp.status != 200:
            raise EmptyResults()

        text = await resp.text()
        page = Selector(text=text)
        price_str = page.xpath('//div[@class="price-box"]//span[@class="price"]/text()').get()
        price = convert_string_to_price(price_str)
        if not price:
            logger.warning("Got bad price for %s. %s", product.id, price_str)
            raise EmptyResults()
        return PriceInfo(
            price=price,
            product_vendor_status=STATUS_ACTIVE,
        )
