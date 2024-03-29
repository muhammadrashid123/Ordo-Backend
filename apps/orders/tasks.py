import asyncio
import datetime
import logging
import urllib.parse
from asyncio import Semaphore

# from decimal import Decimal
from typing import List, Optional

from aiohttp import ClientSession, ClientTimeout
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone
from slugify import slugify

from apps.accounts.models import CompanyMember, OfficeVendor, Subscription, User
from apps.audit.models import OrderTasks
from apps.common.choices import OrderStatus
from apps.common.elk import _make_elk_link
from apps.common.utils import group_products
from apps.notifications.models import Notification
from apps.orders.helpers import OrderHelper, ProductHelper
from apps.orders.models import Keyword as KeyModel
from apps.orders.models import OfficeCheckoutStatus
from apps.orders.models import OfficeKeyword as OfficeKeyModel
from apps.orders.models import OfficeProduct as OfficeProductModel
from apps.orders.models import Product as ProductModel
from apps.orders.models import ProductCategory
from apps.orders.models import ProductImage as ProductImageModel
from apps.orders.models import VendorOrder as VendorOrderModel
from apps.orders.models import VendorOrderProduct as VendorOrderProductModel
from apps.scrapers.errors import VendorAuthenticationFailed
from apps.scrapers.schema import Product as ProductDataClass
from apps.scrapers.scraper_factory import ScraperFactory
from apps.scrapers.semaphore import fake_semaphore
from apps.slack import bot
from apps.slack.bot import notify
from config.celery import app
from promotions import PROMOTION_MAP

logger = logging.getLogger(__name__)


@app.task
def update_office_cart_status():
    ten_minutes_ago = timezone.localtime() - datetime.timedelta(minutes=10)
    objs = OfficeCheckoutStatus.objects.filter(
        checkout_status=OfficeCheckoutStatus.CHECKOUT_STATUS.IN_PROGRESS,
        order_status=OfficeCheckoutStatus.ORDER_STATUS.COMPLETE,
        updated_at__lt=ten_minutes_ago,
    )
    total_count = objs.count()
    batch_size = 100
    for i in range(0, total_count, batch_size):
        batch_objs = objs[i * batch_size : min((i + 1) * batch_size, total_count)]
        for obj in batch_objs:
            obj.checkout_status = OfficeCheckoutStatus.CHECKOUT_STATUS.COMPLETE
        OfficeCheckoutStatus.objects.bulk_update(batch_objs, ["checkout_status"])


async def get_product_detail(product_id, product_url, office_vendor, vendor) -> ProductDataClass:
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        scraper = ScraperFactory.create_scraper(
            vendor=vendor,
            session=session,
            username=office_vendor.username,
            password=office_vendor.password,
        )
        return await scraper.get_product(product_id, product_url, perform_login=True)


@app.task
def update_product_detail(product_id, product_url, office_id, vendor_id):
    try:
        office_vendor = OfficeVendor.objects.get(office_id=office_id, vendor_id=vendor_id)
    except OfficeVendor.DoesNotExist:
        return

    vendor = office_vendor.vendor

    if ProductModel.objects.filter(vendor=vendor, product_id=product_id, category__isnull=False).exists():
        return

    # get product detail
    product_data = asyncio.run(get_product_detail(product_id, product_url, office_vendor, vendor))

    product_data = product_data.to_dict()
    product_data.pop("product_id", None)
    product_images = product_data.pop("images", [])
    product_category = product_data.pop("category", None)

    # find product category
    if product_category:
        product_category_slug = slugify(product_category[0])
        q = {f"vendor_categories__{vendor.slug}__contains": product_category_slug}
        q = Q(**q)
        product_category = ProductCategory.objects.filter(q).first()

    if not product_category:
        product_category = ProductCategory.objects.filter(slug="other").first()

    product_data["category"] = product_category
    try:
        product = ProductModel.objects.get(vendor=vendor, product_id=product_id)
        product.name = product_data.get("name")
        product.description = product_data.get("description")
        product.url = product_data.get("url")
        product.price = product_data.get("price")
        product.category = product_category
        product.product_unit = product_data.get("product_unit")
        product.save()
    except ProductModel.DoesNotExist:
        product = ProductModel.objects.create(
            vendor=vendor,
            product_id=product_id,
            name=product_data.get("name"),
            description=product_data.get("description"),
            url=product_data.get("url"),
            price=product_data.get("price"),
            category=product_category,
            product_unit=product_data.get("product_unit"),
        )

    # product, _ = ProductModel.objects.get_or_create(
    #     vendor=vendor, product_id=product_id, defaults=product_data
    # )
    for product_image in product_images:
        ProductImageModel.objects.create(
            product=product,
            image=product_image["image"],
        )


