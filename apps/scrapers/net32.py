import asyncio
import datetime
import logging
import uuid
from decimal import Decimal
from typing import Dict, List, NamedTuple, Optional
from urllib.parse import urlparse

from aiohttp import ClientConnectorError, ClientResponse
from django.utils.dateparse import parse_datetime
from scrapy import Selector

from apps.common import messages as msgs
from apps.common.utils import (
    concatenate_list_as_string,
    convert_string_to_price,
    strip_whitespaces,
)
from apps.scrapers.base import Scraper
from apps.scrapers.errors import NetworkConnectionException, OrderFetchException
from apps.scrapers.headers.net32 import (
    CART_HEADERS,
    LOGIN_HEADERS,
    PLACE_ORDER_HEADERS,
    REVIEW_CHECKOUT_HEADERS,
    SEARCH_HEADERS,
)
from apps.scrapers.product_track import (
    FedexProductTrack,
    UPSProductTrack,
    USPSProductTrack,
)
from apps.scrapers.schema import Order, Product, ProductCategory, VendorOrderDetail
from apps.scrapers.utils import transform_exceptions
from apps.types.orders import CartProduct
from apps.types.scraper import (
    InvoiceAddress,
    InvoiceFormat,
    InvoiceInfo,
    InvoiceOrderDetail,
    InvoiceProduct,
    InvoiceType,
    InvoiceVendorInfo,
    LoginInformation,
    ProductSearch,
    SmartProductID,
)

logger = logging.getLogger(__name__)


class ShippingInfo(NamedTuple):
    tracking_link: Optional[str] = None
    tracking_number: Optional[str] = None


