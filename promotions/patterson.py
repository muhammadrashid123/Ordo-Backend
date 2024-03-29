import json
import logging
import re
import time
from urllib.parse import urlencode

from django.utils import timezone
from scrapy import Selector

from apps.orders.models import Product
from apps.vendor_clients.headers.patterson import (
    HOME_HEADERS,
    LOGIN_HEADERS,
    LOGIN_HOOK_HEADER,
    LOGIN_HOOK_HEADER2,
    PRE_LOGIN_HEADERS,
)
from promotions.base import SpiderBase
from promotions.exceptions import VendorSiteNotAvailableError

logger = logging.getLogger()


class PattersonSpider(SpiderBase):
    vendor_slug = "patterson"
    baseItem = {"product_id": "", "name": "", "url": "", "images": "", "price": "", "promo": "", "FreeGood": ""}
    headers = HOME_HEADERS

    def textParser(self, element):
        if not element:
            return ""
        text = re.sub(r"\s+", " ", " ".join(element.xpath(".//text()").extract()))
        return text.strip() if text else ""

    def login(self):
        response = self.session.get("https://www.pattersondental.com/", headers=HOME_HEADERS)

        response = self.session.get(
            "https://www.pattersondental.com/Account?returnUrl=%2F&signIn=userSignIn", headers=PRE_LOGIN_HEADERS
        )
        if not response.ok:
            raise VendorSiteNotAvailableError()
        login_page_link = response.url

        settings_content = response.text.split("var SETTINGS")[1].split(";")[0].strip(" =")
        settings = json.loads(settings_content)
        csrf = settings.get("csrf", "")
        transId = settings.get("transId", "")
        policy = settings.get("hosts", {}).get("policy", "")
        diag = {"pageViewId": settings.get("pageViewId", ""), "pageId": "CombinedSigninAndSignup", "trace": []}

        headers = LOGIN_HEADERS.copy()
        headers["Referer"] = login_page_link
        headers["X-CSRF-TOKEN"] = csrf

        params = (
            ("tx", transId),
            ("p", policy),
        )

        data = {"signInName": "Info@ColumbineCreekdentistry.com", "password": "Happy16!", "request_type": "RESPONSE"}

        url = (
            "https://pattersonb2c.b2clogin.com/pattersonb2c.onmicrosoft.com/"
            "B2C_1A_PRODUCTION_Dental_SignInWithPwReset/SelfAsserted?" + urlencode(params)
        )
        response = self.session.post(url, headers=headers, data=data)

        headers = LOGIN_HOOK_HEADER.copy()
        headers["Referer"] = login_page_link

        params = (
            ("tx", transId),
            ("p", policy),
            ("rememberMe", "false"),
            ("csrf_token", csrf),
            ("diag", urlencode(diag)),
        )

        url = (
            "https://pattersonb2c.b2clogin.com/pattersonb2c.onmicrosoft.com/"
            "B2C_1A_PRODUCTION_Dental_SignInWithPwReset/api/CombinedSigninAndSignup/confirmed?" + urlencode(params)
        )
        response = self.session.get(url, headers=headers)

        dom = Selector(text=response.text)
        state = dom.xpath('//input[@name="state"]/@value').get()
        code = dom.xpath('//input[@name="code"]/@value').get()
        id_token = dom.xpath('//input[@name="id_token"]/@value').get()

        data = {
            "state": state,
            "code": code,
            "id_token": id_token,
        }

        response = self.session.post(
            url="https://www.pattersondental.com/Account/LogOnPostProcessing/", headers=LOGIN_HOOK_HEADER2, data=data
        )
        response = self.session.get(
            url="https://www.pattersondental.com/supplies/deals", headers=HOME_HEADERS, data=data
        )
        return response

    def run(self):
        response = self.login()
        return self.parse_products(Selector(text=response.text))

    def parse_products(self, response):
        results = []
        for product in response.xpath(
            '//table[@aria-label="Search Results Table"]//tr//div[@ng-controller="SearchResultsController"]'
        ):
            product_link = (
                "https://www.pattersondental.com"
                + product.xpath(
                    './div[contains(@class, "listViewDescriptionWrapper")]//a[@class="itemTitleDescription"]/@href'
                ).get()
            )
            if "ProductFamilyDetails" in product_link:
                self.parse_family_products(product_link)
            else:
                item = self.baseItem.copy()
                item["product_id"] = product.xpath('.//input[@name="AddToCart"]/@data-objectid').get()
                item["name"] = self.textParser(
                    product.xpath(
                        './div[contains(@class, "listViewDescriptionWrapper")]//a[@class="itemTitleDescription"]'
                    )
                )
                item["url"] = product_link
                images = product.xpath('./div[contains(@class, "listViewImageWrapper")]/img/@src').extract()
                item["images"] = ";".join(images)

                promo_ele = product.xpath(
                    './/span[@class="itemIcons"]/a/span[contains(@data-icontype, "manufacturerPromotionIcon")]'
                )
                if promo_ele:
                    promo_text = self.parse_promo_text(promo_ele)
                    if promo_text:
                        item["promo"] = promo_text

                freegood_ele = product.xpath(
                    './/span[@class="itemIcons"]/a/span[contains(@data-icontype, "autoFreeGoodIcon")]'
                )
                if freegood_ele:
                    freegood_text = self.parse_promo_text(freegood_ele)
                    if freegood_text:
                        item["FreeGood"] = freegood_text

                resp = self.session.get(product_link, headers=self.headers)
                response = Selector(text=resp.text)
                item_data = json.loads(response.xpath('//input[@name="ItemSkuDetail"]/@value').get())
                item["price"] = item_data.get("ItemPrice", 0)
                results.append(item)

        next_page = response.xpath('//ul[@class="pagination"]//a[@aria-label="Next"]/@href').get()

        if next_page:
            link = f"https://www.pattersondental.com{next_page}"
            next_response = self.session.get(link, headers=self.headers)
            next_results = self.parse_products(Selector(text=next_response.text))
            results.extend(next_results)
        return results

    def parse_family_products(self, family_link):
        resp = self.session.get(family_link, headers=self.headers)
        response = Selector(text=resp.text)
        product_name = self.textParser(response.xpath('//div[@id="productFamilyDescriptionHeader"]/h1'))
        for product in response.xpath('//div[@id="productFamilyDetailsGridBody"]'):
            item = self.baseItem.copy()
            item["product_id"] = product.xpath('.//input[@name="checkAllChildQty"]/@value').get()
            item["name"] = product_name + " - " + self.textParser(product.xpath('.//a[@class="itemTitleDescription"]'))
            item["url"] = (
                "https://www.pattersondental.com" + product.xpath('.//a[@class="itemTitleDescription"]/@href').get()
            )
            images = product.xpath(
                './/div[@id="productFamilyDetailsGridBodyColumnOneInnerRowImages"]//img/@src'
            ).extract()
            item["images"] = ";".join(images)

            promo_ele = product.xpath(
                './/span[@class="itemIcons"]/a/span[contains(@class, "manufacturerPromotionIcon")]'
            )
            if promo_ele:
                promo_text = promo_ele.xpath("./@data-title").get()
                if promo_text:
                    item["promo"] = promo_text.strip()

            freegood_ele = product.xpath('.//span[@class="itemIcons"]/a/span[contains(@class, "autoFreeGoodIcon")]')
            if freegood_ele:
                freegood_text = freegood_ele.xpath("./@data-title").get()
                if freegood_text:
                    item["FreeGood"] = freegood_text.strip()

            price = product.xpath('.//div[contains(@class, "productFamilyDetailsPriceBreak")][1]//text()').get()
            if "/" in price:
                item["price"] = price.split("/")[0].strip()
            print(item)

    def parse_promo_text(self, ele):
        productfamilykey = ele.xpath("./@data-productfamilykey").get()
        icontype = ele.xpath("./@data-icontype").get()

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,pt;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Referer": "https://www.pattersondental.com/supplies/deals",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)\
                 Chrome/100.0.4896.75 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

        params = {
            "ProductFamilyKey": productfamilykey,
            "IconType": icontype,
            "_": str(int(time.time() * 1000)),
        }

        response = self.session.get(
            "https://www.pattersondental.com/ItemIcons/GetPromotionIconText", headers=headers, params=params
        )
        return response.json()["title"]

    def update_products(self, data):
        current_time = timezone.localtime()
        to_update = []
        for product_info in data:
            logger.debug("Processing %s", product_info)
            product_id = product_info["product_id"]
            for p in Product.objects.filter(vendor__slug=self.vendor_slug, product_id=product_id):
                logger.info("Updating product %s %s", p.id, p.product_id)
                p.promotion_description = product_info["promo"]
                p.price_expiration = current_time
                to_update.append(p)
        Product.objects.bulk_update(to_update, fields=("promotion_description", "price_expiration"))
        logger.info("Total updated: %s", len(to_update))


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    spider = PattersonSpider()
    data = spider().run()
    spider().update_products(data)
