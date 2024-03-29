import csv
import logging
import os
import re
from json.decoder import JSONDecodeError

from promotions.base import SpiderBase
from promotions.exceptions import VendorSiteNotAvailableError
from services.utils.retry import retry

logger = logging.getLogger(__name__)


class Net32Spider(SpiderBase):
    vendor_slug = "net_32"
    baseItem = {
        "product_id": "",
        "name": "",
        "url": "",
        "images": "",
        "price": "",
        "promo": "",
    }

    def textParser(self, element):
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""

    @retry((JSONDecodeError, VendorSiteNotAvailableError), max_attempts=2, wait=10, stall=2)
    def get_product(self, page=1):
        headers = {
            "authority": "www.net32.com",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "origin": "https://www.net32.com",
            "referer": "https://www.net32.com/weekly-specials",
            "sec-ch-ua": '"Chromium";v="106", "Google Chrome";v="106", "Not;A=Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36",
        }

        json_data = {
            "searchParam": "",
            "page": page,
            "resultsPerPage": 60,
            "isUgrIdRequired": False,
            "isBuyGetPage": False,
            "filters": [
                {
                    "field": "availability",
                    "value": "in stock",
                },
                {
                    "field": "weekly_special",
                    "value": "Y",
                },
            ],
            "sorting": [
                {
                    "field": "ga_item_revenue",
                    "direction": "desc",
                },
            ],
            "tag": "",
        }

        response = self.session.post(
            "https://www.net32.com/rest/neo/search/get-search-results", headers=headers, json=json_data
        )
        if response.status_code != 200:
            raise VendorSiteNotAvailableError()
        return response.json()

    def run(self):
        products = []
        next_page = 1
        while True:
            product_response = self.get_product(next_page)
            logger.debug(next_page, len(product_response["productDetails"]))
            products += product_response["productDetails"]

            next_page = product_response["pagination"]["nextPage"]
            if not next_page:
                break

        return self.parse_products(products)

    def parse_products(self, products):
        items = []
        for product in products:
            item = self.baseItem.copy()
            item["product_id"] = product["mp_id"]
            item["name"] = product["name"]
            item["url"] = "https://www.net32.com" + product["url"]
            item["images"] = "https://www.net32.com/" + product["thumbnailImageUrl"]
            item["price"] = product["bestPrice"]
            if not item["price"]:
                item["price"] = product["price"]
            if not item["price"]:
                item["price"] = product["msrp"]

            items.append(item)
        return items

    def write_csv(self, item):
        file_exists = os.path.exists(f"./promotions/{self.vendor_slug}.csv")
        with open(f"./promotions/{self.vendor_slug}.csv", "a", encoding="utf-8-sig", newline="") as result_f:
            fieldnames = item.keys()
            writer = csv.DictWriter(result_f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(item)


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    print(Net32Spider().run())
