import asyncio
import json
import textwrap
from typing import Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.vendor_clients import types
from apps.vendor_clients.headers.implant_direct import (
    ADD_PRODUCT_TO_CART_HEADERS,
    CLEAR_CART_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    HOMEPAGE_HEADERS,
    LOGIN_HEADERS,
    LOGIN_PAGE_HEADERS,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class ImplantDirectClient(BaseClient):
    VENDOR_SLUG = "implant_direct"

    def get_login_link(self):
        home_dom = self.get_response_as_dom(
            url="https://store.implantdirect.com/",
            headers=HOMEPAGE_HEADERS,
        )
        return home_dom.xpath('//ul/li[@class="authorization-link"]/a/@href').get()

    def get_login_form(self, login_link):
        login_dom = self.get_response_as_dom(login_link, headers=LOGIN_PAGE_HEADERS)
        form_key = login_dom.xpath('//form[@id="login-form"]/input[@name="form_key"]/@value').get()
        form_action = login_dom.xpath('//form[@id="login-form"]/@action').get()
        return {
            "key": form_key,
            "action": form_action,
        }

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        login_link = self.get_login_link()
        form = self.get_login_form(login_link)
        headers = LOGIN_HEADERS.copy()
        headers["referer"] = login_link

        return {
            "url": form["action"],
            "headers": headers,
            "data": {
                "form_key": form["key"],
                "login[username]": self.username,
                "login[password]": self.password,
                "send": "",
            },
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        text = response.text
        dom = Selector(text=text)
        page_title = dom.css("title::text").get()
        return page_title != "Customer Login"

    def get_cart_page(self) -> Union[Selector, dict]:
        return self.get_response_as_dom(
            url="https://store.implantdirect.com/checkout/cart/",
            headers=GET_CART_HEADERS,
        )

    def remove_product_from_cart(self, data):
        self.session.post(
            "https://store.implantdirect.com/checkout/cart/delete/", headers=CLEAR_CART_HEADERS, data=data
        )

    def clear_cart(self):
        cart_page_dom = self.get_cart_page()
        form_key = cart_page_dom.xpath('//form[@id="form-validate"]//input[@name="form_key"]/@value').get()

        tasks = []
        for product in cart_page_dom.xpath(
            '//form[@id="form-validate"]//table[@id="shopping-cart-table"]/tbody[@class="cart item"]'
        ):
            product_delete_action_data = product.xpath(
                './/a[contains(@class, "action-delete")]/@data-post-action'
            ).get()
            product_delete_action_data = json.loads(product_delete_action_data)

            data = {
                "id": product_delete_action_data["data"]["id"],
                "uenc": product_delete_action_data["data"]["uenc"],
                "form_key": form_key,
            }
            tasks.append(self.remove_product_from_cart(data))

        asyncio.gather(*tasks)

    def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        # TODO: action_link can be simply generated if we fetch uenc value
        product_page_dom = self.get_product_page(
            product_link=product["product"]["url"], headers=GET_PRODUCT_PAGE_HEADERS
        )
        action_link = product_page_dom.xpath('//form[@id="product_addtocart_form"]/@action').get()
        data = textwrap.dedent(
            """\
        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="product"

        %s
        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="selected_configurable_option"

        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="related_product"

        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="item"

        %s
        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="form_key"

        nXveVoCfshd9HVbEX
        -----------------------------114617192524257728931343838898
        Content-Disposition: form-data; name="qty"

        %s
        -----------------------------114617192524257728931343838898--
        """
            % (product["product"]["product_id"], product["product"]["product_id"], product["quantity"])
        )

        self.session.post(action_link, headers=ADD_PRODUCT_TO_CART_HEADERS, data=data)

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass
