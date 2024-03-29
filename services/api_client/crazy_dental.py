import asyncio
import datetime
import logging
import traceback
from typing import List
from urllib.parse import urlencode

import oauthlib.oauth1
import requests
from aiohttp import ClientError
from aiohttp.client import ClientSession
from asgiref.sync import sync_to_async
from rest_framework import status

from apps.accounts.views.crazy_dental_integration import (
    access_token,
    consumer_key,
    consumer_secret,
    crazy_dental_Base_url,
    get_vendor_customer_id,
    oauth,
    realm,
    token_secret,
)
from apps.scrapers.base import Scraper
from apps.scrapers.schema import Order
from apps.types.scraper import InvoiceFormat, InvoiceType
from services.api_client.vendor_api_types import CrazyDentalProduct

# from apps.orders.models import Order


logger = logging.getLogger(__name__)


class CrazyDentalOauth:
    def __init__(self):
        # Change for crazy dental
        self.NETSUITE_ACCOUNT_ID = realm
        self.BASE_URL = crazy_dental_Base_url
        self.SAFE_CHARS = "~()*!.'"
        self.client = oauthlib.oauth1.Client(
            client_key=consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=access_token,
            resource_owner_secret=token_secret,
            signature_method="HMAC-SHA256",
        )

    def sign(self, params, http_method, headers):
        uri = f"{self.BASE_URL}?{urlencode(params)}"
        url, headers, body = self.client.sign(
            uri=uri, http_method=http_method, realm=self.NETSUITE_ACCOUNT_ID, headers=headers
        )
        return url, headers, body


