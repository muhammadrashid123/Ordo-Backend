import datetime
import uuid
from asyncio import Semaphore
from typing import Any, Dict, List, Optional, Union

import requests
from asgiref.sync import sync_to_async
from requests import Response
from scrapy import Selector

from apps.vendor_clients import errors, types


class BaseClient:
    VENDOR_SLUG = "base"
    MULTI_CONNECTIONS = 10
    subclasses = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
        cls.subclasses.append(cls)

    @classmethod
    def make_handler(
        cls,
        vendor_slug: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        klass = [subclass for subclass in cls.subclasses if subclass.VENDOR_SLUG == vendor_slug][0]
        return klass(username=username, password=password)

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        self.session = requests.Session()
        self.username = username
        self.password = password
        self.orders = {}

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        raise NotImplementedError("`get_login_data` must be implemented")

    def check_authenticated(self, response: Response) -> bool:
        """Check if whether session is authenticated or not"""
        raise NotImplementedError("`check_authenticated` must be implemented")

    def get_order_list(
        self, from_date: Optional[datetime.date] = None, to_date: Optional[datetime.date] = None
    ) -> Dict[str, Union[Selector, dict]]:
        """Get a list of simple order information"""
        raise NotImplementedError("`get_order_list` must be implemented")

    def get_cart_page(self) -> Union[Selector, dict]:
        """Get cart page in order to get products in cart"""
        raise NotImplementedError("`get_cart_page` must be implemented")

    def remove_product_from_cart(self, product: Any):
        """Remove a single product from the cart"""
        raise NotImplementedError("`remove_product_from_cart` must be implemented")

    def clear_cart(self):
        """Clear all products from the cart"""
        raise NotImplementedError("`clear_cart` must be implemented")

    def serialize(self, data: Union[dict, Selector]) -> Optional[types.Product]:
        """Serialize vendor-specific product detail to our data"""
        raise NotImplementedError("`clear_cart` must be implemented")

    def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        """Add single product to cart"""
        raise NotImplementedError("`add_product_to_cart` must be implemented")

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        """Review the order without making real order"""
        raise NotImplementedError("Vendor client must implement `checkout`")

    def place_order(self, *args, **kwargs) -> str:
        """Make the real order"""
        raise NotImplementedError("Vendor client must implement `place_order`")

    def login(self, username: Optional[str] = None, password: Optional[str] = None):
        """Login session"""
        if username:
            self.username = username
        if password:
            self.password = password

        login_info = self.get_login_data()
        if login_info:
            with self.session.post(login_info["url"], headers=login_info["headers"], data=login_info["data"]) as resp:
                if resp.status_code != 200:
                    raise errors.VendorAuthenticationFailed()

                is_authenticated = self.check_authenticated(resp)
                if not is_authenticated:
                    raise errors.VendorAuthenticationFailed()

                if hasattr(self, "after_login_hook"):
                    self.after_login_hook(resp)

            return resp.cookies

    def get_response_as_dom(
        self, url: str, headers: Optional[dict] = None, query_params: Optional[dict] = None, **kwargs
    ) -> Selector:
        """Return response as dom format"""
        with self.session.get(url, headers=headers, params=query_params, **kwargs) as resp:
            text = resp.text
            return Selector(text=text)

    def get_response_as_json(
        self, url: str, headers: Optional[dict] = None, query_params: Optional[dict] = None, **kwargs
    ) -> dict:
        """Return response as json format"""
        with self.session.get(url, headers=headers, params=query_params, **kwargs) as resp:
            return resp.json()

    def get_product_page(self, product_link: str, headers: Optional[dict] = None):
        """Get the product page"""
        return self.get_response_as_dom(url=product_link, headers=headers)

    def get_product(
        self, product: types.Product, login_required: bool = True, semaphore: Semaphore = None
    ) -> Optional[types.Product]:
        """Get the product information"""
        if semaphore:
            semaphore.acquire()

        if login_required:
            self.login()

        if hasattr(self, "_get_product"):
            product_detail = self._get_product(product)
        else:
            headers = getattr(self, "GET_PRODUCT_PAGE_HEADERS")
            product_page_dom = self.get_response_as_dom(url=product["url"], headers=headers)
            product_detail = self.serialize(product_page_dom)

        if semaphore:
            semaphore.release()

        return product_detail

    def get_products(
        self, products: List[types.Product], login_required: bool = True
    ) -> Dict[str, Optional[types.Product]]:
        """Get the list of product information"""
        if login_required:
            self.login()

        ret: Dict[str, Optional[types.Product]] = {}
        for product in products:
            product_detail = self.get_product(product=product, login_required=False)
            if isinstance(product_detail, dict):
                ret[product["product_id"]] = product_detail
            else:
                ret[product["product_id"]] = None
        return ret

    @sync_to_async
    def get_products_prices(
        self, products: List[types.Product], login_required: bool = True, *args, **kwargs
    ) -> Dict[str, types.ProductPrice]:
        """Get the list of products prices"""
        if login_required:
            self.login()

        if hasattr(self, "_get_products_prices"):
            return self._get_products_prices(products, *args, **kwargs)
        elif hasattr(self, "get_product_price"):
            results = {}
            for product in products:
                product_detail = self.get_product_price(product=product, login_required=False)
                results.update(product_detail)
            return results
        else:
            results: Dict[str, Optional[types.Product]] = self.get_products(products=products, login_required=False)
            ret: Dict[str, types.ProductPrice] = {
                product_id: {"price": product["price"], "product_vendor_status": product["product_vendor_status"]}
                for product_id, product in results.items()
                if product is not None
            }
            return ret

    def remove_products_from_cart(self, products: List[Any]):
        """Remove the products from cart"""
        for product in products:
            self.remove_product_from_cart(product)

    def add_products_to_cart(self, products: List[types.CartProduct]):
        """Add Products to cart"""
        kwargs = {}
        if hasattr(self, "before_add_products_to_cart"):
            kwargs = self.before_add_products_to_cart()

        for product in products:
            self.add_product_to_cart(product, **kwargs)

    def _create_order(self, products: List[types.CartProduct], shipping_method: Optional[str] = None) -> dict:
        """Create an order on vendor side before the step of placing the real one"""
        self.login()
        self.clear_cart()
        self.add_products_to_cart(products)
        return self.checkout_and_review_order(shipping_method)

    def create_order(
        self, products: List[types.CartProduct], shipping_method: Optional[str] = None
    ) -> Dict[str, types.VendorOrderDetail]:
        result = self._create_order(products, shipping_method)
        order_detail = result.get("order_detail")
        return {self.VENDOR_SLUG: order_detail}

    def confirm_order(self, products: List[types.CartProduct], shipping_method=None, fake=False):
        """Place an order on vendor side"""
        result = self._create_order(products)
        if fake:
            order_id = f"{uuid.uuid4()}"
        else:
            order_id = self.place_order(**result)

        order_detail = result.get("order_detail")
        return {
            self.VENDOR_SLUG: order_detail,
            "order_id": order_id,
        }
