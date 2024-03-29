import logging
from typing import Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.vendor_clients.headers.pearson import HOME_HEADERS, LOGIN_HEADERS

logger = logging.getLogger(__name__)


class PearsonClient(BaseClient):
    VENDOR_SLUG = "pearson"

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        async with self.session.get(url="https://www.pearsondental.com/login.asp", headers=HOME_HEADERS):
            data = {
                "csmno": self.username,
                "password": self.password,
                "sp": "",
                "kwik": "",
                "epay": "",
                "site": "",
                "page": "",
                "http_referer": "https://www.pearsondental.com//catalog/topcat_list.asp",
                "action": "LOGIN",
            }

            return {
                "url": "https://www.pearsondental.com/login.asp",
                "headers": LOGIN_HEADERS,
                "data": data,
            }

    async def check_authenticated(self, resp: ClientResponse) -> bool:
        text = await resp.text()
        dom = Selector(text=text)
        return True if dom.xpath("//a[@href='/catalog/logout.asp']") else False

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        resp = await self.session.get(url=product.product.url)
        logger.debug("Response status: %s", resp.status)
        logger.debug("Product ID: %s", product.product.product_id)

        text = await resp.text()
        if resp.status != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()

        page_response_dom = Selector(text=text)
        main_table = page_response_dom.xpath("//table[2]/tr[2]/td[1]/table[2]")
        packages = main_table.xpath('./tr[2]//table[@class="link2"]/tr[@valign="top"]')
        for package in packages:
            item_no = package.xpath("./td[2]//text()").getall()
            item_no = "".join([i.strip() for i in item_no])
            price = package.xpath("./td[3]//text()").getall()
            price = convert_string_to_price("".join([i.strip() for i in price]))
            if product.product.sku == item_no:
                product_vendor_status = STATUS_ACTIVE
                return PriceInfo(price=price, product_vendor_status=product_vendor_status)

        product_vendor_status = STATUS_UNAVAILABLE
        return PriceInfo(price=0, product_vendor_status=product_vendor_status)
