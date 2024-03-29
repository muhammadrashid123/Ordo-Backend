import asyncio

import aiohttp
from asgiref.sync import sync_to_async
from django.db.models import Q

from apps.accounts.models import Vendor
from apps.orders.models import Product
from apps.orders.services.product import ProductService
from apps.scrapers.henryschein import HenryScheinScraper


async def main():
    vendor = await Vendor.objects.filter(slug="henry_schein").aget()
    async with aiohttp.ClientSession() as session:
        to_update = []
        async for product in Product.objects.filter(vendor=vendor, parent=None).exclude(
            Q(url__isnull=True) | Q(url="")
        ):
            scraper = HenryScheinScraper(session, vendor)
            result = await scraper.get_product_as_dict(product.id, product.url)
            product.manufacturer_number = result["manufacturer_number"]
            to_update.append(product)

    for product in to_update:
        parent_id = await sync_to_async(ProductService.get_or_create_parent_id)(product)
        product.parent_id = parent_id
    await Product.objects.abulk_update(to_update, fields=("manufacturer_number", "parent_id"))


if __name__ == "__main__":
    asyncio.run(main())
