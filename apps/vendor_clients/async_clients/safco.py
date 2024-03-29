import logging
from typing import Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.types.scraper import LoginInformation
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.vendor_clients.headers.safco import (
    HOME_HEADER,
    LOGIN_HEADER,
    LOGIN_HOOK_HEADER,
)

logger = logging.getLogger(__name__)


class SafcoClient(BaseClient):
    VENDOR_SLUG = "safco"
    BASE_URL = "https://www.safcodental.com/"

    async def get_login_data(self, *args, **kwargs) -> LoginInformation:
        async with self.session.get(url=f"{self.BASE_URL}/?ref=sir", headers=HOME_HEADER):
            return {
                "url": f"{self.BASE_URL}/ajax/fn_signInJs.html",
                "headers": LOGIN_HEADER,
                "data": {
                    "si_an": self.username,
                    "si_ph": self.password,
                    "lform_title": "Welcome!",
                    "showCreateAccount": "",
                    "signInId": "rSi",
                    "showSiFormHeading": "Y",
                    "showNewDesign": "Y",
                    "redirect": "/",
                    "requestType": "json",
                    "sourcePage": "https://www.safcodental.com/",
                },
            }

    async def check_authenticated(self, resp: ClientResponse) -> bool:
        text = await resp.text()
        dom = Selector(text=text)

        return True if dom.xpath("//a[@href='/shopping-cart']") else False

    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        login_info = await self.get_login_data()
        logger.debug("Got logger data: %s", login_info)
        if login_info:
            async with self.session.post(
                url=login_info["url"], headers=login_info["headers"], data=login_info["data"]
            ) as resp:
                data = {
                    "contactFields": {
                        "email": login_info["data"]["si_an"],
                    },
                    "formSelectorClasses": ".login-form",
                    "formSelectorId": "",
                    "formValues": {},
                    "labelToNameMap": {},
                    "pageTitle": "Dental Supplies and Products | Safco Dental Supply",
                    "pageUrl": "https://www.safcodental.com/?ref=sir&ref=sor",
                    "portalId": 21944014,
                    "type": "SCRAPED",
                    "version": "collected-forms-embed-js-static-1.315",
                    "collectedFormClasses": "login-form",
                    "collectedFormAction": "ajax/fn_signInJs.html",
                }
                async with self.session.post(
                    url="https://forms.hubspot.com/collected-forms/submit/form", headers=LOGIN_HOOK_HEADER, json=data
                ) as resp:
                    async with self.session.get(url=f"{self.BASE_URL}", headers=HOME_HEADER) as resp:
                        if hasattr(self, "after_login_hook"):
                            await self.after_login_hook(resp)

                        logger.info("Successfully logged in")

                    return resp.cookies

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        resp = await self.session.get(url=product.product.url)
        logger.debug("Response status: %s", resp.status)
        logger.debug("Product ID: %s", product.product.product_id)
        text = await resp.text()
        if resp.status != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()

        page_response_dom = Selector(text=text)
        packages = page_response_dom.xpath(
            './/section[@class="product-group"]//div[contains(@class, "product-container")]'
        )
        for package in packages:
            item_no = package.xpath("./div[1]//text()").getall()
            item_no = "".join([i.strip() for i in item_no])
            item_no = item_no.replace("SKU:", "").replace("-", "").replace("Free Offer", "")
            price = package.xpath(".//div[@class='price'][1]//text()").getall()
            price = "".join([i.strip() for i in price])
            if "ea" in price:
                price = price.replace("ea", "").split("@")[1].strip()
            price = convert_string_to_price(price)
            if product.product.product_id.replace("-", "") == item_no:
                product_vendor_status = STATUS_ACTIVE
                return PriceInfo(price=price, product_vendor_status=product_vendor_status)

        product_vendor_status = STATUS_UNAVAILABLE
        return PriceInfo(price=0, product_vendor_status=product_vendor_status)
