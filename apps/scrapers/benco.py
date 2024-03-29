import asyncio
import datetime
import json
import logging
import re
import time
import traceback
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypedDict

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.headers.benco import (
    ADD_CART_HEADERS,
    CLEAR_CART_HEADERS,
    CONFIRM_ORDER_HEADERS,
    CREATE_ORDER_HEADERS,
    LOGIN_HEADERS,
    ORDER_DETAIL_HEADERS,
    ORDER_HISTORY_HEADERS,
    POST_LOGIN_HEADERS,
    PRE_LOGIN_HEADERS,
    PRICE_SEARCH_HEADERS,
    REMOVE_PRODUCT_CART_HEADERS,
    SEARCH_HEADERS,
    SHIPPING_OPTION_DETAIL_HEADERS,
)
from apps.scrapers.schema import Order, Product, ProductCategory, VendorOrderDetail
from apps.scrapers.utils import catch_network, semaphore_coroutine
from apps.types.orders import CartProduct, VendorCartProduct
from apps.types.scraper import (
    InvoiceFile,
    InvoiceFormat,
    InvoiceType,
    LoginInformation,
    ProductSearch,
    SmartProductID,
)

CERTIFICATE_BASE_PATH = Path(__file__).parent.resolve()
logger = logging.getLogger(__name__)


def textParser(element):
    if not element:
        return ""
    text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
    return text.strip() if text else ""


class CartProductDetail(TypedDict):
    product_id: str
    quantity: str
    name: str
    unit_price: Decimal
    total_price: Decimal
    item_id: str
    token: str


