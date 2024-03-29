import logging
import traceback
from asyncio import Semaphore
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import Product
from apps.scrapers.semaphore import fake_semaphore
from apps.vendor_clients import types
from apps.vendor_clients.async_clients.base import (
    BaseClient,
    EmptyResults,
    PriceInfo,
    TooManyRequests,
)
from apps.vendor_clients.headers.net_32 import (
    ADD_PRODUCT_TO_CART_HEADERS,
    CART_HEADERS,
    LOGIN_HEADERS,
    PLACE_ORDER_HEADERS,
    REMOVE_PRODUCT_FROM_CART_HEADERS,
    REVIEW_ORDER_HEADERS,
)
import cloudscraper

logger = logging.getLogger(__name__)


class Net32Client(BaseClient):
    VENDOR_SLUG = "net_32"

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        return {
            "url": "https://www.net32.com/rest/user/login",
            "headers": LOGIN_HEADERS,
            "data": {
                "userName": self.username,
                "password": self.password,
                "latestTosVersion": "1",
            },
        }

    async def check_authenticated(self, response: ClientResponse) -> bool:
        """Check if whether session is authenticated or not"""
        res = await response.json()
        return (
            res.get("CallHeader", {}).get("StatusCode")
            and res["CallHeader"]["StatusCode"] != "SC_ERROR_BAD_LOGIN_CREDENTIALS"
        )

    async def get_cart_page(self) -> Union[Selector, dict]:
        """Get cart page in order to get products in cart"""
        async with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            return await resp.json()

    async def remove_product_from_cart(self, product: Any):
        """Remove a single product from the cart
        Currently not used
        """
        product_id = product["product_id"]
        async with self.session.get(
            "https://www.net32.com/rest/shoppingCart/get", headers=REMOVE_PRODUCT_FROM_CART_HEADERS
        ) as resp:
            cart_res = await resp.json()
            data = [
                {
                    "mpId": product["mpId"],
                    "vendorProductId": product["vendorProductId"],
                    "minimumQuantity": product["minimumQuantity"],
                    "quantity": 0,
                }
                for vendor in cart_res["payload"]["vendorOrders"]
                for product in vendor["products"]
                if str(product["mpId"]) == product_id
            ]
        await self.session.post(
            "https://www.net32.com/rest/shoppingCart/modify/rev2", headers=REMOVE_PRODUCT_FROM_CART_HEADERS, json=data
        )

    async def clear_cart(self):
        """Clear all products from the cart"""
        async with self.session.get("https://www.net32.com/rest/shoppingCart/get", headers=CART_HEADERS) as resp:
            cart_res = await resp.json()
            data = []
            for vendor in cart_res["payload"]["vendorOrders"]:
                for product in vendor["products"]:
                    data.append(
                        {
                            "mpId": product["mpId"],
                            "vendorProductId": product["vendorProductId"],
                            "minimumQuantity": product["minimumQuantity"],
                            "quantity": 0,
                        }
                    )
        await self.session.post("https://www.net32.com/rest/shoppingCart/modify/rev2", headers=CART_HEADERS, json=data)

    async def _get_product(self, product: types.Product) -> Optional[types.Product]:
        """ """
        async with self.session.get(f"https://www.net32.com/rest/neo/pdp/{product['product_id']}") as resp:
            res = await resp.json()
            return self.serialize(product, res)

    async def get_product_price(
        self, product: types.Product, semaphore: Optional[Semaphore] = None, login_required: bool = False
    ) -> Dict[str, types.ProductPrice]:
        if not semaphore:
            semaphore = fake_semaphore
        async with semaphore:
            product_id = product["product_id"]
            try:
                scraper = cloudscraper.create_scraper()
                response = scraper.get(f"https://www.net32.com/rest/neo/pdp/{product_id}/vendor-options")
                logger.debug(f"Status code for {product_id} is {response.status_code}")
                if response.status_code == 429:
                    raise TooManyRequests()
                
                vendor_options = response.json()
                vendor_options = sorted(
                    vendor_options,
                    key=lambda x: min(x["priceBreaks"], key=lambda y: y["unitPrice"])["unitPrice"],
                )
                price = vendor_options[0]["priceBreaks"][0]["unitPrice"]
                is_special_offer = False
                special_price = 0
                if len(vendor_options[0]["priceBreaks"]) >= 2:
                    is_special_offer = True
                    special_price = vendor_options[0]["priceBreaks"][-1]["unitPrice"]
            except Exception as e:  # noqa
                logger.warning("Got exception: %s", "".join(traceback.TracebackException.from_exception(e).format()))
                raise
            return {
                product_id: {
                    "price": Decimal(str(price)),
                    "product_vendor_status": "Active",
                    "is_special_offer": is_special_offer,
                    "special_price": Decimal(str(special_price)),
                }
            }

    async def get_product_price_v2(self, product: Product) -> PriceInfo:
        product_id = product.product_id
        try:
            async with self.session.get(f"https://www.net32.com/rest/neo/pdp/{product_id}/vendor-options") as resp:
                logger.debug(f"Status code for {product_id} is {resp.status}")
                if resp.status == 429:
                    raise TooManyRequests()
                vendor_options = await resp.json()
                if len(vendor_options) == 0:
                    raise EmptyResults()
                logger.debug("Got response for %s: %s", product_id, vendor_options)
                vendor_options = sorted(
                    # vendor_options, key=lambda x: (x["promisedHandlingTime"], x["priceBreaks"][0]["unitPrice"])
                    vendor_options,
                    key=lambda x: min(x["priceBreaks"], key=lambda y: y["unitPrice"])["unitPrice"],
                )

                vendor_option = vendor_options[0]
                price_breaks = vendor_option["priceBreaks"]
                first_price = price_breaks[0]
                price = first_price["unitPrice"]
                is_special_offer = False
                special_price = 0
                if len(price_breaks) >= 2:
                    is_special_offer = True
                    special_price = price_breaks[-1]["unitPrice"]
        except Exception as e:  # noqa
            logger.warning("Got exception: %s", "".join(traceback.TracebackException.from_exception(e).format()))
            raise
        return PriceInfo(
            price=Decimal(str(special_price)) if is_special_offer else Decimal(str(price)),
            product_vendor_status="Active",
            is_special_offer=False,
            special_price=None,
        )

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
        """Serialize vendor-specific product detail to our data"""
        return {
            "vendor": self.VENDOR_SLUG,
            "product_id": "",
            "sku": "",
            "name": data["title"],
            "url": f"https://www.net32.com/{data['url']}",
            "images": [f"https://www.net32.com/media{data['mediaPath']}"],
            "price": Decimal(data["retailPrice"]),
            "product_vendor_status": "",
            "category": "",
            "unit": "",
        }

    async def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        """Add single product to cart"""
        data = [
            {
                "mpId": product["product"]["product_id"],
                "quantity": product["quantity"],
            }
        ]

        await self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation",
            headers=ADD_PRODUCT_TO_CART_HEADERS,
            json=data,
        )

    async def add_products_to_cart(self, products: List[types.CartProduct]):
        data = [
            {
                "mpId": product["product"]["product_id"],
                "quantity": product["quantity"],
            }
            for product in products
        ]

        await self.session.post(
            "https://www.net32.com/rest/shoppingCart/addMfrProdViaConsolidation",
            headers=ADD_PRODUCT_TO_CART_HEADERS,
            json=data,
        )

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        """Review the order without making real order"""
        # TODO: check payment_method & shipping_address
        dom = await self.get_response_as_dom(url="https://www.net32.com/checkout", headers=REVIEW_ORDER_HEADERS)

        subtotal_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[3]/td/text()").get()
        )
        shipping_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[4]/td/text()").get()
        )
        tax_amount = convert_string_to_price(
            dom.xpath("//table[@class='order-summary-subtotal-table']//tr[5]/td/text()").get()
        )
        total_amount = convert_string_to_price(
            dom.xpath(
                "//table[@class='order-summary-grandtotal-table']"
                "//span[@class='order-summary-grandtotal-value']/text()"
            ).get()
        )
        # payment_method = dom.xpath("//dl[@id='order-details-payment']/dd[1]/strong//text()").extract()
        # shipping_address = dom.xpath("//dl[@id='order-details-shipping']/dd[2]/text()").get()

        order_detail = types.VendorOrderDetail(
            subtotal_amount=subtotal_amount,
            shipping_amount=shipping_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            payment_method="",
            shipping_address="",
        )

        return {
            "order_detail": order_detail,
        }

    async def place_order(self, *args, **kwargs) -> str:
        """Make the real order"""
        async with self.session.post(
            "https://www.net32.com/checkout/confirmation", headers=PLACE_ORDER_HEADERS
        ) as resp:
            response_dom = Selector(text=await resp.text())
            return response_dom.xpath("//h2[@class='checkout-confirmation-order-number-header']//a/text()").get()
