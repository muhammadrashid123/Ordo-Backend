import asyncio
import csv
import logging
import os
import platform
import time
import traceback
from datetime import timedelta
from typing import List, Optional

import pysftp
from aiohttp import ClientSession, ClientTimeout
from celery import states
from celery.exceptions import Ignore
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management import call_command
from django.db import connection
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone

from apps.accounts.constants import GHOST_COMPANY_PERIOD, MONTHS_BACKWARDS
from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import (
    Company,
    CompanyMember,
    CompanyMemberInviteSchedule,
    Office,
    OfficeVendor,
    User,
    Vendor,
)
from apps.accounts.services.offices import OfficeService
from apps.common.elk import _make_elk_link
from apps.common.enums import SupportedVendor
from apps.common.month import Month
from apps.orders.helpers import (
    OfficeProductCategoryHelper,
    OfficeProductHelper,
    OrderHelper,
)
from apps.orders.models import OfficeProductCategory, OrderStatus, VendorOrder
from apps.orders.product_updater import update_vendor_products_by_api
from apps.orders.products_updater.net32_updater import update_net32_products
from apps.orders.updater import fetch_for_vendor
from apps.scrapers.errors import (
    OrderFetchException,
    ScraperException,
    VendorAuthenticationFailed,
)
from apps.slack.bot import HISTORY_FETCHING_CHANNEL_ID, notify
from apps.vendor_clients.async_clients import BaseClient
from apps.vendor_clients.errors import VendorClientException
from config.celery import app
from services.api_client.errors import APIClientError
from services.utils.secrets import get_secret_value

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

UserModel = get_user_model()
logger = logging.getLogger(__name__)


@app.task(priority=0, queue="urgent")
def send_forgot_password_mail(user_id, token):
    user = UserModel.objects.get(pk=user_id)
    htm_content = render_to_string(
        "emails/reset_password.html",
        {
            "TOKEN": token,
            "SITE_URL": os.getenv("FRONTEND_URL"),
        },
    )
    send_mail(
        subject="Password Reset",
        message="message",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=htm_content,
    )


@app.task(priority=0, queue="urgent")
def send_third_timer_relink_mail(email, message, vendor_id):
    try:
        vendor = get_object_or_404(Vendor, pk=vendor_id)

        htm_content = render_to_string(
            "emails/reinvite_failed.html",
            {"message": message, "vendor": vendor.name},
        )
        send_mail(
            subject="Relink Vendor",
            message="message",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=htm_content,
        )
    except Exception as e:
        print("Vendor not found.", e)


@app.task(priority=0, queue="urgent")
def send_welcome_email(user_id):
    try:
        user = UserModel.objects.get(id=user_id)
    except UserModel.DoesNotExist:
        return

    htm_content = render_to_string("emails/welcome.html")
    send_mail(
        subject="Welcome to Ordo!",
        message="message",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=htm_content,
    )


def send_company_member_invite(company_member: CompanyMember):
    htm_content = render_to_string(
        "emails/invite.html",
        {
            "inviter": company_member.invited_by,
            "company": company_member.company,
            "TOKEN": company_member.token,
            "SITE_URL": os.getenv("FRONTEND_URL"),
        },
    )
    send_mail(
        subject="You've been invited to Join Ordo!",
        message="message",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[company_member.email],
        html_message=htm_content,
    )


@app.task(priority=3)
def bulk_send_company_members_invite(company_member_ids: List[int]):
    company_members = CompanyMember.objects.filter(pk__in=company_member_ids)
    for company_member in company_members:
        send_company_member_invite(company_member)


@app.task(priority=3)
def send_scheduled_invites():
    current_time = timezone.now()
    invites = list(
        CompanyMemberInviteSchedule.objects.filter(scheduled__lt=current_time, actual__isnull=True).select_related(
            "company_member"
        )
    )
    to_update = []
    for scheduled_invite in invites:
        try:
            send_company_member_invite(company_member=scheduled_invite.company_member)
        except Exception:
            logger.exception("Failed to send email for %s", scheduled_invite.pk)
        else:
            scheduled_invite.actual = timezone.now()
            to_update.append(scheduled_invite)
        CompanyMemberInviteSchedule.objects.bulk_update(to_update, fields=("actual",))


@app.task(priority=9)
def fetch_vendor_products_prices(office_vendor_id):
    print("fetch_vendor_products_prices")
    office_vendor = OfficeVendor.objects.select_related("office", "vendor").get(id=office_vendor_id)
    asyncio.run(
        OfficeProductHelper.get_all_product_prices_from_vendors(
            office_id=office_vendor.office.id, vendor_slugs=[office_vendor.vendor.slug]
        )
    )
    print("fetch_vendor_products_prices DONE")


