from decimal import Decimal
from typing import Any, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.vendor_clients import types
from apps.vendor_clients.headers.net_32 import (
    ADD_PRODUCT_TO_CART_HEADERS,
    CART_HEADERS,
    LOGIN_HEADERS,
    PLACE_ORDER_HEADERS,
    REMOVE_PRODUCT_FROM_CART_HEADERS,
    REVIEW_ORDER_HEADERS,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class Net32Client(BaseClient):
    VENDOR_SLUG = "net_32"

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        return {
            "url": "https://www.net32.com/rest/user/login",
            "headers": LOGIN_HEADERS,
            "data": {
                "userName": self.username,
                "password": self.password,
                "latestTosVersion": "1",
            },
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        """Check if whether session is authenticated or not"""
        res = response.json()
        return (
            res.get("CallHeader", {}).get("StatusCode")
            and res["CallHeader"]["StatusCode"] != "SC_ERROR_BAD_LOGIN_CREDENTIALS"
        )

    def get_cart_page(self) -> Union[Selector, dict]:
        """Get cart page in order to get products in cart"""
        with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            return resp.json()

    def remove_product_from_cart(self, product: Any):
        """Remove a single product from the cart
        Currently not used
        """
        product_id = product["product_id"]
        with self.session.get(
            "https://www.net32.com/rest/shoppingCart/get", headers=REMOVE_PRODUCT_FROM_CART_HEADERS
        ) as resp:
            cart_res = resp.json()
            data = [
                {
                    "mpId": product["mpId"],
                    "vendorProductId": product["vendorProductId"],
                    "minimumQuantity": product["minimumQuantity"],
                    "quantity": 0,
                }
                for vendor in cart_res["payload"]["vendorOrders"]
                for product in vendor["products"]
                if str(product["mpId"]) == product_id
            ]
        self.session.post(
            "https://www.net32.com/rest/shoppingCart/modify/rev2", headers=REMOVE_PRODUCT_FROM_CART_HEADERS, json=data
        )

    def clear_cart(self):
        """Clear all products from the cart"""
        with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            cart_res = resp.json()
            data = []
            for vendor in cart_res["payload"]["vendorOrders"]:
                for product in vendor["products"]:
                    data.append(
                        {
                            "mpId": product["mpId"],
                            "vendorProductId": product["vendorProductId"],
                            "minimumQuantity": product["minimumQuantity"],
                            "quantity": 0,
                        }
                    )
        self.session.post("https://www.net32.com/rest/shoppingCart/modify/rev2", headers=CART_HEADERS, json=data)

    def _get_product(self, product: types.Product) -> Optional[types.Product]:
        """ """
        with self.session.get(f"https://www.net32.com/rest/neo/pdp/{product['product_id']}") as resp:
            res = resp.json()
            return self.serialize(res)

    def serialize(self, data: Union[dict, Selector]) -> Optional[types.Product]:
        """Serialize vendor-specific product detail to our data"""
        return {
            "product_id": "",
            "sku": "",
            "name": data["title"],
            "url": f"https://www.net32.com/{data['url']}",
            "images": [f"https://www.net32.com/media{data['mediaPath']}"],
            "price": Decimal(data["retailPrice"]),
            "category": "",
            "unit": "",
        }

    def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        """Add single product to cart"""
        data = [
            {
                "mpId": product["product"]["product_id"],
                "quantity": product["quantity"],
            }
        ]

        self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation",
            headers=ADD_PRODUCT_TO_CART_HEADERS,
            json=data,
        )

    def add_products_to_cart(self, products: List[types.CartProduct]):
        data = [
            {
                "mpId": product["product"]["product_id"],
                "quantity": product["quantity"],
            }
            for product in products
        ]

        self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation",
            headers=ADD_PRODUCT_TO_CART_HEADERS,
            json=data,
        )

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        """Review the order without making real order"""
        # TODO: check payment_method & shipping_address
        dom = self.get_response_as_dom(url="https://www.net32.com/checkout", headers=REVIEW_ORDER_HEADERS)

        subtotal_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[3]/td/text()").get()
        )
        shipping_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[4]/td/text()").get()
        )
        tax_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[5]/td/text()").get()
        )
        total_amount = convert_string_to_price(
            dom.xpath(
                "//table[@class='order-summary-grandtotal-table']"
                "//span[@class='order-summary-grandtotal-value']/text()"
            ).get()
        )
        # payment_method = dom.xpath("//dl[@id='order-details-payment']/dd[1]/strong//text()").extract()
        # shipping_address = dom.xpath("//dl[@id='order-details-shipping']/dd[2]/text()").get()

        order_detail = types.VendorOrderDetail(
            subtotal_amount=subtotal_amount,
            shipping_amount=shipping_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            payment_method="",
            shipping_address="",
        )

        return {
            "order_detail": order_detail,
        }

    def place_order(self, *args, **kwargs) -> str:
        """Make the real order"""
        with self.session.post("https://www.net32.com/checkout/confirmation", headers=PLACE_ORDER_HEADERS) as resp:
            response_dom = Selector(text=resp.text())
            return response_dom.xpath("//h2[@class='checkout-confirmation-order-number-header']//a/text()").get()
