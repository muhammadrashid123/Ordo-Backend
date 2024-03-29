import asyncio
import datetime
import logging
import re
import uuid
from decimal import Decimal
from typing import List, Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.headers.blue_sky_bio import (
    ADD_CART_HEADER,
    CLEAR_CART_HEADER,
    GENERAL_HEADER,
    GET_CART_HEADER,
    LOGIN_HEADER,
    PLACE_ORDER_HEADER,
    REVIEW_ORDER_HEADER,
)
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.scrapers.utils import catch_network
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


class BlueSkyBioScraper(Scraper):
    BASE_URL = "https://blueskybio.com"

    async def _get_login_data(self, *args, **kwargs):
        await self.session.get(f"{self.BASE_URL}/store/", headers=GENERAL_HEADER)

        data = [
            ("user", self.username),
            ("pass", self.password),
            ("current_uri", "/store/index.php"),
        ]
        return {
            "url": f"{self.BASE_URL}/store/ajax_calls/customer_login.php",
            "headers": LOGIN_HEADER,
            "data": data,
        }

    async def _check_authenticated(self, resp: ClientResponse):
        text = await resp.text()
        return self.username in text

    def parse_product_line(self, product_line):
        products = []
        sku = try_extract_text(product_line.xpath("./td[2]"))
        product_name = try_extract_text(product_line.xpath("./td[1]"))
        product_price = try_extract_text(product_line.xpath("./td[3]"))
        quantity = try_extract_text(product_line.xpath("./td[4]"))
        products.append(
            {
                "product": {
                    "product_id": sku,
                    "sky": sku,
                    "name": product_name,
                    "description": "",
                    "url": "",
                    "images": [],
                    "category": "",
                    "price": product_price,
                    "status": "",
                    "vendor": self.vendor.to_dict(),
                },
                "quantity": quantity,
                "unit_price": product_price,
                "status": "",
            }
        )

        return products

    async def get_order(
        self,
        order_dom,
        office=None,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> dict:
        order_item = {"products": [], "currency": "USD"}

        order_description = try_extract_text(order_dom)
        if not order_description or "#" not in order_description:
            return

        order_item["order_id"] = order_description.split("#")[1].strip()
        if completed_order_ids and str(order_item["order_id"]) in completed_order_ids:
            return

        order_datetime = order_description.split("-")[0].strip()
        order_item["order_date"] = datetime.datetime.strptime(order_datetime, "%b, %d %Y %H:%M:%S").date()
        if from_date and to_date and (order_item["order_date"] < from_date or order_item["order_date"] > to_date):
            return

        order_content = order_dom.xpath('./following-sibling::div[@class="show_receipt"][1]')
        whole_content = try_extract_text(order_content)
        keyword_map = {
            "Subtotal:": "sub_total",
            "Tax:": "tax",
            "Shipping:": "shipping_address",
            "Total:": "total_amount",
        }
        for keyword in keyword_map:
            if keyword not in whole_content:
                continue
            key = keyword_map[keyword]
            data_content = whole_content.split(keyword)[1].split(":")[0]
            data = re.search(r"\$[\d\.\,]+", data_content).group()
            order_item[key] = data

        product_rows = order_content.xpath(".//tr[@class='ga-cart-item']")

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
        tasks = []

        async with self.session.get(f"{self.BASE_URL}/store/view-receipts", headers=GENERAL_HEADER) as resp:
            order_history_resp_dom = Selector(text=await resp.text())

        order_records = order_history_resp_dom.xpath("//div[@class='view_receipts']")
        for order_record in order_records:
            tasks.append(
                self.get_order(
                    order_record,
                    office,
                    from_date=from_date,
                    to_date=to_date,
                    completed_order_ids=completed_order_ids,
                )
            )

        if not tasks:
            return []
        orders = await asyncio.gather(*tasks)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    async def get_cart(self):
        async with self.session.get(f"{self.BASE_URL}/store/cart", headers=GET_CART_HEADER) as resp:
            dom = Selector(text=await resp.text())
            return dom

    async def clear_cart(self):
        cart_dom = await self.get_cart()

        for product in cart_dom.xpath('//tr[@class="ga-cart-item"]'):
            product_id = product.xpath('.//input[@class="item-quantity"]/@name').get()

            data = {
                "id": product_id,
            }

            async with self.session.post(
                f"{self.BASE_URL}/store/ajax_calls/remove_from_cart.php",
                headers=CLEAR_CART_HEADER,
                data=data,
            ) as resp:
                logger.info(f"Remove Product - {product_id}: {resp.status}")

    async def add_products_to_cart(self, products: List[CartProduct]):
        data = {
            "data": "&".join([f'{product["product_id"]}={product["quantity"]}' for product in products]),
        }

        async with self.session.post(
            f"{self.BASE_URL}/store/ajax_calls/add_to_cart.php", headers=ADD_CART_HEADER, data=data
        ) as resp:
            logger.info(f"Add To Cart POST: {resp.status}")

    async def checkout_review_order(self) -> VendorOrderDetail:
        cart_dom = await self.get_cart()
        shipping_cost = cart_dom.xpath('//select[@name="shipping_cost"]/option[1]/@value').get()
        if not shipping_cost:
            shipping_cost = 13
        comments = datetime.datetime.today().strftime("%Y/%m/%d") + " - Ordo"

        data = {
            "shipping_cost": shipping_cost,
            "additional_instructions": comments,
        }

        async with self.session.post(
            f"{self.BASE_URL}/store/finalize-order", headers=REVIEW_ORDER_HEADER, data=data
        ) as resp:
            dom = Selector(text=await resp.text())

            VENDOR_ORDER_PARAMS = [
                ("shipping_address_num", '//select[@id="shipping-address"]/option[@selected]/@value'),
                ("shipping_address_REQ", '//input[@name="shipping_address_REQ"]/@value'),
                ("shipping_address2", '//input[@name="shipping_address2"]/@value'),
                ("shipping_city_REQ", '//input[@name="shipping_city_REQ"]/@value'),
                ("shipping_state_REQ", '//input[@name="shipping_state_REQ"]/@value'),
                ("shipping_zip_REQ", '//input[@name="shipping_zip_REQ"]/@value'),
                ("shipping_country_REQ", '//input[@name="shipping_country_REQ"]/@value'),
                ("tax", '//input[@name="tax"]/@value'),
                ("shipping_cost", '//input[@name="shipping_cost"]/@value'),
                ("total", '//input[@name="total"]/@value'),
                ("additional_instructions", '//input[@name="additional_instructions"]/@value'),
            ]
            data = {name: dom.xpath(xpath).get() for name, xpath in VENDOR_ORDER_PARAMS}

            shipping_address_ele = dom.xpath('//select[@id="shipping-address"]/option[@selected]')
            shipping_address = try_extract_text(shipping_address_ele)
            data["shipping_address"] = shipping_address

            if not data["shipping_country_REQ"]:
                data["shipping_country_REQ"] = "United States"

            logger.info(f"Vendor Order Detail {data}")
            return data

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        logger.info("Blueskybio/confirm_order")
        await self.clear_cart()
        await self.add_products_to_cart(products)
        checkout_detail = await self.checkout_review_order()
        if fake:
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": checkout_detail["total"],
                "shipping_amount": checkout_detail["shipping_cost"],
                "tax_amount": checkout_detail["tax"],
                "total_amount": checkout_detail["total"],
                "payment_method": "",
                "shipping_address": checkout_detail["shipping_address"],
                "order_id": f"{uuid.uuid4()}",
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }

        async with self.session.post(
            f"{self.BASE_URL}/store/receipt", data=checkout_detail, headers=PLACE_ORDER_HEADER
        ) as resp:
            response_dom = Selector(text=await resp.text())
            order_link = response_dom.xpath('//a[@id="print-receipt"]/@href').get()
            matches = re.search(r"receipt\=(\d+)", order_link)
            order_id = matches.group(1)
            logger.info(f"Blueskybio Order id {order_id}")

            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": checkout_detail["total"],
                "shipping_amount": checkout_detail["shipping_cost"],
                "tax_amount": checkout_detail["tax"],
                "total_amount": checkout_detail["total"],
                "payment_method": "",
                "shipping_address": checkout_detail["shipping_address"],
                "order_id": order_id,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }
