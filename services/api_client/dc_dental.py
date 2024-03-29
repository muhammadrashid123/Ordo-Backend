import asyncio
import logging
import os
from typing import List
from urllib.parse import urlencode

import oauthlib.oauth1
from aiohttp.client import ClientSession

# from apps.accounts.views.crazy_dental_integration import (
#     access_token,
#     consumer_key,
#     consumer_secret,
#     crazy_dental_Base_url,
#     realm,
#     token_secret,
# )
from services.api_client.vendor_api_types import DCDentalProduct
from services.utils.secrets import get_secret_value

logger = logging.getLogger(__name__)


class DCDentalOauth:
    def __init__(self):
        # Change for crazy dental
        # self.NETSUITE_ACCOUNT_ID = realm
        # self.BASE_URL = crazy_dental_Base_url
        # self.SAFE_CHARS = "~()*!.'"
        # self.client = oauthlib.oauth1.Client(
        #     client_key=consumer_key,
        #     client_secret=consumer_secret,
        #     resource_owner_key=access_token,
        #     resource_owner_secret=token_secret,
        #     signature_method="HMAC-SHA256",
        # )
        self.NETSUITE_ACCOUNT_ID = "1075085"
        self.BASE_URL = "https://1075085.restlets.api.netsuite.com/app/site/hosting/restlet.nl"
        self.SAFE_CHARS = "~()*!.'"
        self.client = oauthlib.oauth1.Client(
            client_key=os.getenv("DCDENTAL_CONSUMER_KEY"),
            client_secret=get_secret_value("DCDENTAL_CONSUMER_SECRET"),
            resource_owner_key=os.getenv("DCDENTAL_TOKEN_ID"),
            resource_owner_secret=get_secret_value("DCDENTAL_TOKEN_SECRET"),
            signature_method="HMAC-SHA256",
        )

    def sign(self, params, http_method, headers):
        uri = f"{self.BASE_URL}?{urlencode(params)}"
        url, headers, body = self.client.sign(
            uri=uri, http_method=http_method, realm=self.NETSUITE_ACCOUNT_ID, headers=headers
        )
        return url, headers, body


class DCDentalAPIClient:
    def __init__(self, session: ClientSession):
        self.session = session
        self.page_size = 1000
        self.oauthclient = DCDentalOauth()
        self.headers = {"Content-Type": "application/json"}

    async def get_product_list(self, page_number: int = 1, page_size: int = 1000):
        params = {
            "script": "customscript_pri_rest_product",
            "deploy": "customdeploy_pri_rest_product_ordo4837",
            "page": page_number,
            "pagesize": page_size,
        }
        url, headers, body = self.oauthclient.sign(params=params, http_method="GET", headers=self.headers)
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]

    async def get_customer(self, email: str):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
            "email": email,
        }
        url, headers, body = self.oauthclient.sign(params=params, http_method="GET", headers=self.headers)
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]

    async def create_customer(self, customer_info):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
        }
        url, headers, body = self.oauthclient.sign(params=params, http_method="POST", headers=self.headers)
        async with self.session.post(url, headers=headers, json=customer_info) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]

    async def get_customer_address(self, customer_id):
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
            "customerid": customer_id,
        }
        url, headers, body = self.oauthclient.sign(params=params, http_method="GET", headers=self.headers)
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]

    async def create_customer_address(self, customer_address_info):
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
        }
        url, headers, body = self.oauthclient.sign(params=params, http_method="POST", headers=self.headers)
        async with self.session.post(url, headers=headers, json=customer_address_info) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]

    async def get_page_products(self, page_number: int = 1) -> List[DCDentalProduct]:
        products = await self.get_product_list(page_number, self.page_size)
        if not products:
            return []
        return [DCDentalProduct.from_dict(product) for product in products]

    async def get_products(self) -> List[DCDentalProduct]:
        products: List[DCDentalProduct] = []
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
        url, headers, body = self.oauthclient.sign(params=params, http_method="POST", headers=self.headers)
        async with self.session.post(url, headers=headers, json=order_info) as resp:
            if resp.status != 200:
                return None

            result = await resp.json()
            if result["success"]:
                return result["result"]


async def main():
    async with ClientSession() as session:
        api_client = DCDentalAPIClient(session)
        return await api_client.get_products()


if __name__ == "__main__":
    asyncio.run(main())
