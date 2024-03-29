import asyncio
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from scrapy import Selector

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.errors import VendorAuthenticationFailed
from apps.scrapers.headers.safco import (
    ADD_TO_CART_HEADER,
    CART_HEADER,
    CHECKOUT_HEADER,
    HOME_HEADER,
    LOGIN_HEADER,
    LOGIN_HOOK_HEADER,
    ORDER_HISTORY_HEADER,
    PLACE_ORDER_HEADER,
    SURVEY_HEADER,
)
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.scrapers.utils import semaphore_coroutine
from apps.types.orders import CartProduct
from apps.types.scraper import InvoiceFormat, InvoiceType, LoginInformation

logger = logging.getLogger(__name__)


def clean_text(xpath, dom):
    try:
        text = re.sub(r"\s+", " ", " ".join(dom.xpath(xpath).extract())).strip()
        return text
    except Exception:
        return None


class SafcoScraper(Scraper):
    BASE_URL = "https://www.safcodental.com/"
    INVOICE_TYPE = InvoiceType.PDF_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_VENDOR_FORMAT

    async def _get_login_data(self, *args, **kwargs) -> LoginInformation:
        async with self.session.get(url=f"{self.BASE_URL}/?ref=sir", headers=HOME_HEADER):
            return {
                "url": f"{self.BASE_URL}/ajax/fn_signInJs.html",
                "headers": LOGIN_HEADER,
                "data": {
                    "si_an": self.username,
                    "si_ph": self.password,
                    "lform_title": "Welcome!",
                    "showCreateAccount": "",
                    "signInId": "rSi",
                    "showSiFormHeading": "Y",
                    "showNewDesign": "Y",
                    "redirect": "/",
                    "requestType": "json",
                    "sourcePage": "https://www.safcodental.com/",
                },
            }

    async def login(self, username: Optional[str] = None, password: Optional[str] = None):
        login_info = await self._get_login_data()
        logger.debug("Got logger data: %s", login_info)
        if login_info:
            async with self.session.post(
                url=login_info["url"], headers=login_info["headers"], data=login_info["data"]
            ) as resp:
                if not resp.ok:
                    raise VendorAuthenticationFailed()
                data = {
                    "contactFields": {
                        "email": login_info["data"]["si_an"],
                    },
                    "formSelectorClasses": ".login-form",
                    "formSelectorId": "",
                    "formValues": {},
                    "labelToNameMap": {},
                    "pageTitle": "Dental Supplies and Products | Safco Dental Supply",
                    "pageUrl": "https://www.safcodental.com/?ref=sir&ref=sor",
                    "portalId": 21944014,
                    "type": "SCRAPED",
                    "version": "collected-forms-embed-js-static-1.315",
                    "collectedFormClasses": "login-form",
                    "collectedFormAction": "ajax/fn_signInJs.html",
                }
                async with self.session.post(
                    url="https://forms.hubspot.com/collected-forms/submit/form", headers=LOGIN_HOOK_HEADER, json=data
                ) as resp:
                    if not resp.ok:
                        raise VendorAuthenticationFailed()
                    async with self.session.get(url=f"{self.BASE_URL}", headers=HOME_HEADER) as resp:
                        if not resp.ok:
                            raise VendorAuthenticationFailed()
                        if hasattr(self, "after_login_hook"):
                            await self.after_login_hook(resp)
                        logger.info("Successfully logged in")
                    return resp.cookies

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
        vendor_order_detail = VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
            total_amount=Decimal(subtotal_manual),
            payment_method="",
            shipping_address="",
            reduction_amount=Decimal(subtotal_manual),
        )
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
            },
        }

    async def add_products_to_cart(self, products):
        headers = ADD_TO_CART_HEADER
        data = {
            "refValue": "ait",
            "addToCartRedirect": "",
            "selectedSearchCat": "",
            "addToCart_qop": "Y",
            "respondJson": "true",
            "itemSource": "WEB-CT-PP",
        }

        for index, product in enumerate(products):
            data[f"items[{index}][qty]"] = product["quantity"]
            data[f"items[{index}][itemNumber]"] = product["product_id"]

        response = await self.session.post(
            "https://www.safcodental.com/ajax/fn_updateQop.html", headers=headers, data=data
        )
        if not response.ok:
            raise ValueError("Adding products to cart is failed somehow")
        logger.debug("Products are added to cart page successfully!")

    async def clear_cart(self):
        headers = CART_HEADER
        cart_get_url = "https://www.safcodental.com/shopping-cart?ref=h"
        async with self.session.get(cart_get_url, headers=headers) as resp:
            if not resp.ok:
                raise ValueError("Failed to reach the cart page")

            cart_dom = Selector(text=await resp.text())
            data = {
                "updateOp": "Y",
                "redirection": "5",
            }
            product_rows = cart_dom.xpath(
                '//div[@class="list-body"]//div[@class="item-details"]//div[@class="item-detail q"]'
            )

            if not product_rows:
                logger.debug("Cart is already Empty")
                return

            for index, product_row in enumerate(product_rows):
                data[f"items[{index}][itemNumber]"] = product_row.xpath(
                    './input[contains(@name, "itemNumber")]/@value'
                ).get()
                data[f"items[{index}][seqw]"] = product_row.xpath('./input[contains(@name, "seqw")]/@value').get()
                data[f"items[{index}][qty]"] = product_row.xpath('./input[contains(@name, "qty")]/@value').get()
                data[f"items[{index}][delete]"] = "Y"

            response = await self.session.post("https://www.safcodental.com/shopping-cart", headers=headers, data=data)
            logger.debug(f"Cart clean result: {response.ok}")

    async def checkout(self):
        headers = CHECKOUT_HEADER

        async with self.session.get(
            "https://www.safcodental.com/billing-and-shipping-info.html", headers=headers
        ) as resp:
            if not resp.ok:
                raise ValueError("Fetching checkout page is failed!")

            checkout_dom = Selector(text=await resp.text())

            billing_adress = clean_text('//div[@id="shipAddress"]/p//text()', checkout_dom)
            if "P:" in billing_adress:
                billing_adress = billing_adress.split("P:")[0]
            logger.debug(f"-- BILLING ADDRESS: {billing_adress}\n")

            shipping_adress = billing_adress
            logger.debug(f"-- SHIPPING ADDRESS: {shipping_adress}\n")

            shipping_method = checkout_dom.xpath('//input[@name="shipmentMethod"][@checked="checked"]/@value').get()
            logger.debug(f"-- Shipping METHOD: {shipping_method}\n")

            payment_info = "Bill me"
            logger.debug(f"-- PAYMENT METHOD: {payment_info}\n")

            subtotal = clean_text(
                '//div[@id="orderTotals"]/div[@class="leftOrderTotals"][contains(text(), "Subtotal")]'
                "/following-sibling::div[1]//text()",
                checkout_dom,
            )
            logger.debug(f"-- SUBTOTAL: {subtotal}\n")

            tax = clean_text(
                '//div[@id="orderTotals"]/div[@class="leftOrderTotals"][contains(text(), "Tax:")]'
                "/following-sibling::div[1]//text()",
                checkout_dom,
            )
            logger.debug(f"-- TAX: {tax}\n")

            shipping = clean_text(
                '//div[@id="orderTotals"]/div[@class="leftOrderTotals"][contains(text(), "Shipping")]'
                "/following-sibling::div[1]//text()",
                checkout_dom,
            )
            logger.debug(f"-- SHIPPING: {shipping}\n")

            total = clean_text('//span[@id="amountDueTotal"]//text()', checkout_dom)
            if total:
                total = f"${total}"
            logger.debug(f"-- Grand Total: {total}\n")

            return checkout_dom

    async def skip_survey(self):
        headers = SURVEY_HEADER
        params = {"ref": "so"}
        data = {
            "refValue": "sksb",
            "updateSurvey": "Y",
            "survey_question_1": "Do you currently provide patients with giveaways "
            "(bags, toothbrushes, etc.) with your name and/or "
            "practice name printed on them?",
            "survey_question_2": "If so, which types of items do you provide?",
            "survey_answer_2": "",
            "survey_question_3": "If Safco were to offer such services, would you be "
            "interested in purchasing them to help brand "
            "/ market your practice to patients?",
            "formSubmit": "Y",
        }
        response = await self.session.post(
            url="https://www.safcodental.com/survey.html", headers=headers, params=params, data=data
        )
        if not response.ok:
            raise ValueError("Skip survey is failed somehow!")
        return response

    async def place_order(self, checkout_dom):
        headers = PLACE_ORDER_HEADER
        billing_form = checkout_dom.xpath('//form[@id="billingInfoForm"]')
        data = {
            "formSubmit": billing_form.xpath('.//input[@name="formSubmit"]/@value').get(),
            "updateAddressInfo": billing_form.xpath('.//input[@name="updateAddressInfo"]/@value').get(),
            "scr_country": billing_form.xpath('.//input[@name="scr_country"]/@value').get(),
            "useForShipping": billing_form.xpath('.//input[@name="useForShipping"]/@value').get(),
            "addressType": billing_form.xpath('.//input[@name="addressType"]/@value').get(),
            "safco_web_token": billing_form.xpath('.//input[@name="safco_web_token"]/@value').get(),
            "updateBillingInfo": billing_form.xpath('.//input[@name="updateBillingInfo"]/@value').get(),
            "scr_billCountry": billing_form.xpath('.//input[@name="scr_billCountry"]/@value').get(),
            "scr_billDentistType": billing_form.xpath('.//input[@name="scr_billDentistType"]/@value').get(),
            "scr_billDL": billing_form.xpath('.//input[@name="scr_billDL"]/@value').get(),
            "scr_billDLExpires": billing_form.xpath('.//input[@name="scr_billDLExpires"]/@value').get(),
            "scr_billNPI": billing_form.xpath('.//input[@name="scr_billNPI"]/@value').get(),
            "redirectPage": billing_form.xpath('.//input[@name="redirectPage"]/@value').get(),
            "validation": billing_form.xpath('.//input[@name="validation"]/@value').get(),
            "addressList_0_csconr": billing_form.xpath('.//input[@name="addressList_0_csconr"]/@value').get(),
            "addressList_0_cscsnr": billing_form.xpath('.//input[@name="addressList_0_cscsnr"]/@value').get(),
            "addressList_0_csnam": billing_form.xpath('.//input[@name="addressList_0_csnam"]/@value').get(),
            "addressList_0_csnam2": billing_form.xpath('.//input[@name="addressList_0_csnam2"]/@value').get(),
            "addressList_0_csadr1": billing_form.xpath('.//input[@name="addressList_0_csadr1"]/@value').get(),
            "addressList_0_csadr2": billing_form.xpath('.//input[@name="addressList_0_csadr2"]/@value').get(),
            "addressList_0_cscity": billing_form.xpath('.//input[@name="addressList_0_cscity"]/@value').get(),
            "addressList_0_csst": billing_form.xpath('.//input[@name="addressList_0_csst"]/@value').get(),
            "addressList_0_cszip": billing_form.xpath('.//input[@name="addressList_0_cszip"]/@value').get(),
            "addressList_0_csphn1": billing_form.xpath('.//input[@name="addressList_0_csphn1"]/@value').get(),
            "addressConrCsnr": billing_form.xpath('.//input[@name="addressConrCsnr"]/@value').get(),
            "maxIndex": billing_form.xpath('.//input[@name="maxIndex"]/@value').get(),
            "shipmentMethod": billing_form.xpath('.//input[@name="shipmentMethod"][@checked="checked"]/@value').get(),
            "defaultPayment": billing_form.xpath('.//input[@name="defaultPayment"]/@value').get(),
            "paymentMethod": "AR",
            "scr_billEmail": billing_form.xpath('.//input[@name="scr_billEmail"]/@value').get(),
            "scr_billOrderPlacer": f'Ordo Order ({datetime.strftime(datetime.now(), "%m/%d/%Y")})',
            "scr_orderMessage": "",
            "codAmount": billing_form.xpath('.//input[@name="codAmount"]/@value').get(),
            "codThreshold": billing_form.xpath('.//input[@name="codThreshold"]/@value').get(),
            "standardShippingDefault": billing_form.xpath('.//input[@name="standardShippingDefault"]/@value').get(),
            "shippingDefault": billing_form.xpath('.//input[@name="shippingDefault"]/@value').get(),
            "amountTotalDefault": billing_form.xpath('.//input[@name="amountTotalDefault"]/@value').get(),
            "amountDueMinusShipping": billing_form.xpath('.//input[@name="amountDueMinusShipping"]/@value').get(),
            "amountDuePlusShipping": billing_form.xpath('.//input[@name="amountDuePlusShipping"]/@value').get(),
            "submitBnS": billing_form.xpath('.//input[@name="submitBnS"]/@value').get(),
        }
        async with self.session.post(
            "https://www.safcodental.com/billing-and-shipping-info.html", headers=headers, data=data
        ) as resp:
            if not resp.ok:
                raise ValueError("Placing order is failed somehow!")
            if "survey.html" in str(resp.url):
                survey_response = await self.skip_survey()
                dom = Selector(text=await survey_response.text())
            else:
                dom = Selector(text=await resp.text())
            order_id = clean_text(
                '//table//td[contains(text(), "Order Number:")]' '/following-sibling::td[@class="c2"]//text()', dom
            )
            logger.debug(f"===Order ID: {order_id}")
            return order_id

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False):
        try:
            if fake:
                return {"order_type": msgs.ORDER_TYPE_ORDO}

            await self.clear_cart()
            await self.add_products_to_cart(products)

            checkout_dom = await self.checkout()
            order_id = await self.place_order(checkout_dom)

            return {
                "order_id": order_id,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
        except Exception:
            logger.error("safco/confirm_order Except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = VendorOrderDetail(
                retail_amount=Decimal(0),
                savings_amount=Decimal(0),
                subtotal_amount=Decimal(subtotal_manual),
                shipping_amount=Decimal(0),
                tax_amount=Decimal(0),
                total_amount=Decimal(subtotal_manual),
                reduction_amount=Decimal(subtotal_manual),
                payment_method="",
                shipping_address="",
            )
            return {
                **vendor_order_detail.to_dict(),
                **self.vendor.to_dict(),
                "order_id": f"{uuid.uuid4()}",
                "order_type": msgs.ORDER_TYPE_PROCESSING,
            }

    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        sem = asyncio.Semaphore(value=2)
        if perform_login:
            await self.login()

        url = f"{self.BASE_URL}/my-account/my-orders.html?ref=h"
        async with self.session.get(url, headers=ORDER_HISTORY_HEADER) as resp:
            response_dom = Selector(text=await resp.text())
            orders_doms = response_dom.xpath('//div[@class="order-info orderInfoTable"]')
            tasks = (self.get_order(sem, order_dom, office) for order_dom in orders_doms)
            orders = await asyncio.gather(*tasks, return_exceptions=True)

        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]

    @semaphore_coroutine
    async def get_order(self, sem, order_dom, office=None, **kwargs):
        order_item = {
            "currency": "USD",
            "products": [],
        }
        order_header_ele = order_dom.xpath('.//div[@class="orderHeaderInfo"]')
        order_value_ele = order_dom.xpath('.//div[@class="right-side-shipments"]')
        order_id = self.extract_first(
            order_header_ele,
            './/li/span[@class="attribute-txt"][contains(text(), "Order number")]/following-sibling::'
            'span[@class="attribute-value"]//text()',
        )
        order_item["order_id"] = order_id

        order_date = self.extract_first(order_header_ele, './/div[contains(@class, "order-date")]//text()')
        order_date = datetime.strptime(order_date, "%B %d, %Y")
        order_item["order_date"] = datetime.strftime(order_date, "%Y-%m-%d")

        order_total = self.extract_first(
            order_header_ele,
            './/li/span[@class="attribute-txt"][contains(text(), "Order total")]/following-sibling::'
            'span[@class="attribute-value"]//text()',
        )
        order_item["total_amount"] = order_total

        payment_method = self.extract_first(
            order_header_ele,
            './/li/span[@class="attribute-txt"][contains(text(), "Payment method")]/following-sibling::'
            'span[@class="attribute-value"]//text()',
        )
        order_item["payment_method"] = payment_method

        order_status = self.extract_first(
            order_value_ele, './/div[@class="shipmentInfo"]//div[contains(@class, "delivered")]//text()'
        )
        order_item["status"] = order_status

        invoice_link = order_value_ele.xpath('.//a[contains(text(), "View invoice")]/@href').get()
        if invoice_link:
            invoice_link = f"https://www.safcodental.com/{invoice_link}"
        order_item["invoice_link"] = invoice_link

        track_link = order_value_ele.xpath('.//a[contains(text(), "Track this shipment")]/@href').get()
        if track_link:
            track_link = f"https://www.safcodental.com/{track_link}"
        order_item["track_link"] = track_link

        prim = order_value_ele.xpath('.//div[@class="shipmentItems"][@id]/@id').get()
        prim = prim.split("-")[-1].strip() if prim else ""
        if prim:
            async with self.session.get(
                f"https://www.safcodental.com/ajax/fn_getShipmentItems.html?ordn={order_id}&prim={prim}",
                headers=ORDER_HISTORY_HEADER,
            ) as resp:
                order_detail_dom = Selector(text=await resp.text())
                for order_product in order_detail_dom.xpath('//div[contains(@class, "shipmentItemTable")]/div'):
                    order_product_item = {
                        "product": {
                            "product_id": "",
                            "sku": "",
                            "name": "",
                            "description": "",
                            "url": "",
                            "images": [],
                            "category": "",
                            "price": "",
                            "vendor": {},
                        },
                        "quantity": 0,
                        "unit_price": 0,
                        "status": "",
                    }

                    product_sku = clean_text('.//div[@class="itemNumber"]/a//text()', order_product)
                    if not product_sku:
                        continue
                    order_product_item["product"]["sku"] = product_sku
                    order_product_item["product"]["product_id"] = product_sku

                    product_title = clean_text('.//div[@class="description"]//text()', order_product)
                    order_product_item["product"]["name"] = product_title

                    product_qty = clean_text('.//div[@class="qty"]//text()', order_product)
                    order_product_item["qty"] = int(product_qty)

                    order_item["products"].append(order_product_item)
        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order_item))
        return order_item
