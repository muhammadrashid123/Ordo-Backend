import gzip
import json
import logging
import pathlib
import shutil
import tempfile
import uuid

import boto3
from django.conf import settings
from django.utils import timezone

from apps.slack.bot import HISTORY_FETCHING_CHANNEL_ID, notify

from .traced_session import TracedSession

logger = logging.getLogger(__name__)


s3 = boto3.client("s3")


def upload_traced_session(session: TracedSession, context=None):
    try:
        har = session.trace.generate_har()
    except BaseException:
        logger.exception("Error generating HAR")
        return

    td = tempfile.mkdtemp()
    tempdir = pathlib.Path(td)
    if context:
        operation_id = context["operation_id"]
    else:
        operation_id = str(uuid.uuid4())

    try:
        base_name = f"{settings.STAGE}-{operation_id}.har.gz"
        harfile = str(tempdir / base_name)
        with gzip.open(harfile, "wt", encoding="utf-8") as f:
            json.dump(har, f)
        folder_name = timezone.now().date().isoformat()
        object_name = f"{folder_name}/{base_name}"
        s3.upload_file(harfile, settings.HAR_RECORDINGS_BUCKET_NAME, object_name)
    except BaseException:
        logger.exception("Error saving and uploading HAR to S3 bucket")
        return
    else:
        shutil.rmtree(td)
    url = f"https://{settings.HAR_RECORDINGS_BUCKET_NAME}.s3.amazonaws.com/{object_name}"
    return url


def upload_and_notify_vendor_order_session(session: TracedSession, context=None):
    vendor_order_id = context["vendor_order_id"]
    print(f"Uploading ======   {vendor_order_id} to")
    url = upload_traced_session(session, context={"operation_id": vendor_order_id})
    print("url =====", url)
    if not url:
        return

    try:
        notify_text = f"Vendor order {vendor_order_id} exchange has been recorded\nDownload HAR <{url}|here>"
        print("notify_text ", notify_text)
        notify(text=notify_text)
    except BaseException:
        logger.exception("Error sending slack notification")


def upload_and_notify_order_fetch_session(session: TracedSession, context=None):
    vendor_slug = context["vendor_slug"]
    office_id = context["office_id"]
    office_name = context["office_name"]
    url = upload_traced_session(session)
    if not url:
        return

    try:
        notify_text = (
            f"Fetching {vendor_slug} order history for office {office_name} ({office_id}) exchange has been recorded\n"
            f"Download HAR <{url}|here>"
        )
        notify(channel=HISTORY_FETCHING_CHANNEL_ID, text=notify_text)
    except BaseException:
        logger.exception("Error sending slack notification")
