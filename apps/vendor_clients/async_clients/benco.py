import decimal
import json
import logging
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union

from aiohttp import ClientResponse
from result import Ok
from scrapy import Selector

from apps.common.utils import convert_string_to_price, strip_whitespaces
from apps.orders.models import OfficeProduct, Product
from apps.orders.updater import STATUS_ACTIVE, STATUS_UNAVAILABLE
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import (
    BaseClient,
    PriceInfo,
    ProductPriceUpdateResult,
)
from apps.vendor_clients.headers.benco import (
    ADD_PRODUCT_TO_CART_HEADERS,
    CLEAR_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    GET_PRODUCT_PRICES_HEADERS,
    LOGIN_HEADERS,
    POST_LOGIN_HEADERS,
    PRE_LOGIN_HEADERS,
)
import aiohttp

CERTIFICATE_BASE_PATH = Path(__file__).parent.resolve()

logger = logging.getLogger(__name__)


class BencoClient(BaseClient):
    VENDOR_SLUG = "benco"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        self.session = aiohttp.ClientSession()
        async with self.session.get("https://shop.benco.com/Login/Login", headers=PRE_LOGIN_HEADERS) as resp:
            text = await resp.text()
            login_url = str(resp.url)
            try:
                model_json = (
                    text.split("id='modelJson'")[1]
                    .split("</script>", 1)[0]
                    .split(">", 1)[1]
                    .replace("&quot;", '"')
                    .strip()
                )
                idsrv_xsrf = json.loads(model_json)["antiForgery"]["value"]

                headers = LOGIN_HEADERS.copy()
                headers["Referer"] = login_url
                return {
                    "url": login_url,
                    "headers": headers,
                    "data": {
                        "idsrv.xsrf": idsrv_xsrf,
                        "username": self.username,
                        "password": self.password,
                    },
                }
            except (IndexError, KeyError):
                pass

    async def check_authenticated(self, response: ClientResponse) -> bool:
        response_dom = Selector(text=await response.text())
        id_token = response_dom.xpath("//input[@name='id_token']/@value").get()
        scope = response_dom.xpath("//input[@name='scope']/@value").get()
        state = response_dom.xpath("//input[@name='state']/@value").get()
        session_state = response_dom.xpath("//input[@name='session_state']/@value").get()
        if not any([id_token, scope, state, session_state]):
            return False

        data = {"id_token": id_token, "scope": scope, "state": state, "session_state": session_state}
        await self.session.post("https://shop.benco.com/signin-oidc", headers=POST_LOGIN_HEADERS, data=data)
        return True

    async def get_cart_page(self) -> Union[Selector, dict]:
        return await self.get_response_as_dom(url="https://shop.benco.com/Cart")

    def get_cart_id(self, cart_page_dom: Selector) -> str:
        return cart_page_dom.xpath("//table[@id='cart_items_table']//tbody//input[@name='cartId']/@value").get()

    def get_cart_verify_token(self, cart_page_dom: Selector) -> str:
        return cart_page_dom.xpath(
            "//table[@id='cart_items_table']//tbody//input[@name='__RequestVerificationToken']/@value"
        ).get()

    async def clear_cart(self):
        cart_page_dom = await self.get_cart_page()
        cart_id = self.get_cart_id(cart_page_dom)

        params = {"cartId": cart_id}
        await self.session.get(
            "https://shop.benco.com/Cart/RemoveAllItems",
            headers=CLEAR_CART_HEADERS,
            params=params,
        )

    async def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        data = {
            "__RequestVerificationToken": kwargs.get("cart_verify_token"),
            "cartId": kwargs.get("cart_id"),
            "searchId": "",
            "quantity": str(product["quantity"]),
            "prodNum": product["product"]["product_id"],
        }
        await self.session.post(
            "https://shop.benco.com/Cart/AddQOEItem",
            headers=ADD_PRODUCT_TO_CART_HEADERS,
            data=data,
        )

    async def before_add_products_to_cart(self):
        cart_page_dom = await self.get_cart_page()
        return {
            "cart_id": self.get_cart_id(cart_page_dom),
            "cart_verify_token": self.get_cart_verify_token(cart_page_dom),
        }

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
        # TODO: this should be updated in the future
        product_name = data.xpath(".//h3[@class='product-name']/text()").get()
        images = data.xpath(".//div[@class='thumbnail']/img/@src").extract()
        if not images:
            images = data.xpath(".//div[@id='activeImageArea']/img/@src").extract()

        price_str = data.xpath(".//h3[@class='selling-price']/text()").get()
        price = convert_string_to_price(price_str)
        if price:
            product_vendor_status = "Available"
        else:
            product_vendor_status = strip_whitespaces(
                data.xpath(".//div[contains(@class, 'not-available-online')]/text()").get()
            )

        category = data.xpath(".//div[@class='breadcrumb-bar']/ul/li/a/text()").extract()[1:]

        return {
            "vendor": self.VENDOR_SLUG,
            "product_id": "",
            "sku": "",
            "name": product_name,
            "url": "",
            "images": images,
            "price": price,
            "product_vendor_status": product_vendor_status,
            "category": category,
            "unit": "",
        }

    async def _get_products_prices(self, products: List[types.Product]) -> Dict[str, types.Product]:
        """get vendor specific products prices"""
        product_prices = defaultdict(dict)
        product_ids = [product["product_id"] for product in products]
        data = {"productNumbers": product_ids, "pricePartialType": "ProductPriceRow"}
        try:
            async with self.session.post(
                "https://shop.benco.com/Search/GetPricePartialsForProductNumbers",
                headers=GET_PRODUCT_PRICES_HEADERS,
                json=data,
            ) as resp:
                res = await resp.json()
                if res:
                    for product_id, row in res.items():
                        row_dom = Selector(text=row)

                        try:
                            product_price = row_dom.xpath("//h4[@class='selling-price']").attrib["content"]
                            product_price = Decimal(product_price)
                        except (TypeError, decimal.ConversionSyntax):
                            product_prices[product_id]["price"] = Decimal("0")
                            product_prices[product_id]["product_vendor_status"] = self.product_vendor_not_exist
                        else:
                            product_prices[product_id]["price"] = product_price
                            product_prices[product_id]["product_vendor_status"] = "Available"

                        try:
                            promo_price_text = row_dom.xpath("//h3/span[@class='selling-price']").get()
                            expr = r"/?([0-9,]*\.[0-9]*)"
                            match = re.search(expr, promo_price_text)
                            promo_price = Decimal(match.group(0))
                        except (TypeError, decimal.ConversionSyntax):
                            product_prices[product_id]["special_price"] = Decimal("0")
                            product_prices[product_id]["is_special_offer"] = False
                        else:
                            product_prices[product_id]["special_price"] = promo_price
                            product_prices[product_id]["is_special_offer"] = True
                else:
                    for product_id in product_ids:
                        product_prices[product_id]["price"] = Decimal("0")
                        product_prices[product_id]["product_vendor_status"] = self.product_vendor_not_exist
        except Exception:
            pass
        return product_prices
    
    async def get_product_vendor_status(self, url, product_id):
        try:
            async with self.session.get(url) as resp:
                res = Selector(text=await resp.text())
                item_status = res.xpath(f"//a[@href='/Product/StockMap?prodNum={product_id}']/div/span/text()").get()
                item_description = res.xpath(f"//*[@id='product-detail-tab']/div/p/text()").get()
                product_details = {
                    "status": ' '.join(item_status.strip().split()),
                    "description": item_description
                }
                return product_details
        except Exception as e:
            item_status = ''
            logger.info(f"Product {product_id} status not found!")
            return item_status

    async def get_batch_product_prices(
        self, products: List[Union[Product, OfficeProduct]]
    ) -> List[ProductPriceUpdateResult]:
        headers = GET_PRODUCT_PRICES_HEADERS
        product_mapping = {office_product.product.product_id: office_product for office_product in products}
        data = {"productNumbers": list(product_mapping.keys()), "pricePartialType": "ProductPriceRow"}

        logger.debug("\n- Benco - Requesting info for %s", data)

        product_prices = []

        async with self.session.post(
            "https://shop.benco.com/Search/GetPricePartialsForProductNumbers",
            json=data,
            headers=headers,
        ) as resp:
            logger.debug("Response status is %s", resp.status)
            res = await resp.json()
            logger.debug("Response: %s", res)
            for product_id, row in res.items():
                row_dom = Selector(text=row)

                try:
                    price_info = row_dom.xpath("//h4[@class='selling-price']").attrib["content"]
                    product_url = row_dom.xpath("//link[@itemprop='url']/@href")[0]
                    item_details = await self.get_product_vendor_status(product_url.root, product_id)
                    product_price = Decimal(price_info) 
                    product_vendor_status = item_details["status"] or STATUS_ACTIVE
                except Exception:
                    # TODO: better handling, no except Exception please
                    product_price = Decimal("0")
                    product_vendor_status = STATUS_UNAVAILABLE
                try:
                    promotion_price_info = row_dom.xpath("//h3/span[@class='selling-price']").get()
                    match = re.search(r"/?([0-9,]*\.[0-9]*)", promotion_price_info)
                    promotion_price = Decimal(match.group(0))
                    is_special_offer = True
                except Exception:
                    # TODO: better handling, no except Exception please
                    promotion_price = Decimal("0")
                    is_special_offer = False
                result = ProductPriceUpdateResult(
                    product=product_mapping[product_id],
                    result=Ok(
                        PriceInfo(
                            price=product_price,
                            product_vendor_status=product_vendor_status,
                            is_special_offer=is_special_offer,
                            special_price=promotion_price,
                            description=item_details["description"],
                            image='',
                        )
                    ),
                )
                product_prices.append(result)
        return product_prices

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass

    async def place_order(self, *args, **kwargs) -> str:
        pass
