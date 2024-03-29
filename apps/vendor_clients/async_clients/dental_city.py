import asyncio
import logging
from typing import Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import convert_string_to_price
from apps.orders.models import OfficeProduct
from apps.vendor_clients import types
from apps.vendor_clients.async_clients import BaseClient
from apps.vendor_clients.async_clients.base import EmptyResults, PriceInfo
from apps.vendor_clients.headers.dental_city import (
    ADD_PRODUCT_TO_CART_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    LOGIN_PAGE_HEADERS,
    REMOVE_PRODUCT_FROM_CART_HEADERS,
)
from apps.vendor_clients import errors
import cloudscraper

logger = logging.getLogger(__name__)


class DentalCityClient(BaseClient):
    VENDOR_SLUG = "dental_city"
    GET_PRODUCT_PAGE_HEADERS = GET_PRODUCT_PAGE_HEADERS

    async def get_login_data(self, *args, **kwargs) -> types.LoginInformation:
        # await self.session.get("https://www.dentalcity.com/account/login", headers=LOGIN_PAGE_HEADERS)
        return {
            "url": "https://www.dentalcity.com/account/login/",
            "headers": LOGIN_HEADERS,
            "data": {
                "UserName": self.username,
                "Password": self.password,
                "ReturnUrl": "",
                "Message": "",
                "Name": "",
                "DashboardURL": "https://www.dentalcity.com/profile/dashboard",
            },
        }

    async def check_authenticated(self, response: ClientResponse) -> bool:
        text = await response.text()
        dom = Selector(text=text)
        login_success = dom.xpath("//input[@id='Message']/@value").get()
        return login_success == "success"

    async def get_product_price_v2(self, product: OfficeProduct) -> PriceInfo:
        url = product.product.url
        if url is None:
            logger.warning("Url is empty for product %s", product.id)
            raise EmptyResults()
        resp = await self.session.get(url, headers=self.GET_PRODUCT_PAGE_HEADERS)
        logger.debug("Got status: %s", resp.status)
        if resp.status != 200:
            raise EmptyResults()
        text = await resp.text()
        page = Selector(text=text)
        sku = page.xpath('//div[@class="skuname"]//span/text()').get()
        price_str = page.xpath('//div[@class="yourpricecontainer"]//span/text()').get()
        price = convert_string_to_price(price_str)
        if not price:
            logger.warning("Got bad price for %s. %s", product.id, price_str)
            raise EmptyResults()
        return PriceInfo(
            price=price,
            product_vendor_status="Active",
            sku_code=sku,
        )

    def serialize(self, base_product: types.Product, data: Union[dict, Selector]) -> Optional[types.Product]:
        # TODO: we need to parse all product details in the future if that is required.
        # price = convert_string_to_price(data.xpath('//div[@class="yourpricecontainer"]//span/text()').get())
        # TODO: why are we having listpricecontainer? Should we change it?
        price = convert_string_to_price(data.xpath('//div[@class="listpricecontainer"]//span/text()').get())

        # return {
        #     "vendor": self.VENDOR_SLUG,
        #     "product_id": "",
        #     "sku": "",
        #     "name": data["title"],
        #     "url": f"https://www.net32.com/{data['url']}",
        #     "images": [f"https://www.net32.com/media{data['mediaPath']}"],
        #     "price": Decimal(data["retailPrice"]),
        #     "product_vendor_status": "",
        #     "category": "",
        #     "unit": "",
        # }
        product = {
            "vendor": self.VENDOR_SLUG,
            "product_id": "",
            "sku": "",
            "name": "",
            "url": "",
            "images": [],
            "price": price,
            "product_vendor_status": "",
            "category": "",
            "unit": "",
        }
        product.update(base_product)
        product["price"] = price
        product["vendor"] = self.VENDOR_SLUG
        return product

    async def get_cart_page(self) -> Union[Selector, dict]:
        return await self.get_response_as_dom(
            url="https://www.dentalcity.com/widgets-cart/gethtml_shoppingcart",
            headers=GET_CART_HEADERS,
        )

    async def remove_product_from_cart(self, data):
        await self.session.post(
            "https://www.dentalcity.com/widgets-cart/removeitem/", headers=REMOVE_PRODUCT_FROM_CART_HEADERS, json=data
        )

    async def clear_cart(self):
        cart_dom = await self.get_cart_page()
        tasks = []
        for line_id in cart_dom.xpath('//div[@class="shoppinglist"]/ul//input[@name="qty"]/@id').extract():
            data = {"OrderLines": [{"LineID": line_id}]}
            tasks.append(self.remove_product_from_cart(data))

        await asyncio.gather(*tasks)

    async def add_product_to_cart(self, product: types.CartProduct, *args, **kwargs):
        # TODO: We should store sku id to our database
        product_page_dom = await self.get_product_page(
            product_link=product["product"]["url"], headers=GET_PRODUCT_PAGE_HEADERS
        )
        sku_id = product_page_dom.xpath('//input[@name="SkuId"]/@value').get()

        data = {
            "IsFreightApplicable": True,
            "IsShippingDiscountApplicable": False,
            "IsProcessRestrictedDiscounts": False,
            "ResetShipments": False,
            "MarkDiscountsAsApplied": False,
            "IsOrderDiscountApplicable": False,
            "IsLineDiscountApplicable": False,
            "RecalculateUnitPrice": False,
            "RecalculateShippingCharges": False,
            "IsOpportunity": False,
            "IsNewLine": False,
            "IsNewOrder": False,
            "IsCalculateTotal": True,
            "IsCalculateTax": True,
            "WriteInSkuConversionNotificationRequired": False,
            "OverrideExportCompleted": False,
            "OrderEntity": {
                "OrderHeader": {
                    "UpdatedPropertyBag": [
                        "PaymentTotal",
                    ],
                    "orderCount": 0,
                    "groupedOrderTotal": 0,
                    "totalQuantity": 0,
                    "totalDiscount": 0,
                    "CustomerType": 0,
                    "SendEmailOnFraud": False,
                    "RecalculatePrice": False,
                    "RecalculateTax": False,
                    "RecalculateShipping": False,
                    "ShipMethodTaxCategoryId": 0,
                    "IsOrderShipable": True,
                    "UpdateUsername": False,
                    "TrackingNumbers": [],
                    "StoreID": 0,
                    "OrderID": 0,
                    "MiscCharges": 0,
                    "PaymentTotal": 0,
                },
                "OrderLines": [
                    {
                        "UpdatedPropertyBag": [],
                        "RelatedOrderLines": [],
                        "IsNonShippableLinesExists": False,
                        "LineNum": 0,
                        "SkuId": sku_id,
                        "Qty": product["quantity"],
                        "StoreID": 0,
                        "OrderID": 0,
                        "LineID": 0,
                        "MiscCharges": 0,
                    },
                ],
                "WriteInSkuReferences": [],
                "OrderShipments": [],
            },
            "ProcessCheckList": {
                "RunHoldCheckProcess": True,
                "RunFraudCheckProcess": True,
                "RunApprovalCheckProcess": True,
                "RunAggregateOrdeLineStatusCheckProcess": True,
                "PaymentProcess": "Authorize",
            },
            "DesiredStatus": {
                "DocumentStatusId": 0,
                "OrderStatusId": 0,
            },
            "DesiredQuoteStatus": {
                "DocumentStatusId": 0,
                "QuoteStatusId": 0,
            },
            "DesiredOpportunityStatus": {
                "DocumentStatusId": 0,
                "OpportunityStatusId": 0,
            },
        }
        await self.session.post(
            "https://www.dentalcity.com/cart/addtocart", headers=ADD_PRODUCT_TO_CART_HEADERS, json=data
        )

    async def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass

    async def get_product(self, product: types.Product, login_required: bool = True, semaphore: asyncio.Semaphore = None):
        try:
            login_info = await self.get_login_data()
        except Exception as e:
            logger.debug("Got login data exception: %s", e)

        logger.debug("Got logger data: %s", login_info)
        scraper = cloudscraper.create_scraper()
        if login_info:
            logger.debug("Logging in...")
            resp = scraper.post(login_info["url"], headers=login_info["headers"], data=login_info["data"])

            if resp.status_code != 200:
                content = await resp.text
                logger.debug("Got %s status, content = %s", resp.status_code, content)
                raise errors.VendorAuthenticationFailed()
            else:
                headers = getattr(self, "GET_PRODUCT_PAGE_HEADERS")
                response = scraper.get(url=product["url"], headers=headers)
                text = response.text
                dom = Selector(text=text)
                product_detail = self.serialize(product, dom)
                return product_detail
