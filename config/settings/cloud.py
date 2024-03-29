import os

from ..utils import get_bool_config
from . import sentry  # noqa
from .base import *  # noqa

DEBUG = get_bool_config("DEBUG", False)
SITE_URL = os.getenv("SITE_URL", "https://joinordo.com")
EMAIL_HOST = "smtp.mailgun.org"
EMAIL_PORT = 587
EMAIL_HOST_USER = EMAIL_HOST_USER  # noqa
EMAIL_HOST_PASSWORD = EMAIL_HOST_PASSWORD  # noqa
EMAIL_USE_TLS = True

ALLOWED_HOSTS = [
    "ordo-backend-dev-launch.us-east-1.elasticbeanstalk.com",
    "staging.joinordo.com",
    "api.staging.joinordo.com",
    "api.test.joinordo.com",
    "joinordo.com",
    "api.joinordo.com",
    "localhost",
    "127.0.0.1",
    "172.31.93.12",
    "44.215.221.7",
    "34.197.254.198",
]
CSRF_TRUSTED_ORIGINS = ["https://*.joinordo.com"]
CORS_ALLOW_ALL_ORIGINS = True
