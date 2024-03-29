import asyncio
import datetime
import json
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Optional

import regex
from aiohttp import ClientResponse
from scrapy import Selector
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.headers.patterson import (
    ADD_CART_HEADERS,
    CLEAR_CART_HEADER,
    GET_CART_ITEMS_HEADER,
    LOGIN_HEADERS,
    LOGIN_HOOK_HEADER,
    LOGIN_HOOK_HEADER2,
    ORDER_HISTORY_HEADERS,
    ORDER_HISTORY_POST_HEADERS,
    PLACE_ORDER_HEADERS,
    REVIEW_ORDER_HEADERS,
    SEARCH_HEADERS,
    SHIP_HEADERS,
    SHIP_PAYMENT_HEADERS,
    SHOPPING_CART_HEADERS,
    VALIDATE_CART_HEADERS,
)
from apps.scrapers.schema import Order, Product, VendorOrderDetail
from apps.scrapers.utils import catch_network
from apps.types.orders import CartProduct
from apps.types.scraper import (
    InvoiceFormat,
    InvoiceType,
    LoginInformation,
    ProductSearch,
)
from apps.vendor_clients import errors

logger = logging.getLogger(__name__)

SETTINGS_REGEX = regex.compile(r"var SETTINGS \= (?P<json_data>\{(?:[^{}]|(?&json_data))*\})")


def textParser(element):
    if element:
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""
    return ""


