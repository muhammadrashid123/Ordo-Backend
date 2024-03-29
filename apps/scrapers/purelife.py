import datetime
from decimal import Decimal
import time
import re
import json
import uuid
import scrapy
import requests
import traceback
import asyncio
from scrapy import Selector
from typing import Dict, List, Optional, Tuple
from http.cookies import SimpleCookie
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from apps.common import messages as msgs
from apps.scrapers.base import Scraper
from apps.scrapers.utils import catch_network, semaphore_coroutine
from apps.scrapers.schema import VendorOrderDetail, Order
from apps.types.orders import CartProduct



class PureLifeScraper(Scraper):

    def __init__(
        self, 
        session: requests.Session(),
        vendor,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ):
        Scraper.__init__(self, session,vendor, username,password)
        self.driver = None
        self.sleepAmount = 10
        self.reqsession = requests.Session()

    
    def textParser(self, element):
        if not element:
            return ''
        text = re.sub(r"\s+", " ", " ".join(element.xpath('.//text()').extract()))
        text = re.sub(u"(\u2018|\u2019)", "'", text)
        return text.strip() if text else ""

    def scroll_and_click_element(self, element: WebElement):
        # self.driver.execute_script("arguments[0].scrollIntoView(false);", element)
        try:
            element.click()
        except:
            self.driver.execute_script("arguments[0].click();", element)
        
        time.sleep(0.5)

    # create web driver
    def set_driver(self):
        try:
            user_agent = "Mozilla/5.0 (Linux; Android 11; CPH2269) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.58 Mobile Safari/537.36"
            capabilities = webdriver.DesiredCapabilities.CHROME.copy()
            capabilities["pageLoadStrategy"] = "eager"
            
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(f'user-agent={user_agent}')
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument('disable-infobars')

            driver = webdriver.Chrome(
                ChromeDriverManager().install(),
                options=chrome_options,
                desired_capabilities=capabilities
            )

            driver.set_window_size(1920, 1080)
            return driver
        except:
            traceback.print_exc()
            self.final_err_msg = "Can not Creat Web Driver."

        return None

    @catch_network
    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> SimpleCookie:
        if username:
            self.username = username
        if password:
            self.password = password
        loop = asyncio.get_event_loop()
        if not self.driver:
            self.driver = await loop.run_in_executor(None,self.set_driver)
        res = await loop.run_in_executor(None,self.login_proc)
        print("login DONE")
        return res

    def login_proc(self):
        retry_count = 5
        for i in range(retry_count):
            print(f'{i+1}/{retry_count} Trying Login...')
            try:
                self.driver.get("https://www.purelifedental.com/shipment/index/shipmentlist/")
                
                WebDriverWait(self.driver, self.sleepAmount*3).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            '//div[@class="field-recaptcha"]/div[contains(@id, "recaptcha")]'
                        )
                    )
                )

                time.sleep(5)
                loginBtn = WebDriverWait(self.driver, self.sleepAmount*3).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//div[@class="login-container"]//button[contains(@class, "login")]'
                        )
                    )
                )

                emailInput = WebDriverWait(self.driver, self.sleepAmount).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//div[@class="login-container"]//input[@name="login[username]"]'
                        )
                    )
                )
                emailInput.clear()
                emailInput.send_keys(self.username)
                time.sleep(0.5)
                
                passInput = WebDriverWait(self.driver, self.sleepAmount).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//div[@class="login-container"]//input[@name="login[password]"]'
                        )
                    )
                )
                passInput.clear()
                passInput.send_keys(self.password)
                time.sleep(0.5)

                self.scroll_and_click_element(loginBtn)
                time.sleep(5)

                WebDriverWait(self.driver, self.sleepAmount).until(
                    EC.url_matches("https://www.purelifedental.com/shipment/index/shipmentlist/")
                )
                for cookie in self.driver.get_cookies():
                    self.reqsession.cookies.set(cookie['name'], cookie['value'])

                self.driver.quit()
                break

            except:
                traceback.print_exc()

    # @catch_network
    async def get_orders(
        self,
        office=None,
        perform_login=False,
        from_date: Optional[datetime.date] = None,
        to_date: Optional[datetime.date] = None,
        completed_order_ids: Optional[List[str]] = None,
    ) -> List[Order]:
        print("purelife/get_orders")
        loop = asyncio.get_event_loop()
        if not self.driver:
            self.driver = await loop.run_in_executor(None,self.set_driver)
        if perform_login:
            await self.login()
        orders = await loop.run_in_executor(None,self.order_history, office)
        return [Order.from_dict(order) for order in orders if isinstance(order, dict)]
        
        

        
    def order_history(self, office):
        orders = []
        try:
            headers = {
                'authority': 'www.purelifedental.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'accept-language': 'en-US,en;q=0.9',
                'referer': 'https://www.purelifedental.com/orderedproducts/customer/',
                'sec-ch-ua': '"Chromium";v="106", "Google Chrome";v="106", "Not;A=Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36',
            }

            history_page_link = "https://www.purelifedental.com/orderedproducts/customer/"
            
            while True:
                order_history_page = self.reqsession.get(history_page_link, headers=headers)
                print(order_history_page.status_code, order_history_page.url)
                if order_history_page.status_code == 200:
                    dom = Selector(text=order_history_page.text)
                    order_rows = dom.xpath(
                        '//table[contains(@class, "table-order-items")]/tbody/tr[@class="shipment-list-data__heading"]'
                    )
                    for order_row in order_rows:
                        order_history = dict()
                        order_history["order_id"] = self.textParser(order_row.xpath('./td[@data-th="Order #"]'))
                        order_history['currency'] = "USD"
                        order_history["order_date"] = self.textParser(order_row.xpath('./td[@data-th="Date"]'))
                        order_history["order_date"] = datetime.datetime.strptime(order_history["order_date"], "%m/%d/%Y").date()
                        order_history["order_detail_link"] = order_row.xpath('./td[@data-th="Web Ref #"]/a/@href').get()
                        order_history["invoice_link"] = order_row.xpath('./td[@data-th="View Invoice"]/a/@href').get()
                        tracking_link = order_row.xpath('./td[@data-th="Tracking #"]//li[1]/a/@href').get()
                        order_history["tracking_link"] = tracking_link
                        order_detail_data = self.parse_order_detail(order_history)
                        if order_detail_data:
                            if office:
                                order_data = Order.from_dict(order_detail_data)
                                asyncio.run(self.save_order_to_db(office, order=order_data))
                            orders.append(order_detail_data)

                    next_page_ele = dom.xpath('//ul[contains(@class, "pages-items")]/li[contains(@class, "pages-item-next")]/a')
                    if next_page_ele:
                        history_page_link = next_page_ele.xpath('./@href').get()
                    else:
                        break
        except Exception as e:
            traceback.print_exc()
        finally:
            return orders

    def parse_order_detail(self, order_history):
        response = self.reqsession.get(order_history["order_detail_link"])
        print(response.status_code, response.url)
        if response.status_code == 200:
            dom = Selector(text=response.text)
            order_history["order_status"] = self.textParser(dom.xpath('//span[@class="order-status"]'))
            order_history["order_retailtotal"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "retail_value")]/td'))
            order_history["sub_total"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "subtotal_after_discount")]/td'))
            if not order_history["sub_total"]:
                order_history["sub_total"] = order_history["order_retailtotal"]
            order_history["order_discount"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "products_discount")]/td'))
            order_history["order_fee"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "shipping")]/td'))
            order_history["total_amount"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "grand_total")]/td'))
            order_history["promo_code"] = self.textParser(dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@class, "coupon_code")]/td'))
            order_history["products"] = list()
            for product_row in dom.xpath('//table[contains(@class, "table-order-items")]//tr[contains(@id, "order-item-row")]'):
                product = {
                    "product": {
                        "product_id": self.textParser(product_row.xpath('./td[@data-th="SKU"]')),
                        "sky": self.textParser(product_row.xpath('./td[@data-th="SKU"]')),
                        "name": self.textParser(product_row.xpath('./td[@data-th="Product Name"]')),
                        "description": "",
                        "url": "",
                        "images": [],
                        "category": "",
                        "price": self.textParser(product_row.xpath('./td[@data-th="Your Price"]')),
                        "status": "",
                        "vendor": self.vendor.to_dict(),
                    },
                    "quantity": self.textParser(product_row.xpath('./td[@data-th="Qty"]/ul[@class="items-qty"]/li[1]')),
                    "unit_price": self.textParser(product_row.xpath('./td[@data-th="Your Price"]')),
                    "status": "",
                }
                product["name"] = self.textParser(product_row.xpath('./td[@data-th="Product Name"]'))
                product["sku"] = self.textParser(product_row.xpath('./td[@data-th="SKU"]'))
                product["qty"] = self.textParser(product_row.xpath('./td[@data-th="Qty"]/ul[@class="items-qty"]/li[1]'))
                product["catalog_price"] = self.textParser(product_row.xpath('./td[@data-th="Catalog Price"]'))
                product["your_price"] = self.textParser(product_row.xpath('./td[@data-th="Your Price"]'))
                product["subtotal"] = self.textParser(product_row.xpath('./td[@data-th="Subtotal"]'))
                order_history["products"].append(product)
        
        return order_history

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        subtotal_manual = sum([prod['price']*prod['quantity'] for prod in products])
        vendor_order_detail =VendorOrderDetail(
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
        
    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        subtotal_manual = sum([prod['price']*prod['quantity'] for prod in products])
        vendor_order_detail =VendorOrderDetail(
            retail_amount=(0),
            savings_amount=(0),
            subtotal_amount=Decimal(subtotal_manual),
            shipping_amount=(0),
            tax_amount=(0),
            total_amount=Decimal(subtotal_manual),
            reduction_amount=Decimal(subtotal_manual),
            payment_method="",
            shipping_address=""
        )
        return {
            **vendor_order_detail.to_dict(),
            **self.vendor.to_dict(),
            "order_id":"invalid",
            "order_type": msgs.ORDER_TYPE_PROCESSING
        }
