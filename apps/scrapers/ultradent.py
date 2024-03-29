import asyncio
import datetime
import logging
import re
import traceback
import uuid
from decimal import Decimal
from typing import Dict, List, Optional

import jwt
from aiohttp import ClientResponse
from asgiref.sync import sync_to_async
from scrapy import Selector

from apps.common import messages as msgs
from apps.common.utils import concatenate_list_as_string
from apps.scrapers.base import Scraper
from apps.scrapers.headers.ultradent import (
    ADDCART_HEADERS,
    BILLING_HEADERS,
    CHECKOUT_HEADERS,
    CLEAR_HEADERS,
    MAIN_HEADERS,
    ORDER_HEADERS,
    SEARCH_HEADERS,
    SUBMIT_HEADERS,
    UPDATECART_HEADERS,
)
from apps.scrapers.schema import Order, Product, ProductCategory, VendorOrderDetail
from apps.scrapers.search_queries.ultradent import (
    ADD_CART_QUERY,
    ALL_PRODUCTS_QUERY,
    BILLING_QUERY,
    GET_ORDER_DETAIL_HTML,
    GET_ORDER_QUERY,
    GET_ORDERS_QUERY,
    PRODUCT_DETAIL_QUERY,
)
from apps.scrapers.utils import (
    catch_network,
    convert_string_to_price,
    semaphore_coroutine,
)
from apps.types.orders import CartProduct
from apps.types.scraper import (
    InvoiceAddress,
    InvoiceFile,
    InvoiceFormat,
    InvoiceInfo,
    InvoiceOrderDetail,
    InvoiceProduct,
    InvoiceType,
    InvoiceVendorInfo,
    LoginInformation,
    ProductSearch,
)

logger = logging.getLogger(__name__)

ALL_PRODUCTS_VARIABLE = {
    "includeAllSkus": True,
    "withImages": True,
}


def textParser(element):
    if element:
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""
    return ""


