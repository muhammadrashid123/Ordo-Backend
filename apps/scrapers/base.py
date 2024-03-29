import asyncio
import datetime
import logging
import re
import ssl
import time
import traceback
import uuid
from collections import defaultdict
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Dict, List, Optional, Tuple, Union
import certifi
import requests
from aiohttp import ClientResponse, ClientSession
from asgiref.sync import sync_to_async
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone
from requests import Response
from scrapy import Selector
from selenium import webdriver
from selenium.webdriver.common.by import By
from slugify import slugify

from apps.accounts.constants import DEFAULT_FRONT_OFFICE_BUDGET_VENDORS
from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import OfficeVendor, ShippingMethod, Subaccount
from apps.common import messages as msgs
from apps.common.choices import BUDGET_SPEND_TYPE, OrderType
from apps.common.month import Month
from apps.orders.services.product import ProductService
from apps.scrapers.errors import DownloadInvoiceError, VendorAuthenticationFailed
from apps.scrapers.headers.base import HTTP_HEADERS
from apps.scrapers.schema import Order, Product, ProductCategory, VendorOrderDetail
from apps.scrapers.semaphore import fake_semaphore
from apps.scrapers.utils import catch_network, semaphore_coroutine
from apps.types.orders import CartProduct, VendorCartProduct
from apps.types.scraper import (
    InvoiceFile,
    InvoiceFormat,
    InvoiceInfo,
    InvoiceType,
    LoginInformation,
    ProductSearch,
    SmartProductID,
)

logger = logging.getLogger(__name__)


