import json

from scrapy import Selector

from promotions.base import SpiderBase


class HenrySpider(SpiderBase):
    vendor_slug = "henry_schein"

    def get_offers(self):
        headers = {
            "authority": "www.henryschein.com",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,\
                image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "accept-language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
        }

        response = self.session.get(
            "https://www.henryschein.com/us-en/dental/supplies/featuredoffers.aspx", headers=headers, timeout=10
        )
        return response.text

    def parse_ads(self, response_text):
        ads_text = response_text.split("var mmAds =", 1)[1].split("</script>")[0].strip()
        ads_json = json.loads(ads_text)
        ads = list(ads_json.values())[-1]
        return ads

    def parse_detail(self, link):
        product_ids = list()
        print(link)
        headers = {
            "authority": "www.henryschein.com",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/\
                webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
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
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
        }

        response = self.session.get(link, headers=headers)
        dom = Selector(text=response.text)
        product_ids = dom.xpath('//ol[contains(@class, "products")]/li/@data-product-container').extract()
        if not product_ids:
            order_btns = dom.xpath('//a[contains(text(), "Order Now")]/@href').extract()
            for order_btn in order_btns:
                if order_btn and "productid=" in order_btn:
                    product_ids.extend(order_btn.split("productid=", 1)[1].split("&", 1)[0].split(","))
        print(product_ids)
        return product_ids

    def run(self):
        ads = self.parse_ads(self.get_offers())
        data = list()
        for ad in ads:
            item = dict()
            link = ad["link"]["url"]
            link = link.replace("\u0026", "&")
            item["link"] = f"https://www.henryschein.com{link}"
            if ad["alternatetext"]:
                item["title"] = ad["alternatetext"]
            else:
                item["title"] = ad["subheading"]
            item["description"] = ad["description"]
            if ad["product"]["promocode"]:
                item["promo"] = f'Must use promo code {ad["product"]["promocode"]}. Offer valid until {ad["sunset"]}.'
            else:
                continue

            item["image"] = ad["images"]["extralarge"]
            if not item["image"]:
                item["image"] = ad["images"]["large"]
            if not item["image"]:
                item["image"] = ad["images"]["medium"]
            if not item["image"]:
                item["image"] = ad["images"]["small"]
            if item["image"]:
                item["image"] = f'https://www.henryschein.com{item["image"]}'

            item["ids"] = self.parse_detail(item["link"])

            data.append(item)

        # with open(f'{self.vendor_slug}.json', 'w', encoding='utf-8-sig') as ff:
        #     json.dump(data, ff, indent=2)
        items = []
        for store_promotions in data:
            for product_id in store_promotions["ids"]:
                items.append({"product_id": product_id, "promo": store_promotions["promo"]})
        return items


if __name__ == "__main__":
    print(HenrySpider().run())
