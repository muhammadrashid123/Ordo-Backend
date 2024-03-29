import json
import logging
import re

from scrapy import Selector

from promotions.base import SpiderBase

logger = logging.getLogger()


class BencoSpider(SpiderBase):
    vendor_slug = "benco"
    baseItem = {
        "product_id": "",
        "name": "",
        "url": "",
        "images": "",
        "price": "",
        "promo": "",
        "category": "",
    }

    def login(self):
        headers = {
            "Connection": "keep-alive",
            "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Accept-Language": "en-US,en;q=0.9",
        }

        response = self.session.get("https://shop.benco.com/Login/Login", headers=headers, verify=False)
        print(response.url)
        modelJson = (
            response.text.split("id='modelJson'")[1]
            .split("</script>", 1)[0]
            .split(">", 1)[1]
            .replace("&quot;", '"')
            .strip()
        )
        idsrv_xsrf = json.loads(modelJson)["antiForgery"]["value"]
        print(idsrv_xsrf)

        headers = {
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "Origin": "https://identity.benco.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Referer": response.url,
            "Accept-Language": "en-US,en;q=0.9",
        }

        data = {"idsrv.xsrf": idsrv_xsrf, "username": "info@columbinecreekdentistry.com", "password": "Happy16!"}

        response = self.session.post(response.url, headers=headers, data=data, verify=False)
        response_dom = Selector(text=response.text)
        id_token = response_dom.xpath("//input[@name='id_token']/@value").get()
        scope = response_dom.xpath("//input[@name='scope']/@value").get()
        state = response_dom.xpath("//input[@name='state']/@value").get()
        session_state = response_dom.xpath("//input[@name='session_state']/@value").get()

        headers = {
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "Origin": "https://identity.benco.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Referer": "https://identity.benco.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }

        data = {"id_token": id_token, "scope": scope, "state": state, "session_state": session_state}

        response = self.session.post("https://shop.benco.com/signin-oidc", headers=headers, data=data, verify=False)
        print(response.url)
        print(response.status_code)

    def textParser(self, element):
        if element:
            text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
            return text.strip() if text else ""
        return ""

    def run(self):
        self.login()

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
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
            "https://shop.benco.com/Search/SearchBigBigDeals?source=BigBigDealsHeaderLink", headers=headers
        )
        return self.parse_products(Selector(text=response.text))

    def parse_products(self, response):
        product_ids = list()
        products = dict()
        for product in response.xpath(
            '//div[contains(@class, "product-grid")]/div[@class="product-tile"]/'
            'div[contains(@class,"product-tile-content")]'
        ):
            item = self.baseItem.copy()
            item["images"] = product.xpath("./a/div[contains(@class, 'image-div')]/img/@src").get()
            item["name"] = self.textParser(product.xpath("./a/div[contains(@class, 'description')]"))
            item_url = product.xpath("./a/@href").get()
            if item_url:
                item["url"] = "https://shop.benco.com" + item_url.strip()
            item["product_id"] = self.textParser(product.xpath("./a/p"))
            product_ids.append(item["product_id"])
            products[item["product_id"]] = item

        data = {"productNumbers": product_ids, "pricePartialType": "ProductPriceRow"}

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Origin": "https://shop.benco.com",
            "Pragma": "no-cache",
            "Referer": "https://shop.benco.com/Search?q=H4sIAAAAAAAACk2OTUsDMRCG%2F4rMOace97ZucV0QKUa8iIeYHePQ2aRMJvRQ"
            "%2Bt%2BdrkULCSHPfLzPCXYhIXQbBw8hor4Fblihez%2F9%2Fp%2FDYlW4p3R3uVsMXMHB2mb8VexxMFWPjFFxhk4NnT8c"
            "jFLawdNCHGRSXGzppeSgZy7HvmkZiogN%2BfZZlbQplQzdlwVYky9N4jXZzpr7iGFGeaK8dzd01TQH%2F12OL1gba%2B3r"
            "KGQq111Tjtxm3AlFyukf16EsB0bFIYje4BEzSmDfUkIz%2B7M6%2FwD5lpuKLQEAAA%3D%3D",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

        price_response = self.session.post(
            "https://shop.benco.com/Search/GetPricePartialsForProductNumbers", headers=headers, json=data
        )
        self.parse_price(price_response.json(), products)

        # pagination
        next_page_ele = response.xpath('//div[@id="resultsPager"]//input[@value="Next >"]')
        next_page_ele_class = next_page_ele.xpath("./@class").get()
        if "disabled" not in next_page_ele_class:
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Origin": "https://shop.benco.com",
                "Pragma": "no-cache",
                "Referer": "https://shop.benco.com",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36",
                "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }

            data = {}
            for _ele in response.xpath('//div[@id="resultsPager"]//input[@value="Next >"]/../input[@name]'):
                _key = _ele.xpath("./@name").get()
                _val = _ele.xpath("./@value").get()
                if not _val:
                    _val = ""
                data[_key] = _val

            logger.warning("Changing page to %s", data)
            next_response = self.session.post("https://shop.benco.com/Search/ChangePage", headers=headers, data=data)
            next_products = self.parse_products(Selector(text=next_response.text))
            products.update(next_products)
        return products

    def parse_price(self, response, products):
        for id, row in response.items():
            row_dom = Selector(text=row)
            price = self.textParser(row_dom.xpath("//span[@class='selling-price']"))
            if not price:
                price = self.textParser(row_dom.xpath("//h4[@class='selling-price']/span"))

            products[id]["price"] = price

            products[id]["promo"] = self.textParser(
                row_dom.xpath('//div[@class="bulk-discounts"]/span[@class="bulk-discount-quantity"]')
            )


if __name__ == "__main__":
    print(BencoSpider().run())
