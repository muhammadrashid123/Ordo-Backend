from typing import List

from scrapy import Selector

from apps.common.utils import strip_whitespaces
from promotions.base import SpiderBase
from promotions.headers.midwest_dental import HEADERS
from promotions.schema import PromotionProduct


# TODO: Add Error handling
class MidwestDentalSpider(SpiderBase):
    def run(self) -> List[PromotionProduct]:
        page = 0
        next_page = "https://www.mwdental.com/supplies/close-outs.html"
        products = []
        while True:
            page += 1
            offers_resp = self.session.get(next_page, headers=HEADERS)
            offers_dom = Selector(text=offers_resp.text)
            products_dom = offers_dom.xpath(
                '//div[contains(@class, "listing-type-list")]/div[contains(@class, "listing-item")]'
            )
            for product_dom in products_dom:
                sku_text = strip_whitespaces(
                    product_dom.xpath(
                        './/dl[@class="product-attributes"]'
                        '/dt[contains(text(), "Midwest Item #:")]/following-sibling::dd[1]/text()'
                    ).get()
                )

                product = PromotionProduct(
                    product_id=product_dom.xpath(
                        './/div[@class="addtocart"]//input[contains(@class, "submit-from")]/@id'
                    ).get(),
                    name=strip_whitespaces(product_dom.xpath(".//h5/a/text()").get()),
                    url=product_dom.xpath(".//h5/a/@href").get(),
                    images=product_dom.xpath('.//div[@class="product-image"]//img/@src').extract(),
                    price=strip_whitespaces(
                        product_dom.xpath('.//div[contains(@class, "price-box")]//span[@class="price"]/text()').get()
                    ),
                    promo=product_dom.xpath('.//div[@class="addtocart-tieredprice/text()"]').get(),
                    sku=sku_text.split()[0] if sku_text else None,
                )
                products.append(product)

            next_page = offers_dom.xpath('//td[@class="pages"]/ol/li/a[@class="next"]/@href').get()
            if not next_page:
                break

        return products


if __name__ == "__main__":
    spider = MidwestDentalSpider()
    spider.run()
