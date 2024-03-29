import asyncio
import datetime
import json
import logging
import re
import time
import uuid
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Dict, List, Optional

import scrapy
from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.errors import VendorAuthenticationFailed
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.scrapers.utils import catch_network, semaphore_coroutine, solve_captcha
from apps.types.orders import CartProduct
from apps.types.scraper import InvoiceFile, InvoiceFormat, InvoiceType

MIN_SCORE = 0.9
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36"
)

retry_count = 5
logger = logging.getLogger(__name__)

headers = {
    "authority": "store.implantdirect.com",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
    "/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
    "accept": "*/*",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "referer": "https://store.implantdirect.com/us/en/",
    "accept-language": "en-US,en;q=0.9",
}


class ImplantDirectScraper(Scraper):
    results = list()
    aiohttp_mode = False
    INVOICE_TYPE = InvoiceType.HTML_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT
    BASE_URL = "https://store.implantdirect.com"

    def extractContent(dom, xpath):
        return re.sub(r"\s+", " ", " ".join(dom.xpath(xpath).extract())).strip()

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> SimpleCookie:
        if username:
            self.username = username
        if password:
            self.password = password

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, self.login_proc)
        logger.info("login DONE")
        return res

    def get_home_page(self):
        response = self.session.get(f"{self.BASE_URL}/us/en/", headers=headers)
        logger.info(f"Home Page: {response.status_code}")
        return response

    def get_login_page(self, login_link):
        response = self.session.get(login_link, headers=headers)
        logger.info(f"LogIn Page: {response.status_code}")
        return response

    def getCartPage(self):
        response = self.session.get("https://store.implantdirect.com/us/en/checkout/cart/", headers=headers)
        print("Cart Page:", response.status_code)
        return response.text

    def getProductPage(self, link):
        response = self.session.get(link, headers=headers)
        return response.text

    def getOrderDetailPage(self, _link):
        response = self.session.get(_link, headers=headers)
        print("Order Detail Page:", response.status_code)

    @semaphore_coroutine
    async def get_order(self, sem, order, office=None) -> dict:
        print(" === get order ==", office, order)
        loop = asyncio.get_event_loop()
        order_dict = await loop.run_in_executor(None, self.orderDetail, order["order_detail_link"])
        order_dict.update(order)
        order_dict.update({"currency": "USD"})
        print(order_dict)

        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order_dict))

    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        sem = asyncio.Semaphore(value=2)
        loop = asyncio.get_event_loop()

        if perform_login:
            await loop.run_in_executor(None, self.login_proc)

        await loop.run_in_executor(None, self.orderHistory, 1)
        tasks = []

        for order_data in self.results:
            # month, day, year= order_data["order_date"].split("/")
            # order_date = datetime.date(int(year), int(month), int(day))
            if isinstance(order_data["order_date"], datetime.date):
                order_date = order_data["order_date"]
            else:
                order_date = datetime.datetime.strptime(order_data["order_date"], "%b %d, %Y").date()
            order_data["order_date"] = order_date
            if from_date and to_date and (order_date < from_date or order_date > to_date):
                continue

            if completed_order_ids and str(order_data["order_id"]) in completed_order_ids:
                continue
            tasks.append(self.get_order(sem, order_data, office))
        if tasks:
            orders = await asyncio.gather(*tasks)
            return [Order.from_dict(order) for order in orders if isinstance(order, dict)]
        else:
            return []

    def orderHistory(self, page):
        json_headers = {
            "authority": "store.implantdirect.com",
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://store.implantdirect.com/us/en/customer/order/",
            "sec-ch-ua": '"Google Chrome";v="105", "Not)A;Brand";v="8", "Chromium";v="105"',
            "sec-ch-ua-mobile": "?0",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
            "/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
            "x-newrelic-id": "VQUAU1dTABABVFdVBgYEUFcD",
            "x-requested-with": "XMLHttpRequest",
        }

        params = {
            "namespace": "customer_order_listing",
            "sorting[field]": "creation_date",
            "sorting[direction]": "desc",
            "filters[placeholder]": "true",
            "paging[pageSize]": "50",
            "paging[current]": f"{page}",
            "_": f"{int(time.time() * 1000)}",
        }

        response = self.session.get(
            "https://store.implantdirect.com/us/en/customer/order/grid/", params=params, headers=json_headers
        )
        data = response.json()

        for order_item in data["items"]:
            order_history = dict()
            order_history["order_id"] = order_item["entity_id"]
            order_history["order_date"] = order_item["creation_date"]
            order_history["status"] = order_item["state"]
            order_history["total_amount"] = order_item["grand_total"]
            order_history[
                "order_detail_link"
            ] = f'https://store.implantdirect.com/us/en/customer/order/view/id/{order_item["entity_id"]}'
            # order_history["order_subtotal"] = order_item["subtotal_amount"]
            # order_history["order_tax"] = order_item["tax_amount"]
            # order_history["order_shipping"] = order_item["shipping_amount"]
            # order_detail_link = order_item["actions_view"]["view"]["href"]
            order_history[
                "invoice_link"
            ] = f'https://store.implantdirect.com/us/en/customer/order/print/id/{order_item["increment_id"]}/'
            # order_history["order_number"] = order_item["increment_id"]
            self.results.append(order_history)

        if data["totalRecords"] > 50 * page:
            self.orderHistory(page + 1)

    def orderDetail(self, _link):
        self.getOrderDetailPage(_link)
        json_headers = {
            "authority": "store.implantdirect.com",
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "en-US,en;q=0.9",
            "referer": _link,
            "sec-ch-ua": '"Google Chrome";v="105", "Not)A;Brand";v="8", "Chromium";v="105"',
            "sec-ch-ua-mobile": "?0",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
            "/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
            "x-newrelic-id": "VQUAU1dTABABVFdVBgYEUFcD",
            "x-requested-with": "XMLHttpRequest",
        }

        response = self.session.get(
            f"https://store.implantdirect.com/us/en/mui/index/render"
            f"/?namespace=customer_order_items&_={int(time.time() * 1000)}",
            headers=json_headers,
        )
        order = dict()
        order["products"] = list()
        for product_item in response.json()["items"]:
            product = dict()
            product["qty"] = product_item["qty"]
            product["name"] = product_item["name"]
            product["price"] = product_item["price"]
            product["sku"] = product_item["sku"]
            product["product_id"] = product_item["sku"]
            product["vendor"] = self.vendor.to_dict()
            product["subtotal"] = product_item["row_total"]
            product["status"] = product_item["status"]
            product["images"] = []
            product_data = {"product": product, "quantity": product.pop("qty"), "unit_price": product["price"]}
            tracking_number = product_item["tracking_number"]
            if tracking_number:
                product_data.update({'tracking_number':tracking_number, 'tracking_link': f'https://www.ups.com/track?loc=en_US&tracknum={tracking_number}'})
            order["products"].append(product_data)

        return order

    def _check_authenticated(self, response):
        dom = Selector(text=response.text)
        page_title = dom.css("title::text").get()
        logger.debug("Got page title: %s", page_title)
        return page_title != "Customer Login"

    def login_proc(self):
        home_resp = self.get_home_page()
        home_dom = scrapy.Selector(text=home_resp.text)
        login_link = home_dom.xpath('//ul/li[contains(@class, "authorization-link")]/a/@href').get()
        logger.debug("Got login link: %s", login_link)
        login_resp = self.get_login_page(login_link)
        login_dom = scrapy.Selector(text=login_resp.text)
        is_authenticated = self._check_authenticated(login_resp)
        if is_authenticated:
            return True

        logger.info("Seems like we got captcha, checking for key and action")
        form_key = login_dom.xpath('//form[@id="login-form"]/input[@name="form_key"]/@value').get()
        form_action = login_dom.xpath('//form[@id="login-form"]/@action').get()
        logger.debug("Got form key=%s and form action=%s", form_key, form_action)
        sitekey = re.search(r"sitekey\"\s*\:\s*\"([\d\w\-]+)\"", login_resp.text).groups()[0]
        logger.debug("Got site key: %s", sitekey)

        for i in range(retry_count):
            logger.info("Attempt #%s to solve catpcha", i)
            solved = solve_captcha(sitekey, login_resp.url, MIN_SCORE, True, "recaptcha.net")
            logging.debug("Got captcha solution: %s", solved)
            recaptcha_token = solved.solution.token

            data = {
                "form_key": form_key,
                "login[username]": self.username,
                "login[password]": self.password,
                "g-recaptcha-response": recaptcha_token,
                "token": recaptcha_token,
            }

            logger.info("Sending captcha solution...")
            response = self.session.post(form_action, data=data, headers=headers)
            if not response.url.endswith("/customer/account/"):
                logger.info(f"Try #{i+1} >>> Login Failed!")
                continue
            else:
                logger.info(f"Try #{i+1} >>> Log In POST: {response.status_code}")
                is_authenticated = self._check_authenticated(response)
                if not is_authenticated:
                    raise VendorAuthenticationFailed()

                logger.info(response.url)
                logger.info(f"Log In POST: {response.status_code}")
                return response.cookies

        logger.info(f"Exceed trying {retry_count} times!")
        raise VendorAuthenticationFailed()

    def clear_cart(self):
        cart_page = self.getCartPage()
        dom = Selector(text=cart_page)
        form_key = dom.xpath('//form[@id="form-validate"]//input[@name="form_key"]/@value').get()
        products = dom.xpath('//form[@id="form-validate"]//table[@id="shopping-cart-table"]/tbody[@class="cart item"]')
        data = {
            "form_key": form_key,
            "update_cart_action": "empty_cart",
        }
        for product in products:
            _key = product.xpath('.//input[@data-role="cart-item-qty"]/@name').get()
            _val = product.xpath('.//input[@data-role="cart-item-qty"]/@value').get()
            data[_key] = _val

        if products:
            response = self.session.post(
                "https://store.implantdirect.com/us/en/checkout/cart/updatePost/", data=data, headers=headers
            )
            print("Empty Cart POST:", response.status_code)
        else:
            print("Empty Cart: Already Empty")

    def add_to_cart(self, products):
        add_to_cart_headers = {
            "authority": "store.implantdirect.com",
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
            "content-type": "multipart/form-data; boundary=----WebKitFormBoundarytvKTimFXuo4R6Xsw",
            "origin": "https://store.implantdirect.com",
            "referer": "https://store.implantdirect.com/us/en/surgical-kit-grommet-small-2pk",
            "sec-ch-ua": '"Google Chrome";v="105", "Not)A;Brand";v="8", "Chromium";v="105"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
            "/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
        }

        cookies = {
            "form_key": "l7i7sDRkNglwFRKP",
        }

        for product in products:
            product_page = self.getProductPage(product["product_url"])
            dom = Selector(text=product_page)
            action_link = dom.xpath('//form[@id="product_addtocart_form"]/@action').get()
            product_id = dom.xpath("//div[@data-product-id]/@data-product-id").get()

            data = (
                f"------WebKitFormBoundarytvKTimFXuo4R6Xsw\r\nContent-Disposition: "
                f'form-data; name="product"\r\n\r\n{product_id}\r\n------WebKitForm'
                f'BoundarytvKTimFXuo4R6Xsw\r\nContent-Disposition: form-data; name="'
                f'selected_configurable_option"\r\n\r\n\r\n------WebKitFormBoundary'
                f'tvKTimFXuo4R6Xsw\r\nContent-Disposition: form-data; name="related'
                f'_product"\r\n\r\n\r\n------WebKitFormBoundarytvKTimFXuo4R6Xsw\r\n'
                f'Content-Disposition: form-data; name="item"\r\n\r\n{product_id}\r'
                f"\n------WebKitFormBoundarytvKTimFXuo4R6Xsw\r\nContent-Disposition"
                f': form-data; name="form_key"\r\n\r\nl7i7sDRkNglwFRKP\r\n------Web'
                f"KitFormBoundarytvKTimFXuo4R6Xsw\r\nContent-Disposition: form-data;"
                f' name="qty"\r\n\r\n{product["quantity"]}\r\n------WebKitFormBound'
                f"arytvKTimFXuo4R6Xsw--\r\n"
            )

            response = self.session.post(action_link, data=data, headers=add_to_cart_headers, cookies=cookies)
            print(f"Product ({product_id}) added to cart:", response.status_code)

    def shipping_infomation(self, payload):
        post_headers = {
            "authority": "store.implantdirect.com",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            "x-newrelic-id": "VQUAU1dTABAHXFhUDgUHXlc=",
            "sec-ch-ua-mobile": "?0",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
            "/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
            "content-type": "application/json",
            "accept": "*/*",
            "x-requested-with": "XMLHttpRequest",
            "sec-ch-ua-platform": '"Windows"',
            "origin": "https://store.implantdirect.com",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://store.implantdirect.com/us/en/checkout/",
            "accept-language": "en-US,en;q=0.9",
        }

        response = self.session.post(
            "https://store.implantdirect.com/us/en/rest/us_en/V1/carts/mine/shipping-information",
            headers=post_headers,
            json=payload,
        )
        print("Shipping Infomation:", response.status_code)
        return response.json()["totals"]

    def proceed_checkout(self):
        response = self.session.get("https://store.implantdirect.com/us/en/checkout/", headers=headers)
        print("Checkout Page:", response.status_code)
        response_dom = Selector(text=response.text)
        json_text = response_dom.xpath('//script[contains(text(), "totalsData")]//text()').get().strip()
        json_text = (
            json_text.split("window.checkoutConfig", 1)[1]
            .split("window.customerData", 1)[0]
            .split("window.isCustomerLoggedIn", 1)[0]
            .rsplit("};", 1)[0]
        )
        json_text = json_text.strip("\n\r\t =")
        json_data = json.loads(json_text + "}")

        cartId = json_data["quoteData"]["entity_id"]

        shipping_payload = {
            "addressInformation": {
                "shipping_address": {},
                "billing_address": {},
                # shipping_method_code:
                # - Will Call – Pomona, CA: 38
                # - UPS 2 Day : 31
                # - UPS Overnight : 33
                # - UPS Overnight - AM delivery : 34
                # - UPS Overnight - Saturday delivery : UD
                # - UPS Overnight - AM Saturday delivery : 59
                "shipping_method_code": "31",
                "shipping_carrier_code": "shippingoptions",
                "extension_attributes": {},
            },
        }

        shipping_address_l = json_data["customerData"]["addresses"]
        for item in shipping_address_l.values():
            if item["default_billing"]:
                shipping_payload["addressInformation"]["billing_address"]["customerAddressId"] = item["id"]
                shipping_payload["addressInformation"]["billing_address"]["countryId"] = item["country_id"]
                shipping_payload["addressInformation"]["billing_address"]["regionId"] = item["region_id"]
                shipping_payload["addressInformation"]["billing_address"]["regionCode"] = item["region"]["region_code"]
                shipping_payload["addressInformation"]["billing_address"]["region"] = item["region"]["region"]
                shipping_payload["addressInformation"]["billing_address"]["customerId"] = item["customer_id"]
                shipping_payload["addressInformation"]["billing_address"]["street"] = item["street"]
                shipping_payload["addressInformation"]["billing_address"]["company"] = item["company"]
                shipping_payload["addressInformation"]["billing_address"]["telephone"] = item["telephone"]
                shipping_payload["addressInformation"]["billing_address"]["fax"] = item["fax"]
                shipping_payload["addressInformation"]["billing_address"]["postcode"] = item["postcode"]
                shipping_payload["addressInformation"]["billing_address"]["city"] = item["city"]
                shipping_payload["addressInformation"]["billing_address"]["firstname"] = item["firstname"]
                shipping_payload["addressInformation"]["billing_address"]["lastname"] = item["lastname"]
                shipping_payload["addressInformation"]["billing_address"]["middlename"] = item["middlename"]
                shipping_payload["addressInformation"]["billing_address"]["prefix"] = item["prefix"]
                shipping_payload["addressInformation"]["billing_address"]["suffix"] = item["suffix"]
                shipping_payload["addressInformation"]["billing_address"]["vatId"] = item["vat_id"]
                shipping_payload["addressInformation"]["billing_address"]["customAttributes"] = list(
                    item["custom_attributes"].values()
                )

                billing_address = f'{item["inline"]}\n{item["telephone"]}'
                print("--- billing_address:\n", billing_address.strip() if billing_address else "")

            if item["default_shipping"]:
                shipping_payload["addressInformation"]["shipping_address"]["customerAddressId"] = item["id"]
                shipping_payload["addressInformation"]["shipping_address"]["email"] = json_data["customerData"][
                    "email"
                ]
                shipping_payload["addressInformation"]["shipping_address"]["countryId"] = item["country_id"]
                shipping_payload["addressInformation"]["shipping_address"]["regionId"] = item["region_id"]
                shipping_payload["addressInformation"]["shipping_address"]["regionCode"] = item["region"][
                    "region_code"
                ]
                shipping_payload["addressInformation"]["shipping_address"]["region"] = item["region"]["region"]
                shipping_payload["addressInformation"]["shipping_address"]["customerId"] = item["customer_id"]
                shipping_payload["addressInformation"]["shipping_address"]["street"] = item["street"]
                shipping_payload["addressInformation"]["shipping_address"]["company"] = item["company"]
                shipping_payload["addressInformation"]["shipping_address"]["telephone"] = item["telephone"]
                shipping_payload["addressInformation"]["shipping_address"]["fax"] = item["fax"]
                shipping_payload["addressInformation"]["shipping_address"]["postcode"] = item["postcode"]
                shipping_payload["addressInformation"]["shipping_address"]["city"] = item["city"]
                shipping_payload["addressInformation"]["shipping_address"]["firstname"] = item["firstname"]
                shipping_payload["addressInformation"]["shipping_address"]["lastname"] = item["lastname"]
                shipping_payload["addressInformation"]["shipping_address"]["middlename"] = item["middlename"]
                shipping_payload["addressInformation"]["shipping_address"]["prefix"] = item["prefix"]
                shipping_payload["addressInformation"]["shipping_address"]["suffix"] = item["suffix"]
                shipping_payload["addressInformation"]["shipping_address"]["vatId"] = item["vat_id"]
                shipping_payload["addressInformation"]["shipping_address"]["customAttributes"] = list(
                    item["custom_attributes"].values()
                )

                shipping_address = f'{item["inline"]}\n{item["telephone"]}'
                print("--- shipping_address:\n", shipping_address.strip() if shipping_address else "")

        total_info = self.shipping_infomation(shipping_payload)
        currency = total_info["base_currency_code"]
        subtotal = total_info["subtotal"]
        print("--- subtotal:\n", f"{currency} {subtotal}".strip() if subtotal else "")

        shipping = total_info["shipping_amount"]
        print("--- shipping:\n", f"{currency} {shipping}".strip() if shipping else "")

        discount = total_info["discount_amount"]
        print("--- discount:\n", f"{currency} {discount}".strip() if discount else "")

        tax = total_info["tax_amount"]
        print("--- tax:\n", f"{currency} {tax}".strip() if tax else "")

        order_total = total_info["grand_total"]
        print("--- order_total:\n", f"{currency} {order_total}".strip() if order_total else "")

        return cartId, shipping_payload, shipping_address, subtotal, shipping, discount, tax, order_total

    def submit_order(self, cartId, shipping_payload):
        post_headers = {
            "authority": "store.implantdirect.com",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            "x-newrelic-id": "VQUAU1dTABAHXFhUDgUHXlc=",
            "sec-ch-ua-mobile": "?0",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
            "/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
            "content-type": "application/json",
            "accept": "*/*",
            "x-requested-with": "XMLHttpRequest",
            "sec-ch-ua-platform": '"Windows"',
            "origin": "https://store.implantdirect.com",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://store.implantdirect.com/us/en/checkout/",
            "accept-language": "en-US,en;q=0.9",
        }

        billingAddress = shipping_payload["addressInformation"]["shipping_address"]
        billingAddress["saveInAddressBook"] = None

        json_data = {
            "cartId": cartId,
            "billingAddress": billingAddress,
            "paymentMethod": {"method": "checkmo", "po_number": None, "additional_data": None},
        }

        response = self.session.post(
            "https://store.implantdirect.com/us/en/rest/us_en/V1/carts/mine/payment-information",
            headers=post_headers,
            json=json_data,
        )
        print("Place Order Response:", response.status_code)
        print("Place Order Response:", response.text)

        response = self.session.get("https://store.implantdirect.com/us/en/checkout/onepage/success/", headers=headers)
        print("Order Result Response:", response.status_code)

        response_dom = Selector(text=response.text)
        order_num = response_dom.xpath('//div[@class="checkout-success"]//strong/text()').get()
        order_num = order_num.strip() if order_num else order_num
        return order_num

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("Implant Direct/create_order")
        loop = asyncio.get_event_loop()
        try:
            await asyncio.sleep(0.5)
            raise Exception()
            await self.login()
            await loop.run_in_executor(None, self.clear_cart)
            await loop.run_in_executor(None, self.add_to_cart, products)
            (
                cartId,
                shipping_payload,
                shipping_address,
                subtotal,
                shipping,
                discount,
                tax,
                order_total,
            ) = await loop.run_in_executor(None, self.proceed_checkout)
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": discount,
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": tax,
                "total_amount": order_total,
                "reduction_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
            }
        except Exception:
            print("implant_direct create_order except")
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
        print("Implant Direct/confirm_order")
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self.clear_cart)
            await loop.run_in_executor(None, self.add_to_cart, products)
            (
                cartId,
                shipping_payload,
                shipping_address,
                subtotal,
                shipping,
                discount,
                tax,
                order_total,
            ) = await loop.run_in_executor(None, self.proceed_checkout)
            if fake:
                vendor_order_detail = {
                    "retail_amount": "",
                    "savings_amount": discount,
                    "subtotal_amount": subtotal,
                    "shipping_amount": shipping,
                    "tax_amount": tax,
                    "total_amount": order_total,
                    "payment_method": "",
                    "shipping_address": shipping_address,
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
                print("Implant Direct/confirm_order DONE")

                return {
                    **vendor_order_detail,
                    **self.vendor.to_dict(),
                }

            order_num = await loop.run_in_executor(None, self.submit_order, cartId, shipping_payload)
            print("Order Number:", order_num)
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": discount,
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": tax,
                "total_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
                "order_id": order_num,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            print("Implant Direct/confirm_order DONE")

            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }
        except Exception:
            print("implant_direct confirm_order except")
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

    async def _download_invoice(self, **kwargs) -> InvoiceFile:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._download_invoice_proc, kwargs["invoice_link"])

    def _download_invoice_proc(self, invoice_link) -> InvoiceFile:
        # self.login_proc()
        with self.session.get(invoice_link) as resp:
            return resp.content
