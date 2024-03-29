from typing import Optional

from aiohttp import ClientResponse

from apps.common.utils import convert_string_to_price
from apps.vendor_clients import types
from apps.vendor_clients.headers.amazon import SEARCH_HEADERS
from apps.vendor_clients.sync_clients.base import BaseClient


class AmazonClient(BaseClient):
    VENDOR_SLUG = "amazon"

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        pass

    def check_authenticated(self, response: ClientResponse) -> bool:
        pass

    def search_products(
        self, q: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price"
    ) -> types.ProductSearch:
        page_size = 16
        params = {"k": q, "page": page, "ref": "nb_sb_noss", "s": "price-asc-rank"}

        response_dom = self.get_response_as_dom(
            url="https://www.amazon.com/s",
            headers=SEARCH_HEADERS,
            query_params=params,
        )

        total_search_results_str = response_dom.xpath(
            "//span[@data-component-type='s-result-info-bar']//h1//span/text()"
        ).get()
        try:
            total_search_results = total_search_results_str.split("of", 1)[1]
            total_search_results = convert_string_to_price(total_search_results)
            total_search_results = int(total_search_results)
        except (ValueError, AttributeError):
            total_search_results = 0

        products = []
        for product_dom in response_dom.xpath(
            '//div[contains(@class, "s-result-list")]/div[contains(@class, "s-result-item")]'
        ):
            product_id = product_dom.xpath("./@data-asin").get()  # asin
            if not product_id:
                continue

            product_name = product_dom.xpath(".//h2//text()").get()
            product_url = product_dom.xpath(".//h2/a/@href").get()
            product_price = convert_string_to_price(
                product_dom.xpath('.//span[@class="a-price"]/span[@class="a-offscreen"]//text()').get()
            )

            product_image = product_dom.xpath('.//span[@data-component-type="s-product-image"]//img/@src').get()
            products.append(
                {
                    "vendor": "amazon",
                    "product_id": product_id,
                    "sku": product_id,
                    "name": product_name,
                    "url": f"https://www.amazon.com{product_url}",
                    "images": [product_image],
                    "price": product_price,
                    "category": "",
                    "unit": "",
                }
            )

        next_page_button = response_dom.xpath(".//a[contains(@class, 's-pagination-next')]")
        last_page = not bool(next_page_button)

        return {
            "meta": {
                "vendor_slug": "amazon",
                "total_size": total_search_results,
                "page": page,
                "page_size": page_size,
                "last_page": last_page,
            },
            "products": products,
        }
