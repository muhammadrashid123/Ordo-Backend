import os
from itertools import islice
from pathlib import Path

import pandas as pd
from django.core.management import BaseCommand

from apps.accounts.models import Vendor


class Command(BaseCommand):
    help = "Load vendors from csv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Truncate the table first",
        )

    def handle(self, *args, **options):
        file_path = os.path.join(Path(__file__).parent, "csv/vendors.csv")
        print(f"Reading data from {file_path}")

        if options["refresh"]:
            Vendor.objects.all().delete()

        df = pd.read_csv(file_path)
        batch_size = 100
        vendors = (Vendor(name=row["name"], url=row["url"]) for _, row in df.iterrows())

        i = 0
        while True:
            batch = list(islice(vendors, batch_size))
            if not batch:
                break

            Vendor.objects.bulk_create(batch, batch_size)
            print(f"Loaded {i * batch_size + len(batch)} / {len(df.index)}")
            i += 1
