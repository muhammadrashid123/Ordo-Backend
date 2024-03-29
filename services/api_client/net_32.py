import asyncio
import re
from decimal import Decimal
from typing import List

from aiohttp.client import ClientSession
from lxml import etree

from services.api_client.vendor_api_types import Net32Product, Net32ProductInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json


def convert_string_to_price(price_string: str) -> Decimal:
    try:
        price = re.search(r"[,\d]+.?\d*", price_string).group(0)
        price = price.replace(",", "")
        return Decimal(price)
    except (KeyError, ValueError, TypeError, IndexError):
        return Decimal("0")


class Net32APIClient:
    def __init__(self, session: ClientSession):
        self.session = session

        # Setup Chrome options
        self.chrome_options = Options()
        
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        language = "en-US"
        
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        self.chrome_options.add_argument("--disable-logging")
        self.chrome_options.add_argument("--log-level=3")
        self.chrome_options.add_argument("--disable-infobars")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--window-size=1366,768")
        self.chrome_options.add_argument(f"--lang={language}")
        self.chrome_options.add_argument("--ignore-ssl-errors=yes")
        self.chrome_options.add_argument("--ignore-certificate-errors")
        self.chrome_options.add_argument("--disable-notifications")
        self.chrome_options.add_argument(f"--user-agent={user_agent}")
        self.chrome_options.add_argument("--mute-audio")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_experimental_option(
            "prefs", {"profile.default_content_setting_values.notifications": 2}
        )

    async def get_products(self) -> List[Net32Product]:
        url = "https://www.net32.com/feeds/feedonomics/dental_delta_products.xml"
        products = []
        async with self.session.get(url) as resp:
            content = await resp.read()
            tree = etree.fromstring(content)
            product_list = tree.findall(".//entry")
            for product_element in product_list:
                products.append(
                    Net32Product(
                        mp_id=product_element.findtext("mp_id"),
                        price=convert_string_to_price(product_element.findtext("price")),
                        inventory_quantity=int(product_element.findtext("inventory_quantity")),
                    )
                )
            return products

    def parse_content(self, content: bytes):
        tree = etree.fromstring(content)
        product_elements = tree.findall(".//entry")
        return [
            Net32ProductInfo(
                mp_id=product_element.findtext(".//mp_id"),
                price=convert_string_to_price(product_element.findtext(".//price")),
                inventory_quantity=int(product_element.findtext(".//inventory_quantity")),
                name=product_element.findtext(".//title"),
                manufacturer_number=product_element.findtext(".//mp_code"),
                category=product_element.findtext(".//category"),
                url=product_element.findtext(".//link"),
                retail_price=convert_string_to_price(product_element.findtext(".//retail_price")),
                availability=product_element.findtext(".//availability"),
            )
            for product_element in product_elements
        ]

    async def get_full_products(self) -> List[Net32ProductInfo]:
        url = "https://www.net32.com/feeds/searchspring_windfall/dental_products.xml"
        async with self.session.get(url) as resp:
            content = await resp.read()
        return self.parse_content(content)
    
    async def get_product_status(self, mp_id):
        loop = asyncio.get_running_loop()
        url = f"https://www.net32.com/rest/neo/pdp/{mp_id}/vendor-options"
        page_source = await loop.run_in_executor(None, lambda: self.get_page_source(url))

        match = re.search(r'<pre style="[^"]*">(.+?)</pre>', page_source, re.DOTALL)

        if match:
            try:
                json_str = match.group(1)
                data = json.loads(json_str)

                if len(data):
                    print("Item found!")
                    return "Active"
            except Exception as e:
                pass
        else:
            print("Item not found")
            return "Discontinued"

        return page_source
        
    def get_page_source(self, url):
        driver = webdriver.Chrome(options=self.chrome_options)
        try:
            driver.get(url)
            return driver.page_source
        finally:
            driver.quit()

async def main():
    async with ClientSession() as session:
        api_client = Net32APIClient(session)
        return await api_client.get_full_products()


if __name__ == "__main__":
    ret = asyncio.run(main())
    print(ret)