class Scraper:
    aiohttp_mode = True
    selenium_mode = False
    selenium_mode_headless = True


    def __init__(
        self,
        session: ClientSession,
        vendor,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        logger.setLevel(logging.WARNING)
        self.session = session if self.aiohttp_mode else requests.Session()
        self.vendor = vendor
        self.username = username
        self.password = password
        self.orders = {}
        self.objs = {"product_categories": defaultdict(dict)}
        self.logged_in = True
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.driver = self.setup_driver(self.selenium_mode_headless) if self.selenium_mode else None
        self.content = None

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
        chrome_options.add_argument("--ignore-ssl-errors=yes")
        chrome_options.add_argument("--ignore-certificate-errors")
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
        driver = webdriver.Chrome(options=chrome_options)
        return driver

    @staticmethod
    def extract_first(dom, xpath):
        return x.strip() if (x := dom.xpath(xpath).extract_first()) else x

    @staticmethod
    def extract_string_only(s):
        return re.sub(r"\s+", " ", s).strip()

    @staticmethod
    def extract_amount(s):
        return re.search(r"[,\d]+.?\d*", s).group(0)

    @staticmethod
    def merge_strip_values(dom, xpath, delimeter=""):
        return delimeter.join(filter(None, map(str.strip, dom.xpath(xpath).extract())))

    @staticmethod
    def remove_thousands_separator(value):
        try:
            value = value.strip(" $")
            value = value.replace(" ", "")
            value = value.replace(",", "")
            return value
        except AttributeError:
            return "0"

    @staticmethod
    def get_category_slug(value) -> Optional[str]:
        try:
            return value.split("/")[-1]
        except (AttributeError, IndexError):
            pass

    @staticmethod
    def extract_price(value):
        prices = re.findall("\\d+\\.\\d+", value)
        return prices[0] if prices else None

    @staticmethod
    def normalize_order_status(order_status):
        if order_status is None:
            return "closed"

        order_status = order_status.lower()
        if any(status in order_status for status in ("delivered", "complete", "closed", "shipped")):
            return "closed"
        elif "cancelled" in order_status:
            return "cancelled"
        return "open"

    @staticmethod
    def normalize_order_product_status(order_product_status):
        if order_product_status is None:
            return "processing"
        order_product_status = order_product_status.lower()

        if any(status in order_product_status for status in ("processing", "pending", "open")):
            return "processing"
        elif any([status in order_product_status for status in ("backordered",)]):
            return "backordered"
        elif any([status in order_product_status for status in ("returned",)]):
            return "returned"
        elif any([status in order_product_status for status in ("cancelled",)]):
            return "cancelled"
        elif any([status in order_product_status for status in ("received", "complete")]):
            return "received"
        else:
            return order_product_status

    @staticmethod
    def normalize_product_status(product_status):
        product_status = product_status.lower()
        return product_status

    async def _get_check_login_state(self) -> Tuple[bool, dict]:
        return False, {}

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> SimpleCookie:
        logger.debug("Logging in...")
        if username:
            self.username = username
        if password:
            self.password = password

        is_already_login, kwargs = await self._get_check_login_state()
        if not is_already_login:
            login_info = await self._get_login_data(**kwargs)
            logger.debug("Got login data: %s", login_info)
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
                    await self._after_login_hook(resp)

                return resp.cookies

            except VendorAuthenticationFailed as auth_error:
                logger.error("VendorAuthenticationFailed: %s", auth_error)

            except Exception as e:
                logger.error("An unexpected error occurred: %s", e)

    async def _check_authenticated(self, response: Union[ClientResponse, Response]) -> bool:
        return True

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        pass

    async def _after_login_hook(self, response: ClientResponse):
        pass

    def _get_vendor_categories(self, response) -> List[ProductCategory]:
        pass

    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        raise NotImplementedError()

    async def get_product_as_dict(self, product_id, product_url, perform_login=False) -> dict:
        raise NotImplementedError()

    async def get_product(self, product_id, product_url, perform_login=False, semaphore=None) -> Product:
        product = await self.get_product_as_dict(product_id, product_url, perform_login)
        return Product.from_dict(product)

    async def get_product_v2(
        self, product_id, product_url, perform_login=False, semaphore=None, queue: asyncio.Queue = None
    ) -> Optional[Product]:
        if not semaphore:
            semaphore = fake_semaphore
        async with semaphore:
            product = await self.get_product_as_dict(product_id, product_url, perform_login)
            product = Product.from_dict(product)
            if queue:
                await queue.put(product)
            await asyncio.sleep(3)

        return product

    @semaphore_coroutine
    async def get_missing_product_fields(self, sem, product_id, product_url, perform_login=False, fields=None) -> dict:
        product = await self.get_product_as_dict(product_id, product_url, perform_login)

        if fields and isinstance(fields, tuple):
            return {k: v for k, v in product.items() if k in fields}

    async def fetch_invoice_async(self, invoice_link):
        try:
            return await self.session.get(invoice_link, headers=HTTP_HEADERS)
        except Exception as e:
            return await self.session.get(invoice_link, headers=HTTP_HEADERS,verify=False)

    def fetch_invoice_via_selenium(self,invoice_link):
        driver = self.setup_driver()
        driver.get("https://shop.benco.com/Login/Login")
        driver.implicitly_wait(5)
        driver.find_element(By.ID, 'username').send_keys(self.username)
        driver.find_element(By.ID, 'password').send_keys(self.password)
        driver.find_element(By.ID, 'sign-in').click()
        selenium_cookies = driver.get_cookies()
        session = requests.session()
        for cookie in selenium_cookies:
            session.cookies.set(cookie["name"], cookie["value"])
        response = session.get(invoice_link)
        driver.close()
        return response.content

    async def fetch_invoice(self, invoice_link):
        try:
            return self.session.get(invoice_link, headers=HTTP_HEADERS).content
        except Exception as e:
            return self.session.get(invoice_link, headers=HTTP_HEADERS,verify=False).content
            
    async def download_invoice(self, **kwargs) -> InvoiceFile:
        invoice_link = kwargs.get("invoice_link")
        order_id = kwargs.get("order_id")
        vendor = kwargs.get('vendor')

        if invoice_link is None and order_id is None:
            raise DownloadInvoiceError("Not Found invoice")

        invoice_type = getattr(self, "INVOICE_TYPE", None)
        invoice_format = getattr(self, "INVOICE_FORMAT", None)
        if invoice_type is None or invoice_format is None:
            raise DownloadInvoiceError(f"{self.vendor} does not implement Downloading Invoice")

        if vendor != 'Benco':
            await self.login()

        if hasattr(self, "_download_invoice") and callable(self._download_invoice) and vendor != 'Benco':
            self.content = await self._download_invoice(**kwargs)
        elif vendor == 'Benco':
            self.content = self.fetch_invoice_via_selenium(invoice_link)
        else:
            try:
                self.content = await self.fetch_invoice_async(invoice_link)
            except Exception as e:
                logger.debug(e)
                self.content = await self.fetch_invoice(invoice_link)

            if hasattr(self.content, "content"):
                self.content = self.content.content
                if hasattr(self.content, "read"):
                    self.content = await self.content.read()

        if invoice_format == InvoiceFormat.USE_ORDO_FORMAT:
            if isinstance(self.content, bytes):
                self.content = self.content.decode("utf-8")
            invoice_page_dom = Selector(text=self.content)
            invoice_info = await self.extract_info_from_invoice_page(invoice_page_dom)
            self.content = await self.make_invoice_template(invoice_info)

        if invoice_type == InvoiceType.HTML_INVOICE:
            self.content = await self.html2pdf(self.content)

        return self.content

    @staticmethod
    async def run_command(cmd, data=None):
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate(data)
            if stderr:
                raise Exception(stderr)
            return stdout
        except Exception as e:
            raise e

    async def extract_info_from_invoice_page(self, invoice_page_dom: Selector) -> InvoiceInfo:
        raise NotImplementedError(
            "Scraper that has html format invoice must implement `extract_info_from_invoice_page`"
        )

    async def make_invoice_template(self, invoice_info: InvoiceInfo) -> InvoiceFile:
        html_content = render_to_string("invoice-template.html", invoice_info.to_dict())
        html_content = render_to_string("invoice-template.html", invoice_info.to_dict())
        return html_content.encode("utf-8")

    async def html2pdf(self, data: InvoiceFile):
        return await self.run_command(
            cmd="xvfb-run -a -s '-screen 0 1024x768x24' wkhtmltopdf --quiet - - | cat", data=data
        )

    def save_single_product_to_db(self, product_data, office=None, is_inventory=False, keyword=None, order_date=None):
        """save product to product table"""
        try:
            logger.debug("Saving %s to db", product_data)
            from django.db.models import Q

            from apps.orders.models import OfficeProduct as OfficeProductModel
            from apps.orders.models import (
                OfficeProductCategory as OfficeProductCategoryModel,
            )
            from apps.orders.models import Product as ProductModel
            from apps.orders.models import ProductCategory as ProductCategoryModel
            from apps.orders.models import ProductImage as ProductImageModel

            other_category = self.objs["product_categories"].get("other_category", None)
            if other_category is None:
                other_category = ProductCategoryModel.objects.filter(slug="other").first()
                self.objs["product_categories"]["other_category"] = other_category

            vendor_data = product_data.pop("vendor")
            product_images = product_data.pop("images", [])
            product_id = product_data.pop("product_id")
            product_category_hierarchy = product_data.pop("category")

            if product_category_hierarchy:
                product_root_category = slugify(product_category_hierarchy[0])
                product_category = self.objs["product_categories"].get(product_root_category, None)
                if product_category is None:
                    q = {f"vendor_categories__{vendor_data['slug']}__contains": product_root_category}
                    q = Q(**q)
                    product_category = ProductCategoryModel.objects.filter(q).first()
                    self.objs["product_categories"][product_root_category] = product_category
            else:
                product_category = None
            logger.debug("Product category: %s", product_category)

            product_data["category"] = product_category or other_category
            product_price = product_data.pop("price")
            if "nickname" in product_data:
                product_data.pop("nickname")
            print("vendor assa===", self.vendor)
            print("product_id assa===", product_id)
            print("product_data assa===", product_data)
            product, created = ProductModel.objects.get_or_create(
                vendor=self.vendor,
                product_id=product_id,
                defaults=product_data,
            )
            print("product single ======", product)
            print("created single ======", created)
            logger.debug("Product %s created=%s", product, created)
            if keyword:
                product.tags.add(keyword)

            if created:
                product.parent_id = ProductService.get_or_create_parent_id(product)
                product.save(update_fields=["parent_id"])
                logger.debug("Creating parent: %s", product.parent_id)
                product_images = [
                    ProductImageModel(
                        product=product,
                        image=product_image["image"],
                    )
                    for product_image in product_images
                ]
                ProductImageModel.objects.bulk_create(product_images)
                logger.debug("Created images: %s", product_images)
            if office:
                office_product_category_slug = product_data["category"].slug
                office_product_category = (
                    self.objs["product_categories"].get(office, {}).get(office_product_category_slug)
                )
                if office_product_category is None:
                    office_product_category = OfficeProductCategoryModel.objects.filter(
                        office=office, slug=office_product_category_slug
                    ).first()
                    logger.debug("Office product category: %s", office_product_category)
                    self.objs["product_categories"][office][office_product_category_slug] = office_product_category

                try:
                    office_product = OfficeProductModel.objects.get(
                        office=office,
                        product=product,
                    )
                    office_product.price = product_price
                    office_product.office_product_category = office_product_category
                    if is_inventory:
                        office_product.is_inventory = is_inventory

                    if order_date:
                        if office_product.last_order_date is None or office_product.last_order_date < order_date:
                            office_product.last_order_date = order_date
                            office_product.last_order_price = product_price

                    office_product.save()
                    logger.debug("Updated office product: %s", office_product)
                except OfficeProductModel.DoesNotExist:
                    office_product = OfficeProductModel.objects.create(
                        office=office,
                        product=product,
                        is_inventory=is_inventory,
                        price=product_price,
                        office_product_category=office_product_category,
                        last_order_date=order_date,
                        last_order_price=product_price,
                        price_expiration=timezone.now(),
                    )
                    logger.debug("Created office product: %s", office_product)

            else:
                office_product = None

            return product, office_product
        except Exception as e:
            print(f"An error occurred ----: {e}")
            # Handle the error as per your requirement
            traceback.print_exc()
        return []

    def find_vendor_order(self, office, order_data: dict, order_products: list):
        from apps.orders.models import VendorOrder as VendorOrderModel

        vendor_order_reference = order_data.get("vendor_order_reference", "")
        order_id = order_data.get("order_id", "")

        # Try vendor order reference first
        logger.info("venor_order_reference = %s", vendor_order_reference)
        if vendor_order_reference:
            vendor_order = VendorOrderModel.objects.filter(
                order__office=office, vendor=self.vendor, vendor_order_reference=vendor_order_reference
            ).first()
            if vendor_order:
                logger.info("Found vendor order id=%s by reference", vendor_order.id)
                return vendor_order

        # Try order_id
        logger.info("Order ID = %s", order_id)
        if order_id:
            vendor_order = VendorOrderModel.objects.filter(
                order__office=office, vendor=self.vendor, vendor_order_id=order_id
            ).first()
            if vendor_order:
                logger.info("Found vendor order id=%s by order ID", vendor_order.id)
                return vendor_order

        # Try to find by date and products
        open_vendor_orders = list(
            VendorOrderModel.objects.filter(
                order__office=office, vendor=self.vendor, order_date=order_data["order_date"]
            )
        )
        logger.info("Total vendor orders to look through - %s", len(open_vendor_orders))
        for vendor_order in open_vendor_orders:
            vendor_order_products = list(vendor_order.order_products.select_related("product"))
            origin_product_ids = {i.product.product_id for i in vendor_order_products}
            coming_product_ids = {o["product"]["product_id"] for o in order_products}
            product_match = (
                any(origin_product_ids) and any(coming_product_ids) and origin_product_ids == coming_product_ids
            )
            logger.info(
                "DB product ids = %s, data product ids = %s. Match? %s",
                origin_product_ids,
                coming_product_ids,
                product_match,
            )
            if product_match:
                return vendor_order
        logger.info("Vendor order was not found in db")

    def create_vendor_order(self, order_data, order_products, office):
        from apps.orders.models import Order as OrderModel
        from apps.orders.models import VendorOrder as VendorOrderModel

        logger.debug("Create new vendor order information")
        order = OrderModel.objects.create(
            office=office,
            status=order_data["status"],
            order_date=order_data["order_date"],
            total_items=order_data["total_items"],
            total_amount=order_data["total_amount"],
            order_type=OrderType.VENDOR_DIRECT,
        )
        vendor_order = VendorOrderModel.from_dataclass(vendor=self.vendor, order=order, dict_data=order_data)
        return vendor_order

    def update_vendor_order(self, vendor_order, order_data, order_products):
        logger.info("Updating vendor order")
        vendor_order.vendor_order_id = order_data["order_id"]
        vendor_order.status = order_data["status"]
        vendor_order.vendor_order_reference = order_data.get("vendor_order_reference", "")
        vendor_order.total_amount = Decimal(order_data.get("total_amount", 0.0))
        vendor_order.invoice_link = order_data.get("invoice_link", "")
        vendor_order.save()

        vendor_order_products = vendor_order.order_products.select_related("product")
        for order_product in order_products:
            vendor_order_product = vendor_order_products.filter(
                product__product_id=order_product["product"]["product_id"]
            ).first()
            if not vendor_order_product:
                continue
            vendor_order_product.status = self.normalize_order_product_status(order_product["status"])
            vendor_order_product.tracking_link = order_product.get("tracking_link")
            vendor_order_product.save()

    def adjust_office_budget(self, office, vendor_order):
        order_date = vendor_order.order_date

        office_budget = office.budgets.filter(month__gte=order_date).order_by("month").first()

        logger.debug(f"office_budget is {office_budget}")

        if not office_budget:
            logger.warning("Could not find office budget")
            return

        month = Month(year=order_date.year, month=order_date.month)
        # Making a copy
        office_budget = OfficeBudgetHelper.get_or_create_budget(office_id=office.pk, month=month)
        vendor_to_slug = OfficeBudgetHelper.get_slug_mapping(office_budget)
        Subaccount.objects.filter(budget=office_budget, slug=vendor_to_slug[vendor_order.vendor.slug]).update(
            spend=F("spend") + vendor_order.total_amount
        )

    @sync_to_async
    def save_order_to_db(self, office, order: Order):
        try:
            logger.debug("Saving order to db: %s", order)
            from apps.orders.models import VendorOrderProduct as VendorOrderProductModel

            order_data = order.to_dict()

            order_data.pop("shipping_address")
            order_products = order_data.pop("products")

            order_data["vendor_status"] = order_data["status"]
            order_data["status"] = Scraper.normalize_order_status(order_data["vendor_status"])
            order_date = order_data["order_date"]

            vendor_order = Scraper.find_vendor_order(self, office, order_data, order_products)
            if vendor_order:
                Scraper.update_vendor_order(self, vendor_order, order_data, order_products)
            else:
                logger.info("Creating vendor order")
                vendor_order = Scraper.create_vendor_order(self, order_data, order_products, office)
            for order_product in order_products:
                product_data = order_product.pop("product")
                product, _ = self.save_single_product_to_db(
                    product_data, office, is_inventory=True, order_date=order_date
                )
                order_product["vendor_status"] = order_product["status"]
                order_product["status"] = Scraper.normalize_order_product_status(order_product["vendor_status"])
                if vendor_order.vendor.slug in DEFAULT_FRONT_OFFICE_BUDGET_VENDORS:
                    order_product["budget_spend_type"] = BUDGET_SPEND_TYPE.FRONT_OFFICE_SUPPLY_SPEND_BUDGET.value
                else:
                    order_product["budget_spend_type"] = BUDGET_SPEND_TYPE.DENTAL_SUPPLY_SPEND_BUDGET.value

                logger.debug(
                    "Setting status to %s, spend_type to %s",
                    order_product["status"],
                    order_product["budget_spend_type"],
                )
                print("vendor_order =====", vendor_order)
                print("product ======", product)
                print("order_product ===, order_product", order_product)
                vop, created = VendorOrderProductModel.objects.update_or_create(
                    vendor_order=vendor_order,
                    product=product,
                    defaults=order_product,
                )
                logger.debug("Vendor order product %s, created=%s", vop, created)
                print("!!!!!!!!!!!!!!!!!!!!!!!!!vop!!!!!!!!!!!!!created", vop, created)
            print("Vendor order product done")
        except Exception as e:
            print(f"An error occurred ----: {e}")
            # Handle the error as per your requirement
            traceback.print_exc()
        return []

    async def get_missing_products_fields(self, order_products, fields=("description",)):
        logger.debug("Getting missing product fields: %s for products %s", fields, order_products)
        sem = asyncio.Semaphore(value=2)
        tasks = (
            self.get_missing_product_fields(
                sem,
                product_id=order_product["product"]["product_id"],
                product_url=order_product["product"]["url"],
                perform_login=False,
                fields=fields,
            )
            for order_product in order_products
            if order_product["product"]["url"]
        )
        products_missing_data = await asyncio.gather(*tasks, return_exceptions=True)
        for order_product, product_missing_data in zip(order_products, products_missing_data):
            if not isinstance(product_missing_data, dict):
                continue

            for field in fields:
                order_product["product"][field] = product_missing_data[field]

    async def get_vendor_categories(self, url=None, headers=None, perform_login=False) -> List[ProductCategory]:
        if perform_login:
            await self.login()

        url = self.CATEGORY_URL if hasattr(self, "CATEGORY_URL") else url
        if not url:
            raise ValueError

        headers = self.CATEGORY_HEADERS if hasattr(self, "CATEGORY_HEADERS") else headers

        ssl_context = self._ssl_context if hasattr(self, "_ssl_context") else None
        async with self.session.get(url, headers=headers, ssl=ssl_context) as resp:
            if resp.content_type == "application/json":
                response = await resp.json()
            else:
                response = Selector(text=await resp.text())
            return self._get_vendor_categories(response)

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        pass

    @catch_network
    async def search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price"
    ) -> ProductSearch:
        res_products = []
        page_size = 0

        if self.vendor.slug not in ["ultradent", "amazon"]:
            await self.login()

        while True:
            product_search = await self._search_products(
                query, page, min_price=min_price, max_price=max_price, sort_by=sort_by
            )
            if not page_size:
                page_size = product_search["page_size"]

            total_size = product_search["total_size"]
            products = product_search["products"]
            last_page = product_search["last_page"]
            if max_price:
                products = [product for product in products if product.price and product.price < max_price]
            if min_price:
                products = [product for product in products if product.price and product.price > min_price]

            res_products.extend(products)

            if len(res_products) > 10 or last_page:
                break
            page += 1

        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": res_products,
            "last_page": last_page,
        }

    @sync_to_async
    def get_page_queryset(self, query, page, page_size, office_id=None):
        from apps.orders.models import OfficeProduct

        products = OfficeProduct.objects.all()
        if office_id:
            products = products.filter(office_id=office_id)

        products = products.filter(product__vendor_id=self.vendor.id, product__name__icontains=query)
        total_size = products.count()
        if (page - 1) * page_size < total_size:
            page_products = products[(page - 1) * page_size : page * page_size]
            page_products = [product.to_dataclass() for product in page_products]
        else:
            page_products = []

        return total_size, page_products

    async def _search_products_from_table(
        self,
        query: str,
        page: int = 1,
        min_price: int = 0,
        max_price: int = 0,
        sort_by="price",
        office_id=None,
    ) -> ProductSearch:
        page_size = 15
        total_size, page_products = await self.get_page_queryset(query, page, page_size, office_id)
        last_page = page_size * page >= total_size
        return {
            "vendor_slug": self.vendor.slug,
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": page_products,
            "last_page": last_page,
        }

    @catch_network
    async def search_products_v2(self, keyword, office=None):
        if self.vendor.slug == "ultradent":
            return

        await self.login()

        page = 1
        products_objs = []
        fetch_all = False
        while True:
            product_search = await self._search_products(keyword.keyword, page)
            last_page = product_search["last_page"]
            products = product_search["products"]

            for product in products:
                product_obj, _ = await sync_to_async(self.save_single_product_to_db)(
                    product.to_dict(), office=office, keyword=keyword
                )
                products_objs.append(product_obj)

            if not fetch_all or (fetch_all and last_page):
                break

            page += 1

        return products_objs

    async def track_product(self, order_id, product_id, tracking_link, tracking_number, perform_login=False):
        raise NotImplementedError("Vendor scraper must implement `track_product`")

    async def add_product_to_cart(self, product: CartProduct, perform_login=False) -> VendorCartProduct:
        raise NotImplementedError("Vendor scraper must implement `add_product_to_cart`")

    async def add_products_to_cart(self, products: List[CartProduct]) -> List[VendorCartProduct]:
        raise NotImplementedError("Vendor scraper must implement `add_products_to_cart`")

    async def remove_product_from_cart(
        self, product_id: SmartProductID, perform_login: bool = False, use_bulk: bool = True
    ):
        raise NotImplementedError("Vendor scraper must implement `remove_product_from_cart`")

    async def remove_products_from_cart(self, product_ids: List[SmartProductID]):
        tasks = (self.remove_product_from_cart(product_id, use_bulk=False) for product_id in product_ids)
        await asyncio.gather(*tasks)

    async def clear_cart(self):
        raise NotImplementedError("Vendor scraper must implement `clear_cart`")

    # async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False):
    #     raise NotImplementedError("Vendor scraper must implement `confirm_order`")

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
        vendor_order_detail = VendorOrderDetail.from_dict(
            {
                "retail_amount": 0,
                "savings_amount": 0,
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": 0,
                "total_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
                "reduction_amount": Decimal(subtotal_manual),
            }
        )
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
            },
        }

    async def redundancy_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
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
            "order_id": f"{uuid.uuid4()}",
            "order_type": msgs.ORDER_TYPE_PROCESSING,
        }

    def add_shipping_method_to_db(
        self,
        shipping_name: str = "",
        shipping_value: str = "",
        price: float = 0.00,
        vendor_id: int = "",
        office_id: int = 0,
        default_shipping_method_str: str = "",
    ):
        if shipping_name:
            if vendor_id:
                try:
                    # checking of the default shipping method exist in db
                    default_shipping_method = ShippingMethod.objects.filter(name=default_shipping_method_str)
                    # check for shipping method if exists
                    shipping_method_exist = ShippingMethod.objects.filter(name=shipping_name)
                    # if shipping method is not exists then create it
                    if not shipping_method_exist.exists():
                        shipping_method_updated = ShippingMethod.objects.create(
                            name=shipping_name, value=shipping_value, price=price
                        )
                    else:
                        # if shipping method exists update it
                        shipping_method_updated = shipping_method_exist.first()
                        shipping_method_updated.name = shipping_name
                        shipping_method_updated.value = shipping_value
                        shipping_method_updated.price = price
                        shipping_method_updated.save()

                    # if an entry is their in officevendor then update the shipping method foreign key
                    office_vendor_selected = OfficeVendor.objects.filter(office_id=office_id, vendor_id=vendor_id)
                    if office_vendor_selected:
                        office_vendor_selected_first = office_vendor_selected.first()
                        if default_shipping_method:
                            office_vendor_selected_first.default_shipping_option = default_shipping_method.first()
                        office_vendor_selected_first.shipping_options.add(shipping_method_updated)
                        office_vendor_selected_first.save()
                except Exception as e:
                    logger.debug("Problem in add_shipping_method_to_db" + str(e))
            else:
                logger.debug("add_shipping_method_to_db: please provide vendor_id.")
        else:
            logger.debug(
                "add_shipping_method_to_db: Couldn't add shipping method to DB, Please provide shipping method"
                " from scraper"
            )
