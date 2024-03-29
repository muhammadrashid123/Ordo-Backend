import asyncio
import datetime
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Optional

import scrapy
from aiohttp import ClientResponse
from asgiref.sync import sync_to_async
from scrapy import Selector
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from apps.common import messages as msgs
from apps.common.utils import (
    concatenate_list_as_string,
    convert_string_to_price,
    strip_whitespaces,
)
from apps.scrapers.base import Scraper
from apps.scrapers.schema import Order, VendorOrderDetail
from apps.types.orders import CartProduct
from apps.types.scraper import (
    InvoiceAddress,
    InvoiceFile,
    InvoiceFormat,
    InvoiceInfo,
    InvoiceOrderDetail,
    InvoiceProduct,
    InvoiceType,
    InvoiceVendorInfo,
    ProductSearch,
)

logger = logging.getLogger(__name__)

LOGIN_PAGE_HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}

LOGIN_HEADERS = {
    "Connection": "keep-alive",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Cache-Control": "no-cache",
    "X-Requested-With": "XMLHttpRequest",
    "X-MicrosoftAjax": "Delta=true",
    "sec-ch-ua-platform": '"Windows"',
    "Accept": "*/*",
    "Origin": "https://store.edgeendo.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://store.edgeendo.com/login.aspx",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}
ORDER_HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;"
    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Language": "en-US,en;q=0.9",
}

PRODUCT_DETAIL_HEADER = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/97.0.4692.71 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
    "*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '" Not;A Brand";v="99", "Google Chrome";v="97", "Chromium";v="97"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_content(dom, xpath):
    return re.sub(r"\s+", " ", " ".join(dom.xpath(xpath).extract())).strip()


