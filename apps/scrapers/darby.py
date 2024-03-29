import asyncio
import datetime
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from aiohttp import ClientResponse
from scrapy import Selector
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from apps.common import messages as msgs
from apps.common.utils import clean_text, concatenate_list_as_string
from apps.scrapers.base import Scraper
from apps.scrapers.schema import Order, Product, ProductCategory, VendorOrderDetail
from apps.scrapers.utils import (
    catch_network,
    convert_string_to_price,
    semaphore_coroutine,
)
from apps.types.orders import CartProduct
from apps.types.scraper import (
    InvoiceFormat,
    InvoiceType,
    LoginInformation,
    ProductSearch,
)
import cloudscraper
from apps.scrapers.errors import VendorAuthenticationFailed
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36",  # noqa
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.darbydental.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.darbydental.com/DarbyHome.aspx",
    "Accept-Language": "en-US,en;q=0.9",
}

SEARCH_HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
    "sec-ch-ua-mobile": "?0",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/92.0.4515.159 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml; q=0.9,image/avif,"
    "image/webp,image/apng,*/*; q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.darbydental.com/",
    "Accept-Language": "en-US,en;q=0.9",
}
GET_CART_HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.darbydental.com/Home.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}
ADD_TO_CART_HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36",
    "sec-ch-ua-platform": '"Windows"',
    "Origin": "https://www.darbydental.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.darbydental.com",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
