import datetime
import logging
import re
from asyncio import Semaphore
from decimal import Decimal
from typing import Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import concatenate_strings, convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.scrapers.semaphore import fake_semaphore
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.vendor_clients.headers.darby import (
    ADD_PRODUCTS_TO_CART_HEADERS,
    CHECKOUT_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    ORDER_HEADERS,
)
import cloudscraper
from apps.vendor_clients import errors

logger = logging.getLogger(__name__)


PRICE_REGEX = re.compile(r"(?P<amount>\d+)\s*@\s*\$?(?P<price>[0-9]*\.?[0-9]*)")


class DarbyClient(BaseClient):
    VENDOR_SLUG = "darby"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        return {
            "url": "https://www.darbydental.com/api/Login/Login",
            "headers": LOGIN_HEADERS,
            "data": {"username": self.username, "password": self.password, "next": ""},
        }

    async def check_authenticated(self, response: ClientResponse) -> bool:
        res = await response.json()
        return res["m_Item2"] and res["m_Item2"]["<username>k__BackingField"] == self.username

    async def get_cart_page(self) -> Union[Selector, dict]:
        return await self.get_response_as_dom(
            url="https://www.darbydental.com/scripts/cart.aspx",
            headers=GET_CART_HEADERS,
        )

    async def clear_cart(self):
        cart_page_dom = await self.get_cart_page()

        products: List[types.CartProduct] = []
        for tr in cart_page_dom.xpath('//div[@id="MainContent_divGridScroll"]//table[@class="gridPDP"]//tr'):
            sku = tr.xpath(
                './/a[starts-with(@id, "MainContent_gvCart_lbRemoveFromCart_")][@data-prodno]/@data-prodno'
            ).get()
            if sku:
                products.append(
                    {
                        "product": {
                            "product_id": sku,
                        },
                        "quantity": 0,
                    }
                )

        if products:
            await self.add_products_to_cart(products)

    async def add_products_to_cart(self, products: List[types.CartProduct]):
        data = {}
        for index, product in enumerate(products):
            data[f"items[{index}][Sku]"] = (product["product"]["product_id"],)
            data[f"items[{index}][Quantity]"] = product["quantity"]

        await self.session.post(
            "https://www.darbydental.com/api/ShopCart/doAddToCart2", headers=ADD_PRODUCTS_TO_CART_HEADERS, data=data
        )

    async def get_product_price(
        self, product: types.Product, semaphore: Optional[Semaphore] = None, login_required: bool = False
    ) -> Dict[str, types.ProductPrice]:
        if not semaphore:
            semaphore = fake_semaphore
        async with semaphore:

            try:
                login_info = await self.get_login_data()
            except Exception as e:
                logger.debug("Got login data exception: %s", e)

            product_id = product["product_id"]
            try:

                logger.debug("Got logger data: %s", login_info)
                scraper = cloudscraper.create_scraper()
                if login_info:
                    logger.debug("Logging in...")
                    resp = scraper.post(login_info["url"], headers=login_info["headers"], data=login_info["data"])

                    if resp.status_code != 200:
                        content = await resp.text
                        logger.debug("Got %s status, content = %s", resp.status_code, content)
                        raise errors.VendorAuthenticationFailed()
                    else:
                        headers = getattr(self, "GET_PRODUCT_PAGE_HEADERS")
                        response = scraper.get(url=product["url"], headers=headers)
                        text = response.text
                        page_response_dom = Selector(text=text)
                        # product_detail = self.serialize(product, dom)
                        # return product_detail
                        price_text = page_response_dom.xpath(
                            f'//tr[@class="pdpHelltPrimary"]/td//input[@data-sku="{product_id}"]'
                            '/../following-sibling::td//span[contains(@id, "_lblPrice")]//text()'
                        ).get()

                        if not price_text:
                            price_text = page_response_dom.xpath('//span[@id="MainContent_lblPrice"]//text()').get()

                        product_unit = Decimal(price_text[:1])
                        price = convert_string_to_price(price_text[1:])
                        price = price / product_unit
                        product_vendor_status = ""
            except Exception:
                return {product_id: {"price": 0, "product_vendor_status": "Network Error"}}
            else:
                return {product_id: {"price": price, "product_vendor_status": product_vendor_status}}
            
    async def get_product_vendor_status(self, product_id, page_response_dom):
        response = await self.session.get(f'https://www.darbydental.com/categories/Implant-Products/Implant-Instruments/Implant-Scalers/{product_id}')
        product_details_parse = Selector(text=await response.text())
        table_rows = product_details_parse.xpath(
            "//table[@id='MainContent_gvAdditonalProduct']/tr"
        )
        item_details = {
            "item_status": "",
            "item_description": ""
        }
        for index,row in enumerate(table_rows[1:]):
            item_id = page_response_dom.xpath(f"//span[@id='MainContent_gvAdditonalProduct_hlProdNo_{index}']/text()").get()
            if item_id is None:
                continue

            if item_id.replace('-', '') == product_id:
                item_details["item_status"] = page_response_dom.xpath(f"//span[@id='MainContent_gvAdditonalProduct_lblStock_{index}']/text()").get()
                item_details["item_description"] = page_response_dom.xpath(f"//span[@id='MainContent_gvAdditonalProduct_lblDesc_{index}']/text()").get()
                break

        return item_details
    
    def construct_image_url(self, product_id):
        # Ensure the product_id is a string to work with it easily
        product_id_str = str(product_id)
        
        # Extract, reverse, and split the last four digits
        last_four_reversed_split = "/".join(product_id_str[-4:][::-1])
        
        # Construct the URL
        url_template = "https://storprodwebcontent.blob.core.windows.net/resources/PrintAndWebImages/PrintImages/{split_digits}/{product_id}.jpg"
        image_url = url_template.format(split_digits=last_four_reversed_split, product_id=product_id_str)
        
        return image_url

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        product_id = product.product.product_id
        resp = await self.session.get(url=product.product.url, headers=GET_PRODUCT_PAGE_HEADERS)
        logger.debug("Response status: %s", resp.status)
        text = await resp.text()
        if resp.status != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()
        page_response_dom = Selector(text=text)

        price_text = page_response_dom.xpath(
            f'//tr[@class="pdpHelltPrimary"]/td//input[@data-sku="{product_id}"]'
            '/../following-sibling::td//span[contains(@id, "_lblPrice")]//text()'
        ).get()

        image_url = self.construct_image_url(product_id)

        try:
            item_details = await self.get_product_vendor_status(product_id, page_response_dom)
        except Exception as e:
            logger.debug("Product status exception: %s", e)

        if not price_text:
            price_text = page_response_dom.xpath('//span[@id="MainContent_lblPrice"]//text()').get()

        if not price_text:
            logger.debug("Second attempt gave no results for price parsing")
            raise EmptyResults()

        if price_text.lower() == "call for price":
            logger.debug("Got call for price")
            raise EmptyResults()

        mo = PRICE_REGEX.search(price_text)
        if not mo:
            logger.warning("Could not parse price %s", price_text)
            raise EmptyResults()

        gd = mo.groupdict()
        product_unit = Decimal(gd["amount"])
        price = Decimal(gd["price"])
        price = price / product_unit
        product_vendor_status = "Active" if item_details["item_status"].lower() == "yes" else "Discontinued"
        return PriceInfo(
            price=price,
            product_vendor_status=product_vendor_status,
            image=image_url,
            description=item_details["item_description"] if item_details["item_description"] != "" else ""
        )

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
        product_id = data.xpath(".//span[@id='MainContent_lblItemNo']/text()").get()
        product_main_name = data.xpath(".//span[@id='MainContent_lblName']/text()").get()
        product_detail_name = data.xpath(
            ".//select[@id='MainContent_ddlAdditional']/option[@selected='selected']/text()"
        ).get()
        product_name = product_main_name + re.sub(r"(\d+)-(\d+)", "", product_detail_name)
        product_price = data.xpath(".//span[@id='MainContent_lblPrice']/text()").get()
        units = Decimal(product_price[:1])
        product_price = convert_string_to_price(product_price[1:]) / units
        product_category = data.xpath(".//ul[contains(@class, 'breadcrumb')]/li/a/text()").extract()[1]
        return {
            "vendor": self.VENDOR_SLUG,
            "product_id": product_id,
            "sku": product_id,
            "name": product_name,
            "url": "",
            "images": [
                "https://azfun-web-image-picker.azurewebsites.net"
                f"/api/getImage?sku={product_id.replace('-', '')}&type=WebImages"
            ],
            "price": product_price,
            "product_vendor_status": "",
            "category": product_category,
            "unit": "",
        }

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        cart_page_dom = await self.get_cart_page()

        shipping_address = concatenate_strings(
            cart_page_dom.xpath('//span[@id="MainContent_lblAddress"]//text()').extract(), delimeter=", "
        )
        subtotal_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblSubTotal"]//text()').get()
        )
        shipping_amount = convert_string_to_price(
            cart_page_dom.xpath(
                '//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblServiceCharge"]//text()'
            ).get()
        )
        tax_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblEstimatedTax"]//text()').get()
        )
        total_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblTotal"]//text()').get()
        )
        order_detail = types.VendorOrderDetail(
            subtotal_amount=subtotal_amount,
            shipping_amount=shipping_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            payment_method=None,
            shipping_address=shipping_address,
        )
        return {
            "order_detail": order_detail,
        }

    async def place_order(self, *args, **kwargs) -> str:
        checkout_dom = await self.get_response_as_dom(
            url="https://www.darbydental.com/scripts/checkout.aspx",
            headers=CHECKOUT_HEADERS,
        )

        data = {
            "ctl00$MainContent$pono": f"Ordo Order ({datetime.date.today().isoformat()})",
            "__ASYNCPOST": "true",
            "ctl00$masterSM": "ctl00$MainContent$UpdatePanel1|ctl00$MainContent$completeOrder",
            "ctl00$ddlPopular": "-1",
        }
        for _input in checkout_dom.xpath('//form[@id="form1"]//input[@name]'):
            _key = _input.xpath("./@name").get()
            _val = _input.xpath("./@value").get()
            data[_key] = _val
        async with self.session.post(
            "https://www.darbydental.com/scripts/checkout.aspx", headers=ORDER_HEADERS, data=data
        ) as resp:
            dom = Selector(text=await resp.text())
            order_id = dom.xpath('//span[@id="MainContent_lblInvoiceNo"]//text()').get()

        return order_id
