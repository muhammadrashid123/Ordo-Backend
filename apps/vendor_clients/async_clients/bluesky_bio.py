import logging
import re
from typing import Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.scrapers.headers.blue_sky_bio import GENERAL_HEADER, LOGIN_HEADER
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo

logger = logging.getLogger(__name__)


def text_parser(element):
    if not element:
        return ""
    text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
    text = re.sub("(\u2018|\u2019)", "'", text)
    return text.strip() if text else ""


class BlueskyBioClient(BaseClient):
    VENDOR_SLUG = "bluesky_bio"
    BASE_URL = "https://blueskybio.com"

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        await self.session.get(f"{self.BASE_URL}/store/", headers=GENERAL_HEADER)
        data = [
            ("user", self.username),
            ("pass", self.password),
            ("current_uri", "/store/index.php"),
        ]
        return {
            "url": f"{self.BASE_URL}/store/ajax_calls/customer_login.php",
            "headers": LOGIN_HEADER,
            "data": data,
        }

    async def check_authenticated(self, response: ClientResponse) -> bool:
        text = await response.text()
        return self.username in text

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        resp = await self.session.get(url=product.product.url)
        logger.debug("Response status: %s", resp.status)
        logger.debug("Product ID: %s", product.product.product_id)
        text = await resp.text()
        if resp.status != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()

        page_response_dom = Selector(text=text)
        packages = page_response_dom.xpath('//article//div[contains(@class, "store")]//h2[@id]')

        for package in packages:
            next_ele = package.xpath("./following-sibling::*[1]")
            next_ele_name = next_ele.xpath("name()").get()
            next_next_ele = package.xpath("./following-sibling::*[2]")
            next_next_ele_name = next_next_ele.xpath("name()").get()

            table_ele = None
            if next_ele_name == "table":
                table_ele = next_ele
            elif next_next_ele_name == "table":
                table_ele = next_next_ele

            if not table_ele:
                product_vendor_status = STATUS_UNAVAILABLE
                return PriceInfo(price=0, product_vendor_status=product_vendor_status)

            for variant in table_ele.xpath('.//tr[contains(@class, "ga-item")]'):
                product_id = variant.xpath('.//td/input[@class="input_num"]/@name').get()
                price = text_parser(variant.xpath("./td[4]"))
                price = convert_string_to_price(price)

                if product.product.product_id == product_id:
                    product_vendor_status = STATUS_ACTIVE
                    return PriceInfo(price=price, product_vendor_status=product_vendor_status)

        product_vendor_status = STATUS_UNAVAILABLE
        return PriceInfo(price=0, product_vendor_status=product_vendor_status)
