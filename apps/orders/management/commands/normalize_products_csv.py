import glob
import os
from pathlib import Path

import pandas as pd
from django.core.management import BaseCommand

BASE_PATH = os.path.join(Path(__file__).parent.parent.parent, "fixtures")


class Command(BaseCommand):
    help = "Download csv files from S3"

    def add_arguments(self, parser):
        parser.add_argument("--fsdirectory", type=str, help="output folder for csv files", default="products")

    def normalize_csv(self, fs_directory):
        for file_name in glob.glob(f"{fs_directory}/*.csv"):
            print(f"normalize {file_name}")
            df = pd.read_csv(file_name)
            df = df.drop_duplicates(subset=["product_id"])
            df.to_csv(file_name, index=False)

    def handle(self, *args, **options):
        self.normalize_csv(options["fsdirectory"])