class PattersonScraper(Scraper):
    BASE_URL = "https://www.pattersondental.com"
    INVOICE_TYPE = InvoiceType.PDF_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT
    aiohttp_mode = False
    selenium_mode = True

    def extract_content(self, ele):
        text = re.sub(r"\s+", " ", " ".join(ele.xpath(".//text()").extract()))
        return text.strip() if text else ""

    async def _get_login_data(self,*args, **kwargs) -> LoginInformation:
        pass

    def login_proc(self):

        try:
            login_url = f"{self.BASE_URL}/Account"
            self.driver.get(login_url)
            self.driver.implicitly_wait(10)
            self.driver.find_element(By.ID, 'signInName').send_keys(self.username)
            self.driver.find_element(By.ID, 'password').send_keys(self.password)
            self.driver.find_element(By.ID, 'next').click()
        except:
            self.driver.quit()
            return False
        try:
            self.driver.find_element(By.XPATH,
                                     '//a[@class="header__action-item header__action-item--account"]/span[contains(text(), "Account")]')
            self.set_cookies_from_driver()
            self.driver.quit()
            return True
        except:
            self.driver.quit()
        return False

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        if username:
            self.username = username
        if password:
            self.password = password

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, self.login_proc)
        logger.info(f"login {res}")
        return res
    def set_cookies_from_driver(self):
        all_cookies = self.driver.get_cookies()
        for cookie in all_cookies:
            self.session.cookies.set(cookie["name"], cookie["value"])

    def _check_authenticated(self, response) -> bool:
        try:
            data = response.json()
            return data['status'] == '200'
        except Exception as e:
            print(f"Error checking authentication: {e}")
            return False

    async def _after_login_hook(self, response: ClientResponse):
        response_dom = Selector(text=response.text)
        data = {
            "wa": response_dom.xpath("//input[@name='wa']/@value").get(),
            "wresult": response_dom.xpath("//input[@name='wresult']/@value").get(),
            "wctx": response_dom.xpath("//input[@name='wctx']/@value").get(),
        }
        self.session.post(self.BASE_URL, headers=LOGIN_HOOK_HEADER, data=data,verify=False)
        with self.session.get(self.BASE_URL, headers=LOGIN_HOOK_HEADER2,verify=False) as resp:
            return resp.text

    async def get_order(self, sem, order_dom, office=None, **kwargs):
        order_id = self.merge_strip_values(order_dom, "./td[3]//text()")
        order = {
            "order_id": order_id,
            "total_amount": self.remove_thousands_separator(self.merge_strip_values(order_dom, "./td[5]//text()")),
            "currency": "USD",
            "order_date": datetime.datetime.strptime(
                self.extract_first(order_dom, "./td[1]//text()"), "%m/%d/%Y"
            ).date(),
            "status": self.extract_first(order_dom, "./td[2]//text()"),
            "products": [],
        }
        order_link = self.extract_first(order_dom, "./td[3]/a/@href")
        logger.info("Getting order information from %s: %s", order_link, order)
        with self.session.get(f"{self.BASE_URL}{order_link}",verify=False) as resp:
            order_detail_response = Selector(text=resp.text)
            order_product_doms = order_detail_response.xpath('//div[contains(@class, "itemRecord")]')
            logger.info("Got %s order product doms for order %s", len(order_product_doms), order_id)
            for i, order_product_dom in enumerate(order_product_doms):
                product_id = order_product_dom.xpath(
                    f".//input[@name='itemSkuDetails[{i}].PublicItemNumber']/@value"
                ).get()
                # product_name = self.extract_first(product_name_url_dom, ".//a/text()")
                product_url = self.extract_first(
                    order_product_dom, ".//div[contains(@class, 'orderHistoryOrderDetailItemText')]//@href"
                )
                if product_url:
                    product_url = f"{self.BASE_URL}{product_url}"
                product_price = self.remove_thousands_separator(
                    self.extract_first(
                        order_product_dom, ".//div[contains(@class, 'orderHistoryOrderDetailPriceText')]//text()"
                    )
                )
                quantity = self.extract_first(
                    order_product_dom, ".//div[contains(@class, 'orderHistoryOrderDetailQuantityText')]/input/@value"
                )

                if "invoice_link" not in order:
                    invoice_number = self.extract_first(
                        order_product_dom,
                        ".//div[contains(@class, 'orderHistoryOrderDetailInvoiceOrRejectReasonText')]//text()",
                    )

                    account_id = kwargs.get("account_id")
                    order["invoice_link"] = (
                        "https://www.pattersondental.com/DocumentLibrary/Invoice"
                        f"?invoiceNumber={invoice_number}&customerNumber={account_id}"
                    )

                dom_product = {
                    "product": {
                        "product_id": product_id,
                        "name": "",
                        "description": "",
                        "url": product_url,
                        "images": [],
                        "category": "",
                        "price": product_price,
                        "vendor": self.vendor.to_dict(),
                    },
                    "quantity": quantity,
                    "unit_price": product_price,
                    "status": "",
                }
                logger.info("Got product: %s", dom_product)
                order["products"].append(dom_product)

        await self.get_missing_products_fields(
            order["products"],
            fields=(
                "name",
                # "description",
                "images",
                "category",
            ),
        )
        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order))
        return order

    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        sem = asyncio.Semaphore(value=2)
        if perform_login:
            self.login()

        url = "https://www.pattersondental.com/OrderHistory/Search"
        logger.info("Getting verification token for search")
        with self.session.get(url, headers=ORDER_HISTORY_HEADERS,verify=False) as resp:
            response_html = resp.text
            response_dom = Selector(text=response_html)
            verification_token = response_dom.xpath(
                '//form[@id="orderHistorySearchForm"]/input[@name="__RequestVerificationToken"]/@value'
            ).get()

        data_layer = json.loads(response_html.split("dataLayer =")[1].split(";")[0].strip())
        account_id = data_layer[0]["accountid"]

        search_params = {
            "usePartial": "true",
        }
        search_data = {
            "__RequestVerificationToken": verification_token,
            "FromDate": "",
            "ToDate": "",
            "ItemNumber": "",
            "ItemDescription": "",
            "ManufacturerName": "",
            "PurchaseOrderNumber": "",
            "OrderNumber": "",
            "ManufacturerOrNdcNumber": "",
            "ViewSortByValue": "",
            "ViewSortDirection": "",
        }
        if from_date and to_date:
            search_data["FromDate"] = from_date.strftime("%m/%d/%Y")
            search_data["ToDate"] = to_date.strftime("%m/%d/%Y")
        else:
            search_data["FromDate"] = (datetime.datetime.now() - datetime.timedelta(days=2 * 365)).strftime("%m/%d/%Y")
            search_data["ToDate"] = datetime.datetime.today().strftime("%m/%d/%Y")

        logger.info("Searching for orders %s", search_data)
        with self.session.post(
            url, headers=ORDER_HISTORY_POST_HEADERS, params=search_params, data=search_data,verify=False
        ) as resp:
            response_dom = Selector(text=resp.text)
            orders_doms = response_dom.xpath('.//table[@id="orderHistory"]/tbody/tr')
            tasks = [self.get_order(sem, order_dom, office, **{"account_id": account_id}) for order_dom in orders_doms]
            orders = await asyncio.gather(*tasks, return_exceptions=True)

        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        if perform_login:
            self.login()
        logger.info("Getting product as dict: %s, %s", product_id, product_url)
        with self.session.get(product_url,verify=False) as resp:
            res = Selector(text=resp.text)
            product_category_and_name = self.merge_strip_values(res, "//div[@class='catalogBreadcrumb']/span//text()")
            categories = product_category_and_name.split(":")
            product_name = categories[-1]
            product_images = res.xpath("//div[contains(@class, 'itemDetailCarousel')]//a/img/@src").extract()
            product_price = self.extract_first(res, ".//div[@class='priceText']//text()")
            product_price = self.remove_thousands_separator(self.extract_price(product_price))
            ret = {
                "product_id": product_id,
                "name": product_name,
                "url": product_url,
                "images": [{"image": product_image} for product_image in product_images],
                "category": categories[1],
                "price": product_price,
                "vendor": self.vendor.to_dict(),
            }

        product_description_detail = res.xpath(
            "//div[@id='ItemDetailsProductDetailsRow']//asyncdiv/@src"
        ).extract_first()
        if product_description_detail:
            logger.info("Getting product detail: %s", product_description_detail)
            with self.session.get(f"{self.BASE_URL}{product_description_detail}",verify=False) as resp:
                res = Selector(text=resp.text)
                product_description = self.merge_strip_values(res, "//div[@class='itemDetailBody']//text()")
        else:
            product_description = self.merge_strip_values(res, ".//div[@class='viewMoreDescriptionContainer']/text()")
        ret["description"] = product_description
        return ret

    async def get_product_prices(self, product_ids, perform_login=False, **kwargs) -> Dict[str, Decimal]:
        # TODO: perform_login, this can be handle in decorator in the future
        if perform_login:
            self.login()

        tasks = (self.get_product_price(product_id) for product_id in product_ids)
        product_prices = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            product_id: product_price
            for product_id, product_price in zip(product_ids, product_prices)
            if isinstance(product_price, Decimal)
        }

    async def get_product_price(self, product_id) -> Decimal:
        with self.session.get(
            f"{self.BASE_URL}/Supplies/ProductFamilyPricing?productFamilyKey={product_id}&getLastDateOrdered=false",verify=False
        ) as resp:
            res = resp.json()
            return Decimal(str(res["PriceHigh"]))

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        page_size = 24
        url = f"{self.BASE_URL}/Search/SearchResults"
        params = {
            "F.MYCATALOG": "false",
            "q": query,
            "p": page,
        }
        products = []
        with self.session.get(url, headers=SEARCH_HEADERS, params=params,verify=False) as resp:
            response_dom = Selector(text=resp.text)
        products_dom = response_dom.xpath(
            "//div[@class='container-fluid']//table//tr//div[@ng-controller='SearchResultsController']"
        )
        if products_dom:
            try:
                total_size = int(
                    response_dom.xpath("//div[contains(@class, 'productItemFamilyListHeader')]//h1//text()")
                    .get()
                    .split("results", 1)[0]
                    .split("Found")[1]
                    .strip(" +")
                )
            except (IndexError, AttributeError, ValueError):
                total_size = 0

            for product_dom in products_dom:
                product_description_dom = product_dom.xpath(".//div[contains(@class, 'listViewDescriptionWrapper')]")
                product_link = product_description_dom.xpath(".//a[@class='itemTitleDescription']")
                product_id = product_link.attrib["data-objectid"]
                product_name = self.extract_first(
                    product_description_dom,
                    ".//a[@class='itemTitleDescription']//text()",
                )
                product_url = self.BASE_URL + self.extract_first(
                    product_description_dom,
                    ".//a[@class='itemTitleDescription']/@href",
                )
                product_image = self.extract_first(
                    product_dom, ".//div[contains(@class, 'listViewImageWrapper')]/img/@src"
                )

                products.append(
                    {
                        "product_id": product_id,
                        "name": product_name,
                        "description": "",
                        "url": product_url,
                        "images": [{"image": product_image}],
                        "price": Decimal(0),
                        "vendor": self.vendor.to_dict(),
                        "category": "",
                    }
                )

            product_prices = await self.get_product_prices([product["product_id"] for product in products])

            for product in products:
                product["price"] = product_prices[product["product_id"]]
        else:
            products_dom = response_dom.xpath(
                "//div[@id='productFamilyDetailsRow']//div[contains(@class, 'productFamilyGridBody')]"
            )
            total_size = len(products_dom)
            product_name = self.extract_first(response_dom, ".//div[@id='productFamilyDescriptionHeader']/h1//text()")

            for product_dom in products_dom:
                product_title = self.extract_first(
                    product_dom,
                    ".//div[@id='productFamilyDetailsGridBodyColumnOneInnerRowDescription']"
                    "//a[@class='itemTitleDescription']//text()",
                )
                product_url = self.BASE_URL + self.extract_first(
                    product_dom,
                    ".//div[@id='productFamilyDetailsGridBodyColumnOneInnerRowDescription']"
                    "//a[@class='itemTitleDescription']/@href",
                )
                product_id = self.extract_first(
                    product_dom, ".//div[@id='productFamilyDetailsGridBodyColumnTwoInnerRowItemNumber']/text()"
                )
                product_image = self.extract_first(
                    product_dom, ".//div[@id='productFamilyDetailsGridBodyColumnOneInnerRowImages']//img/@src"
                )
                product_price = self.extract_first(
                    product_dom, ".//div[contains(@class, 'productFamilyDetailsPriceBreak')]/text()"
                )
                product_price = self.extract_price(product_price)

                products.append(
                    {
                        "product_id": product_id,
                        "name": product_name + product_title,
                        "description": "",
                        "url": product_url,
                        "images": [{"image": product_image}],
                        "price": Decimal(product_price),
                        "vendor": self.vendor.to_dict(),
                        "category": "",
                    }
                )

        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": [Product.from_dict(product) for product in products if isinstance(product, dict)],
            "last_page": page_size * page >= total_size,
        }

    def get_cart_items(self):
        with self.session.get(
            "https://www.pattersondental.com/ShoppingCart/CartItemQuantities", headers=GET_CART_ITEMS_HEADER,verify=False
        ) as resp:
            return resp.json()

    def clear_cart(self):
        data = list()
        cart_items = self.get_cart_items()
        for cart_item in cart_items:
            item = {
                "OrderItemId": cart_item["OrderItemId"],
                "ParentItemId": None,
                "PublicItemNumber": cart_item["PublicItemNumber"],
                "PersistentItemNumber": "",
                "ItemQuantity": cart_item["ItemQuantity"],
                "BasePrice": None,
                "ItemPriceBreaks": None,
                "UnitPriceOverride": None,
                "IsLabelItem": False,
                "IsTagItem": False,
                "ItemDescription": "",
                "UseMyCatalogQuantity": False,
                "UnitPrice": cart_item["UnitPrice"],
                "ItemSubstitutionReasonModel": None,
                "NavInkConfigurationId": None,
                "CanBePersonalized": False,
                "HasBeenPersonalized": False,
                "Manufacturer": False,
            }
            data.append(item)

        with self.session.post(
            "https://www.pattersondental.com/ShoppingCart/RemoveItemsFromShoppingCart",
            headers=CLEAR_CART_HEADER,
            json=data,verify=False
        ) as resp:
            logger.info(f"Clear Cart: {resp.status_code}")

    def add_to_cart(self, products):
        for product in products:
            product_id = product["product_id"]
            quantity = product["quantity"]
            data = {"itemNumbers": product_id, "loadItemType": "ShoppingCart"}
            self.session.post(
                "https://www.pattersondental.com/Item/ValidateItems",
                headers=VALIDATE_CART_HEADERS,
                data=json.dumps(data),verify=False
            )

            data = [
                {
                    "OrderItemId": None,
                    "ParentItemId": None,
                    "PublicItemNumber": product_id,
                    "PersistentItemNumber": None,
                    "ItemQuantity": quantity,
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

            return self.session.post(
                "https://www.pattersondental.com/ShoppingCart/AddItemsToCart",
                headers=ADD_CART_HEADERS,
                data=json.dumps(data),verify=False
            )

    def shipping_payment(self):
        response = self.session.get("https://www.pattersondental.com/Order/ShippingPayment", headers=SHIP_HEADERS,verify=False)
        response_text = response.text
        response_dom = Selector(text=response_text)
        return response_dom

    def review_checkout(self, response_dom):
        shipping_address = "\n".join(
            [
                self.extract_content(it)
                for it in response_dom.xpath('//div[@class="shippingPayment__address"]/div[@class="columns"]/div')
            ]
        )
        print("Shipping Address:\n", shipping_address)

        __RequestVerificationToken = response_dom.xpath("//input[@name='__RequestVerificationToken']/@value").get()
        shippingMethod = response_dom.xpath("//input[@name='shippingMethod'][@checked='checked']/@value").get()
        SpecialInstructions = response_dom.xpath("//input[@name='SpecialInstructions']/@value").get()
        shippingAddressNumber = response_dom.xpath("//input[@name='shippingAddressNumber']/@value").get()
        paymentMethod = response_dom.xpath("//input[@name='paymentMethod'][@checked='checked']/@value").get()
        CardTypeId = response_dom.xpath("//select[@name='CardTypeId']/option[@selected='selected']/@value").get()
        CardNumber = response_dom.xpath("//input[@name='CardNumber']/@value").get()
        ExpirationMonth = response_dom.xpath(
            "//select[@name='ExpirationMonth']/option[@selected='selected']/@value"
        ).get()
        ExpirationYear = response_dom.xpath(
            "//select[@name='ExpirationYear']/option[@selected='selected']/@value"
        ).get()
        CardHolderName = response_dom.xpath("//input[@name='CardHolderName']/@value").get()
        StatementPostalCode = response_dom.xpath("//input[@name='StatementPostalCode']/@value").get()
        Token = response_dom.xpath("//input[@name='Token']/@value").get()
        poNumber = response_dom.xpath("//input[@name='poNumber']/@value").get()
        purchaseOrderRequired = response_dom.xpath("//input[@name='purchaseOrderRequired']/@value").get()
        isZeroOrderTotal = response_dom.xpath("//input[@name='isZeroOrderTotal']/@value").get()
        cardNumberLastFour = response_dom.xpath("//input[@name='cardNumberLastFour']/@value").get()
        encryptedCardNumber = response_dom.xpath("//input[@name='encryptedCardNumber']/@value").get()
        ShippingInfo = response_dom.xpath("//input[@name='ShippingInfo.DefaultCharges']/@value").get()
        UserIsTerritoryRep = response_dom.xpath("//input[@name='UserIsTerritoryRep']/@value").get()
        CustomerRefNumber = response_dom.xpath("//input[@name='CustomerRefNumber']/@value").get()
        shoppingCartButton = response_dom.xpath("//input[@name='shoppingCartButton']/@value").get()

        data = {
            "__RequestVerificationToken": __RequestVerificationToken,
            "shippingMethod": shippingMethod,
            "SpecialInstructions": SpecialInstructions,
            "shippingAddressNumber": shippingAddressNumber,
            "paymentMethod": paymentMethod,
            "CardTypeId": CardTypeId,
            "CardNumber": CardNumber,
            "ExpirationMonth": ExpirationMonth,
            "ExpirationYear": ExpirationYear,
            "CardHolderName": CardHolderName,
            "StatementPostalCode": StatementPostalCode,
            "Token": Token,
            "poNumber": poNumber,
            "purchaseOrderRequired": purchaseOrderRequired,
            "isZeroOrderTotal": isZeroOrderTotal,
            "cardNumberLastFour": cardNumberLastFour,
            "encryptedCardNumber": encryptedCardNumber,
            "ShippingInfo.DefaultCharges": ShippingInfo,
            "UserIsTerritoryRep": UserIsTerritoryRep,
            "CustomerRefNumber": CustomerRefNumber,
            "shoppingCartButton": shoppingCartButton,
        }

        with self.session.post(
            "https://www.pattersondental.com/Order/ShippingPayment", headers=SHIP_PAYMENT_HEADERS, data=data,verify=False
        ) as resp:
            if not resp.ok:
                raise ValueError("Review order POST API is failed somehow!")

            with self.session.get("https://www.pattersondental.com/Order/ReviewOrder",verify=False) as redirect_resp:
                if not redirect_resp.ok:
                    raise ValueError("Redirecting to review order is failed somehow!")
                logger.info(f"{redirect_resp.url} --- {redirect_resp.status_code}")
                response_text = redirect_resp.text
                resp_dom = Selector(text=response_text)

            subtotal = self.extract_content(
                resp_dom.xpath('//div[contains(@class, "OrderSummaryBackground")]/div[2]/div[2]')
            )
            print("--- subtotal:\n", subtotal.strip() if subtotal else "")

            shipping = self.extract_content(
                resp_dom.xpath('//div[contains(@class, "OrderSummaryBackground")]/div[3]/div[2]')
            )
            print("--- shipping:\n", shipping.strip() if shipping else "")

            order_total = self.extract_content(
                resp_dom.xpath('//div[contains(@class, "OrderSummaryBackground")]/following-sibling::div/div[2]')
            )
            print("--- order_total:\n", order_total.strip() if order_total else "")
            return resp_dom, subtotal, shipping, order_total, shipping_address

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("patterson/create_order")
        try:
            await asyncio.sleep(0.3)
            await self.login()
            await self.clear_cart()
            await self.add_to_cart(products)
            order_dom, subtotal, shipping, order_total, shipping_address = await self.checkout()
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": "",
                "total_amount": order_total,
                "reduction_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
            }
        except Exception:
            print("patterson/create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": "",
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
        print("patterson/confirm_order")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.clear_cart)
            await loop.run_in_executor(None, self.add_to_cart, products)
            shipping_payment_dom = await loop.run_in_executor(None, self.shipping_payment)
            resp_dom, subtotal, shipping, order_total, shipping_address = await loop.run_in_executor(
                None, self.review_checkout, shipping_payment_dom
            )

            if fake:
                vendor_order_detail = {
                    "retail_amount": "",
                    "savings_amount": "",
                    "subtotal_amount": subtotal,
                    "shipping_amount": shipping,
                    "tax_amount": "",
                    "total_amount": order_total,
                    "payment_method": "",
                    "shipping_address": shipping_address,
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
                return {
                    **vendor_order_detail,
                    **self.vendor.to_dict(),
                }
            data = {
                "__RequestVerificationToken": resp_dom.xpath(
                    "//input[@name='__RequestVerificationToken']/@value"
                ).get(),
                "SpecialInstructions": "",
                "CustomerPurchaseOrder": "",
                "PaymentMethodId": resp_dom.xpath("//input[@name='PaymentMethodId']/@value").get(),
                "PlaceOrderButton": "Place+Order",
            }

            self.session.post(
                "https://www.pattersondental.com/Order/ReviewOrder", headers=PLACE_ORDER_HEADERS, data=data,verify=False
            )
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": "",
                "total_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
                "order_id": "invalid",
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }
        except Exception as e:
            print(f"patterson/confirm_order except {e}")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": "",
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

    async def get_shipping_options(self):
        with self.session.get(
            "https://www.pattersondental.com/Order/ShippingPayment", headers=SHIP_HEADERS,verify=False
        ) as response:
            response_dom = Selector(text=response.text)
            checkout_info = dict()
            shipping_options = dict()
            shipping_option_eles = response_dom.xpath('//input[@name="shippingMethod"]')
            logger.info(">>>>> Shipping Options:")
            for shipping_option_ele in shipping_option_eles:
                ele_id = shipping_option_ele.xpath("./@id").get()
                _label = textParser(response_dom.xpath(f'//label[@for="{ele_id}"][@class="labelInstruct"]'))
                _val = shipping_option_ele.xpath("./@value").get()
                _selected = shipping_option_ele.xpath("./@checked")
                if _selected:
                    checkout_info["default_shipping_method"] = _label
                logger.info(f"-- {_label}: {_val}")
                shipping_options[_label] = _val
            checkout_info["shipping_options"] = dict()

            return response_dom, shipping_options, checkout_info

    async def get_shipping_option_detail(self, checkout_dom, shipping_option_label, shipping_option_val):
        review_data = dict()
        SHIPPING_OPTIONS_XPATHS = [
            ("__RequestVerificationToken", "//input[@name='__RequestVerificationToken']/@value"),
            ("SpecialInstructions", "//input[@name='SpecialInstructions']/@value"),
            ("shippingAddressNumber", "//input[@name='shippingAddressNumber']/@value"),
            ("paymentMethod", "//input[@name='paymentMethod'][@checked='checked']/@value"),
            ("CardTypeId", "//select[@name='CardTypeId']/option[@selected='selected']/@value"),
            ("CardNumber", "//input[@name='CardNumber']/@value"),
            ("ExpirationMonth", "//select[@name='ExpirationMonth']/option[@selected='selected']/@value"),
            ("ExpirationYear", "//select[@name='ExpirationYear']/option[@selected='selected']/@value"),
            ("CardHolderName", "//input[@name='CardHolderName']/@value"),
            ("StatementPostalCode", "//input[@name='StatementPostalCode']/@value"),
            ("Token", "//input[@name='Token']/@value"),
            ("poNumber", "//input[@name='poNumber']/@value"),
            ("purchaseOrderRequired", "//input[@name='purchaseOrderRequired']/@value"),
            ("isZeroOrderTotal", "//input[@name='isZeroOrderTotal']/@value"),
            ("cardNumberLastFour", "//input[@name='cardNumberLastFour']/@value"),
            ("encryptedCardNumber", "//input[@name='encryptedCardNumber']/@value"),
            ("ShippingInfo.DefaultCharges", "//input[@name='ShippingInfo.DefaultCharges']/@value"),
            ("UserIsTerritoryRep", "//input[@name='UserIsTerritoryRep']/@value"),
            ("CustomerRefNumber", "//input[@name='UserIsTerritoryRep']/@value"),
            ("shoppingCartButton", "//input[@name='shoppingCartButton']/@value"),
        ]

        shipping_address = "\n".join(
            [
                textParser(it)
                for it in checkout_dom.xpath('//div[@class="shippingPayment__address"]/div[@class="columns"]/div')
            ]
        )

        data = {name: checkout_dom.xpath(xpath).get() for name, xpath in SHIPPING_OPTIONS_XPATHS}
        data["shippingMethod"] = shipping_option_val

        with self.session.get("https://www.pattersondental.com/ShoppingCart", headers=SHOPPING_CART_HEADERS,verify=False):
            with self.session.post(
                "https://www.pattersondental.com/Order/ShippingPayment", headers=SHIP_PAYMENT_HEADERS, data=data,verify=False
            ) as response:
                with self.session.get(
                    "https://www.pattersondental.com/Order/ReviewOrder", headers=REVIEW_ORDER_HEADERS,verify=False
                ) as response:
                    response_dom = Selector(text=response.text)

                    review_data["shipping_address"] = shipping_address

                    shipping_method = textParser(response_dom.xpath('//div[@data-auto="shipping-method-section"]'))
                    review_data["shipping_method"] = shipping_method

                    shipping = textParser(
                        response_dom.xpath('//div[contains(@class, "OrderSummaryBackground")]/div[3]/div[2]')
                    )
                    if shipping == "TBD":
                        shipping = re.search(r"\((\$[\d\.\,]+)\)", shipping_option_label).group(1)
                    review_data["shipping"] = shipping

                    return review_data

    async def fetch_shipping_options(self, products: List[CartProduct]):
        await self.clear_cart()
        await self.add_to_cart(products)
        checkout_dom, shipping_options, checkout_info = await self.get_shipping_options()

        for shipping_option_label, shipping_option_val in shipping_options.items():
            logger.info(f'----- Checkout in "{shipping_option_label}" Shipping Option...')
            review_data = await self.get_shipping_option_detail(
                checkout_dom, shipping_option_label, shipping_option_val
            )
            review_data["shipping_value"] = shipping_option_val
            checkout_info["shipping_options"][shipping_option_label] = review_data

        return checkout_info
