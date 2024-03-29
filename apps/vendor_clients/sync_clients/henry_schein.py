import datetime
import json
from collections import defaultdict
from typing import Dict, List, Optional, Union

from aiohttp import ClientResponse
from scrapy import Selector

from apps.common.utils import (
    concatenate_strings,
    convert_string_to_price,
    strip_whitespaces,
)
from apps.vendor_clients import types
from apps.vendor_clients.headers.henry_schein import (
    ADD_PRODUCTS_TO_CART_HEADERS,
    CHECKOUT_HEADER,
    CLEAR_CART_HEADERS,
    GET_PRODUCT_PRICES_HEADERS,
    LOGIN_HEADERS,
)
from apps.vendor_clients.sync_clients.base import BaseClient


class HenryScheinClient(BaseClient):
    VENDOR_SLUG = "henry_schein"

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        """Provide login credentials and additional data along with headers"""
        with self.session.get("https://www.henryschein.com/us-en/dental/Default.aspx") as resp:
            text = resp.text
            n = text.split("var _n =")[1].split(";")[0].strip(" '")
        self.session.headers.update({"n": n})
        return {
            "url": "https://www.henryschein.com/webservices/LoginRequestHandler.ashx",
            "headers": LOGIN_HEADERS,
            "data": {
                "username": self.username,
                "password": self.password,
                "did": "dental",
                "searchType": "authenticateuser",
                "culture": "us-en",
            },
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        """Check if whether session is authenticated or not"""
        res = response.json()
        return res.get("IsAuthenticated", False)

    def get_cart_page(self) -> Union[Selector, dict]:
        """Get cart page in order to get products in cart"""
        return self.get_response_as_dom(url="https://www.henryschein.com/us-en/Shopping/CurrentCart.aspx")

    def get_checkout_products_sensitive_data(self, dom: Selector) -> dict:
        data = {}
        for i, product_dom in enumerate(
            dom.xpath("//div[@id='ctl00_cphMainContentHarmony_ucOrderCartShop_pnlCartDetails']/ol/li")
        ):
            product_index = f"{i + 1:02d}"
            for key in [
                "$ucProductDetailsForEnhancedView$hiddenProductId",
                "$ucProductDetailsForEnhancedView$hiddenProductAvailabilityCode",
                "$ucProductDetailsForEnhancedView$hiddenInventoryAvailabilityCode",
                "$ucProductDetailsForEnhancedView$hiddenImgProduct",
                "$hdnPriceLabel1",
                "$hdnPriceLabel2",
                "$oldQty",
                "$txtQuantity",
                "$hdnItemId",
                "$ucProductDetailsForEnhancedView$hiddenUom",
            ]:
                key = f"ctl00$cphMainContentHarmony$ucOrderCartShop$rptBasket$ctl{product_index}{key}"
                data[key] = product_dom.xpath(f'.//input[@name="{key}"]/@value').get()
        return data

    def clear_cart(self):
        # TODO: check if the cart contains products, clear cart only if the cart contains products
        cart_page_dom = self.get_cart_page()
        data = {
            "__LASTFOCUS": "",
            "ctl00_ScriptManager_TSM": ";;System.Web.Extensions, Version=4.0.0.0, Culture=neutral, "
            "PublicKeyToken=31bf3856ad364e35:en-US:f319b152-218f-4c14-829d-050a68bb1a61:ea597d4b:b25378d2",
            "__EVENTTARGET": "ctl00$cphMainContentHarmony$ucOrderActionBarBottomShop$btnClearOrder",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": cart_page_dom.xpath("//input[@name='__VIEWSTATE']/@value").get(),
            "__VIEWSTATEGENERATOR": cart_page_dom.xpath("//input[@name='__VIEWSTATEGENERATOR']/@value").get(),
            "ctl00$ucHeader$ucSearchBarHeaderbar$txtSearch": "",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnKeywordText": "Keywords",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnCategoryText": "Category",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnManufacturerText": "Manufacturer",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnContentResultsText": "Content Result",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnRecommendedProducts": "Recommended products for",
            "ctl00$ucHeader$ucSearchBarHeaderbar$hdnAddText": "Add",
            "ctl00$cphMainContentHarmony$ucOrderTopBarShop$txtItemCode": "",
            "ctl00$cphMainContentHarmony$ucOrderTopBarShop$txtQty": "",
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPurchaseOrder": cart_page_dom.xpath(
                '//input[@name="ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPurchaseOrder"]/@value'
            ).get(),
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPromoCode": cart_page_dom.xpath(
                '//input[@name="ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPromoCode"]/@value'
            ).get(),
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtSpecialInstructions": "",
            "dest": "",
        }
        data.update(self.get_checkout_products_sensitive_data(cart_page_dom))
        self.session.post(
            "https://www.henryschein.com/us-en/Shopping/CurrentCart.aspx", headers=CLEAR_CART_HEADERS, data=data
        )

    def add_products_to_cart(self, products: List[types.CartProduct]):
        item_data_to_add = {"ItemDataToAdd": []}
        for product in products:
            item_data_to_add["ItemDataToAdd"].append(
                {
                    "CheckProductIdForPromoCode": "False",
                    "CheckExternalMapping": "False",
                    "CheckBackOrderStatus": "False",
                    "IsProductInventoryStatusLoaded": "True",
                    "LineItemId": "",
                    "ProductId": product["product"]["product_id"],
                    "Qty": product["quantity"],
                    "Uom": product["product"]["unit"],
                }
            )

        data = {
            "ItemArray": json.dumps(item_data_to_add),
            "searchType": "5",
            "did": "dental",
            "catalogName": "B_DENTAL",
            "endecaCatalogName": "DENTAL",
            "culture": "us-en",
        }

        self.session.post(
            "https://www.henryschein.com/webservices/JSONRequestHandler.ashx",
            headers=ADD_PRODUCTS_TO_CART_HEADERS,
            data=data,
        )

    def checkout(self):
        checkout_time = datetime.date.today()
        cart_page_dom = self.get_cart_page()
        data = {
            "__LASTFOCUS": "",
            "ctl00_ScriptManager_TSM": ";;System.Web.Extensions, Version=4.0.0.0, Culture=neutral, "
            "PublicKeyToken=31bf3856ad364e35:en-US:f319b152-218f-4c14-829d-050a68bb1a61:ea597d4b:b25378d2",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": cart_page_dom.xpath("//input[@name='__VIEWSTATE']/@value").get(),
            "__VIEWSTATEGENERATOR": cart_page_dom.xpath("//input[@name='__VIEWSTATEGENERATOR']/@value").get(),
            "ctl00$ucHeader$ucSearchBarHeaderbar$txtSearch": "",
            "ctl00$cphMainContentHarmony$ucOrderActionBarBottomShop$btnCheckout": cart_page_dom.xpath(
                "//input[@name='ctl00$cphMainContentHarmony$ucOrderActionBarBottomShop$btnCheckout']/@value"
            ).get(),
            "layout": "on",
            "ctl00$cphMainContentHarmony$ucOrderTopBarShop$txtItemCode": "",
            "ctl00$cphMainContentHarmony$ucOrderTopBarShop$txtQty": "",
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPurchaseOrder": (
                f'{checkout_time.strftime("%m/%d/%Y")} - Ordo Order'
            ),
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtPromoCode": "",
            "ctl00$cphMainContentHarmony$ucOrderFinalsShop$txtSpecialInstructions": "",
            "dest": "",
        }

        data.update(self.get_checkout_products_sensitive_data(cart_page_dom))

        headers = CHECKOUT_HEADER.copy()
        headers["referer"] = "https://www.henryschein.com/us-en/Shopping/CurrentCart.aspx"
        with self.session.post(
            "https://www.henryschein.com/us-en/Shopping/CurrentCart.aspx", headers=headers, data=data
        ) as resp:
            response_dom = Selector(text=resp.text)
            if len(response_dom.xpath("//div[@id='MessagePanel']/div[contains(@class, 'informational')]")):
                return self.checkout()
            else:
                return response_dom

    def review_checkout(self, checkout_dom: Selector, shipping_method: Optional[str] = None):
        for shipping_method_option in checkout_dom.xpath(
            "//select[@name='ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ddlShippingMethod']/option"
        ):
            if shipping_method_option.xpath("./text").get() == shipping_method:
                shipping_method_value = shipping_method_option.attrib["value"]
                break
        else:
            shipping_method_value = checkout_dom.xpath(
                "//select[@name='ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ddlShippingMethod']"
                "/option[@selected]/@value"
            ).get()

        data = {
            "ctl00_ScriptManager_TSM": ";;System.Web.Extensions, Version=4.0.0.0, Culture=neutral, "
            "PublicKeyToken=31bf3856ad364e35:en-US:f319b152-218f-4c14-829d-050a68bb1a61:ea597d4b:b25378d2",
            "__EVENTTARGET": "ctl00$cphMainContentHarmony$hylNext",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": checkout_dom.xpath("//input[@name='__VIEWSTATE']/@value").get(),
            "__VIEWSTATEGENERATOR": checkout_dom.xpath("//input[@name='__VIEWSTATEGENERATOR']/@value").get(),
            "SideMenuControl1000txtItemCodeId": "",
            "SideMenuControl1000txtItemQtyId": "",
            "ctl00$ucHeader$ucSearchBarHeaderbar$txtSearch": "",
            "SideMenuControl1000txtItemCodeId9": "",
            "SideMenuControl1000txtItemQtyId9": "",
            "ctl00_cpAsideMenu_AsideMenu_SideMenuControl1000txtItemCodeId": "",
            "ctl00_cpAsideMenu_AsideMenu_SideMenuControl1000txtItemQtyId": "",
            "layout": "on",
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ddlShippingMethod": shipping_method_value,
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ddlPaymentMethod": checkout_dom.xpath(
                "//select[@name='ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ddlPaymentMethod']"
                "/option[@selected]/@value"
            ).get(),
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$hiddenModifyLink": (
                "https://www.henryschein.com/us-en/checkout/CheckoutCreditCard.aspx?action=0&ccid={0}&overlay=true"
            ),
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$txtPo": checkout_dom.xpath(
                "//input[@id='ctl00_cphMainContentHarmony_ucOrderPaymentAndOptionsShop_txtPo']/@value"
            ).get(),
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$": "rbnNoDelayNoRecurring",
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$dpStartDate": (
                checkout_dom.xpath(
                    "//input[@name='ctl00$cphMainContentHarmony"
                    "$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$dpStartDate']/@value"
                ).get()
            ),
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$ddlFrequency": "Weekly",
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$dpEndDate": (
                checkout_dom.xpath(
                    "//input[@name='ctl00$cphMainContentHarmony"
                    "$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$dpEndDate']/@value"
                ).get()
            ),
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$ddlTotal": "Select One",
            "ctl00$cphMainContentHarmony$ucOrderPaymentAndOptionsShop$ucSchedulingOptions$checkoutType": "Normal",
            "dest": "",
        }

        params = {
            "PaymentIndex": "0",
        }

        headers = CHECKOUT_HEADER.copy()
        headers["referer"] = "https://www.henryschein.com/us-en/Checkout/BillingShipping.aspx"
        with self.session.post(
            "https://www.henryschein.com/us-en/Checkout/BillingShipping.aspx",
            headers=headers,
            params=params,
            data=data,
        ) as resp:
            return Selector(text=resp.text)

    def review_order(self, review_checkout_dom: Selector) -> types.VendorOrderDetail:
        subtotal_amount = convert_string_to_price(
            review_checkout_dom.xpath(
                "//div[@id='ctl00_cphMainContentHarmony_divOrderSummarySubTotal']/strong//text"
            ).get()
        )
        shipping_amount = convert_string_to_price(
            review_checkout_dom.xpath(
                "//div[@id='ctl00_cphMainContentHarmony_divOrderSummaryShipping']/strong//text"
            ).get()
        )
        tax_amount = convert_string_to_price(
            review_checkout_dom.xpath("//div[@id='ctl00_cphMainContentHarmony_divOrderSummaryTax']/strong//text").get()
        )
        total_amount = convert_string_to_price(
            review_checkout_dom.xpath(
                "//div[@id='ctl00_cphMainContentHarmony_divOrderSummaryTotal']/strong//text"
            ).get()
        )
        payment_method = strip_whitespaces(
            review_checkout_dom.xpath(
                "//div[@id='ctl00_cphMainContentHarmony_divOrderSummaryPaymentMethod']/strong//text"
            ).get()
        )
        shipping_address = concatenate_strings(
            review_checkout_dom.xpath(
                "//section[contains(@class, 'order-details')]"
                "//section[contains(@class, 'half')]/div[@class='half'][1]//address/p/span[2]/text",
            ).extract(),
            delimeter=", ",
        )

        return types.VendorOrderDetail(
            subtotal_amount=subtotal_amount,
            shipping_amount=shipping_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            payment_method=payment_method,
            shipping_address=shipping_address,
        )

    def checkout_and_review_order(self, shipping_method: Optional[str] = None) -> dict:
        """Review the order without making real order"""
        checkout_dom = self.checkout()
        review_checkout_dom = self.review_checkout(checkout_dom, shipping_method)
        order_detail = self.review_order(review_checkout_dom)
        return {
            "order_detail": order_detail,
            "review_checkout_dom": review_checkout_dom,
        }

    def place_order(self, *args, **kwargs) -> str:
        review_checkout_dom = kwargs.get("review_checkout_dom")
        headers = CHECKOUT_HEADER.copy()
        headers["referer"] = "https://www.henryschein.com/us-en/Checkout/OrderReview.aspx"

        data = {
            "ctl00_ScriptManager_TSM": ";;System.Web.Extensions, Version=4.0.0.0, Culture=neutral, "
            "PublicKeyToken=31bf3856ad364e35:en-US:f319b152-218f-4c14-829d-050a68bb1a61:ea597d4b:b25378d2",
            "__EVENTTARGET": "ctl00$cphMainContentHarmony$lnkNextShop",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": review_checkout_dom.xpath("//input[@name='__VIEWSTATE']/@value").get(),
            "__VIEWSTATEGENERATOR": review_checkout_dom.xpath("//input[@name='__VIEWSTATEGENERATOR']/@value").get(),
            "ctl00_cpAsideMenu_AsideMenu_SideMenuControl1000txtItemCodeId": "",
            "ctl00_cpAsideMenu_AsideMenu_SideMenuControl1000txtItemQtyId": "",
            "layout": "on",
            "dest": "",
        }
        data.update(self.get_checkout_products_sensitive_data(review_checkout_dom))

        with self.session.post(
            "https://www.henryschein.com/us-en/Checkout/OrderReview.aspx", headers=headers, data=data
        ) as resp:
            response = resp.text
            res_data = response.split("dataLayer.push(", 1)[1].split(");")[0]
            res_data = res_data.replace("'", '"')
            res_data = json.loads(res_data)
            return res_data["ecommerce"]["purchase"]["actionField"]["id"]

    def _get_products_prices(self, products: List[types.Product], *args, **kwargs) -> Dict[str, types.ProductPrice]:
        """get vendor specific products prices"""
        # keyword = products[0]["name"][:3]
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
        # headers["referer"] = f"https://www.henryschein.com/us-en/Search.aspx?searchkeyWord={keyword}"
        product_prices = defaultdict(dict)
        with self.session.post(
            "https://www.henryschein.com/webservices/JSONRequestHandler.ashx",
            data=data,
            headers=headers,
        ) as resp:
            res = resp.json()
            for product_price in res["ItemDataToPrice"]:
                # if product_price["InventoryStatus"] in ["Unavailable", "Error", "Discontinued", "Unknown"]:
                #     continue
                product_prices[product_price["ProductId"]]["product_vendor_status"] = product_price["InventoryStatus"]
                product_prices[product_price["ProductId"]]["price"] = convert_string_to_price(
                    product_price["CustomerPrice"]
                )
        return product_prices