class UltraDentScraper(Scraper):
    BASE_URL = "https://www.ultradent.com"
    CATEGORY_URL = "https://www.ultradent.com/products/categories"
    CATEGORY_HEADERS = MAIN_HEADERS
    INVOICE_TYPE = InvoiceType.HTML_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_ORDO_FORMAT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.product_urls = {}

    @sync_to_async
    def resolve_product_urls(self, product_ids):
        pass

    async def _check_authenticated(self, response: ClientResponse) -> bool:
        res = await response.text()
        res_dom = Selector(text=res)
        return self.username == res_dom.xpath("//meta[@name='mUserName']/@content").get()

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        url = "https://www.ultradent.com/login"
        async with self.session.get(url, headers=MAIN_HEADERS) as resp:
            login_get_response_dom = Selector(text=await resp.text())
            token = login_get_response_dom.xpath("//input[@name='__RequestVerificationToken']/@value").get()

        return {
            "url": url,
            "headers": MAIN_HEADERS,
            "data": {
                "Email": self.username,
                "Password": self.password,
                "__RequestVerificationToken": token,
            },
        }

    async def get_token(self):
        async with self.session.get("https://www.ultradent.com/account", headers=ORDER_HEADERS) as response:
            response_text = await response.text()

        dom = Selector(text=response_text)

        account_number_xpath = '//div[@id="generalInfo"]//p[contains(text(), "Account #:")]//text()'
        account_number = " ".join(dom.xpath(account_number_xpath).extract()).strip()
        account_number = account_number.split("Account #:")[1].strip()
        first_name_xpath = '//div[@id="generalInfo"]//h2[contains(text(), "Hi,")]//text()'
        first_name = " ".join(dom.xpath(first_name_xpath).extract()).strip()
        first_name = first_name.split("Hi,")[1].strip()
        first_name = first_name.split(" ")[0].upper()

        user_id = response_text.split("customerId:")[1].split(",")[0].strip()
        user_guid = response_text.split("upiSessionId:")[1].split(",")[0].strip()
        user_guid = user_guid.strip("'\"")

        expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        user_data = (
            '{"Data":{"UserId":%s,"AccountNumber":%s,"UserGuid":"%s","Email":"%s",'
            '"FirstName":"%s","SalesChannel":1},"UserType":0,"Roles":[],"PreviewMode":false}'
            % (user_id, account_number, user_guid, self.username, first_name)
        )

        payload = {
            "unique_name": self.username,
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/userdata": user_data,
            "nbf": 1691687834,
            "exp": expiration_time,
            "iat": 1691687834,
            "iss": "https://www.ultradent.com",
            "aud": "https://www.ultradent.com",
        }

        token = jwt.encode(payload, "secret", algorithm="HS256")
        print("JWT Token:", token)
        return token

    async def _after_login_hook(self, response: ClientResponse):
        token = await self.get_token()
        ORDER_HEADERS["authorization"] = f"Bearer {token}"

    @semaphore_coroutine
    async def get_order(self, sem, order, office=None) -> dict:
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

        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce", headers=ORDER_HEADERS, json=json_data
        ) as resp:
            oder_html = (await resp.json())["data"]["orderHtml"]["orderDetailWithShippingHtml"]
            order_dom = Selector(text=oder_html)
            tracking_dom = order_dom.xpath("//section[@data-tab='track-shipments']")
            product_images = {}
            for tracking_product in tracking_dom.xpath(".//ul/li"):
                sku = self.extract_first(tracking_product, ".//span[@class='sku-id']/text()")
                product_images[sku] = self.extract_first(
                    tracking_product, ".//figure[@class='sku-thumb']/div/img/@src"
                )

            # track_status = tracking_dom.xpath(".//span[contains(@class, 'shipment-package-date')]//text()").extract()
            # order["status"] = track_status[0].strip().strip(":")
            # order["tracking_date"] = track_status[1]

            shipping_dom = order_dom.xpath(
                "//section[@data-tab='order-details']/div[@class='odr-line-summary']"
                "/div[@class='grid-unit'][last()]/div[@class='address']"
            )

            codes = self.extract_first(shipping_dom, "./span[@class='location']//text()").split(", ")[1]
            region_code, postal_code, _ = codes.split()
            order["shipping_address"] = {
                "address": self.merge_strip_values(shipping_dom, "./span[@class='street1']//text()"),
                "region_code": region_code,
                "postal_code": postal_code,
            }
            order["tracking_link"] = order_dom.xpath('//a[@title="Track this package"]/@href').get()
            for order_detail in order_dom.xpath("//section[@class='order-details']/ul[@class='odr-line-list']/li"):
                if order_detail.xpath("./@class").get() == "odr-line-header":
                    continue
                elif order_detail.xpath("./@class").get() == "odr-line-footer":
                    order["base_amount"] = self.extract_first(
                        order_detail, "//div[@class='subtotal']/span[contains(@class, 'value')]//text()"
                    )
                    order["shipping_amount"] = self.extract_first(
                        order_detail,
                        "//div[@class='shipping-total']/span[contains(@class, 'value')]//text()",
                    )
                    order["tax_amount"] = self.extract_first(
                        order_detail,
                        "//div[@class='tax']/span[contains(@class, 'value')]//text()",
                    )
                    order["total_amount"] = self.extract_first(
                        order_detail,
                        "//div[@class='odr-total']/span[contains(@class, 'value')]//text()",
                    )
                else:
                    product_id = self.extract_first(order_detail, "./span[@class='sku-id']//text()").strip()
                    price = self.extract_first(order_detail, "./span[@class='sku-price']//text()")

                    if product_id in product_images:
                        order_product_images = [{"image": product_images[product_id]}]
                    else:
                        order_product_images = []

                    order["products"].append(
                        {
                            "product": {
                                "product_id": product_id.strip("#-"),
                                "name": self.extract_first(order_detail, "./span[@class='sku-product-name']//text()"),
                                "images": order_product_images,
                                "price": price,
                                "vendor": self.vendor.to_dict(),
                            },
                            "quantity": self.extract_first(order_detail, "./span[@class='sku-qty']//text()"),
                            "unit_price": price,
                            "tracking_link": order["tracking_link"],
                            # "status": self.
                        }
                    )

        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order))
        return order

    @catch_network
    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        sem = asyncio.Semaphore(value=2)
        url = "https://www.ultradent.com/api/ecommerce"

        json_data = {
            "variables": {"numberOfDays": 546, "numberOfRows": 150},
            "query": GET_ORDERS_QUERY,
        }
        if perform_login:
            await self.login()
        async with self.session.post(url, headers=ORDER_HEADERS, json=json_data) as resp:
            data = await resp.json()
            orders_data = data["data"]["orders"]
            tasks = []
            for order_data in orders_data:
                order_date = datetime.date.fromisoformat(order_data["orderDate"])
                print(order_data, from_date, to_date)
                if from_date and to_date and (order_date < from_date or order_date > to_date):
                    continue

                if completed_order_ids and str(order_data["orderNumber"]) in completed_order_ids:
                    continue

                tasks.append(self.get_order(sem, order_data, office))
            if tasks:
                orders = await asyncio.gather(*tasks, return_exceptions=True)
                return [Order.from_dict(order) for order in orders if isinstance(order, dict)]
            else:
                return []

    async def get_product_detail_as_dict(self, product_id, product_url) -> dict:
        json_data = {
            "variables": {
                "skuValues": product_id,
                "withAccessories": False,
                "withPrice": False,
            },
            "query": PRODUCT_DETAIL_QUERY,
        }

        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce", headers=ORDER_HEADERS, json=json_data
        ) as resp:
            res = await resp.json()
            product = res["data"]["product"]
            return {
                "product_id": product_id,
                "name": product["productName"],
                "url": product_url,
                "images": [{"image": product_image["source"]} for product_image in product["images"]],
                "category": product["url"].split("/")[3:],
                "price": product["catalogPrice"],
                "vendor": self.vendor.to_dict(),
            }

    async def get_product_description_as_dict(self, product_url) -> dict:
        async with self.session.get(product_url) as resp:
            res = Selector(text=await resp.text())
            return {"description": res.xpath("//section[@id='productOverview']//p/text()").extract_first()}

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        if perform_login:
            await self.login()

        tasks = (
            self.get_product_detail_as_dict(product_id, product_url),
            self.get_product_description_as_dict(product_url),
        )
        result = await asyncio.gather(*tasks, return_exceptions=True)
        res = {}
        for r in result:
            if isinstance(r, dict):
                logger.debug("Got response: %s", r)
                res.update(r)
            elif isinstance(r, Exception):
                logger.warning("Got exception: %s", "".join(traceback.TracebackException.from_exception(r).format()))

        return res

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        return await self._search_products_from_table(query, page, min_price, max_price, sort_by, office_id)

    def _get_vendor_categories(self, response) -> List[ProductCategory]:
        return [
            ProductCategory(
                name=category.xpath(".//h3/text()").extract_first(),
                slug=category.attrib["href"].split("/")[-1],
            )
            for category in response.xpath("//div[contains(@class, 'category-card-grid')]//a")
        ]

    async def get_all_products_data(self):
        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce",
            headers=SEARCH_HEADERS,
            json={"query": ALL_PRODUCTS_QUERY, "variables": ALL_PRODUCTS_VARIABLE},
        ) as resp:
            res = await resp.json()
            ultradent_products = res["data"]["allProducts"]
            products = []
            for ultradent_product in ultradent_products:
                sku = ultradent_product["sku"]
                product_url = ultradent_product["url"]
                if not product_url:
                    continue
                products.append(
                    {
                        "product_id": sku,
                        # "name": product["productName"],
                        "url": f"{self.BASE_URL}{product_url}?sku={sku}",
                        "images": [
                            {
                                "image": image["source"],
                            }
                            for image in ultradent_product["images"]
                        ],
                        # "price": 0,
                        "vendor": self.vendor.to_dict(),
                        # "category": "category",
                    }
                )
            return products

    async def get_all_products(self) -> List[Product]:
        products = await self.get_all_products_data()
        tasks = (self.get_product(product["product_id"], product["url"]) for product in products[:1])
        products = await asyncio.gather(*tasks, return_exceptions=True)
        return [product for product in products if isinstance(product, Product)]

    async def save_product_to_db(self, queue: asyncio.Queue, office=None):
        while True:
            product = await queue.get()
            await sync_to_async(self.save_single_product_to_db)(product.to_dict(), office)
            await asyncio.sleep(3)
            queue.task_done()

    async def get_all_products_v2(self, office=None):
        products = await self.get_all_products_data()
        sem = asyncio.Semaphore(value=50)
        q = asyncio.Queue()
        producers = (
            self.get_product_v2(product_id=product["product_id"], product_url=product["url"], semaphore=sem, queue=q)
            for product in products
        )
        consumers = [asyncio.create_task(self.save_product_to_db(q, office)) for _ in range(50)]
        await asyncio.gather(*producers)
        await q.join()
        for c in consumers:
            c.cancel()

    async def _download_invoice(self, **kwargs) -> InvoiceFile:
        json_data = {
            "operationName": "GetOrderDetailHtml",
            "variables": {"orderNumber": kwargs["order_id"]},
            "query": GET_ORDER_DETAIL_HTML,
        }

        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce", headers=ORDER_HEADERS, json=json_data
        ) as resp:
            order_detail_html = (await resp.json())["data"]["orderHtml"]["orderDetailHtml"]
            return order_detail_html

    async def clear_cart(self):
        async with self.session.get("https://www.ultradent.com/checkout/clear-cart", headers=CLEAR_HEADERS) as resp:
            print(f"Clear Cart {resp.status}")

    async def add_to_cart(self, products):
        items = []
        for product in products:
            items.append({"sku": product["sku"], "quantity": product["quantity"]})
        variables = {"input": {"lineItems": items}}

        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce",
            headers=ADDCART_HEADERS,
            json={"query": ADD_CART_QUERY, "variables": variables},
        ) as resp:
            print(resp.status)
            return Selector(text=await resp.text())

    async def getBillingAddress(self):
        variables = {
            "withAddresses": True,
        }
        async with self.session.post(
            "https://www.ultradent.com/api/ecommerce",
            headers=BILLING_HEADERS,
            json={"query": BILLING_QUERY, "variables": variables},
        ) as resp:
            resp_json = await resp.json()
            for item in resp_json["data"]["customer"]["addresses"]:
                if item["addressType"] == "Billing":
                    return (
                        f'{item["address1"]} {item["address2"]}\n'
                        f'{item["city"]}, {item["state"]} '
                        f'{item["postalCode"]} {item["country"]}'
                    )
            return ""

    async def checkout(self):
        async with self.session.get("https://www.ultradent.com/checkout", headers=CHECKOUT_HEADERS) as resp:
            checkout_page_response_dom = Selector(text=await resp.text())
            data = {
                "PromoCode_TextBox": checkout_page_response_dom.xpath(
                    "//input[@name='PromoCode_TextBox']/@value"
                ).get(),
                "ShippingAddress.Value": checkout_page_response_dom.xpath(
                    "//input[@name='ShippingAddress.Value']/@value"
                ).get(),
                "ShippingAddress.Original": checkout_page_response_dom.xpath(
                    "//input[@name='ShippingAddress.Original']/@value"
                ).get(),
                "shippingMethod.Value": checkout_page_response_dom.xpath(
                    "//input[@name='shippingMethod.Value']/@value"
                ).get(),
                "shippingMethod.Original": checkout_page_response_dom.xpath(
                    "//input[@name='shippingMethod.Original']/@value"
                ).get(),
                "__RequestVerificationToken": checkout_page_response_dom.xpath(
                    "//input[@name='__RequestVerificationToken']/@value"
                ).get(),
                "ContinueCheckout_Button": checkout_page_response_dom.xpath(
                    "//input[@name='ContinueCheckout_Button']/@value"
                ).get(),
            }
            for index, line_item in enumerate(
                checkout_page_response_dom.xpath(
                    "//div[@class='paddedBoxContent']/ul[@class='lineItemCollection']/li[@class='lineItem']"
                )
            ):
                value_key = f"lineItems[{index}].Value"
                data[value_key] = line_item.xpath(f".//input[@name='{value_key}']/@value").get()

                original_key = f"lineItems[{index}].Original"
                data[original_key] = line_item.xpath(f".//input[@name='{original_key}']/@value").get()

                key_key = f"lineItems[{index}].Key"
                data[key_key] = line_item.xpath(f".//input[@name='{key_key}']/@value").get()

            shipping_address = "\n".join(
                checkout_page_response_dom.xpath('//address[@id="shippingAddress"]/span//text()').extract()
            )
            print("--- shipping address:\n", shipping_address.strip() if shipping_address else "")

            billing_address = await self.getBillingAddress()
            print("--- billing address:\n", billing_address.strip() if billing_address else "")

            subtotal = convert_string_to_price(
                checkout_page_response_dom.xpath(
                    '//div[@id="orderTotals"]/div[@class="subtotal"]/span[@class="value"]//text()'
                ).get()
            )
            print("--- subtotal:\n", subtotal if subtotal else "")

            shipping = checkout_page_response_dom.xpath(
                '//div[@id="orderTotals"]/div[@class="shipping"]/span[@class="value"]//text()'
            ).get()
            print("--- shipping:\n", shipping.strip() if shipping else "")

            tax = convert_string_to_price(
                checkout_page_response_dom.xpath(
                    '//div[@id="orderTotals"]/div[@class="tax"]/span[@class="value"]//text()'
                ).get()
            )
            print("--- tax:\n", tax if tax else "")

            order_total = convert_string_to_price(
                checkout_page_response_dom.xpath(
                    '//div[@id="orderTotals"]/div[@class="order-total"]/span[@class="value"]//text()'
                ).get()
            )
            print("--- order_total:\n", order_total if order_total else "")

            async with self.session.post(
                "https://www.ultradent.com/Cart/UpdateCart", headers=UPDATECART_HEADERS, data=data
            ) as resp:
                resp_text = await resp.text()
                return resp_text, subtotal, shipping, tax, order_total, shipping_address

    async def submit_order(self, response_dom):
        __RequestVerificationToken = response_dom.xpath("//input[@name='__RequestVerificationToken']/@value").get()
        data = (
            f"------WebKitFormBoundaryFK2XSoFIILacpl1Z\r\n"
            f'Content-Disposition: form-data; name="SelectedPaymentMethod"\r\n'
            f"\r\n4\r\n------WebKitFormBoundaryFK2XSoFIILacpl1Z\r\n"
            f'Content-Disposition: form-data; name="SelectedBillingAddress"\r\n\r\n'
            f"1494702\r\n------WebKitFormBoundaryFK2XSoFIILacpl1Z\r\n"
            f'Content-Disposition: form-data; name="PONumber"\r\n\r\n\r\n'
            f"------WebKitFormBoundaryFK2XSoFIILacpl1Z\r\n"
            f'Content-Disposition: form-data; name="__RequestVerificationToken"\r\n\r\n'
            f"{__RequestVerificationToken}\r\n------WebKitFormBoundaryFK2XSoFIILacpl1Z--\r\n"
        )
        resp = await self.session.post("https://www.ultradent.com/checkout/payment", headers=SUBMIT_HEADERS, data=data)
        async with self.session.get(resp.url) as redirect_resp:
            if not redirect_resp.ok:
                raise ValueError("Redirecting to review order is failed somehow!")
            print(f"{redirect_resp.url} --- {redirect_resp.status}")
            dom = Selector(text=await redirect_resp.text())
            order_num = dom.xpath('//dl[@id="orderDetails"]/dd[1]//text()').get()
            return order_num

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("Ultradent/create_order")
        try:
            await asyncio.sleep(1)
            raise Exception()
            await self.login()
            await self.clear_cart()
            await self.add_to_cart(products)
            resp_text, subtotal, shipping, tax, order_total, shipping_address = await self.checkout()
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": tax,
                "total_amount": order_total,
                "reduction_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
            }
        except:  # noqa
            print("ultradent/create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": 0,
                "total_amount": Decimal(subtotal_manual),
                "reduction_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
            }
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            },
        }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("ultradent/confirm_order")
        try:
            await self.clear_cart()
            await self.add_to_cart(products)
            resp_text, subtotal, shipping, tax, order_total, shipping_address = await self.checkout()
            if fake:
                vendor_order_detail = {
                    "retail_amount": "",
                    "savings_amount": "",
                    "subtotal_amount": subtotal,
                    "shipping_amount": shipping,
                    "tax_amount": tax,
                    "total_amount": order_total,
                    "payment_method": "",
                    "shipping_address": shipping_address,
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
                print("ultradent/confirm_order DONE")
                return {
                    **vendor_order_detail,
                    **self.vendor.to_dict(),
                }
            checkout_dom = Selector(text=resp_text)
            order_num = await self.submit_order(checkout_dom)
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": tax,
                "total_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
                "order_id": order_num,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            print("order num is ", order_num)
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }
        except:  # noqa
            print("exept")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": 0,
                "total_amount": Decimal(subtotal_manual),
                "reduction_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
                "order_id": f"{uuid.uuid4()}",
                "order_type": msgs.ORDER_TYPE_PROCESSING,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }

    async def update_cart(self, checkout_dom, shipping_option_val):
        SHIPPING_OPTIONS_XPATHS = [
            ("PromoCode_TextBox", "//input[@name='PromoCode_TextBox']/@value"),
            ("ShippingAddress.Value", "//input[@name='ShippingAddress.Value']/@value"),
            ("ShippingAddress.Original", "//input[@name='ShippingAddress.Original']/@value"),
            ("shippingMethod.Original", "//input[@name='shippingMethod.Original']/@value"),
            ("__RequestVerificationToken", "//input[@name='__RequestVerificationToken']/@value"),
        ]
        data = {name: checkout_dom.xpath(xpath).get() for name, xpath in SHIPPING_OPTIONS_XPATHS}
        data["shippingMethod.Value"] = shipping_option_val

        for index, line_item in enumerate(
            checkout_dom.xpath(
                "//div[@class='paddedBoxContent']/ul[@class='lineItemCollection']/li[@class='lineItem']"
            )
        ):
            value_key = f"lineItems[{index}].Value"
            original_key = f"lineItems[{index}].Original"
            key_key = f"lineItems[{index}].Key"
            xpaths = [
                (value_key, f"lineItems[{index}].Value"),
                (original_key, f".//input[@name='{original_key}']/@value"),
                (key_key, f".//input[@name='{key_key}']/@value"),
            ]
            for key, xpath in xpaths:
                data[key] = line_item.xpath(xpath).get()

        async with self.session.post(
            "https://www.ultradent.com/Cart/UpdateCart", headers=UPDATECART_HEADERS, data=data
        ) as response:
            response_dom = Selector(text=await response.text())
            return response_dom

    async def get_shipping_option_detail(
        self, checkout_dom, shipping_option_label, shipping_option_val, checkout_info
    ):
        review_data = {}
        if shipping_option_label == checkout_info["default_shipping_method"]:
            response_dom = checkout_dom
        else:
            response_dom = await self.update_cart(checkout_dom, shipping_option_val)

        shipping_address = "\n".join(
            [
                it.strip()
                for it in response_dom.xpath('//address[@id="shippingAddress"]/span//text()').extract()
                if it.strip()
            ]
        )
        review_data["shipping_address"] = shipping_address

        shipping_method = textParser(
            response_dom.xpath(
                '//fieldset[contains(@class, "shippingOptions")]//input[@name="shippingMethod.Value"]'
                "[@checked]/following-sibling::label"
            )
        )
        review_data["shipping_method"] = shipping_method

        shipping = textParser(
            response_dom.xpath('//div[@id="orderTotals"]/div[@class="shipping"]/span[@class="value"]')
        )
        review_data["shipping"] = shipping

        return review_data

    async def get_shipping_options(self):
        async with self.session.get(
            "https://www.ultradent.com/checkout", headers=CHECKOUT_HEADERS
        ) as checkout_page_response:
            checkout_page_response_dom = Selector(text=await checkout_page_response.text())

            shipping_options = {}
            shipping_option_eles = checkout_page_response_dom.xpath(
                '//fieldset[contains(@class, "shippingOptions")]/div'
            )
            logger.info(">>>>> Shipping Options:")
            checkout_info = {}
            for shipping_option_ele in shipping_option_eles:
                _label = textParser(shipping_option_ele.xpath("./label"))
                _val = shipping_option_ele.xpath('.//input[@name="shippingMethod.Value"]/@value').get()
                _selected = shipping_option_ele.xpath('.//input[@name="shippingMethod.Value"][@checked]')
                if _selected:
                    checkout_info["default_shipping_method"] = _label
                logger.info(f"-- {_label}: {_val}")
                shipping_options[_label] = _val
            checkout_info["shipping_options"] = {}

            return checkout_page_response_dom, shipping_options, checkout_info

    async def fetch_shipping_options(self, products: List[CartProduct]):
        await self.clear_cart()
        await self.add_to_cart(products)
        checkout_dom, shipping_options, checkout_info = await self.get_shipping_options()

        for shipping_option_label, shipping_option_val in shipping_options.items():
            logger.info(f'----- Checkout in "{shipping_option_label}" Shipping Option...')
            review_data = await self.get_shipping_option_detail(
                checkout_dom, shipping_option_label, shipping_option_val, checkout_info
            )
            review_data["shipping_value"] = shipping_option_val
            checkout_info["shipping_options"][shipping_option_label] = review_data

        return checkout_info

    async def extract_info_from_invoice_page(self, invoice_page_dom: Selector) -> InvoiceInfo:
        # parsing invoice address
        address_dom = invoice_page_dom.xpath("//div[@class='address']")
        shipping_address = address_dom[1].xpath("./span//text()").extract()
        billing_address = address_dom[0].xpath("./span//text()").extract()
        address = InvoiceAddress(
            shipping_address=concatenate_list_as_string(shipping_address),
            billing_address=concatenate_list_as_string(billing_address),
        )

        # parsing products
        invoice_products = invoice_page_dom.xpath(".//ul[@class='odr-line-list']/li[not(@class)]")
        products: List[InvoiceProduct] = []
        for invoice_product in invoice_products:
            products.append(
                InvoiceProduct(
                    product_url="",
                    product_name=invoice_product.xpath("./span[2]/text()").get(),
                    quantity=int(invoice_product.xpath("./span[3]/text()").get()),
                    unit_price=convert_string_to_price(invoice_product.xpath("./span[4]/text()").get()),
                )
            )

        # parsing order detail
        order_id = invoice_page_dom.xpath(".//article/@data-order-number").get()
        order_date = invoice_page_dom.xpath(".//span[@class='odr-date']/@datetime").get()
        order_amounts = invoice_page_dom.xpath(".//div[@class='odr-totals']/div/span[2]/text()").extract()
        order_detail = InvoiceOrderDetail(
            order_id=order_id,
            order_date=datetime.datetime.strptime(order_date, "%Y-%m-%d %H:%M:%SZ").date(),
            payment_method="",
            total_items=sum([p.quantity for p in products]),
            sub_total_amount=convert_string_to_price(order_amounts[0]),
            shipping_amount=convert_string_to_price(order_amounts[1]),
            tax_amount=convert_string_to_price(order_amounts[2]),
            total_amount=convert_string_to_price(order_amounts[3]),
        )

        return InvoiceInfo(
            address=address,
            order_detail=order_detail,
            products=products,
            vendor=InvoiceVendorInfo(name="Ultradent", logo="https://cdn.joinordo.com/vendors/ultradent.jpg"),
        )
