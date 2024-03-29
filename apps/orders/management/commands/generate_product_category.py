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
        python manage.py generate_product_category \
        --file apps/orders/management/commands/csv/category_mapping.csv \
        --app_model orders.productcategory
        python manage.py loaddata orders_productcategory
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
        categories = df["category"].unique()

        json_data = []
        for i, category in enumerate(categories):
            vendors_categories = df[df["category"] == category]
            vendors_categories = (
                vendors_categories.groupby("vendor")["vendor_category"]
                .apply(list)
                .reset_index(name="vendor_categories")
            )
            json_data.append(
                {
                    "model": app_model,
                    "pk": i + 1,
                    "fields": {
                        "name": category,
                        "slug": slugify(category),
                        "vendor_categories": {
                            vendor_categories["vendor"]: [
                                slugify(category) for category in vendor_categories["vendor_categories"]
                            ]
                            for _, vendor_categories in vendors_categories.iterrows()
                        },
                        "description": "",
                    },
                }
            )
        category = "other"
        json_data.append(
            {
                "model": app_model,
                "pk": len(categories) + 1,
                "fields": {
                    "name": category,
                    "slug": slugify(category),
                    "description": "",
                },
            }
        )
        app_model = app_model.replace(".", "_")
        with open(f"{os.path.join(BASE_PATH, app_model)}.json", "w") as f:
            json.dump(json_data, f, indent=4)
