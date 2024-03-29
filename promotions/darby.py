import logging
import re

from scrapy import Selector

from promotions.base import SpiderBase

logger = logging.getLogger(__name__)


class DarbySpider(SpiderBase):
    vendor_slug = "darby"
    baseItem = {
        "product_id": "",
        "name": "",
        "url": "",
        "images": "",
        "price": "",
        "promo": "",
        "category": "",
    }

    def textParser(self, element):
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""

    def run(self):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

        response = self.session.get(
            "https://www.darbydental.com/scripts/productListView.aspx?&filter=Promotions&filterval=T", headers=headers
        )
        return self.parse_products(Selector(text=response.text), 0, {}, "")

    def parse_products(self, response, page, data, form_link):
        items = []
        for product in response.xpath('//div[@id="productContainer"]/div[contains(@id, "MainContent_prodRepeater")]'):
            item = self.baseItem.copy()
            item["name"] = self.textParser(product.xpath('.//div[@class="prod-title"]'))
            item["url"] = (
                "https://www.darbydental.com" + product.xpath('.//div[contains(@class, "card-body")]/a/@href').get()
            )
            item["product_id"] = self.textParser(product.xpath('.//div[@class="prodno"]//label[@itemprop="sku"]'))
            item["images"] = ";".join(
                product.xpath('.//div[@class="box-nopromo"]/img[@class="card-img-top"]/@src').extract()
            )

            items.append(self.parse_product(item))

        headers = {
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-MicrosoftAjax": "Delta=true",
            "sec-ch-ua-platform": '"Windows"',
            "Accept": "*/*",
            "Origin": "https://www.darbydental.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.darbydental.com/categories/Acrylics",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
        }

        if page == 0:
            form_link = response.xpath("//form/@action").get()
            form_link = "https://www.darbydental.com/scripts" + form_link.strip(".")

            data = {
                "ctl00$masterSM": "ctl00$MainContent$UpdatePanel1|ctl00$MainContent$pagelinkNext",
                "__EVENTTARGET": "ctl00$MainContent$pagelinkNext",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "__ASYNCPOST": "true",
                "ctl00$MainContent$currentPage": str(page),
            }

            for ele in response.xpath("//input[@name]"):
                _key = ele.xpath("./@name").get()
                _val = ele.xpath("./@value").get()
                if _val is None:
                    _val = ""
                if _key not in data:
                    if _key not in [
                        "ctl00$logonControl$btnLogin",
                        "ctl00$logonControl$btnSignUp",
                        "ctl00$btnBigSearch",
                    ]:
                        data[_key] = _val

            for ele in response.xpath("//select[@name]"):
                _key = ele.xpath("./@name").get()
                _val = ele.xpath('./option[@selected="selected"]/@value').get()
                if not _val:
                    _val = ele.xpath("./option[1]/@value").get()
                if _key not in data:
                    data[_key] = _val

        else:
            data["ctl00$MainContent$currentPage"] = str(page)

        page_count = data["ctl00$MainContent$pageCount"]
        if page < int(page_count) - 1:
            logger.info("Getting page %s products", page)
            next_response = self.session.post(form_link, data=data, headers=headers)
            next_items = self.parse_products(Selector(text=next_response.text), page + 1, data, form_link)
            items.extend(next_items)
        return items

    def parse_product(self, item):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

        response = self.session.get(item["url"], headers=headers)
        resp_dom = Selector(text=response.text)
        promo_table = self.textParser(resp_dom.xpath('//span[@id="MainContent_lblPromoOffer"]'))
        promo_table_dom = Selector(text=promo_table)
        promo_text = "\n".join(promo_table_dom.xpath("//tr//text()").extract()).strip()
        item["promo"] = promo_text
        return item


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    print(DarbySpider().run())