class Net32Scraper(Scraper):
    BASE_URL = "https://www.net32.com"
    CATEGORY_URL = "https://www.net32.com/rest/userAndCartSummary/get"
    CATEGORY_HEADERS = LOGIN_HEADERS
    INVOICE_TYPE = InvoiceType.HTML_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_ORDO_FORMAT

    async def _check_authenticated(self, response: ClientResponse) -> bool:
        res = await response.json()
        return (
            res.get("CallHeader", {}).get("StatusCode")
            and res["CallHeader"]["StatusCode"] != "SC_ERROR_BAD_LOGIN_CREDENTIALS"
        )

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        return {
            "url": f"{self.BASE_URL}/rest/user/login",
            "headers": LOGIN_HEADERS,
            "data": {
                "userName": self.username,
                "password": self.password,
                "latestTosVersion": "1",
            },
        }

    def _get_shipping_info(self, line_item, shipping_base_tracking_urls) -> ShippingInfo:
        if "manifests" not in line_item:
            return ShippingInfo()
        manifests = line_item["manifests"]
        if not manifests:
            return ShippingInfo()
        manifest = manifests[0]
        for required_field in ("shippingMethod", "trackingNumber"):
            if required_field not in manifest:
                return ShippingInfo()
        shipping_method = manifest["shippingMethod"]
        if shipping_method not in shipping_base_tracking_urls:
            return ShippingInfo()
        base_url = shipping_base_tracking_urls[shipping_method]
        tracking_number = manifest["trackingNumber"]
        tracking_link = f"{base_url}{tracking_number}"
        return ShippingInfo(tracking_link=tracking_link, tracking_number=tracking_number)

    def _transform_line_item(self, line_item, shipping_base_tracking_urls):
        shipping_info = self._get_shipping_info(line_item, shipping_base_tracking_urls)

        return {
            "product": {
                "product_id": line_item["mpId"],
                "name": line_item["mpName"],
                "description": line_item["description"],
                "url": f"{self.BASE_URL}/{line_item['detailLink']}",
                "images": [{"image": f"{self.BASE_URL}/media{line_item['mediaPath']}"}]
                if "mediaPath" in line_item
                else [],
                "category": [line_item["catName"]],
                "price": line_item["oliProdPrice"],
                "vendor": self.vendor.to_dict(),
                "status": line_item["status"],
            },
            "quantity": line_item["quantity"],
            "unit_price": line_item["oliProdPrice"],
            "status": line_item["status"],
            **shipping_info._asdict(),
        }

    def _transform_order(self, order, from_date, to_date, completed_order_ids, shipping_base_tracking_urls):
        order_date = parse_datetime(order["coTime"]).date()
        if from_date and to_date and (order_date < from_date or order_date > to_date):
            return

        order_id = str(order["id"])
        if completed_order_ids and order_id in completed_order_ids:
            return

        order_products = [
            self._transform_line_item(line_item, shipping_base_tracking_urls)
            for vendor_order in order["vendorOrders"]
            for line_item in vendor_order["lineItems"]
        ]

        shippingAdress = order["shippingAdress"]

        return {
            "order_id": order["id"],
            "total_amount": order["orderTotal"],
            "currency": "USD",
            "order_date": parse_datetime(order["creationTime"].split("T")[0]).date(),
            "status": order["status"],
            "shipping_address": {
                "address": f'{shippingAdress["Streets"][0]} {shippingAdress["City"]}',
                "region_code": shippingAdress["RegionCD"],
                "postal_code": shippingAdress["PostalCD"],
            },
            "invoice_link": f"https://www.net32.com/account/orders/invoice/{order['id']}",
            "products": order_products,
        }

    @transform_exceptions(
        {
            ClientConnectorError: NetworkConnectionException,
        },
        OrderFetchException,
    )
    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        url = f"{self.BASE_URL}/rest/order/orderHistory"
        headers = LOGIN_HEADERS.copy()
        headers["Referer"] = f"{self.BASE_URL}/account/orders"
        params = {
            "paymentSystemId": "1",
            "startPoint": "0",
            "endPoint": "100000",
            "pendingSw": "true",
            "completeSw": "true",
        }

        print("net32/get_orders")

        if perform_login:
            await self.login()

        async with self.session.get(url, headers=headers, params=params) as resp:
            res = await resp.json()

        if "Payload" not in res or "orders" not in res["Payload"]:
            return []

        shipping_base_tracking_urls = {
            shipping_method["name"]: shipping_method.get("smTrackingUrl", "")
            for shipping_method in res["Payload"]["shippingMethods"]
        }
        orders = [
            res_order
            for order in res["Payload"]["orders"]
            if (
                res_order := self._transform_order(
                    order, from_date, to_date, completed_order_ids, shipping_base_tracking_urls
                )
            )
        ]

        # TODO: use `catName` field to figure out category. Though we need to have
        # Catname -> Our Category mapping
        orders = [Order.from_dict(order) for order in orders]

        if office:
            for order in orders:
                await self.save_order_to_db(office, order=order)

        return orders

    async def get_product_category_tree(self, product_id, product_data_dict=None):
        url = f"https://www.net32.com/rest/neo/pdp/{product_id}/categories-tree"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise OrderFetchException()
            res = await resp.json()
            categories = [item["name"] for item in res]
            if product_data_dict:
                product_data_dict["category"] = categories
            return categories

    async def get_product_detail(self, product_id, product_data_dict):
        async with self.session.get(f"https://www.net32.com/rest/neo/pdp/{product_id}") as resp:
            res = await resp.json()

            product_data_dict["name"] = res["title"]
            product_data_dict["description"] = res["description"]
            product_data_dict["images"] = [{"image": f"{self.BASE_URL}/media{res['mediaPath']}"}]
            product_data_dict["price"] = res["retailPrice"]
            product_data_dict["vendor"] = self.vendor.to_dict()

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        product_data_dict = {
            "product_id": product_id,
            "url": product_url,
        }
        tasks = (
            self.get_product_detail(product_id, product_data_dict),
            self.get_product_category_tree(product_id, product_data_dict),
        )
        await asyncio.gather(*tasks, return_exceptions=True)
        return product_data_dict

    def get_products_from_search_page(self, dom) -> List[Product]:
        products = []
        products_dom = dom.xpath(
            "//div[@class='localsearch-results-container']//div[contains(@class, 'localsearch-result-wrapper')]"
        )

        for product_dom in products_dom:
            products.append(
                Product.from_dict(
                    {
                        "product_id": product_dom.attrib["data-mpid"],
                        "name": self.extract_first(
                            product_dom, ".//a[@class='localsearch-result-product-name']//text()"
                        ),
                        "description": self.extract_first(
                            product_dom, ".//div[@class='localsearch-result-product-packaging-container']//text()"
                        ),
                        "url": self.BASE_URL
                        + self.extract_first(product_dom, ".//a[@class='localsearch-result-product-name']/@href"),
                        "images": [
                            {
                                "image": self.BASE_URL
                                + self.extract_first(
                                    product_dom, ".//img[@class='localsearch-result-product-thumbnail']/@src"
                                )
                            }
                        ],
                        "price": self.extract_first(
                            product_dom, ".//ins[@class='localsearch-result-best-price']//text()"
                        ),
                        "vendor": self.vendor.to_dict(),
                    }
                )
            )

        return products

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        url = f"{self.BASE_URL}/search"
        page_size = 60
        params = {
            "q": query,
            "page": page,
            "sortby": "price",
        }
        if min_price:
            params["filter.price.low"] = min_price
        if max_price:
            params["filter.price.high"] = max_price

        async with self.session.get(url, headers=SEARCH_HEADERS, params=params) as resp:
            response_url = str(resp.url)
            search_result_page = "search" in response_url
            response_dom = Selector(text=await resp.text())

        if search_result_page:
            try:
                total_size_str = response_dom.xpath(
                    "//p[@class='localsearch-result-summary-paragraph']/strong/text()"
                ).get()
                total_size = int(self.remove_thousands_separator(total_size_str))
            except (AttributeError, ValueError, TypeError):
                total_size = 0

            products = self.get_products_from_search_page(response_dom)
        else:
            product_id = response_url.split("-")[-1]
            product = await self.get_product_as_dict(product_id, response_url)
            products = [Product.from_dict(product)]
            total_size = 1

        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": products,
            "last_page": page_size * page >= total_size,
        }

    async def add_product_to_cart(self, product: CartProduct, perform_login=False) -> dict:
        if perform_login:
            await self.login()

        data = [
            {
                "mpId": product["product_id"],
                "quantity": product["quantity"],
            }
        ]

        async with self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation", headers=CART_HEADERS, json=data
        ) as resp:
            cart_res = await resp.json()
            for vendor in cart_res["payload"]["vendorOrders"]:
                for vendor_product in vendor["products"]:
                    if str(vendor_product["mpId"]) == str(product["product_id"]):
                        return {
                            "product_id": product["product_id"],
                            "unit_price": vendor_product["unitPrice"],
                        }

    async def add_products_to_cart(self, products: List[CartProduct]):
        data = [
            {
                "mpId": product["product_id"],
                "quantity": product["quantity"],
            }
            for product in products
        ]

        await self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation", headers=CART_HEADERS, json=data
        )

    async def remove_product_from_cart(
        self, product_id: SmartProductID, perform_login: bool = False, use_bulk: bool = True
    ):
        if perform_login:
            await self.login()

        async with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            cart_res = await resp.json()
            data = [
                {
                    "mpId": product["mpId"],
                    "vendorProductId": product["vendorProductId"],
                    "minimumQuantity": product["minimumQuantity"],
                    "quantity": 0,
                }
                for vendor in cart_res["payload"]["vendorOrders"]
                for product in vendor["products"]
                if str(product["mpId"]) == str(product_id)
            ]
        await self.session.post("https://www.net32.com/rest/shoppingCart/modify/rev2", headers=CART_HEADERS, json=data)

    async def clear_cart(self):
        async with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            cart_res = await resp.json()
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
        await self.session.post("https://www.net32.com/rest/shoppingCart/modify/rev2", headers=CART_HEADERS, json=data)

    async def review_order(self) -> VendorOrderDetail:
        async with self.session.get("https://www.net32.com/checkout", headers=REVIEW_CHECKOUT_HEADERS) as resp:
            res = Selector(text=await resp.text())
            retail_amount = self.remove_thousands_separator(
                self.extract_first(res, "//table[@class='order-summary-subtotal-table']//tr[1]/td/text()")
            )
            savings_amount = self.extract_price(
                self.remove_thousands_separator(
                    self.extract_first(res, "//table[@class='order-summary-subtotal-table']//tr[2]/td/text()")
                )
            )
            subtotal_amount = self.remove_thousands_separator(
                self.extract_first(res, "//table[@class='order-summary-subtotal-table']//tr[3]/td/text()")
            )
            shipping_amount = self.remove_thousands_separator(
                self.extract_first(res, "//table[@class='order-summary-subtotal-table']//tr[4]/td/text()")
            )
            tax_amount = self.remove_thousands_separator(
                self.extract_first(res, "//table[@class='order-summary-subtotal-table']//tr[5]/td/text()")
            )
            total_amount = self.remove_thousands_separator(
                self.extract_first(
                    res,
                    "//table[@class='order-summary-grandtotal-table']"
                    "//span[@class='order-summary-grandtotal-value']/text()",
                )
            )
            payment_method = self.merge_strip_values(res, "//dl[@id='order-details-payment']/dd[1]/strong//text()")
            shipping_address = self.extract_first(res, "//dl[@id='order-details-shipping']/dd[2]/text()")

            return VendorOrderDetail.from_dict(
                {
                    "retail_amount": retail_amount,
                    "savings_amount": savings_amount,
                    "subtotal_amount": subtotal_amount,
                    "shipping_amount": shipping_amount,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "reduction_amount": total_amount,
                    "payment_method": payment_method,
                    "shipping_address": shipping_address,
                }
            )

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("net32/create_order")
        vendor_slug: str = self.vendor.slug
        try:
            await self.clear_cart()
            await self.add_products_to_cart(products)
            vendor_order_detail = await self.review_order()
            print("net32/create_order DONE")
            return {
                vendor_slug: {
                    **vendor_order_detail.to_dict(),
                    **self.vendor.to_dict(),
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
            }
        except Exception:
            print("net32/create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = VendorOrderDetail(
                retail_amount=Decimal(0),
                savings_amount=Decimal(0),
                subtotal_amount=Decimal(subtotal_manual),
                shipping_amount=Decimal(0),
                tax_amount=Decimal(0),
                total_amount=Decimal(subtotal_manual),
                reduction_amount=Decimal(subtotal_manual),
                payment_method="",
                shipping_address="",
            )
            return {vendor_slug: {**vendor_order_detail.to_dict(), **self.vendor.to_dict()}}

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("net32/confirm_order")
        result = await self.create_order(products)
        if fake:
            print("net32/confirm_order DONE")
            return {**result[self.vendor.slug], "order_id": f"{uuid.uuid4()}", "order_type": msgs.ORDER_TYPE_ORDO}
        try:
            async with self.session.post(
                "https://www.net32.com/checkout/confirmation", headers=PLACE_ORDER_HEADERS
            ) as resp:
                response_dom = Selector(text=await resp.text())
                order_id = response_dom.xpath(
                    "//h2[@class='checkout-confirmation-order-number-header']//a/text()"
                ).get()
            return {**result[self.vendor.slug], "order_id": order_id}
        except Exception:
            print("benco/confirm_order Except")
            return {
                **result[self.vendor.slug],
                "order_type": msgs.ORDER_TYPE_PROCESSING,
                "order_id": f"{uuid.uuid4()}",
            }

    def _get_vendor_categories(self, response) -> List[ProductCategory]:
        return [
            ProductCategory(
                name=category["CatName"],
                slug=category["url"].split("/")[-1],
            )
            for category in response["TopCategories"]
        ]

    async def track_product(self, order_id, product_id, tracking_link, tracking_number, perform_login=False):
        parsed_url = urlparse(tracking_link)
        netloc = parsed_url.netloc
        if netloc == "www.fedex.com":
            product_track = FedexProductTrack(session=self.session)
            return await product_track.track_product(tracking_number)
        elif netloc == "wwwapps.ups.com":
            product_track = UPSProductTrack(session=self.session)
            return await product_track.track_product(tracking_number)
        elif netloc == "tools.usps.com":
            product_track = USPSProductTrack(session=self.session)
            return await product_track.track_product(tracking_number)

    #
    # async def track_products(self, products_track: List[ProductTrack]):
    #     # group by shipping
    #     fedex_tracking_numbers = []
    #     ups_tracking_numbers = []
    #     usps_tracking_numbers = []
    #
    #     for product_track in products_track:
    #         tracking_link = product_track["tracking_link"]
    #         parsed_url = urlparse(tracking_link)
    #         parsed_url_netloc = parsed_url.netloc
    #         if parsed_url_netloc == "www.fedex.com":
    #             fedex_tracking_numbers.append(tracking_link)
    #         elif parsed_url_netloc == "wwwapps.ups.com":
    #             ups_tracking_numbers.append(tracking_link)
    #         elif parsed_url_netloc == "tools.usps.com":
    #             usps_tracking_numbers.append(tracking_link)
    #
    #     if fedex_tracking_numbers:
    #         return await self.track_product_from_fedex(tracking_number)

    async def extract_info_from_invoice_page(self, invoice_page_dom: Selector) -> InvoiceInfo:
        # parsing invoice address
        shipping_address = invoice_page_dom.xpath("(//div[@class='shipping-info'])[1]//text()").extract()
        address = InvoiceAddress(shipping_address=concatenate_list_as_string(shipping_address), billing_address="")

        # parsing products
        invoice_products = invoice_page_dom.xpath("//div[@class='product-row1']")
        products: List[InvoiceProduct] = []
        for invoice_product in invoice_products:
            quantity = int(
                strip_whitespaces(invoice_product.xpath(".//div[@class='product-column']/span/text()").get())
            )
            total_price = convert_string_to_price(invoice_product.xpath(".//div[@class='price-column']/text()").get())
            products.append(
                InvoiceProduct(
                    product_url="",
                    product_name=invoice_product.xpath(".//div[@class='product-title']//text()").get(),
                    quantity=quantity,
                    unit_price=total_price / quantity,
                )
            )

        # parsing order detail
        order_id = invoice_page_dom.xpath(".//h1[contains(@class, 'order-number')]/text()").get()
        order_date = strip_whitespaces(invoice_page_dom.xpath(".//div[@class='order-date']/text()").get())
        order_amounts = invoice_page_dom.xpath(".//dl[@class='cost-breakdown']/dd/text()").extract()
        sub_total_amount = convert_string_to_price(order_amounts[0])
        shipping_amount = convert_string_to_price(order_amounts[1])
        total_amount = convert_string_to_price(order_amounts[-1])
        order_detail = InvoiceOrderDetail(
            order_id=order_id,
            order_date=datetime.datetime.strptime(order_date, "%B %d, %Y").date(),
            payment_method=invoice_page_dom.xpath(".//span[@class='card-brand']/text()").get(),
            total_items=sum([p.quantity for p in products]),
            sub_total_amount=sub_total_amount,
            shipping_amount=shipping_amount,
            tax_amount=total_amount - sub_total_amount - shipping_amount,
            total_amount=total_amount,
        )

        return InvoiceInfo(
            address=address,
            order_detail=order_detail,
            products=products,
            vendor=InvoiceVendorInfo(name="Net 32", logo="https://cdn.joinordo.com/vendors/net_32.jpg"),
        )
