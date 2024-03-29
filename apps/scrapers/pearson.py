import asyncio
import datetime
import re
from decimal import Decimal
from typing import Dict, List, Optional

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.headers.pearson import (
    HOME_HEADERS,
    LOGIN_HEADERS,
    ORDER_HISTORY_HEADERS,
)
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.types.orders import CartProduct
from apps.types.scraper import InvoiceFormat, InvoiceType
from apps.vendor_clients import types


def clean_text(xpath, dom):
    try:
        text = re.sub(r"\s+", " ", " ".join(dom.xpath(xpath).extract())).strip()
        return text
    except Exception:
        return None


class PearsonScraper(Scraper):
    INVOICE_TYPE = InvoiceType.HTML_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT

    async def _get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        async with self.session.get(url="https://www.pearsondental.com/login.asp", headers=HOME_HEADERS):
            data = {
                "csmno": self.username,
                "password": self.password,
                "sp": "",
                "kwik": "",
                "epay": "",
                "site": "",
                "page": "",
                "http_referer": "https://www.pearsondental.com//catalog/topcat_list.asp",
                "action": "LOGIN",
            }

            return {
                "url": "https://www.pearsondental.com/login.asp",
                "headers": LOGIN_HEADERS,
                "data": data,
            }

    async def check_authenticated(self, resp: ClientResponse) -> bool:
        text = await resp.text()
        dom = Selector(text=text)
        return True if dom.xpath("//a[@href='/catalog/logout.asp']") else False

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

        url = "https://www.pearsondental.com/order/c-olist.asp"
        async with self.session.get(url, headers=ORDER_HISTORY_HEADERS) as resp:
            response_html = await resp.text()
            response_dom = Selector(text=response_html)
            orders_dom = response_dom.xpath("//table//tr[@bgcolor='#ffffff']")
            tasks = []
            for order_dom in orders_dom:
                order_date = clean_text("./td[3]//text()", order_dom)
                order_date = datetime.datetime.strptime(order_date, "%m/%d/%Y").date()
                order_id = clean_text("./td[1]/a//text()", order_dom)

                if from_date and to_date and (order_date < from_date or order_date > to_date):
                    continue
                if completed_order_ids and str(order_id) in completed_order_ids:
                    continue

                tasks.append(self.get_order(sem, order_dom, office))
            orders = await asyncio.gather(*tasks, return_exceptions=True)

        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    async def get_order(self, sem, order_dom, office=None, **kwargs):
        order_id = clean_text("./td[1]/a//text()", order_dom)
        order_link = order_dom.xpath("./td[1]/a/@href").get()
        if order_link:
            order_link = "https://www.pearsondental.com/order/" + order_link
        order_date = clean_text("./td[3]//text()", order_dom)
        order_date = datetime.datetime.strptime(order_date, "%m/%d/%Y").date()

        order = {
            "order_id": order_id,
            "total_amount": "0.0",
            "currency": "USD",
            "order_date": order_date,
            "invoice_link": order_link,
            "status": "",
            "products": [],
        }
        async with self.session.get(order_link, headers=ORDER_HISTORY_HEADERS) as resp:
            order_detail_response = Selector(text=await resp.text())

            product_rows = order_detail_response.xpath('//table[@class="link2"]//tr')
            order_total = clean_text("./td[last()]//text()", product_rows[-1])
            order["total_amount"] = order_total

            for index, order_product in enumerate(product_rows):
                if index == 0:
                    continue
                if index == len(product_rows) - 1:
                    continue

                product_id = clean_text("./td[2]//text()", order_product)
                product_qty = clean_text("./td[4]//text()", order_product)
                unit_price = clean_text("./td[5]//text()", order_product)
                sub_total = clean_text("./td[6]//text()", order_product)
                product_title = clean_text("./td[3]//text()", order_product)
                order["products"].append(
                    {
                        "product": {
                            "product_id": product_id,
                            "name": product_title,
                            "description": "",
                            "url": "",
                            "images": [],
                            "category": "",
                            "price": unit_price,
                            "vendor": self.vendor.to_dict(),
                        },
                        "quantity": product_qty,
                        "unit_price": unit_price,
                        "sub_total": sub_total,
                        "status": "",
                    }
                )

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
