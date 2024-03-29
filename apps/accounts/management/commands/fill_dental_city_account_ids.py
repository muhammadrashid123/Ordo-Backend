import asyncio

from aiohttp import ClientSession
from django.core.management import BaseCommand
from django.db.models import Q

from apps.accounts.models import OfficeVendor
from apps.common.enums import SupportedVendor
from apps.scrapers.dental_city import DentalCityScraper


class Command(BaseCommand):
    help = "Fetch account ids from dental city"

    async def fetch_account_ids(self, username_passwords):
        account_ids = []
        async with ClientSession() as session:
            for username, password in username_passwords:
                scraper = DentalCityScraper(
                    session=session,
                    vendor=None,
                    username=username,
                    password=password,
                )
                account_id = await scraper.get_account_id()
                account_ids.append(account_id)
            await asyncio.sleep(1)
        return account_ids

    def add_arguments(self, parser):
        parser.add_argument(
            "--offices",
            type=str,
            help="comma separated string of office ids",
        )

    def handle(self, *args, **options):
        filter = Q(vendor__slug=SupportedVendor.DentalCity.value)
        if options["offices"]:
            office_ids = str(options["offices"]).split(",")
            filter &= Q(office_id__in=office_ids)

        office_vendors = OfficeVendor.objects.filter(filter)
        username_passwords = list(office_vendors.values_list("username", "password"))
        ret = asyncio.run(self.fetch_account_ids(username_passwords))
        for office_vendor, account_id in zip(office_vendors, ret):
            if not isinstance(account_id, str):
                continue
            office_vendor.account_id = account_id

        OfficeVendor.objects.bulk_update(office_vendors, fields=["account_id"])
