import asyncio
import datetime
import logging
import random
import time
from asyncio import Queue
from collections import deque
from typing import Deque, Dict, List, Union

from aiohttp import ClientSession
from asgiref.sync import sync_to_async
from django.db.models.functions import Now
from django.utils import timezone

from apps.accounts.models import OfficeVendor, Vendor
from apps.orders.models import OfficeProduct, Product, ProductImage
from apps.orders.types import ProcessResult, ProcessTask, Stats, VendorParams
from apps.vendor_clients.async_clients import BaseClient
from apps.vendor_clients.async_clients.base import (
    EmptyResults,
    PriceInfo,
    ProductPriceUpdateResult,
    TooManyRequests,
)
from apps.vendor_clients.errors import MissingCredentials

logger = logging.getLogger(__name__)


STATUS_UNAVAILABLE = "Unavailable"
STATUS_EXHAUSTED = "Exhausted"
STATUS_ACTIVE = "Active"

BULK_SIZE = 500


INVENTORY_AGE_DEFAULT = datetime.timedelta(days=1)
NONINVENTORY_AGE_DEFAULT = datetime.timedelta(days=2)

DEFAULT_VENDOR_PARAMS = VendorParams(
    inventory_age=datetime.timedelta(days=7), regular_age=datetime.timedelta(days=14), batch_size=1, request_rate=1
)

VENDOR_PARAMS: Dict[str, VendorParams] = {
    "net_32": VendorParams(
        inventory_age=datetime.timedelta(days=1),
        regular_age=datetime.timedelta(days=2),
        batch_size=1,
        request_rate=1.5,
        needs_login=False,
    ),
    "henry_schein": VendorParams(
        inventory_age=datetime.timedelta(days=7),
        regular_age=datetime.timedelta(days=7),
        batch_size=20,
        request_rate=5,
        needs_login=True,
    ),
    "benco": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=20,
        request_rate=5,
        needs_login=True,
    ),
    "darby": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "dental_city": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "patterson": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=1,
        needs_login=True,
    ),
    "pearson": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "edge_endo": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "ultradent": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "midwest_dental": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=1,
        needs_login=True,
    ),
    "safco": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "implant_direct": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=1,
        needs_login=False,
    ),
    "bluesky_bio": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
    "top_glove": VendorParams(
        inventory_age=datetime.timedelta(days=14),
        regular_age=datetime.timedelta(days=14),
        batch_size=1,
        request_rate=5,
        needs_login=True,
    ),
}


def get_vendor_age(v: Vendor, p: Union[Product, OfficeProduct]):
    vendor_params = VENDOR_PARAMS.get(v.slug, DEFAULT_VENDOR_PARAMS)
    if isinstance(p, Product):
        if p.inventory_refs > 0:
            return vendor_params.inventory_age
    if isinstance(p, OfficeProduct):
        if p.is_inventory:
            return vendor_params.inventory_age
    return vendor_params.regular_age


class StatBuffer:
    max_duration = datetime.timedelta(seconds=20)

    def __init__(self):
        self.items: Deque[ProcessResult] = deque()
        self.total_errors = 0
        self.total = 0

    def cleanup(self):
        if not self.items:
            return
        while (self.items[-1].timestamp - self.items[0].timestamp) >= self.max_duration:
            self.pop()

    def add_item(self, item: bool):
        self.items.append(ProcessResult(timezone.localtime(), item))
        if not item:
            self.total_errors += 1
        self.total += 1

    def pop(self):
        if not self.items:
            return
        left = self.items.popleft()
        if not left.success:
            self.total_errors -= 1
        self.total -= 1

    def stats(self):
        self.cleanup()
        if self.items:
            td = self.items[-1].timestamp - self.items[0].timestamp
        else:
            td = datetime.timedelta(0)
        return Stats(
            rate=len(self.items) / td.total_seconds() if td.total_seconds() else None,
            error_rate=self.total_errors / self.total if self.total else None,
            total=self.total,
        )


class Updater:
    attempt_threshold = 3

    def __init__(self, vendor: Vendor, office_id: str = None):
        self.producer_started = asyncio.Event()
        self.vendor = vendor
        self.vendor_params = VENDOR_PARAMS[vendor.slug]
        self.batch_size = self.vendor_params.batch_size
        self.to_process: Queue[ProcessTask] = Queue(maxsize=20)
        self._crendentials = None
        self.statbuffer = StatBuffer()
        self.target_rate = self.vendor_params.request_rate
        self.last_check: float = time.monotonic()
        self.errors = 0
        self.office_id = office_id

    async def get_credentials(self):
        if not self._crendentials:
            qs = OfficeVendor.objects.filter(vendor=self.vendor)
            if self.office_id:
                qs = qs.filter(office_id=self.office_id)
            credentials = await qs.values("username", "password").afirst()
            if not credentials:
                raise MissingCredentials()
            self._crendentials = credentials
        return self._crendentials

    def get_products(self):
        if self.office_id:
            logger.info(f"Fetching Products for office {self.office_id}")
            products = (
                OfficeProduct.objects.select_related("product")
                .filter(office_id=self.office_id, vendor=self.vendor, is_inventory=True)
                .exclude(product_vendor_status__in=(STATUS_EXHAUSTED,))
                .order_by("-is_inventory", "price_expiration")
            )
        else:
            logger.info(f"Office ID not found in the updater, Fetching Products from products table.")
            products = (
                Product.objects.all()
                .with_inventory_refs()
                .filter(vendor=self.vendor, price_expiration__lt=Now())
                .exclude(product_vendor_status__in=(STATUS_EXHAUSTED,))
                .order_by("-_inventory_refs", "price_expiration")
            )
        return list(products[:BULK_SIZE])

    async def producer(self):
        logger.debug("Started producer...")
        products = await sync_to_async(self.get_products)()
        for product in products:
            await self.to_process.put(ProcessTask(product))
            self.producer_started.set()
        else:
            logger.info("No items to work on")
            self.producer_started.set()

    async def process(self, client: BaseClient, tasks: List[ProcessTask]):
        results: List[ProductPriceUpdateResult] = await client.get_batch_product_prices([pt.product for pt in tasks])
        task_mapping = {pt.product.id: pt for pt in tasks}
        for process_result in results:
            product = process_result.product
            if process_result.result.is_ok():
                self.statbuffer.add_item(True)
                await self.update_price(product, process_result.result.value)
            else:
                exc = process_result.result.value
                if isinstance(exc, TooManyRequests):
                    attempt = task_mapping[product.id].attempt + 1
                    self.statbuffer.add_item(False)
                    await self.reschedule(ProcessTask(product, attempt))
                elif isinstance(exc, EmptyResults):
                    logger.debug("Marking product %s as empty", product.id)
                    self.statbuffer.add_item(True)
                    await self.mark_status(product, STATUS_UNAVAILABLE)
                else:
                    attempt = task_mapping[product.id].attempt + 1
                    self.statbuffer.add_item(True)
                    await self.reschedule(ProcessTask(product, attempt))

        if task_mapping.items():
            for _, pt in task_mapping.items():
                await self.mark_status(pt.product, pt.product.product_vendor_status)

    async def reschedule(self, pt: ProcessTask):
        if pt.attempt > self.attempt_threshold:
            logger.warning("Too many attempts updating product %s. Giving up", pt.product.id)
            await self.mark_status(pt.product, STATUS_EXHAUSTED)
        else:
            logger.debug("Rescheduling fetching product price for %s. Attempt #%s", pt.product.id, pt.attempt)
            await self.to_process.put(pt)

    async def mark_status(self, product: Union[Product, OfficeProduct], status: str):
        current_time = timezone.localtime()
        update_fields = {
            "product_vendor_status": status,
            "last_price_updated": current_time,
            "price_expiration": current_time + get_vendor_age(self.vendor, product),
        }
        if isinstance(product, Product):
            await Product.objects.filter(
                pk=product.pk,
            ).aupdate(**update_fields)
            await OfficeProduct.objects.filter(product_id=product.pk).aupdate(**update_fields)
        else:
            await OfficeProduct.objects.filter(id=product.pk).aupdate(**update_fields)

    async def update_price(self, product: Union[Product, OfficeProduct], price_info: PriceInfo):
        update_time = timezone.localtime()
        update_fields = {
            "price": price_info.price,
            "last_price_updated": update_time,
            "product_vendor_status": price_info.product_vendor_status,
            "price_expiration": timezone.localtime() + get_vendor_age(self.vendor, product),
        }
        if isinstance(product, Product):
            logger.debug("Product with old price: ", product.price)
            logger.debug("Updating price for product %s: %s", product.id, price_info)
            data = {"special_price": price_info.special_price, "is_special_offer": price_info.is_special_offer}
            if price_info.sku_code:
                data["sku"] = price_info.sku_code
            product_update_fields = {
                **update_fields,
                "description": price_info.description,
            }
            await Product.objects.filter(pk=product.pk).aupdate(**data, **product_update_fields)
            if price_info.image != '':
                update_image_field = {
                    "image": price_info.image,
                    "updated_at": update_time,
                }
                await ProductImage.objects.filter(product_id=product.pk).aupdate(**update_image_field)
            await OfficeProduct.objects.filter(product_id=product.pk).aupdate(**update_fields)
        elif isinstance(product, OfficeProduct):
            if price_info.image != '':
                update_image_field = {
                    "image": price_info.image,
                    "updated_at": update_time,
                }
                await ProductImage.objects.filter(product_id=product.product_id).aupdate(**update_image_field)
            if price_info.description != '':
                description_update_field = {
                    "description": price_info.description,
                }
                await Product.objects.filter(id=product.product_id).aupdate(**description_update_field)
            await OfficeProduct.objects.filter(id=product.pk).aupdate(**update_fields)

    async def get_batch(self) -> List[ProcessTask]:
        batch = []
        sleeps = 0
        while len(batch) < self.batch_size:
            await asyncio.sleep(random.uniform(0.5, 1.5) / self.target_rate)
            if sleeps > 3 and batch:
                break
            if not self.to_process.empty():
                item = await self.to_process.get()
                batch.append(item)
                sleeps = 0
            else:
                sleeps += 1
        return batch

    async def get_client(self, session):
        credentials = await self.get_credentials()
        logger.debug("Making handler")
        client = BaseClient.make_handler(
            vendor_slug=self.vendor.slug,
            session=session,
            username=credentials["username"],
            password=credentials["password"],
        )
        if self.vendor_params.needs_login:
            await client.login()
        return client
    
    async def process_batch_and_update_stats(self, client, batch):
        try:
            await self.process(client, batch)  # Await the processing to complete
            for _ in batch:
                self.to_process.task_done()
            # Update stats after processing is complete
            stats = self.statbuffer.stats()
            logger.debug("Stats: %s", stats)
            if stats.total > 10 and time.monotonic() - self.last_check > 20:
                if stats.error_rate > 0:
                    self.errors += 1
                    self.target_rate /= 1.05
                else:
                    self.target_rate *= 1 + 0.05 / (self.errors + 1)
                self.last_check = time.monotonic()
                logger.debug("New target rate: %s", self.target_rate)
        except Exception as e:
            logger.exception("Batch processor raised an error: %s", e)

    async def consumer(self, client):
        logger.debug("Started consumer")
        while True:
            batch = await self.get_batch()
            await self.process_batch_and_update_stats(client, batch)

    async def complete(self):
        await self.producer_started.wait()
        await self.to_process.join()

    async def fetch(self):
        logger.debug("Getting credentials")
        async with ClientSession() as session:
            client = await self.get_client(session)
            worker_task = asyncio.create_task(self.consumer(client))
            producer_task = asyncio.create_task(self.producer())
            await self.complete()
            worker_task.cancel()
            producer_task.cancel()


async def fetch_for_vendor(slug, office_id):
    logger.info(f"Fetching {slug} for office {office_id}")
    vendor = await Vendor.objects.aget(slug=slug)
    updater = Updater(vendor=vendor, office_id=office_id)
    await updater.fetch()
