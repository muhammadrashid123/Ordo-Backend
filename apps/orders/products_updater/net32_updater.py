import datetime
import logging
from typing import List

from aiohttp import ClientSession
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Vendor
from apps.common.utils import batched
from apps.orders.models import Product
from services.api_client import Net32APIClient
from services.api_client.vendor_api_types import Net32ProductInfo

BATCH_SIZE = 200


async def update_net32_products():
    """
    Fetch Full products from Net32 using API
    - Enable or disable products in the table
    - Update prices if not updated since yesterday.
    """
    async with ClientSession() as session:
        client = Net32APIClient(session)
        logging.info("Getting full product list")
        products_from_api: List[Net32ProductInfo] = await client.get_full_products()

        await enable_or_disable_products(products_from_api)
        await update_prices(products_from_api)


async def enable_or_disable_products(products_from_api: List[Net32ProductInfo]):
    net_32_vendor_id = (await Vendor.objects.aget(slug="net_32")).id
    all_products = [
        o
        async for o in Product.objects.filter(vendor_id=net_32_vendor_id).values_list(
            "product_id", "is_available_on_vendor"
        )
    ]
    available_product_ids = {product_id for product_id, available in all_products if available}
    unavailable_product_ids = {product_id for product_id, available in all_products if not available}
    all_product_ids = {product_id for product_id, _ in all_products}

    available_product_ids_from_api = set(product.mp_id for product in products_from_api)

    product_ids_to_be_disabled = available_product_ids - available_product_ids_from_api
    product_ids_to_be_enabled = unavailable_product_ids & available_product_ids_from_api
    product_ids_to_be_created = available_product_ids_from_api - all_product_ids

    logging.info(
        "To disable = %s, to enable = %s, to_create = %s",
        len(product_ids_to_be_disabled),
        len(product_ids_to_be_enabled),
        len(product_ids_to_be_created),
    )

    for batch in batched(product_ids_to_be_disabled, BATCH_SIZE):
        logging.debug("Disabling %s", batch)
        await Product.objects.filter(product_id__in=batch).aupdate(
            is_available_on_vendor=False, updated_at=timezone.localtime()
        )

    for batch in batched(product_ids_to_be_enabled, BATCH_SIZE):
        logging.debug("Enabling %s", batch)
        await Product.objects.filter(product_id__in=batch).aupdate(
            is_available_on_vendor=True, updated_at=timezone.localtime()
        )

    updated_at = timezone.localtime()
    products_to_be_created = [
        Product(
            vendor_id=net_32_vendor_id,
            product_id=product.mp_id,
            manufacturer_number=product.manufacturer_number,
            name=product.name,
            url=product.url,
            price=product.price,
            last_price_updated=updated_at,
            created_at=updated_at,
            updated_at=updated_at,
        )
        for product in products_from_api
        if product.mp_id in product_ids_to_be_created
    ]

    await Product.objects.abulk_create(products_to_be_created, batch_size=BATCH_SIZE)


async def update_prices(products_from_api: List[Net32ProductInfo]):
    product_prices = {p.mp_id: p.price for p in products_from_api}
    updated_at = timezone.localtime()
    datetime_from = updated_at - datetime.timedelta(days=1)
    product_instances = Product.net32.available_products().filter(
        Q(last_price_updated__lt=datetime_from) | Q(last_price_updated=None)
    )
    async for product_instance in product_instances:
        if product_instance.product_id not in product_prices:
            continue
        product_instance.price = product_prices[product_instance.product_id]
        product_instance.last_price_updated = updated_at
        product_instance.updated_at = updated_at

    await Product.objects.abulk_update(
        product_instances, fields=["price", "last_price_updated", "updated_at"], batch_size=BATCH_SIZE
    )