@app.task
def auto_relink_failed_vendors():
    office_vendors = OfficeVendor.objects.filter(login_success=False, office__company__is_active=True).select_related(
        "vendor", "office"
    )
    for office_vendor in office_vendors:
        link_vendor.delay(office_vendor.vendor.slug, office_vendor.office_id)


@app.task(bind=True, priority=9)
def update_vendor_products_prices(self, vendor_slug, office_id=None):
    try:
        asyncio.run(fetch_for_vendor(vendor_slug, office_id))
    except (ScraperException, VendorClientException) as e:
        self.update_state(state=states.FAILURE, meta=traceback.format_exc())
        raise Ignore() from e
    else:
        OrderHelper.update_vendor_order_product_price(vendor_slug, office_id)


@app.task(priority=9)
def update_vendor_product_prices_for_all_offices(vendor_slug):
    for ov in OfficeVendor.objects.filter(vendor__slug=vendor_slug, office__company__is_active=True):
        update_vendor_products_prices.delay(vendor_slug, ov.office_id)


@app.task(bind=True, priority=9)
def update_vendor_products_by_api_for_all_offices(self, vendor_slug):
    try:
        asyncio.run(update_vendor_products_by_api(vendor_slug))
        print("================ Done updating product++++++++++++++++++++++++")
    except APIClientError as e:
        print("error updating")
        traceback.print_exc()
        self.update_state(state=states.FAILURE, meta=traceback.format_exc())
        raise Ignore() from e
    OrderHelper.update_vendor_order_product_price(vendor_slug)


@app.task(priority=9)
def task_update_net32_products():
    asyncio.run(update_net32_products())


@app.task(priority=0, queue="urgent")
def link_vendor(vendor_slug: str, office_id: int, consider_recent=False):
    office_vendor = OfficeVendor.objects.filter(vendor__slug=vendor_slug, office=office_id)[:1].get()
    res = asyncio.run(OrderHelper.login_vendor(office_vendor, office_vendor.vendor, vendor_slug))
    if not res:
        raise VendorAuthenticationFailed

    office_vendor.login_success = True
    office_vendor.save()

    link_vendor_proc.delay(vendor_slug, office_id, consider_recent)


@app.task
def link_vendor_proc(vendor_slug: str, office_id: int, consider_recent=False):
    call_command("fill_office_products", office=office_id, vendor=vendor_slug)
    if vendor_slug == SupportedVendor.DentalCity.value:
        call_command("fill_dental_city_account_ids", offices=office_id)
    fetch_order_history.delay(vendor_slug, office_id, consider_recent)


@app.task(bind=True, autoretry_for=(OrderFetchException,), max_retries=3, default_retry_delay=60)
def fetch_order_history(self, vendor_slug, office_id, consider_recent=False):
    """
    NOTE: Passed vendor_slug and office_id as params instead of OfficeVendor object
    to clearly observe task events in the celery flower...
    """
    # Add delay because instance fetching order history makes the auth failure somehow
    time.sleep(10)
    try:
        office = Office.objects.get(pk=office_id)
        if not OfficeProductCategory.objects.filter(office=office_id).exists():
            OfficeProductCategoryHelper.create_categories_from_product_category(office_id)

        office_vendor = OfficeVendor.objects.get(vendor__slug=vendor_slug, office=office_id)

        if not office_vendor.login_success:
            self.update_state(state=states.FAILURE, meta="Cancelled due to failed authentication earlier")
            return

        order_id_field = "vendor_order_reference" if vendor_slug == "henry_schein" else "vendor_order_id"
        completed_order_ids = list(
            VendorOrder.objects.filter(
                vendor=office_vendor.vendor, order__office=office_vendor.office, status=OrderStatus.CLOSED
            ).values_list(order_id_field, flat=True)
        )
        elk_link = _make_elk_link(self.request.id)
    except Exception as e:
        logger.error("Got error in fetch_order_history" + str(e))
    try:
        asyncio.run(
            OrderHelper.fetch_orders_and_update(
                office_vendor=office_vendor,
                completed_order_ids=completed_order_ids,
                consider_recent=consider_recent,
                handler_context={"vendor_slug": vendor_slug, "office_id": office_id, "office_name": office.name},
            )
        )
    except Exception:
        notify(
            channel=HISTORY_FETCHING_CHANNEL_ID,
            text=f"Could not fetch {vendor_slug} order for office {office.name} ({office_id})\n"
            f"Check on ELK <{elk_link}|here>\n",
        )
        raise
    else:
        notify(
            channel=HISTORY_FETCHING_CHANNEL_ID,
            text=f"Successfully fetched {vendor_slug} orders for office {office.name} ({office_id})\n"
            f"Check on ELK <{elk_link}|here>\n",
        )