async def _search_products(keyword, office_vendors):
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        tasks = []
        for office_vendor in office_vendors:
            scraper = ScraperFactory.create_scraper(
                vendor=office_vendor.vendor,
                session=session,
                username=office_vendor.username,
                password=office_vendor.password,
            )
            tasks.append(scraper.search_products_v2(keyword, office=office_vendor.office))
        return await asyncio.gather(*tasks, return_exceptions=True)


@app.task
def search_and_group_products(keyword, office_id, vendor_ids):
    office_vendors_to_be_searched = list(
        OfficeVendor.objects.select_related("office")
        .select_related("vendor")
        .filter(office_id=office_id, vendor_id__in=vendor_ids)
    )
    keyword = KeyModel.objects.get(keyword=keyword)
    keyword_objs = OfficeKeyModel.objects.filter(keyword=keyword, office_id=office_id, vendor_id__in=vendor_ids)
    for keyword_obj in keyword_objs:
        keyword_obj.task_status = OfficeKeyModel.TaskStatus.IN_PROGRESS
    OfficeKeyModel.objects.bulk_update(keyword_objs, ["task_status"])

    searched_vendors_products = asyncio.run(_search_products(keyword, office_vendors_to_be_searched))

    vendors_products = []
    for keyword_obj, vendor_products in zip(keyword_objs, searched_vendors_products):
        if isinstance(vendor_products, list) and all(
            [isinstance(vendor_product, ProductModel) for vendor_product in vendor_products]
        ):
            keyword_obj.task_status = OfficeKeyModel.TaskStatus.FETCHING_COMPLETE
            vendors_products.append(vendor_products)
        else:
            # TODO: if it fails, we need to retry
            keyword_obj.task_status = OfficeKeyModel.TaskStatus.FAILED

    OfficeKeyModel.objects.bulk_update(keyword_objs, ["task_status"])

    # pricing comparison
    # get other linked vendor products
    other_office_vendors = (
        OfficeVendor.objects.select_related("office")
        .select_related("vendor")
        .filter(Q(office_id=office_id) & ~Q(vendor_id__in=vendor_ids))
    )
    for other_office_vendor in other_office_vendors:
        vendors_products.append(
            ProductModel.objects.filter(
                Q(vendor=other_office_vendor.vendor), (Q(tags=keyword) | Q(name__icontains=keyword.keyword))
            )
        )

    grouped = group_products(vendors_products, model=True)
    if grouped:
        for keyword_obj in keyword_objs:
            keyword_obj.task_status = OfficeKeyModel.TaskStatus.COMPLETE
        OfficeKeyModel.objects.bulk_update(keyword_objs, ["task_status"])


@app.task(priority=3)
def notify_order_creation(vendor_order_ids, approval_needed):
    vendor_orders = VendorOrderModel.objects.filter(id__in=vendor_order_ids)
    total_items = 0
    total_amount = 0
    if not vendor_orders.exists():
        raise Exception("order failed")
    order_date = vendor_orders[0].order_date
    order_created_by = vendor_orders[0].order.created_by
    for vendor_order in vendor_orders:
        total_amount += vendor_order.total_amount
        total_items += vendor_order.total_items

    office = vendor_orders[0].order.office

    products = VendorOrderProductModel.objects.filter(
        vendor_order_id__in=vendor_order_ids, rejected_reason__isnull=True
    ).annotate(total_price=F("unit_price") * F("quantity"))

    # send notification
    if approval_needed:
        user_ids = (
            CompanyMember.objects.select_related("user")
            .filter(
                Q(invite_status=CompanyMember.InviteStatus.INVITE_APPROVED),
                Q(company=office.company),
                Q(role=User.Role.ADMIN),
                (Q(office=office) | Q(office__isnull=True)),
            )
            .values_list("user_id", flat=True)
        )
    else:
        # add products to inventory lists
        product_ids = [product.product.id for product in products]
        office_products = OfficeProductModel.objects.filter(office=office, product__product_id__in=product_ids)
        for office_product in office_products:
            office_product.is_inventory = True
        OfficeProductModel.objects.bulk_update(office_products, ["is_inventory"])

        user_ids = (
            CompanyMember.objects.select_related("user")
            .filter(
                Q(invite_status=CompanyMember.InviteStatus.INVITE_APPROVED),
                Q(company=office.company),
                (Q(office=office) | Q(office__isnull=True)),
            )
            .values_list("user_id", flat=True)
        )

    # TODO: Compare performance above vs below, I guess below is more faster than above
    #  because additional query won't happen in django templates

    # products = (
    #     VendorOrderProductModel.objects.filter(vendor_order__order_id=order_id)
    #     .annotate(total_price=F("unit_price") * F("quantity"))
    #     .values(
    #         "product__images__image",
    #         "product__name",
    #         "product__vendor__name",
    #         "product__vendor__logo",
    #         "quantity",
    #         "unit_price",
    #         "total_price",
    #     )
    # )

    if approval_needed:
        email_template = "order_approval_needed.html"
    else:
        email_template = "order_creation.html"

    vendor_order_ids = ",".join([str(vendor_order.id) for vendor_order in vendor_orders])
    htm_content = render_to_string(
        f"emails/{email_template}",
        {
            "order_created_by": order_created_by,
            "vendors": [vendor_order.vendor.name for vendor_order in vendor_orders],
            "vendor_order_ids": vendor_order_ids,
            "order_date": order_date,
            "total_items": total_items,
            "total_amount": total_amount,
            # "remaining_budget": Decimal(
            #     office.budget.dental_budget - office.budget.dental_spend - total_amount
            # ).quantize(Decimal(10) ** -2),
            "office": office,
            "products": products,
            "SITE_URL": settings.SITE_URL,
        },
    )
    # create notification
    metadata = {
        "vendors": [vendor_order.vendor.name for vendor_order in vendor_orders],
        "order_date": order_date.isoformat(),
        "total_amount": str(total_amount),
    }

    if approval_needed:
        metadata["link"] = f"{settings.SITE_URL}/orders?order_approval_reject={vendor_order_ids}"
    else:
        metadata["link"] = f"{settings.SITE_URL}/orders?view={vendor_order_ids}"
    users = User.objects.filter(id__in=user_ids)

    emails = list(users.values_list("email", flat=True))
    notification = Notification.objects.create(
        root_content_object=vendor_orders[0].order,
        event="OrderApprovalNotification" if approval_needed else "NewOrderNotification",
        metadata=metadata,
    )
    notification.recipients.add(*users)

    send_mail(
        subject="Order approval needed" if approval_needed else "Order Confirmation",
        message="message",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=emails,
        html_message=htm_content,
    )


async def _sync_with_vendor(
    sem: Semaphore,
    session: ClientSession,
    office_vendor: OfficeVendor,
    completed_vendor_order_ids: List[str],
    from_date: Optional[datetime.date],
    to_date: Optional[datetime.date],
):
    scraper = ScraperFactory.create_scraper(
        vendor=office_vendor.vendor,
        session=session,
        username=office_vendor.username,
        password=office_vendor.password,
    )

    if not hasattr(scraper, "get_orders"):
        return

    if not sem:
        sem = fake_semaphore

    async with sem:
        results = await scraper.get_orders(
            office=office_vendor.office,
            perform_login=True,
            from_date=from_date,
            to_date=to_date,
            completed_order_ids=completed_vendor_order_ids,
        )

    return results


@sync_to_async
def get_vendor_orders_id_and_last_processing_order_date(office_vendor):
    vendor_orders = VendorOrderModel.objects.select_related("vendor", "order__office").filter(
        order__office=office_vendor.office,
        vendor=office_vendor.vendor,
    )

    order_id_field = "vendor_order_reference" if office_vendor.vendor.slug == "henry_schein" else "vendor_order_id"
    completed_vendor_order_ids = list(
        vendor_orders.filter(status=OrderStatus.CLOSED).values_list(order_id_field, flat=True)
    )
    return (
        completed_vendor_order_ids,
        vendor_orders.filter(status=OrderStatus.OPEN).order_by("order_date").first(),
    )


