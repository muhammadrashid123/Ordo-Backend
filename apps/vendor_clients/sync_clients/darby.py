import datetime
import re
from decimal import Decimal
from typing import Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import concatenate_strings, convert_string_to_price
from apps.vendor_clients import types
from apps.vendor_clients.headers.darby import (
    ADD_PRODUCTS_TO_CART_HEADERS,
    CHECKOUT_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    ORDER_HEADERS,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class DarbyClient(BaseClient):
    VENDOR_SLUG = "darby"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        return {
            "url": "https://www.darbydental.com/api/Login/Login",
            "headers": LOGIN_HEADERS,
            "data": {"username": self.username, "password": self.password, "next": ""},
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        res = response.json()
        return res["m_Item2"] and res["m_Item2"]["username"] == self.username

    def get_cart_page(self) -> Union[Selector, dict]:
        return self.get_response_as_dom(
            url="https://www.darbydental.com/scripts/cart.aspx",
            headers=GET_CART_HEADERS,
        )

    def clear_cart(self):
        cart_page_dom = self.get_cart_page()

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
            self.add_products_to_cart(products)

    def add_products_to_cart(self, products: List[types.CartProduct]):
        data = {}
        for index, product in enumerate(products):
            data[f"items[{index}][Sku]"] = (product["product"]["product_id"],)
            data[f"items[{index}][Quantity]"] = product["quantity"]

        self.session.post(
            "https://www.darbydental.com/api/ShopCart/doAddToCart2", headers=ADD_PRODUCTS_TO_CART_HEADERS, data=data
        )

    def get_product_price(self, product: types.Product, login_required: bool = False) -> Dict[str, types.ProductPrice]:
        page_response_dom = self.get_response_as_dom(url=product["url"], headers=GET_PRODUCT_PAGE_HEADERS)
        product_id = product["product_id"]
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
        return {product_id: {"price": price, "product_vendor_status": product_vendor_status}}

    def serialize(self, data: Union[dict, Selector]) -> Optional[types.Product]:
        product_id = data.xpath(".//span[@id='MainContent_lblItemNo']/text").get()
        product_main_name = data.xpath(".//span[@id='MainContent_lblName']/text").get()
        product_detail_name = data.xpath(
            ".//select[@id='MainContent_ddlAdditional']/option[@selected='selected']/text"
        ).get()
        product_name = product_main_name + re.sub(r"(\d+)-(\d+)", "", product_detail_name)
        product_price = data.xpath(".//span[@id='MainContent_lblPrice']/text").get()
        units = Decimal(product_price[:1])
        product_price = convert_string_to_price(product_price[1:]) / units
        product_category = data.xpath(".//ul[contains(@class, 'breadcrumb')]/li/a/text").extract()[1]
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

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        cart_page_dom = self.get_cart_page()

        shipping_address = concatenate_strings(
            cart_page_dom.xpath('//span[@id="MainContent_lblAddress"]//text').extract(), delimeter=", "
        )
        subtotal_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblSubTotal"]//text').get()
        )
        shipping_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblServiceCharge"]//text').get()
        )
        tax_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblEstimatedTax"]//text').get()
        )
        total_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblTotal"]//text').get()
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

    def place_order(self, *args, **kwargs) -> str:
        checkout_dom = self.get_response_as_dom(
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
        with self.session.post(
            "https://www.darbydental.com/scripts/checkout.aspx", headers=ORDER_HEADERS, data=data
        ) as resp:
            dom = Selector(text=resp.text)
            order_id = dom.xpath('//span[@id="MainContent_lblInvoiceNo"]//text').get()

        return order_id