CHECKOUT_HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.darbydental.com/scripts/cart.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
ORDER_HEADERS = {
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "X-MicrosoftAjax": "Delta=true",
    "sec-ch-ua-platform": '"Windows"',
    "Accept": "*/*",
    "Origin": "https://www.darbydental.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.darbydental.com/scripts/checkout.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}

REVIEW_ORDER_HEADER = {
    "Connection": "keep-alive",
    "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;"
    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.darbydental.com/scripts/cart.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}

CHECKOUT_SUBMIT_HEADER = {
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "X-MicrosoftAjax": "Delta=true",
    "sec-ch-ua-platform": '"Windows"',
    "Accept": "*/*",
    "Origin": "https://www.darbydental.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.darbydental.com/scripts/checkout.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}
REAL_ORDER_HEADER = {
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "X-MicrosoftAjax": "Delta=true",
    "sec-ch-ua-platform": '"Windows"',
    "Accept": "*/*",
    "Origin": "https://www.darbydental.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.darbydental.com/scripts/checkout.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}


def wait_and_click(d, xp, timeout=15):
    account_name_input = WebDriverWait(d, timeout=timeout).until(EC.element_to_be_clickable((By.XPATH, xp)))
    account_name_input.click()


def wait_element(d, xp, timeout=15):
    wait = WebDriverWait(d, timeout=timeout)
    element = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
    return element


class DarbyScraper(Scraper):
    BASE_URL = "https://www.darbydental.com"
    CATEGORY_URL = "https://www.darbydental.com/scripts/Categories.aspx"
    INVOICE_TYPE = InvoiceType.PDF_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT


    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        logger.debug("Logging in...")
        if username:
            self.username = username
        if password:
            self.password = password

        login_info = await self._get_login_data()
        logger.debug("Got login data: %s", login_info)
        for tryy in range(3):
            self.session = aiohttp.ClientSession()
            try:
                async with self.session.post(
                    login_info["url"], headers=login_info["headers"], data=login_info["data"]
                ) as resp:
                    if resp.status != 200:
                        resp_body = await resp.read()
                        logger.warning("Got %s status when trying to login: %s", resp.status, resp_body)
                        raise VendorAuthenticationFailed()
                    is_authenticated = await self._check_authenticated(resp)
                    if not is_authenticated:
                        logger.warning("Not authenticated after an attempt")
                        raise VendorAuthenticationFailed()
                    logger.info("Login success!")
                return True
            except VendorAuthenticationFailed as auth_error:
                logger.error("VendorAuthenticationFailed: %s", auth_error)
                return False
            except Exception as e:
                logger.error("An unexpected error occurred: %s", e)
                return False


    async def _check_authenticated(self, response: ClientResponse) -> bool:
        res = await response.json()
        return res["m_Item2"] and res["m_Item2"]["<username>k__BackingField"] == self.username

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        return {
            "url": f"{self.BASE_URL}/api/Login/Login",
            "headers": HEADERS,
            "data": {"username": self.username, "password": self.password, "next": ""},
        }

    async def get_shipping_track(self, order, order_id):
        url = f"{self.BASE_URL}/Scripts/InvoiceTrack.aspx?invno={order_id}"
        async with self.session.get(
            url, headers=HEADERS
        ) as resp:
            try:
                track_response_dom = Selector(text=await resp.text())
                tracking_dom = track_response_dom.xpath(
                    "//table[contains(@id, 'MainContent_rpt_gvInvoiceTrack_')]//tr[@class='pdpHelltPrimary']"
                )[0]
                vendor_order_status = self.extract_first(tracking_dom, "./td[4]//text()")
                print('vendor_order_status:',vendor_order_status)
                tracking_number = clean_text("./td[3]//text()", tracking_dom)
                if 'Delivered' in vendor_order_status:
                    order["status"] = "delivered"
                else:
                    try:
                        for tryy in range(3):
                            try:
                                user_agent = UserAgent().random
                                self.cloud_scraper.get(headers={ "User-Agent":user_agent},url=f'https://www.ups.com/track?InquiryNumber1={tracking_number}&AcceptUPSLicenseAgreement=Yes&TypeOfInquiryNumber=T&nonUPS_body=BACKGROUND%3D%22http://www.darbydental.com/background.gif%22%20BGPROPERTIES%3D%22FIXED%22',timeout=20)
                                UPS_Failed = False
                                break
                            except:
                                UPS_Failed = True
                        if UPS_Failed is False:
                            cookies = self.cloud_scraper.cookies.get_dict()
                            X_XSRF_TOKEN = cookies['X-XSRF-TOKEN-ST']

                            url = "https://webapis.ups.com/track/api/Track/GetStatus?loc=en_US"

                            data = {
                                "Locale": "en_US", "TrackingNumber": [tracking_number], "Requester": "",
                                "returnToValue": ""
                            }
                            header = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                                "X-Xsrf-Token": X_XSRF_TOKEN,
                                "Content-Type": "application/json",
                                "Origin": "https://www.ups.com",
                                "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
                                "Sec-Ch-Ua-Mobile": "?0",
                                "Sec-Ch-Ua-Platform": '"Windows"',
                                "Sec-Fetch-Dest": "empty",
                                "Sec-Fetch-Mode": "cors",
                                "Sec-Fetch-Site": "same-site",
                                "authority": "webapis.ups.com",
                                "method": "POST",
                                "path": "/track/api/Track/GetStatus?loc=en_US",
                                "scheme": "https",
                                "Accept": "application/json, text/plain, */*",
                                "Accept-Encoding": "gzip, deflate, br, zstd",
                                "Accept-Language": "en-US,en;q=0.9"
                            }
                            response = self.cloud_scraper.post(url, json=data, headers=header)
                            print('UPS TRACKING STATUS =======================================\n',response.json())
                            try:
                                json_data = response.json()
                                delivered_status = json_data['trackDetails'][0]['progressBarType']
                                if delivered_status == "Delivered":
                                    order["status"] = 'delivered'
                                else:
                                    order["status"] = 'processing'
                            except:
                                order["status"] = 'processing'
                        else:
                            order["status"] = 'processing'
                        print("=========status===========",order["status"])

                    except Exception as e:
                        order["status"] = 'processing'

                if tracking_number:
                    params = {
                        "InquiryNumber1": tracking_number,
                        "AcceptUPSLicenseAgreement": "Yes",
                        "TypeOfInquiryNumber": "T",
                        "nonUPS_body": "BACKGROUND%3D%22http:",
                        "loc": "en_US",
                        "requester": "ST/trackdetails",
                    }
                    order["tracking_link"] = f"https://www.ups.com/track?{urlencode(params)}"
            except IndexError:
                order["status"] = "processing"
            print('==========order==============')
            print(order)
            return order

    async def get_order_products(self, order, link):
        async with self.session.get(f"{self.BASE_URL}/Scripts/{link}", headers=HEADERS) as resp:
            order_detail_response = Selector(text=await resp.text())
            order["products"] = []
            for detail_row in order_detail_response.xpath(
                "//table[@id='MainContent_gvInvoiceDetail']//tr[@class='pdpHelltPrimary']"  # noqa
            ):
                # product_id = self.merge_strip_values(detail_row, "./td[1]/a//text()")
                product_name = self.merge_strip_values(detail_row, "./td[2]//text()")
                if "COLORADO RETAIL DELIVERY" not in product_name:
                    product_url = self.merge_strip_values(detail_row, "./td[1]/a//@href")
                    product_id = product_url.split("/")[-1]
                    if product_url:
                        product_url = f"{self.BASE_URL}{product_url}"

                    product_image = self.merge_strip_values(detail_row, "./td[1]/input//@src")
                    product_image = product_image if product_image else None
                    product_price = self.merge_strip_values(detail_row, "./td[4]//text()")
                    quantity = self.merge_strip_values(detail_row, "./td[5]//text()")
                    order["products"].append(
                        {
                            "product": {
                                "product_id": product_id,
                                "name": product_name,
                                "description": "",
                                "url": product_url,
                                "category": "",
                                "images": [{"image": product_image}],
                                "price": product_price,
                                "vendor": self.vendor.to_dict(),
                            },
                            "unit_price": product_price,
                            "quantity": quantity,
                        }
                    )
        await self.get_missing_products_fields(
            order["products"],
            fields=(
                "description",
                # "images",
                "category",
            ),
        )

        return order

    @semaphore_coroutine
    async def get_order(self, sem, order_dom, order_date: Optional[datetime.date] = None, office=None):
        link = self.merge_strip_values(order_dom, "./td[1]/a/@href")
        order_id = self.merge_strip_values(order_dom, "./td[1]//text()")
        invoice_link = self.merge_strip_values(order_dom, "./td[9]/a/@href")
        order = {
            "order_id": order_id,
            "total_amount": self.merge_strip_values(order_dom, ".//td[8]//text()"),
            "currency": "USD",
            "order_date": order_date
            if order_date
            else datetime.datetime.strptime(self.merge_strip_values(order_dom, ".//td[2]//text()"), "%m/%d/%Y").date(),
            "invoice_link": f"{self.BASE_URL}{invoice_link}",
        }
        add_product_info_to_order,add_order_status_to_order = await asyncio.gather(self.get_order_products(order, link), self.get_shipping_track(order, order_id))
        order.update(add_product_info_to_order)
        order.update(add_order_status_to_order)

        if "tracking_link" in order:
            tracking_link = order.pop("tracking_link")
            for product in order["products"]:
                product["tracking_link"] = tracking_link
        if office:
            print("===== darby/get_order 6 =====")
            order_from_dict = Order.from_dict(order)
            print("==========order_from_dict=========",order_from_dict)
            await self.save_order_to_db(office, order=order_from_dict)
        print("===== darby/get_order 7 =====")

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
        print("Darby/get_orders")
        sem = asyncio.Semaphore(value=2)
        url = f"{self.BASE_URL}/Scripts/InvoiceHistory.aspx"
        self.cloud_scraper = cloudscraper.create_scraper()


        if perform_login:
            await self.login()

        orders = []
        async with self.session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            response_dom = Selector(text=text)
            orders_dom = response_dom.xpath(
                "//table[@id='MainContent_gvInvoiceHistory']//tr[@class='pdpHelltPrimary']"
            )
            tasks = []
            for order_dom in orders_dom:
                order_date = datetime.datetime.strptime(
                    self.merge_strip_values(order_dom, ".//td[2]//text()"), "%m/%d/%Y"
                ).date()

                if from_date and to_date and (order_date < from_date or order_date > to_date):
                    continue

                order_id = self.merge_strip_values(order_dom, "./td[1]//text()")
                if completed_order_ids and order_id in completed_order_ids:
                    continue

                tasks.append(self.get_order(sem, order_dom, order_date, office))

            if tasks:
                orders = await asyncio.gather(*tasks, return_exceptions=True)
        self.cloud_scraper.close()
        return [Order.from_dict(order) for order in orders]

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        if perform_login:
            await self.login()

        async with self.session.get(product_url) as resp:
            res = Selector(text=await resp.text())
            product_name = self.extract_first(res, ".//span[@id='MainContent_lblName']/text()")
            product_description = self.extract_first(res, ".//span[@id='MainContent_lblDescription']/text()")
            # product_images = res.xpath(".//div[contains(@class, 'productSmallImg')]/img/@src").extract()
            product_price = self.extract_first(res, ".//span[@id='MainContent_lblPrice']/text()")
            product_price = re.findall("\\d+\\.\\d+", product_price)
            product_price = product_price[0] if isinstance(product_price, list) else None
            product_category = res.xpath(".//ul[contains(@class, 'breadcrumb')]/li/a/text()").extract()[1:]

            return {
                "product_id": product_id,
                "name": product_name,
                "description": product_description,
                "url": product_url,
                "images": [
                    {
                        "image": "https://azfun-web-image-picker.azurewebsites.net/api/getImage?"
                        f"sku={product_id.replace('-', '')}&type=WebImages"
                    }
                ],
                "category": product_category,
                "price": product_price,
                "vendor": self.vendor.to_dict(),
            }

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        url = "https://www.darbydental.com/scripts/productlistview.aspx"
        page_size = 30
        params = {
            "term": query,
        }
        data = {
            "ctl00$masterSM": f"ctl00$MainContent$UpdatePanel1|ctl00$MainContent$ppager$ctl{page - 1:02}$pagelink",
            "ctl00$logonControl$txtUsername": "",
            "ctl00$logonControl$txtPassword": "",
            "ctl00$bigSearchTerm": query,
            "ctl00$searchSmall": query,
            # "ctl00$MainContent$currentPage": f"{current_page}",
            # "ctl00$MainContent$pageCount": clean_text(
            #     response, "//input[@name='ctl00$MainContent$pageCount']/@value"
            # ),
            "ctl00$MainContent$currentSort": "priceLowToHigh",
            "ctl00$MainContent$selPerPage": f"{page_size}",
            "ctl00$MainContent$sorter": "priceLowToHigh",
            # "ctl00$serverTime": clean_text(response, "//input[@name='ctl00$serverTime']/@value"),
            "__EVENTTARGET": f"ctl00$MainContent$ppager$ctl{page - 1:02}$pagelink",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": "",
            "__VIEWSTATEGENERATOR": "A1889DD4",
            "__ASYNCPOST": "true",
        }
        products = []

        async with self.session.post(url, headers=SEARCH_HEADERS, data=data, params=params) as resp:
            response_dom = Selector(text=await resp.text())
            total_size_str = response_dom.xpath(".//span[@id='MainContent_resultCount']/text()").extract_first()
            matches = re.search(r"of(.*?)results", total_size_str)
            total_size = int(matches.group(1).strip()) if matches else 0
            products_dom = response_dom.xpath("//div[@id='productContainer']//div[contains(@class, 'prodcard')]")
            for product_dom in products_dom:
                price = self.extract_first(product_dom, ".//div[contains(@class, 'prod-price')]//text()")
                if "@" not in price:
                    continue
                _, price = price.split("@")
                product_id = self.extract_first(product_dom, ".//div[@class='prodno']/label//text()")
                product_name = self.extract_first(product_dom, ".//div[@class='prod-title']//text()")
                product_url = self.BASE_URL + self.extract_first(product_dom, ".//a[@href]/@href")
                product_image = self.extract_first(product_dom, ".//img[@class='card-img-top']/@src")
                products.append(
                    Product.from_dict(
                        {
                            "product_id": product_id,
                            "name": product_name,
                            "description": "",
                            "url": product_url,
                            "images": [
                                {
                                    "image": product_image,
                                }
                            ],
                            "price": price,
                            "vendor": self.vendor.to_dict(),
                        }
                    )
                )
        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": products,
            "last_page": page_size * page >= total_size,
        }

    def _get_vendor_categories(self, response) -> List[ProductCategory]:
        return [
            ProductCategory(
                name=category.xpath("./text()").extract_first(),
                slug=category.attrib["href"].split("/")[-1],
            )
            for category in response.xpath(
                "//ul[@id='catCage2']//div[contains(@class, 'card-footer')]/a[contains(@class, 'topic-link')]"
            )
        ]

    async def get_cart_page(self):
        for tryy in range(3):
            try:
                async with self.session.get("https://www.darbydental.com/scripts/cart.aspx", headers=GET_CART_HEADERS) as resp:
                    dom = Selector(text=await resp.text())
                    return dom
            except Exception as e:
                if tryy == 2:
                    logger.error(f'Unable to get cart page:{str(e)}')
    async def add_products_to_cart(self, products: List[CartProduct]):
        logger.info("Adding products to cart")
        data = {}
        for index, product in enumerate(products):
            data[f"items[{index}][Sku]"] = (product["product_id"],)
            data[f"items[{index}][Quantity]"] = product["quantity"]

        url = "https://www.darbydental.com/api/ShopCart/doAddToCart2"
        for tryy in range(3):
            try:
                response = await self.session.post(url, headers=ADD_TO_CART_HEADERS, data=data)
                logger.info("Request to %s, response status = %s", url, response.status)
                await response.text()
                break
            except Exception as e:
                if tryy == 2:
                    logger.info(f'Unable to add product to cart:{str(e)}')
    async def clear_cart(self):
        logger.info("Clearing cart...")
        cart_page_dom = await self.get_cart_page()

        products: List[CartProduct] = []
        for tr in cart_page_dom.xpath('//div[@id="MainContent_divGridScroll"]//table[@class="gridPDP"]//tr'):
            sku = tr.xpath(
                './/a[starts-with(@id, "MainContent_gvCart_lbRemoveFromCart_")][@data-prodno]/@data-prodno'
            ).get()
            if sku:
                products.append(CartProduct(product_id=sku, quantity=0))

        logger.info("Got products: %s", products)
        if products:
            await self.add_products_to_cart(products)

    async def review_order(self) -> VendorOrderDetail:
        cart_page_dom = await self.get_cart_page()

        shipping_address = concatenate_list_as_string(
            cart_page_dom.xpath('//span[@id="MainContent_lblAddress"]//text()').extract()
        )
        subtotal_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblSubTotal"]//text()').get()
        )
        shipping_amount = convert_string_to_price(
            cart_page_dom.xpath(
                '//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblServiceCharge"]//text()'
            ).get()
        )
        tax_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblEstimatedTax"]//text()').get()
        )
        total_amount = convert_string_to_price(
            cart_page_dom.xpath('//tbody[@id="orderTotals"]//td/span[@id="MainContent_lblTotal"]//text()').get()
        )
        data = {
            "subtotal_amount": subtotal_amount,
            "shipping_amount": shipping_amount,
            "tax_amount": tax_amount,
            "total_amount": total_amount,
            "shipping_address": shipping_address,
            "reduction_amount": total_amount,
        }
        logger.info("Review order: %s", data)
        return VendorOrderDetail.from_dict(data)


    async def checkout(self):
        for tryy in range(3):
            try:
                response = await self.session.get('https://www.darbydental.com/scripts/checkout.aspx')
                text = await response.text()
                break
            except Exception as e:
                if tryy == 2:
                    logger.error(f'Unable to get checkout page:{str(e)}')
        checkout_header = {
            "Cache-Control":"no-cache",
            "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
            "Referer":"https://www.darbydental.com/scripts/checkout.aspx",
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "X-MicrosoftAjax":"Delta=true",
            "X-Requested-With":"XMLHttpRequest",
            "sec-ch-ua":'"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile":"?0",
            "sec-ch-ua-platform":'"Windows"'
        }
        checkout_dom = Selector(text= text)
        data = {
            "ctl00$masterSM":"ctl00$MainContent$UpdatePanel1|ctl00$MainContent$completeOrder",
            "__EVENTTARGET":"ctl00$MainContent$completeOrder",
            "__EVENTARGUMENT":"",
            "__LASTFOCU":"",
            "__VIEWSTATE":checkout_dom.xpath("//input[@id='__VIEWSTATE']/@value").get().replace("\xa0"," "),
            "__VIEWSTATEGENERATOR":checkout_dom.xpath("//input[@id='__VIEWSTATEGENERATOR']/@value").get().replace("\xa0"," "),
            "ctl00$logonControl$txtUsername":self.username,
            "ctl00$logonControl$txtPassword":self.password,
            "ctl00$ddlPopular":"-1",
            "ctl00$bigSearchTerm":"",
            "search_param":"all",
            "ctl00$Categories2$siteCategories$ctl00$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl00$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl07$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl07$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl14$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl14$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl21$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl21$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl28$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl28$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl35$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl35$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl01$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl01$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl08$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl08$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl15$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl15$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl22$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl22$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl29$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl29$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl36$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl36$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl02$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl02$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl09$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl09$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl16$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl16$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl23$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl23$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl30$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl30$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl37$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl37$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl03$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl03$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl10$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl10$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl17$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl17$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl24$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl24$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl31$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl31$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl38$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl38$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl04$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl04$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl11$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl11$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl18$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl18$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl25$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl25$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl32$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl32$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl39$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl39$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl05$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl05$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl12$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl12$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl19$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl19$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl26$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl26$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl33$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl33$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl40$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl40$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl06$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl06$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl13$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl13$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl20$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl20$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl27$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl27$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl34$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl34$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$Categories2$siteCategories$ctl41$hfName":checkout_dom.xpath("//input[@name='ctl00$Categories2$siteCategories$ctl41$hfName']/@value").get().replace("\xa0"," "),
            "ctl00$MainContent$pono":f"Ordo ({time.strftime('%Y-%m-%d')})",
            "ctl00$MainContent$instr":"",
            "ctl00$MainContent$couponCode":"",
            "ctl00$MainContent$paymode":checkout_dom.xpath("//input[@name='ctl00$MainContent$paymode']/@value").get().replace("\xa0"," "),
            "ctl00$serverTime":datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S:%f")[:-3],
            "ctl00$footer$txtContactFullName":"",
            "ctl00$footer$hfRepEmail":"",
            "ctl00$footer$txtContactEmail":"",
            "ctl00$footer$txtContactPhone":"",
            "ctl00$footer$txtContactCompany":"",
            "ctl00$footer$ddlContactDepartment":"0",
            "ctl00$footer$txtContactMessage":"",
            "g-recaptcha-response":"",
            "captcha":"",
            "ctl00$footer$hfCaptcha":"",
            "__ASYNCPOST":"true"
        }
        for tryy in range(3):
            try:
                response = await self.session.post("https://www.darbydental.com/scripts/checkout.aspx",data=data,headers=checkout_header)
                placed_order_text = await response.text()
            except Exception as e:
                if tryy == 2:
                    logger.error(f'Unable to confirm order:{str(e)}')
        try:
            invoice_number = placed_order_text.split("invno%")[-1][:7].replace('|',"")
        except Exception as e:
            logger.error(f'Unable to get invoice number: {str(e)}')
        return invoice_number



    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("darby/confirm_order")
        try:
            await self.clear_cart()
            await self.add_products_to_cart(products)
            vendor_order_detail = await self.review_order()

            if fake:
                print("darby/confirm_order DONE (faked)")
                return {
                    **vendor_order_detail.to_dict(),
                    **self.vendor.to_dict(),
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }

            invoice_num = await self.checkout()
            logger.info("Got invoice num: %s", invoice_num)
            self.session.close()
            return {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
                "order_id": invoice_num,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
        except Exception:
            logger.exception("darby/confirm_order except")
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
                "order_id": "invalid",
                "order_type": msgs.ORDER_TYPE_PROCESSING,
            }
