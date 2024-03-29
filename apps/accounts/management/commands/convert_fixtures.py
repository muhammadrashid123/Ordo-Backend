import json
import os
from pathlib import Path

import pandas as pd
from django.core.management import BaseCommand
from slugify import slugify

BASE_PATH = os.path.join(Path(__file__).parent.parent.parent, "fixtures")


class Command(BaseCommand):
    help = "Convert csv data to fixtures"

    def add_arguments(self, parser):
        """
        python manage.py convert_fixtures \
        --file apps/accounts/management/commands/csv/vendors.csv \
        --app_model accounts.vendor
        python manage.py loaddata accounts_vendor
        """
        parser.add_argument(
            "--file",
            type=str,
            help="the path of csv",
        )
        parser.add_argument(
            "--app_model",
            type=str,
            help="name of app.model e.g. account.vendor",
        )

    def handle(self, *args, **options):
        file_path = options.get("file")
        app_model = options.get("app_model")
        print(f"Converting {file_path} into fixture format")

        df = pd.read_csv(file_path)
        df.fillna("", inplace=True)
        json_data = []
        for i, row in df.iterrows():
            shipping_options = row.pop("shipping_options")
            shipping_options = shipping_options.split(";") if shipping_options else []
            json_data.append(
                {
                    "model": app_model,
                    "pk": i + 1,
                    "fields": {
                        "slug": (slug := slugify(row["name"], separator="_")),
                        "logo": f"https://cdn.joinordo.com/vendors/{slug}.jpg",
                        "shipping_options": shipping_options,
                        **row,
                    },
                }
            )
        app_model = app_model.replace(".", "_")
        with open(f"{os.path.join(BASE_PATH, app_model)}.json", "w") as f:
            json.dump(json_data, f, indent=4)
