import asyncio
from typing import Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.vendor_clients.headers.dental_city import (
    ADD_PRODUCT_TO_CART_HEADERS,
    GET_CART_HEADERS,
    GET_PRODUCT_PAGE_HEADERS,
    LOGIN_HEADERS,
    LOGIN_PAGE_HEADERS,
    REMOVE_PRODUCT_FROM_CART_HEADERS,
)
from apps.vendor_clients.sync_clients import BaseClient
from apps.vendor_clients.types import CartProduct, LoginInformation


class DentalCityClient(BaseClient):
    VENDOR_SLUG = "dental_city"

    def get_login_data(self, *args, **kwargs) -> LoginInformation:
        self.session.get("https://www.dentalcity.com/account/login", headers=LOGIN_PAGE_HEADERS)
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

    def check_authenticated(self, response: ClientResponse) -> bool:
        text = response.text
        dom = Selector(text=text)
        login_success = dom.xpath("//input[@id='Message']/@value").get()
        return login_success == "success"

    def get_cart_page(self) -> Union[Selector, dict]:
        return self.get_response_as_dom(
            url="https://www.dentalcity.com/widgets-cart/gethtml_shoppingcart",
            headers=GET_CART_HEADERS,
        )

    def remove_product_from_cart(self, data):
        self.session.post(
            "https://www.dentalcity.com/widgets-cart/removeitem/", headers=REMOVE_PRODUCT_FROM_CART_HEADERS, json=data
        )

    def clear_cart(self):
        cart_dom = self.get_cart_page()
        tasks = []
        for line_id in cart_dom.xpath('//div[@class="shoppinglist"]/ul//input[@name="qty"]/@id').extract():
            data = {"OrderLines": [{"LineID": line_id}]}
            tasks.append(self.remove_product_from_cart(data))

        asyncio.gather(*tasks)

    def add_product_to_cart(self, product: CartProduct, *args, **kwargs):
        # TODO: We should store sku id to our database
        product_page_dom = self.get_product_page(
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
        self.session.post("https://www.dentalcity.com/cart/addtocart", headers=ADD_PRODUCT_TO_CART_HEADERS, json=data)

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        pass
