import logging
import os
import re

from scrapy import Selector

from promotions.base import SpiderBase

USERNAME = "kdg@kantordentalgroup.com"
PASSWORD = "Happy16!"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
)


class SkydentalsupplySpider(SpiderBase):
    vendor_slug = "skydental"
    base_url = "https://www.skydentalsupply.com"
    login_url = "https://www.skydentalsupply.com/index.php"
    cookies = {}

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Host": "www.skydentalsupply.com",
        "Origin": "https://www.skydentalsupply.com",
        "Referer": "https://www.skydentalsupply.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "sec-ch-ua": '"Google Chrome";v="107", "Chromium";v="107", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
    }

    base_item = {
        "product_id": "",
        "name": "",
        "url": "",
        "images": "",
        "price": "",
        "promo": "",
        "category": "",
    }

    def __init__(self):
        super().__init__()
        if os.path.exists(f"{self.vendor_slug}.csv"):
            os.remove(f"{self.vendor_slug}.csv")

    def run(self):
        payload = {
            "DATA[EMAIL]": USERNAME,
            "DATA[PASSWORD1]": PASSWORD,
            "DATA[REMEMBER_ME]": "1",
            "section": "login",
            "ac": "login",
            "ACC_TPY": "CUSTOMERS",
            "userid": "",
            "json": "1",
        }
        response = self.session.post(self.login_url, headers=self.headers, data=payload)

        if not response.ok:
            print("Authentication failed")
            return

        self.cookies = response.cookies.get_dict()

        response = self.session.get(f"{self.base_url}/products", headers=self.headers, cookies=self.cookies)

        return self.parse(Selector(text=response.text))

    def parse(self, response):
        promoted_products = response.xpath('//div[@class="discountline"]')
        results = []
        for product in promoted_products:
            root_element = product.xpath("..")[0]
            product_link = root_element.xpath(".//a/@href").get()
            print(f"===Scraping a product===: {product_link}")
            product_res = self.session.get(product_link, headers=self.headers, cookies=self.cookies)
            if not product_res.ok:
                print(f"Request Error in {product_link}")
                continue
            item = self.parse_product(Selector(text=product_res.text))
            results.append(item)

        next_page = response.xpath('//li[@class="page-item"]/a[contains(text(), "→")]/@href').get()

        if next_page:
            next_res = self.session.get(next_page, headers=self.headers, cookies=self.cookies)
            if not next_res.ok:
                print(f"Next page request error: {next_page}")
                return
            next_results = self.parse(Selector(text=next_res.text))
            results.extend(next_results)
        return results

    def parse_product(self, response):
        script_data = response.xpath('//script[contains(., "_Settings")]//text()').get()

        item = self.base_item.copy()

        name = re.search('name: "(.+?)"', script_data)
        item["name"] = name.group(1) if name else ""

        sku = re.search('sku: "(.+?)"', script_data)
        item["product_id"] = sku.group(1) if sku else ""

        img = re.search('img: "(.+?)"', script_data)
        item["images"] = img.group(1) if img else ""

        category = re.search('category: "(.+?)"', script_data)
        item["category"] = category.group(1) if category else ""

        url = re.search('url: "(.+?)"', script_data)
        item["url"] = url.group(1) if url else ""

        prices = response.xpath(
            '//div[contains(@class, "zoom_properties")]'
            '//span[@class="products__list__item__offer__price__value"]//text()'
        ).getall()
        item["price"] = "".join([i.strip() for i in prices])

        promotions = response.xpath('//div[@class="row"]//div[@class="discountline"]//text()').getall()
        item["promo"] = "\n".join([i.strip() for i in promotions])

        return item


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    print(SkydentalsupplySpider().run())
