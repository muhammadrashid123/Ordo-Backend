import json
from decimal import Decimal
from typing import Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.vendor_clients import types
from apps.vendor_clients.headers.patterson import (
    ADD_PRODUCT_CART_HEADERS,
    CLEAR_CART_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    LOGIN_HOOK_HEADER,
    LOGIN_HOOK_HEADER2,
    PRE_LOGIN_HEADERS,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class PattersonClient(BaseClient):
    VENDOR_SLUG = "patterson"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        params = {
            "returnUrl": "/",
            "signIn": "userSignIn",
        }
        with self.session.get(
            url="https://www.pattersondental.com/Account", headers=PRE_LOGIN_HEADERS, params=params
        ) as resp:
            url = str(resp.url)

            headers = LOGIN_HEADERS.copy()
            headers["Referer"] = url
            return {
                "url": url,
                "headers": headers,
                "data": {
                    "userName": self.username,
                    "password": self.password,
                    "AuthMethod": "FormsAuthentication",
                },
            }

    def check_authenticated(self, resp: ClientResponse) -> bool:
        dom = Selector(text=resp.text)
        return False if dom.xpath(".//div[@id='error']") else True

    def after_login_hook(self, response: ClientResponse):
        response_dom = Selector(text=response.text)
        data = {
            "wa": response_dom.xpath("//input[@name='wa']/@value").get(),
            "wresult": response_dom.xpath("//input[@name='wresult']/@value").get(),
            "wctx": response_dom.xpath("//input[@name='wctx']/@value").get(),
        }
        self.session.post(url="https://www.pattersondental.com", headers=LOGIN_HOOK_HEADER, data=data)
        with self.session.get(url="https://www.pattersondental.com", headers=LOGIN_HOOK_HEADER2) as resp:
            text = resp.text
            return text

    def get_cart_page(self) -> Union[Selector, dict]:
        return self.get_response_as_json(
            url="https://www.pattersondental.com/ShoppingCart/CartItemQuantities",
            headers=GET_CART_HEADERS,
        )

    def clear_cart(self):
        products = self.get_cart_page()
        data = []
        for product in products:
            data.append(
                {
                    "OrderItemId": product["OrderItemId"],
                    "ParentItemId": None,
                    "PublicItemNumber": product["PublicItemNumber"],
                    "PersistentItemNumber": "",
                    "ItemQuantity": product["ItemQuantity"],
                    "BasePrice": None,
                    "ItemPriceBreaks": None,
                    "UnitPriceOverride": None,
                    "IsLabelItem": False,
                    "IsTagItem": False,
                    "ItemDescription": "",
                    "UseMyCatalogQuantity": False,
                    "UnitPrice": product["UnitPrice"],
                    "ItemSubstitutionReasonModel": None,
                    "NavInkConfigurationId": None,
                    "CanBePersonalized": False,
                    "HasBeenPersonalized": False,
                    "Manufacturer": False,
                }
            )
        self.session.post(
            url="https://www.pattersondental.com/ShoppingCart/RemoveItemsFromShoppingCart",
            headers=CLEAR_CART_HEADERS,
            json=data,
        )

    def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        data = {
            "itemNumbers": product["product"]["product_id"],
            "loadItemType": "ShoppingCart",
        }
        self.session.post(
            "https://www.pattersondental.com/Item/ValidateItems",
            headers=ADD_PRODUCT_CART_HEADERS,
            data=json.dumps(data),
        )
        data = [
            {
                "OrderItemId": None,
                "ParentItemId": None,
                "PublicItemNumber": product["product"]["product_id"],
                "PersistentItemNumber": None,
                "ItemQuantity": product["quantity"],
                "BasePrice": None,
                "ItemPriceBreaks": None,
                "UnitPriceOverride": None,
                "IsLabelItem": False,
                "IsTagItem": False,
                "ItemDescription": None,
                "UseMyCatalogQuantity": False,
                "UnitPrice": 0,
                "ItemSubstitutionReasonModel": None,
                "NavInkConfigurationId": None,
                "CanBePersonalized": False,
                "HasBeenPersonalized": False,
                "Manufacturer": False,
            }
        ]

        self.session.post(
            "https://www.pattersondental.com/ShoppingCart/AddItemsToCart",
            headers=ADD_PRODUCT_CART_HEADERS,
            data=json.dumps(data),
        )

    def serialize(self, data: Union[dict, Selector]) -> Optional[types.Product]:
        product_detail = data.xpath("//input[@id='ItemSkuDetail']/@value").get()
        try:
            product_detail = json.loads(product_detail)
            product_id = product_detail["PublicItemNumber"]
            return {
                "vendor": self.VENDOR_SLUG,
                "product_id": product_id,
                "sku": product_id,
                "name": product_detail["ItemDescription"],
                "url": f"https://www.pattersondental.com/Supplies/ItemDetail/{product_id}",
                "images": [
                    f"https://content.pattersondental.com/items/LargeSquare/images/{image['AssetFilename']}"
                    for image in product_detail["Images"]
                ],
                "price": Decimal(str(product_detail["UnitPrice"])),
                "product_vendor_status": "",
                "category": "",
                "unit": "",
            }
        except (TypeError, json.decoder.JSONDecodeError):
            pass

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass
