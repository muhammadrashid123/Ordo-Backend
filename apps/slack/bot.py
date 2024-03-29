import logging
import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
HISTORY_FETCHING_CHANNEL_ID = "C06ABPW6UQY"


logger = logging.getLogger(__name__)


client = WebClient(token=SLACK_BOT_TOKEN)


def notify(channel=None, **kwargs):
    channel = channel or SLACK_CHANNEL_ID
    try:
        client.chat_postMessage(channel=channel, **kwargs)
    except SlackApiError:
        logger.exception("Got slack issue")


def list_channels():
    cl = client.conversations_list()
    print(cl)