async def _sync_with_vendors(office_vendors):
    sem = Semaphore(value=2)
    today = datetime.date.today()
    tasks = []
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        for office_vendor in office_vendors:
            (
                completed_vendor_order_ids,
                last_processing_vendor_order,
            ) = await get_vendor_orders_id_and_last_processing_order_date(office_vendor)
            tasks.append(
                _sync_with_vendor(
                    sem=sem,
                    session=session,
                    office_vendor=office_vendor,
                    completed_vendor_order_ids=completed_vendor_order_ids,
                    from_date=last_processing_vendor_order.order_date if last_processing_vendor_order else None,
                    to_date=today,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        invalid_credentials_office_vendors = [
            result for result in results if type(result) == VendorAuthenticationFailed
        ]

    if invalid_credentials_office_vendors:
        # send email notification
        pass


@app.task
def sync_with_vendors():
    """
    This task is running every day, checking following items
    - check if orders are created on vendor side directly
    - update order status for those created on Ordo
    """
    office_ids = Subscription.actives.select_related("office").values_list("office", flat=True)
    office_vendors = list(OfficeVendor.objects.select_related("office", "vendor").filter(office_id__in=office_ids))
    asyncio.run(_sync_with_vendors(office_vendors))


@app.task
def update_vendor_promotions(vendor_slug):
    spider_class = PROMOTION_MAP[vendor_slug]
    spider = spider_class()
    result = spider.run()
    if hasattr(spider, "update_products") and callable(spider.update_products):
        spider.update_products(result)
    else:
        ProductHelper.import_promotion_products_from_list(result, vendor_slug=vendor_slug)


@app.task
def update_promotions():
    for vendor_slug in PROMOTION_MAP.keys():
        update_vendor_promotions.delay(vendor_slug)


def get_admin_link(vendor_order):
    backend_parts = urllib.parse.urlsplit(settings.SITE_URL)
    stripped = backend_parts._replace(
        path=f"/admin/orders/order/{vendor_order.order_id}/change/", query="", fragment=""
    )
    return urllib.parse.urlunsplit(stripped)


def notify_in_slack(task_id, vendor_order):
    elk_link = _make_elk_link(task_id)
    admin_link = get_admin_link(vendor_order)
    notify_text = (
        f"Order id {vendor_order.id} office={vendor_order.order.office.name}({vendor_order.order.office.id}) "
        f"to be submitted to {vendor_order.vendor.name}({vendor_order.vendor.id}). \n"
        f"Task id is {task_id} \n"
        f"Check on ELK <{elk_link}|here>\n"
        f"View in admin dashboard <{admin_link}|here>"
    )
    bot.notify(text=notify_text)


@app.task(bind=True, priority=0, queue="urgent")
def perform_real_vendor_order(self, vendor_order_id):
    vendor_orders = VendorOrderModel.objects.filter(pk=vendor_order_id).select_related("order__office", "vendor")
    vendor_orders.update(submitted_to_vendor_site=True)
    vendor_order = vendor_orders.first()
    OrderTasks.objects.create(task_id=self.request.id, order_id=vendor_order_id)
    notify_in_slack(self.request.id, vendor_order)
    asyncio.run(
        OrderHelper.perform_orders_in_vendors(
            order_id=vendor_order.order_id,
            vendor_order_ids=[vendor_order_id],
            fake_order=False,
        )
    )


@app.task(bind=True, priority=0, queue="urgent")
def perform_real_order(self, vendor_order_ids):
    # TODO: Remove Logs
    vendor_orders: List[VendorOrderModel] = list(VendorOrderModel.objects.filter(pk__in=vendor_order_ids))
    if not vendor_orders:
        logger.warning("No Vendor Orders found for vendor_order_ids", vendor_order_ids)
    ids_to_submit = []
    for vendor_order in vendor_orders:
        if vendor_order.submitted_to_vendor_site:
            logger.warning("VendorOrder %s is already ordered on site", vendor_order.pk)
        else:
            ids_to_submit.append(vendor_order.id)
    if not ids_to_submit:
        return

    for vendor_order_id in ids_to_submit:
        perform_real_vendor_order.delay(vendor_order_id)


@app.task(priority=9)
def refresh_product_words():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW product_words;")


@app.task(priority=9)
def refresh_price_age():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW price_age;")


@app.task
def test_task():
    logger.error("Error message")
    logger.warning("Warning message")
    logger.info("Info message")
    logger.debug("Debug message")


@app.task
def test_notify(sent_time: str, queue_name: str):
    executed = timezone.now().isoformat()
    text = f"Latency check: queue={queue_name} sent={sent_time} executed={executed}"
    notify(text=text)


def check_latency(queue_name):
    sent_time = timezone.now().isoformat()
    test_notify.apply_async(args=[sent_time, queue_name], queue=queue_name)
