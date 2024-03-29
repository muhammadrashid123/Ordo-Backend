import asyncio
import json
import os
from collections import defaultdict

from aiohttp import ClientSession, ClientTimeout
from asgiref.sync import sync_to_async
from django.core.management import BaseCommand

from apps.orders.models import Product, ProductImage
from apps.scrapers.ultradent import UltraDentScraper

SEARCH_HEADERS = {
    "authority": "www.ultradent.com",
    "sec-ch-ua": '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
    "accept": "*/*",
    "content-type": "application/json",
    "sec-ch-ua-mobile": "?0",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
    "sec-ch-ua-platform": '"Windows"',
    "origin": "https://www.ultradent.com",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "referer": "https://www.ultradent.com/checkout",
    "accept-language": "en-US,en;q=0.9,ko;q=0.8",
}
SEARCH_VARIABLES = {
    "includeAllSkus": True,
    "withImages": False,
}
SEARCH_QUERY = """
  query Catalog($includeAllSkus: Boolean = true, $withImages: Boolean = false) {
    allProducts(includeAllSkus: $includeAllSkus) {
      sku
      brandName
      productName
      productFamily
      kitName
      url
      isOrderable
      images @include(if: $withImages) {
        source
        __typename
      }
      __typename
    }
  }
"""


class Command(BaseCommand):
    BASE_URL = "https://www.ultradent.com"
    help = "Fetch Ultradent products and store them into a table"

    async def fetch_group_products(self, session, group_url, products_group):
        async with session.get(f"{self.BASE_URL}{group_url}") as resp:
            dom_text = await resp.text()
            products_res = json.loads(
                dom_text.split("window.upi.apps.productpage.ProductModel = ")[1].split(";</script>")[0]
            )
            product_images = {product["id"]: product for product in products_res["skus"]}
            for product in products_group:
                product["images"] = [image["src"] for image in product_images[product["sku"]]["images"]]
                product["price"] = products_res["pricing"][product["sku"]]["customerPrice"]

    async def fetch_products(self):
        username = os.getenv("ULTRADENT_SCHEIN_USERNAME")
        password = os.getenv("ULTRADENT_SCHEIN_PASSWORD")
        async with ClientSession(timeout=ClientTimeout(30)) as session:
            scraper = UltraDentScraper(
                session=session,
                vendor_slug="",
                username=username,
                password=password,
            )
            await scraper.login()
            async with session.post(
                "https://www.ultradent.com/api/ecommerce",
                headers=SEARCH_HEADERS,
                json={"query": SEARCH_QUERY, "variables": SEARCH_VARIABLES},
            ) as resp:
                res = await resp.json()
                products = res["data"]["allProducts"]
                products_groups = defaultdict(list)
                for product in products:
                    products_groups[product["url"]].append(product)

                tasks = (
                    self.fetch_group_products(session, group_url, products_group)
                    for group_url, products_group in products_groups.items()
                )
                await asyncio.gather(*tasks, return_exceptions=True)
        await self.save_products(products_groups)

    @sync_to_async
    def save_products(self, products_groups):
        failed_products = []
        for url, products_group in products_groups.items():
            for product_data in products_group:
                try:
                    product = Product.objects.create(
                        vendor_id=6,  # ultradent
                        product_id=product_data["sku"],
                        name=product_data["kitName"],
                        description="",
                        url=f"{self.BASE_URL}{url}?sku={product_data['sku']}",
                        price=product_data["price"],
                    )
                    for product_image in product_data["images"]:
                        ProductImage.objects.create(product=product, image=product_image)
                except Exception as e:
                    print(e)
                    failed_products.append(product_data)

        if failed_products:
            print(f"Failed products: {len(failed_products)}")
            print(failed_products)

    def handle(self, *args, **options):
        asyncio.run(self.fetch_products())