class EdgeEndoScraper(Scraper):
    INVOICE_TYPE = InvoiceType.HTML_INVOICE
    INVOICE_FORMAT = InvoiceFormat.USE_ORDO_FORMAT
    product_skus = dict()
    sleepAmount = 10
    driver = None
    BASE_URL = "https://store.edgeendo.com"

    def setup_driver(self):
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/80.0.3987.132 Safari/537.36"
        )

        caps = DesiredCapabilities.CHROME
        caps["pageLoadStrategy"] = "eager"
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={user_agent}")
        chrome_options.add_argument("--log-level=3")
        driver = webdriver.Chrome(
            ChromeDriverManager(version="114.0.5735.90").install(),
            options=chrome_options,
            desired_capabilities=caps,
        )
        driver.set_window_size(1920, 1080)
        return driver

    @sync_to_async
    def login(self):
        if not self.driver:
            self.driver = self.setup_driver()

        self.driver.get("https://store.edgeendo.com/account.aspx")
        emailInput = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//input[@name="ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$txtEmail"]')
            )
        )
        emailInput.clear()
        emailInput.send_keys(self.username)
        time.sleep(0.5)

        passInput = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    '//input[@name="ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$txtRestricted"]',
                )
            )
        )
        passInput.clear()
        passInput.send_keys(self.password)
        time.sleep(0.5)

        loginBtn = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//input[@name="ctl00$ctl00$cphMain$cphMain$lfBtoC$btnCustomerLogin"]')
            )
        )

        self.scroll_and_click_element(loginBtn)
        WebDriverWait(self.driver, self.sleepAmount).until(
            EC.presence_of_element_located((By.XPATH, '//p[@class="nextLoginWelcome"]'))
        )

    async def get_login_form(self):
        async with self.session.get(f"{self.BASE_URL}/login.aspx", headers=LOGIN_PAGE_HEADERS) as resp:
            login_dom = Selector(text=await resp.text())
            login_dom.xpath('//input[@name="_TSM_HiddenField_"]/@value').extract()
            hidden_field = login_dom.xpath('//input[@name="_TSM_HiddenField_"]/@value').extract_first()
            event_target = login_dom.xpath('//input[@name="__EVENTTARGET"]/@value').extract_first()
            event_argument = login_dom.xpath('//input[@name="__EVENTARGUMENT"]/@value').extract_first()
            view_state = login_dom.xpath('//input[@name="__VIEWSTATE"]/@value').extract_first()
            view_state_generator = login_dom.xpath('//input[@name="__VIEWSTATEGENERATOR"]/@value').extract_first()
            return {
                "hidden_field": hidden_field,
                "event_target": event_target,
                "event_argument": event_argument,
                "view_state": view_state,
                "view_state_generator": view_state_generator,
            }

    async def _get_login_data(self, *args, **kwargs):
        form = await self.get_login_form()
        return {
            "url": "https://store.edgeendo.com/login.aspx",
            "headers": LOGIN_HEADERS,
            "data": {
                "ctl00$ctl00$tsmScripts": "",
                "_TSM_HiddenField_": form["hidden_field"],
                "__EVENTTARGET": form["event_target"],
                "__EVENTARGUMENT": form["event_argument"],
                "__VIEWSTATE": form["view_state"],
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$txtEmail": self.username,
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$vceValid_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$vceRequired_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$txtRestricted": self.password,
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceRegExp_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceLength_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceRequired_ClientState": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartProductID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartSKUID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartQuantity": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartWriteInIDs": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartWriteInValues": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartBidPrice": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartShipTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartNewShipTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartGiftMessage": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartGiftWrap": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartFulfillmentMethod": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartPickupAt": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartEmailTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartSubscriptionID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartExpressOrder": "",
                "ctl00$ctl00$cphMain$ctl00$hfManualCartPostBack": "",
                "ctl00$ctl00$cphMain$ctl00$hfRemoveCartProductIndex": "",
                "ctl00$ctl00$cphMain$ctl00$hfEditQuantityNewValue": "",
                "ctl00$ctl00$cphMain$ctl00$hfEditQuantityCartProductIndex": "",
                "ctl00$ctl00$cphMain$ctl00$hfReorderID": "",
                "ctl00$ctl00$cphMain$ctl00$hfProductSharingDiscountID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartRefresh": "",
                "__VIEWSTATEGENERATOR": form["view_state_generator"],
                "__ASYNCPOST": "true",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$btnCustomerLogin": "Log In Securely",
            },
        }

    async def _check_authenticated(self, response: ClientResponse) -> bool:
        text = await response.text()
        return "CustomerID" in text

    async def get_product_id(self, link, subname):
        if not link:
            return ""
        async with self.session.get(link, headers=PRODUCT_DETAIL_HEADER) as response:
            dom = scrapy.Selector(text=await response.text())

            sku_xpath = (
                "//table[@class='nextExpressOrderSKUTable']//tr[contains(@class, 'nextExpressOrderRow')"
                " or contains(@class, 'nextExpressOrderAlternateRow')]/td[1][contains(text(), '{subname}')]"
                "/following-sibling::td[1]//text()"
            )
            sku = extract_content(dom, sku_xpath)
            if not sku:
                sku = extract_content(dom, '//meta[@property="og:mpn"]/@content')
            return sku

    async def order_detail(self, order):
        link = order["order_detail_link"]
        self.driver.get(link)
        WebDriverWait(self.driver, self.sleepAmount).until(
            EC.presence_of_all_elements_located((By.XPATH, '//table[contains(@id, "cphMain_cphMain_oltOrderDetail")]'))
        )
        dom = scrapy.Selector(text=self.driver.page_source)
        table = dom.xpath('//tr[@class="nextCartSubtotal"]/..')
        order["subtotal"] = extract_content(
            table, './tr[@class="nextCartSubtotal"]/td[contains(@id, "_tdSubtotalPrice")]//text()'
        )
        order["shipping "] = extract_content(
            table, './tr[@class="nextShipping"]/td[contains(@id, "_tdShippingPrice")]//text()'
        )
        order["tax"] = extract_content(
            table, './tr[@class="nextSalesTax"]/td[contains(@id, "_tdSalesTaxPrice")]//text()'
        )
        shipping_address_content = dom.xpath('//span[contains(@id, "ShipTo_spnAddressDisplay")]//text()').extract()
        shipping_address = [_it.strip() for _it in shipping_address_content if _it.strip()]
        if len(shipping_address) >= 4:
            shipping_address = shipping_address[2:4]
        order["shipping_address"] = order["shipping_address"] = {"address": ", ".join(shipping_address)}

        order["products"] = []
        tracking_link = ""
        for tr in table.xpath("./tr"):
            if tr.xpath("./@class"):
                continue

            subname = extract_content(tr, './/td[3]//span[@class="nextCartAttributes"]//text()')
            product_name = extract_content(tr, './td[3]/span[@class="nextCartProdText"]/a//text()')
            if subname not in product_name:
                product_name = product_name + " (" + subname + ")"
            product_url = extract_content(tr, './td[3]/span[@class="nextCartProdText"]/a/@href')
            product_id = await self.get_product_id(product_url, subname)
            product_status = extract_content(tr, "./td[7]//text()")

            if product_status:
                product = {
                    "product": {
                        "product_id": product_id,
                        "name": product_name,
                        "description": "",
                        "images": [],
                        "category": "",
                        "url": extract_content(tr, './td[3]/span[@class="nextCartProdText"]/a/@href'),
                        "price": extract_content(tr, "./td[6]//text()"),
                        "vendor": self.vendor.to_dict(),
                        "status": extract_content(tr, "./td[7]//text()"),
                    },
                    "quantity": extract_content(tr, "./td[1]//text()"),
                    "unit_price": extract_content(tr, "./td[5]//text()"),
                }
                order["products"].append(product)
            else:
                tracking_number = extract_content(tr, './td[@colspan="7"]/b[last()]//text()')
                if tracking_number:
                    tracking_link = f"https://www.ups.com/track?loc=en_US&tracknum={tracking_number}"

        if tracking_link:
            for product in order["products"]:
                product["tracking_link"] = tracking_link

        return order

    async def get_order(self, order, office=None) -> dict:
        order_dict = await self.order_detail(order=order)
        order_dict.update({"currency": "USD"})

        if office:
            await self.save_order_to_db(office, order=Order.from_dict(order_dict))
        return order

    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        self.driver.get(f"{self.BASE_URL}/account.aspx")
        results = []
        WebDriverWait(self.driver, self.sleepAmount).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, '//table[contains(@id, "cphMain_cphMain_oltOrderList")]//tr[contains(@class, "OrderRow")]')
            )
        )
        dom = scrapy.Selector(text=self.driver.page_source)

        for tr_ele in dom.xpath(
            '//table[contains(@id, "cphMain_cphMain_oltOrderList")]//tr[contains(@class, "OrderRow")]'
        ):
            order_history = dict()
            order_history["order_id"] = extract_content(tr_ele, "./td[1]/span[@id]//text()")
            logger.info(f'Order ID: {order_history["order_id"]}')
            order_history["order_date"] = datetime.datetime.strptime(
                extract_content(tr_ele, "./td[2]//text()"), "%m/%d/%Y"
            ).date()
            order_history["status"] = extract_content(tr_ele, "./td[3]//text()")
            order_history["billing_status"] = extract_content(tr_ele, "./td[4]//text()")
            order_history["total_amount"] = extract_content(tr_ele, "./td[5]//text()")
            order_detail_link = extract_content(tr_ele, "./td[1]/span[@id]/a/@href")
            order_history["order_detail_link"] = order_detail_link
            order_history[
                "invoice_link"
            ] = f"https://store.edgeendo.com/accountinvoice.aspx?RowID={order_history['order_id']}"
            order_history = await self.get_order(order_history, office)
            results.append(order_history)

        return results

    async def _search_products(
        self, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price", office_id=None
    ) -> ProductSearch:
        return await self._search_products_from_table(query, page, min_price, max_price, sort_by, office_id)

    # extract text
    def textParser(self, element):
        text = element.get_attribute("textContent")
        return text.strip() if text else ""

    def scroll_and_click_element(self, element: WebElement):
        # self.driver.execute_script("arguments[0].scrollIntoView(false);", element)
        try:
            element.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", element)

        time.sleep(0.5)

    def wait_cart_action(self):
        while True:
            progress_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        '//div[contains(@id, "upoCartData_uprProgress")]',
                    )
                )
            )
            progress_style = progress_ele.get_attribute("style")
            if "block" in progress_style:
                time.sleep(3)
                break

    @sync_to_async
    def add_to_cart(self, products):
        for product in products:
            self.driver.get(product["product_url"])
            sku = product["product_id"]
            WebDriverWait(self.driver, self.sleepAmount).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        '//td[@id="ctl00_ctl00_ctl00_cphMain_cphMain_tdMain"]',
                    )
                )
            )
            if "nextExpressOrderDetailContainer" in self.driver.page_source:
                open_tab_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//a[@id="__tab_ctl00_ctl00_ctl00_cphMain_cph'
                            'Main_cphMain_pdtProduct_tcTabs_tpReviewsQuestions3"]',
                        )
                    )
                )
                self.scroll_and_click_element(open_tab_ele)

                while True:
                    quantity_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                f'//table[@class="nextExpressOrderSKUTable"]//tr/td[2][contains(text(), "{sku}")]'
                                '/following-sibling::td/span/input[@title="Enter Quantity"]',
                            )
                        )
                    )
                    quantity = int(quantity_ele.get_attribute("value"))

                    if quantity == product["quantity"]:
                        add_to_cart_btn = WebDriverWait(self.driver, self.sleepAmount).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, '//div[@class="nextExpressOrderATC"]//input[@type="submit"]')
                            )
                        )
                        self.scroll_and_click_element(add_to_cart_btn)
                        time.sleep(2)
                        self.wait_cart_action()
                        break
                    else:
                        plus_quantity_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                            EC.element_to_be_clickable(
                                (
                                    By.XPATH,
                                    f'//table[@class="nextExpressOrderSKUTable"]//tr/td[2][contains(text(), "{sku}")]'
                                    '/following-sibling::td/span/a[contains(@id, "Quantity_aIncrementTxt")]',
                                )
                            )
                        )
                        self.scroll_and_click_element(plus_quantity_ele)
            else:
                while True:
                    quantity_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                '//input[@name="ctl00$ctl00$ctl00$cphMain$cphMain$'
                                'cphMain$pdtProduct$atcTabbed$txtQuantity"]',
                            )
                        )
                    )
                    quantity = quantity_ele.get_attribute("value")

                    if quantity == product["quantity"]:
                        add_to_cart_btn = WebDriverWait(self.driver, self.sleepAmount).until(
                            EC.element_to_be_clickable(
                                (
                                    By.XPATH,
                                    '//input[@name="ctl00$ctl00$ctl00$cphMain$'
                                    'cphMain$cphMain$pdtProduct$atcTabbed$btnAddToCart"]',
                                )
                            )
                        )
                        self.scroll_and_click_element(add_to_cart_btn)
                        time.sleep(2)
                        self.wait_cart_action()
                        break
                    else:
                        plus_quantity_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                            EC.element_to_be_clickable(
                                (
                                    By.XPATH,
                                    '//a[@id="ctl00_ctl00_ctl00_cphMain_cphMain_cph'
                                    'Main_pdtProduct_atcTabbed_aIncrementATCTxt"]',
                                )
                            )
                        )
                        self.scroll_and_click_element(plus_quantity_ele)
        print("edge_endo/add_to_cart done")

    @sync_to_async
    def clear_cart(self):
        try:
            self.driver.get("https://store.edgeendo.com/storefront.aspx")
            clear_cart_ele = WebDriverWait(self.driver, self.sleepAmount).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        '//a[@id="ctl00_ctl00_ctl00_cphMain_ctl00_ctrShoppingCart_lbRemoveAll"]',
                    )
                )
            )
            self.scroll_and_click_element(clear_cart_ele)
            WebDriverWait(self.driver, self.sleepAmount).until(EC.alert_is_present())
            self.driver.switch_to.alert.accept()
            time.sleep(3)
            print("edge_endo/clear_cart Done")
        except TimeoutException:
            pass

    @sync_to_async
    def checkout(self):
        checkoutBtn = None
        try:
            checkoutBtn = self.driver.find_element(
                By.XPATH, '//input[contains(@name, "$cphMain$ctl00$btnCheckOutBottom")]'
            )
        except NoSuchElementException:
            pass

        if not checkoutBtn:
            self.driver.get("https://store.edgeendo.com/storefront.aspx")
            checkoutBtn = WebDriverWait(self.driver, self.sleepAmount * 2).until(
                EC.element_to_be_clickable((By.XPATH, '//input[contains(@name, "$cphMain$ctl00$btnCheckOutBottom")]'))
            )
        self.scroll_and_click_element(checkoutBtn)
        continueBtn = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//input[contains(@name, "$cphMain$uplUpsell$btnClose")]'))
        )
        self.scroll_and_click_element(continueBtn)
        time.sleep(1.5)
        print("edge_endo/checkout done")

    @sync_to_async
    def secure_payment(self):
        securepaymentBtn = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//input[contains(@name, "$cphMain$dbSubmit$btnSubmit")]'))
        )
        self.scroll_and_click_element(securepaymentBtn)
        time.sleep(1)
        print("edge_endo/secure_payment done")

    @sync_to_async
    def real_order(self):
        shipping_address_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//td[@class="nextInvoiceShipToAddress"]'))
        )
        shipping_address = self.textParser(shipping_address_ele)
        print("Shpping Address:\n", shipping_address)

        billing_address_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//span[contains(@id, "adBillTo_spnAddressDisplay")]'))
        )
        billing_address = self.textParser(billing_address_ele)
        print("Billing Address:\n", billing_address)

        subtotal_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//td[contains(@id, "sctrShipToOrder_tdSubtotalPrice")]'))
        )
        subtotal = convert_string_to_price(self.textParser(subtotal_ele))
        print("Subtotal:\n", subtotal)

        tax_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//td[contains(@id, "sctrShipToOrder_tdSalesTaxPrice")]'))
        )
        tax = convert_string_to_price(self.textParser(tax_ele))
        print("Tax:\n", tax)

        shipping_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//td[contains(@id, "sctrShipToOrder_tdShippingPrice")]'))
        )
        shipping = convert_string_to_price(self.textParser(shipping_ele))
        print("Shipping:\n", shipping)

        order_total_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//td[contains(@id, "sctrShipToOrder_tdTotalPrice")]'))
        )
        order_total = convert_string_to_price(self.textParser(order_total_ele))
        print("Order Total:\n", order_total)

        # payment option
        invoice_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//tr[@id="ctl00_cphMain_piInformation_trInvoicePay"]//label'))
        )
        self.scroll_and_click_element(invoice_ele)

        submitBtn = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.element_to_be_clickable((By.XPATH, '//input[contains(@name, "$cphMain$dbOrderSubmit$btnSubmit")]'))
        )
        self.scroll_and_click_element(submitBtn)

        # order number
        ordernum_ele = WebDriverWait(self.driver, self.sleepAmount).until(
            EC.presence_of_element_located((By.XPATH, '//p[@class="nextOrderConfirmationText"]/b[1]'))
        )
        orderNumber = ordernum_ele.get_attribute("textContent")
        print("Order Number:", orderNumber)

        return shipping_address, shipping, tax, subtotal, order_total, orderNumber

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("edge_endo/create_order")
        try:
            await asyncio.sleep(0.3)
            raise Exception()
        except Exception:
            print("edge_endo/create_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": "",
                "total_amount": Decimal(subtotal_manual),
                "reduction_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
            }
        vendor_slug: str = self.vendor.slug
        return {
            vendor_slug: {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            },
        }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("edge_endo/confirm_order")
        try:
            await self.login()
            await self.clear_cart()
            await self.add_to_cart(products)
            await self.checkout()

            if fake:
                vendor_order_detail = {
                    "retail_amount": "",
                    "savings_amount": "",
                    "subtotal_amount": "50.84",
                    "shipping_amount": "0.00",
                    "tax_amount": "3.43",
                    "total_amount": "54.27",
                    "payment_method": "",
                    "shipping_address": "Alexandra KantorColumbine Creek Dentistry",
                }
                return {
                    **vendor_order_detail,
                    "order_id": f"{uuid.uuid4()}",
                }
            await self.secure_payment()
            shipping_address, shipping, tax, subtotal, order_total, orderNumber = await self.real_order()

            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": subtotal,
                "shipping_amount": shipping,
                "tax_amount": tax,
                "total_amount": order_total,
                "payment_method": "",
                "shipping_address": shipping_address,
            }
            return {
                **vendor_order_detail,
                "order_id": orderNumber,
                "order_type": msgs.ORDER_TYPE_ORDO,
            }
        except Exception:
            print("edge_endo/confirm_order except")
            subtotal_manual = sum([prod["price"] * prod["quantity"] for prod in products])
            vendor_order_detail = {
                "retail_amount": "",
                "savings_amount": "",
                "subtotal_amount": Decimal(subtotal_manual),
                "shipping_amount": 0,
                "tax_amount": "",
                "total_amount": Decimal(subtotal_manual),
                "reduction_amount": Decimal(subtotal_manual),
                "payment_method": "",
                "shipping_address": "",
                "order_id": f"{uuid.uuid4()}",
                "order_type": msgs.ORDER_TYPE_PROCESSING,
            }
            return {
                **vendor_order_detail,
                **self.vendor.to_dict(),
            }

    async def extract_info_from_invoice_page(self, invoice_page_dom: Selector) -> InvoiceInfo:
        # parsing invoice address
        address_dom = invoice_page_dom.xpath("//table[@id='icItem_rptInvoice_ctl00_tblMain']/tr[2]/td")
        shipping_address = address_dom[0].xpath(".//tr[2]/td[2]/text()").extract()
        billing_address = address_dom[1].xpath(".//tr[2]/td[2]/text()").extract()
        address = InvoiceAddress(
            shipping_address=concatenate_list_as_string(shipping_address),
            billing_address=concatenate_list_as_string(billing_address),
        )

        # parsing products
        invoice_products = invoice_page_dom.xpath(
            "//table[@id='icItem_rptInvoice_ctl00_tblMain']/following-sibling::table[1]//tr"
        )
        products: List[InvoiceProduct] = []
        order_amounts = []
        for invoice_product in invoice_products[1:]:
            parts = invoice_product.xpath(".//td")
            if len(parts) == 5:
                products.append(
                    InvoiceProduct(
                        product_url="",
                        product_name=concatenate_list_as_string(parts[2].xpath(".//text()").extract()),
                        quantity=int(strip_whitespaces(parts[0].xpath(".//text()").get())),
                        unit_price=convert_string_to_price(parts[3].xpath(".//text()").get()),
                    )
                )
            else:
                order_amounts.append(convert_string_to_price(parts[-1].xpath(".//text()").get()))

        # parsing order detail
        order_detail_dom = invoice_page_dom.xpath("//table[@id='icItem_rptInvoice_ctl00_tblMain']/tr[1]/td[2]//tr")
        order_id = strip_whitespaces(order_detail_dom[2].xpath("./td/text()").get())
        order_date = strip_whitespaces(order_detail_dom[1].xpath("./td/text()").get())
        payment_method = strip_whitespaces(order_detail_dom[3].xpath("./td/text()").get())
        order_detail = InvoiceOrderDetail(
            order_id=order_id,
            order_date=datetime.datetime.strptime(order_date, "%m/%d/%Y").date(),
            payment_method=payment_method,
            total_items=sum([p.quantity for p in products]),
            sub_total_amount=order_amounts[0],
            shipping_amount=order_amounts[1],
            tax_amount=order_amounts[2],
            total_amount=order_amounts[3],
        )

        return InvoiceInfo(
            address=address,
            order_detail=order_detail,
            products=products,
            vendor=InvoiceVendorInfo(name="Edge Endo", logo="https://cdn.joinordo.com/vendors/edge_endo.png"),
        )

    async def download_invoice(self, **kwargs) -> InvoiceFile:
        if order_id := kwargs.get("order_id"):
            kwargs.setdefault("invoice_link", f"https://store.edgeendo.com/accountinvoice.aspx?RowID={order_id}")
        return await super().download_invoice(**kwargs)