class BencoScraper(Scraper):
    BASE_URL = "https://shop.benco.com"
    CATEGORY_URL = "https://shop.benco.com/Browse"
    INVOICE_TYPE = InvoiceType.PDF_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT

    async def _get_check_login_state(self) -> Tuple[bool, dict]:
        async with self.session.get(f"{self.BASE_URL}/Login/Login", headers=PRE_LOGIN_HEADERS) as resp:
            text = await resp.text()
            url = str(resp.url)
            try:
                modelJson = (
                    text.split("id='modelJson'")[1]
                    .split("</script>", 1)[0]
                    .split(">", 1)[1]
                    .replace("&quot;", '"')
                    .strip()
                )
                idsrv_xsrf = json.loads(modelJson)["antiForgery"]["value"]
                return False, {"url": url, "idsrv_xsrf": idsrv_xsrf}
            except IndexError:
                return True, {}

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        async with self.session.get("https://shop.benco.com/Login/Login", headers=PRE_LOGIN_HEADERS) as resp:
            text = await resp.text()
            login_url = str(resp.url)
            try:
                model_json = (
                    text.split("id='modelJson'")[1]
                    .split("</script>", 1)[0]
                    .split(">", 1)[1]
                    .replace("&quot;", '"')
                    .strip()
                )
                idsrv_xsrf = json.loads(model_json)["antiForgery"]["value"]

                headers = LOGIN_HEADERS.copy()
                headers["Referer"] = login_url
                return {
                    "url": login_url,
                    "headers": headers,
                    "data": {
                        "idsrv.xsrf": idsrv_xsrf,
                        "username": self.username,
                        "password": self.password,
                    },
                }
            except (IndexError, KeyError):
                pass

    @catch_network
    async def _check_authenticated(self, resp: ClientResponse) -> bool:
        response_dom = Selector(text=await resp.text())
        id_token = response_dom.xpath("//input[@name='id_token']/@value").get()
        scope = response_dom.xpath("//input[@name='scope']/@value").get()
        state = response_dom.xpath("//input[@name='state']/@value").get()
        session_state = response_dom.xpath("//input[@name='session_state']/@value").get()
        if not any([id_token, scope, state, session_state]):
            return False

        data = {"id_token": id_token, "scope": scope, "state": state, "session_state": session_state}
        time.sleep(1)
        await self.session.post("https://shop.benco.com/signin-oidc", headers=POST_LOGIN_HEADERS, data=data)
        return True

    async def _after_login_hook(self, response: ClientResponse):
        pass

    def parse_order_date(self, value):
        if "on" not in value:
            return None
        return datetime.datetime.strptime(value.split("on", 1)[1].strip("| "), "%B %d, %Y").date()

    @semaphore_coroutine
    async def get_order(self, sem, order_detail_link, referer, office=None) -> dict:
        headers = ORDER_DETAIL_HEADERS.copy()
        headers["Referer"] = referer

        order = {"products": []}
        logger.debug("Getting order info from %s", order_detail_link)
        async with self.session.get(f"{self.BASE_URL}{order_detail_link}", headers=headers) as resp:
            response_dom = Selector(text=await resp.text())
        order["order_date"] = self.parse_order_date(
            textParser(response_dom.xpath("//p[@class='order-details-summary']/span[1]"))
        )
        order["order_id"] = order_detail_link.split("/")[-1]

        for order_container in response_dom.xpath("//div[contains(@class, 'order-container')]"):
            panel_heading = order_container.xpath("./div[@class='panel-heading']/h3[2]")

            if not panel_heading:
                order["shipping_address"] = {
                    "address": textParser(
                        order_container.xpath(".//div[contains(@class, 'account-details-panel')]/div[2]/p")
                    ),
                }
                order["total_amount"] = textParser(
                    order_container.xpath(".//div[contains(@class, 'account-details-panel')]/div[4]/p")
                )
                order["status"] = textParser(
                    order_container.xpath(".//div[contains(@class, 'account-details-panel')]/div[5]/p")
                )
                order["currency"] = "USD"
            else:
                invoice_link = panel_heading.xpath(".//a/@href").get()
                if invoice_link:
                    order["invoice_link"] = f"https://shop.benco.com{invoice_link}"
                for product_row in order_container.xpath("./ul[@class='list-group']/li[@class='list-group-item']"):
                    if product_row.xpath(".//h4"):
                        continue
                    product_id = textParser(
                        product_row.xpath(
                            ".//div[contains(@class, 'product-details')]/p[contains(text(), 'Product #:')]"
                        )
                    )
                    product_id = product_id.split("Product #:")[1].strip() if product_id else None
                    product_name = textParser(
                        product_row.xpath(".//div[contains(@class, 'product-details')]/strong/a")
                    )
                    product_url = product_row.xpath(".//div[contains(@class, 'product-details')]/strong/a/@href").get()
                    # product image is one in order history we try to fetch images on product detail
                    # product_images = product_row.xpath(".//img/@src").extract()
                    product_price = textParser(
                        product_row.xpath(
                            ".//div[contains(@class, 'product-details')]/p[contains(text(), 'Net Price:')]"
                        )
                    )
                    product_price = product_price.split("Net Price:")[1].strip() if product_price else 0
                    quantity = textParser(
                        product_row.xpath(
                            ".//div[contains(@class, 'product-details')]/p[contains(text(), 'Quantity:')]"
                        )
                    )
                    quantity = quantity.split("Quantity:")[1].strip() if quantity else 0
                    order["products"].append(
                        {
                            "product": {
                                "product_id": product_id,
                                "name": product_name,
                                "description": "",
                                "url": product_url,
                                "images": [],
                                "category": "",
                                "price": product_price,
                                "vendor": self.vendor.to_dict(),
                                # "images": [{"image": product_image for product_image in product_images}],
                            },
                            "unit_price": product_price,
                            "quantity": quantity,
                        }
                    )

        await self.get_missing_products_fields(
            order["products"],
            fields=(
                "description",
                "images",
                "category",
            ),
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
        url = f"{self.BASE_URL}/PurchaseHistory/NewIndex"
        if perform_login:
            await self.login()

        # TODO: pagination not tested
        page_number = 0
        orders: List[Order] = []

        while True:
            if from_date and to_date:
                params = {
                    "DateRangeOption": "CustomRange",
                    "OrderStatus": "all",
                    "PageNumber": page_number,
                    "StartDate": from_date.isoformat(),
                    "EndDate": to_date.isoformat(),
                }
            else:
                params = {
                    "PageNumber": page_number,
                }
            logger.debug("Params = %s", params)
            async with self.session.get(url, headers=ORDER_HISTORY_HEADERS, params=params) as resp:
                text = await resp.text()
            page_orders = await self.get_page_orders(text, sem, url, office)
            if not page_orders:
                break
            orders.extend(page_orders)
            page_number += 1
        return orders

    async def get_page_orders(self, text, sem, url, office):
        response_dom = Selector(text=text)
        tasks = []
        for order_detail_link in response_dom.xpath(
            "//div[@class='order-history']//div[contains(@class, 'order-container')]/"
            "div[@class='panel-heading']//a[contains(@href, 'OrderDetail')]/@href"
        ).extract():
            if not order_detail_link:
                continue
            tasks.append(self.get_order(sem, order_detail_link, url, office))
        orders = []
        for task in tasks:
            try:
                result = await task
            except Exception as e:
                result = e
            orders.append(result)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        logger.debug("Getting product as dict %s %s", product_id, product_url)
        if not product_url:
            logger.debug("Invalid parameters %s %s", product_id, product_url)
            return {}

        if perform_login:
            await self.login()

        async with self.session.get(product_url) as resp:
            res = Selector(text=await resp.text())
        product_name = self.extract_first(res, ".//h3[@class='product-name']/text()")
        product_description = self.extract_first(res, ".//p[@class='product-description']/text()")
        product_images = res.xpath(".//div[@class='thumbnail']/img/@src").extract()
        if not product_images:
            product_images = res.xpath(".//div[@id='activeImageArea']/img/@src").extract()

        product_price = self.extract_first(res, ".//div[@class='product-detail-actions-wrapper']/h3/text()")
        product_category = res.xpath(".//div[@class='breadcrumb-bar']/ul/li/a/text()").extract()[1:]
        return {
            "product_id": product_id,
            "name": product_name,
            "description": product_description,
            "url": product_url,
            "images": [{"image": product_image} for product_image in product_images],
            "category": product_category,
            "price": product_price,
            "vendor": self.vendor.to_dict(),
        }

    async def get_product_prices(self, product_ids, perform_login=False, **kwargs) -> Dict[str, Decimal]:
        if perform_login:
            await self.login()

        product_prices = {}
        data = {"productNumbers": product_ids, "pricePartialType": "ProductPriceRow"}
        headers = PRICE_SEARCH_HEADERS.copy()
        headers["Referer"] = kwargs.get("Referer")
        async with self.session.post(
            "https://shop.benco.com/Search/GetPricePartialsForProductNumbers",
            headers=headers,
            json=data,
        ) as resp:
            res = await resp.json()
            for product_id, row in res.items():
                row_dom = Selector(text=row)
                product_prices[product_id] = row_dom.xpath("//h4[@class='selling-price']").attrib["content"]
        return product_prices

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        page_size = 24
        data = {
            "Page": str(page),
            "Terms": query,
            "SortBy": "",
            "GroupSimilarItems": "True",
            "PromoKey": "",
            "ProductLine": "",
            "IsCompleteCart": "False",
            "IsGeneralSuggestion": "False",
            "Source": "",
            "ShowResultsAsGrid": "False",
        }
        products = []
        async with self.session.post(f"{self.BASE_URL}/Search/ChangePage", headers=SEARCH_HEADERS, data=data) as resp:
            url = str(resp.url)
            response_dom = Selector(text=await resp.text())
            total_size = int(
                response_dom.xpath("//ul[contains(@class, 'search-breadcrumbs')]/li[last()]//h6//text()")
                .get()
                .split("of", 1)[1]
                .strip()
            )
            products_dom = response_dom.xpath("//div[@class='product-list']/div[contains(@class, 'product-row')]")
            for product_dom in products_dom:
                additional_products = product_dom.xpath(".//div[contains(@class, 'additional-products')]")
                if additional_products:
                    product_image = product_dom.xpath(".//div[contains(@class, 'summary-row')]//img/@src").get()
                    product_description = self.extract_first(product_dom, ".//p[@class='description']/text()")
                    for additional_product in additional_products.xpath(".//tr"):
                        product_id = self.extract_first(additional_product, ".//td[@itemprop='sku']/text()")
                        name = self.extract_first(additional_product, ".//td[@class='product-name']/span/text()")
                        product_url = additional_product.attrib["data-click-href"]
                        product_url = f"{self.BASE_URL}{product_url}" if product_url else None
                        products.append(
                            {
                                "product_id": product_id,
                                "name": name,
                                "description": product_description,
                                "url": product_url,
                                "images": [
                                    {
                                        "image": product_image,
                                    }
                                ],
                                "price": Decimal(0),
                                "vendor_id": self.vendor.to_dict(),
                            }
                        )
                else:
                    product_id = self.extract_first(
                        product_dom, "./div[contains(@class, 'product-data-area')]//span[@itemprop='sku']//text()"
                    )
                    product_url = self.extract_first(
                        product_dom,
                        "./div[contains(@class, 'product-data-area')]/div[contains(@class, 'title')]//a/@href",
                    )
                    product_url = f"{self.BASE_URL}{product_url}" if product_url else None
                    name = self.extract_first(
                        product_dom, "./div[contains(@class, 'product-data-area')]//h4[@itemprop='name']//text()"
                    )
                    product_image = product_dom.xpath("./div[contains(@class, 'product-image-area')]/img/@src").get()
                    product_description = self.extract_first(product_dom, ".//p/text()")
                    products.append(
                        {
                            "product_id": product_id,
                            "name": name,
                            "description": product_description,
                            "url": product_url,
                            "images": [
                                {
                                    "image": product_image,
                                }
                            ],
                            "price": Decimal(0),
                            "vendor": self.vendor.to_dict(),
                        }
                    )

        kwargs = {"Referer": url}
        product_prices = await self.get_product_prices([product["product_id"] for product in products], **kwargs)
        for product in products:
            product["price"] = product_prices[product["product_id"]]

        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": [Product.from_dict(product) for product in products],
            "last_page": page_size * page >= total_size,
        }

    def _get_vendor_categories(self, response) -> List[ProductCategory]:
        return [
            ProductCategory(
                name=category.xpath("./h4/text()").extract_first(),
                slug=category.attrib["href"].split("/")[-1],
            )
            for category in response.xpath("//div[@class='tab-header']/a")
        ]

    async def get_cart(self) -> Tuple[str, str, List[CartProductDetail]]:
        for tryy in range(3):
            try:
                time.sleep(1)
                async with self.session.get("https://shop.benco.com/Cart") as resp:
                    cart_page_dom = Selector(text=await resp.text())
                break
            except Exception as e:
                if tryy == 2:
                    logger.error(str(e))


        cart_id = cart_page_dom.xpath("//table[@id='cart_items_table']//tbody//input[@name='cartId']/@value").get()
        request_verification_token = cart_page_dom.xpath(
            "//table[@id='cart_items_table']//tbody//input[@name='__RequestVerificationToken']/@value"
        ).get()

        products = []
        for product_row in cart_page_dom.xpath("//table[@id='cart_items_table']/tbody[@class='cart-items']/tr"):
            product_row_classes = product_row.xpath(".//@class").get()
            if not product_row_classes or "hidden" in product_row_classes:
                continue

            product_id = product_row.xpath(".//td[4]/a//text()").get()
            quantity = product_row.xpath(".//td[3]//input[@name='Quantity']//@value").get()
            name = product_row.xpath(".//td[5]/b//text()").get()
            unit_price = product_row.xpath(".//td[7]//text()").get()
            total_price = product_row.xpath(".//td[8]//text()").get()
            item_id = (item_id := product_row.xpath(".//input[@name='ItemId']/@value").get()) and item_id.strip()
            token = product_row.xpath(
                ".//form[contains(@action, 'UpdateItemQuantity')]/input[@name='__RequestVerificationToken']/@value"
            ).get()

            products.append(
                CartProductDetail(
                    product_id=product_id,
                    quantity=quantity,
                    name=name,
                    unit_price=unit_price,
                    total_price=total_price,
                    item_id=item_id,
                    token=token,
                )
            )

        return cart_id, request_verification_token, products

    async def _add_product_to_cart(
        self, product: CartProduct, cart_id, request_verification_token
    ) -> VendorCartProduct:
        data = {
            "__RequestVerificationToken": request_verification_token,
            "cartId": cart_id,
            "searchId": "",
            "quantity": str(product["quantity"]),
            "prodNum": product["product_id"],
        }
        for tryy in range(3):
            try:
                time.sleep(1)
                await self.session.post("https://shop.benco.com/Cart/AddQOEItem", headers=ADD_CART_HEADERS, data=data)
                break
            except Exception as e:
                if tryy == 2:
                    logger.error(str(e))
    async def add_product_to_cart(self, product: CartProduct, perform_login=False) -> VendorCartProduct:
        if perform_login:
            await self.login()

        cart_id, request_verification_token, _ = await self.get_cart()
        await self._add_product_to_cart(product, cart_id, request_verification_token)
        _, _, cart_products = await self.get_cart()
        return [
            VendorCartProduct(product_id=cart_product["product_id"], unit_price=cart_product["unit_price"])
            for cart_product in cart_products
            if product["product_id"] == product["product_id"]
        ][0]

    async def add_products_to_cart(self, products: List[CartProduct],cart_id, request_verification_token) -> List[VendorCartProduct]:
        logger.info("Adding products to cart: %s", products)
        try:
            # cart_id, request_verification_token, _ = await self.get_cart()
            tasks = (self._add_product_to_cart(product, cart_id, request_verification_token) for product in products)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    tb = "\n".join(traceback.format_exception(None, result, result.__traceback__))
                    logger.error(f"{tb}")
            _, _, cart_products = await self.get_cart()
            return [
                VendorCartProduct(product_id=cart_product["product_id"], unit_price=cart_product["unit_price"])
                for cart_product in cart_products
            ]
        except Exception as e:
            logger.error(f"add_products_to_cart:{str(e)}")
    async def remove_product_from_cart(
        self, product_id: SmartProductID, perform_login: bool = False, use_bulk: bool = True
    ):
        if perform_login:
            await self.login()
        cart_id, request_verification_token, cart_products = await self.get_cart()
        product = [cart_product for cart_product in cart_products if cart_product["product_id"] == product_id][0]

        data = {"__RequestVerificationToken": product["token"], "ItemId": product["item_id"], "CartId": cart_id}

        await self.session.post(
            "https://shop.benco.com/Cart/RemoveItem",
            headers=REMOVE_PRODUCT_CART_HEADERS,
            data=data,
        )

    async def clear_cart(self):
        logger.info("Clearing cart")
        try:
            cart_id, request_verification_token, products = await self.get_cart()
            time.sleep(2)
            params = {
                "cartId": cart_id,
            }
            for tryy in range(3):
                try:
                    time.sleep(1)
                    resp = await self.session.get(
                        "https://shop.benco.com/Cart/RemoveAllItems", headers=CLEAR_CART_HEADERS, params=params
                    )
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
            logger.info("Got response status %s", resp.status)
            return cart_id, request_verification_token
        except Exception as e:
            logger.error(f"clear_cart:{str(e)}")
    async def checkout(self) -> Tuple[str, str, VendorOrderDetail]:
        logger.info("Checking out...")
        try:
            time.sleep(2)
            cart_id, request_verification_token, cart_products = await self.get_cart()
            params = {
                "cartId": cart_id,
            }
            for tryy in range(3):
                try:
                    time.sleep(1)
                    async with self.session.get(
                        "https://shop.benco.com/Checkout/BeginCheckout",
                        params=params,
                        headers=CREATE_ORDER_HEADERS,
                        # ssl=self._ssl_context,
                    ) as resp:
                        text = await resp.text()
                        logger.info("BeginCheckout: status %s", resp.status)
                        response_dom = Selector(text=text)
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
            time.sleep(2)
            for tryy in range(3):
                try:
                    async with self.session.get(f"https://shop.benco.com/Cart/TaxesAndFees/{cart_id}") as resp:
                        cart_status_dom = Selector(text=await resp.text())
                    logger.info('Cart/TaxesAndFees:Success')
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
                # billing_address = self.merge_strip_values(response_dom, "//fieldset[contains(@class, 'bill-to')]/text()")
            try:
                shipping_address = self.merge_strip_values(response_dom, "//fieldset[contains(@class, 'ship-to')]/text()")
                shipping_method = self.merge_strip_values(
                    response_dom, "//fieldset[contains(@class, 'shipping-method')]/text()"
                )

                payment_method = self.merge_strip_values(
                    response_dom, "//fieldset[contains(@class, 'payment-method')]/text()"
                )
                subtotal_amount = self.remove_thousands_separator(
                    self.extract_first(cart_status_dom, "//th[@id='item_subtotal_value']/p/text()")
                )
                shipping_amount = self.remove_thousands_separator(
                    self.extract_first(cart_status_dom, "//tr[3]/td[last()]//text()")
                )
                tax_amount = self.remove_thousands_separator(
                    self.extract_first(cart_status_dom, "//tr[4]/td[last()]//text()")
                )
                savings_amount = self.remove_thousands_separator(
                    self.extract_first(cart_status_dom, "//tr[5]/td[last()]//text()")
                )
                total_amount = self.remove_thousands_separator(
                    self.extract_first(cart_status_dom, "//tr[last()]/th[last()]/p/text()")
                )
                return (
                    cart_id,
                    request_verification_token,
                    VendorOrderDetail(
                        retail_amount=Decimal(0),
                        savings_amount=Decimal(savings_amount),
                        subtotal_amount=Decimal(subtotal_amount),
                        shipping_amount=Decimal(shipping_amount),
                        tax_amount=Decimal(tax_amount),
                        total_amount=Decimal(total_amount),
                        payment_method=payment_method,
                        shipping_address=shipping_address,
                        reduction_amount=Decimal(total_amount)

                    ),


                )
            except Exception as e:
                pass
        except Exception as e:
            logger.error(str(e))
    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        try:
            await asyncio.sleep(0.3)
            raise Exception()
            await self.login()
            await self.clear_cart()
            res = await self.add_products_to_cart(products)
            if len(res) < 1:
                raise Exception
            _, _, vendor_order_detail = await self.checkout()
        except Exception:
            print("Benco/create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = VendorOrderDetail(
                retail_amount=Decimal(0),
                savings_amount=Decimal(0),
                subtotal_amount=Decimal(subtotal_manual),
                shipping_amount=Decimal(0),
                tax_amount=Decimal(0),
                total_amount=Decimal(subtotal_manual),
                payment_method="",
                shipping_address="",
                reduction_amount=Decimal(subtotal_manual),
            )
        finally:
            vendor_slug: str = self.vendor.slug
            return {
                vendor_slug: {
                    **vendor_order_detail.to_dict(),
                    **self.vendor.to_dict(),
                },
            }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        try:
            cart_id, request_verification_token = await self.clear_cart()
            time.sleep(2)
            res = await self.add_products_to_cart(products,cart_id, request_verification_token)
            if len(res) < 1:
                logger.error("No products in cart")
                raise Exception

            checkout_dom, shipping_options, checkout_info, cart_id = await self.get_shipping_options()
            if shipping_method:
                shipping_option_val = shipping_options[shipping_method]
            else:
                shipping_option_val = shipping_options['Truck']
            review_data = await self.changing_shipping_method(checkout_dom, cart_id, shipping_option_val)
            cart_id, request_verification_token, vendor_order_detail = await self.checkout()

            if fake:
                return {
                    **vendor_order_detail.to_dict(),
                    **self.vendor.to_dict(),
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
            data = {"__RequestVerificationToken": request_verification_token}
            headers = CONFIRM_ORDER_HEADERS.copy()
            headers["Referer"] = f"https://shop.benco.com/Checkout/BeginCheckout?cartId={cart_id}"

            for tryy in range(10):
                try:
                    time.sleep(2)
                    async with self.session.post(
                        "https://shop.benco.com/Checkout/Confirm", headers=headers, data=data
                    ) as resp:
                        response_text = await resp.text()
                        response_dom = Selector(text=response_text)
                        try:
                            order_id = response_dom.xpath("//h4//span[@class='alt-dark-text']//text()").get()
                        except:
                            order_id = None
                        if order_id:
                            logger.info('Order placed')
                            break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
            await self.clear_cart()
            return {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
                "order_id": order_id,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
        except Exception as e:
            logger.error(f"benco/confirm_order Exception:{str(e)}")
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
            return {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
                "order_id": f"{uuid.uuid4()}",
                "order_type": msgs.ORDER_TYPE_PROCESSING,
            }

    async def _download_invoice(self, **kwargs) -> InvoiceFile:
        async with self.session.get(kwargs["invoice_link"]) as resp:
            return await resp.content.read()

    async def shipping_info(self, CartId):
        time.sleep(2)
        async with self.session.get(f"https://shop.benco.com/Cart/TaxesAndFeesEdit/{CartId}") as resp:
            cart_dom = Selector(text=await resp.text())
            shipping = textParser(cart_dom.xpath('//td[contains(text(), "Shipping")]/following-sibling::td[1]'))
            return shipping

    async def changing_shipping_method(self, checkout_dom, cart_id, shipping_option_val):
        try:
            review_data = {}

            data = {
                "HeaderUpdated": "true",
                "OrderId": checkout_dom.xpath('//input[@name="OrderId"]/@value').get(),
                "ShipToNum": checkout_dom.xpath('//select[@name="ShipToNum"]/option[@selected]/@value').get(),
                "ShipViaNum": shipping_option_val,
                "PONum": "",
                "OrderMessage": "",
                "ProcessingDate": checkout_dom.xpath('//input[@name="ProcessingDate"]/@value').get(),
                "__RequestVerificationToken": checkout_dom.xpath(
                    '//input[@name="__RequestVerificationToken"]/@value'
                ).get(),
                "__ncforminfo": checkout_dom.xpath('//input[@name="__ncforminfo"]/@value').get(),
            }
            time.sleep(2)
            for tryy in range(3):
                try:
                    time.sleep(1)
                    async with self.session.post(
                        "https://shop.benco.com/Checkout/OrderDetails", headers=SHIPPING_OPTION_DETAIL_HEADERS, data=data
                    ) as resp:
                        response_dom = Selector(text=await resp.text())
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))

                SHIPPING_OPTIONS_DETAIL_XPATHS = [
                    ("shipping_address", '//fieldset[contains(@class, "ship-to")]'),
                    ("shipping_method", '//fieldset[contains(@class, "shipping-method")]'),
                ]

                for key, xpath in SHIPPING_OPTIONS_DETAIL_XPATHS:
                    review_data[key] = textParser(response_dom.xpath(xpath))
                    if "(change)" in review_data[key]:
                        review_data[key] = review_data[key].split("(change)")[1].strip()

                shipping = await self.shipping_info(cart_id)
                review_data["shipping"] = shipping

                return review_data
        except Exception as e:
            logger.error(f"changing_shipping_method:{str(e)}")
    async def get_shipping_options(self):
        try:
            cart_id, request_verification_token, cart_products = await self.get_cart()
            params = {
                "cartId": cart_id,
            }
            time.sleep(2)
            for tryy in range(3):
                try:
                    time.sleep(1)
                    async with self.session.get(
                        "https://shop.benco.com/Checkout/BeginCheckout",
                        params=params,
                        headers=CREATE_ORDER_HEADERS,
                    ) as resp:
                        await resp.text()
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
            time.sleep(2)
            for tryy in range(3):
                try:
                    time.sleep(1)
                    async with self.session.get(
                        "https://shop.benco.com/Checkout/OrderDetails",
                    ) as resp:

                        options_dom = Selector(text=await resp.text())

                        shipping_options = dict()
                        shipping_option_eles = options_dom.xpath('//select[@name="ShipViaNum"]/option')
                        checkout_info = dict()
                        for shipping_option_ele in shipping_option_eles:
                            _label = textParser(shipping_option_ele)
                            _val = shipping_option_ele.xpath("./@value").get()
                            self.add_shipping_method_to_db(shipping_name=_label,shipping_value=_val,vendor_id=7,office_id=self.office.id)
                            if "2DayGrnd" in _label:
                                checkout_info["default_shipping_method"] = _label
                            if _label not in shipping_options:
                                logger.info(f"-- {_label}: {_val}")
                                shipping_options[_label] = _val
                        checkout_info["shipping_options"] = dict()
                    break
                except Exception as e:
                    if tryy == 2:
                        logger.error(str(e))
            return options_dom, shipping_options, checkout_info, cart_id
        except Exception as e:
            logger.error(f"get_shipping_options:{str(e)}")
    # async def fetch_shipping_options(self, products: List[CartProduct],shipping_option_label:str):
    #     await self.clear_cart()
    #     await self.add_products_to_cart(products)
    #     checkout_dom, shipping_options, checkout_info, cart_id = await self.get_shipping_options()
    #
    #     # for shipping_option_label, shipping_option_val in shipping_options.items():
    #         # if "2DayGrnd" in shipping_option_label or shipping_option_label in ["UPS 2nd Day Air", "UPS Ground"]:
    #     shipping_option_val = shipping_options[shipping_option_label]
    #     logger.info(f'----- Checkout in "{shipping_option_label}" Shipping Option...')
    #     review_data = await self.changing_shipping_method(checkout_dom, cart_id, shipping_option_val)
    #     review_data["shipping_value"] = shipping_option_val
    #     checkout_info["shipping_options"][shipping_option_label] = review_data
    #
    #     return checkout_info
