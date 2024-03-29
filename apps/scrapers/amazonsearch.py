import re

from requests import Session
from scrapy import Selector

session = Session()

SEARCH_HEADERS = {
    "authority": "www.amazon.com",
    "rtt": "250",
    "downlink": "10",
    "ect": "4g",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="96", "Google Chrome";v="96"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:80.0) Gecko/20100101 Firefox/80.0"
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "accept-language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
}


class AmazonSearchScraper:
    BASE_URL = "https://www.amazon.com"

    def _search_products(self, query: str, page: int = 1, from_price=None, to_price=None):
        log1 = "query = " + query
        url = f"{self.BASE_URL}/s"
        page_size = 16
        params = {"k": query, "page": page, "ref": "nb_sb_noss", "s": "price-asc-rank"}

        log1 += "ama1=="
        resp = session.get(url, headers=SEARCH_HEADERS, params=params)
        log1 += "ama2 response = " + str(resp.text)
        response_dom = Selector(text=resp.text)

        total_size_str = response_dom.xpath("//span[@data-component-type='s-result-info-bar']//h1//span/text()").get()
        try:
            # total_size_str = total_size_str.split("of", 1)[1]
            # total_size_str = self.remove_thousands_separator(self.extract_amount(total_size_str))
            log1 += "ama3"
            total_size_str = total_size_str.replace(",", "")
            log1 += "ama4"
            total_size_str = re.search(r"(\d+)\s+results", total_size_str).group(1)
            log1 += "ama5"
            total_size = int(total_size_str)
        except (ValueError, AttributeError):
            log1 += "ama6"
            total_size = 0

        products = []
        log1 += "ama7"

        for product_dom in response_dom.xpath(
            '//div[contains(@class, "s-result-list")]/div[contains(@class, "s-result-item")]'
        ):
            product_id = product_dom.xpath("./@data-asin").get()  # asin
            if not product_id:
                continue

            product_name = product_dom.xpath(".//h2//text()").get()
            product_url = product_dom.xpath(".//h2/a/@href").get()
            product_price = product_dom.xpath('.//span[@class="a-price"]/span[@class="a-offscreen"]//text()').get()
            if product_price:
                product_price = product_price.strip("$")
                try:
                    if from_price and float(product_price) < float(from_price):
                        continue
                    if to_price and float(product_price) > float(to_price):
                        continue
                except Exception:
                    # Since searching doesn't work properly in cloud, added this exception just for checking
                    pass
            else:  # Without this case, it causes VauleErroras the field is not a decimal number.
                product_price = 0
            product_image = product_dom.xpath('.//span[@data-component-type="s-product-image"]//img/@src').get()
            log1 += " " + product_name
            products.append(
                {
                    "product_id": product_id,
                    "product_unit": "",
                    "name": product_name,
                    "description": "",
                    "url": f"{self.BASE_URL}{product_url}",
                    "images": [
                        {
                            "image": product_image,
                        }
                    ],
                    "price": product_price,
                    "vendor": "amazon",
                }
            )

        next_page_button = response_dom.xpath(".//a[contains(@class, 's-pagination-next')]")
        last_page = not bool(next_page_button)

        return {
            "vendor_slug": "amazon",
            "total_size": total_size,
            "page": page,
            "page_size": page_size,
            "products": products,
            "last_page": last_page,
            "log": log1,
        }
