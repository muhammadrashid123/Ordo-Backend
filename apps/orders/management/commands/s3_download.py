import asyncio
import os
from pathlib import Path

import aioboto3
from django.core.management import BaseCommand

BASE_PATH = os.path.join(Path(__file__).parent.parent.parent, "fixtures")


class Command(BaseCommand):
    help = "Download csv files from S3"

    def add_arguments(self, parser):
        parser.add_argument("--s3directory", type=str, help="directory name in S3 bucket", default="products")

        parser.add_argument("--fsdirectory", type=str, help="output folder for csv files", default="products")

    async def download_files(self, s3_directory, fs_directory):
        if not os.path.exists(fs_directory):
            os.mkdir(fs_directory)

        session = aioboto3.Session()
        async with session.resource("s3") as s3_resources:
            bucket = await s3_resources.Bucket("cdn.joinordo.com")
            async for s3_object in bucket.objects.filter(Prefix=s3_directory):
                if not s3_object.key.endswith(".csv"):
                    continue

                file_name = s3_object.key.split("/")[-1]
                print(f"Downloading {file_name} from s3...")
                await bucket.download_file(s3_object.key, os.path.join(fs_directory, file_name))

    def handle(self, *args, **options):
        asyncio.run(self.download_files(options["s3directory"], options["fsdirectory"]))