class CrazyDentalAPIClient:
    def __init__(self, session: ClientSession, vendor):
        self.session = session
        self.page_size = 1000
        self.oauthclient = CrazyDentalOauth()
        self.headers = {"Content-Type": "application/json"}
        self.aiohttp_mode = False
        self.INVOICE_TYPE = InvoiceType.PDF_INVOICE
        self.INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT
        self.BASE_URL = "https://www.crazydentalprices.com"
        self.vendor = vendor

    async def get_product_list(self, page_number: int = 1, page_size: int = 1000):
        params = {
            "script": "customscript_pri_rest_product",
            "deploy": "customdeploy_pri_rest_product_ordo4837",
            "page": page_number,
            "pagesize": page_size,
        }
        headers = {"Content-Type": "application/json"}
        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return None

        result = response.json()

        if result["success"]:
            return result["result"]

    async def get_page_products(self, page_number: int = 1) -> List[CrazyDentalProduct]:
        products = await self.get_product_list(page_number, self.page_size)
        if not products:
            return []
        return [CrazyDentalProduct.from_dict(product) for product in products]

    async def get_products(self) -> List[CrazyDentalProduct]:
        print("Getting products...")
        products: List[CrazyDentalProduct] = []
        start_page = 1
        while True:
            end_page = start_page + 10
            tasks = (self.get_page_products(page) for page in range(start_page, end_page))
            results = await asyncio.gather(*tasks)
            for result in results:
                if result is None:
                    continue
                products.extend(result)
            if len(products) < self.page_size * (end_page - 1):
                break
            start_page = end_page
        return products

    async def create_order_request(self, order_info):
        params = {
            "script": "customscript_pri_rest_salesorder",
            "deploy": "customdeploy_pri_rest_salesord_ordo4837",
        }
        try:
            url, headers, body = self.oauthclient.sign(params=params, http_method="POST", headers=self.headers)
            async with self.session.post(url, headers=headers, json=order_info) as resp:
                if resp.status != 200:
                    response_text = await resp.text()
                    logging.error(f"Failed to create order, status: {resp.status}, response: {response_text}")
                    return None

                result = await resp.json()
                logging.info("Crazy Dental Order has been placed successfully", result)
                if result.get("success"):
                    logging.info("Order result", result)
                    print("Crazy Dental Order has been placed successfully")
                    return result.get("result")
        except ClientError as e:
            logging.error(f"An HTTP client error occurred: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")

    def get_tracking_link(self, tranid):
        product_status = tracking_number = tracking_link = ""
        params = {
            "script": "customscript_pri_rest_salesorder",
            "deploy": "customdeploy_pri_rest_salesord_ordo4837",
            "tranid": tranid,
        }
        headers = {"Content-Type": "application/json"}
        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)

        if response.status_code != status.HTTP_200_OK:
            return product_status, tracking_number, tracking_link

        resp_data = response.json()
        if "result" in resp_data:
            for result in resp_data["result"]:
                tracking_numbers_links = result.get("trackingNumbersLinks", [])
                if tracking_numbers_links:
                    tracking_number = tracking_numbers_links[0].get("trackingNumber", "")
                    tracking_link = tracking_numbers_links[0].get("link", "")
                    # product_status = result.get("statusref", "")
                    break
        product_status = resp_data["result"][0]["statusref"]
        return product_status, tracking_number, tracking_link

    async def get_customer_address(self, customer_id):
        headers = {"Content-Type": "application/json"}
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
            "customerid": customer_id,
        }

        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return None

        result = response.json()
        if result["success"]:
            return result["result"]

    async def get_order(self, order_id, order_type, office=None):
        try:
            params = {
                "script": "customscript_pri_rest_salesorder",
                "deploy": "customdeploy_pri_rest_salesord_ordo4837",
                "internalid": order_id,
            }
            headers = {"Content-Type": "application/json"}
            order_detail_resp = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)

            if order_detail_resp.status_code != status.HTTP_200_OK:
                return []
            logger.info(f"Order Detail - {order_id}: {order_detail_resp.status_code}")

            resp_data = order_detail_resp.json()
            order_history = {
                "currency": "USD",
                "order_id": resp_data["result"]["fields"]["tranid"],
                "order_date": datetime.datetime.strptime(resp_data["result"]["fields"]["trandate"], "%m/%d/%Y").date(),
                "status": resp_data["result"]["fields"]["status"],
                "order_detail_link": f"{self.BASE_URL}/dc-dental/my_account.ssp#purchases/view/{order_type}/"
                f"{order_id}",
                # "order_detail_link": "https://www.crazy_dental",
                "total_amount": resp_data["result"]["fields"]["total"],
            }
            get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
            customer_id = await get_vendor_customer_id_async(office_id=office.id)

            customer_address_info = await self.get_customer_address(customer_id)
            if customer_address_info:
                customer_address = [
                    {
                        "addressee": customer_address_info[-1]["addressee"],
                        "address1": customer_address_info[-1]["address1"],
                        "city": customer_address_info[-1]["city"],
                        "state": customer_address_info[-1]["state"],
                        "zipcode": customer_address_info[-1]["zipcode"],
                        "country": customer_address_info[-1]["country"],
                    }
                ]

                for address_item in customer_address:
                    address_items = [
                        address_item[k] for k in ["addressee", "address1", "city", "zipcode", "state", "country"]
                    ]
                    address_items = [_it.strip() for _it in address_items if _it.strip()]
                    address = ", ".join(address_items)

                    shipping_address = address
                order_history["shipping_address"] = {"address": shipping_address}
                order_history["products"] = []
                for product_line in resp_data["result"]["lines"]:
                    product_id = product_line["item_display"]
                    product_name = product_line["description"]
                    quantity = product_line["quantity"]
                    price = product_line["rate"]
                    url = "https://www.crazy_dental"

                    # line_id = product_line["internalid"]
                    product_status, tracking_number, tracking_link = self.get_tracking_link(
                        resp_data["result"]["fields"]["tranid"]
                    )

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
                    scraper = Scraper(vendor=self.vendor, session=self.session)
                    await scraper.save_order_to_db(office, order=Order.from_dict(order_history))
                return order_history
            return []
        except Exception as e:
            print(f"An error occurred ----: {e}")
            # Handle the error as per your requirement
            traceback.print_exc()
        return []

    async def get_crazy_dental_orders(self, office, completed_order_ids):
        page_number = 0
        tasks = []
        get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
        customer_id = await get_vendor_customer_id_async(office_id=office.id)
        while True:
            params = {
                "script": "customscript_pri_rest_salesorder",
                "deploy": "customdeploy_pri_rest_salesord_ordo4837",
                "customerid": customer_id,
                "page": page_number,
                "pagesize": 1000,
            }
            headers = {"Content-Type": "application/json"}
            response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
            if response.status_code != status.HTTP_200_OK:
                return []

            result = response.json()
            if result["success"]:
                for order in result["result"]:
                    order_id = order["internalid"]
                    order_type = order["ordertype"]
                    tasks.append(self.get_order(order_id, order_type, office))
                # if len(result) < 20:
                #     break
                # else:
                #     page_number += 1
                # page_number += 1
                if len(result["result"]) < 1000:
                    break
                page_number += 1
        orders = await asyncio.gather(*tasks, return_exceptions=True)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]


async def main():
    async with ClientSession() as session:
        api_client = CrazyDentalAPIClient(session)
        return await api_client.get_products()


if __name__ == "__main__":
    asyncio.run(main())
