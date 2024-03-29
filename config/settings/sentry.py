import os

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .version import VERSION

SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "UNKNOWN")
SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    TRACES_SAMPLE_RATES = {"beanstalk": 0.5, "celery": 0.1}
    PROFILE_SAMPLE_RATES = {"beanstalk": 0.2, "celery": 0.1}
    DEFAULT_TRACES_SAMPLE_RATE = 0.1
    DEFAULT_PROFILES_SAMPLE_RATE = 0.1
    traces_sample_rate = TRACES_SAMPLE_RATES.get(SENTRY_ENVIRONMENT, DEFAULT_TRACES_SAMPLE_RATE)
    profiles_sample_rate = PROFILE_SAMPLE_RATES.get(SENTRY_ENVIRONMENT, DEFAULT_PROFILES_SAMPLE_RATE)
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            AsyncioIntegration(),
        ],
        environment=SENTRY_ENVIRONMENT,
        release=VERSION,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=True,
    )
