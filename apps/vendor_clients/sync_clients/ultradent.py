import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.vendor_clients import types
from apps.vendor_clients.headers.ultradent import (
    ALL_PRODUCTS_QUERY,
    GET_ORDER_HEADERS,
    GET_ORDER_QUERY,
    GET_ORDERS_HEADERS,
    GET_ORDERS_QUERY,
    GET_PRODUCT_HEADERS,
    GET_PRODUCTS_HEADERS,
    PRE_LOGIN_HEADERS,
    PRODUCT_DETAIL_QUERY,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class UltradentClient(BaseClient):
    VENDOR_SLUG = "ultradent"

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        url = "https://www.ultradent.com/login"
        login_get_response_dom = self.get_response_as_dom(url=url, headers=PRE_LOGIN_HEADERS)
        token = login_get_response_dom.xpath("//input[@name='__RequestVerificationToken']/@value").get()

        return {
            "url": url,
            "headers": PRE_LOGIN_HEADERS,
            "data": {
                "Email": self.username,
                "Password": self.password,
                "__RequestVerificationToken": token,
            },
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        """Check if whether session is authenticated or not"""
        res = response.text()
        res_dom = Selector(text=res)
        return self.username == res_dom.xpath("//meta[@name='mUserName']/@content").get()

    def get_order_list(
        self, from_date: Optional[datetime.date] = None, to_date: Optional[datetime.date] = None
    ) -> Dict[str, Union[Selector, dict]]:
        # TODO: we need to understand query meaning correctly to improve the performance
        json_data = {
            "variables": {"numberOfDays": 546, "numberOfRows": 150},
            "query": GET_ORDERS_QUERY,
        }
        with self.session.post(
            url="https://www.ultradent.com/api/ecommerce", headers=GET_ORDERS_HEADERS, json=json_data
        ) as resp:
            res = resp.json()
            orders: Dict[str, Any] = {}
            for order in res["data"]["orders"]:
                order_date = datetime.date.fromisoformat(order["orderDate"])
                if from_date and to_date and (order_date < from_date or order_date > to_date):
                    continue
                orders[order["orderNumber"]] = order

            return orders

    def _get_order(self, order) -> types.Order:
        """Get vendor specific order"""
        json_data = {
            "variables": {"orderNumber": order["orderNumber"]},
            "query": GET_ORDER_QUERY,
        }
        order = {
            "order_id": order["orderNumber"],
            "status": order["orderStatus"],
            "order_date": order["orderDate"],
            "currency": "USD",
            "products": [],
        }

        with self.session.post(
            "https://www.ultradent.com/api/ecommerce", headers=GET_ORDER_HEADERS, json=json_data
        ) as resp:
            oder_html = (resp.json())["data"]["orderHtml"]["orderDetailWithShippingHtml"]
            order_dom = Selector(text=oder_html)
            tracking_dom = order_dom.xpath("//section[@data-tab='track-shipments']")
            product_images = {}
            for tracking_product in tracking_dom.xpath(".//ul/li"):
                sku = tracking_product.xpath(".//span[@class='sku-id']/text()").get()
                product_images[sku] = tracking_product.xpath(".//figure[@class='sku-thumb']/div/img/@src").get()

            shipping_dom = order_dom.xpath(
                "//section[@data-tab='order-details']/div[@class='odr-line-summary']"
                "/div[@class='grid-unit'][last()]/div[@class='address']"
            )

            codes = shipping_dom.xpath("./span[@class='location']//text()").split(", ")[1]
            region_code, postal_code, _ = codes.split()
            order["shipping_address"] = {
                "address": shipping_dom.xpath("./span[@class='street1']//text()").extract(),
                "region_code": region_code,
                "postal_code": postal_code,
            }
            for order_detail in order_dom.xpath("//section[@class='order-details']/ul[@class='odr-line-list']/li"):
                if order_detail.xpath("./@class").get() == "odr-line-header":
                    continue
                elif order_detail.xpath("./@class").get() == "odr-line-footer":
                    order["base_amount"] = order_detail.xpath(
                        "//div[@class='subtotal']/span[contains(@class, 'value')]//text()"
                    ).get()
                    order["shipping_amount"] = order_detail.xpath(
                        "//div[@class='shipping-total']/span[contains(@class, 'value')]//text()"
                    ).get()
                    order["tax_amount"] = order_detail.xpath(
                        "//div[@class='tax']/span[contains(@class, 'value')]//text()"
                    ).get()
                    order["total_amount"] = order_detail.xpath(
                        "//div[@class='odr-total']/span[contains(@class, 'value')]//text()"
                    ).get()
                else:
                    product_id = order_detail.xpath("./span[@class='sku-id']//text()").get()
                    price = order_detail.xpath("./span[@class='sku-price']//text()")

                    if product_id in product_images:
                        order_product_images = [product_images[product_id]]
                    else:
                        order_product_images = []

                    order["products"].append(
                        {
                            "product": {
                                "product_id": product_id,
                                "sku": product_id,
                                "name": order_detail.xpath("./span[@class='sku-product-name']//text()").get(),
                                "images": order_product_images,
                                "price": price,
                                "product_url": "",
                            },
                            "quantity": order_detail.xpath("./span[@class='sku-qty']//text()").get(),
                            "unit_price": price,
                            # "status": self.
                        }
                    )

        return order

    def get_cart_page(self) -> Union[Selector, dict]:
        pass

    def remove_product_from_cart(self, product: Any):
        pass

    def clear_cart(self):
        pass

    def add_products_to_cart(self, products: List[types.Product]):
        pass

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass

    def place_order(self, *args, **kwargs) -> str:
        pass

    def serialize(self, data: dict) -> Optional[types.Product]:
        product_url = data["url"]
        if product_url:
            category = product_url.split("/")[3]
            return {
                "product_id": data["sku"],
                "sku": data["sku"],
                "name": data["productName"],
                "url": f"https://www.ultradent.com{product_url}?sku={data['sku']}",
                "images": list(map(lambda x: x["source"], data["images"])),
                "price": Decimal(data.get("catalogPrice", "")),
                "category": category,
                "unit": "",
            }

    def get_all_products(self) -> List[types.Product]:
        products: List[types.Product] = []

        with self.session.post(
            url="https://www.ultradent.com/api/ecommerce",
            headers=GET_PRODUCTS_HEADERS,
            json={
                "query": ALL_PRODUCTS_QUERY,
                "variables": {
                    "includeAllSkus": True,
                    "withImages": True,
                },
            },
        ) as resp:
            res = resp.json()
            vendor_products = res["data"]["allProducts"]
            for vendor_product in vendor_products:
                product = self.serialize(vendor_product)
                if product:
                    products.append(product)

        return products

    def _get_product(self, product: types.Product) -> types.Product:
        with self.session.post(
            "https://www.ultradent.com/api/ecommerce",
            headers=GET_PRODUCT_HEADERS,
            json={
                "variables": {
                    "skuValues": product["product_id"],
                    "withAccessories": False,
                    "withPrice": False,
                },
                "query": PRODUCT_DETAIL_QUERY,
            },
        ) as resp:
            res = resp.json()
            return self.serialize(res["data"]["product"])
