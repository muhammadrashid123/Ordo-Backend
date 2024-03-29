import datetime
import re
from typing import List

from scrapy import Selector

from promotions.base import SpiderBase
from promotions.headers.safco import AJAX_HEADERS, HEADERS
from promotions.schema import PromotionProduct


def same(x):
    return x


def transform_offer_date(offer_date):
    """
    Transform date in form YYYYMMDD to YYYY-MM-DD
    """
    try:
        return datetime.datetime.strptime(offer_date, "%Y%m%d").date().isoformat()
    except (ValueError, TypeError):
        return ""


FIELDS = {
    "offer name": same,
    "offer desc": same,
    "desc": same,
    "offer end date": transform_offer_date,
    "offer additional text": same,
}


# TODO: Add Error handling
class SafcoSpider(SpiderBase):
    def __init__(self):
        super().__init__()
        self._token = self.get_safco_token()

    def run(self) -> List[PromotionProduct]:
        products = []
        initial_products = self.get_initial_products()
        products_count = len(initial_products)
        url = "https://www.safcodental.com/ajax/index.php"
        params = {
            "get": "get_skus_by_classes",
            "isSingle": "false",
            "token": self._token,
        }
        for i in range(0, products_count, 20):
            products_chunk = initial_products[i : i + 20]
            params["classes"] = ",".join([product["item class"] for product in products_chunk])
            response = self.session.get(url, headers=AJAX_HEADERS, params=params)
            products_by_category = response.json()["results"]
            for item in products_by_category:
                promo = "\n".join([transformer(item.get(field_name)) for field_name, transformer in FIELDS.items()])

                products.append(
                    PromotionProduct(
                        product_id=item["item number"],
                        price=item["price"],
                        promo=promo,
                        sku=item["item number"],
                        name=item["title"],
                        url=f"https://www.safcodental.com/catalog/{item['url']}",
                        images=[f"https://cdn.safcodental.com/products/large/{item['item class']}.jpg"],
                    )
                )

        return products

    def get_initial_products(self):
        url = "https://www.safcodental.com/ajax/index.php"
        params = {
            "get": "search",
            "pageType": "landing",
            "withItem": "offer",
            "initialSearch": "true",
            "token": self._token,
        }
        offers_api_resp = self.session.get(url, headers=AJAX_HEADERS, params=params)
        product_results = offers_api_resp.json()["results"]["results"]
        return product_results

    def get_safco_token(self) -> str:
        self.session.get("https://www.safcodental.com/", headers=HEADERS)
        offers_resp = self.session.get(
            "https://www.safcodental.com/search?pageType=landing&withItem=offer", headers=HEADERS
        )
        offers_dom = Selector(text=offers_resp.text)
        script_data = offers_dom.xpath('//script[contains(., "safco_token")]/text()').get()
        safco_token = re.search(r'safco_token ="(.*?)";', script_data).group(1)
        return safco_token


if __name__ == "__main__":
    # import csv
    spider = SafcoSpider()
    items = spider.run()

    # with open("safco.csv", "a", encoding="utf-8", newline="") as result_f:
    #     fieldnames = ["product_id", "sku", "name", "url", "images", "price", "promo"]
    #     writer = csv.DictWriter(result_f, fieldnames=fieldnames)
    #     for item in items:
    #         writer.writerow(item)
