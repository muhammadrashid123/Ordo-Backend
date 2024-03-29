import asyncio
import datetime
import itertools
import logging
import re
from decimal import Decimal
from itertools import zip_longest
from typing import Dict, List, Optional
from urllib.parse import urlencode

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.headers.top_glove import (
    HTTP_HEADER,
    LOGIN_HEADER,
    ORDER_DETAIL_HEADER,
    ORDER_HISTORY_HEADER,
)
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.scrapers.utils import (
    catch_network,
    convert_string_to_price,
    semaphore_coroutine,
)
from apps.types.orders import CartProduct

logger = logging.getLogger(__name__)


def try_extract_text(dom):
    try:
        text = re.sub(r"\s+", " ", " ".join(dom.xpath(".//text()").extract())).strip()
        return text
    except Exception:
        return None


def same(x):
    return x


def parse_int_or_float(v):
    try:
        return int(v)
    except ValueError:
        return Decimal(v)


class TopGloveScraper(Scraper):
    BASE_URL = "https://www.topqualitygloves.com"

    async def _get_login_data(self, *args, **kwargs):
        data = {
            'form_type':'customer_login',
            'utf8':'✓',
            'return_to':'/',
            'customer[email]':self.username,
            'customer[password]':self.password
        }
        return {
            "url": f"{self.BASE_URL}/account/login",
            "headers": LOGIN_HEADER,
            "data": data,
        }

    async def _check_authenticated(self, resp: ClientResponse):
        text = await resp.text()
        dom = Selector(text=text)
        return "Sign Out" in dom.xpath("//a[@href='/account/logout']//text()").get()

    def parse_product_line(self, product_line):
        PRODUCT_LINE_EXTRACTION_PARAMS = [
            ("descriptions", './td[@class="accountProductDescDisplay"]//text()', same),
            ("skus", './td[@class="accountProductCodeDisplay"]//text()', same),
            ("qtys", './td[@class="accountQuantityDisplay"]//text()', parse_int_or_float),
            ("unit_prices", './td[@class="cartUnitDisplay"]//text()', convert_string_to_price),
            ("prices", './td[@class="cartTotalDisplay"]//text()', convert_string_to_price),
        ]

        data = {
            name: list(map(converter, [i for i in product_line.xpath(xpath).extract() if i.strip()]))
            for name, xpath, converter in PRODUCT_LINE_EXTRACTION_PARAMS
        }
        data["product_name"] = try_extract_text(product_line.xpath('./td[@class="accountProductDisplay"]'))

        if not data["skus"]:
            return []

        products = []
        important_keys = ("skus", "qtys", "unit_prices", "prices")
        if len({len(data[key]) for key in important_keys}) > 1:
            # logger.warning("Could not parse the following product line: %s", get_html_content(product_line))
            return []
        for sku, qty, unit_price, price, description in zip_longest(
            *(data[k] for k in (*important_keys, "description"))
        ):
            products.append(
                {
                    "product": {
                        "product_id": sku,
                        "sky": sku,
                        "name": data["product_name"],
                        "description": description,
                        "url": "",
                        "images": [],
                        "category": "",
                        "price": price,
                        "status": "",
                        "vendor": self.vendor.to_dict(),
                    },
                    "quantity": qty,
                    "unit_price": unit_price,
                    "status": "",
                }
            )

        return products

    @semaphore_coroutine
    async def get_order(
        self,
        sem,
        order_dom,
        office=None,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> dict:
        order_item = {"products": [], "currency": "USD"}

        order_id = try_extract_text(order_dom.xpath("./legend"))
        order_item["order_id"] = order_id.split(":")[1].strip()

        order_status = try_extract_text(order_dom.xpath('./div[contains(@class, "notice")]'))
        order_item["status"] = order_status.split(":")[1].strip()

        order_detail_link = order_dom.xpath('.//a[contains(@href, "account_history_info")]/@href').get()
        order_item["order_detail_link"] = order_detail_link

        async with self.session.get(order_detail_link, headers=ORDER_DETAIL_HEADER) as resp:
            resp_dom = Selector(text=await resp.text())

        order_date = try_extract_text(
            resp_dom.xpath('//div[@id="accountHistInfo"]/div[@class="forward"][contains(text(), "Order Date")]')
        )
        if order_date and ":" in order_date:
            order_item["order_date"] = datetime.datetime.strptime(
                order_date.split(":")[1].strip(), "%A %d %B, %Y"
            ).date()

        if completed_order_ids and str(order_item["order_id"]) in completed_order_ids:
            return
        if from_date and to_date and (order_item["order_date"] < from_date or order_item["order_date"] > to_date):
            return

        total = try_extract_text(resp_dom.xpath('//div[@id="orderTotals"]/div[contains(@class, "amount")][last()]'))
        order_item["total_amount"] = total

        product_rows = resp_dom.xpath('//table[@id="orderHistoryHeading"]//tr')

        for product_line in product_rows:
            order_item["products"].extend(self.parse_product_line(product_line))

        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order_item))
        return order_item

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
        if perform_login:
            await self.login()

        tasks = []
        page = 1
        for page in itertools.count(1):
            params = (
                ("main_page", "account_history"),
                ("page", page),
            )
            async with self.session.get(
                f"{self.BASE_URL}/index.php?" + urlencode(params), headers=ORDER_HISTORY_HEADER
            ) as resp:
                order_history_resp_dom = Selector(text=await resp.text())
            order_history_doms = order_history_resp_dom.xpath('//div[@id="accountHistoryDefault"]/fieldset')
            for order_dom in order_history_doms:
                order_detail_link = order_dom.xpath('.//a[contains(@href, "account_history_info")]/@href').get()
                if not order_detail_link:
                    continue

                tasks.append(
                    self.get_order(
                        sem,
                        order_dom,
                        office,
                        from_date=from_date,
                        to_date=to_date,
                        completed_order_ids=completed_order_ids,
                    )
                )

            if len(order_history_doms) < 10:
                break

        if not tasks:
            return []
        orders = await asyncio.gather(*tasks)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
        vendor_order_detail = VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
            total_amount=Decimal(subtotal_manual),
            payment_method="",
            shipping_address="",
            reduction_amount=Decimal(subtotal_manual),
        )
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
            },
        }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
        vendor_order_detail = VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
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