@app.task(priority=9)
def update_order_history_for_all_offices(vendor_slug):
    office_vendors = OfficeVendor.objects.filter(vendor__slug=vendor_slug, office__company__is_active=True)
    for ov in office_vendors:
        fetch_order_history.delay(vendor_slug, ov.office_id, True)


@app.task
def send_budget_update_notification():
    now_date = timezone.localtime().date()
    current_month = now_date.strftime("%B")
    previous_month = now_date - relativedelta(months=1)
    previous_month = previous_month.strftime("%B")
    offices = Office.objects.select_related("company").all()
    for office in offices:
        company_members = CompanyMember.objects.filter(
            office=office, role=User.Role.ADMIN, invite_status=CompanyMember.InviteStatus.INVITE_APPROVED
        )
        for member in company_members:
            if office.dental_api:
                htm_content = render_to_string(
                    "emails/updated_budget.html",
                    {
                        "SITE_URL": settings.SITE_URL,
                        "first_name": member.user.first_name,
                        "current_month": current_month,
                        "previous_month": previous_month,
                        "adjusted_production": office.budget.adjusted_production,
                        "collections": office.budget.collection,
                        "dental_percentage": office.budget.dental_percentage,
                        "dental_budget": office.budget.dental_budget,
                        "office_percentage": office.budget.office_percentage,
                        "office_budget": office.budget.office_budget,
                    },
                )
                send_mail(
                    subject="Your budget has automatically updated!",
                    message="message",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[member.email],
                    html_message=htm_content,
                )
            else:
                htm_content = render_to_string(
                    "emails/update_budget.html",
                    {"SITE_URL": settings.SITE_URL, "first_name": "Alex"},
                )
                send_mail(
                    subject="It's time to update your budget!",
                    message="message",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[member.email],
                    html_message=htm_content,
                )


@app.task
def update_office_budget():
    OfficeBudgetHelper.update_office_budgets()
    # OfficeBudgetHelper.update_budget_with_previous_month()


#####################################################################################################################
# v2
#####################################################################################################################


async def get_orders_v2(office_vendor, completed_order_ids):
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        vendor = office_vendor.vendor
        client = BaseClient.make_handler(
            vendor_slug=vendor.slug,
            session=session,
            username=office_vendor.username,
            password=office_vendor.password,
        )
        from_date = timezone.localtime().date()
        to_date = from_date - relativedelta(year=1)
        await client.get_orders(from_date=from_date, to_date=to_date, exclude_order_ids=completed_order_ids)


@app.task
def fetch_orders_v2(office_vendor_id):
    """
    this is used for fetching implant orders only, but in the future, we should fetch orders using this
    """

    office_vendor = OfficeVendor.objects.select_related("office", "vendor").get(id=office_vendor_id)

    if not OfficeProductCategory.objects.filter(office=office_vendor.office).exists():
        call_command("fill_office_product_categories", office_ids=[office_vendor.office.id])

    order_id_field = "vendor_order_reference" if office_vendor.vendor.slug == "henry_schein" else "vendor_order_id"

    completed_order_ids = list(
        VendorOrder.objects.filter(
            vendor=office_vendor.vendor, order__office=office_vendor.office, status=OrderStatus.CLOSED
        ).values_list(order_id_field, flat=True)
    )
    asyncio.run(get_orders_v2(office_vendor, completed_order_ids))


@app.task(priority=0, queue="urgent")
def notify_vendor_auth_issue_to_admins(office_vendor_id):
    office_vendor = OfficeVendor.objects.get(pk=office_vendor_id)

    htm_content = render_to_string(
        "emails/vendor_unlink.html",
        {
            "vendor": office_vendor.vendor.name,
        },
    )

    company_member_emails = list(
        CompanyMember.objects.filter(
            office_id=office_vendor.office_id, role=User.Role.ADMIN, user__email__isnull=False
        ).values_list("user__email", flat=True)
    )

    send_mail(
        subject="Vendor authentication failure",
        message="message",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=company_member_emails,
        html_message=htm_content,
    )


