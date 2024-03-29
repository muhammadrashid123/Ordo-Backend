import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Union, cast

from result import Ok

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct, Product
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import (
    BaseClient,
    PriceInfo,
    ProductPriceUpdateResult,
)
from apps.vendor_clients.errors import VendorAuthenticationFailed
from apps.vendor_clients.headers.henry_schein import (
    GET_PRODUCT_PRICES_HEADERS,
    LOGIN_HEADERS,
)
from scrapy import Selector

logger = logging.getLogger(__name__)


class HenryScheinClient(BaseClient):
    aiohttp_mode = False
    VENDOR_SLUG = "henry_schein"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._n_value = None

    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        if username:
            self.username = username
        if password:
            self.password = password

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, self.login_proc)
        logger.info(f"login {res}")
        return res

    def login_proc(self):
        response = self.session.get("https://www.henryschein.com/", headers=LOGIN_HEADERS)
        data = {
            "username": self.username,
            "password": self.password,
            "did": "dental",
            "searchType": "authenticateuser",
            "culture": "us-en",
        }
        response = self.session.post(
            "https://www.henryschein.com/webservices/LoginRequestHandler.ashx",
            headers=LOGIN_HEADERS,
            data=data,
        )
        if not response.ok:
            raise VendorAuthenticationFailed
        res = json.loads(response.text)
        if res["IsAuthenticated"]:
            return True
        raise VendorAuthenticationFailed

    @property
    def n_value(self):
        if not self._n_value:
            resp = self.session.get(
                "https://www.henryschein.com/us-en/Search.aspx", headers=GET_PRODUCT_PRICES_HEADERS
            )
            body = resp.text
            magic_n_regex = re.compile(r"var _n = '(?P<nvalue>[^']+)'")
            match = magic_n_regex.search(body)
            if match:
                self._n_value = match.group("nvalue")
            else:
                raise ValueError("Failed to extract magic n value")
        return self._n_value

    async def get_product_image_and_description (self, product_id, headers):
        url = f"https://www.henryschein.com/us-en/Search.aspx?searchkeyWord={product_id}"
        with self.session.get(url, headers=headers) as resp:
            if not resp.ok:
                return
            response_text = resp.text
            
            pattern = r'<script type="application/ld\+json">(.*?)</script>'
            matches = re.findall(pattern, response_text, re.DOTALL)

            if matches:
                json_str = matches[0]
                # Clean up the JSON string and convert to a Python dictionary
                try:
                    json_data = json.loads(json_str)
                    return json_data
                except json.JSONDecodeError as e:
                    print("JSON decode error:", e)
                    return {"description": "", "image": ""}
            else:
                print("No matching <script> tag found.")
                return {"description": "", "image": ""}

    async def get_batch_product_prices(
        self, products: List[Union[Product, OfficeProduct]]
    ) -> List[ProductPriceUpdateResult]:
        cast(products, List[OfficeProduct])
        product_mapping = {office_product.product.product_id: office_product for office_product in products}
        logger.info("Requesting info for %s", [office_product.product.id for office_product in products])
        item_data_to_price = [
            {
                "ActionForSubstituteItems": None,
                "AllowSubstitutes": False,
                "AvailabilityCode": "01",
                "CatalogName": "B_DENTAL",
                # CatalogPrice: ...,
                # CatalogPriceDisplay: ...,
                # CustomerPrice: ...,
                # CustomerPriceList: ...,
                "DoNotShowPrice": False,
                "ErrorToGetInventoryStatus": False,
                "ForceUpdateInventoryStatus": False,
                "InventoryAvailabilityStyle": "Ico_AvailInStockLocally us-dental xx-small",
                "InventoryAvailabilityText": "In stock locally (see estimated delivery date during checkout)",
                "InventoryStatus": "AvailableLocally",
                "IsTooth": False,
                "ItemsInCart": None,
                "LastPurchasedDate": None,
                "ManufactureItemCode": "",
                "PricingErrorMessage": None,
                "PricingLabel": "Contract",
                "PricingLabelStyle": "US_PricingLabel_CONTRACT",
                "ProductId": product.product.product_id,
                "ProductLabelText": "",
                "PromoCode": "",
                "Qty": "1",
                "ShowPriceForAnonymousUsers": False,
                "SubstituteItems": None,
                "TSMPriceLabel": None,
                "ToothItemCode": "",
                "Uom": product.product.product_unit,
                "UomList": None,
            }
            for product in products
        ]
        data = {
            "ItemArray": json.dumps(
                {
                    "ItemDataToPrice": item_data_to_price,
                }
            ),
            "searchType": "6",
            "did": "dental",
            "catalogName": "B_DENTAL",
            "endecaCatalogName": "DENTAL",
            "culture": "us-en",
            "showPriceToAnonymousUserFromCMS": "False",
            "isCallingFromCMS": "False",
        }

        headers = {**GET_PRODUCT_PRICES_HEADERS, "N": self.n_value}
        product_prices = []
        with self.session.post(
            "https://www.henryschein.com/webservices/JSONRequestHandler.ashx",
            data=data,
            headers=headers,
        ) as resp:
            logger.info("Response status is %s", resp.status_code)
            if not resp.ok:
                return product_prices
            response_text = resp.text
            try:
                res = json.loads(response_text)
            except json.decoder.JSONDecodeError:
                logger.error("Could not parse response text: %s", response_text)
                return product_prices
            for product_price in res["ItemDataToPrice"]:
                availability = product_price.get("InventoryAvailabilityText", "")
                price = product_price.get("CustomerPrice", 0)
                try:
                    img_des_json = await self.get_product_image_and_description(
                        product_price['ProductId'], headers
                    )
                except Exception as e:
                    img_des_json = {"description": "", "image": ""}
                    print('Got exception while getting product Des & Image => ', e)
                if availability and availability in ["Temporarily unavailable", "Discontinued"]:
                    price = 0
                if availability and any(
                    [
                        _it in availability
                        for _it in [
                            "add to comments",
                        ]
                    ]
                ):
                    price = 0
                result = ProductPriceUpdateResult(
                    product=product_mapping[product_price["ProductId"]],
                    result=Ok(
                        PriceInfo(
                            price=convert_string_to_price(price),
                            product_vendor_status=product_price["InventoryStatus"],
                            image=img_des_json["image"] if img_des_json["image"] != "" else '',
                            description=img_des_json["description"] if img_des_json["description"] != "" else '',
                        )
                    ),
                )
                product_prices.append(result)
        return product_prices

    async def _get_products_prices(
        self, products: List[types.Product], *args, **kwargs
    ) -> Dict[str, types.ProductPrice]:
        """get vendor specific products prices"""
        data = {
            "ItemArray": json.dumps(
                {
                    "ItemDataToPrice": [
                        {
                            "ProductId": product["product_id"],
                            "Qty": "1",
                            "Uom": product["unit"],
                            "PromoCode": "",
                            "CatalogName": "B_DENTAL",
                            "ForceUpdateInventoryStatus": False,
                            "AvailabilityCode": "01",
                        }
                        for product in products
                    ],
                }
            ),
            "searchType": "6",
            "did": "dental",
            "catalogName": "B_DENTAL",
            "endecaCatalogName": "DENTAL",
            "culture": "us-en",
            "showPriceToAnonymousUserFromCMS": "False",
            "isCallingFromCMS": "False",
        }

        headers = GET_PRODUCT_PRICES_HEADERS.copy()
        product_prices = defaultdict(dict)
        with self.session.post(
            "https://www.henryschein.com/webservices/JSONRequestHandler.ashx",
            data=data,
            headers=headers,
        ) as resp:
            if resp.status_code != 200:
                return product_prices
            res = json.loads(resp.text)
            for product_price in res["ItemDataToPrice"]:
                with self.session.get(f'https://www.henryschein.com/us-en/Search.aspx?searchkeyWord={product_price["ProductId"]}') as response:
                    title_selector = Selector(text=response.text)
                    try:
                        title = title_selector.xpath("//h2[@class='product-name']/a/text()").get()
                    except Exception as e:
                        title = ''
                product_prices[product_price["ProductId"]]["product_vendor_status"] = product_price["InventoryStatus"]
                product_prices[product_price["ProductId"]]["name"] = title
                product_prices[product_price["ProductId"]]["price"] = convert_string_to_price(
                    product_price["CustomerPrice"]
                )
        return product_prices
