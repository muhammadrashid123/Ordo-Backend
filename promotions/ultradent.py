import logging
import re

from django.utils import timezone
from scrapy import Selector

from apps.orders.models import OfficeProduct, Product
from promotions.base import SpiderBase

logger = logging.getLogger()


HEADERS = {
    "authority": "www.ultradent.com",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,\
        */*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "accept-language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, \
        like Gecko) Chrome/100.0.4896.75 Safari/537.36",
}


PROMOCODE_REGEX = re.compile(r"Promo Code: (?P<promo_code>\d+)")

OFFICE_LIMIT_REGEX = re.compile(r"Limit (?P<office_limit>\d+) per office")

SKUS = re.compile(r"Applicable SKUs\s*: (?P<skus>.*)\.")


class UltradentSpider(SpiderBase):
    vendor_slug = "ultradent"
    baseItem = {
        "product_id": "",
        "name": "",
        "url": "",
        "images": "",
        "price": "",
        "promo": "",
    }

    def __init__(self):
        super().__init__()
        self.session.headers = HEADERS

    def textParser(self, element):
        if not element:
            return ""
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""

    def run(self):
        response = self.session.get("https://www.ultradent.com/")
        return self.parse_products(Selector(text=response.text))

    def update_products(self, data):
        products_to_update = []
        # Unsetting promotion information
        # TODO: this looks not very reliable, but I would still like to avoid putting this in a transaction
        #       if we should put promotion information to separate table?
        Product.objects.filter(vendor__slug=self.vendor_slug, promotion_description__isnull=False).update(
            promotion_description=None
        )
        for product_info in data:
            logger.debug("Processing %s", product_info)
            mo = SKUS.search(product_info["promo"])
            if not mo:
                continue
            skus = mo.groupdict()["skus"]
            skus = [f"{item}" for item in skus.replace(" ", "").split(",")]
            logger.info("Updating product with SKUs %s", skus)

            for p in Product.objects.filter(vendor__slug=self.vendor_slug, product_id__in=skus):
                logger.info("Updating product %s sku %s", p.id, p.product_id)
                p.promotion_description = product_info["promo"]
                p.price_expiration = timezone.localtime()
                products_to_update.append(p)
                OfficeProduct.objects.filter(product=p).update(price_expiration=timezone.localtime())
        Product.objects.bulk_update(products_to_update, fields=("promotion_description", "price_expiration"))
        logger.info("Total updated: %s", len(products_to_update))

    def parse_products(self, response):
        result = []

        for product in response.xpath('//div[contains(@class, "promo-wrap")]//li[@class="promo-item"]'):
            item = self.baseItem.copy()
            item["name"] = self.textParser(product.xpath('.//p[@class="product-name"]'))
            item["url"] = "https://www.ultradent.com" + product.xpath("./a[@data-promo-id]/@href").get()
            images = product.xpath('.//span[contains(@class, "thumbnail")]/picture/img/@ data-src').extract()
            item["images"] = ";".join(images)
            item["promo"] = "\n".join(product.xpath('.//p[@class="fine-print"]//text()').extract()).strip()
            result.append(item)

        next_page = response.xpath('//ul[@class="pagination"]//a[@aria-label="Next"]/@href').get()
        if next_page:
            link = f"https://www.ultradentdental.com{next_page}"
            next_response = self.session.get(link)
            next_results = self.parse_products(Selector(text=next_response.text))
            result.extend(next_results)

        return result


def main():
    spider = UltradentSpider()
    data = spider.run()
    spider.update_products(data)


if __name__ == "__main__":
    main()
