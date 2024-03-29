import asyncio
import datetime
import json
import logging
import time
import uuid
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Dict, List, Optional
from urllib.parse import urlencode

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.errors import VendorAuthenticationFailed
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.scrapers.utils import catch_network
from apps.types.orders import CartProduct
from apps.types.scraper import InvoiceFile, InvoiceFormat, InvoiceType

logger = logging.getLogger(__name__)

headers = {
    "authority": "www.crazydentalprices.com",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json; charset=UTF-8",
    "origin": "https://www.crazydentalprices.com",
    "referer": "https://www.crazydentalprices.com",
    "sec-ch-ua": '"Google Chrome";v="105", "Not)A;Brand";v="8", "Chromium";v="105"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit"
    "/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
    "x-sc-touchpoint": "checkout",
}


class CrazyDentalScraper(Scraper):
    aiohttp_mode = False
    INVOICE_TYPE = InvoiceType.PDF_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT
    BASE_URL = "https://www.crazydentalprices.com"

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> SimpleCookie:
        if username:
            self.username = username
        if password:
            self.password = password

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, self.login_proc)
        logger.info(f"login {res}")
        return res

    def login_proc(self):
        json_data = {
            "email": self.username,
            "password": self.password,
            "redirect": "true",
        }
        resp = self.session.post(
            "https://www.crazydentalprices.com/dc-dental/services/Account.Login.Service.ss?n=3&c=1075085",
            headers=headers,
            json=json_data,
        )
        res = json.loads(resp.text)
        if "errorStatusCode" in res:
            raise VendorAuthenticationFailed()
        return res

    def extract_tracking_link(self, resp_data, line_id):
        product_status = tracking_link = tracking_number = ""
        for fulfilment in resp_data["fulfillments"]:
            for fulfillment_line in fulfilment["lines"]:
                if fulfillment_line["internalid"] != line_id:
                    continue

                product_status = fulfilment["status"]["name"]
                tracking_numbers = fulfilment.get("trackingnumbers", [])
                if not tracking_numbers:
                    continue

                tracking_number = tracking_numbers[0]
                if tracking_number:
                    tracking_link = f"https://www.ups.com/track?loc=en_US&tracknum={tracking_number}"

        return product_status, tracking_number, tracking_link

    async def get_order(self, sem, order_id, order_type, office=None, **kwargs):
        params = {"c": 1075085, "n": 3, "internalid": order_id, "recordtype": order_type}
        order_detail_resp = self.session.get(
            f"{self.BASE_URL}/dc-dental/services/OrderHistory.Service.ss?{urlencode(params)}",
            headers=headers,
        )
        logger.info(f"Order Detail - {order_id}: {order_detail_resp.status_code}")

        resp_data = order_detail_resp.json()
        order_history = {
            "currency": "USD",
            "order_id": resp_data["tranid"],
            "order_date": datetime.datetime.strptime(resp_data["trandate"], "%m/%d/%Y").date(),
            "status": resp_data["status"]["name"],
            "order_detail_link": f"{self.BASE_URL}/dc-dental/my_account.ssp#purchases/view/{order_type}/{order_id}",
            "total_amount": resp_data["summary"]["total"],
        }
        billing_address = resp_data["billaddress"]
        shipping_address = resp_data["shipaddress"]
        for address_item in resp_data["addresses"]:
            bill_flag = address_item["internalid"] == billing_address
            ship_flag = address_item["internalid"] == shipping_address
            if bill_flag or ship_flag:
                address_items = [address_item[k] for k in ["addr1", "city", "zip", "state", "country"]]
                address_items = [_it.strip() for _it in address_items if _it.strip()]
                address = ", ".join(address_items)

                if ship_flag:
                    shipping_address = address

        order_history["shipping_address"] = {"address": shipping_address}

        order_history["products"] = []
        for product_line in resp_data["lines"]:
            product_id = product_line["item"]["itemid"]
            product_name = product_line["item"]["storedisplayname2"]
            quantity = product_line["quantity"]
            price = product_line["item"]["onlinecustomerprice_detail"]["onlinecustomerprice"]
            url = f'{self.BASE_URL}/{product_line["item"]["urlcomponent"]}'

            line_id = product_line["internalid"]
            product_status, tracking_number, tracking_link = self.extract_tracking_link(resp_data, line_id)

            order_history["products"].append(
                {
                    "product": {
                        "product_id": product_id,
                        "name": product_name,
                        "description": "",
                        "url": url,
                        "images": [],
                        "category": "",
                        "price": price,
                        "vendor": self.vendor.to_dict(),
                    },
                    "unit_price": price,
                    "quantity": quantity,
                    "tracking_number": tracking_number,
                    "tracking_link": tracking_link,
                    "status": product_status,
                }
            )
        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order_history))
        return order_history

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

        page = 1
        tasks = []
        while True:
            params = {
                "c": 1075085,
                "n": 3,
                "sort": "trandate,internalid",
                "order": 1,
                "page": page,
            }
            if from_date and to_date:
                # params["from"] = from_date.isoformat()
                # TODO: the next is due to investigation of KeyError issue
                params["from"] = "1800-01-02"
                params["to"] = to_date.isoformat()
            url = f"{self.BASE_URL}/dc-dental/services/OrderHistory.Service.ss"
            order_history_resp = self.session.get(url, headers=headers, params=params)
            logger.info(f"Order History: {order_history_resp.status_code}")

            records = order_history_resp.json()["records"]
            for record in records:
                order_id = record["internalid"]
                order_type = record["recordtype"]
                tasks.append(self.get_order(sem, order_id, order_type, office))
            if len(records) < 20:
                break
            else:
                page += 1

        orders = await asyncio.gather(*tasks, return_exceptions=True)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    def get_cart_products(self):
        resp = self.session.get(
            "https://www.crazydentalprices.com/dc-dental/services/LiveOrder.Service.ss?c=1075085&internalid=cart",
            headers=headers,
        )
        print(f"[INFO] Cart Page : {resp.status_code}")
        return resp.json()["lines"]

    def clear_cart(self):
        cart_products = self.get_cart_products()
        print(f"[INFO] Found {len(cart_products)} Products in Cart")
        for cart_product in cart_products:
            internalid = cart_product["internalid"]
            resp = self.session.delete(
                f"https://www.crazydentalprices.com/dc-dental/services"
                f"/LiveOrder.Line.Service.ss?c=1075085&internalid={internalid}&n=3",
                headers=headers,
            )
            print(f"[INFO] Removed Product {internalid} : {resp.status_code}")

        print("[INFO] Emptied Cart..")

    def add_to_cart(self, products):
        data = list()
        for product in products:
            item = {
                "item": {
                    "internalid": int(product["product_id"]),
                },
                "quantity": product["quantity"],
                "options": [],
                "location": "",
                "fulfillmentChoice": "ship",
            }
            data.append(item)

        resp = self.session.post(
            "https://www.crazydentalprices.com/dc-dental/services/LiveOrder.Line.Service.ss",
            headers=headers,
            json=data,
        )
        print(f"[INFO] Add to Cart : {resp.status_code}")

    def checkout(self):
        resp = self.session.get(
            f"https://www.crazydentalprices.com/dc-dental/checkout.environment.ssp"
            f"?lang=en_US&cur=USD&X-SC-Touchpoint=checkout&cart-bootstrap=T&t={int(time.time() * 1000)}",
            headers=headers,
        )
        print(f"[INFO] Checkout Data : {resp.status_code}")
        resp_text = resp.text

        cart_data = resp_text.split("SC.ENVIRONMENT.CART ")[1].split("\n")[0].strip(" =;")
        cart_json = json.loads(cart_data)

        ship_methods = cart_json["shipmethods"]
        cheapest_method_value = None
        cheapest_method_id = None
        for ship_method in ship_methods:
            if not cheapest_method_value:
                cheapest_method_value = ship_method["rate"]
                cheapest_method_id = ship_method["internalid"]
            else:
                if cheapest_method_value > ship_method["rate"]:
                    cheapest_method_value = ship_method["rate"]
                    cheapest_method_id = ship_method["internalid"]

        cart_json["shipmethod"] = cheapest_method_id
        resp = self.session.put(
            f"https://www.crazydentalprices.com/dc-dental/services"
            f"/LiveOrder.Service.ss?internalid=cart&t={int(time.time() * 1000)}&c=1075085&n=3",
            headers=headers,
            json=cart_json,
        )
        print(f"[INFO] Choosen Shipmethod - {cheapest_method_id} : {resp.status_code}")

        resp_json = resp.json()
        billing_addr = ""
        shipping_addr = ""
        addresses = resp_json["addresses"]
        for address in addresses:
            if address["defaultbilling"] == "T":
                billing_addr = [
                    address["fullname"],
                    address["addr1"],
                    address["city"],
                    address["state"],
                    address["zip"],
                    address["country"],
                ]
                billing_addr = ", ".join(billing_addr)
                print("::::: Billing Address :::::")
                print(billing_addr)

            elif address["defaultshipping"] == "T":
                shipping_addr = [
                    address["fullname"],
                    address["addr1"],
                    address["city"],
                    address["state"],
                    address["zip"],
                    address["country"],
                ]
                shipping_addr = ", ".join(shipping_addr)
                print("::::: Shipping Address :::::")
                print(shipping_addr)

        subtotal = resp_json["summary"]["subtotal"]
        print("::::: Subtotal :::::")
        print(subtotal)

        flat_rate_shipping = resp_json["summary"]["handlingcost"]
        print("::::: Flat Rate Shipping :::::")
        print(flat_rate_shipping)

        return resp_json, shipping_addr, subtotal

    def review_order(self, checkout_data):
        resp = self.session.put(
            f"https://www.crazydentalprices.com/dc-dental/services"
            f"/LiveOrder.Service.ss?internalid=cart&t={int(time.time() * 1000)}&c=1075085&n=3",
            headers=headers,
            json=checkout_data,
        )
        print(f"[INFO] Review Order: {resp.status_code}")

        return resp.json()

    def place_order(self, order_data):
        order_data["agreetermcondition"] = True
        resp = self.session.post(
            f"https://www.crazydentalprices.com/dc-dental/services"
            f"/LiveOrder.Service.ss?t={int(time.time() * 1000)}&c=1075085&n=3",
            headers=headers,
            json=order_data,
        )
        print(f"[INFO] Place Order: {resp.status_code}")

        resp_json = resp.json()

        estimated_tax = resp_json["confirmation"]["summary"]["taxtotal"]
        print("::::: Estimated Tax :::::")
        print(estimated_tax)

        total = resp_json["confirmation"]["summary"]["total"]
        print("::::: Total :::::")
        print(total)

        order_num = resp_json["confirmation"]["tranid"]
        return order_num, estimated_tax, total

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("Crazy Dental/create_order")
        loop = asyncio.get_event_loop()
        try:
            await asyncio.sleep(0.3)
            raise Exception()
            await self.login()
            await loop.run_in_executor(None, self.clear_cart)
            await loop.run_in_executor(None, self.add_to_cart, products)
            checkout_data, ship_addr, subtotal = await loop.run_in_executor(None, self.checkout)
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": 0,
                "subtotal_amount": subtotal,
                "shipping_amount": "",
                "tax_amount": "",
                "total_amount": "",
                "payment_method": "",
                "shipping_address": ship_addr,
                "reduction_amount": subtotal,
            }
        except Exception:
            print("crazy_dental create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": "",
                "total_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
                "reduction_amount": Decimal(subtotal_manual),
            }
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            },
        }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("Crazy Dental/confirm_order")
        try:
            await asyncio.sleep(1)
            raise Exception()
            await self.login()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.clear_cart)
            await loop.run_in_executor(None, self.add_to_cart, products)
            checkout_data, ship_addr, subtotal = await loop.run_in_executor(None, self.checkout)
            if fake:
                vendor_order_detail = {
                    "retail_amount": "",
                    "savings_amount": 0,
                    "subtotal_amount": subtotal,
                    "shipping_amount": "",
                    "tax_amount": "",
                    "total_amount": "",
                    "payment_method": "",
                    "shipping_address": ship_addr,
                    "order_id": f"{uuid.uuid4()}",
                    "order_type": msgs.ORDER_TYPE_ORDO,
                }
                return {
                    **vendor_order_detail,
                    **self.vendor.to_dict(),
                }
            order_data = await loop.run_in_executor(None, self.review_order, checkout_data)
            order_num, tax, total = await loop.run_in_executor(None, self.place_order, order_data)
            print("Order Number:", order_num)
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": 0,
                "subtotal_amount": subtotal,
                "shipping_amount": "",
                "tax_amount": tax,
                "total_amount": total,
                "payment_method": "",
                "shipping_address": ship_addr,
                "order_id": order_num,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }
        except Exception:
            print("Crazy_dental/confirm order except")
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
        content = await loop.run_in_executor(None, self._download_invoice_proc, kwargs.get("invoice_link"))
        return content

    def _download_invoice_proc(self, invoice_link) -> InvoiceFile:
        with self.session.get(invoice_link) as resp:
            return resp.content