@app.task
def generate_csv_for_salesforce():
    """
    NOTE: the logic needs to be updated a bit more.
    But, this is basically create csv file from office table and upload it into SFTP server
    """
    offices = Office.objects.all()

    if not offices.exists():
        # No data accidentally
        return

    office_data = []

    for idx, office in enumerate(offices):
        if idx == 0:
            target_columns = list(office.__dict__.keys())
            target_columns.remove("_state")
            target_columns.remove("company_id")
            target_columns.append("company_name")
            target_columns.append("company_slug")
            target_columns.append("onboarding_step")
            target_columns.append("vendors")
            target_columns.append("email")
            target_columns.append("role")
            target_columns.append("first_name")
            target_columns.append("last_name")
        data = office.__dict__
        data["company_name"] = office.company.name
        data["company_slug"] = office.company.slug
        data["onboarding_step"] = office.company.on_boarding_step
        data["vendors"] = ",".join(office.vendors.values_list("name", flat=True))
        data["created_at"] = data["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        data["updated_at"] = data["updated_at"].strftime("%Y-%m-%d %H:%M:%S")

        company_members = office.companymember_set.all()
        for member in company_members:
            if member.invite_status == CompanyMember.InviteStatus.INVITE_SENT:
                continue
            new_data = data.copy()
            new_data["email"] = member.email
            new_data["role"] = next(label for value, label in User.Role.choices if value == member.user.role)
            new_data["first_name"] = member.user.first_name
            new_data["last_name"] = member.user.last_name
            office_data.append(new_data)

    dict_columns = {i: i.title() for i in target_columns}
    host = os.getenv("SFTP_HOST")
    username = os.getenv("SFTP_USERNAME")
    password = get_secret_value("SFTP_PASSWORD")
    port = os.getenv("SFTP_PORT")
    connection_options = pysftp.CnOpts()
    connection_options.hostkeys = None

    with pysftp.Connection(
        host=host, username=username, password=password, port=int(port), cnopts=connection_options
    ) as sftp:
        with sftp.open(f"/Import/customer_master{timezone.localtime().strftime('%Y%m%d')}.csv", mode="w") as csv_file:
            file_writer = csv.DictWriter(csv_file, fieldnames=dict_columns, extrasaction="ignore")
            file_writer.writerow(dict_columns)
            file_writer.writerows(office_data)


@app.task
def unsubscribe_office(office_id):
    office = Office.objects.get(pk=office_id)
    OfficeService.cancel_subscription(office)


@app.task
def check_non_formula_vendors_login(vendor_slugs):
    for vs in vendor_slugs:
        check_vendor_login_for_all_offices.delay(vs)


@app.task
def check_vendor_login_for_all_offices(vendor_slug):
    office_vendors = OfficeVendor.objects.filter(vendor__slug=vendor_slug, office__company__is_active=True)
    for ov in office_vendors:
        asyncio.run(OrderHelper.login_vendor(ov, ov.vendor))


@app.task
def cleanup_ghosted_companies():
    threshold = timezone.now() - timedelta(days=GHOST_COMPANY_PERIOD)
    removal_companies = Company.objects.get_all_queryset().filter(is_active=False, ghosted__lt=threshold)
    with connection.cursor() as cursor:
        for company_id in removal_companies.values_list("id", flat=True):
            cursor.callproc("erase_company", [company_id])


@app.task
def fill_office_budget_full(office_id: Optional[int] = None, months=MONTHS_BACKWARDS):
    current_month = Month.from_date(timezone.localdate())
    offices = Office.objects.filter(dental_api__isnull=False).select_related("dental_api")
    if office_id:
        offices = offices.filter(pk=office_id)
    for o in offices:
        logger.info("Processing %s", o.name)
        m = current_month - months - 1
        while m < current_month:
            b = OfficeBudgetHelper.get_or_create_budget(office_id=o.pk, month=m + 1)
            if not b.adjusted_production or not b.collection:
                logger.info("Requesting for month %s", m)
                ap, col = OfficeBudgetHelper.load_dental_data(o.dental_api.key, m)
                b.adjusted_production = ap
                b.collection = col
                b.save(update_fields=["adjusted_production", "collection"])
            m += 1
def notyify_for_unlinked_vendor(office_name,vendor_name,reason):
    channel_id = os.getenv('UNLINK_VENDOR_SLACK_CHANNEL_ID')
    site = os.getenv('SITE_URL')
    msg = (f"'{vendor_name}' has been unlinked for office = '{office_name}'.\n"
           f"Portal is {site}.\n"
           f"{reason}")
    notify(channel_id,text=msg)