import logging
from collections import namedtuple
from typing import List, Union

from aiohttp import ClientSession
from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.enums import SupportedVendor
from apps.orders.models import OfficeProduct, Product
from services.api_client import (
    DCDentalAPIClient,
    DentalCityAPIClient,
    DentalCityProduct,
    Net32APIClient,
    Net32Product,
)
from services.api_client.crazy_dental import CrazyDentalAPIClient

logger = logging.getLogger(__name__)

VendorAPIClientMapper = namedtuple(
    "VendorAPIClientMapper",
    (
        "klass",
        "identifier_in_table",
    ),
)

VendorAPIClientMapping = {
    SupportedVendor.DentalCity: {
        "klass": DentalCityAPIClient,
        "kwargs": {
            "auth_key": settings.DENTAL_CITY_AUTH_KEY,
        },
        "product_identifier_name_in_table": "sku",
    },
    SupportedVendor.Net32: {
        "klass": Net32APIClient,
        "product_identifier_name_in_table": "product_id",
    },
    SupportedVendor.DcDental: {
        "klass": DCDentalAPIClient,
        "product_identifier_name_in_table": "product_id",
    },
    SupportedVendor.CrazyDental: {
        "klass": CrazyDentalAPIClient,
        "product_identifier_name_in_table": "product_id",
    },
}
BATCH_SIZE = 5000


async def create_vendor_api_client(vendor_slug: str, session: ClientSession) -> any:
    vendor = SupportedVendor(vendor_slug)
    vendor_api_client_info = VendorAPIClientMapping[vendor]
    api_client_klass = vendor_api_client_info["klass"]
    kwargs = {"session": session}
    if extra_kwargs := vendor_api_client_info.get("kwargs"):
        kwargs.update(extra_kwargs)

    client = api_client_klass(**kwargs)
    return client


async def get_product_status_async(vendor_slug, mp_id):
    async with ClientSession() as session:
        client = await create_vendor_api_client(vendor_slug, session)
        product_status = await client.get_product_status(mp_id=mp_id)
        # await client.close_session()  # Ensure closure of the session
        return product_status


@sync_to_async
def update_products(vendor: SupportedVendor, products: Union[List[DentalCityProduct], List[Net32Product]]):
    """Update the product price in db with data we get from vendor api
    - Net32
    - Dental City: In addition to product price, we update manufacturer promotion
    """
    products_by_identifier = {product.product_identifier: product for product in products}
    update_time = timezone.localtime()
    office_product_instances = []

    vendor_api_client_info = VendorAPIClientMapping[vendor]
    product_identifier_name_in_table = vendor_api_client_info["product_identifier_name_in_table"]
    filters = Q(vendor__slug=vendor.value) & Q(
        **{f"{product_identifier_name_in_table}__in": products_by_identifier.keys()}
    )
    product_instances = Product.objects.filter(filters)
    product_instance_ids = Product.objects.filter(filters).values_list("id", flat=True)
    office_product_instances = OfficeProduct.objects.filter(product_id__in=product_instance_ids).select_related(
        "product"
    )

    manufacturer_promotion_products = []
    mismatch_manufacturer_numbers = []
    no_comparison_products = []
    with transaction.atomic():
        for product_instance in product_instances:
            # update the product price
            product_identifier_in_table = getattr(product_instance, product_identifier_name_in_table)
            vendor_product = products_by_identifier[product_identifier_in_table]
            if vendor.value == "net_32":
                product_status = async_to_sync(get_product_status_async)(
                    vendor_slug=vendor.value, mp_id=product_identifier_in_table
                )
            product_instance.price = vendor_product.price
            product_instance.last_price_updated = update_time
            product_instance.updated_at = update_time
            if vendor.value == "net_32":
                product_instance.product_vendor_status = product_status
            if vendor.value == "dcdental":
                product_instance.product_vendor_status = "Active" if vendor_product.quantity >= 1 else "Unavailable"

            if vendor.value == "crazy_dental":
                print("crazy_dental case ==============", vendor_product)
                product_instance.product_vendor_status = "Active" if vendor_product.quantity >= 1 else "Discontinued"

            product_description = getattr(vendor_product, "product_desc", None)
            if product_description:
                product_instance.vendor_description = product_description

            # In case of dental city and DC Dental, we update manufacturer promotion
            manufacturer_special = getattr(vendor_product, "manufacturer_special", None)
            if manufacturer_special:
                manufacturer_number = getattr(vendor_product, "manufacturer_part_number", None)
                if (
                    manufacturer_number
                    and manufacturer_number.replace("-", "") != product_instance.manufacturer_number
                ):
                    mismatch_manufacturer_numbers.append(vendor_product)
                    continue

                if product_instance.parent_id is None:
                    no_comparison_products.append(vendor_product)
                    continue

                # Avoid loading parent from db, simulate product with id field.
                manufacturer_promotion_product = Product(id=product_instance.parent_id)
                manufacturer_promotion_product.promotion_description = manufacturer_special
                manufacturer_promotion_product.is_special_offer = True
                manufacturer_promotion_product.updated_at = update_time
                manufacturer_promotion_products.append(manufacturer_promotion_product)

        for office_product_instance in office_product_instances:
            logger.info(f"Office Product Updated => {office_product_instance.id}")
            product_identifier_in_table = getattr(office_product_instance.product, product_identifier_name_in_table)
            vendor_product = products_by_identifier[product_identifier_in_table]
            if vendor.value == "net_32":
                product_status = async_to_sync(get_product_status_async)(
                    vendor_slug=vendor.value, mp_id=product_identifier_in_table
                )
            office_product_instance.price = vendor_product.price
            office_product_instance.last_price_updated = update_time
            office_product_instance.updated_at = update_time
            if vendor.value == "net_32":
                office_product_instance.product_vendor_status = product_status
            if vendor.value == "dcdental":
                office_product_instance.product_vendor_status = (
                    "Active" if vendor_product.quantity >= 1 else "Unavailable"
                )

            if vendor.value == "crazy_dental":
                print("crazy_dental case 2 _______ ==============", vendor_product)
                product_instance.product_vendor_status = "Active" if vendor_product.quantity >= 1 else "Discontinued"
        Product.objects.bulk_update(
            manufacturer_promotion_products, fields=("promotion_description", "is_special_offer", "updated_at")
        )
        common_fields = ["price", "last_price_updated", "product_vendor_status", "updated_at"]
        Product.objects.bulk_update(product_instances, fields=common_fields + ["vendor_description"])
        OfficeProduct.objects.bulk_update(office_product_instances, fields=common_fields)

    if mismatch_manufacturer_numbers:
        logger.debug(f"Manufacturer Number Mismatches: {mismatch_manufacturer_numbers}")

    if no_comparison_products:
        logger.debug(f"No pricing comparison: {no_comparison_products}")


async def update_vendor_products_by_api(vendor_slug: str) -> None:
    async with ClientSession() as session:
        vendor = SupportedVendor(vendor_slug)
        client = await create_vendor_api_client(vendor_slug, session)
        products_from_api = await client.get_products()
        products_len = len(products_from_api)

        print("products_len=", products_len)
        for i in range(0, products_len, BATCH_SIZE):
            products_chunk = products_from_api[i : i + BATCH_SIZE]
            await update_products(vendor, products_chunk)
