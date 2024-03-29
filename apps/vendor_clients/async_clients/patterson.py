import asyncio
import json
import logging
import re
import time
from decimal import Decimal
from typing import Optional, Union
from urllib.parse import urlencode

import regex
from aiohttp import ClientResponse
from scrapy import Selector

from apps.orders.models import OfficeProduct
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.scrapers.utils import catch_network
from apps.types.scraper import LoginInformation
from apps.vendor_clients import errors, types
from apps.vendor_clients.async_clients.base import BaseClient, EmptyResults, PriceInfo
from apps.vendor_clients.headers.patterson import (
    ADD_PRODUCT_CART_HEADERS,
    CLEAR_CART_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    HOME_HEADERS,
    LOGIN_HEADERS,
    LOGIN_HOOK_HEADER,
    LOGIN_HOOK_HEADER2,
)
from selenium import webdriver
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


SETTINGS_REGEX = regex.compile(r"var SETTINGS \= (?P<json_data>\{(?:[^{}]|(?&json_data))*\})")


class PattersonClient(BaseClient):
    VENDOR_SLUG = "patterson"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS
    aiohttp_mode = False
    BASE_URL = "https://www.pattersondental.com"

    def gen_options(self, headless=True):
        language = "en-US"
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument("--lang=en-US,en;q=0.9")
        chrome_options.add_argument('--ignore-ssl-errors=yes')
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument(f"--user-agent={user_agent}")
        chrome_options.add_argument(f"--lang={language}")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument("--disable-dev-shm-usage")
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_experimental_option(
            "prefs",
            {
                "profile.default_content_setting_values.notifications": 2,
            },
        )
        return chrome_options

    def setup_driver(self, headless=True):
        chrome_options = self.gen_options(headless=headless)
        driver = webdriver.Chrome(
            options=chrome_options
        )
        return driver

    def extract_content(self, ele):
        text = re.sub(r"\s+", " ", " ".join(ele.xpath(".//text()").extract()))
        return text.strip() if text else ""

    def get_home_page(self):
        response = self.session.get(url=f"{self.BASE_URL}", headers=HOME_HEADERS,verify=False)
        logger.info(f"Home Page: {response.status_code}")
        return response

    def get_pre_login_page(self):
        params = {
            "returnUrl": "/",
            "signIn": "userSignIn",
        }
        response = self.session.get(url=f"{self.BASE_URL}/Account", headers=HOME_HEADERS, params=params,verify=False)
        logger.info(f"Login Page: {response.status_code}")
        return response

    def _get_login_data(self, response) -> LoginInformation:
        text = response.text
        login_url = response.url

        mo = SETTINGS_REGEX.search(text)
        if not mo:
            raise errors.VendorClientException("Missing settings object in page")

        data = json.loads(mo.group("json_data"))

        csrf = data["csrf"]
        properties = data["transId"]
        page_view_id = data["pageViewId"]

        login_post_endpoint = (
            f"https://pattersonb2c.b2clogin.com/pattersonb2c.onmicrosoft.com/"
            f"B2C_1A_PRODUCTION_Dental_SignInWithPwReset/SelfAsserted?"
            f"tx=StateProperties={properties}&p=B2C_1A_PRODUCTION_Dental_SignInWithPwReset"
        )

        headers = LOGIN_HEADERS.copy()
        headers["Referer"] = login_url
        headers["X-CSRF-TOKEN"] = csrf

        data = {
            "signInName": self.username,
            "password": self.password,
            "request_type": "RESPONSE",
        }

        return {
            "url": login_post_endpoint,
            "headers": headers,
            "data": data,
            "page_view_id": page_view_id,
            "login_page_link": login_url,
            "csrf_token": csrf,
            "properties": properties,
        }

    def check_authenticated(self, resp: ClientResponse) -> bool:
        text = resp.text
        dom = Selector(text=text)
        return True if dom.xpath("//a[@href='/Account/LogOff']") else False

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        """Login session"""
        if username:
            self.username = username
        if password:
            self.password = password

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.login_proc)
        logger.info("Login DONE")

    def login_proc(self, return_driver=False):
        driver = self.setup_driver()
        login_url = "https://www.pattersondental.com/Account"
        driver.get(login_url)
        try:
            driver.implicitly_wait(10)
            driver.find_element(By.ID, 'signInName').send_keys(self.username)
            driver.find_element(By.ID, 'password').send_keys(self.password)
            driver.find_element(By.ID, 'next').click()
            time.sleep(5)
        except:
            return False
        try:
            driver.find_element(By.XPATH,
                                '//a[@class="header__action-item header__action-item--account"]/span[contains(text(), "Account")]')
            all_cookies = driver.get_cookies()
            for cookie in all_cookies:
                self.session.cookies.set(cookie["name"], cookie["value"])

            if return_driver:
                return driver
            else:
                driver.quit()
                return True
        except:
            driver.quit()
            pass
        return False

    async def get_cart_page(self) -> Union[Selector, dict]:
        return await self.get_response_as_json(
            url="https://www.pattersondental.com/ShoppingCart/CartItemQuantities",
            headers=GET_CART_HEADERS,verify=False
        )

    async def clear_cart(self):
        products = await self.get_cart_page()
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
        await self.session.post(
            url="https://www.pattersondental.com/ShoppingCart/RemoveItemsFromShoppingCart",
            headers=CLEAR_CART_HEADERS,
            json=data,verify=False
        )

    async def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        data = {
            "itemNumbers": product["product"]["product_id"],
            "loadItemType": "ShoppingCart",
        }
        await self.session.post(
            "https://www.pattersondental.com/Item/ValidateItems",
            headers=ADD_PRODUCT_CART_HEADERS,
            data=json.dumps(data),verify=False
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

        await self.session.post(
            "https://www.pattersondental.com/ShoppingCart/AddItemsToCart",
            headers=ADD_PRODUCT_CART_HEADERS,
            data=json.dumps(data),verify=False
        )

    def get_product_dom(self, product_url):
        with self.session.get(product_url, headers=GET_PRODUCT_PAGE_HEADERS,verify=False) as resp:
            return resp

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        loop = asyncio.get_event_loop()

        resp = await loop.run_in_executor(None, self.get_product_dom, product.product.url)
        logger.debug("Response status: %s", resp.status_code)
        logger.debug("Product ID: %s", product.product.product_id)

        text = resp.text
        if resp.status_code != 200:
            logger.debug("Got response: %s", text)
            raise EmptyResults()
        page_response_dom = Selector(text=text)
        products = page_response_dom.xpath('//div[@id="ItemDetailImageAndDescriptionRow"]')
        if products:
            if "ProductFamilyDetails" in product.product.url:
                for product_dom in page_response_dom.xpath('//div[@id="productFamilyDetailsGridBody"]'):
                    mfg_number = product_dom.xpath(
                        './/div[@id="productFamilyDetailsGridBodyColumnTwoInnerRowMfgNumber"]//text()'
                    ).get()
                    price = product_dom.xpath(
                        './/div[contains(@class, "productFamilyDetailsPriceBreak")][1]//text()'
                    ).get()
                    if "/" in price:
                        price = price.split("/")[0].strip()
                    if product["mfg_number"] == mfg_number:
                        product_vendor_status = STATUS_ACTIVE
                        return PriceInfo(price=price, product_vendor_status=product_vendor_status)
            else:
                item_data = json.loads(page_response_dom.xpath('//input[@name="ItemSkuDetail"]/@value').get())
                price = item_data.get("UnitPrice", 0)
                description = item_data["ItemSubstitutionDescription"]
                image_file = item_data["Images"][0]["AssetFilename"]
                image_url = "https://content.pattersondental.com/items/LargeSquare/images/"+image_file
                product_vendor_status = STATUS_ACTIVE
                return PriceInfo(
                    price=price,
                    product_vendor_status=product_vendor_status,
                    description=description,
                    image=image_url
                )
        else:
            product_vendor_status = self.product_vendor_not_exist
            return PriceInfo(
                price=0, 
                product_vendor_status=product_vendor_status,
                description="",
                image="",
            )

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
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
                "price": Decimal(str(product_detail["UnitPrice"]) if product_detail["UnitPrice"] else 0),
                "product_vendor_status": "",
                "category": "",
                "unit": "",
            }
        except (TypeError, json.decoder.JSONDecodeError):
            print("Patterson/TypeError")
            pass

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass

    async def get_product(self, product, semaphore, login_required=False):
        try:
            driver = self.login_proc(return_driver=True)
            driver.get(product["url"])
            page_source = driver.page_source

            dom = Selector(text=page_source)
            product_detail = self.serialize(product,dom)
            driver.quit()
            return product_detail
        except Exception as e:
            logger.exception("Got exception while getting dom => ", str(e))
