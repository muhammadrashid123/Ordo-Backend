import asyncio
import datetime
import decimal
import logging
import time
import traceback
import uuid
from asyncio import Semaphore
from collections import ChainMap
from typing import Any, Dict, List, NamedTuple, Optional, Union

import requests
from aiohttp import ClientResponse, ClientSession
from asgiref.sync import sync_to_async
from result import Err, Ok, Result
from scrapy import Selector

from apps.accounts.views.crazy_dental_integration import (
    crazy_dental_Base_url,
    get_vendor_customer_id,
    oauth,
)
from apps.orders.models import OfficeProduct, Product
from apps.scrapers.semaphore import fake_semaphore
from apps.vendor_clients import errors, types
from config.utils import get_bool_config

logger = logging.getLogger(__name__)


BASE_HEADERS = {
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class ScrapingError(Exception):
    pass


class TooManyRequests(ScrapingError):
    pass


class EmptyResults(ScrapingError):
    pass


class PriceInfo(NamedTuple):
    price: decimal.Decimal
    product_vendor_status: str
    is_special_offer: bool = False
    special_price: Optional[decimal.Decimal] = None
    sku_code: Optional[str] = None
    image: Optional[str] = None
    description: Optional[str] = None


class ProductPriceUpdateResult(NamedTuple):
    product: Union[Product, OfficeProduct]
    result: Result[PriceInfo, Union[ScrapingError, Exception]]


class BaseClient:
    VENDOR_SLUG = "base"
    MULTI_CONNECTIONS = 10
    subclasses = []
    aiohttp_mode = True
    product_vendor_not_exist = "Discontinued"
    SELF_LOGIN_VENDORS = ["patterson", "dental_city", "darby"]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
        cls.subclasses.append(cls)

    @classmethod
    def make_handler(
        cls,
        vendor_slug: str,
        session: Optional[ClientSession] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        klass = [subclass for subclass in cls.subclasses if subclass.VENDOR_SLUG == vendor_slug][0]
        return klass(session=session, username=username, password=password)

    def __init__(
        self, session: Optional[ClientSession] = None, username: Optional[str] = None, password: Optional[str] = None
    ):
        if self.aiohttp_mode:
            self.session = session
        else:
            self.session = requests.Session()
            verify = get_bool_config("REQUESTS_VERIFY", default=True)
            if not verify:
                self.session.verify = False
                requests.urllib3.disable_warnings()

        self.username = username
        self.password = password
        self.orders = {}

    async def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        raise NotImplementedError("`get_login_data` must be implemented")

    async def check_authenticated(self, response: ClientResponse) -> bool:
        """Check if whether session is authenticated or not"""
        raise NotImplementedError("`check_authenticated` must be implemented")

    async def get_order_list(
        self, from_date: Optional[datetime.date] = None, to_date: Optional[datetime.date] = None
    ) -> Dict[str, Union[Selector, dict]]:
        """Get a list of simple order information"""
        raise NotImplementedError("`get_order_list` must be implemented")

    async def get_cart_page(self) -> Union[Selector, dict]:
        """Get cart page in order to get products in cart"""
        raise NotImplementedError("`get_cart_page` must be implemented")

    async def remove_product_from_cart(self, product: Any):
        """Remove a single product from the cart"""
        raise NotImplementedError("`remove_product_from_cart` must be implemented")

    async def clear_cart(self):
        """Clear all products from the cart"""
        raise NotImplementedError("`clear_cart` must be implemented")

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
        """Serialize vendor-specific product detail to our data"""
        raise NotImplementedError("`clear_cart` must be implemented")

    async def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        """Add single product to cart"""
        raise NotImplementedError("`add_product_to_cart` must be implemented")

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        """Review the order without making real order"""
        raise NotImplementedError("Vendor client must implement `checkout`")

    async def place_order(self, *args, **kwargs) -> str:
        """Make the real order"""
        raise NotImplementedError("Vendor client must implement `place_order`")

    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        """Login session"""
        if username:
            self.username = username
        if password:
            self.password = password
        try:
            login_info = await self.get_login_data()
        except Exception as e:
            logger.debug("Got login data exception: %s", e)

        logger.debug("Got logger data: %s", login_info)
        if login_info:
            logger.debug("Logging in...")
            async with self.session.post(
                login_info["url"], headers=login_info["headers"], data=login_info["data"]
            ) as resp:
                if resp.status != 200:
                    content = await resp.read()
                    logger.debug("Got %s status, content = %s", resp.status, content)
                    raise errors.VendorAuthenticationFailed()

                is_authenticated = await self.check_authenticated(resp)
                if not is_authenticated:
                    logger.debug("Still not authenticated")
                    raise errors.VendorAuthenticationFailed()

                if hasattr(self, "after_login_hook"):
                    await self.after_login_hook(resp)

                logger.info("Successfully logged in")

    async def get_response_as_dom(
        self, url: str, headers: Optional[dict] = None, query_params: Optional[dict] = None, **kwargs
    ) -> Selector:
        """Return response as dom format"""
        for tryy in range(3):
            try:
                async with self.session.get(url, headers=headers, params=query_params, **kwargs) as resp:
                    text = await resp.text()
                    return Selector(text=text)
            except Exception as e:
                logger.exception("Got exception while getting dom => ", str(e))
                time.sleep(1)

    async def get_response_as_json(
        self, url: str, headers: Optional[dict] = None, query_params: Optional[dict] = None, **kwargs
    ) -> dict:
        """Return response as json format"""
        async with self.session.get(url, headers=headers, params=query_params, **kwargs) as resp:
            return await resp.json()

    async def get_product_page(self, product_link: str, headers: Optional[dict] = None):
        """Get the product page"""
        return await self.get_response_as_dom(url=product_link, headers=headers)

    async def get_order(self, *args, **kwargs) -> Optional[types.Order]:
        """Get Order information"""
        semaphore = kwargs.pop("semaphore", None)
        if not semaphore:
            semaphore = fake_semaphore
        async with semaphore:
            if hasattr(self, "_get_order"):
                queue: asyncio.Queue = kwargs.pop("queue", None)

                order = await self._get_order(*args)
                if queue:
                    await queue.put(order)

                return order

    async def get_orders(
        self,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        exclude_order_ids: Optional[List[str]] = None,
        queue: Optional[asyncio.Queue] = None,
    ) -> List[types.Order]:
        await self.login()
        semaphore = Semaphore(value=self.MULTI_CONNECTIONS)
        order_list = await self.get_order_list(from_date=from_date, to_date=to_date)
        tasks = []
        for order_id, order_data in order_list.items():
            if exclude_order_ids and order_id in exclude_order_ids:
                continue
            tasks.append(self.get_order(order_data, semaphore=semaphore, queue=queue))

        orders = await asyncio.gather(*tasks, return_exceptions=True)
        return [order for order in orders if isinstance(order, dict)]

    async def get_product(
        self, product: types.Product, login_required: bool = True, semaphore: Semaphore = None
    ) -> Optional[types.Product]:
        """Get the product information"""
        if not semaphore:
            semaphore = fake_semaphore
        async with semaphore:
            if login_required:
                await self.login()

            if hasattr(self, "_get_product"):
                product_detail = await self._get_product(product)
            else:
                headers = getattr(self, "GET_PRODUCT_PAGE_HEADERS")
                product_page_dom = await self.get_response_as_dom(url=product["url"], headers=headers)
                product_detail = self.serialize(product, product_page_dom)

        return product_detail

    async def get_products(
        self, products: List[types.Product], login_required: bool = True
    ) -> Dict[str, Optional[types.Product]]:
        """Get the list of product information"""
        semaphore = Semaphore(value=self.MULTI_CONNECTIONS)
        ret: Dict[str, Optional[types.Product]] = {}

        if login_required and self.VENDOR_SLUG not in self.SELF_LOGIN_VENDORS:
            await self.login()

        tasks = [
            self.get_product(
                product=product,
                semaphore=semaphore,
                login_required=False if self.VENDOR_SLUG not in self.SELF_LOGIN_VENDORS else True,
            )
            for product in products
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for product, result in zip(products, results):
            if isinstance(result, dict):
                ret[product["product_id"]] = result
            else:
                if isinstance(result, Exception):
                    logger.warning(
                        "Got exception: %s", "".join(traceback.TracebackException.from_exception(result).format())
                    )
                ret[product["product_id"]] = None
        return ret

    async def get_crazy_dental_products_prices_from_vendor(self, office_id, product_id):
        get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
        customer_id = await get_vendor_customer_id_async(office_id=office_id)
        headers = {"Content-Type": "application/json"}
        params = {
            "script": "customscript_pri_rest_product",
            "deploy": "customdeploy_pri_rest_product_ordo4837",
            "itemid": product_id,
            "customerid": customer_id,
        }
        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
        if response.status_code == 200:
            json_response = response.json()
            if json_response["success"]:
                data = json_response["result"]

                return data
            return []
        return []

    async def get_products_prices(
        self, products: List[types.Product], login_required: bool = True, office_id=None, *args, **kwargs
    ) -> Dict[str, types.ProductPrice]:
        """Get the list of products prices"""

        if self.VENDOR_SLUG == "crazy_dental":
            ret: Dict[str, types.ProductPrice] = {}
            for product in products:
                results = await self.get_crazy_dental_products_prices_from_vendor(
                    office_id=login_required, product_id=product["product_id"]
                )
                if results:
                    # Assuming results is a list of dictionaries containing product prices
                    product_price = results[0]["pricing_unitprice"]
                    ret[product["product_id"]] = {"price": product_price, "product_vendor_status": "Active"}
            return ret

        else:
            if login_required and self.VENDOR_SLUG not in self.SELF_LOGIN_VENDORS:
                try:
                    await self.login()
                except Exception as e:
                    print("Login got exception =======> ", e)

            if hasattr(self, "_get_products_prices"):
                return await self._get_products_prices(products, *args, **kwargs)
            elif hasattr(self, "get_product_price"):
                semaphore = Semaphore(value=self.MULTI_CONNECTIONS)
                tasks = (
                    self.get_product_price(product=product, semaphore=semaphore, login_required=False)
                    for product in products
                )
                results = await asyncio.gather(*tasks, return_exceptions=True)
                results = [result for result in results if isinstance(result, dict)]
                return dict(ChainMap(*results))
            else:
                results: Dict[str, Optional[types.Product]] = await self.get_products(
                    products=products,
                    login_required=False if self.VENDOR_SLUG not in self.SELF_LOGIN_VENDORS else True,
                )
                ret: Dict[str, types.ProductPrice] = {
                    product_id: {"price": product["price"], "product_vendor_status": product["product_vendor_status"]}
                    for product_id, product in results.items()
                    if product is not None
                }
                return ret

    async def remove_products_from_cart(self, products: List[Any]):
        """Remove the products from cart"""
        tasks = []
        for product in products:
            tasks.append(self.remove_product_from_cart(product))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def add_products_to_cart(self, products: List[types.CartProduct]):
        """Add Products to cart"""
        tasks = []
        kwargs = {}
        if hasattr(self, "before_add_products_to_cart"):
            kwargs = await self.before_add_products_to_cart()

        for product in products:
            tasks.append(self.add_product_to_cart(product, **kwargs))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _create_order(self, products: List[types.CartProduct], shipping_method: Optional[str] = None) -> dict:
        """Create an order on vendor side before the step of placing the real one"""
        await self.login()
        await self.clear_cart()
        await self.add_products_to_cart(products)
        return await self.checkout_and_review_order(shipping_method)

    async def create_order(
        self, products: List[types.CartProduct], shipping_method: Optional[str] = None
    ) -> Dict[str, types.VendorOrderDetail]:
        result = await self._create_order(products, shipping_method)
        order_detail = result.get("order_detail")
        return {self.VENDOR_SLUG: order_detail}

    async def confirm_order(self, products: List[types.CartProduct], shipping_method=None, fake=False):
        """Place an order on vendor side"""
        result = await self._create_order(products)
        if fake:
            order_id = f"{uuid.uuid4()}"
        else:
            order_id = await self.place_order(**result)

        order_detail = result.get("order_detail")
        return {
            self.VENDOR_SLUG: order_detail,
            "order_id": order_id,
        }

    async def get_product_price_v2(self, product: Product) -> PriceInfo:
        ...

    async def get_batch_product_prices(self, products: List[Product]) -> List[ProductPriceUpdateResult]:
        """
        Default implementation using get_product_price_v2 approach
        """
        results = []
        for product in products:
            try:
                price_info = await self.get_product_price_v2(product)
                logger.debug("Got price info for product %s: %s", product.id, price_info)
            except ScrapingError as e:
                logger.debug("Get error: %s", e)
                results.append(ProductPriceUpdateResult(product=product, result=Err(e)))
            except Exception as e:
                logger.exception("Got exception")
                results.append(ProductPriceUpdateResult(product=product, result=Err(e)))
            else:
                results.append(ProductPriceUpdateResult(product=product, result=Ok(price_info)))
        return results
